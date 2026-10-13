# Frontera de documentos: qué saldría a otro repositorio (F21.2, decisión D11)

**No se mueve nada todavía.** Este inventario dice qué habría que llevarse si las 42 herramientas de documentos
(PDF, Office, EPUB, OCR, imágenes, firma, video) pasaran a otra aplicación de la suite, y qué de lo común
tendrían que seguir usando. Se midió el 2026-10-13 sobre `origin/main`. La regla de separación está en
`docs/ARQUITECTURA_PRODUCTO.md`; la vigila `apps/core/test_frontera_documentos.py`.

## Lo que vigila la prueba

Por análisis de `ast` (sin importar nada), ninguno de los módulos de `raster`, `pointcloud`, `vector`, `gnss`,
`mesh`, `visor`, `vuelos`, `formats` y `targets` importa `apps.documents`, salvo lo declarado. Además vigila las
dos formas de acoplamiento que un `import` no muestra: nombres de ruta `documents:...` y plantillas
`documents/...`. La prueba **falla de verdad** ante un intruso (hay un caso con un módulo sintético en una
carpeta temporal, y se comprobó a mano con un `from apps.documents.office import x` en `apps/raster/`), y también
cuando una excepción ya no hace falta.

### Excepciones declaradas (lo que hoy cruza la frontera)

| Dónde | Qué cruza | Motivo | Qué haría falta para quitarla |
| --- | --- | --- | --- |
| `apps/vuelos/*` (4 módulos de `vuelos`) | `apps.documents.cola`, `.composicion` (`ComposicionInvalida`), `.views._comun`, `.motor` (`disponibilidad`) | Las herramientas de vuelo (telemetría, fotos de dron, vuelo PPK) se registran en la cola y el despachador de documentos | Subir cola, error de composición, entrada de archivos y `disponibilidad` a un paquete común (`apps/jobs` o `apps/core`) |
| `apps/visor/vuelo.py` | `reverse("documents:vuelo_ver" / "vuelo_miniatura" / "vuelo_ficha")` | Las pantallas del vuelo cuelgan del espacio de nombres `documents:` | Montar `apps/vuelos/urls.py` con su propio `app_name` |
| `templates/vuelos/vuelo_visor.html` | `documents:vuelo_datos`, `vuelo_miniatura`, `vuelo_ficha` | Igual | Igual |
| `templates/vuelos/telemetria.html`, `video.html` | `{% include "documents/_origen.html" %}` | Reutilizan el selector de origen | Mover `_origen.html` a `templates/core/` |
| `templates/vuelos/vuelo_dron.html` | `{% include "documents/_paso_vuelo.html" %}` | Reutiliza el paso de vuelo | Mover `_paso_vuelo.html` a `templates/vuelos/` |

Ningún import cruza hoy fuera de `vuelos` (comprobado). Lo que **sí** cruza es la dirección contraria, que es la
que más estorba al corte, y no la vigila esta prueba:

- `apps/documents/motor.py` y `tarea.py` **contienen la lógica de despacho de las herramientas de vuelo**
  (`vuelo_ppk`, `vuelo_rtk`, `vuelo_pos`, `vuelo_exif`, `fotos_dron`, `telemetria`, `video`).
- `apps/documents/urls.py` **incluye `apps.vuelos.urls`** bajo el espacio de nombres `documents`.
- `apps/jobs/{despachador,runner,models,views}.py`, `apps/dashboard/{acciones,recientes,taxonomia}.py`,
  `apps/engines/{equipo,views}.py` y `apps/core/context_processors.py` consultan `documents` (herramientas,
  `estado_de_herramientas`, `secretos`, `motor`).
- `apps/documents/dxf_lamina.py` (DXF a PDF/SVG, lámina) es geoespacial por su origen y hoy está registrada como
  herramienta de documentos.

## Qué se movería

### Aplicación Django `apps/documents/` (90 archivos)

- **Motores y piezas** (módulos de primer nivel): `a_epub`, `a_imagenes`, `a_markdown`, `catalogos`,
  `catalogos_mdbtools`, `comparar`, `comprimir`, `desde_markdown`, `dividir`, `escanear`, `extraer_imagenes`,
  `firma_comprobar`, `firma_digital`, `firma_visible`, `formularios`, `html_a_pdf`, `imagenes_lote`,
  `libreoffice_hijo`, `marcas`, `metadatos`, `miniaturas`, `ocr`, `office`, `pdfa`, `portadas`, `receta`,
  `redactar`, `reparar`, `seguridad`, `tamano`.
- **Núcleo del despacho de documentos**: `herramientas.py` (el registro), `motor.py` (sondas, planes, informes),
  `tarea.py` (lo que ejecuta el proceso hijo), `cola.py`, `composicion.py`, `secretos.py`, `apps.py`, `urls.py`.
  `cola`, `composicion`, `secretos` y `motor` mezclan lo propio con lo que usa la cola general: hay que **partirlos**
  antes de moverlos (ver «Lo común»).
- **Vistas**: `apps/documents/views/` (`_comun.py` y una `pantalla_*.py` por herramienta).
- **Pruebas**: 49 `test_*.py` en `apps/documents/`, más `apps/jobs/test_runner_documentos.py`,
  `test_runner_caracterizacion.py` (parte de documentos), `apps/dashboard/test_taxonomia.py`,
  `test_portada_archivo.py`, `test_nombres.py` y `apps/core/test_iconos.py` en lo que usan `HERRAMIENTAS`.

