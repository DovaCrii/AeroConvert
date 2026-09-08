# Registro de cambios

Sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

## [0.1.0] — 2026-09-08

Primera versión. Andamiaje al estándar de la familia Aero y el núcleo de detección, que es
lo que sostiene el diagnóstico: **saber qué tiene un archivo dentro y dónde va a abrir**.

### Añadido

- **Lector propio de cabecera TIFF y BigTIFF** (`apps/formats/tiff.py`), sin GDAL. Devuelve
  variante, dimensiones, bandas, banda alfa, compresión, teselado, pirámides, EPSG, GSD y
  extensión en terreno. Navega el archivo con desplazamientos, no leyendo un prefijo, y
  nunca lee un píxel.
- **Catálogo de formatos** (`apps/formats/catalogo.py`) con las cuatro familias. BigTIFF es
  una entrada propia y no una bandera de GeoTIFF: comparten extensión pero uno abre en
  Civil 3D y el otro no.
- **Detección** por firma → extensión → GDAL, con la confianza declarada en la respuesta.
  Una discrepancia entre firma y extensión no es un error: gana la firma y se avisa.
- **CRS con procedencia** (`apps/formats/crs.py`): `incrustado`, `sidecar-prj`, `declarado`
  o `desconocido`. `PuntoConCrs` impide que una coordenada viaje sin su sistema.
- **Perfiles de destino y veredictos** (`apps/targets/perfiles.py`) para Civil 3D, QGIS,
  ArcGIS Pro, Google Earth, visor web y AeroBim.
- **Contrato de motor, registro y matriz de capacidades** (`apps/engines/`), con tres
  estados por celda: disponible, instalable y no soportado.
- **Sondas** de GDAL, PROJ, PDAL, ECW y ODA. La de ECW distingue tres motivos —
  `sin-driver-ecw`, `sin-clave-ecw`, `sin-binario-ecw` — porque son tres arreglos distintos.
- **Catálogo de motivos** con código estable (`apps/jobs/motivos.py`), extendiendo el
  vocabulario que ya usa AeroBim.
- **Dos modos**, `taller` y `nube`, con la misma base de código. En taller
  `AEROCONVERT_RAICES_PERMITIDAS` es obligatoria y `manage.py check` falla sin ella.
- **Identidad visual**: quinto color de la familia, magenta `#F15BB5`, a 55° del violeta de
  AeroBim y 70° del ámbar de AeroPlanner. Marca y variante oscura en `assets/`.
- **73 pruebas**, verdes en una máquina sin GDAL, con TIFF de unos 400 bytes construidos
  byte a byte dentro de la propia prueba.

### Notas de verificación

El lector de cabecera se contrastó contra `gdalinfo` sobre archivos de obra reales y
coincide en variante, dimensiones, bandas, compresión, teselado, EPSG y **número de
pirámides**, incluido el caso en que hay banda de máscara y sus IFD inflarían la cuenta al
doble.

Un detalle que se descartó a propósito: un escritor puede dejar IFD más pequeños **sin**
`NewSubfileType`. Contarlos como pirámides parecía razonable, pero el oráculo dice que GDAL
no los expone como overviews —y por tanto QGIS tampoco los usa—, así que se cuentan aparte.
Prometer un zoom rápido que ningún programa va a dar sería peor que callarlo.
