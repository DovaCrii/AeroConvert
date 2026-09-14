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

## Corrida del 2026-09-11 — las herramientas de PDF, sobre documentos de oficina

Aquí el oráculo **no es otra herramienta de línea de comandos, es el dibujo**: se pinta la
página con PDFium y se mira dónde cayó la tinta. Para la geometría no hay alternativa
honesta —comprobar la posición contra el mismo cálculo que la produjo sería el código
dándose la razón— y el fallo que se busca no se ve de ninguna otra forma: un número de
página colocado en el sistema de coordenadas equivocado da un archivo que abre, imprime, y
está mal.

Lo que *dice* cada marca lo lee el extractor de texto de pypdf, que no sabe nada de cómo se
escribió.

### 1. Lo que traen dentro, medido sin abrirlos

| Archivo | Lo que dice AeroConvert |
| --- | --- |
| `Xgrids Lixel L2 PRO - Puntos de control.pdf` | 5 páginas · **Carta** vertical |
| `Organigrama 20261902.pdf` | 1 página · **866 × 802 mm apaisada** |
| `LCD-0240-PP-GEN-11003_P1.pdf` | 1 página · Tabloide apaisada |
| `4985-0240-GE-INF-001_B.pdf` | 59 páginas · **tamaños mezclados** |
| `TOTAL_RASTREO.pdf` · `Monografia_5-6.pdf` | 1 página · A4 apaisada / A4 vertical |

Dos cosas que confirman decisiones del catálogo: **Carta no es A4** y se distingue, y una
hoja de 866 × 802 mm no se fuerza dentro de ningún formato con nombre — se dice en
milímetros, porque inventarle un nombre sería mentir.

### 2. PDF a imágenes, a 150 ppp

Sobre la hoja Carta: **1275 × 1651 px**, que es exactamente lo que sale de 8,5 × 11 pulgadas
a 150 ppp. El mismo dibujo en los dos formatos:

| | Peso |
| --- | ---: |
| PNG | 289 KB |
| JPG | 123 KB — el **42 %** |

Esa proporción es la razón de que la pantalla ofrezca los dos y diga para qué sirve cada uno.

### 3. Proteger, sobre un documento real

Cifrado con AES-256 y comprobado **reabriéndolo**: pide clave, la correcta abre, otra no. La
vuelta —quitar la contraseña— devuelve el mismo número de páginas, los mismos formatos y las
mismas orientaciones, sobre una hoja de 866 × 802 mm.

### 4. Numerar, sobre 59 páginas de tamaños mezclados

`4985-0240-GE-INF-001_B.pdf`: **59 numeradas**, y los 59 tamaños y orientaciones idénticos
antes y después. Es el caso para el que la capa se dibuja **por página**: una sola capa
reutilizada dejaría el número fuera del papel en cuanto cambia el formato.

### 5. El giro, sobre una lámina escaneada de verdad

Lo importante, porque es donde falla en silencio. Una bitácora de vuelo escaneada:

```
caja (MediaBox)     593 x 764 pt   -- vertical
/Rotate             270
lo que se ve        269 x 209 mm   -- APAISADA
```

Es la trampa entera en tres líneas: la caja dice vertical y el documento **se ve apaisado**.

Se numeró en «pie, a la derecha» y se comparó el centro de gravedad de la tinta con el de la
misma página sin numerar:

```
tinta   (0,4814, 0,2732)  ->  (0,4834, 0,2764)
         x +0,0020            y +0,0031
```

**Los dos signos positivos**: el número empujó la tinta hacia la derecha y hacia abajo de lo
que se ve. El desplazamiento es pequeño porque el escaneo cubre casi toda la hoja, pero la
dirección no es ambigua — si la capa hubiera caído de canto en un lateral, que es el fallo
clásico, empujaría en otra.

Las cuatro rotaciones están además cubiertas en el gate con páginas fabricadas
(`apps/documents/test_marcas.py`), ocho casos, con el mismo oráculo de píxeles.

### 6. Marca de agua

Sobre los cuatro documentos: añadirla **acerca** el centro de gravedad de la tinta al centro
de la hoja en todos, y en ninguno lo aleja. Y las tres intensidades dejan la hoja
progresivamente menos clara —medido, no nombrado—, que es lo que hace que «suave», «normal»
y «marcada» signifiquen algo.

### 7. Los originales quedaron intactos

Comprobado byte a byte en todas las operaciones anteriores. Las salidas se escribieron en la
carpeta temporal de las pruebas, nunca junto a los originales.

### 8. Office a PDF, contra el PDF que exportó Word a mano

Este tiene **el mejor oráculo de toda la corrida**, y fue suerte: en la carpeta de una minuta
está el `.docx` y, al lado, el PDF que alguien exportó desde Word en su día. Si lo que sale
por la aplicación coincide con eso, lo que se entrega es lo mismo que se entregaría a mano.

