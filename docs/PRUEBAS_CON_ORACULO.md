# Pruebas con oráculo externo

Las pruebas del gate corren **sin GDAL**, a propósito: `verify.ps1` tiene que ser verde en
una máquina limpia. Pero la regla de la familia es que *un test que compara nuestra salida
con nuestra propia lectura no prueba nada*, así que existe esta segunda capa.

```powershell
uv run pytest -m oraculo
```

Y para lo que ni siquiera eso cubre —ECW, que exige la clave OEM— está este documento: el
procedimiento a mano, **con las cifras de la última corrida y su fecha**. Sin la fecha y las
cifras, la siguiente persona no puede distinguir una regresión nueva de algo que siempre
fue así.

---

## Corrida del 2026-09-08 — el entregable del cruce minero (BHP CC 716)

**Entorno.** GDAL 3.12.4 «Chicoutimi» (2026/04/22) y PDAL 2.10.0, los que trae
QGIS 4.0.2 en `C:\Program Files\QGIS 4.0.2\bin`. Windows 11.

**Archivo de entrada.** `Cruce Minero.tif`, ortofoto de Agisoft Metashape:

| | |
| --- | --- |
| Variante | BigTIFF (marca de versión `43`) |
| Dimensiones | 14.526 × 14.443 px · 209,8 Mpx |
| Bandas | 4 — RGB + alfa sin premultiplicar (`ExtraSamples = 2`) |
| Compresión | LZW, teselado 256 × 256 |
| Pirámides | 6 niveles internos |
| CRS | EPSG:32719 incrustado, y también en `.prj` y `.tfw` |
| GSD | 2,5577 cm/px · 372 m × 369 m de cobertura |
| Tamaño | 466,2 MB · 0,84 GB sin comprimir |

### 1. El lector propio contra `gdalinfo`

`apps/formats/tiff.py` no usa GDAL. Se contrastó su salida con la de `gdalinfo` sobre tres
archivos reales, y **coincide en todo**:

| Archivo | Variante | Dimensiones | Bandas | Pirámides (nuestro / GDAL) |
| --- | --- | --- | --- | --- |
| `Cruce Minero.tif` | BigTIFF | 14.526 × 14.443 | 4 | **6 / 6** |
| `Cruce_Minero_civil3d.tif` | clásico | 14.526 × 14.443 | 3 | **5 / 5** (+6 IFD de máscara, no contados) |
| `tile-0-0.tif` (DEM) | clásico | 3.720 × 3.780 | 1 (Float32) | **0 / 0** |

Dos cosas que este contraste enseñó y que están en el código:

- **Los IFD de la banda de máscara no son pirámides.** El archivo convertido tiene 12 IFD:
  1 principal, 5 reducciones y 6 de máscara. Contarlos todos daba 11 «pirámides», el doble
  de las reales.
- **Un IFD más pequeño sin `NewSubfileType` tampoco es una pirámide utilizable.** El DEM de
  Metashape tiene 4 IFD más chicos sin la etiqueta, y **`gdalinfo` reporta cero overviews**:
  sin la etiqueta GDAL no los usa, y por tanto QGIS tampoco. Contarlos habría prometido un
  zoom rápido que ningún programa va a dar. Se cuentan aparte, en
  `menores_sin_declarar`.

### 2. Calidad y peso de cada destino

Ventana central de **3.000 × 3.000 px × 3 bandas = 27.000.000 de muestras**, extraída con
`gdal_translate -of ENVI -srcwin 5763 5721 3000 3000` de cada archivo y comparada muestra a
muestra contra la misma ventana del original.

| Destino | Tamaño | % del original | PSNR | RMSE | Error máx. | Muestras idénticas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TIFF clásico LZW, 3 bandas | 316,7 MB | 68 % | ∞ | 0,00 | **0** | 100,00 % |
| **TIFF clásico DEFLATE-9, 3 bandas** | **283,3 MB** | **61 %** | **∞** | **0,00** | **0** | **100,00 %** |
| **JPEG 2000 (`QUALITY=25`)** | **60,0 MB** | **13 %** | **51,7 dB** | 0,66 | **4** | 61,48 % |
| TIFF con JPEG `q92` | 46,7 MB | 10 % | 43,3 dB | 1,74 | 15 | 26,41 % |
| TIFF con JPEG `q85` | 34,1 MB | 7 % | 41,0 dB | 2,27 | 22 | 21,31 % |

**El resultado que decide el valor por omisión: JPEG 2000 gana en los dos ejes a la vez.**
Con 60 MB tiene mejor fidelidad (51,7 dB, error máximo de 4 niveles sobre 255) que un TIFF
con JPEG `q92`, que pesa menos y se equivoca hasta en 15. No hay que elegir entre calidad y
tamaño: en este material JP2 domina a JPEG-en-TIFF.

Y **DEFLATE-9 es 33 MB más pequeño que LZW siendo igual de exacto**, así que LZW no tiene
ninguna ventaja aquí.

De ahí salen los dos valores por omisión del producto:

- **Entrega y uso en CAD** → JPEG 2000. Georreferencia dentro (cajas GeoJP2 y GMLJP2), sin
  acompañantes: `gdalinfo` lo lee con el `.jp2` solo, y su línea `Files:` nombra un único
  archivo.
- **Archivo maestro y cualquier cálculo posterior** → GeoTIFF clásico con DEFLATE-9.

### 3. Estadísticas por banda, entrada contra salida sin pérdida

`gdalinfo -stats` sobre el original y sobre el TIFF clásico de 3 bandas:

