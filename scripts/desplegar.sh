#!/usr/bin/env bash
#
# Despliega AeroConvert en la VM. Es el `run.ps1` de Linux, y **el orden no es negociable**:
# validar antes de migrar, recolectar los estaticos antes de servir, y esperar a la sonda
# antes de dar el despliegue por bueno.
#
#   cd /opt/aeroconvert && sudo -u aeroconvert git pull && scripts/desplegar.sh
#
# ## Lo que este guion aprendio del servidor de verdad
#
# Se escribio para el manual generico y **nunca se habia ejecutado**: la instalacion del
# 2026-09-14 se hizo a mano, orden por orden. Al intentar usarlo el 2026-09-15 fallaba en
# tres sitios a la vez, y los tres estan corregidos aqui:
#
# 1. **Llamaba a `uv` a secas.** En esta maquina vivia en `/home/levdigital01/.local/bin`, que
#    ni esta en el PATH de root ni lo puede leer el usuario del servicio. Ahora se busca, y si
#    no aparece se dice donde ponerlo en vez de fallar con «command not found».
# 2. **Corria todo como quien lo invoca**, o sea root. Eso deja el entorno virtual y los
#    estaticos con dueno root dentro de `/opt/aeroconvert`, que es del usuario `aeroconvert`:
#    el servicio arranca hoy y falla el dia que tenga que escribir algo. Cada orden que toca
#    el arbol va ahora con `sudo -u aeroconvert`; solo `systemctl` va con sudo.
# 3. **Esperaba a `/salud/` en el puerto 80 y sin cabecera `Host`.** Aqui no hay nginx --
#    publica Tailscale-- asi que en el 80 no hay nada, y `ALLOWED_HOSTS` solo acepta el nombre
#    del tailnet: pedirlo a `127.0.0.1` devuelve un 400 en HTML. El guion habria esperado
#    treinta segundos para declarar roto un despliegue correcto.
#
set -euo pipefail
cd "$(dirname "$0")/.."

# Donde escucha gunicorn de verdad. Ver `despliegue/aeroconvert.service`.
HOST="${AEROCONVERT_HOST:-127.0.0.1:8001}"
# El nombre que `ALLOWED_HOSTS` acepta. Sin esto, Django responde 400 a la sonda.
NOMBRE="${AEROCONVERT_NOMBRE:-}"
# Quien es el dueno de `/opt/aeroconvert` y quien corre el servicio.
DUENO="${AEROCONVERT_USUARIO:-aeroconvert}"

if [ ! -f .env ]; then
    echo "Falta .env. Copia .env.example y pon al menos ALLOWED_HOSTS," >&2
    echo "CSRF_TRUSTED_ORIGINS, SECRET_KEY y AEROCONVERT_RAICES_PERMITIDAS." >&2
    exit 1
fi

# **El .env se lee como su dueno, no como quien invoca.**
#
# Es modo 600 y pertenece a `aeroconvert`: lleva la SECRET_KEY, y que solo el la lea es
# deliberado. Un `grep` normal aqui muere con «permission denied» aunque quien lanza el guion
# tenga sudo -- tener sudo no es lo mismo que usarlo.
if [ -z "$NOMBRE" ]; then
    NOMBRE="$(sudo -u "$DUENO" grep -hE '^ALLOWED_HOSTS=' .env 2>/dev/null \
        | head -n1 | cut -d= -f2- | cut -d, -f1 | tr -d ' "'"'"'' || true)"
fi
if [ -z "$NOMBRE" ]; then
    echo "No hay ALLOWED_HOSTS en .env, y sin el la sonda recibe un 400." >&2
    echo "Compruebalo asi, que el fichero solo lo lee su dueno:" >&2
    echo "  sudo -u ${DUENO} grep ALLOWED_HOSTS ${PWD}/.env" >&2
    exit 1
fi

# **`uv` tiene que poder ejecutarlo `aeroconvert`, no quien lanza el guion.**
#
# `command -v uv` a secas encuentra el del PATH de quien invoca, y en esta maquina eso es
# `/home/levdigital01/.local/bin/uv` -- que el usuario del servicio no puede leer porque el
# directorio personal de otra persona no es suyo. Se pasaba esa ruta a `sudo -u aeroconvert`
# y moria con «Permiso denegado» nombrando un fichero que existe y que quien mira si puede
# ejecutar, que es la forma mas confusa posible de decir «este no».
#
# Asi que se prueban las rutas de sistema primero, y **se comprueba como el dueno**: es la
# condicion de verdad, y comprobarla de otra manera es volver a tener el mismo fallo.
UV=""
for candidato in /usr/local/bin/uv /usr/bin/uv "$(command -v uv 2>/dev/null || true)"; do
    [ -n "$candidato" ] || continue
    if sudo -u "$DUENO" test -x "$candidato" 2>/dev/null; then
        UV="$candidato"
        break
    fi
done

if [ -z "$UV" ]; then
    echo "No hay ningun 'uv' que ${DUENO} pueda ejecutar." >&2
    encontrado="$(command -v uv 2>/dev/null || true)"
    if [ -n "$encontrado" ]; then
        echo "El tuyo esta en ${encontrado}, pero ${DUENO} no puede leerlo." >&2
    fi
    echo "Copialo donde lo vean todos los usuarios:" >&2
    echo "  sudo install -m 0755 ${encontrado:-\$HOME/.local/bin/uv} /usr/local/bin/uv" >&2
    exit 1
fi

