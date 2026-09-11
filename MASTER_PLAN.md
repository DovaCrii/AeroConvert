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

## Deuda conocida

| Qué | Por qué está | Cuándo se paga |
| --- | --- | --- |
| Sin `RegistroDeSonda` | La matriz se calcula en vivo; falta el historial de «el día que GDAL desapareció» | F1.1 |
| El modo experto solo elige formato | Las opciones del motor ya son declarativas, pero el formulario aún no las despliega | F1.7 |
| Sin remuestreo ni nodata en la interfaz | El plan los acepta; falta exponerlos | F1.7 |
| Sin traducciones compiladas | Los nombres de formato salen en inglés, que es su `msgid` | F1.7 |
| El LAS no reporta su CRS | Vive en las VLR, que aún no se leen | F2.3 |
| Soltar un archivo solo da su nombre | El navegador no entrega la ruta completa, por seguridad. Pegar la ruta es el camino fiable | no se paga |
