# Motores: qué necesita cada conversión y cómo se detecta

La aplicación no trae ninguna herramienta de conversión dentro. Las **sondea** al arrancar y
lo que falta apaga su fila de la matriz con un motivo escrito.

Para ver qué encuentra esta máquina:

```powershell
pwsh scripts/sondear.ps1
```

---

## La sutileza que decide media matriz

**Que el controlador esté no significa que sepa escribir.**

El controlador ECW de GDAL **lee siempre**. Escribir necesita además la SDK con clave OEM de
Hexagon. Comprobar `gdal.GetDriverByName("ECW")` y dar la conversión por buena es lo que
produce un trabajo que corre veinte minutos y muere al final.

Por eso las sondas miran las banderas de capacidad, no solo la presencia:

```
  GTiff -raster- (rw+uvs): GeoTIFF (*.tif, *.tiff)
                  ↑↑
                  r = lee, w = escribe, + = crea
```

Y por eso ECW tiene **tres** motivos distintos, porque son tres arreglos distintos.

## Las sondas

| Sonda | Qué comprueba | Motivo si falla |
| --- | --- | --- |
| `sondar_gdal()` | `gdalinfo --version` y `--formats`; construye el conjunto de controladores **y el de los que escriben** | `motor-no-disponible` |
| `sondar_proj()` | que `PROJ_DATA` o `PROJ_LIB` apunten a una carpeta con `proj.db` | `proj-descolocado` |
| `sondar_ecw()` | binario externo, o controlador **+** capacidad de escritura **+** clave y empresa | `sin-binario-ecw` · `sin-driver-ecw` · `sin-clave-ecw` |
| `sondar_pdal()` | `pdal --version` | `motor-no-disponible` |
| `sondar_oda()` | que la ruta configurada apunte a un archivo, o que esté en el `PATH` | `sin-conversor` |
| `sondar_trimble_rinex()` | que la ruta (configurada o la de Trimble Business Center) sea un archivo; en Linux, además `wine` | `sin-conversor-trimble`, `sin-wine` |

### Dos reglas heredadas de AeroBim

**Una sonda no ejecuta una conversión.** Nunca.

**Y a ser posible tampoco lanza el programa.** `estado_del_conversor()` de AeroBim lo dice
literal: *«no se lanza el programa para preguntarle su versión: arrancarlo cuesta segundos y
esto se consulta al pintar una página»*. Aquí hay una excepción medida — GDAL, del que hay
que enumerar controladores — y por eso se cachea diez minutos.

### Un detalle que costó una corrida

`pdal --version` abre con una fila de guiones a modo de banner. Quedarse con la primera
línea daba una versión que era `-----------`. Por eso `_preguntar_version()` acepta un
parámetro `contiene`: no todas las herramientas contestan en la primera línea.

## PROJ descolocado

Mezclar el GDAL de una instalación con el `proj` de otra **no falla limpiamente**: o dice
«Cannot find proj.db», o reproyecta con datos equivocados y entrega un archivo que parece
bien. Lo segundo es mucho peor, y por eso tiene motivo propio.

El `PATH` de GDAL se antepone **al del proceso hijo**, jamás al del servidor.

## Los motores de hoy

| Motor | Familia | Pares | Necesita |
| --- | --- | ---: | --- |
| `gdal-raster` | ráster | 80 | GDAL + PROJ |
| `gdal-ecw` | ráster | 10 | GDAL con SDK de Hexagon y clave OEM |
| `gdal-curvas` | ráster → vector | 15 | GDAL (`gdal_contour`) + PROJ |

`gdal-curvas` saca **curvas de nivel** de un modelo de elevación (GeoTIFF, BigTIFF, COG, IMG o ASCII
Grid → DXF, Shapefile o GeoPackage) con un intervalo y una cota de partida. La banda 1 es la altura.
El Shapefile y el GeoPackage llevan la cota en el campo `ELEV`; el DXF la lleva en la elevación de cada
polilínea, y para eso **pasa por un GeoPackage 3D**: `gdal_contour` escribe el DXF directo sin la cota
(se midió: 29 polilíneas planas). El DXF no guarda el sistema de coordenadas, y el recibo lo dice. El
DWG espera a ODA (F15.8).

`gdal-ecw` está **separado a propósito** y no es un destino más de `gdal-raster`. Si ECW
fuera un destino más, al faltar la clave la fila entera se apagaría con el motivo
equivocado — y GDAL sí está.

## Lo que ve esta máquina hoy

Con QGIS 4.0.2 instalado (`C:\Program Files\QGIS 4.0.2\bin`):

