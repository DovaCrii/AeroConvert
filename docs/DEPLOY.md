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

Para conversiones livianas y para compartir resultados. **No** para las ortofotos de 40 GB:
subirlas es el cuello de botella, y desplegar la SDK de ECW en un servidor exige la licencia
cara.

Igual que AeroBim y AeroControl, se despliega en VM propia. No hay `render.yaml` ni Docker:
no se ha necesitado.

```
/opt/aeroconvert          el código
/var/lib/aeroconvert      la base y el almacén de salidas
```

- **nginx** delante, con TLS y `client_max_body_size` acorde a `AEROCONVERT_TOPE_MB`.
- **gunicorn** con `config.wsgi`, `DJANGO_SETTINGS_MODULE=config.settings.nube`.
- **systemd** para el servicio.

El tope de tamaño se comprueba en **tres** sitios: nginx, el manejador de subida en
streaming y `clean()` del modelo. Solo el último es inevadible, y solo los dos primeros dan
un mensaje que se entiende.

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

## Respaldo

La base guarda el historial de trabajos y los preajustes, no los archivos. En modo taller
las salidas viven junto a sus originales, bajo el control de quien las hizo. En modo nube
viven en el almacén con `expires_at` y hay un barrido de retención.

**Los datos reales no entran nunca al repositorio.**
