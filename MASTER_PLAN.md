# MASTER_PLAN — AeroConvert

La fuente de verdad de qué sigue. Cada fase cerrada marca ✅ en su fila, con la fecha y el
enlace a la entrada del `CHANGELOG.md`.

**Criterio de aceptación general de la fase 1:** el entregable real del cruce minero de BHP,
no un ejemplo inventado. Sus cifras están en
[docs/PRUEBAS_CON_ORACULO.md](docs/PRUEBAS_CON_ORACULO.md).

---

## Fase 0 — Andamiaje

| # | Bloque | Entrega | Estado |
| --- | --- | --- | --- |
| F0.1 | Estructura | Layout Aero, `config/settings/{base,dev,prod,taller,nube}`, `apps.core`, apps de familia vacías | ✅ 2026-09-08 |
| F0.2 | Documentos | `AGENTS.md`, `MASTER_PLAN.md`, `HANDOFF.md`, `CHANGELOG.md`, `README.md`, `LICENSE`, `INSTALL.md` y `docs/` | ✅ 2026-09-08 |
| F0.3 | Identidad | Marca y variante oscura, quinto color de familia `#F15BB5` con sus tokens medidos | ✅ 2026-09-08 |
| F0.4 | Modos | `settings.MODO`, chapa en la interfaz, `comprobar_ruta()`, `manage.py check` que falla sin raíces | ✅ 2026-09-08 |
| F0.5 | Gate | `scripts/verify.ps1`, `run.ps1`, `sondear.ps1`, CI de GitHub Actions **verde** | ✅ 2026-09-08 |
| F0.6 | Vendorizado | Bootstrap 5.3.3 y htmx 2.0.10 con SRI en `static/vendor/`, CSP `'self'` | ✅ 2026-09-08 |

## Fase 1 — Ráster, de punta a punta

| # | Bloque | Entrega | Estado |
| --- | --- | --- | --- |
| F1.0 | Catálogo y detección | `apps.formats`: catálogo, lector TIFF/BigTIFF propio, firmas, `Crs`, `PuntoConCrs`, acompañantes | ✅ 2026-09-08 |
| F1.1 | Motores | Contrato, registro, sondas de GDAL/PROJ/PDAL/ECW/ODA, matriz de capacidades, `/motores/`, API | 🟨 lógica lista, falta `RegistroDeSonda` y la plantilla |
| F1.2 | Trabajos | `ConversionJob`, `JobEvent`, runner, despachador, reclamo atómico, latido, cancelación, escritura atómica | ✅ 2026-09-08 |
| F1.3 | Perfiles de destino | `apps.targets` y la tira de veredictos | ✅ 2026-09-08 |
| F1.4 | La mesa | Ficha del archivo, destino por software, modo experto, progreso htmx, el recibo, historial, matriz | ✅ 2026-09-08 |
| F1.8 | Retención y disco | Tres políticas, presupuesto con cola, barrido de caducados y huérfanos, descarga que consume | ✅ 2026-09-08 |
| F1.5 | Ráster GDAL | GeoTIFF/BigTIFF ↔ COG, JP2, IMG, ASC; reproyección, pirámides, alfa descartada, verificación con `gdalinfo` | ✅ 2026-09-08 |
| F1.6 | ECW | `gdal-ecw` con clave OEM y `ecw-externo`, tres motivos, alternativa COG/JP2, «reencolar como JP2» | ⬜ |
| F1.7 | Preajustes y pulido | `ConversionPreset` con sembrado idempotente, formulario generado desde `opciones()`, estimación previa, reintentar y alternativas | ✅ 2026-09-09 |

**Valores por omisión ya decididos, y medidos** (ver `PRUEBAS_CON_ORACULO.md` §2):

- Archivo maestro → **GeoTIFF clásico, DEFLATE-9, predictor 2**. Idéntico bit a bit y 33 MB
  menos que LZW: LZW no tiene ninguna ventaja.
- Entrega y CAD → **JPEG 2000**. 13 % del peso con 51,7 dB y error máximo de 4 sobre 255 —
  mejor calidad *y* mejor comportamiento que un TIFF con JPEG q92.

## Fase 2 — Nubes de puntos

| # | Entrega | Estado |
| --- | --- | --- |
| F2.0 | Lector propio de cabecera LAS/LAZ/COPC, sin PDAL | ✅ 2026-09-09 |
| F2.1 | LAS/LAZ → COPC. **No se portó `a-copc.py`**: el PDAL instalado ya trae `writers.copc`, así que son 3 líneas en vez de 371 | ✅ 2026-09-09 |
| F2.2 | Diezmado con `filters.sample` y reproyección. **E57 no**: esta compilación de PDAL no lo trae, y su celda lo dice | ✅ 2026-09-09 |
| F2.3 | CRS desde las VLR, con el mismo parser de geoclaves del GeoTIFF. **Un CRS ausente es detención dura, sin excepción** | ✅ 2026-09-09 |
| F2.4 | El aviso de precisión: `float32` pierde 200 mm en el norte UTM. Se detecta y se avisa en la ficha | ✅ 2026-09-09 |
| F2.5 | RCS y RCP de ReCap: en el catálogo **para poder decir que no se pueden**, con el remedio escrito | ✅ 2026-09-09 |
| F2.6 | 3D Tiles y Potree con `py3dtiles` | ⬜ |

## Fase 3 — Vectorial, CAD y topografía

| # | Entrega | Estado |
| --- | --- | --- |
| F3.1 | OGR: SHP, GPKG, GeoJSON, GML, GPX, DXF | ✅ |
| F3.2 | KML y KMZ | ✅ · los lee y los escribe LIBKML, verificado de punta a punta. El parser endurecido de AeroControl **no hace falta**: resolvía un problema que OGR ya cubre |
| F3.3 | **Archivos de puntos PNEZD/PENZD/NEZ/ENZ, con vista previa antes de convertir** | ✅ |
| F3.4 | DWG y DGN v8 por ODA; DGN v7 por GDAL | ✅ 2026-09-21 ⚠ · el motor y el comando están y se comprueban; **falta correrlo con el conversor instalado**, que no está en ninguna de las dos máquinas |
| F3.5 | LandXML: superficies y alineamientos para Civil 3D | ◐ · se escribe y se lee; los puntos se convierten en los dos sentidos. Las superficies y los alineamientos **se cuentan y se identifican**, pero traducirlos espera a tener un archivo real con el que contrastar |

## Fase 4 — BIM y malla

| # | Entrega | Estado |
| --- | --- | --- |
| F4.1 | IFC con `ifcopenshell`, OBJ, glTF/GLB, 3D Tiles | ⬜ |
| F4.2 | Integración con AeroBim, por archivo o API | ⬜ |

## Fase 5 — Documentos de oficina

No estaba en el plan original y **entró porque es el trabajo real de todos los días**: el
entregable que sale de aquí acaba dentro de un informe, y juntar los PDF de una entrega se
hace más veces por semana que convertir una ortofoto. La referencia de funciones es iLovePDF;
la diferencia es que aquí el archivo **no sale del equipo**, que es justo lo que impide usar
esas páginas con un plano bajo acuerdo de confidencialidad.

Estas herramientas **no pasan por la cola de conversión** a propósito: se tocan muchas veces
—subir, bajar, quitar, girar— y escriben en menos de un segundo. Meterlas en el despachador
sería pedir que alguien espere a un proceso en segundo plano para reordenar tres hojas.

| # | Entrega | Estado |
| --- | --- | --- |
| F5.0 | Leer un PDF: páginas, tamaño en mm, formato normalizado y orientación **con `/Rotate` aplicado** | ✅ 2026-09-10 |
| F5.1 | Unir eligiendo páginas, orden y giro; receta sin estado en el servidor | ✅ 2026-09-10 |
| F5.2 | Miniaturas con pypdfium2 y caché por `ETag` del navegador | ✅ 2026-09-10 |
| F5.3 | Dividir por rangos o en hojas sueltas; imágenes → PDF en A4 o al tamaño del original | ✅ 2026-09-11 |
| F5.4 | Índice de herramientas, una entrada en la barra y no seis | ✅ 2026-09-11 |
| F5.5 | PDF → JPG/PNG con resolución elegida y tope de lado | ✅ 2026-09-11 |
| F5.6 | Proteger y desproteger, **solo AES-256** | ✅ 2026-09-11 |
| F5.7 | Números de página y marca de agua, con la geometría del giro resuelta | ✅ 2026-09-11 |
| F5.8 | Word/Excel/PowerPoint → PDF por COM, **solo en taller** | ✅ 2026-09-11 |
| F5.9 | PDF → Word, con el aviso de qué se recibe de verdad | ✅ 2026-09-11 |
| F5.10 | Comprimir, **y negarse cuando comprimir empeoraría el archivo** | ✅ 2026-09-21 |
| F5.11 | OCR con Tesseract sondeado, no declarado | ✅ 2026-09-21 |

> **F5.11 estuvo unas horas con una ⚠, y así se quitó.** El motor se escribió sin Tesseract
> en ninguna de las dos máquinas, así que el comando, el sondeo y las negativas se
> comprobaban y **la conversión no**. Se instaló en el servidor ese mismo día
> —`tesseract-ocr` 5.5.0 con `spa`, `eng` y `osd`— y se corrió sobre un escaneo de verdad:
>
> ```
> antes  tiene texto: False
> despues tiene texto: True
> reconocio: 'ACTA DE RECEPCION'
> ```
>
> Sin una errata. **Eso es lo que convierte un ⚠ en un ✅**, y no que el código parezca
> correcto.