`Minuta 002 Reunión Tecnico Contractual 05-11-2025.docx` → PDF, en **16,7 s**:

| | Mío | El exportado a mano |
| --- | --- | --- |
| Páginas | 6 | 6 |
| Formato y orientación | Carta vertical ×6 | Carta vertical ×6 |
| Páginas idénticas palabra por palabra | 1, 2, 3, 4, 6 | |
| Texto total | 9.100 caracteres | 9.099 |

**La diferencia es un solo espacio**, en la página 5. Ignorando los espacios, los dos textos
son idénticos carácter por carácter — así que no es contenido ni maquetación: es el
extractor de pypdf infiriendo un espacio donde el otro no lo pone. (El `.docx` además se
guardó cuatro segundos *después* de exportarse aquel PDF, así que ni siquiera es seguro que
sean la misma revisión.)

### 9. Excel, y por qué el ajuste de ancho no es un capricho

El mismo libro de curvas de avance, exportado de las dos maneras:

| | Páginas | Tiempo |
| --- | ---: | ---: |
| Tal cual | **68** | 7,5 s |
| Encajando cada hoja a lo ancho de una página | **6** | 2,9 s |

Una hoja de cálculo **no tiene tamaño de papel**. Sin ajustar, el libro sale partido en
columnas por sesenta y ocho hojas, que no es un PDF peor: es un PDF inservible. Esa cifra
—68 contra 6— es la que está escrita en la propia pantalla, junto a la casilla.

### 10. PowerPoint, y la trampa de su firma

`Organigrama CC 716.pptx` → 3 páginas de **339 × 190 mm apaisadas**, que es una presentación
16:9. En 5,3 s.

Costó un intento: `ExportAsFixedFormat` de PowerPoint tiene dieciséis parámetros opcionales y
el enlace tardío de PowerShell no consigue pasarle el enum —responde *«no se puede convertir
el valor 2 de tipo int al tipo Object»*—. Se hace con `SaveAs($ruta, 32)`, que tiene una
firma simple. Word y Excel sí usan `ExportAsFixedFormat`, **y con los argumentos en orden
distinto entre ellos**: Word `(ruta, tipo)`, Excel `(tipo, ruta)`.

### 11. El camino de vuelta: cuánto sobrevive de un PDF a Word

El mismo PDF de la minuta, a `.docx` (5,0 s) y de ahí otra vez a PDF para poder compararlo:

| | Original | Ida y vuelta |
| --- | --- | --- |
| Páginas | 6 | **8** |
| Caracteres de texto | 9.099 | 9.299 |
| Palabras distintas | 698 | 722 |
| **Se conservan** | | **682 — el 97,7 %** |

Lo que se pierde son sobre todo códigos partidos y palabras pegadas a un signo
(`LCD-0000-CL-TRE-`, `(shp/kmz)`, `11305)`), que es exactamente lo que cabe esperar de
reconstruir párrafos a partir de posiciones de letras.

**La paginación sí se mueve: 6 → 8.** Esa es la cifra que está escrita en la pantalla, y el
motivo de que la herramienta se presente como «para reaprovechar el texto», no como «para
recuperar el documento».

### 12. Los dos fallos silenciosos que solo aparecen con archivos de verdad

**Un PDF escaneado se «convierte» perfectamente.** La bitácora de vuelo: **cero caracteres**
extraíbles, y aun así Word devuelve un `.docx` de **497 KB** con código de salida **0**.
Dentro están las mismas fotos y ni una palabra editable. Se detecta antes de convertir
—contando el texto de las primeras cinco páginas— y la pantalla no ofrece el botón.

**Y a Word le vale cualquier cosa.** Un archivo con el contenido `no soy un pdf` y la
extensión `.pdf` lo abre como texto plano, lo guarda como `.docx` y sale con **0**. La firma
se comprueba ahora en Python, antes de lanzar el hijo.

**No quedaron procesos huérfanos** tras ninguna de las conversiones: `tasklist` no encuentra
ningún `WINWORD.EXE` vivo. El `finally` del guion hace su trabajo.

---

## Corrida del 2026-09-14 — el paseo de aceptación, sobre una instalación limpia

No es una prueba de conversión: es la comprobación de que **una instalación nueva funciona de
punta a punta por HTTP**. Base vacía, carpetas vacías, usuario recién creado.

### 1. La instalación

| Paso | Resultado |
| --- | --- |
| `migrate` sobre base vacía | 26 migraciones, sin un error |
| `check --deploy` con `config.settings.prod` | **sin una sola queja** |
| `collectstatic --clear` | 167 archivos, **483 post-procesados** |
| `createsuperuser --noinput` | ✅ |

### 2. La sonda de salud, con todo en verde

```json
{"estado": "ok", "modo": "taller",
 "base": {"ok": true, "encolados": 0, "ejecutando": 0},
 "despachador": {"ok": true, "dentro_del_web": true},
 "origenes": {"ok": true, "raices": 1, "legibles": 1},
 "disco": {"ok": true, "libre_gb": 485.9},
 "estaticos": {"ok": true, "manifiesto": true}}
```

