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
