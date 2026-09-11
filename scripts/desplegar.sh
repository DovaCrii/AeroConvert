#!/usr/bin/env bash
#
# Despliega AeroConvert en la VM. Es el `run.ps1` de Linux, y **el orden no es negociable**:
# validar antes de migrar, recolectar los estaticos antes de servir, y esperar a la sonda
# antes de dar el despliegue por bueno.
#
#   git pull && scripts/desplegar.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${AEROCONVERT_HOST:-127.0.0.1}"

if [ ! -f .env ]; then
    echo "Falta .env. Copia .env.example y pon al menos ALLOWED_HOSTS," >&2
    echo "CSRF_TRUSTED_ORIGINS, SECRET_KEY y AEROCONVERT_RAICES_PERMITIDAS." >&2
    exit 1
fi

export DJANGO_SETTINGS_MODULE=config.settings.prod

echo "==> dependencias"
# Del bloqueo y sin las de desarrollo. `--locked` falla si `uv.lock` no cuadra con
# `pyproject.toml`, que es justo lo que se quiere en un servidor: nada se resuelve aqui.
uv sync --locked --no-dev --group despliegue

echo "==> comprobar la configuracion"
# **Antes de tocar la base.** Un .env sin ALLOWED_HOSTS tiene que parar aqui, no despues de
# haber migrado: `manage.py check` dice cual falta y con que ejemplo.
uv run python manage.py check --deploy --fail-level WARNING

echo "==> migraciones"
uv run python manage.py migrate --noinput

echo "==> estaticos"
# **Esto no es opcional, y omitirlo no da un aviso: da un 500 en TODAS las paginas.**
# `prod` corre con DEBUG=False y el almacen con manifiesto de apps/core/estaticos.py; sin
# `staticfiles.json`, la primera etiqueta {% static %} revienta. Ya paso una vez, y
# apps/core/test_arranque.py existe por eso.
uv run python manage.py collectstatic --noinput --clear

echo "==> preajustes de fabrica"
uv run python manage.py sembrar_preajustes

echo "==> servicios"
# El obrero primero: si no arranca, el web sigue sirviendo la version anterior.
sudo systemctl restart aeroconvert-obrero
sudo systemctl restart aeroconvert

echo "==> esperando a /salud/"
# Igual que `run.ps1`, y por el mismo motivo: en un arranque en frio Django tarda mas, y dar
# el despliegue por bueno antes de tiempo esconde el fallo.
listo=""
for _ in $(seq 1 60); do
    sleep 0.5
    if curl -fsS --max-time 2 "http://${HOST}/salud/" 2>/dev/null | grep -q '"estado"'; then
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
curl -fsS "http://${HOST}/salud/" | python3 -m json.tool
