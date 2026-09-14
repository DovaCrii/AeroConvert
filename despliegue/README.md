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

```
https://p340.<tailnet>.ts.net          → AeroControl
https://p340.<tailnet>.ts.net:8443     → AeroConvert
https://p340.<tailnet>.ts.net:10000    → AeroBim, cuando toque
```

Cada una montada en `/`, sin `FORCE_SCRIPT_NAME` y sin reescribir estáticos.

### Publicarlo

```bash
tailscale funnel --bg --https=8443 http://127.0.0.1:8001
tailscale funnel status
```

Y en el `.env`, con el puerto:

```
ALLOWED_HOSTS=p340.<tailnet>.ts.net
CSRF_TRUSTED_ORIGINS=https://p340.<tailnet>.ts.net:8443
```

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
sudo apt install -y python3.12 python3.12-venv gdal-bin pdal nginx cifs-utils
```

**Nunca `pip install gdal`**: la rueda de PyPI no trae los controladores que la aplicación
sondea, y la matriz de compatibilidad saldría medio apagada sin decir por qué.

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

```bash
sudo -u aeroconvert git clone <el repositorio> /opt/aeroconvert
cd /opt/aeroconvert
sudo -u aeroconvert cp .env.example .env
sudo -u aeroconvert nano .env      # descomenta el bloque «LA VM COMPARTIDA»
sudo chmod 600 .env
```

Lo que **no** puede faltar, porque sin ello el sitio devuelve 400 a todo y no dice por qué:
`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SECRET_KEY`.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 4. Los servicios

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

**Son dos servicios y no uno.** El web no despacha conversiones
(`AEROCONVERT_DESPACHADOR=0`): con varios obreros de gunicorn arrancarían varios
despachadores, y aunque reclamar un trabajo sí es atómico, el tope de trabajos simultáneos se
comprueba con un `count()` que no lo es. Dos leen cero a la vez, arrancan dos conversiones, y
dos nubes de puntos suman sus techos de memoria y se llevan la máquina.

## 5. Desplegar

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && scripts/desplegar.sh
```

El guion valida la configuración **antes** de migrar, recolecta los estáticos **antes** de
servir —sin `collectstatic`, todas las páginas dan 500— y espera a `/salud/` antes de dar el
despliegue por bueno.

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
- **Subir archivos por el navegador.** No está escrito. Los archivos llegan por la carpeta
  compartida, que además es lo correcto para varios gigabytes.