---

## Fase 6 — Poner esto en una VM

**No estaba en el plan y hace falta declararla**, porque `docs/DEPLOY.md` describía un
despliegue diseñado y se leía como uno construido. Comprobado el 2026-09-11: el modo nube
arranca, sirve páginas y autentica, y **no puede convertir ni un archivo**. El modo taller,
que es el que está en uso, sí está terminado.

**El hallazgo que reordenó la fase:** al comprobarlo con los ajustes de la VM de verdad, el
despliegue correcto resultó ser **`config.settings.prod` con `AEROCONVERT_MODO=taller`** y las
raíces apuntando a la carpeta compartida. Eso ya funcionaba sin tocar una línea: la ruta
dentro del recurso se acepta, la de fuera se rechaza, la salida va junto al original —que es
lo que se quiere cuando el equipo tiene la unidad montada—, y la retención es permanente.

O sea que la subida de archivos **no era el bloqueante**. Lo que hacía falta era impedir la
elección equivocada y arreglar tres defectos que solo aparecen con más de una persona.

| # | Entrega | Estado |
| --- | --- | --- |
| F6.1 | **Los tres defectos de varias personas**: colisión de salidas, bloqueo de sesión por IP compartida, y un 500 sin rastro | ✅ 2026-09-11 |
| F6.2 | El techo de memoria de las nubes, dicho antes de empezar | ✅ 2026-09-11 |
| F6.3 | `manage.py check` se niega en modo nube, y avisa de una raíz demasiado ancha en una máquina compartida | ✅ 2026-09-11 |
| F6.4 | El despachador fuera del proceso web, en su propia unidad | ✅ 2026-09-11 |
| F6.5 | Infraestructura: `gunicorn`, systemd, nginx, `desplegar.sh`, `/salud/` de verdad, `admin.py`, respaldo | ✅ 2026-09-11 |
| F6.6 | `check --deploy` y `collectstatic` en el CI, y con el módulo correcto | ✅ 2026-09-11 |
| F6.7 | Páginas de error (`404`, `500`, `403`, `400`) y el 410 de la salida caducada, con su recibo | ✅ 2026-09-11 |
| F6.8 | Instalar en la VM y el paseo de aceptación | ✅ 2026-09-15 · `/opt/aeroconvert`, systemd, Funnel en el 8443 |
| F6.9 | La subida por navegador y la descarga del resultado | ✅ 2026-09-14 |
| F6.10 | Paseo de aceptación sobre base limpia, por HTTP | ✅ 2026-09-14 |
| F6.11 | Cada aplicación con su cookie: compartían `sessionid` en el mismo nombre y se echaban entre sí | ✅ 2026-09-15 |
| F6.12 | Entrar con el correo, y el enlace a las altas en la barra | ✅ 2026-09-15 |
| F6.13 | Elegir el archivo sin teclear su ruta: subir del propio equipo, o andar la carpeta compartida | ✅ 2026-09-15 |
| F6.14 | PDAL de conda-forge en el servidor: 30 conversiones de nubes recuperadas | ✅ 2026-09-15 |

**Lo que queda del servidor**, y no es de esta aplicación sola — está en
[despliegue/SERVIDOR.md](despliegue/SERVIDOR.md): no hay respaldo automático de nada, no hay
límite de peticiones contra un extremo público, y SSH sigue admitiendo contraseña.

---

## Fase 7 — Crecer

Lo que sigue después de que el equipo lo esté usando. **El orden no es el de dificultad: es el
de cuántas veces al día alguien se queda sin poder hacer algo.**

### F7.1 — Markdown, que es la salida que falta

La referencia sigue siendo iLovePDF, y ahí ya está: *PDF a Markdown*. Pero el caso de esta
oficina es más ancho que el suyo.

**Por qué importa aquí.** Un informe de terreno, una tabla de coordenadas o un acta acaban
copiándose a mano a un correo, a una ficha de AeroControl o a un tablero. Markdown es el
formato que atraviesa todo eso sin perder la tabla ni los títulos, y **no necesita programa
para leerse**.

| # | Entrega | Notas | Estado |
| --- | --- | --- | --- |
| F7.1a | **Excel → Markdown** | Una hoja es una tabla y Markdown tiene tablas. Es la conversión más directa del grupo y probablemente la más pedida | ✅ 2026-09-15 |
| F7.1b | **PDF → Markdown** | Solo del texto que el PDF ya tiene. Un PDF escaneado no tiene texto y hay que **decirlo**, no entregar una página en blanco: eso es OCR, y es F5.11 — **que ya está**, así que desde el 2026-09-21 el aviso nombra la herramienta en vez de decir «todavía no» | ✅ 2026-09-15 |
| F7.1c | **Word → Markdown** | Títulos, listas, tablas y negritas. Lo que no sobrevive —cuadros de texto, columnas— se avisa antes | ✅ 2026-09-15 |
| F7.1d | **Markdown → PDF** | El camino de vuelta, para entregar lo que se redactó en Markdown | ✅ 2026-09-15 |
| F7.1e | **CSV, EPUB y página web → Markdown** | No estaban en el plan y entraron con el resto: el EPUB salió casi gratis porque por dentro es un ZIP con XHTML | ✅ 2026-09-15 |

**Hecha entera en `0e07182`**, con `apps/documents/a_markdown.py` y `desde_markdown.py`. Sin
`markitdown`: su `magika` obligatorio arrastra `onnxruntime`, ~40 MB de runtime de aprendizaje
automático solo para adivinar el tipo de archivo. Entraron `markdownify` y `beautifulsoup4`,
**126 KB entre las dos**.

**La decisión de licencia, que es la de siempre:** hay biblioteca para casi todo esto, y casi
toda es AGPL. `markitdown` (MIT) y `openpyxl` (MIT) cubren Excel y Word; para PDF, el texto ya
lo saca `pypdf`, que es BSD y ya está dentro. **Ninguna de las tres obliga a cambiar la regla
de licencias**, y eso es lo que hace esta fase viable donde PyMuPDF no lo fue.

### F7.2 — Las tarjetas, como referencia de forma

Lo que iLovePDF hace bien y aquí ya está a medias: **icono con color propio, nombre corto y
una línea de qué hace**. Lo que a ellos les falta y aquí sí está: decir **qué sale**, y decir
qué **no** se puede y por qué.

| # | Entrega | Estado |
| --- | --- | --- |
| F7.2a | Iconos propios por familia, en dúotono y con color por tipo de operación | ✅ 2026-09-14 |
| F7.2b | Grupos con encabezado, y «Sale: un PDF» en cada tarjeta | ✅ 2026-09-15 |
| F7.2c | El mismo trato en la pantalla de convertir: los destinos geoespaciales como tarjetas con su formato de salida | ✅ 2026-10-06 · baldosa, «Sale:» y estimación; mirado en el navegador con los motores reales |

### F7.3 — Las herramientas de PDF que faltan

De la lista de iLovePDF, ordenadas por lo que se pide de verdad en una oficina de topografía:

| # | Entrega | Por qué, y qué cuesta |
| --- | --- | --- |
| F7.3a | ~~**Comprimir PDF**~~ | ✅ 2026-09-21, como F5.10. Medido sobre un escaneo real: 7,2 MB → 1,19 MB |
| F7.3b | **Ordenar, eliminar y extraer páginas** | Ya está medio hecho: la receta de «unir» sabe hacerlo, falta la pantalla de una sola entrada |
| F7.3c | **Rotar PDF** | Tres líneas con `pypdf`. Está ya dentro de «unir», suelto no |
| F7.3d | ~~**OCR**~~ | ✅ 2026-09-21, como F5.11. Verificado sobre un escaneo real en el servidor, con Tesseract 5.5.0 |
| F7.3e | **Firmar PDF** | El caso real es el acta firmada. Firma dibujada primero; la digital con certificado es otra cosa y otra fase |
| F7.3f | Comparar, censurar, recortar, reparar, HTML a PDF, PDF/A, formularios | La cola larga. Cada una entra cuando alguien la pida dos veces |

### F7.4 — Un ayudante que guíe

> **Hecho el 2026-09-21, y con una vuelta de tuerca que conviene leer.**
>
> Al ir a escribirlo salió que **las tres cosas de la lista de abajo las contesta esta
> máquina sola**: están en la matriz de capacidades, en el catálogo de formatos y en el de
> herramientas. Así que Tino empieza por ahí, y lo que contesta desde aquí es *exacto* —sale
> de lo mismo que decide la conversión—, **no sale del equipo**, y funciona sin configurar
> nada ni pagar nada.
>
> La puerta hacia fuera existe, está escrita, y **nace cerrada**: sin `AEROCONVERT_TINO_CLAVE`
> no se ejecuta una sola línea de ella. **El proveedor se deja sin decidir a propósito**: a
> quién se le manda la pregunta de alguien es una decisión sobre los datos de la oficina, y
> esa no es de quien escribe el código. Hay una prueba que comprueba que sigue sin decidir.
>
> De paso salieron dos fallos del buscador que nadie había visto porque los ejemplos de la
> portada son dos palabras sueltas: **un signo de interrogación bastaba para no reconocer
> ningún formato**, y «la», «de» y «un» daban puntos gratis a las veinte herramientas.