| Banda | mín | máx | media | desviación |
| --- | ---: | ---: | ---: | ---: |
| 1 (rojo) | 2 | 255 | 163,0840 | 30,6240 |
| 2 (verde) | 1 | 255 | 154,0230 | 29,0300 |
| 3 (azul) | 0 | 254 | 143,2740 | 27,2180 |

**Idénticas en las dos**, hasta el cuarto decimal.

### 4. De punta a punta, por la aplicación entera

Ya no es `gdal_translate` a mano: el archivo pasa por `ConversionJob` → `runner` → motor →
verificación.

| Destino | Tiempo | Salida | Lo que dijo `gdalinfo` al verificar |
| --- | ---: | ---: | --- |
| GeoTIFF clásico, DEFLATE, 3 bandas, 5 pirámides | 7,1 s | 285,0 MB | 14.526 × 14.443 · 3 bandas · GTiff · EPSG:32719 |
| JPEG 2000, calidad 25 | 9,4 s | 60,0 MB | 14.526 × 14.443 · 4 bandas · JP2OpenJPEG · EPSG:32719 |

Y el veredicto se invierte, que es el objetivo del producto. Leído con el lector propio,
sin GDAL:

```
Cruce Minero.tif          BigTIFF | 4 bandas | alfa=True  | EPSG:32719
                          Civil 3D -> NO ABRE: es BigTIFF

AEROCONVERT_civil3d.tif   TIFF clásico | 3 bandas | alfa=False | EPSG:32719
                          Civil 3D -> ABRE: abre tal cual
```

### 5. El progreso, que estuvo roto

Sobre el mismo archivo de 466 MB, contando los avisos de avance que llegan durante la etapa
de conversión:

| | Tics de progreso |
| --- | ---: |
| Leyendo la salida por líneas | **3** |
| Leyendo por trozos con `os.read` | **33** |

No era cosmético. GDAL escribe `0...10...20...` en una sola línea que va creciendo, sin
salto, así que por líneas no llegaba nada hasta el final — y **sin señales el detector de
atasco habría matado un motor sano** en cualquier ráster que tardase más que
`AEROCONVERT_SILENCIO_MAXIMO_S`.

### 6. La nube de puntos, contra `pdal info`

Archivo: `716 - Cruce minero.las`, 278,9 MB, del mismo vuelo.

El lector propio de cabecera LAS **no usa PDAL**, y coincide con él en todo:

| | Lector propio | `pdal info --summary` |
| --- | --- | --- |
| Versión | LAS 1.2 | 1.2 |
| Puntos | 9.618.692 | 9.618.692 |
| Formato de punto | 2 | 2 |
| Límites | 495003,24 – 495373,63 · 7318472,78 – 7318841,78 | idénticos |
| CRS | EPSG:32719 (de las geoclaves) | `WGS 84 / UTM zone 19S` |

Y deriva lo que PDAL no dice: **70,4 puntos/m², un punto cada 11,9 cm**, cobertura de
370 × 369 × 25,5 m — que cuadra con los 372 × 369 m de la ortofoto del mismo vuelo.

**El aviso de precisión se dispara sobre este archivo**: con el norte en 7,3 millones y una
escala de 1 cm, `float32` no llega.

### 7. LAS → COPC, de punta a punta

| | |
| --- | --- |
| Tiempo | 50,3 s |
| Entrada | 278,9 MB · LAS 1.2 · formato de punto 2 · sin comprimir |
| Salida | **76,4 MB** (−73 %) · LAS 1.4 · formato de punto 7 · COPC |
| Puntos | 9.618.692 → **9.618.692** |
| Extensión | 370,39 × 369,00 × 25,45 m, sin cambio |
| CRS | EPSG:32719 conservado (como `COMPD_CS`) |

La verificación compara la cuenta de puntos contra la del original y **rechaza la salida si
faltan puntos sin haber pedido diezmar**. Es el fallo silencioso propio de esta familia: una
conversión que se come la mitad de la nube deja un archivo que abre, se ve bien, y le falta
media obra.

Y el veredicto se invierte igual que con el ráster:

```
716 - Cruce minero.las      LAS 1.2 · fmt 2 · no comprimido
                            AeroBim -> NO ABRE: solo lee COPC, y esta no lo es

AEROCONVERT_nube.copc.laz   LAS 1.4 · fmt 7 · COPC
                            AeroBim -> ABRE: se abre por rangos
```

### 8. El original quedó intacto

`488.815.770` bytes y la misma fecha de escritura antes y después de las cinco
conversiones.

---

## Lo que sigue sin oráculo, y se dice

**ECW no se puede verificar aquí.** El GDAL de QGIS 4.0.2 **no trae el controlador ECW**, ni
siquiera de lectura — se comprobó con `gdalinfo --formats`. Escribirlo exige además la clave
OEM de Hexagon. Mientras no haya una instalación con la SDK, la fila ECW de la matriz
aparece apagada con el motivo `sin-driver-ecw`, y no hay ninguna prueba que finja lo
contrario.

Cuando exista esa instalación, el procedimiento es el mismo de la sección 2, y sus cifras se
anotan aquí con su fecha.

## Cómo repetir la medición

```powershell
$gt = "C:\Program Files\QGIS 4.0.2\bin\gdal_translate.exe"
```

```powershell
& $gt -q -of ENVI -ot Byte -b 1 -b 2 -b 3 -srcwin 5763 5721 3000 3000 <entrada> <salida>.bin
```

Y luego se comparan los `.bin` muestra a muestra. La ventana se toma del centro a propósito:
los bordes de una ortofoto son transparencia y comprimirían de forma poco representativa.
