# Despliegue

Dos modos, un solo código. La diferencia es la política de entrada y salida, no la lógica.

---

## Modo taller — la estación de trabajo

Es el modo para el que se diseñó la aplicación, y en el que se va a usar el 95 % del tiempo.

```powershell
pwsh scripts/run.ps1
```

Levanta el servidor en `127.0.0.1:8420`, espera a que `/salud/` responda **200** y abre el
navegador. Espera en vez de dormir unos segundos porque en un arranque frío Django tarda
más, y abrir antes de tiempo da una página de error que parece un fallo de la aplicación.

Tres cosas que conviene entender de este modo:

- **Los archivos no se copian.** Se leen de donde están. Una ortofoto de obra son cientos de
  megabytes y copiarla para convertirla es tiempo y espacio tirados.
- **No hay tope de tamaño.** El límite lo pone el disco.
- **`AEROCONVERT_RAICES_PERMITIDAS` es obligatoria**, y `manage.py check` falla sin ella. La
  ruta de origen la teclea una persona, así que sin lista blanca esto sería un primitivo de
  lectura del disco entero — y da igual que escuche solo en `127.0.0.1`: un enlace en un
  correo puede hacer que el navegador envíe el formulario.

`--noreload` no es un detalle: con el recargador, `runserver` son **dos** procesos, y
arrancarían dos despachadores compitiendo por el mismo trabajo.

## Modo nube — VM propia

> ### ⚠ Hoy el modo nube **no convierte nada**. No lo despliegues todavía.
>
> Comprobado el **2026-09-11**, sobre el código, no de memoria. `config.settings.nube`
> arranca, sirve páginas, autentica, redirige a HTTPS y pinta su chapa. Y no puede convertir
> **ni un solo archivo**, porque la única vía de entrada que existe —escribir una ruta del
> disco— está cerrada a propósito en nube (`apps/core/modo.py::comprobar_ruta`), y la vía
> que la sustituye —la subida— **no está escrita**.
>
> Lo que falta, verificado por búsqueda en todo el repositorio:
>
> - **Cero `request.FILES`, cero `enctype="multipart/form-data"`, cero manejadores de
>   subida.** El campo `ConversionJob.source_upload` existe y está huérfano: nada lo escribe,
>   y el runner solo lee `source_path`.
> - **No hay `MEDIA_ROOT` ni `MEDIA_URL`** en ningún fichero de ajustes, así que ese
>   `FileField` no tendría dónde escribir.
> - **`AEROCONVERT_TOPE_MB` no valida nada.** Se define y se interpola en el texto de la
>   chapa. Nada más. (Este documento afirmaba que se comprobaba en tres sitios; eran cero.
>   Corregido.)
> - **Las herramientas de PDF fallan todas**, con un error de ruta genérico. Solo
>   «Office a PDF» se apaga dando su motivo.
> - **`revisar_configuracion()` no valida nada en modo nube**: un despliegue sin
>   `ALLOWED_HOSTS` pasa `manage.py check` y luego da 400 a todo.
>
> Lo que **sí** está comprobado que funciona en nube (2026-09-11): los ajustes cargan,
> `manage.py check --deploy` solo se queja de `ALLOWED_HOSTS` vacío, y `manage.py migrate`
> sobre una base vacía aplica las 25 migraciones sin un solo error.
>
> **El modo taller es el que está terminado y en uso.** Ver arriba.

Cuando se escriba, para conversiones livianas y para compartir resultados. **No** para las
ortofotos de 40 GB: subirlas es el cuello de botella, y desplegar la SDK de ECW en un
servidor exige la licencia cara.

Igual que AeroBim y AeroControl, iría en VM propia. No hay `render.yaml` ni Docker: no se ha
necesitado. **Tampoco hay** unit de systemd, configuración de nginx, script de arranque para
Linux, ni `gunicorn` entre las dependencias — nada de eso está en el repositorio, y lo de
abajo es el diseño, no un procedimiento que se pueda seguir hoy.

```
/opt/aeroconvert          el código
/var/lib/aeroconvert      la base y el almacén de salidas
```

- **nginx** delante, con TLS y `client_max_body_size` acorde a `AEROCONVERT_TOPE_MB`.
- **gunicorn** con `config.wsgi`, `DJANGO_SETTINGS_MODULE=config.settings.nube`.
- **systemd** para el servicio.

**Ojo con la última línea.** `config/wsgi.py` tiene como valor por omisión
`config.settings.prod`, **no** `nube`. Si el servicio no exporta
`DJANGO_SETTINGS_MODULE=config.settings.nube`, la VM arranca en modo **taller** —porque
`prod.py` no toca `MODO`— con las cookies de HTTPS puestas y sin `RAICES_PERMITIDAS`. Es un
fallo silencioso que se parece a un problema de configuración de nginx.