### Las 42 herramientas (`apps/documents/herramientas.py`)

`unir`, `organizar`, `dividir`, `tamano`, `comparar`, `portada`, `pdf_a`, `reparar`, `html_a_pdf`,
`imagenes_lote`, `imagenes`, `escanear`, `a_imagenes`, `extraer_imagenes`, `comprimir`, `ocr`, `numerar`,
`marca`, `formularios`, `firma_visible`, `firmar`, `verificar_firmas`, `metadatos`, `redactar`, `proteger`,
`office`, `a_word`, `md_excel`, `md_csv`, `md_word`, `md_pdf`, `md_epub`, `md_html`, `md_a_pdf`, `a_epub`,
`catalogo_excel`, `excel_catalogo`: **37 de documentos puros**.

**Se quedan o se discuten (5)**, porque son geoespaciales: `telemetria`, `video`, `vuelo_dron`, `fotos_dron`
(vuelos de dron, ya implementados en `apps/vuelos/`) y `dxf_lamina` (lámina técnica, base de F21.5). La
decisión de la etapa es que el registro **se parta en dos** y estas cinco pasen al registro geoespacial.

### Plantillas (`templates/documents/`, 36 archivos)

`inicio.html`, una plantilla por herramienta (`unir`, `dividir`, `office`, `ocr`, `firmar`…), y las piezas
`_origen.html` y `_paso_vuelo.html`. Ver las excepciones: `_origen.html` y `_paso_vuelo.html` los usan las
plantillas de vuelos y **no se mueven con documentos**. `dxf_lamina.html` se queda con lámina.

### Estáticos

Ninguna hoja ni script lleva el nombre `documents`. Los iconos `icon-pdf-*` y similares viven en
`static/img/icons.svg` (compartido); habría que **extraer los de documentos** a su propio sprite. El CSS de
`static/css/app.css` es común: lo propio de documentos (vista previa de páginas, firma) se localiza por prefijo
al hacer el corte.

### Ajustes (`config/settings/base.py`)

`"apps.documents"` en `INSTALLED_APPS`, `path("documentos/", include("apps.documents.urls"))` en
`config/urls.py`, y las variables de herramientas externas que solo usa documentos: `AEROCONVERT_LIBREOFFICE`,
`AEROCONVERT_MDBTOOLS`, `AEROCONVERT_FFMPEG` (compartida con vuelos), `AEROCONVERT_GHOSTSCRIPT` y `AEROCONVERT_VERAPDF`
(Tesseract se sondea sin variable de ajuste). El resto de ajustes es común.

### Dependencias (`pyproject.toml`)

| Paquete | Quién más lo usa (imports de primer nivel fuera de `apps/documents`) | Destino |
| --- | --- | --- |
| `pypdfium2`, `pikepdf`, `pyhanko`, `openpyxl`, `python-docx`, `markdownify`, `beautifulsoup4`, `pyodbc` | nadie | **se van con documentos** |
| `cryptography` | nadie directamente (la necesita `pypdf` para AES-256) | se va con documentos |
| `pypdf` | `apps/formats/pdf.py` | queda: `formats` lee PDF; documentos lo reutiliza |
| `reportlab` | `apps/jobs/informe.py` (informe del trabajo) | queda; la lámina de F21.5 lo usa |
| `pillow` | `visor`, `vuelos`, `raster` (pruebas) | queda |
| `ezdxf` | `ezdxf` solo lo usa `dxf_lamina` | acompaña a `dxf_lamina` (se queda con lámina) |
| `exifread` | `vuelos` | queda |

Programas externos (sondas, no dependencias del paquete): LibreOffice, mdbtools, Tesseract, Ghostscript, veraPDF
y FFmpeg se van con documentos; FFmpeg se queda además para el video de vuelos si esa herramienta se queda.

## Lo común que documentos usa y tendría que seguir encontrando

| Pieza | Dónde vive | Cómo la usa documentos |
| --- | --- | --- |
| La cola de trabajos y su modelo | `apps/jobs/` (`ConversionJob`, `EntradaDeTrabajo`, `retencion`, `runner`, `despachador`) | `cola.py` encola; el runner **importa `apps.documents.motor`** (dirección inversa) |
| Contrato de motor | `apps/engines/base.py` (`Disponibilidad`, `PlanDeEjecucion`, `Verificacion`, `ruta_parcial`) | todos los motores |
| Lectura de PDF | `apps/formats/pdf.py` | casi todos los motores de PDF |
| Entrada, modo y subidas | `apps/core/{entrada,modo,subidas}.py` | todas las vistas |
| Taxonomía y buscador | `apps/dashboard/taxonomia.py` | `views/_comun.py` |
| Motivos y bitácora | `apps/jobs/motivos.py`, bitácora | apagado con motivo (regla 4) |
| Permisos, plantilla base, `static/vendor` | `apps/core`, `templates/base.html` | todas las pantallas |

**Orden propuesto para el corte (F21.11):** (1) subir `cola`, `composicion.ComposicionInvalida`, `views._comun`
y `motor.disponibilidad` a un paquete común y apuntar vuelos a él, con lo que desaparece la lista de
excepciones de import; (2) dar a vuelos su espacio de nombres de rutas y sus plantillas; (3) partir
`herramientas.py`, `motor.py` y `tarea.py` en geoespacial y documentos; (4) que el runner y la taxonomía lean un
registro y no importen `apps.documents`; (5) mover la app, sus 49 pruebas, sus plantillas y sus dependencias.
