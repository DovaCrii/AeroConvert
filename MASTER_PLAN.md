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
| F3.4 | DWG y DGN v8 por ODA; DGN v7 por GDAL | ⬜ |
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

| # | Entrega | Notas |
| --- | --- | --- |
| F7.1a | **Excel → Markdown** | Una hoja es una tabla y Markdown tiene tablas. Es la conversión más directa del grupo y probablemente la más pedida |
| F7.1b | **PDF → Markdown** | Solo del texto que el PDF ya tiene. Un PDF escaneado no tiene texto y hay que **decirlo**, no entregar una página en blanco: eso es OCR, y es F5.11 |
| F7.1c | **Word → Markdown** | Títulos, listas, tablas y negritas. Lo que no sobrevive —cuadros de texto, columnas— se avisa antes |
| F7.1d | **Markdown → PDF** | El camino de vuelta, para entregar lo que se redactó en Markdown |

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

### F7.5 — La barra, cuando entren más aplicaciones

La distribución de ahora funciona y **no hay que rehacerla**. Lo que falta es lo de al lado:
un acceso a las aplicaciones hermanas —AeroControl, AeroBim— desde la misma barra, porque hoy
viven en el mismo servidor y en puertos distintos que nadie recuerda.

---

## Deuda conocida

| Qué | Por qué está | Cuándo se paga |
| --- | --- | --- |
| Sin `RegistroDeSonda` | La matriz se calcula en vivo; falta el historial de «el día que GDAL desapareció» | F1.1 |
| El modo experto solo elige formato | Las opciones del motor ya son declarativas, pero el formulario aún no las despliega | F1.7 |
| Sin remuestreo ni nodata en la interfaz | El plan los acepta; falta exponerlos | F1.7 |
| Sin traducciones compiladas | Los nombres de formato salen en inglés, que es su `msgid` | F1.7 |
| El LAS no reporta su CRS | Vive en las VLR, que aún no se leen | F2.3 |
| Soltar un archivo solo da su nombre | El navegador no entrega la ruta completa, por seguridad. Por eso hay tres vías: subir, explorar la compartida, o pegar la ruta | no se paga |
| El correo no es único en la base | `auth.User` no lo declara así, y cambiarlo obliga a migrar el modelo con la base ya en producción. El alta lo impide y el backend se niega a elegir entre dos | cuando toque tocar el modelo por otra cosa |
| Office solo en Windows | Hablan con Word por COM. En el servidor salen apagadas con su motivo | no se paga · la alternativa entrega un documento que *se parece* |

---

## Lo que solo puedes decidir tú

No son cosas que se resuelvan programando mejor.

| Decisión | Qué está en juego | Mi recomendación |
| --- | --- | --- |
| **Nombre del ayudante** | Es de familia: se usa en las tres aplicaciones | **Tino** |
| **Si el ayudante habla con un modelo de fuera** | El argumento entero de la aplicación es que nada sale del equipo | Que salga la pregunta, nunca el archivo — y dicho en pantalla |
| **ECW** | Medio día y una licencia de pago, para 10 conversiones que ya tienen salida abierta | No, hasta que alguien lo pida dos veces |
| **Office en el servidor** | LibreOffice daría Word→PDF en Linux, pero *parecido* no es *idéntico* | Dejarlas apagadas |
| **Respaldo del servidor** | Hoy no hay ninguno, con tres aplicaciones y exposición pública | Es lo más urgente de todo lo que queda |