El tope de tamaño **tendrá** que comprobarse en tres sitios: nginx, el manejador de subida en
streaming y `clean()` del modelo. Solo el último sería inevadible, y solo los dos primeros
darían un mensaje que se entiende. Hoy no está ninguno.

### Qué VM hace falta

Las cifras salen de medir, no de estimar. Todas son del **2026-09-09**, sobre los archivos
reales del cruce minero de BHP y con `GDAL_CACHEMAX=512`:

| Trabajo | Entrada | Salida | Tiempo | Pico de memoria |
| --- | --- | --- | --- | --- |
| Ortofoto → JP2 | 466,2 MB · 209,8 Mpx · 4 bandas | 60,1 MB | 11,0 s | **655 MB** |
| Ortofoto → GeoTIFF DEFLATE | 466,2 MB | 285 MB | 7 s | ~650 MB |
| Nube → COPC | 266,0 MB · 9.618.692 puntos | 72,9 MB | 31,4 s | **966 MB** |

Medido en una máquina de 20 núcleos. El tiempo baja con más núcleos —GDAL y PDAL usan
todos— pero **no linealmente**: el cuello es el disco antes que el procesador.

**Lo que decide el dimensionado es que las dos familias acotan la memoria de forma
distinta.** GDAL la acota él: `GDAL_CACHEMAX` es un tope duro, así que una ortofoto de 40 GB
se convierte con el mismo techo que una de 500 MB. **PDAL no**: carga los puntos en memoria y
`GDAL_CACHEMAX` no le afecta, así que su techo **crece con el número de puntos** — unos
**105 MB por millón**, medidos. Una nube de 50 millones de puntos pide más de 5 GB.

Esa asimetría está en el código, en `apps/jobs/estimacion.py::_memoria_mb()`, y es la que
manda a la hora de elegir la máquina:

| | Mínimo que funciona | Recomendado | Si entran nubes grandes |
| --- | --- | --- | --- |
| vCPU | 2 | **4** | 4–8 |
| RAM | 2 GB | **4 GB** | 8–16 GB |
| Disco | 40 GB SSD | **80 GB SSD** | 120 GB SSD |
| Sistema | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |

- **2 GB de RAM basta para ráster** —el techo son 704 MB más Django, gunicorn y el sistema—
  pero deja sin margen a cualquier nube de más de 15 millones de puntos.
- **4 GB es el punto sensato**: cubre ráster de cualquier tamaño y nubes de hasta unos
  35 millones de puntos, con sitio para la caché de archivos del sistema, que es lo que de
  verdad acelera esto.
- **Con nubes de decenas de millones de puntos, la RAM se calcula, no se elige**:
  `105 MB × millones de puntos + 1 GB`. Y conviene poner `AEROCONVERT_TRABAJOS_SIMULTANEOS=1`
  —que es el valor por omisión— porque dos nubes a la vez suman sus dos techos.
- **El disco no lo fija el sistema, lo fija el presupuesto de trabajo**: la regla de más abajo
  es `2 × (mayor archivo esperado) × (trabajos simultáneos) + margen`. La instalación en sí
  ocupa poco: unos 125 MB de entorno virtual más 1,5–2,5 GB de GDAL y PDAL.
- **SSD, no disco mecánico.** Con 466 MB en 11 s el proceso está limitado por
  entrada/salida buena parte del tiempo.

**GDAL y PDAL no se instalan desde PyPI.** La rueda no trae los binarios que la aplicación
sondea. En Ubuntu, `apt install gdal-bin pdal` o un entorno de conda-forge; nunca
`pip install gdal`. La aplicación los **sonda**, no los declara como dependencia — por eso
una VM sin ellos arranca y enseña la matriz de compatibilidad en ámbar en vez de reventar.

En **modo taller no hay VM que dimensionar**: la máquina es la estación de trabajo, y las
cifras de arriba dicen lo que la aplicación le va a pedir mientras convierte.

### Un solo obrero, o el reclamo atómico manda

Con varios obreros de gunicorn hay varios despachadores. Está previsto —reclamar un trabajo
es un `UPDATE` atómico con su prueba de la carrera— pero **por omisión se convierte un
trabajo a la vez**: GDAL ya usa todos los núcleos con `GDAL_NUM_THREADS=ALL_CPUS`, y dos
conversiones compitiendo por el mismo disco es más lento, no más rápido.

## Variables que hay que poner en producción