La idea es buena y **es transversal a la familia**: la misma pieza sirve en AeroBim, AeroControl
y AeroConvert, y lo que cambia es de qué sabe.

**Qué haría, en orden de valor:**

1. **Contestar «¿por qué no puedo hacer esto?»** — que es la pregunta que ya contesta la
   pantalla de compatibilidad, pero buscando por el archivo que alguien tiene en la mano.
2. **Llevar a la herramienta correcta.** «Tengo que juntar estos tres planos y numerarlos»
   son dos herramientas, y saber cuál primero no es evidente.
3. **Explicar lo que la aplicación ya sabe** — el CRS que falta, por qué JPEG 2000 y no ECW,
   qué significa que un LAS venga en `float32`.

**Lo que hay que decidir antes de escribir una línea**, y no es técnico:

- **Si habla con un modelo de fuera, los archivos no.** El argumento entero de esta aplicación
  es que un plano bajo acuerdo de confidencialidad no sale del equipo. Un ayudante que mande
  el nombre del archivo, o su contenido, a una API rompe eso. Lo que sí puede salir es la
  pregunta escrita por la persona, y ni eso sin decirlo claramente.
- **Un ayudante que no sabe decir «no sé» es peor que ninguno.** En una herramienta cuyo valor
  es decir la verdad sobre lo que se puede y lo que no, una respuesta inventada sobre un
  sistema de referencia hace daño de verdad.

**El nombre.** Tiene que funcionar en las tres aplicaciones y decirse fácil por teléfono.
Tres que valen, y la decisión es tuya:

| Nombre | De dónde sale | Por qué funciona |
| --- | --- | --- |
| **Tino** | De «atinar», y del chilenismo «tener tino» | Es exactamente lo que se le pide: criterio. Dos sílabas, se dice por teléfono sin deletrear |
| **Nimbo** | El tipo de nube | Queda dentro del mundo Aero sin ser un avión. Suena a herramienta, no a juguete |
| **Rumbo** | El azimut de navegación | Es término técnico de la casa, y lo que hace es justamente dar rumbo |

Yo elegiría **Tino**: los otros dos describen el ambiente, y ese describe el trabajo.

### F7.6 — Catálogos de tubería: Excel ↔ `.mdb`

Pedido el **2026-09-15**, con un archivo de verdad delante: `HDPE_PE100_PN16.mdb`.

**Y lo primero que hay que decir es que no es «Excel a Access».** Al abrirlo resulta ser un
**catálogo de especificación de AutoCAD Plant 3D**: nueve tablas —`PIPE`, `ELBOW`, `TEE`,
`FLANGE`, `REDUCER`, `CROSSES`, `GASKET`, `BOLT`, `MISC_FIT`—, 481 filas y columnas como
`EC_CLASS_NAME`, `PIECE_MARK`, `END_COND_1`, `SKT_DPTH_M` o `CTR_END_B`. Entre 28 y 52
columnas por tabla.

Un conversor genérico de hoja a base de datos **no sirve para esto**: produciría una tabla con
los nombres que traiga el Excel, y Plant 3D no abriría el resultado. Lo que hace falta es
rellenar **un esquema fijo que ya existe**.

#### Lo que ya está medido, no supuesto

Comprobado el 2026-09-15 en la estación de trabajo:

| Qué | Resultado |
| --- | --- |
| Formato del archivo | **Jet 4** (Access 2000-2003), 675 KB |
| Controlador presente | `Microsoft Access Driver (*.mdb, *.accdb)` **en 64 bits** |
| ¿Se puede **crear** un `.mdb` Jet 4? | **Sí.** `ADOX.Catalog` con `Jet OLEDB:Engine Type=5` |
| ¿Crear tabla e insertar? | **Sí**, las dos comprobadas |
| ¿Hace falta licencia de Access? | **No.** ACE es un redistribuible gratuito de Microsoft |

Era la pregunta que decidía la fase entera: leer un `.mdb` es fácil y **escribirlo** es lo que
suele no poderse. Se puede.

#### El orden, que es al revés de lo que se pidió

| # | Entrega | Por qué en este orden |
| --- | --- | --- |
| F7.6a | **`.mdb` → Excel**, una hoja por tabla | Es la mitad que más se usa y la que no puede fallar: **nadie escribe 52 columnas desde cero**. El flujo real es exportar el catálogo que ya existe, editarlo en Excel y volver a meterlo | ✅ 2026-09-15 |
| F7.6b | **Excel → `.mdb` usando un `.mdb` de plantilla** | El esquema sale del archivo de plantilla, no del Excel. Las columnas del Excel se **comprueban contra él** y una que no exista **para el trabajo**, no se descarta en silencio: un catálogo al que le falta una columna lo abre Plant 3D y falla más tarde, en la obra | ✅ 2026-09-15 |
| F7.6c | Avisar de lo que no cuadra **antes** de escribir | Filas con `MAIN_SIZE` vacío, textos más largos que el campo, números donde va texto. Es la misma regla que el resto: si no se puede entregar algo correcto, se dice | ✅ 2026-09-15 |

**Hecha en `2ef2c86`**, con `apps/documents/catalogos.py`. Probada de punta a punta contra
`HDPE_PE100_PN16.mdb`: nueve tablas, 481 filas, exportado a Excel, editado y reconstruido.

**Y la pregunta que quedaba abierta está resuelta el 2026-09-21: son catálogos de Plant 3D.**
El código no cambia. Si algún día entra CADWorx, hará falta un `.mdb` suyo para comparar
esquemas antes de tocar nada.

#### Cómo se hace

- **`pyodbc`** (MIT) contra el controlador ACE, que **se sondea, no se declara** — exactamente
  como `apps/documents/office.py` con Word. En el servidor Linux no hay ACE, así que las dos
  herramientas salen **apagadas con su motivo**, igual que las de Office.
- La lectura (F7.6a) sí tiene alternativa en Linux: `mdbtools` exporta a CSV. Se deja anotado
  y **no se hace todavía**: media función que solo lee en un sitio y solo escribe en otro es
  más difícil de explicar que una que no está.
- El `.mdb` de plantilla se elige con las dos vías de siempre —subir o carpeta compartida—,
  como cualquier otra pantalla. Ver `docs/ESTILO.md`.

#### Lo que hay que preguntar antes de escribir una línea

- **¿Plant 3D o CADWorx?** El esquema se parece mucho entre los dos y las tablas no son
  idénticas. Con un archivo de cada uno delante se sale de dudas en diez minutos.
- **¿De dónde salen los catálogos nuevos?** Si siempre se parte de uno existente, F7.6b es
  rellenar; si hay que crear uno desde cero, hace falta además saber qué tablas son
  obligatorias para que el programa lo acepte.

### F7.5 — La barra, cuando entren más aplicaciones

La distribución de ahora funciona y **no hay que rehacerla**. Lo que falta es lo de al lado:
un acceso a las aplicaciones hermanas —AeroControl, AeroBim— desde la misma barra, porque hoy
viven en el mismo servidor y en puertos distintos que nadie recuerda.

---

## Fase 9 — Que se pueda terminar una conversión, que se vea y que se lea bien

Plan aprobado el 2026-09-25, con las tres decisiones tomadas: primero lo que rompe y luego lo
visual; **las 20 herramientas de documentos por la cola de trabajos**; la paleta a OKLCH como
etapa final. Cada etapa va en su rama `codex/fase-9-*` con su PR.

| # | Entrega | Estado |
| --- | --- | --- |
| F9.0 | Cerrar la fase 8 como manda `AGENTS.md`: entrada en `CHANGELOG.md`, corregir `HANDOFF.md`, y dejar de hacer commit directo a `main` | ✅ 2026-09-25 |
| F9.1 | Lo que rompe y no depende de la cola: soltar archivos de verdad, errores que se ven, la ficha a la vista, un error al encolar no borra nada, `aria-live` | ✅ 2026-09-25 |
| F9.2 | Las 20 herramientas por la cola: descarga, progreso, historial y plazo para todas; OCR sin morir a los 120 s | ✅ 2026-09-25 · falta retirar `Resultado` cuando caduquen sus filas |
| F9.3 | Contraste y foco medidos y sostenidos por pruebas: anillo en la barra, foco de formularios, enlaces, estados | ✅ 2026-09-25 · falta la pasada de teclado en los dos temas |
| F9.4 | Lo visual: una acción principal, profundidad, radios, iconos, tipografía, móvil a 375 px | ✅ 2026-10-06 · hecha la pantalla del resultado de una conversión y el desborde de la barra a 375 px; menú «Herramientas» sin salirse y con columnas parejas, límite de subida a la vista, y `/convertir/` y `/motores/` sin desborde a 375 px; portada con grupos plegables (2.000 a 1.010 px); **tipografía y radios cerrados:** 14 tamaños de letra y 4 radios sueltos pasan a la escala y `test_escala_visual.py` impide volver (la profundidad ya salía de `--av-elev-*`); iconos revisados: GNSS, PDF a Markdown y Página web a Markdown dejan la diana y la hoja genéricas por uno propio, y `test_iconos.py` vigila que todo icono nombrado exista |
| F9.5 | La paleta en OKLCH sin cambiar lo que se ve | ✅ 2026-10-06 · 95 tokens en los tres bloques de tema; el navegador pinta el mismo byte en 95 de 95 (`docs/PRUEBAS_CON_ORACULO.md`); `apps/core/oklch.py` y `test_oklch.py`; quedan 49 hex que no son tokens |
| F9.6 | Saber si mejoró: `Incidente` y `resumen_de_uso` | ✅ 2026-10-06 · modelo `Incidente` (500 del servidor y fallos de htmx), `manage.py resumen_de_uso`, 20 pruebas · falta ver cifras reales tras unos días en `p340` |

