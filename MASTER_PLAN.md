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
| F3.4 | DWG y DGN v8 por ODA; DGN v7 por GDAL | ⬜ · **decidido el 2026-09-21: se hace.** Ver Fase 8 |
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
| F5.10 | Comprimir, con vista previa antes de escribir | ⬜ |
| F5.11 | OCR con Tesseract sondeado, no declarado | ⬜ |

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
| F7.1b | **PDF → Markdown** | Solo del texto que el PDF ya tiene. Un PDF escaneado no tiene texto y hay que **decirlo**, no entregar una página en blanco: eso es OCR, y es F5.11 | ✅ 2026-09-15 |
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
| F7.2c | El mismo trato en la pantalla de convertir: los destinos geoespaciales como tarjetas con su formato de salida | ⬜ |

### F7.3 — Las herramientas de PDF que faltan

De la lista de iLovePDF, ordenadas por lo que se pide de verdad en una oficina de topografía:

| # | Entrega | Por qué, y qué cuesta |
| --- | --- | --- |
| F7.3a | **Comprimir PDF** | Un juego de planos no entra en un correo. Con `pypdf` se recomprimen las imágenes; vista previa antes de escribir |
| F7.3b | **Ordenar, eliminar y extraer páginas** | Ya está medio hecho: la receta de «unir» sabe hacerlo, falta la pantalla de una sola entrada |
| F7.3c | **Rotar PDF** | Tres líneas con `pypdf`. Está ya dentro de «unir», suelto no |
| F7.3d | **OCR** | Tesseract **sondeado, no declarado**, como todo lo externo aquí. Es lo que convierte un escaneo en algo buscable, y es la puerta de F7.1b |
| F7.3e | **Firmar PDF** | El caso real es el acta firmada. Firma dibujada primero; la digital con certificado es otra cosa y otra fase |
| F7.3f | Comparar, censurar, recortar, reparar, HTML a PDF, PDF/A, formularios | La cola larga. Cada una entra cuando alguien la pida dos veces |

### F7.4 — Un ayudante que guíe

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

## Deuda conocida

> **Cómo se lee esta tabla, y por qué hizo falta arreglarla.**
>
> Al auditarla el 2026-09-21 salió un defecto del propio documento: **tres filas apuntaban a
> F1.7, que está marcada ✅**. O se pagaron y nadie actualizó la tabla, o la fase se cerró con
> la deuda dentro — y no había forma de saber cuál. Una tabla de deuda que no permite saber si
> algo sigue abierto no sirve para nada, que es justo lo contrario de su propósito.
>
> Ahora cada fila lleva **estado comprobado contra el código**, no contra el plan.

| Qué | Por qué está | Estado |
| --- | --- | --- |
| Sin `RegistroDeSonda` | La matriz se calcula en vivo; falta el historial de «el día que GDAL desapareció» | **Abierta** — comprobado: el identificador no aparece en ningún `.py` |
| El modo experto solo elige formato | Las opciones del motor ya son declarativas, pero el formulario aún no las despliega | **Por verificar** — F1.7 se cerró y la deuda no se tachó |
| Sin remuestreo ni nodata en la interfaz | El plan los acepta; falta exponerlos | **Por verificar** — igual que la anterior |
| Sin traducciones compiladas | Los nombres de formato salen en inglés, que es su `msgid` | **Abierta** — no hay `.mo` compilados |
| El LAS no reporta su CRS | Vive en las VLR, que aún no se leen | **Probablemente saldada** — F2.3 se cerró con «un CRS ausente es detención dura». Confirmar y tachar |
| Soltar un archivo solo da su nombre | El navegador no entrega la ruta completa, por seguridad. Quedan las dos vías: subir o explorar la compartida | no se paga |
| El correo no es único en la base | `auth.User` no lo declara así, y cambiarlo obliga a migrar el modelo con la base ya en producción. El alta lo impide y el backend se niega a elegir entre dos | cuando toque tocar el modelo por otra cosa |
| Office solo en Windows | Hablan con Word por COM. En el servidor salen apagadas con su motivo | no se paga · la alternativa entrega un documento que *se parece* |

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

> **Corrección del 2026-09-21.** Este documento y `SERVIDOR.md` decían «hoy no hay ningún
> respaldo» — y el repositorio trae `aeroconvert-respaldo.service` y `.timer` (03:15,
> `Persistent=true`), que el README habilita. La afirmación se repitió durante días sin
> comprobarla. Lo que falta con certeza es la **copia fuera de la máquina**.
