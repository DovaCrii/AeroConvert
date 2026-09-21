# Instalar AeroConvert en la VM

Ubuntu, para un equipo pequeño. Los ficheros de esta carpeta se **copian** a `/etc`; el que
se ejecuta desde el repositorio es `scripts/desplegar.sh`.

**El dimensionado está medido, no estimado**: 4 vCPU, 4 GB de RAM, 80 GB SSD. Las cifras y de
dónde salen están en `docs/DEPLOY.md`.

---

## La máquina de la oficina, que no está vacía

Comprobado el **2026-09-14** sobre `p340` (Ubuntu 26.04.1, VM de Hyper-V sobre una
ThinkStation P340). **Ya es el servidor Aero de la oficina**, y AeroConvert es el tercer
inquilino:

| | Cómo corre | Puerto |
| --- | --- | --- |
| **AeroControl** | systemd + `uv run gunicorn`, `/opt/aerocontrol` | 8000 |
| **AeroLink** | Docker compose — API, dos pilotos, PostgreSQL 16, MinIO | 8081, 8090, 8092, 9000, 9001 |
| **AeroConvert** | systemd + `uv run gunicorn`, `/opt/aeroconvert` | **8001** |
| AeroBim | *(previsto)* | 8002 |

Dos cosas que no son como el manual genérico da por hecho:

**No hay nginx, ni caddy, ni traefik.** Quien termina TLS y publica es **Tailscale**, con
Funnel encendido: el sitio es alcanzable **desde todo internet**, no solo desde la red
privada. Es una decisión tomada a propósito —acceso desde terreno— y tiene consecuencias que
están más abajo.

**Y Funnel admite tres puertos: 443, 8443 y 10000.** Eso evita el problema de montar varias
aplicaciones Django bajo prefijos de ruta, que rompe todas las URL generadas:

Comprobado el 2026-09-14, el reparto real —el tailnet es **`tailccd107`**—:

```
https://p340.tailccd107.ts.net            → AeroControl   (127.0.0.1:8000)
https://p340.tailccd107.ts.net/aerolink   → AeroLink      (127.0.0.1:8092)
https://p340.tailccd107.ts.net:8443       → AeroConvert   (127.0.0.1:8001)   ← libre
https://p340.tailccd107.ts.net:10000      → AeroBim, cuando toque
```

Cada una montada en `/`, sin `FORCE_SCRIPT_NAME` y sin reescribir estáticos.

### Publicarlo

```bash
tailscale funnel --bg --https=8443 http://127.0.0.1:8001
tailscale funnel status
```

**Esto no toca lo que ya está publicado.** Cada puerto de Funnel es una entrada
independiente: el 443 de AeroControl sigue igual, y quitar el 8443 mañana
(`tailscale funnel --https=8443 off`) tampoco lo toca.

Y en el `.env`, con el puerto:

```
ALLOWED_HOSTS=p340.tailccd107.ts.net
CSRF_TRUSTED_ORIGINS=https://p340.tailccd107.ts.net:8443
```

**`ALLOWED_HOSTS` sin el puerto y `CSRF_TRUSTED_ORIGINS` con él.** No es un descuido: Django
compara el primero contra el nombre a secas y el segundo contra el origen entero. Puesto al
revés, la pantalla de entrada acepta la contraseña y devuelve 403 al enviar el formulario.

### Lo que cambia por estar en internet abierto

- **El bloqueo por intentos fallidos tiene que funcionar.** Tailscale pone la dirección real
  en `X-Forwarded-For` y `apps/core/ip.py` la lee. Sin eso, todos compartirían `127.0.0.1` y
  ocho equivocaciones de cualquiera dejarían fuera a toda la oficina.
- **Cada entrada y cada intento fallido quedan en el registro**, diciendo si vinieron de
  internet o de la red privada — se distinguen por la cabecera `Tailscale-Funnel-Request`, y
  no hay otra forma de saberlo porque llegan por el mismo puerto.
- **nginx deja de ser opcional y pasa a ser recomendable**, por el límite de peticiones sobre
  la pantalla de entrada. Ver `aeroconvert.nginx.conf`, que trae la trampa de `real_ip`
  explicada.

---

## 1. La máquina

```bash
sudo apt update
sudo apt install -y gdal-bin nginx cifs-utils
```

**Nunca `pip install gdal`**: la rueda de PyPI no trae los controladores que la aplicación
sondea, y la matriz de compatibilidad saldría medio apagada sin decir por qué.