Las cinco comprobaciones contestan, y el despachador dejó su latido en la carpeta de trabajo.

### 3. El manifiesto de estáticos, que es lo que más ha costado históricamente

```
hoja: /static/css/app.7c07e66279c4.css
      200 · 27.483 bytes · Cache-Control: public, max-age=315360000, immutable
```

**Con huella de contenido y `immutable`.** Es el arreglo del fallo que se disfrazaba de error
de diseño —HTML nuevo con la hoja vieja— funcionando en una instalación nueva.

### 4. Subir, componer y descargar, por HTTP de verdad

Dos PDF de 3 y 2 páginas subidos con `multipart/form-data`:

| | |
| --- | --- |
| Identificadores devueltos | **2** |
| Receta generada | `0:1:0,0:2:0,0:3:0,1:1:0,1:2:0` — las cinco páginas, en orden |
| **¿Se ve la ruta del servidor en el HTML?** | **No** |
| Enlace de descarga | `/documentos/descargar/1a6af9c0-…/` |
| La descarga | 200 · 981 bytes · `filename="uno_unido.pdf"` |
| El PDF resultante | **5 páginas, A4 vertical** |

La cuarta fila es la prueba de la fuga hecha contra el servidor real: si el campo devolviera
la ruta de `MEDIA_ROOT`, el POST siguiente la trataría como una ruta del disco del servidor.

### 5. Y dónde quedó cada cosa

```
medios/subidas/21f5831a-…/uno.pdf     713 B
medios/subidas/d9bd3058-…/dos.pdf     579 B
trabajo/uno_unido.pdf                 981 B
trabajo/.despachador                    0 B
```

Cada subida **en su propia carpeta y con su nombre intacto** — que es el motivo de que el
identificador esté en la ruta y no en el nombre del archivo. Y los dos originales de la
carpeta compartida, con sus 3 y 2 páginas, **sin tocar**.

---

## Lo que sigue sin oráculo, y se dice

**ECW no se puede verificar aquí.** El GDAL de QGIS 4.0.2 **no trae el controlador ECW**, ni
siquiera de lectura — se comprobó con `gdalinfo --formats`. Escribirlo exige además la clave
OEM de Hexagon. Mientras no haya una instalación con la SDK, la fila ECW de la matriz
aparece apagada con el motivo `sin-driver-ecw`, y no hay ninguna prueba que finja lo
contrario.

Cuando exista esa instalación, el procedimiento es el mismo de la sección 2, y sus cifras se
anotan aquí con su fecha.

**LandXML tampoco lo tiene, y por un motivo distinto.** No falta una licencia: es que **OGR
no trae controlador de LandXML**, ni de lectura ni de escritura — comprobado con
`ogrinfo --formats`. No hay una segunda herramienta a la que preguntarle si el archivo está
bien, y comprobarlo con nuestro propio lector sería el código dándose la razón.

Lo que sí se comprueba en automático, y basta para atrapar el fallo que de verdad ocurre —un
archivo válido, vacío o a medias—:

- que el XML esté **bien formado**, según el analizador de la biblioteca estándar;
- que traiga **tantos `<CgPoint>` como puntos** tenía la libreta;
- que el contenido de cada punto sea **norte, este, cota**, fijado contra un ejemplo escrito
  a mano en `apps/vector/test_landxml.py`.

### El procedimiento manual, pendiente

Son cinco minutos en un puesto con Civil 3D, y **es la aceptación de verdad**:

1. Convertir `puntos control cruce minero.csv` con el destino **Civil 3D**, declarando
   EPSG:32719. Sale `puntos control cruce minero_civil3d.xml`.
2. En Civil 3D: **Insertar → LandXML**, elegir el archivo, aceptar.
3. Comprobar cuatro cosas, que son las que pueden fallar sin dar error:
   - aparecen **5 puntos**, no uno (un `name` repetido o vacío los machaca en silencio);
   - los números son **P1…P5** y no correlativos inventados;
   - la **descripción bruta** de cada uno es `pr`;
   - el punto P1 cae en **N 7.318.729,036 · E 495.279,406 · cota 3.042,641**. Si norte y este
     salieran cambiados, el grupo aparecería a 9.650 km.
4. Anotar aquí el resultado con la fecha y la versión de Civil 3D.

## Cómo repetir la medición

```powershell
$gt = "C:\Program Files\QGIS 4.0.2\bin\gdal_translate.exe"
```

```powershell
& $gt -q -of ENVI -ot Byte -b 1 -b 2 -b 3 -srcwin 5763 5721 3000 3000 <entrada> <salida>.bin
```

Y luego se comparan los `.bin` muestra a muestra. La ventana se toma del centro a propósito:
los bordes de una ortofoto son transparencia y comprimirían de forma poco representativa.
