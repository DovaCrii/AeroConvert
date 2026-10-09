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

## Corrida del 2026-10-05 — crudos de Trimble a RINEX

**Entorno.** Windows 11, **nativo** (no bajo Wine; eso está sin probar). `convertToRinex.exe`
4.0.1.9 («Convert To RINEX — TBC utility»), instalado con Trimble Business Center en
`C:\Program Files (x86)\Trimble\convertToRINEX\`; su instalador es
`ConvertToRinex_v3.14.0.msi` (1,6 MB). Los datos quedan **fuera del repositorio**.

**Archivos de campo.**

| | T02 | T04 |
| --- | --- | --- |
| Receptor | Trimble NetR9, serie 5303K49763 | Trimble R12i, serie 6212F01411 |
| Tamaño | 1.207.675 B | 3.123.464 B |
| Empieza por | `00 00 00 0d`, y `BZh1` en el byte 21 | `00 00 00 0d`, y `BZh3` en el byte 21 |
| Bloques bzip2 | 54, todos completos | 45, todos completos |

### 1. La conversión, y lo que el convertidor dice de sí mismo

`convertToRinex.exe <entrada> -p <carpeta>` — por omisión escribe RINEX 3.04:

| | T02 | T04 |
| --- | --- | --- |
| Tiempo | 14,2 s | 31,9 s |
| Salidas | `.23o` 9.284.918 B, `.23n` (GPS), `.23g` (GLONASS), `.23l` (Galileo) | `.23o` 16.207.362 B, y las tres de navegación |
| Con `-mx` | `.23o` y `.23mix` (88.881 B), 3,8 s | — |

Los nombres son **cortos, de RINEX 2** (`GMLA202301311700A.23o`), aunque el contenido es 3.04.

### 2. Lo que dicen las salidas, leídas con `apps/formats/rinex.py`

| | T02 | T04 |
| --- | --- | --- |
| Versión | 3.04 | 3.04 |
| Épocas | **3.600** a 1 Hz | **8.727** a 1 Hz |
| De / a | 2023-01-31 17:00:00 / 17:59:59 | 2023-02-28 11:21:55 / 13:47:21 |
| Huecos | 0 (3.600 esperadas) | 0 (8.727 esperadas) |
| Coincide con `TIME OF FIRST/LAST OBS` | sí | sí |
| Receptor que declara | `TRIMBLE NETR9` | `TRIMBLE R12i` |
| Constelaciones | E G R | E G R |

El receptor del RINEX **coincide** con el que `trimble.py` saca del bloque bzip2 del crudo:
son dos lectores distintos opinando sobre lo mismo.

### 3. Lo que el convertidor hace mal, sin avisar

Probado con copias en una carpeta temporal. En **todos** estos casos sale con **código 0** y
escribe «Success»:

| Entrada | Lo que escribe |
| --- | --- |
| Archivo vacío (0 bytes) | `.26o` de 1.476 B: solo cabecera, **ninguna época** |
| 200 bytes de basura | lo mismo |
| El T02 **cortado por la mitad** | un `.23o` de 4,5 MB, la mitad: **RINEX válido, más corto, sin una palabra** |
| Archivo que no existe | no escribe nada y dice `Error: … unable to open file` (el único que avisa) |

Es la regla número uno en estado puro. De ahí salen las dos defensas del motor:

- **Antes**: `trimble.comprobar_integridad()` recorre los bloques bzip2. Con el T02 cortado:
  27 candidatos, 26 completos y **1 cortado**. Con los dos enteros: ninguno cortado.
- **Después**: sin épocas, `rinex-sin-epocas`; cortado a mitad de una época, `rinex-invalido`.

### 4. Corrida del corredor entero, con el programa real

`uv run pytest -m oraculo apps/gnss/tests/test_con_trimble_real.py`, con las rutas en
`AEROCONVERT_PRUEBA_T02` y `AEROCONVERT_PRUEBA_T04`. Los dos pasan: **HECHO, 3.600 y 8.727
épocas, sin huecos, el original con el mismo `sha256` y `mtime`, y nada en la carpeta de
trabajo al terminar.**

### 5. La versión 4.0.1.10, que entregó la persona el mismo día

`convertToRinex_v4_0_1_10_sign.msi` (2.319.872 B, firma Authenticode válida de Trimble Inc.).
**No se instaló**: se extrajo a una carpeta temporal con `msiexec /a` y se corrió desde allí,
con las mismas opciones del motor (`-v 3.04 -mx -d -s`) y salida fuera del original.

| Crudo | Versión 4.0.1.9 (instalada con TBC) | Versión 4.0.1.10 |
| --- | --- | --- |
| T02 NetR9 | 14,2 s · 3.600 épocas, 17:00:00 a 17:59:59 | 4,5 s · 3.600 épocas, 17:00:00 a 17:59:59 |
| T04 R12i | 31,9 s · 8.727 épocas, 11:21:55 a 13:47:21 | 9 s · 8.727 épocas, 11:21:55 a 13:47:21 |

Con la 4.0.1.10: RINEX 3.04, `apps/formats/rinex.py` lee la cabecera y las épocas, sin huecos ni
truncado, y el receptor coincide con el del crudo. **El mismo CLI y el mismo resultado**, en menos
de la mitad del tiempo (las dos corridas no son del mismo minuto ni se repitieron: lo de la
velocidad es una medida, no una promesa). Una diferencia: con `-mx` la navegación sale como
**un solo `.23mix`** (88 KB y 200 KB) además del `.23o`; el empaquetado del motor la recoge
porque zipa todo archivo con contenido. Los plazos del motor (30 s por MB) quedan holgados.

### 6. RTKLIB `convbin`, medido con el que trae Trimble Business Center

`C:\Program Files\Trimble\Trimble Business Center\convbin.exe` es el `convbin` de RTKLIB
(la ayuda lista RT17, SBF, UBX, RTCM 3, BINEX y RINEX). Se corrió **solo** como oráculo de
la ruta, sin copiarlo ni redistribuirlo, con el RINEX del T02 de la sección 5 como entrada:
`convbin -r rinex -v 2.11 -d <carpeta> GMLA202301311700A.23o`. Salió con código 0 en 1 s,
`GMLA202301311700A.obs` de 15,9 MB, y `apps/formats/rinex.py` lo lee: **versión 2.11, 3.600
épocas, 17:00:00 a 17:59:59, sin huecos ni truncado**. Dos hallazgos: con `-d` los nombres
salen del archivo de entrada (`<nombre>.obs`, `<nombre>.nav`), y el receptor del RINEX sale
vacío, así que el cruce con el receptor del crudo es solo de Trimble.

**No medido**: un flujo real UBX, SBF, RT17, NovAtel, RTCM 3, BINEX o Javad. No hay ninguno en
esta máquina. Las pruebas del motor son de `argv` y de veredicto; la conversión de un flujo
queda pendiente en p340 con `apt install rtklib`.

### 7. La calidad del RINEX, contra un recuento independiente

`rinex_calidad.calcular()` sobre el RINEX 3.04 del T02 (3.600 épocas): 17 a 21 satélites por
época (media 18,6), 23 distintos, 86,0 % de las observaciones posibles presentes (GPS 363.152 de
410.160, GLONASS 317.152 de 431.940, Galileo 316.964 de 316.992). **Oráculo**: un recuento
hecho en PowerShell, sin `rinex.py`, de las líneas que empiezan por `G` después de
`END OF HEADER`: **25.635**, igual que la suma de épocas de los satélites GPS del informe. Es
un oráculo de recuento, no de calidad: no dice si 86 % es bueno, solo que se cuenta lo que hay.

### Lo que esta corrida **no** prueba

- **Bajo Wine.** Todo lo anterior es Windows nativo. El plazo bajo Wine (90 s por MB) es una
  estimación a partir de la receta pública (~3× más lento), no una medida.
- **Que el RINEX esté completo frente al crudo.** El T0x es un formato cerrado: no hay
  oráculo. Se cuenta lo que hay y se compara consigo mismo (cabecera contra épocas), no con lo
  que grabó el receptor. **Un corte justo entre dos bloques** deja un archivo con todos sus
  bloques completos y no se ve. Procedimiento manual: abrir el mismo T02 en Trimble Business
  Center y comparar épocas y hora de inicio y fin con las del recibo.
- **Más de dos archivos.** La detección y la integridad se midieron con un T02 y un T04; otros
  receptores (R10, Alloy, NetR9 con otro firmware) pueden traer otra estructura.

---

## Corrida del 2026-10-06 — la paleta en OKLCH (F9.5)

**Oráculo: el navegador.** Convertir la paleta a `oklch()` solo es correcto si el navegador pinta
**el mismo byte** que pintaba el hexadecimal. La fórmula de `apps/core/oklch.py` contra sí misma
no prueba eso, así que cada token se pintó en un `<canvas>` 1×1 y se leyó el píxel
(`getImageData`), y se comparó con el hex original.

| Bloque de `app.css` | Tokens | Idénticos |
| --- | --- | --- |
| `:root` (claro) | 32 | 32 |
| `:root[data-theme="dark"]` | 32 | 32 |
| `@media (prefers-color-scheme: dark)` | 31 | 31 |

**95 de 95, canal por canal.** Con 4 decimales de L, 4 de C y 2 de H, ninguno se desvía ni un
byte. `test_oklch.py` guarda además la paleta hexadecimal anterior como foto (`PALETA_ANTERIOR`) y
exige que cada `oklch()` del CSS vuelva a ese hex; `test_paleta.py` sigue midiendo el contraste
WCAG sobre sRGB, convirtiendo cada token con `a_hex()`.

**Repetir:** abrir cualquier pantalla, y en la consola leer `getComputedStyle(documentElement)`
por cada `--av-*`, pintarlo en un canvas y comparar con el hex de `PALETA_ANTERIOR`; hacerlo con
`data-theme` en `light`, `dark` y ausente con el esquema del sistema oscuro.

**Fuera de alcance, dicho:** quedan 49 literales hexadecimales que no son tokens (reglas sueltas)
y `templates/500.html`, que no carga el CSS. No se tocan: no son paleta.

---

## Corrida del 2026-10-08 — un vuelo real contra Trimble Business Center (F18.2, F18.6)

**Datos** (fuera del repositorio): vuelo de un **DJI Matrice 3E**, 2025-12-29, 2 505 fotos, en
Baquedano. El `.MRK` del dron (2 505 disparos), la trayectoria que sacó Trimble Business Center
(7 519 puntos a 5 Hz, sin huecos, de 15:38:13 a 16:03:16 GPST) y las posiciones PPK de las 2 505
fotos que sacó su UAS sync. Pasan con `AEROCONVERT_VUELO_DE_PRUEBA=<carpeta>` y
`pytest -m oraculo apps/vuelos/test_vuelo_real.py`.

**Qué se compara:** la posición de cada foto que calcula `vuelo_sync` (interpolar la trayectoria
en el instante del disparo y aplicar el desfase de la antena) contra la que entregó Trimble.

| Componente | Desviación | Peor caso |
| --- | ---: | ---: |
| Norte | 0,30 mm | 0,73 mm |
| Este | 0,33 mm | 0,90 mm |
| Altura | 0,28 mm | 0,50 mm |

Es el **redondeo a tres decimales** del CSV de Trimble: no queda diferencia que explicar.

**El signo del desfase se midió, no se supuso.** Probando las cuatro combinaciones contra Trimble:

| Norte, Este, V | Desviación N, E, U (mm) |
| --- | --- |
| sin aplicar | 28,9 · 11,1 · 3,3, con la altura **85,8 mm** corrida |
| **N +, E +, V −** | **0,30 · 0,33 · 0,28** |
| N +, E +, V + | 0,30 · 0,33 · 6,50, con la altura **171,6 mm** corrida |
| N −, E −, V − | 57,8 · 22,0 · 0,28 |

Es decir: norte y este se **suman**, y `V` es positivo **hacia abajo**: la cámara cuelga por debajo
de la antena.

**El sistema de las coordenadas de Trimble** (Este y Norte, sin decir en qué sistema) se midió
contra la latitud y longitud que trae el mismo archivo: **WGS 84, SIRGAS-Chile 2002 y SIRGAS 2000,
UTM zona 19S, coinciden a 0,4 mm de media y 0,8 mm de máximo** (no se distinguen entre sí); PSAD56
queda a **418 m** y SAD69 a **73 m**. La hora de la trayectoria es **GPST** (con otra escala las
posiciones quedarían a metros).

**La altura de Trimble no es la elipsoidal del `.MRK`:** difieren **35,3 m de media** (de 34,5 a
36,3: la ondulación del geoide más el error de las posiciones en tiempo real, que es de ±2 a 3 m). No
hay aquí un modelo de geoide con que convertir, así que la salida dice de qué altura se trata.

**El proceso entero (`vuelo_proceso.procesar`, lo que hace la pantalla)**, con ese vuelo: **2 505
fotos y 7 519 puntos de trayectoria en 1,0 s**, sistema medido WGS 84 / UTM 19S (los tres del marco
ITRF coinciden), contraste con las posiciones de Trimble de **0,65 mm como máximo**, las 2 505
miniaturas disponibles. Y en el visor, la foto 5 sale con Este 414 884,611, Norte 7 418 785,755 y
altura 1 123,319: **la misma línea del CSV de Trimble**. Se encontraron mirándolo en el navegador
tres errores que ninguna prueba había visto (un redondeo que subía un metro el Este y el Norte
mostrados, un nombre de clase que chocaba con otro y un visor que no dibujaba si el navegador
detenía `requestAnimationFrame`), y uno que el vuelo destapó en el explorador de la carpeta
compartida (cortaba a 300 entradas **antes** de filtrar, y en una carpeta con 2 505 fotos nunca
mostraba los CSV).

**F18.5, la posición escrita en fotos reales de DJI (2026-10-08).** Fotos de una Matrice (EXIF de unos 31 kB con MakerNote, y XMP de DJI): con `vuelo_exif.poner_posicion`, `exifread` —otro lector— devuelve la latitud escrita con error menor de 1e-9° (0,1 mm), el sur con su signo y el datum WGS-84; el XMP deja de repetir la posición del dron y conserva la altura relativa y el gimbal; lo que va desde SOS es idéntico byte por byte, Pillow decodifica los mismos píxeles, el MakerNote es el mismo y el original conserva su sha256 y su mtime.

**Lo que no se midió:** la corrida de RTKLIB. Ese vuelo trae el RINEX del dron (`*_PPKOBS.obs`,
RINEX 3.05, 35 MB) y el crudo de la base (`13933630.T04`), pero no hay RTKLIB en esta estación ni
se conoce la coordenada de la base (pedidos P16 y P15).

## Corrida del 2026-10-09 — las fotos del vuelo de Baquedano: posición, ficha y orientación (F18.8 a F18.10)

**Datos** (fuera del repositorio): las 2 505 fotos del vuelo de la Matrice 3E del 2025-12-29, su `.MRK`
y el `export_extended` de Trimble. Pasan con `AEROCONVERT_VUELO_DE_PRUEBA=<carpeta>` y
`pytest -m oraculo apps/vuelos/test_vuelo_real.py`.

**Cómo se midió.** Las fotos están en una carpeta de OneDrive (marcadores de posición que bajan al abrirlas,
unos 7 MB cada una, 17 GB en total): se leyó **una de cada 25 y la última, 102 fotos**, a 0,36 s cada una
(37 s). Solo se lee la cabecera (192 kB). Los lectores de contraste son otros que el código: el `.MRK`
(texto del dron), el `export_extended` de Trimble (otro programa, leído con `csv`) y, en las pruebas
sintéticas, `exifread` y un analizador de XML.

| Qué | Contra qué | Resultado (102 fotos) |
| --- | --- | --- |
| Posición del XMP (`GpsLatitude`, `GpsLongitude`) | Lat y Lon del `.MRK` del mismo disparo | **0,69 mm** como máximo en horizontal (el `.MRK` redondea a 1 mm). Es la posición de la **antena**: el desfase no está aplicado |
| `AbsoluteAltitude` del XMP | «Ellh» del `.MRK` | diferencia **0,000 mm** en todas |
| Bandera `RtkFlag` | Columna `Q` del `.MRK` (las 2 505 líneas) | **16** en las 102 y en las 2 505 líneas del `.MRK`: coinciden |
| Estado `GpsStatus` | — | «RTK» en las 102, con la bandera en 16 |
| `AltitudeType`, datum del EXIF | — | «RtkAlt» y «WGS-84» en las 102 |
| Gimbal (guiñada, cabeceo, alabeo) | `Gimbal Yaw`, `Pitch`, `Roll` de Trimble | diferencia **0** |
| Actitud del dron | `UAV Yaw`, `Pitch`, `Roll` | diferencia **0** |
| Velocidades X, Y, Z | `V. UAV X`, `Y`, `Z` | diferencia **0** |
| Focal, apertura, exposición, ISO, dimensiones, modelo | `Focal`, `F Number`, `Tiempo exp.`, `ISO Speed`, `Dimensiones`, `Modelo` | diferencia **0**; 5280 × 3956, M3E |
| Altura del XMP y altura sobre el despegue | `Alt. abs. vuelo` y `Alt.rel.vuelo` | diferencia **0** |
| Columnas `gimbal_*` del CSV de `vuelo_rtk.procesar` | las mismas de Trimble | diferencia **0°**; el cabeceo es −80° y la guiñada cambia de una pasada a otra |

**Lo que dice esta corrida de la altura.** La `AbsoluteAltitude` de DJI coincide con la «Ellh» que el propio
`.MRK` llama elipsoidal, y es la misma que Trimble copia en su columna `Alt. abs. vuelo` (diferencia 0). **No** es la
altura que Trimble entrega como posición de la foto (columna `Elevación`), que difiere unos 35 m (el geoide, ya
medido el 2026-10-08). Por eso `vuelo_rtk.py` solo la llama elipsoidal **si coincide con la `Ellh` del `.MRK`**:
la etiqueta la pone DJI en el `.MRK`, y esa es la comprobación. Sin `.MRK` no se afirma.

**Lo que esta corrida destapó.**

- **`GpsStatus` no es la calidad:** dice «RTK» en las 102 fotos de un vuelo que fue PPK, sin corrección en
  el aire, con `RtkFlag` y la columna `Q` del `.MRK` en 16. La calidad sale de la bandera.
- **El XMP lleva la posición de la antena**, no la de la cámara: coincide con la del `.MRK` sin aplicar su
  desfase. Si un dron la dejara ya con el desfase aplicado, sumarlo otra vez correría la foto: por eso se
  rechaza todo cuando la posición de una foto y la de su disparo difieren más de 2 cm.
- En la primera foto, `UTCAtExposure` del XMP (15:39:10,934) es la hora **GPST** del disparo del `.MRK`
  (semana 2399, segundo 142 750,934), no el UTC, que sería 18 s menos (15:38:52, lo que dice la hora local
  de la foto, 12:38:52 −03:00). Solo se miró en la primera foto y **no se usa**: la hora de cada disparo
  sale del `.MRK`.

**Lo que no se midió, y queda ⚠ (F18.8).** El vuelo fue PPK: **no hay un vuelo con RTK en el aire**, así
que solo se vio la bandera 16. Las banderas 50 (fija) y 34 (flotante) son las que publica DJI y no se han
contrastado con un archivo real. Hace falta (pedido P20) una carpeta de fotos de un vuelo con RTK y su
exportación de UAS Sync o de TBC.

### Procedimiento manual con un vuelo RTK real, pendiente

1. Fotos de un vuelo RTK (bandera 34 o 50) y su `.MRK`, fuera del repositorio.
2. «Corregir un vuelo de dron» → «Las fotos ya traen la posición RTK»: carpeta de fotos, `.MRK` y el
   sistema del visor.
3. Contar con `exifread` (o con el `.MRK`: columna `Q`) cuántas fotos traen cada bandera y comparar con la
   tabla de `calidad.md`: **fijas contra `50`, flotantes contra `34`**, una por una. Anotar aquí la fecha y
   las cuentas.
4. Comprobar que la altura sale «elipsoidal» (coincide con la «Ellh» del `.MRK`) y contrastar la posición
   de cinco fotos con la de UAS Sync o TBC (el contraste es del plano: la altura de Trimble no es la
   elipsoidal).
5. Si alguna cifra no coincide, **no** ajustar la tabla de banderas a ojo: anotar el código que apareció.

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

## Corrida del 2026-10-08 — curvas de nivel contra una fórmula (F15.6)

Un cono `z = 100 − 0,5·r` (`r` en metros desde el centro) en un GeoTIFF de 400 × 400 píxeles de 1 m,
UTM 19S, convertido por el motor `gdal-curvas` con intervalo de 10 m. **El oráculo es la fórmula**, no
una segunda lectura de GDAL: la curva de cota `L` tiene que ser una circunferencia de radio
`(100 − L)/0,5`.

- **Cotas 10 a 90:** un solo anillo por cota, **cerrado**, y **todos sus vértices a menos de 0,6 m** del
  radio calculado (`ogrinfo -json -features`, que es otro programa que el que escribió el archivo).
- **Cotas −40 a 0:** cuatro arcos cada una, porque el radio llega a 283 m y el cuadrado solo a 200 m
  del centro. Total: **29 curvas** en los tres destinos; GeoPackage, Shapefile y DXF dan el mismo
  número por cota (el DXF, leído con `ezdxf`).
- **Lo que la corrida destapó:** `gdal_contour -f DXF -3d` escribe 29 polilíneas **sin elevación**
  (valido y sin la cota: inservible), y `-a ELEV` con DXF falla («Failed to create elevation field»).
  Por eso el DXF pasa por un GeoPackage 3D y `ogr2ogr`; la corrida lo comprobó con el grupo 38 de
  cada polilínea.
- Un intervalo de 5 000 m (mayor que el desnivel) **no deja un entregable vacío**: el trabajo falla.
- **No medido:** DWG (espera a ODA, F15.8); un DEM real de la faena; rendimiento con un modelo de varios
  gigabytes.

## Corrida del 2026-10-09 — alturas con geoide contra `cs2cs` (F15.2)

Oráculo: `cs2cs` de PROJ (QGIS 4.0.2) por la ruta de **códigos EPSG**, `EPSG:4979` → `EPSG:4326+5773`
(EGM96 height) con `PROJ_DATA` apuntando a la carpeta de la grilla y `PROJ_NETWORK=OFF`. Nuestro código
usa otra ruta: `+proj=vgridshift +grids="<archivo>"` con pyproj 3.8.0. Misma grilla, dos caminos.

Grilla usada: `us_nga_egm96_15.tif`, 3 462 098 bytes, SHA-256
`67ba9175a290ba4a7d82498bab182818876e3802c1415907998813ffa51132ab`. **Es la copia que trae Agisoft
Metashape** (`geoids\egm96-15.tif`), copiada con el nombre de PROJ a una carpeta de trabajo: su
metadato dice `VERT_DATUM["EGM96 geoid"]` (EPSG:5171) y su ondulación en (0, 0) es 17,162 m, el valor
publicado de EGM96.

| lon, lat | N (m) | H de nuestro código (z = 1000) | H de `cs2cs` |
| --- | ---: | ---: | ---: |
| −68,9 ; −23,0 | 36,7372 | 963,2628 | 963,2628 |
| −70,65 ; −33,45 | 26,9438 | 973,0562 | 973,05616 |
| 0 ; 0 | 17,1620 | 982,838 | 982,837999 |
| 2,35 ; 48,85 | 44,5670 | 955,433 | 955,43296 |
| 139,7 ; 35,7 | 36,8014 | 963,1986 | 963,19856 |

Diferencia máxima: **4,05·10⁻⁷ m** (`cs2cs` imprime 6 decimales); el criterio es < 1 mm. La base `AUX_01`
de Baquedano, en UTM 19S (para comprobar también la reproyección), pasa la ida y vuelta contra el oráculo
con la misma tolerancia.

**EGM2008: sin medir.** No hay `us_nga_egm08_25.tif` en esta máquina ni en las carpetas de PROJ de
pyproj o QGIS, y descargarla exige permiso de la persona. Las pruebas de oráculo de EGM2008 se saltan
con ese motivo. Procedimiento: copiar la grilla (cdn.proj.org) a una carpeta, poner
`AEROCONVERT_PROJ_GRILLAS` en el `.env` y correr
`uv run pytest -m oraculo apps/formats/test_alturas.py`; anotar aquí fecha, grilla y SHA-256.
## Corrida del 2026-10-09 — «Ver en el mapa» contra GDAL (F19.1, F19.2)

`uv run pytest -m oraculo apps/visor/test_oraculo.py` con GDAL 3.12.4 (QGIS 4.0.2): **43 pasan**. El
archivo es un **GeoTIFF sintético** que crea cada prueba (200 × 100 píxeles de 2 m en EPSG:32719, un
tablero de 20 píxeles con un degradado por canal); no hay ningún dato real en el repositorio.

| Qué | Oráculo | Medida |
| --- | --- | --- |
| Esquinas en EPSG:4326 | `wgs84Extent` de `gdalinfo -json` | diferencia máxima **4,4e-8°** (tolerancia 1e-7°; GDAL redondea a siete decimales) |
| Centro en EPSG:4326 | `gdaltransform` sobre el centro de `gdalinfo` | **4e-14°** |
| Una tesela 16/19903/39241 | otro `gdalwarp -t_srs EPSG:3857 -te … -ts 256 256 -r bilinear -dstalpha` a PNG, con la caja de una fórmula escrita aparte | **0** de 65 536 píxeles distintos |
| La misma, contra GeoTIFF | el mismo `gdalwarp` con otro controlador | ±1 nivel en 240 píxeles (**0,37 %**): redondeo de GDAL entre controladores; la prueba tolera ±1 en menos del 1 % |
| Orientación y posición | el color que **debe** tener un píxel del tablero (cinco puntos) | rojo, verde y azul en su sitio: el norte arriba y el este a la derecha, sin depender de `gdalwarp` |
| Columna, fila y valores bajo el cursor | `gdallocationinfo -wgs84` y `-geoloc` (cinco píxeles) | iguales; p. ej. (130,5; 10,5) → columna 130, fila 10, bandas 0, 166, 25 |
| 16 bits, 4 bandas con alfa, 8 bandas | VRT escalado; `gdalinfo`; `gdalwarp` del RGB | el rango medido por `-approx_stats` es el escrito (100 y 3000); las ocho bandas dan lo mismo que las tres primeras |
| El original | `sha256`, `mtime` y la carpeta | intactos tras ficha, nueve teselas y la lectura del píxel; **ningún `.aux.xml`** (la prueba de control demuestra que sin `GDAL_PAM_ENABLED=NO` GDAL sí lo escribe) |

**Lo que el plan pedía y no se hizo así:** una tesela contra `gdal_translate -projwin` y `gdalcompare`.
Una tesela de EPSG:3857 es una **reproyección**; un recorte `-projwin` en el sistema del archivo no
puede coincidir con ella píxel a píxel. Y `python -m osgeo_utils.gdalcompare` no está en esta máquina
(el Python de QGIS no trae `osgeo_utils`). Se comparó con un `gdalwarp` independiente y numpy, que es
lo que `gdalcompare` hace sin el informe.

**Sin medir:** una ortofoto real de varios gigas (rendimiento de las teselas lejanas sin pirámide,
tamaño de la caché en uso). Se anota aquí con fecha cuando se corra en `p340` con un COG del equipo.

## Pendiente: «Hacer un libro EPUB» contra EPUBCheck (F14.22)

EPUBCheck es el validador de referencia del W3C (BSD-3, Java 11+). En el CI no está; la prueba `test_epubcheck_lo_da_por_valido` lleva `@pytest.mark.oraculo` y se salta sin él.

1. Bajar el `.zip` de EPUBCheck 5.x de su repositorio oficial y descomprimirlo fuera del repositorio.
2. `$env:AEROCONVERT_EPUBCHECK="<carpeta>\epubcheck.jar"` y Java en el `PATH`.
3. `uv run pytest -m oraculo apps/documents/test_a_epub.py`.
4. Anotar aquí la fecha, la versión de EPUBCheck y su frase final (debe ser «No errors or warnings detected»).

## Pendiente de correr en `p340`: «Office a PDF» con LibreOffice (F17.1)

En la estación no hay LibreOffice, así que lo comprobado aquí es el pegamento, con un `soffice` de
mentira que hace lo mismo que el de verdad (escribe `<outdir>/<nombre>.pdf` y deja un `.~lock` junto
al documento que abre): el original y su carpeta quedan intactos, el PDF llega al parcial, la carpeta
de trabajo se borra siempre, el recibo dice «con LibreOffice».

**Procedimiento en `p340`**, tras `sudo despliegue/instalar_faltantes.sh`:

```bash
cd /opt/aeroconvert && sudo -u aeroconvert .venv/bin/python -m pytest -q -m oraculo \
    apps/documents/test_libreoffice.py
```

La prueba arma un `.docx` con la frase «Frase de control 4711 para el oráculo», lo convierte con el
LibreOffice instalado y **PDFium** (otro lector) cuenta las páginas y busca la frase. Anotar aquí la
fecha, la versión de LibreOffice y el tiempo.

## Pendiente de correr en `p340`: catálogos con `mdbtools` (F17.2)

En la estación hay ACE y no hay `mdbtools`; en el servidor, al revés. El procedimiento cruza las dos:

1. En la **estación**, con ACE: `catalogos.esquema("HDPE_PE100_PN16.mdb")` y anotar aquí el número de
   filas de cada una de las nueve tablas (el total medido el 2026-09-15 fue 481).
2. En **`p340`**, tras `sudo despliegue/instalar_faltantes.sh`, copiar el mismo `.mdb` (fuera del
   repositorio) y exportarlo con «Catálogo Plant 3D a Excel». El recibo dice las tablas y sus filas:
   tienen que coincidir una por una con las de ACE.
3. Abrir el Excel y comprobar que una columna numérica (`NOMINAL_DIAMETER`) sale como número.

