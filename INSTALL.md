# Instalación

AeroConvert se instala en dos pasos separados a propósito: **la aplicación** y **las
herramientas de conversión**. La aplicación funciona sin las segundas —diagnostica, muestra
la matriz de capacidades y dice qué falta— y eso es lo que permite desarrollar y correr las
pruebas en una máquina limpia.

---

## 1. La aplicación

Requisitos: Python 3.12, PowerShell 7+, Git y [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/DovaCrii/AeroConvert.git
Set-Location AeroConvert
uv sync --all-groups
```

```powershell
Copy-Item .env.example .env
```

Edita `.env`. Lo único obligatorio en modo taller es **`AEROCONVERT_RAICES_PERMITIDAS`**:
las carpetas bajo las cuales se puede leer, separadas por `;`. Sin ella `manage.py check`
falla, y falla a propósito — la ruta de origen la teclea una persona, así que sin lista
blanca la aplicación sería un primitivo de lectura del disco entero.

```powershell
uv run python manage.py migrate
uv run python manage.py createsuperuser
pwsh scripts/run.ps1
```

---

## 2. Las herramientas de conversión

Ninguna es dependencia del paquete: se **sondean** en tiempo de ejecución. Lo que falte
apaga su fila de la matriz con un motivo escrito, no rompe nada.

Para ver qué encuentra esta máquina:

```powershell
pwsh scripts/sondear.ps1
```

### GDAL y PDAL — obligatorios para convertir

**En Windows, la vía más simple es que ya los tengas.** QGIS los trae completos:

```
C:\Program Files\QGIS 4.0.2\bin
```

Ahí viven `gdalinfo.exe`, `gdal_translate.exe`, `gdalwarp.exe`, `gdaladdo.exe`,
`ogr2ogr.exe` y `pdal.exe`. Apunta las variables a esa carpeta y listo:

```
AEROCONVERT_GDAL_BIN=C:\Program Files\QGIS 4.0.2\bin
AEROCONVERT_PDAL_BIN=C:\Program Files\QGIS 4.0.2\bin
```

Se antepone al `PATH` **del proceso hijo**, nunca al del servidor: mezclar el GDAL de una
instalación con el PROJ de otra no falla limpiamente — reproyecta con datos equivocados y
entrega un archivo que parece bien.

Alternativas, en orden de preferencia:

| Vía | Cuándo |
| --- | --- |
| **QGIS** | Ya lo tienes instalado. Es la más simple |
| **OSGeo4W** | Instalación de GDAL sin QGIS encima. Permite añadir paquetes sueltos |
| **conda-forge** (`micromamba install gdal pdal`) | Servidores Linux y CI |
| Rueda de PyPI | **No sirve**: no trae los controladores que hacen falta |

Comprueba que PROJ encuentre su base de datos. Si `sondear.ps1` reporta
`proj-descolocado`, define:

```
PROJ_DATA=C:\Program Files\QGIS 4.0.2\share\proj
```

### En el servidor: Ubuntu 26.04

GDAL sí está empaquetado y basta con `apt`:

```bash
sudo apt install -y gdal-bin
```

**PDAL no está** — `apt-cache policy pdal` no devuelve nada en 26.04. Sin él, las nubes de
puntos salen apagadas con su motivo escrito, que es lo correcto, pero son 30 conversiones
menos. La vía que no arrastra medio sistema de compilación es conda-forge, en un prefijo
aparte:

```bash
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | sudo tar -xvj -C /usr/local bin/micromamba
sudo micromamba create -y -p /opt/geo -c conda-forge pdal
/opt/geo/bin/pdal --version
```

Y en el `.env`:

```
AEROCONVERT_PDAL_BIN=/opt/geo/bin
```

**Un prefijo aparte y no el sistema, a propósito.** conda-forge trae su propio GDAL y su
propio PROJ; instalarlo por encima dejaría dos de cada uno mezclados, y eso **no falla
limpiamente**: reproyecta con datos equivocados y entrega un archivo que parece bien. Con
`/opt/geo` separado, cada proceso hijo ve solo lo suyo.

Después hay que **reiniciar los servicios**: la lista de controladores se cachea dentro de
cada proceso y sin caducidad (`apps/engines/sondas.py`), así que hasta reiniciar la pantalla
de compatibilidad seguirá diciendo que falta lo que acabas de instalar.

```bash
sudo systemctl restart aeroconvert aeroconvert-obrero
```

### ECW — opcional y de pago

Escribir ECW exige la **ERDAS ECW/JP2 SDK de Hexagon con clave OEM**, comercial. GDAL solo
lee, y **la compilación que trae QGIS no incluye ECW ni para leer**.

Con la clave:

```
AEROCONVERT_ECW_ENCODE_KEY=<la clave>
AEROCONVERT_ECW_ENCODE_COMPANY=<la empresa, exactamente como figura en la clave>
```

O bien un ejecutable externo que comprima a ECW:

```
AEROCONVERT_ECW_BIN=C:\ruta\al\compresor.exe
```

Sin ninguna de las dos, el destino ECW aparece apagado con el motivo `sin-clave-ecw` y la
aplicación propone COG o JPEG 2000.

**Y para el caso corriente, JPEG 2000 basta y sobra.** Está medido sobre material real
(`docs/PRUEBAS_CON_ORACULO.md`): 13 % del peso del original, error máximo de 4 niveles
sobre 255, georreferencia dentro del archivo sin acompañantes, y Civil 3D con Raster Design
lo lee. No necesita licencia de nadie.

#### ECW en Linux, si aun así hace falta

En Ubuntu **no hay atajo**: ni `apt` ni conda-forge traen ECW, por la licencia. La única vía
es compilar GDAL contra la SDK de Hexagon, y conviene saber qué se gana en cada escalón antes
de empezar:

| Lo que quieres | Qué hace falta | Coste |
| --- | --- | --- |
| **Leer** ECW que manda un cliente | SDK de solo lectura + GDAL compilado con ella | Gratis, previo registro y aceptar su licencia. Medio día de trabajo |
| **Escribir** ECW | Además, clave OEM de Hexagon | **Comercial**, y la clave va atada a la empresa |

La compilación no es un `./configure` y a correr: hay que bajar la SDK, descomprimirla,
compilar GDAL entero con `-DECW_ROOT=`, y **reemplazar o convivir con el `gdal-bin` de
Ubuntu**, que es justo la mezcla de dos GDAL contra la que avisa la sección anterior. Un
prefijo aparte, como con PDAL, es la forma de que eso no muerda.

**La recomendación, con la aritmética delante:** ECW cuesta medio día y una licencia para
resolver 10 conversiones de las que 8 ya tienen una salida abierta y medida. Si un cliente
manda un ECW y hay que leerlo, se abre una vez en QGIS —que sí lo lee en Windows— y se guarda
como COG. Si el día que lo pidan es todos los días, entonces sí sale a cuenta.

### ODA File Converter — opcional, para DWG y DGN

Gratuito, de la Open Design Alliance, con su propia licencia. **No se distribuye con
AeroConvert.** Se descarga de su web, se instala, y:

```
AEROCONVERT_ODA_CONVERTER=C:\Program Files\ODA\ODAFileConverter <versión>\ODAFileConverter.exe
```

La alternativa abierta para DWG, LibreDWG, es GPL-3 y **contagiaría la licencia del
proyecto entero**, así que no se contempla.

**En Linux hace falta una cosa más**, y no se adivina leyendo el error que sale sin ella:

```bash
sudo apt install xvfb
```

ODA está hecho con Qt y **necesita un servidor gráfico para arrancar aunque no dibuje nada**.
En un servidor sin escritorio, sin `xvfb-run` delante, lo que aparece es un fallo de Qt sobre
un «display» que nadie pidió, y nadie lo relaciona con convertir un plano. AeroConvert lo
envuelve solo cuando lo encuentra, y cuando no está lo dice nombrando el paquete.

Con las dos cosas puestas, DWG y DGN v8 se convierten a GeoPackage, SHP, GeoJSON, KML, KMZ y
DXF. Sin ellas, esos orígenes salen apagados con su motivo y ofreciendo la alternativa que sí
sirve: «Guardar como DXF» desde cualquier CAD hace exactamente el mismo primer paso.

---

## 3. Comprobar que quedó bien

```powershell
pwsh scripts/verify.ps1
```

```powershell
pwsh scripts/sondear.ps1
```

El primero es la puerta de calidad y **tiene que ser verde aunque no haya GDAL**. El
segundo dice qué motores ve la máquina y por qué faltan los que faltan.