**Lo que la auditoría encontró y motiva el orden**: 13 de las 20 herramientas no dejan
descargar el resultado de un archivo subido; arrastrar y soltar no hace nada; ningún error de
htmx se ve; OCR muere a los 120 s de gunicorn. Y siete pares de contraste por debajo de WCAG,
el peor el anillo de foco sobre la barra en claro, a 1,97:1.

---

## Fase 10 — Datos GNSS: del receptor Trimble a RINEX, verificado

Pedido el 2026-10-05. Se investigó antes qué existe: **RTKLIB `convbin` no lee T02 ni T04**
(solo los flujos RT17 y RT27), TEQC está muerto y no convierte un T04, y los sustitutos son
GPL o de pago. Lo único que convierte un archivo de campo de Trimble es su utilidad oficial.

| # | Entrega | Estado |
| --- | --- | --- |
| F10.0 | Coordenadas locales para nubes de puntos sin sistema (lo que el escáner sin GNSS necesita) | ✅ 2026-10-05 |
| F10.1 | La espiga: el convertidor de Trimble convierte un T02 y un T04 reales (en Windows) | ✅ 2026-10-05 |
| F10.2 | Familia GNSS en el catálogo, reconocer un T0x y leer RINEX 2/3/4 | ✅ 2026-10-05 |
| F10.3 | El motor `trimble-rinex`, verificado contra lo que el convertidor hace mal | ✅ 2026-10-05 |
| F10.4 | Que se vea y se encuentre: perfil, ficha, recibo y buscador | ✅ 2026-10-05 |
| F10.5 | **Bajo Wine en p340**: instalar, medir tiempos y fechar la corrida | ⬜ falta instalarlo en el servidor · el 2026-10-05 llegó el MSI firmado 4.0.1.10, probado en Windows con el mismo resultado |
| F10.6 | Motor abierto con RTKLIB `convbin`: RT17, u-blox, Septentrio, NovAtel, RTCM 3, BINEX y Javad a RINEX | ✅ 2026-10-05 · pedido por la persona · falta correrlo en p340 con `apt install rtklib` y un flujo real |
| F10.7 | Informe de calidad de un RINEX, **en código propio** (completitud, huecos, satélites por época, constelaciones), al estilo de lo que hacía TEQC. TEQC no entra: está muerto desde 2019, escribe solo RINEX 2 y no es de código abierto | ✅ 2026-10-05 · `formats/rinex_calidad.py`, en el recibo de toda conversión GNSS · contado contra un recuento independiente sobre el T02 · **no mide** multitrayecto ni saltos de ciclo · el informe suelto de un RINEX ajeno entra con F10.8 |
| F10.8 | RINEX → RINEX de otra versión con `convbin -r rinex` (medido a mano a 2.11) | ✅ 2026-10-05 · formato `rinex_obs` (`.rnx`, `.obs`, `.YYo`), confirmado al abrirlo · el recibo da también su informe de calidad · falta correrlo en p340 |

**Lo que la espiga encontró**, y que ordena el diseño: el convertidor de Trimble sale con
código 0 y dice «Success» con un archivo vacío, con basura y con un T02 cortado a la mitad,
y en este último caso entrega un RINEX más corto sin avisar. Las dos defensas están en
`docs/PRUEBAS_CON_ORACULO.md`.

**Sin oráculo para la integridad frente al crudo**: el T0x es un formato cerrado. Se dice allí,
con el procedimiento manual, igual que ECW.

---

## Fase 11 — Proceso de agentes y base de código

Registrada el 2026-10-05 a partir del kit de proceso (`Claude-info/aeroconvert-claude-kit/`,
fuera del repositorio hasta que la Fase 1 lo aplique). No cambia el comportamiento del producto:
afina cómo trabajan los agentes, deja el gate verde en cualquier máquina y ordena lo que más pesa
antes de la fase visual. **Todo PR va contra `main`, no apilado.** La Fase 2 del kit empieza con
la Fase 1 fusionada.

Medido de nuevo el 2026-10-05 sobre `main` tras el #12: 2.289 pruebas recogidas (3 con oráculo
deseleccionadas), 42.280 líneas en `apps/` de las que 19.527 son de pruebas.