**Dos ausencias en Ubuntu 26.04**, comprobadas el 2026-09-14:

- **`python3.12` no está** — la distribución trae 3.14, y la aplicación pide `>=3.12,<3.13`.
- **`pdal` tampoco está empaquetado.** Sin él las nubes de puntos salen apagadas con su
  motivo escrito, como las dos de Office; el ráster, el vectorial, LandXML y quince de las
  veinte herramientas de documentos funcionan igual. **No bloquea el despliegue.** Si hace
  falta, se trae de conda-forge, que es la vía que no arrastra medio sistema de compilación.

**Y una que sí hay que poner**, porque es barata y desbloquea una herramienta entera
— **puesta en p340 el 2026-09-21**:

```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

Sin ella, «Reconocer el texto de un escaneo» sale apagada y «PDF a Markdown» sigue sin poder
hacer nada con un escaneo. Con ella, las dos funcionan: verificado ese día sobre un escaneo
real, que entró sin texto y salió devolviendo `ACTA DE RECEPCION`. Ver `SERVIDOR.md` para
las otras cuatro apagadas, que son de Microsoft y no tienen arreglo en Linux.

Python lo pone `uv`, pero **fuera de `/home`**:

```bash
sudo mkdir -p /opt/python
sudo env UV_PYTHON_INSTALL_DIR=/opt/python /home/levdigital01/.local/bin/uv python install 3.12
```

**El `/opt` importa.** Las dos unidades llevan `ProtectHome=yes`, así que para el usuario
`aeroconvert` la carpeta `/home` sencillamente no existe. Un entorno virtual creado con el
Python que `uv` guarda en `/home/levdigital01/.local/share/uv/` arranca perfectamente a mano
y **falla al iniciar el servicio**, con un error que no menciona `/home` por ninguna parte.

```bash
sudo useradd --system --home /opt/aeroconvert --shell /usr/sbin/nologin aeroconvert
sudo mkdir -p /opt/aeroconvert /var/lib/aeroconvert /var/backups/aeroconvert
sudo chown aeroconvert:aeroconvert /var/lib/aeroconvert /var/backups/aeroconvert
sudo chmod 700 /var/backups/aeroconvert
```

## 2. La carpeta compartida

Es por donde llegan las ortofotos y las nubes. Que la gente copie ahí con el Explorador es
reanudable y rápido; subir 20 GB por el navegador no lo es.

```bash
sudo mkdir -p /mnt/entregas
# En /etc/fstab, con las credenciales en un fichero de modo 600:
# //servidor/entregas /mnt/entregas cifs credentials=/etc/samba/credenciales,uid=aeroconvert,gid=aeroconvert,cache=strict,_netdev 0 0
sudo mount -a
```

`AEROCONVERT_RAICES_PERMITIDAS` apunta **a esta carpeta y a nada más**. Ni `/`, ni `/mnt`, ni
el padre de `/opt/aeroconvert`: `manage.py check` lo rechaza, porque en esta aplicación una
ruta es un primitivo de lectura del disco.

## 3. El código y la configuración

El repositorio es **privado**, y AeroControl ya resolvió esto con una clave SSH
(`git@github.com:DovaCrii/AeroControl.git`). Aquí conviene **una clave propia y no la misma**:
una clave de despliegue por aplicación se revoca sola el día que haga falta, sin dejar a las
otras dos fuera.

```bash
sudo -u aeroconvert ssh-keygen -t ed25519 -f /opt/aeroconvert/.ssh/id_ed25519 -N ""
sudo -u aeroconvert cat /opt/aeroconvert/.ssh/id_ed25519.pub
```

Esa clave pública se pega en GitHub, en **Settings → Deploy keys** del repositorio
AeroConvert, **sin marcar «Allow write access»**: el servidor solo tiene que leer.

```bash
sudo -u aeroconvert git clone git@github.com:DovaCrii/AeroConvert.git /opt/aeroconvert
cd /opt/aeroconvert
sudo -u aeroconvert cp .env.example .env
sudo -u aeroconvert nano .env      # descomenta el bloque «LA VM COMPARTIDA»
sudo chmod 600 .env
```

Y el entorno virtual, con el Python de `/opt` y **no** con el de `/home`:

```bash
sudo -u aeroconvert env UV_PYTHON_INSTALL_DIR=/opt/python \
     /home/levdigital01/.local/bin/uv venv --python 3.12 /opt/aeroconvert/.venv