| Variable | Nota |
| --- | --- |
| `SECRET_KEY` | Larga y aleatoria. Nunca la del ejemplo |
| `ALLOWED_HOSTS` · `CSRF_TRUSTED_ORIGINS` | Separadas por comas |
| `AEROCONVERT_MODO` | `taller` o `nube` |
| `AEROCONVERT_RAICES_PERMITIDAS` | Obligatoria en taller |
| `AEROCONVERT_TOPE_MB` | Solo en nube |
| `AEROCONVERT_GDAL_BIN` · `AEROCONVERT_PDAL_BIN` | La carpeta `bin`, no el ejecutable |
| `AEROCONVERT_ECW_ENCODE_KEY` · `_COMPANY` | Solo si se compró la licencia |
| `PROJ_DATA` | Si la sonda reporta `proj-descolocado` |

**La clave de ECW no va en ningún registro.** Viaja solo en el entorno del proceso hijo, y
hay una prueba con clave centinela que la busca en los registros, en los eventos de la
bitácora y en el HTML de la respuesta.

## Antes de cada despliegue

```powershell
pwsh scripts/verify.ps1
```

```powershell
pwsh scripts/sondear.ps1
```

El primero es la puerta de calidad. El segundo dice qué motores ve **esa** máquina — que no
es la de desarrollo, y es donde aparecen las sorpresas.

## Cuánto disco gasta esto, y cómo no gastarlo

### Lo que no se puede evitar

GDAL necesita **un archivo de verdad, con acceso aleatorio**, tanto de entrada como de
salida. No hay forma de convertir un GeoTIFF «al vuelo» desde el flujo HTTP: el formato
exige saltar por dentro del archivo — leer la cabecera, ir al índice de teselas, volver.
`/vsistdin/` existe, pero solo sirve para formatos secuenciales, que no son estos.

Así que **algo toca disco siempre**. Lo que sí se puede garantizar es que no sobreviva a la
petición.

### Las tres políticas

`AEROCONVERT_RETENCION`:

| Política | Qué hace | Cuándo usarla |
| --- | --- | --- |
| **`efimera`** | La salida se borra **en cuanto se descarga**; si nadie la descarga, a los 30 min | Servicio compartido. Es el valor por omisión en modo nube |
| `temporal` | Se guarda 24 h y se barre | Un equipo pequeño que rehace entregas el mismo día |
| `permanente` | No se barre nunca | Modo taller. La salida vive junto al original, en el disco de la persona: barrerla sería borrarle su entregable |

Las **entradas subidas se borran siempre** al terminar el trabajo, con cualquier política.
Quien la subió ya la tiene, y guardarla duplicaría el archivo del cliente en nuestro
servidor sin que nadie lo haya pedido.

Lo que **sí** sobrevive es la fila del trabajo: tamaños, huellas, CRS, motor, veredicto y
bitácora. Son unos pocos KB y es lo que permite responder «¿qué le pasó a esa entrega?» seis
meses después. El recibo sobrevive; el archivo no.

### Y lo que de verdad protege el disco

No es la política de borrado. Borrar al terminar **no impide** que tres conversiones
simultáneas de 40 GB llenen el volumen a la vez.

Lo que lo impide es `AEROCONVERT_PRESUPUESTO_GB`: antes de reclamar un trabajo, el
despachador mide lo que ya ocupa la carpeta de trabajo y lo que este va a necesitar —**el
doble de la entrada**, porque durante un instante conviven el parcial y el definitivo—. Si
no cabe, el trabajo **espera en la cola** en vez de arrancar. No falla: un disco lleno es
transitorio y se libera cuando otro trabajo se descarga; fallarlo obligaría a reencolar a
mano por algo que se arregla solo.

Un servidor que se queda sin disco no devuelve un error: deja de funcionar entero, y
normalmente se lleva la base de datos por delante.

### Cómo dimensionarlo

```
presupuesto ≈ 2 × (mayor archivo esperado) × (trabajos simultáneos)  +  margen
```

Con un solo trabajo a la vez y ortofotos de hasta 5 GB, 20 GB de presupuesto sobran. Con
`AEROCONVERT_TRABAJOS_SIMULTANEOS=1` —el valor por omisión— el pico es predecible.

### El barrido

Corre solo: al arrancar el despachador y cada cinco minutos. También a mano:

```powershell
uv run python manage.py barrer --simular
```

```powershell
uv run python manage.py barrer
```

Recoge tres cosas: salidas caducadas, entradas subidas de trabajos terminados, y
**huérfanos** — un `.parcial` que sobrevivió a un proceso muerto. Los huérfanos se exigen de
más de una hora para no llevarse por delante el parcial de un trabajo que está corriendo
ahora mismo: el nombre no dice de quién es.

El barrido de arranque es el importante. Es el único momento en que se sabe con certeza que
ningún trabajo está en marcha, así que es cuando se puede limpiar lo que dejó un apagón.

## Respaldo

La base guarda el historial de trabajos y los preajustes, no los archivos. En modo taller
las salidas viven junto a sus originales, bajo el control de quien las hizo. En modo nube
viven en el almacén con `expires_at` y hay un barrido de retención.

**Los datos reales no entran nunca al repositorio.**
