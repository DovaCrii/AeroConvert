# Qué formatos entran y salen, y qué pedir a quien entrega

Este documento existe para dos cosas: **decidir de una vez qué lee y escribe la
aplicación**, y **poder pasárselo a quien entrega archivos** sin tener que explicarlo cada
vez.

---

## Lo primero: BigTIFF no es GeoTIFF

Comparten la extensión `.tif` y **son formatos distintos**. Se diferencian en un byte:

```
49 49 2A 00   →  II, versión 42  →  TIFF clásico
49 49 2B 00   →  II, versión 43  →  BigTIFF
```

**AutoCAD y Civil 3D leen el primero y no el segundo.** Ese es el diagnóstico más frecuente
que da esta aplicación, y por eso BigTIFF es una entrada propia del catálogo y no una
bandera de GeoTIFF.

BigTIFF existe para pasar el techo de 4 GB del TIFF clásico. Muchos programas —Metashape
entre ellos— lo escriben **aunque no haga falta**, porque la casilla está marcada. Cuando el
contenido sin comprimir cabe de sobra bajo los 4 GB, reescribirlo como clásico no pierde un
solo píxel y lo abre mucho más software.

## Ráster

| Formato | Lee | Escribe | Nota |
| --- | :-: | :-: | --- |
| GeoTIFF clásico | ✔ | ✔ | El que abre en cualquier parte |
| **BigTIFF** | ✔ | ✔ | Mismo `.tif`, formato distinto. Civil 3D **no** lo lee |
| COG | ✔ | ✔ | Teselado y con pirámides, para servir por rangos HTTP |
| JPEG 2000 | ✔ | ✔ | **El sustituto libre de ECW.** Georreferencia dentro |
| ECW | ✔ | ⚿ | Escribir exige clave OEM de Hexagon |
| MrSID | ✔ | ✖ | **Nunca se escribe**: exige el SDK de Extensis |
| ERDAS IMAGINE `.img` | ✔ | ✔ | |
| Arc/Info ASCII Grid | ✔ | ✔ | Texto plano, sin firma |
| Arc/Info Binary Grid | ✔ | ✖ | |
| BIL / BIP / BSQ | ✔ | ✔ | |
| USGS DEM · SRTM HGT | ✔ | ✖ | |
| PNG · JPEG · WebP | ✔ | ✔ | Con world file al lado |
| NITF · netCDF · Zarr | ✔ | ~ | |
| MBTiles · GeoPackage ráster | ✔ | ✔ | |
| VRT | ✔ | ✔ | Mosaico virtual: no copia un píxel |

## Nubes de puntos (fase F2)

LAS 1.0–1.4, LAZ, **COPC**, E57, PLY, PCD, XYZ/PTS. Salida a 3D Tiles y Potree.

## Vectorial, CAD y topografía (fase F3)

SHP, GeoPackage, GeoJSON, TopoJSON, FlatGeobuf, GeoParquet, KML/KMZ, GML, GPX, MapInfo,
DXF, **archivos de puntos PNEZD/PENZD**, LandXML.

## BIM y malla (fase F4)

IFC (lectura), OBJ, glTF/GLB, STL, Collada, 3D Tiles.

---

## Por qué no se escribe DWG ni DGN

Igual que en AeroBim, y por la misma razón:

| Opción | Por qué no |
| --- | --- |
| **LibreDWG** | GPL-3: **contagiaría la licencia de AeroConvert entero** |
| **ODA Drawings SDK** | Es la solución real y es **comercial** |
| Lectores en JavaScript | No hay ninguno serio |

**DXF no es un apaño**: es el formato de intercambio que publica la propia Autodesk, está
documentado, y cualquier CAD exporta a él en un paso. DWG y DGN v8 se **leen** convirtiendo
a DXF con ODA File Converter, que es gratuito pero hay que instalarlo aparte.

GDAL sí lee DGN v7 con controlador abierto, pero casi nadie entrega v7 hoy.

## Por qué ECW es opcional y JPEG 2000 es la respuesta

Escribir ECW exige la ERDAS ECW/JP2 SDK de Hexagon con clave OEM, comercial. Sin ella el
destino aparece apagado con el motivo `sin-clave-ecw` y se proponen COG o JP2. **La
compilación de GDAL que trae QGIS no incluye ECW ni para leer.**

Y para el caso corriente no hace falta. Está medido sobre material real
([PRUEBAS_CON_ORACULO.md](PRUEBAS_CON_ORACULO.md)):

| | Tamaño | PSNR | Error máx. |
| --- | ---: | ---: | ---: |
| JPEG 2000 | **13 %** del original | **51,7 dB** | **4** de 255 |
| TIFF con JPEG q92 | 10 % | 43,3 dB | 15 de 255 |

JPEG 2000 gana en los dos ejes a la vez, lleva la georreferencia dentro sin acompañantes, y
Civil 3D con Raster Design lo lee. No necesita licencia de nadie.

---

## Los archivos que viajan al lado

Un `.tif` sin su `.prj` es un `.tif` sin georreferencia, y **el síntoma es que la salida sale
bien pero está en el sitio equivocado** — el peor síntoma que existe. La aplicación los lista
en la ficha y avisa de los que faltan.

| Formato | Acompañantes |
| --- | --- |
| GeoTIFF | `.tfw` `.prj` `.aux.xml` `.ovr` `.msk` |
| JPEG 2000 | `.j2w` `.prj` |
| Shapefile | `.shx` `.dbf` `.prj` — **imprescindibles**, no opcionales |
| PNG · JPEG | `.pgw` `.jgw` `.wld` `.prj` |

**Pero la salida no debe necesitarlos.** GeoTIFF lleva el CRS en sus etiquetas y JPEG 2000 en
sus cajas GeoJP2 y GMLJP2. La prueba de que un entregable se basta a sí mismo es que
`gdalinfo` sobre él devuelva el CRS y su línea `Files:` nombre **un único archivo**.

---

## Qué pedir a quien entrega

La lista corta que conviene mandar tal cual:

1. **La ortofoto en GeoTIFF clásico, no BigTIFF**, salvo que de verdad pase de 4 GB sin
   comprimir. En Metashape es una casilla al exportar.
2. **Con el EPSG dicho** — para nuestros proyectos, normalmente **EPSG:32719** (WGS 84 /
   UTM 19S). Si el archivo lo trae dentro, mejor; si no, que venga escrito en el correo.
3. **El levantamiento en LAS o LAZ, sin convertir**, y **con su sistema de referencia
   declarado**. Una nube sin CRS no se puede cruzar con nada, y el dato se pierde para
   siempre si nadie lo apunta al entregarla.
4. **Los planos en DXF**, no en DWG. Es «Guardar como» en cualquier CAD.
5. **Si mandan un shapefile, que vaya completo**: `.shp`, `.shx`, `.dbf` y `.prj`.