sudo -u aeroconvert env VIRTUAL_ENV=/opt/aeroconvert/.venv \
     /home/levdigital01/.local/bin/uv sync --frozen --no-dev --group despliegue
```

**`--group despliegue` no es opcional: ahí vive `gunicorn`.** Está fuera de `dependencies`
porque la estación de trabajo corre con `runserver` y no tiene por qué bajarse un servidor
WSGI. Sin ese grupo, `uv sync` termina en verde, instala las veinte dependencias normales y
el servicio falla al arrancar con un `ExecStart` que no existe.

Lo que **no** puede faltar, porque sin ello el sitio devuelve 400 a todo y no dice por qué:
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SECRET_KEY`.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 4. Los servicios

**Primero la carpeta de respaldos, y no es un paso de adorno.** Faltaba en esta lista, y por
eso el servidor estuvo semanas con el temporizador puesto y **cero respaldos escritos**: el
servicio declara `ReadWritePaths=/var/backups/aeroconvert` y systemd no arranca una unidad
cuya ruta de escritura no existe. Falla antes de ejecutar nada, en el montaje del espacio de
nombres, y en el diario sale un `226/NAMESPACE` que no menciona la palabra respaldo.

```bash
sudo install -d -o aeroconvert -g aeroconvert -m 0700 /var/backups/aeroconvert
```

`0700` porque ahí dentro va la bitácora entera de la oficina.

```bash
sudo cp despliegue/aeroconvert.service        /etc/systemd/system/
sudo cp despliegue/aeroconvert-obrero.service /etc/systemd/system/
sudo cp despliegue/aeroconvert-respaldo.*     /etc/systemd/system/
sudo cp despliegue/aeroconvert.nginx.conf     /etc/nginx/sites-available/aeroconvert
sudo ln -s /etc/nginx/sites-available/aeroconvert /etc/nginx/sites-enabled/
sudo systemctl daemon-reload
sudo systemctl enable --now aeroconvert-obrero aeroconvert aeroconvert-respaldo.timer
sudo nginx -t && sudo systemctl reload nginx
```

**Y se comprueba que el respaldo escribe de verdad, ahora y no en tres semanas.** Es el
único de los tres servicios cuyo fallo no se nota usando la aplicación:

```bash
sudo systemctl start aeroconvert-respaldo.service && sudo ls -lh /var/backups/aeroconvert/
```

**El `sudo` del `ls` no sobra**: la carpeta es `0700` de `aeroconvert`, así que sin él sale
«Permiso denegado» y parece que el respaldo falló cuando lo que pasa es que está bien
guardado.

Tiene que aparecer un `.sqlite3.gz`. Si no aparece, el motivo está en
`journalctl -u aeroconvert-respaldo -n 30`.

**Son dos servicios y no uno.** El web no despacha conversiones
(`AEROCONVERT_DESPACHADOR=0`): con varios obreros de gunicorn arrancarían varios
despachadores, y aunque reclamar un trabajo sí es atómico, el tope de trabajos simultáneos se
comprueba con un `count()` que no lo es. Dos leen cero a la vez, arrancan dos conversiones, y
dos nubes de puntos suman sus techos de memoria y se llevan la máquina.

## 5. Desplegar

**Primero, `uv` donde lo vean todos.** Vive en `/home/levdigital01/.local/bin`, que el usuario
del servicio no puede leer: ni el guion ni ninguna orden con `sudo -u aeroconvert` lo
encuentran ahí. Se hace una sola vez:

```bash
sudo install -m 0755 /home/levdigital01/.local/bin/uv /usr/local/bin/uv
```