| # | Entrega | Oráculo (cómo se sabe que está) | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F11.1 | **Kit** (Fase 1 del kit): `CLAUDE.md`, `.claude/{settings.json,rules,skills}`, `scripts/claude/{verificar,plan_fila}.py`, dos líneas de `.gitignore`, dos ediciones de `AGENTS.md`. `HANDOFF.md` se parte **al final** y solo sin ramas abiertas que lo toquen | `plan_fila.py --abiertas` y `plan_fila.py F9.4` coinciden con este plan; `verificar.py rapido` y `todo` en verde; un fallo provocado enseña causa y log; `ruff check` y `ruff format --check` limpios; `/context` antes y después en el PR | Claude abre el PR; **la persona decide** si se fusiona | ✅ 2026-10-05 (#14) · `verificar.py todo` y la medida de contexto no corridos; `gh pr merge` sigue negado en `.claude/settings.json` |
| F11.2 | **G0** · dos pruebas que dependen del equipo: `hay_tesseract` debe exigir también el idioma `spa` (`apps/documents/test_ocr.py:26` y `test_ocr_en_cola.py:35`) y `test_el_total_se_recorta_al_tope` (`apps/jobs/test_memoria.py:114`) debe fijar también la RAM | La suite completa pasa con Tesseract sin `spa` y con ≈4 GB de RAM; con `spa` y RAM de sobra sigue corriendo las mismas pruebas (ninguna omitida de más) | Claude | ✅ 2026-10-05 (#15) · el caso «Tesseract sin `spa`» no se reprodujo con un Tesseract real |
| F11.3 | **G1** · alinear los tres gates (`verify.ps1`, `scripts/verificar.sh`, `.github/workflows/ci.yml`) y corregir el comentario desfasado de `verificar.sh` | Una tabla paso × gate sin celdas distintas: `check --fail-level WARNING`, `collectstatic`, `shellcheck` y el módulo de producción en los tres (o la diferencia anotada con su motivo) | Claude | ✅ 2026-10-05 (#16) · CI verde con `shellcheck` y `collectstatic` |
| F11.4 | **G2** · una sola versión (README `v0.3.0-alpha`, `pyproject.toml` `0.1.0`, CHANGELOG `0.1.0`) | `rg` de la cadena de versión: un único valor en los tres sitios | **La persona decide** cuál es la verdadera; Claude lo aplica | ✅ 2026-10-05 · decidió `0.10.0` · `uv.lock` vuelto a resolver |
| F11.5 | **Auditoría de seguridad**, una vez y antes de F9.4: `security-audit` de Cloudflare con el alcance de la superficie pública (`jobs/runner.py`, `engines/`, `documents/{ocr,office,tarea,views}.py`, `dashboard/`, `prod.py`, `scripts/{office_convertir.ps1,desplegar.sh}`). Informe **fuera** del repo; la skill se retira y se anota el commit usado | Informe con severidad, archivo, evidencia y la prueba de 403 o de aislamiento que faltaba, por hallazgo confirmado; los `alta` entran a este plan como filas nuevas | Claude audita; **la persona tría** | ✅ 2026-10-05 · perfil `quick`, cuatro revisores en solo lectura, **sin** ledger ni `findings.json` validados · skill en el commit `c1c8a8c`, nunca instalada y fuera del repo · informe en `C:\Users\cmunoz\security-audit-skill\AeroConvert\run-1\REPORT.md` · hallazgos en F11.9 a F11.11 |
| F11.6 | **Prueba de diseño** para F9.4 y F9.5, tres brazos sobre la misma pantalla (la del resultado de conversión): A sin skill · B `ui-ux-pro-max` · C Ponytail `lite` + `impeccable audit` | Gana el brazo con pruebas verdes, menor diff, 375 px sin desbordes y mejor `npx impeccable detect`; contraste leído del CSS (`/verificar pruebas apps/core apps/dashboard`) y `apps/core/test_estilo.py`. Se descarta el que baje un umbral, cambie tokens sin pasar el test o añada CDN | Claude corre los brazos; **la persona elige** | 🟨 2026-10-06 · medida hecha, **elige la persona** · tres ramas `codex/prueba-diseno-{a,b,c}` sin fusionar · ver el resultado abajo |
| F11.7 | **R1** · dividir `apps/documents/views.py` (1.420 líneas) en paquete `views/` por herramienta, con re-exportación | Mapa de URL idéntico antes y después, suite igual de verde, `fail_under` intacto; un commit por grupo; `/refactor-seguro` | Claude | ✅ 2026-10-05 · `views/` con 11 módulos y `__init__.py` que reexporta · mapa de URL idéntico (20 rutas, antes y después) · suite completa 2349 verdes sin GDAL ni PDAL · un solo commit y no uno por grupo: el corte fue mecánico (`ast`), sin tocar el cuerpo de ninguna función |
| F11.8 | **Etapa 3** · `jobs/runner.py` (1.181 líneas) y las funciones de más de 140 líneas (`inspeccionar`, `_ejecutar_documento`) | Pruebas de caracterización **antes** de tocar, `/oraculo` y paseo en `p340` | **Bloqueada**: solo si la auditoría (F11.5) o el uso la piden · B-07 y B-08 (PID del obrero y árbol de procesos) hechas el 2026-10-06 sin tocar la estructura de `runner.py`; sigue bloqueada para el resto | ⬜ bloqueada |
| F11.9 | **Auditoría · integridad**: C-01 (Markdown a PDF pisa un `.pdf`), A-02 (preajuste ajeno en `encolar`), C-06 (rangos de páginas sin tope y O(n²)), D-04 (`epsgCode` no numérico), D-05 (valores no finitos en TIFF y LAS) | Una prueba por hallazgo que **falla antes y pasa después**; el original con el mismo `sha256` y `mtime` en C-01 | Claude | ✅ 2026-10-05 (#25) · 13 de las 15 pruebas nuevas fallan sin el arreglo |
| F11.10 | **Auditoría · memoria y disco**: D-01/B-02 (libretas leídas enteras), D-02 (línea de RINEX sin tope), B-01 (la estimación no impide una salida enorme), A-05 (cuota de subidas), A-01 (cuerpo anónimo de 2 GB) | Un archivo hostil de tamaño acotado que antes crecía la memoria y ahora no; medido con `tracemalloc` | Claude, salvo A-01 que toca nginx y `p340` | 🟨 2026-10-05 · hechos D-01/B-02, D-02 y B-01 (10 de 11 pruebas nuevas fallan sin el arreglo) · A-05 (cuota por persona) hecha el 2026-10-06 · A-01 (cuerpo anónimo) hecha el 2026-10-06 en la aplicación y en el nginx opcional; **sin medir contra Funnel real** |
| F11.11 | **Auditoría · hechos de `p340` y fixtures**: la prueba de `X-Forwarded-For` ante Funnel (A-03/D-06), el valor real de `AEROCONVERT_RAICES_PERMITIDAS`, y un VRT con extensión `.asc` ante la GDAL desplegada (B-04) | Cifras fechadas en `docs/PRUEBAS_CON_ORACULO.md` | **La persona** corre lo de `p340`; Claude arma los fixtures | ✅ 2026-10-06 · `RAICES_PERMITIDAS=/mnt/entregas` ✔ · B-04 confirmado y corregido (#46) · `X-Forwarded-For` ante Funnel: la persona confirma que la IP registrada es la real (sin salida pegada) |

**Resultado de la prueba de diseño (F11.6), 2026-10-06.** Pantalla: el resultado de una
conversión (`templates/jobs/_progreso.html`), medida en el navegador a 375 px con los cuatro
estados. La primera ronda **se anuló**: los brazos B y C se pisaron entre sí (clases de uno en la
rama del otro) y uno escribió en el repositorio principal por una ruta relativa; se repitieron
desde cero con rutas absolutas, y el reparto de clases se comprobó antes de medir.

| | base | A sin skill | B ui-ux-pro-max | C Ponytail + impeccable |
| --- | ---: | ---: | ---: | ---: |
| Botones principales (hecho) | 2 | 1 | 1 | 1 |
| Alto de la pantalla a 375 px | 2.456 | 1.728 | **1.647** | 1.728 |
| Contenido fuera de 375 px | 0 | 0 | 0 | 0 |
| Detector de impeccable | 6 | 6 | 6 | 6 |
| Pruebas (core, jobs, ficha) | — | 925 ✔ (medido) | 925 ✔ (medido) | 1.032 ✔ (informado) |
| Cambio (líneas) | — | +152 −37 | +188 −46 | +156 −46 |
| Regla compartida tocada | — | no | no | no |

**Lectura:** las tres skills y el brazo sin skill **empatan en todo lo medible**. B acorta un 5 %
más la pantalla a costa de un 24 % más de cambio; el detector no se movió en ninguno porque sus
seis hallazgos están en reglas compartidas que ninguno debía tocar. **Ninguna skill demuestra
ventaja sobre no usar skill.** Dos hallazgos que ningún brazo tocaba: (1) a 375 px **toda la
página** desborda 240 px por el menú «Herramientas» de la barra, que es de `base.html` y no de
esta pantalla; (2) los tres corrigieron «puedes» a «puede» en el titular. Decide la persona qué
rama se adopta como primera pieza de F9.4; ver `HANDOFF.md`.

**Orden propuesto:** F11.1 → F11.2 → F11.3 → F11.4 → F11.5 → F11.6 → F11.7 (F11.8 aparte).
F11.2 y F11.3 son de bajo riesgo y de efecto inmediato; F11.5 y F11.6 deben ir **antes** de F9.4.
El kit trae además G3 (`pytest-xdist`) y R2 (guardia `C901`): solo se abren como filas si la
medición de F11.5 las justifica.

**Lo que el kit no puede hacer en este repositorio sin decisión previa:** su `settings.json`
niega `gh pr merge`, y la regla fijada el 2026-10-05 es que Claude fusiona los PR y la persona
despliega. Hay que elegir uno de los dos antes de aplicar F11.1.

**Dicho sin comprobar:** el kit supone que `catalogos.py`, `tarea.py` y `despachador.py` tienen
poca cobertura porque corren en procesos hijos que la medición del padre no ve. `pyproject.toml`
no configura `concurrency` ni medición de subprocesos, así que es plausible, pero no está medido.

---

## Fase 12 — Una suite de documentos práctica (sustituida por la Fase 14)

> **Pedido del 2026-10-06**, ampliado el 2026-10-07: sus once filas pasaron a la **Fase 14**, que
> las absorbe con su número nuevo (cada una dice «era F12.x»). **F12.1 y F12.10 ya están hechas
> (#54)** y figuran en F14.1 y F14.10. Esta cabecera queda solo para que quien busque «F12» sepa
> adónde mirar: **no hay dos fuentes**. Plan completo: `docs/planes/PLAN_2026-10-07.md`.

---

## Fase 13 — Interfaz: una taxonomía, un idioma, iconos coherentes, plano con color

**Regla de la fase:** no cambia ningún comportamiento. Cada fila deja **una prueba que impide
volver atrás**, igual que `test_escala_visual.py` y `test_iconos.py`. Versión `0.11.0` al cerrarla.

| # | Entrega | Oráculo | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F13.1 | **Una sola taxonomía** en `apps/dashboard/taxonomia.py`, con id estable por grupo, consumida por la portada, el lateral, `/documentos/` y Compatibilidad. Se retiran `CATEGORIAS` y `GRUPOS`. Ocho grupos (`docs/planes/PLAN_2026-10-07.md` §3) | `test_taxonomia.py`: toda herramienta en exactamente un grupo; las pantallas renderizan los mismos grupos en el mismo orden; ningún grupo con menos de 2 herramientas salvo `admite_uno=True`. `data-recuerda` por id estable, no por título | Claude | ✅ 2026-10-07 · `apps/dashboard/taxonomia.py` con 8 grupos y 28 herramientas asignadas; se retiran `CATEGORIAS` y `GRUPOS`; portada, lateral y los dos índices de `/documentos/` leen el mismo árbol; `test_taxonomia.py`. Compatibilidad aún lista por herramienta (sin grupos) |
| F13.2 | **Convención de nombres** aplicada a todas las herramientas, con tabla de renombres en el PR. Comprobar que `ConversionJob` e `Incidente` guardan el id y no el nombre | `test_nombres.py`: patrón por tipo, ≤ 28 caracteres, sentence case; los sinónimos viejos siguen encontrando la herramienta | Claude · **la persona aprueba la tabla** | ✅ 2026-10-07 · tabla aprobada por la persona (programa como título y propósito debajo + 7 renombres); `test_nombres.py`: ≤ 28 caracteres, conversión u operación con verbo, y 12 nombres viejos siguen encontrando |
| F13.3 | **Trato de usted** en plantillas, `que_hace`, mensajes **y `locale/es/…/django.po`** | `test_trato.py`: falla con formas verbales tuteantes con límite de palabra («suelta el», «tu equipo», «eliges», «quieres», «puedes», «sabes»), con lista blanca para «hojas sueltas» y citas | Claude | ✅ 2026-10-07 · ~60 frases a usted; `test_trato.py` mira plantillas (sin comentarios), cadenas de Python, `static/js/` y `locale/es/`; `apps/tino/fuera.py` exento por ser la instrucción al modelo |
| F13.4 | **Iconos sin conflictos**: un icono por significado; `icon-todas`, `icon-tino`, `icon-texto-csv`, `icon-imagen-a-pdf` (renombre); la flecha del lateral entra al sprite | `test_iconos.py`: ningún id para dos significados (mapa explícito) y ningún SVG suelto en plantillas | Claude | ✅ 2026-10-07 · `icon-todas`, `icon-tino`, `icon-texto-csv`, `icon-chevron` nuevos y `icon-pdf-a-pdf` pasa a `icon-imagen-a-pdf`; la flecha del lateral entra al sprite; `test_iconos.py`: ningún icono con dos significados y ningún SVG suelto |
| F13.5 | **Familia de iconos coherente**: retícula 24 × 24, trazo único 1,75, extremos redondeados | `test_iconos.py`: todo `stroke-width` vale 1,75 y todo `viewBox` vale `0 0 24 24` | Claude | ✅ 2026-10-07 · un solo trazo de 1,75 en los 51 símbolos (había 9 grosores), todos 24 × 24 con extremos redondeados; `test_iconos.py` |
| F13.6 | **Color por familia también en lo geoespacial**: `fam-geo`, `fam-gnss`, `fam-pdf-*`, `fam-imagen`, `fam-video`, `fam-planta`. Color + forma + texto | Contraste WCAG leído del CSS de cada `--av-fam-*` y su `-soft`, en los dos temas | Claude | ✅ 2026-10-07 · `fam-gnss` (232°), `fam-planta` (112°) y `fam-imagen` (321°) en los huecos de matiz que dejan las seis familias y los tres estados; contraste en los tres temas y 20° de separación (`test_paleta.py`). `fam-video` queda para F14.17; `destino` hace de `fam-geo` |
| F13.7 | **Plano con color** (decisión 2026-10-07): fuera degradados, `--av-elev-*` a borde de 1 px más cambio de superficie, `hover` por color sin `transform` ni sombra; una sombra solo para lo que flota. **Las baldosas conservan color de familia fuerte, también en oscuro**; sustituye el brillo de #53 | `test_plano.py`: cero `gradient`; `box-shadow` solo en la lista blanca. Contraste de **texto e icono sobre el relleno de la baldosa** en los dos temas | Claude | ✅ 2026-10-07 · 0 degradados (eran 8), sin sombras con difuminado salvo el único nivel de lo que flota (`--av-elev-3`, hoy sin uso), `hover` sin `transform`; baldosas de color sólido, también en oscuro (16 % del color de la familia sobre su fondo); `test_plano.py` y el contraste del icono sobre la baldosa mezclada en `test_paleta.py` |
| F13.8 | **Portada «archivo primero»**: zona de soltar como acción principal, ficha y veredictos debajo, y las herramientas que aplican **a ese archivo**. La cabecera se lee con `File.slice()` de los primeros MB, con vía de respaldo declarada si el formato necesita el final | Paseo a 1440 y 375 px con un BigTIFF: una acción principal y el veredicto «Civil 3D ✗» sin cambiar de pantalla. Prueba de vista (`data-zona-soltar`, un solo botón principal) | Claude | ✅ 2026-10-07 · la portada empieza por la zona de soltar; `File.slice()` manda 4 MiB a `reconocer/` y sale la pista (formato por cabecera o extensión, y si lo de dentro está al final) con las herramientas del archivo; vía de respaldo = la ficha al terminar la subida; `test_portada_archivo.py` |
| F13.9 | **Barra superior en tres zonas**: marca · buscador · cuenta. La explicación del modo pasa al lateral (sigue visible) | A 375 px no desborda y el buscador mide al menos 160 px | Claude | ✅ 2026-10-07 · la explicación del modo al pie del lateral (con sesión); el buscador mide 248 px a 375 px (era 136 por un `width: 8.5rem` y desaparecía bajo 1000 px); `apps/dashboard/test_barra.py` |
| F13.10 | **Estilos en línea fuera**: de 183 `style="…"` a cero salvo valores calculados documentados. PR aparte de F13.3 | `test_escala_visual.py` cuenta `style="` en `templates/` ≤ lista blanca | Claude | ✅ 2026-10-07 · 182 de 183 pasan a clases (Bootstrap o `av-*` con la escala); queda solo el ancho calculado de la barra de avance; 375 y 1440 px sin desborde |
| F13.11 | **Vista de mapa en la ficha**: huella del archivo sobre una retícula de coordenadas, sin mapa base (D5); biblioteca vendorizada con SRI. Nada sale del equipo | Esquinas de la huella frente a `gdalinfo` en EPSG:4326 con error ≤ 1e-7° (ortofoto BHP, `@pytest.mark.oraculo`). La CSP no cambia | Claude | ✅ 2026-10-07 · «Dónde está» en la ficha: SVG del servidor con meridianos y paralelos, sin mapa base ni biblioteca (no hay nada que vendorizar); esquinas = `gdalinfo` ≤ 1e-7° en EPSG:32719, 5361 y 24879 (`test_huella.py`, `test_mapa.py`) |
| F13.12 | **Cerrar F11.6**: se adopta el brazo A y se cierran `codex/prueba-diseno-{b,c}` con nota | Ramas cerradas | La persona confirma | ✅ 2026-10-07 · se adopta el brazo A; `-b` y `-c` ya no existían y la persona mandó borrar `codex/prueba-diseno-resultado` (sin commits fuera de `main`) |
| F13.13 | **Estilo oscuro y transiciones** (referencia visual: ArtCraft): oscuro neutro por omisión, transiciones de 150 a 200 ms solo en color, borde, fondo y opacidad, entrada suave de página y paneles, opciones en fichas junto al botón principal. Sin degradados, sombras ni `transform` al pasar (F13.7) | `test_plano` ampliado: ninguna `transform` en `:hover`, transiciones solo sobre propiedades de estado, bloque `prefers-reduced-motion`; contraste WCAG en los dos temas; paseo en navegador a 1440 y 375 px | Claude | ⬜ |

---

## Fase 14 — Suite documental y creativa libre, en la línea de Adobe

> **Objetivo.** Cubrir con software libre lo que hoy se hace con Acrobat, Acrobat Sign, Adobe Scan,
> Photoshop o Lightroom (lo básico), Illustrator (lo básico), Media Encoder y Bridge, **sin que el
> archivo salga del equipo**. Cada herramienta pasa por la cola, dice qué entrega, no toca el
> original y trae su oráculo con **otro lector**. Programas externos GPL/AGPL: solo sondeados y
> con su paso de instalación (D1). Versión `0.12.0` con las firmas.

| # | Entrega | Oráculo | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F14.0 | **Reparto con Stirling-PDF** (D4): las ~12 de uso diario en casa, Stirling local sondeado para la cola larga | Documento en `docs/` | Claude propone · **la persona aprueba** | ✅ 2026-10-07 · aprobado por la persona; [`docs/DECISION_STIRLING_PDF.md`](docs/DECISION_STIRLING_PDF.md) |
| F14.1 | **Organizar páginas** (era F12.1) y **extraer páginas e imágenes** (era F12.2) | Organizar: PDFium cuenta y pypdf reabre. Extraer: PDFium cuenta; Pillow abre cada imagen | Claude | ✅ 2026-10-07 · organizar (#54); extraer páginas ya lo hace «Dividir PDF» (rangos) y extraer imágenes es nuevo: cada objeto una vez, sin las diminutas, siempre en zip; Pillow abre cada una con el tamaño de la imagen de entrada (`test_extraer_imagenes.py`) |
| F14.2 | **Metadatos**: ver, editar y limpiar antes de entregar (era F12.3) | `pikepdf` lee lo escrito; no quedan `/Author` ni XMP si se pidió limpiar | Claude | ✅ 2026-10-07 · «Ver y limpiar metadatos»: lee Info y XMP, edita campos o limpia todo; se escribe un documento nuevo (pypdf deja el flujo XMP suelto en los bytes si solo se borra `/Metadata`); `pikepdf` reabre y no halla `/Author` ni `/Metadata`, y el nombre no está en los bytes (`test_metadatos.py`) |
| F14.3 | **Formularios**: rellenar y aplanar (era F12.4) | `pypdf` lee los campos; PDFium muestra el valor visible | Claude | ✅ 2026-10-07 · «Rellenar un formulario PDF»: texto y casillas (lo demás se muestra y no se edita); aplanar con PDFium y reescribir sin `AcroForm`; `pikepdf` lee los valores, PDFium dibuja el campo con tinta (`test_formularios.py`) |
| F14.4 | **Firma visible** con imagen y fecha (era F12.5) | PDFium: la imagen aparece en la posición pedida (±2 px) | Claude | ✅ 2026-10-07 · «Poner una firma en un PDF»: imagen + fecha en seis posiciones y tres tamaños, en la página que se elija, también girada; PDFium: la caja cae donde la regla (12 mm de margen) dice, ±2 px (`test_firma_visible.py`). **No es firma digital** y la pantalla lo dice |
| F14.5 | **Firma digital PAdES** con certificado del usuario, sello de tiempo opcional y **verificación** de PDF firmados recibidos (`pyHanko`, MIT) | `pyHanko` valida; `pdfsig` de Poppler, si existe, coincide. La clave privada **nunca** se escribe en disco ni en los registros (prueba con certificado centinela) | Claude | ✅ 2026-10-08 (⚠ sello de tiempo: necesita la URL de una TSA, P14; `pdfsig` no se usó: el otro lector es `hashlib` + `asn1crypto` + `cryptography`) |
| F14.6 | **Recortar márgenes y cambiar el tamaño de página** (era F12.6) | PDFium: el tamaño de cada página coincide con el pedido | Claude | ✅ 2026-10-07 · «Recortar y cambiar el tamaño»: al contenido (PDFium mide lo dibujado), a mano o a otra hoja sin deformar; también en páginas giradas; PDFium: el tamaño coincide con el pedido (±1 pt) y el dibujo queda donde la geometría dice (`test_tamano.py`). Recortar no es borrar y la pantalla lo dice |
| F14.7 | **Comparar dos PDF** con vista lado a lado (era F12.7) | Dos renderizados difieren solo en las regiones informadas | Claude | ✅ 2026-10-07 · «Comparar dos PDF»: se dibujan y restan con PDFium; las regiones cubren el rectángulo que cambió y no tocan el que no (`test_comparar.py`); el informe trae solo las páginas que difieren (antes, después y diferencias en rojo); iguales = desenlace `sin-diferencias`, sin archivo |
| F14.8 | **Redactar de verdad** (era F12.8) | Ni `pypdf` ni `pdftotext` encuentran el texto redactado; la imagen bajo el rectángulo tampoco existe | Claude | ✅ 2026-10-07 · «Redactar: tachar de verdad»: textos y áreas; las páginas afectadas se convierten en imagen y el documento se escribe nuevo, así que ni `pypdf`, ni los flujos decodificados con `pikepdf`, ni la imagen de debajo conservan lo tachado; PDFium dibuja negro donde estaba (`test_redactar.py`). Los términos viajan por `secretos`, nunca por la base. Precio dicho en pantalla: la página redactada ya no tiene texto |
| F14.9 | **PDF/A** con OCRmyPDF y validación con veraPDF sondeado (era F12.9) | veraPDF dice «conforme»; sin veraPDF, ⚠ y la interfaz no afirma conformidad | Claude | ⬜ |
| F14.10 | **Encadenar herramientas** sin volver a subir (era F12.10) | La prueba de la cola; el original conserva su `sha256` | Claude | ✅ 2026-10-07 (#54) · token `resultado:<id>` y «Seguir con este archivo» |
| F14.11 | **Visor y anotaciones** con PDF.js vendorizado, guardadas como anotaciones estándar | PDFium ve las anotaciones; la CSP sigue `'self'` | Claude | ⬜ |
| F14.12 | **Escanear con el teléfono**: fotos a PDF con recorte y corrección de perspectiva, y OCR opcional | La página resultante es rectangular (bordes ±2 %); Tesseract lee una frase de control | Claude | ⬜ |
| F14.13 | **Imágenes**: convertir (HEIC, WebP, AVIF, TIFF, PNG, JPG), redimensionar, recortar, girar y comprimir **por lote** | Pillow reabre cada salida; dimensiones y formato coinciden | Claude | ✅ 2026-10-08 · «Convertir imágenes»: por lote a JPG, PNG, WebP o TIFF, con tamaño, giro (por EXIF o fijo), recorte centrado y calidad; conserva fecha y GPS (en TIFF sin comprimir, medido); HEIC solo si está `pillow-heif` y se dice; Pillow reabre cada salida y formato y medidas coinciden con lo calculado (`test_imagenes_lote.py`) |
| F14.14 | **Fotos de dron**: ver y limpiar EXIF **conservando el GPS** (o quitándolo a propósito); posiciones a KMZ/GeoJSON; renombrar por fecha o vuelo | `exifread` lee lo escrito; `ogrinfo` abre el KMZ y cuenta tantos puntos como fotos | Claude | ✅ 2026-10-08 |
| F14.15 | **Quitar fondo** de una imagen, como extra opcional (D2) | Máscara alfa no vacía; tiempo medido | Claude | ⬜ |
| F14.16 | **Vector y láminas**: SVG a PDF o PNG; DXF a lámina PDF o SVG con `ezdxf` | PDFium renderiza; el número de entidades coincide con `ezdxf` | Claude | 🟨 2026-10-08: DXF a lámina hecho; falta SVG a PDF o PNG (exige Inkscape sondeado, D1) |
| F14.17 | **Video** con FFmpeg sondeado (D1): comprimir, recortar, cambiar formato, quitar audio y **extraer fotogramas** cada N segundos o metros para fotogrametría | `ffprobe` lee duración, códec y resolución; el número de fotogramas coincide | Claude | ⬜ |
| F14.18 | **Telemetría de video de dron**: el `.SRT` de DJI a GPX o KML (puente con AeroLink) | `ogrinfo` abre la traza; el número de puntos coincide con las entradas | Claude | ✅ 2026-10-08 · «Traza de un video de dron»: el `.SRT` de DJI (formato nuevo y antiguo) a GPX o KML; se descartan y cuentan los fotogramas sin posición; la hora solo se escribe si se dice el desfase con UTC; `ogrinfo` abre la traza y cuenta la misma línea y los mismos puntos que las entradas con posición (`test_telemetria.py`, `oraculo`) |
| F14.19 | **Markdown a PDF con la plantilla de J.E.J.** con WeasyPrint | PDFium renderiza; `pypdf` encuentra el texto del pie en cada página | Claude · **la persona entrega la plantilla** | ✅ 2026-10-07 · «Portada de J.E.J.»: rellena las dos plantillas Word de la empresa (**fuera del repositorio**, carpeta `AEROCONVERT_PLANTILLAS_JEJ`) con código, título y autor, o servicio y plan; entrega `.docx` y el PDF es un clic con «Office a PDF». **No usa WeasyPrint**: la persona entregó las plantillas Word y el diseño ya está en ellas. Oráculo: el zip no deja ningún `XXXX`; con Word, el PDF que exporta se lee con `pypdf` y se ve la portada con su logotipo (`test_portadas.py`, 2 pruebas `oraculo`) |
| F14.20 | **HTML a PDF** y **reparar PDF** dañado | PDFium abre el reparado; el número de páginas coincide con lo recuperable | Claude | ✅ 2026-10-07 · «Reparar un PDF dañado» (PDFium reconstruye el índice; `pypdf` estricto no abría el de partida y sí abre el reparado, con sus 3 páginas y su texto) y «Página web a PDF» (HTML → Markdown → PDF: texto, títulos, listas y tablas; **no es un navegador** y la pantalla lo dice) (`test_reparar.py`, `test_html_a_pdf.py`) |
| F14.21 | **Editar Office en el navegador** (era F12.11) | — | **Descartada por D3 (2026-10-07)**; se reabre si el uso la pide dos veces | ⏸ |

---

## Fase 15 — El diferenciador geoespacial

| # | Entrega | Oráculo | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F15.1 | **Datums de Chile**: PSAD56, SAD69, WGS84 y SIRGAS-Chile, con grillas PROJ cuando existan y el método usado escrito en el recibo | `cs2cs`/`projinfo` sobre puntos de control publicados; diferencia ≤ la tolerancia declarada | Claude · **la persona aporta los puntos de control** | ⬜ |
| F15.2 | **Alturas**: elipsoidal ↔ ortométrica con geoide (EGM2008 u otro, sondeado) | `cs2cs` con la misma grilla; diferencia < 1 mm | Claude | ⬜ |
| F15.3 | **Calibración a un sistema local de faena**: Helmert 2D/3D o afín desde puntos de control, con residuales por punto y RMS en el recibo; nunca se adivina (regla 3) | Cálculo independiente con `numpy` en la prueba: mismos residuales a 0,1 mm | Claude | ⬜ |
| F15.4 | **Perfiles mineros**: Deswik, Vulcan, Surpac y Datamine, con su veredicto y formato preferido | Un archivo de cada programa abierto por la persona en el programa real, con fecha en `docs/PRUEBAS_CON_ORACULO.md` | Claude · **la persona valida** | ⬜ |
| F15.5 | **Más perfiles**: Trimble Business Center, Pix4D/Metashape, Leica Cyclone, MicroStation/OpenRoads | Ídem | Claude | ⬜ |
| F15.6 | **Curvas de nivel** desde un DEM a DXF, DWG (vía ODA), SHP y GeoPackage | `gdal_contour` independiente; mismo número de curvas por cota | Claude | ⬜ |
| F15.7 | **LandXML de superficie TIN** para Civil 3D (completa F3.5) | Civil 3D abre la superficie (paseo fechado) y `defusedxml` cuenta caras y puntos | Claude · **la persona valida** | ⬜ |
| F15.8 | **DWG/DGN con ODA instalado** (cierra F3.4) | `ogrinfo` del DXF intermedio; ODA reabre el DWG escrito | **La persona instala** · Claude corre | ⬜ |

---

## Fase 16 — Plataforma: lotes, informe, API

| # | Entrega | Oráculo | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F16.1 | **Lotes**: una carpeta entera con la receta de un cliente, como trabajo padre con hijos | Cada hijo verifica con su oráculo; el padre falla si falla uno y lo dice | Claude | ⬜ |
| F16.2 | **Paquete de entrega**: recetas con nombre («Entrega a BHP») que fijan destinos, CRS y nombres de archivo | La misma receta produce los mismos parámetros en dos corridas | Claude | ⬜ |
| F16.3 | **Informe de verificación en PDF** que acompaña la entrega: ficha antes y después, CRS, estadísticas, `sha256` y veredictos | PDFium lo renderiza; `pypdf` encuentra cada `sha256` en el texto | Claude | ⬜ |
| F16.4 | **API de conversión** con token por usuario y permisos | Prueba de 403 por extremo; un cliente `httpx` de prueba convierte un TIFF de punta a punta | Claude | ⬜ |
| F16.5 | **Integración con AeroBim** (cierra F4.2) por API | AeroBim abre el COG y el COPC entregados (paseo fechado) | Claude | ⬜ |
| F16.6 | **`RegistroDeSonda`**, `remuestreo` y `nodata` expuestos, y traducciones compiladas (deuda conocida) | Pruebas de cada uno; `test_traducciones.py` verde con `.mo` versionado | Claude | ⬜ |

## Fase 17 — Poner en marcha lo que hoy sale apagado

Detalle y pasos en `docs/PUESTA_EN_MARCHA_DE_LO_APAGADO.md`. Lo que exige licencia, clave o
instalar en la VM es de la persona (P7, P10, P12, P13); lo demás, de Claude.

| # | Entrega | Oráculo | La cierra | Estado |
| --- | --- | --- | --- | --- |
| F17.1 | **Office a PDF con LibreOffice**, opción rotulada «puede variar», sondeada y ejecutada aparte (D1) | PDFium cuenta páginas y halla el texto conocido de un documento de partida | Claude | ⬜ |
| F17.2 | **Leer catálogos `.accdb`/`.mdb` sin Access** con `mdbtools` | Las nueve tablas con su número de filas, contadas por `pyodbc` en la estación con Access | Claude | ⬜ |
| F17.3 | **Pantalla «cómo dejar listo el equipo»**: el paso exacto por cada apagado y la sonda en vivo | Prueba de vista: cada motivo del catálogo trae su paso | Claude | ⬜ |
| F17.4 | **`despliegue/instalar_faltantes.sh`**: instala por `apt` lo que no pide licencia (FFmpeg, Ghostscript, Inkscape, mdbtools, LibreOffice, `xvfb`) | `shellcheck` en el CI | Claude | ⬜ |

---

## Deuda conocida

> **Cómo se lee esta tabla, y por qué hizo falta arreglarla.**
>
> Al auditarla el 2026-09-21 salió un defecto del propio documento: **tres filas apuntaban a
> F1.7, que está marcada ✅**. O se pagaron y nadie actualizó la tabla, o la fase se cerró con
> la deuda dentro — y no había forma de saber cuál. Una tabla de deuda que no permite saber si
> algo sigue abierto no sirve para nada, que es justo lo contrario de su propósito.
>
> Ahora cada fila lleva **estado comprobado contra el código**, no contra el plan. Las tres
> que quedaban «por verificar» se verificaron el 2026-09-21, una por una, abriendo el
> archivo. **Dos estaban pagadas desde hacía semanas** y la tercera era peor de lo que la
> fila decía.

| Qué | Por qué está | Estado |
| --- | --- | --- |
| Sin `RegistroDeSonda` | La matriz se calcula en vivo; falta el historial de «el día que GDAL desapareció» | **Abierta** — comprobado: el identificador no aparece en ningún `.py` |
| ~~El modo experto solo elige formato~~ | — | **Saldada** — `engines/formulario.py:113` construye los campos desde `motor.opciones(par)` y `_ajustes.html` los pinta. El ráster declara compresión, banda alfa, pirámides, tesela y calidad; el vectorial, CRS de destino y solo-geometría |
| Sin remuestreo ni nodata en la interfaz | El plan los acepta; falta exponerlos | **Abierta, y peor de lo que decía.** `raster/motores.py:234` **lee** `opciones["remuestreo"]` y nadie lo declara: es un parámetro que se puede leer y no se puede poner, o sea código muerto con aspecto de función. `nodata` no aparece en ningún `.py` |
| Sin traducciones compiladas | Los nombres de formato salen en inglés, que es su `msgid` | **Abierta** — no hay `.mo` compilados |
| ~~El LAS no reporta su CRS~~ | — | **Saldada** — `formats/las.py:169` lee las VLR y saca EPSG y WKT, con el bit de `global_encoding` que decide cuál manda |
| Soltar un archivo solo da su nombre | El navegador no entrega la ruta completa, por seguridad. Quedan las dos vías: subir o explorar la compartida | no se paga |
| El correo no es único en la base | `auth.User` no lo declara así, y cambiarlo obliga a migrar el modelo con la base ya en producción. El alta lo impide y el backend se niega a elegir entre dos | cuando toque tocar el modelo por otra cosa |
| Office solo en Windows | Hablan con Word por COM. En el servidor salen apagadas con su motivo | no se paga · la alternativa entrega un documento que *se parece* |
| Seis pruebas dependen del equipo | Cinco de `TestDondeTesseractEsta` fallan con Tesseract sin `spa` y `test_el_total_se_recorta_al_tope` falla con ≈4 GB de RAM: el gate deja de ser verde «en una máquina cualquiera» (2026-10-05, leído en el código; la falla no se ha reproducido aquí) | **Abierta** → F11.2 |
| Los tres gates no comprueban lo mismo | `--fail-level WARNING` y `shellcheck` solo en `verificar.sh`; `collectstatic` solo en el CI | **Abierta** → F11.3 |
| Tres versiones distintas | README `v0.3.0-alpha`, `pyproject.toml` `0.1.0`, última entrada del CHANGELOG `0.1.0` | ~~Tres versiones distintas~~ **Saldada** 2026-10-05 → `0.10.0` en los tres (F11.4) |
| Cobertura baja en `catalogos.py`, `tarea.py`, `despachador.py` | Quizá corren en procesos hijos que `pytest --cov` no ve; **inferencia sin medir** | **Abierta** → se mide en F11.5 |

---

## Lo que solo podías decidir tú

No son cosas que se resuelvan programando mejor. **Cuatro se resolvieron el 2026-09-21** y
quedan aquí anotadas con su fecha: una decisión sin registro se vuelve a discutir.

| Decisión | Qué estaba en juego | Resuelto |
| --- | --- | --- |
| **Nombre del ayudante** | Es de familia: se usa en las tres aplicaciones | **Tino** · 2026-09-21 |
| **¿El ayudante habla con un modelo de fuera?** | El argumento entero de la aplicación es que nada sale del equipo | **Solo la pregunta escrita, nunca el archivo** —ni su nombre, ni su contenido— y dicho en pantalla cada vez · 2026-09-21 |
| **Catálogos `.mdb`: ¿Plant 3D o CADWorx?** | El esquema se parece entre los dos y las tablas no son iguales. Adivinar mal es entregar un catálogo que el programa abre y falla en obra | **Plant 3D.** F7.6 se cierra sin cambios · 2026-09-21 |
| **DWG y DGN por ODA (F3.4)** | Es el formato de intercambio diario de una oficina de topografía, y hoy no se convierte | **Sí**, se instala el conversor y se hace · 2026-09-21 |
| **ECW** | Medio día y una licencia de pago, para 10 conversiones que ya tienen salida abierta | Abierta — no, hasta que alguien lo pida dos veces |
| **Office en el servidor** | LibreOffice daría Word→PDF en Linux, pero *parecido* no es *idéntico* | Abierta — dejarlas apagadas |
| **Dónde va la copia de respaldo fuera de la máquina** | El servicio escribe en el mismo NVMe que la base: un fallo del disco se lo lleva todo a la vez | **Abierta, y es lo único de la lista sin arreglo posible después** |
| **¿El repositorio sigue público?** | `HANDOFF.md` expone rutas, puerto y la carpeta compartida de p340 | **Abierta** · si sigue público, esos datos salen a un archivo fuera del repositorio |
| **Ejecutor del plan F13–F16** | Quién escribe las filas | **Claude**, un PR por fila, CI verde y fusiona; la persona despliega · 2026-10-07 |
| **Diseño: plano o con relieve** | La persona pidió «menos plano» el 06-10 y el plan F13.7 quita el relieve | **Plano con color:** sin degradados, sombras ni movimiento; baldosas de familia con color fuerte, también en oscuro · 2026-10-07 |
| **D1 · programas externos GPL/AGPL** (FFmpeg, Ghostscript, Inkscape) | Sin ellos no hay video | **Sí**, solo sondeados y ejecutados aparte, nunca importados ni copiados; cada uno con su sonda y su paso en `SERVIDOR.md` · 2026-10-07 |
| **D2 · `rembg` con `onnxruntime`** | ~40 MB, y `markitdown` se rechazó por lo mismo | Solo como extra opcional (`uv sync --extra imagen`), apagado con motivo si falta · 2026-10-07 |
| **D3 · Editar Office en el navegador** | Un servicio más expuesto a internet | **No por ahora**; se reabre si el uso lo pide dos veces · 2026-10-07 |
| **D4 · Reparto con Stirling-PDF** | Amplitud frente a un servicio Java de 1–2 GB | Las ~12 de uso diario en casa; Stirling local sondeado para la cola larga · 2026-10-07 |
| **D5 · Mapa base de la ficha** | Las teselas de internet rompen «nada sale del equipo» | Retícula de coordenadas sin mapa base; teselas propias opcionales · 2026-10-07 |
| **D6 · «Planta» como grupo propio** | Hoy son 2 herramientas | Dentro de «Imagen, video y planta» hasta que haya 4 · 2026-10-07 |

> **Corrección del 2026-09-21.** Este documento y `SERVIDOR.md` decían «hoy no hay ningún
> respaldo» — y el repositorio trae `aeroconvert-respaldo.service` y `.timer` (03:15,
> `Persistent=true`), que el README habilita. La afirmación se repitió durante días sin
> comprobarla. Lo que falta con certeza es la **copia fuera de la máquina**.