# `--no-config` porque `uv` busca ficheros de configuracion hacia arriba y en el directorio
# personal, y el usuario del servicio no puede leer el de nadie: sin esto muere con un
# «permission denied» que no menciona que lo que no pudo leer era opcional.
como_dueno() { sudo -u "$DUENO" env DJANGO_SETTINGS_MODULE=config.settings.prod "$@"; }
gestionar() { como_dueno .venv/bin/python manage.py "$@"; }

echo "==> dependencias"
# Del bloqueo y sin las de desarrollo. `--locked` falla si `uv.lock` no cuadra con
# `pyproject.toml`, que es justo lo que se quiere en un servidor: nada se resuelve aqui.
como_dueno VIRTUAL_ENV="$PWD/.venv" UV_PYTHON_INSTALL_DIR=/opt/python \
    "$UV" sync --locked --no-dev --group despliegue --no-config

echo "==> comprobar la configuracion"
# **Antes de tocar la base.** Un .env sin ALLOWED_HOSTS tiene que parar aqui, no despues de
# haber migrado: `manage.py check` dice cual falta y con que ejemplo.
gestionar check --deploy --fail-level WARNING

echo "==> migraciones"
gestionar migrate --noinput

echo "==> estaticos"
# **Esto no es opcional, y omitirlo no da un aviso: da un 500 en TODAS las paginas.**
# `prod` corre con DEBUG=False y el almacen con manifiesto de apps/core/estaticos.py; sin
# `staticfiles.json`, la primera etiqueta {% static %} revienta. Ya paso una vez, y
# apps/core/test_arranque.py existe por eso.
gestionar collectstatic --noinput --clear

echo "==> preajustes de fabrica"
gestionar sembrar_preajustes

# --- La carpeta de respaldos ------------------------------------------------
#
# **Esto era un paso del README y por eso se salto.** El 2026-09-21 se descubrio que el
# servidor llevaba semanas con el temporizador puesto y cero respaldos escritos: la carpeta
# no existia, y systemd **se niega a arrancar** una unidad cuya `ReadWritePaths` no existe.
# Falla en el montaje del espacio de nombres, antes de ejecutar nada, con un `226/NAMESPACE`
# que no menciona la palabra respaldo.
#
# Un paso de una lista que alguien tiene que acordarse de hacer es un paso que un dia no se
# hace. Aqui se hace solo, y es idempotente.
#
# `0700` porque ahi dentro va la bitacora entera de la oficina.
RESPALDOS="/var/backups/aeroconvert"
if [ ! -d "$RESPALDOS" ]; then
    echo "==> creando ${RESPALDOS} (faltaba: el respaldo no podia escribir)"
    sudo install -d -o "$DUENO" -g "$DUENO" -m 0700 "$RESPALDOS"
fi

echo "==> servicios"
# El obrero primero: si no arranca, el web sigue sirviendo la version anterior.
sudo systemctl restart aeroconvert-obrero
sudo systemctl restart aeroconvert

echo "==> esperando a /salud/ (${NOMBRE} en ${HOST})"
# Igual que `run.ps1`, y por el mismo motivo: en un arranque en frio Django tarda mas, y dar
# el despliegue por bueno antes de tiempo esconde el fallo.
#
# Las dos cabeceras son obligatorias y no adorno: `Host` porque `ALLOWED_HOSTS` no acepta
# `127.0.0.1`, y `X-Forwarded-Proto` porque `SECURE_SSL_REDIRECT` contesta un 301 a todo lo
# que llega sin TLS -- que es siempre, con Tailscale terminandolo por delante.
sonda() {
    curl -fsS --max-time 3 \
        -H "Host: ${NOMBRE}" -H "X-Forwarded-Proto: https" \
        "http://${HOST}/salud/" 2>/dev/null
}

listo=""
for _ in $(seq 1 60); do
    sleep 0.5
    if sonda | grep -q '"estado"'; then
        listo=1
        break
    fi
done

if [ -z "$listo" ]; then
    echo "No respondio en 30 s. Las ultimas lineas del servicio:" >&2
    journalctl -u aeroconvert -n 40 --no-pager >&2
    exit 1
fi

# Y decir si algo quedo **degradado**, que no es lo mismo que roto: la carpeta compartida sin
# montar, el obrero caido o el disco lleno salen aqui.
echo "==> estado"
sonda | python3 -m json.tool

# El tope de subida, en claro. Es el ajuste que mas veces se ha quedado desfasado entre el
# codigo, el ejemplo y el .env del servidor, y el sintoma es una subida que se corta sin
# decir por que. **Se imprime el valor que de verdad quedo cargado**, no lo que dice ningun
# fichero: el .env manda sobre el codigo, y ahi es donde se ha escondido la discrepancia.
echo "==> tope de subida"
gestionar shell -c 'from django.conf import settings; print(f"{settings.TOPE_MB} MB")'

# **El respaldo, dicho en cada despliegue.**
#
# Es el unico de los tres servicios cuyo fallo no se nota usando la aplicacion: los otros dos
# se caen y alguien lo ve el mismo dia; este se descubre el dia que hace falta el respaldo,
# que es el peor dia posible. Aqui cuesta una linea y sale delante de quien despliega.
echo "==> respaldo"
ultimo=$(find "$RESPALDOS" -maxdepth 1 -name 'aeroconvert-*.sqlite3.gz' -printf '%T@ %p\n' \
    2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
if [ -n "$ultimo" ]; then
    echo "  ultimo: $(basename "$ultimo")"
else
    echo "  NINGUNO todavia. Para probarlo ahora mismo:" >&2
    echo "  sudo systemctl start aeroconvert-respaldo.service" >&2
fi