Y ya, cada despliegue es esto:

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && scripts/desplegar.sh
```

El guion valida la configuración **antes** de migrar, recolecta los estáticos **antes** de
servir —sin `collectstatic`, todas las páginas dan 500—, espera a `/salud/` con la cabecera
`Host` que `ALLOWED_HOSTS` exige, y termina diciendo el tope de subida que quedó activo.

Cada orden que escribe dentro de `/opt/aeroconvert` va como `aeroconvert`; solo `systemctl` va
con `sudo`. Lanzarlo todo como root deja el entorno virtual y los estáticos con dueño root en
un árbol que no es suyo: arranca ese día y falla el día que el servicio tenga que escribir.

## 6. La primera cuenta

```bash
sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py createsuperuser
```

No hay pantalla de alta: las cuentas las crea quien administra, desde aquí o desde `/admin/`.

---

## Operar

### Ver qué pasa

```bash
journalctl -u aeroconvert -u aeroconvert-obrero -p err --since "1 hour ago"
journalctl -u aeroconvert-obrero -f          # seguir una conversión en vivo
curl -s http://127.0.0.1/salud/ | python3 -m json.tool
```

`/salud/` dice `degradado` —con 200, no 503— cuando la carpeta compartida no está montada, el
obrero se cayó o el disco se llenó. Un 503 ahí dejaría al guion de despliegue esperando para
siempre.

### Alguien no puede entrar

El bloqueo es por la **pareja** usuario + IP, así que un compañero equivocándose no deja fuera
a los demás. Para levantarlo al instante:

```bash
sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py axes_reset_username ana
```

O desde `/admin/` → Intentos de acceso, borrando la fila.

### Después de instalar o cambiar GDAL, PDAL o el conversor de ODA

```bash
sudo systemctl restart aeroconvert aeroconvert-obrero
```

La lista de controladores se cachea **dentro de cada proceso y sin caducidad**
(`apps/engines/sondas.py`). Sin reiniciar, la pantalla de compatibilidad seguirá diciendo que
falta lo que acabas de instalar.

### Respaldo

Corre solo, a las 03:15. A mano:

```bash
sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py respaldar
```

No es un `cp`: con WAL, copiar el fichero entrega la foto del último punto de control y le
faltan las últimas horas **sin decirlo**. El comando usa la API de respaldo en línea de
SQLite, **verifica la copia abriéndola** y falla ruidosamente si no cuadra.

**Y hace falta al menos una copia fuera de la VM.** Un respaldo en el mismo disco que la base
no protege del escenario que más importa.

### Restaurar

```bash
sudo systemctl stop aeroconvert aeroconvert-obrero
sudo -u aeroconvert gunzip -c /var/backups/aeroconvert/aeroconvert-AAAAMMDD-HHMMSS.sqlite3.gz \
     > /var/lib/aeroconvert/db.sqlite3
# Los -wal y -shm viejos son de la base anterior: dejarlos corrompe la restaurada.
sudo rm -f /var/lib/aeroconvert/db.sqlite3-wal /var/lib/aeroconvert/db.sqlite3-shm
sudo chown aeroconvert:aeroconvert /var/lib/aeroconvert/db.sqlite3
sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py migrate
sudo systemctl start aeroconvert-obrero aeroconvert
```

---

## Lo que no va a funcionar, y es a propósito

- **Word, Excel y PowerPoint a PDF, y PDF a Word.** Hablan con Office por COM, que es
  Windows. En la pantalla salen apagadas con su motivo escrito; las otras nueve herramientas
  de PDF funcionan igual.
- **Las nubes de puntos muy grandes.** PDAL carga los puntos en memoria: la regla medida son
  105 MB por millón. Una nube de mil millones de puntos pide unos 100 GB, y la aplicación lo
  dice **antes** de empezar en vez de dejar que el sistema mate el proceso.
- **Subir una nube de diez o veinte gigabytes por el navegador.** No es el tope: es que una
  subida por HTTP **no se reanuda**, así que perder la conexión al 90 % es empezar de cero.
  Para eso está la carpeta compartida.

## El tope de subida

`AEROCONVERT_TOPE_MB`, **2048 por omisión**. Cubre las ortofotos, que es lo que de verdad se
sube desde un portátil.

Estuvo en 200 hasta el 2026-09-15, con el argumento de que «los archivos grandes llegan por la
carpeta compartida» — y esa carpeta no está montada, así que subir era la única vía y una
ortofoto de 600 MB no cabía. Peor: el mensaje decía **«No llegó ningún archivo»**, porque
`StopUpload` descarta el cuerpo entero y la vista no podía distinguirlo de no haber elegido
nada. Ya lo distingue y lo dice con el número.

Si se cambia, hay **tres sitios** que tienen que moverse juntos, y una prueba que lo vigila:

| Dónde | Qué |
| --- | --- |
| `.env` | `AEROCONVERT_TOPE_MB` |
| `despliegue/aeroconvert.nginx.conf` | `client_max_body_size`, con margen por encima |
| — | `test_el_tope_de_cuerpo_deja_pasar_una_subida` falla si los dos se separan |

Y el tiempo: `client_body_timeout` está en 600 s. Con los 60 de fábrica, dos gigabytes por una
red de oficina se cortan a mitad y el mensaje no dice que fue el reloj.