```
GDAL   OK      GDAL 3.12.4 "Chicoutimi", released 2026/04/22
               lee 137 controladores, escribe 61
                 GTIFF         lee y escribe
                 COG           lee y escribe
                 JP2OPENJPEG   lee y escribe
                 ECW           NO ESTA
                 MRSID         NO ESTA
                 HFA           lee y escribe
PROJ   OK      C:\Program Files\QGIS 4.0.2\share\proj\proj.db
PDAL   OK      pdal 2.10.0
ECW    FALTA   [sin-driver-ecw] ... en su lugar sirven: cog, jp2
ODA    FALTA   [sin-conversor]  ... en su lugar sirve: dxf

disponible      80 conversiones
instalable      10 conversiones (10 por sin-driver-ecw)
no-soportado     0 conversiones
```

**La compilación de GDAL que trae QGIS no incluye ECW ni para leer**, y la de conda-forge
tampoco. Es un dato útil: quien espere abrir un ECW con QGIS recién instalado se va a llevar
una sorpresa.

## Cómo se añade un motor

1. Subclase de `Motor` en `apps/<familia>/motores.py`.
2. `pares()` devuelve lo que sabe hacer, **esté o no disponible**.
3. `disponibilidad()` usa una sonda; si falla, devuelve motivo, sugerencia y **alternativas**.
4. `opciones()` describe los ajustes — de ahí sale el formulario.
5. `plan()` construye el `argv` completo.
6. Se registra en `registrar_todos()`.
7. Una prueba compara el `argv` **entero y en orden** con `assertEqual` sobre la tupla.

El paso 7 no es opcional. Es la lección de los seis argumentos posicionales de ODA.

## El motor abierto: RTKLIB `convbin` (`apps/gnss/`)

| | |
| --- | --- |
| Id | `rtklib-convbin` |
| Pares | `rtcm3`, `ubx`, `novatel`, `sbf`, `rt17`, `binex`, `javad` → `rinex` |
| Programa | `convbin` de RTKLIB (BSD-2). Nativo, sin Wine |
| Sonda | `sondar_rtklib()`: `AEROCONVERT_RTKLIB_CONVBIN`, o `convbin` en el `PATH` |
| Plazo | 300 s + 20 s por MB |

Comparte con el de Trimble el empaquetado en zip y el verificador (`verificar_rinex`): abre
cada archivo, exige épocas, la versión pedida y que no estén cortados. **No lee T01/T02/T04.**
Los formatos se reconocen solo por la extensión (`.rtcm3`, `.ubx`, `.gps`, `.sbf`, `.rt17`,
`.bnx`, `.jps`): no tienen firma de archivo, y lo que decide es lo que sale. El RTCM 3 no trae
la semana GPS: se ofrece una fecha aproximada; sin ella, `convbin` usa la del archivo en disco.

## El motor de Trimble a RINEX (`apps/gnss/`)

| | |
| --- | --- |
| Id | `trimble-rinex` |
| Par | `trimble_t0x` → `rinex` |
| Programa | `convertToRinex.exe` de Trimble, de Windows. En Linux, bajo Wine |
| Sonda | `sondar_trimble_rinex()`: `AEROCONVERT_TRIMBLE_RINEX`, o la ruta de Trimble Business Center |
| Plazo | 300 s + 30 s por MB (Windows) o 90 s por MB (Wine). **Medido: unos 10 s por MB en Windows** |
| Salida | un `.zip` con las observaciones y la navegación |

**El convertidor sale con código 0 y escribe «Success» siempre** — con un archivo vacío, con
200 bytes de basura (deja un RINEX de 1.476 bytes, solo cabecera) y con un T02 cortado a la
mitad (entrega un RINEX más corto sin avisar). Por eso el motor no se fía de él:

1. **Antes**, `trimble.comprobar_integridad()` recorre los bloques bzip2 del crudo y se
   detiene con `crudo-incompleto` si el último no llega a su final.
2. **Después**, `empaquetar.py` exige que haya archivos con contenido, y `verificar_rinex()`
   abre cada uno del zip con `rinex.py` y exige épocas, la versión pedida y que no estén
   cortados. Huecos y falta de navegación **avisan** sin tumbar.
3. El receptor que declara el crudo se **cruza** con el que declara el RINEX: dos lectores
   distintos opinando sobre lo mismo.

Se prueba con un convertidor falso que reproduce esos modales (`apps/gnss/tests/`), en la
puerta de calidad, y con el programa real bajo la marca `oraculo`.
