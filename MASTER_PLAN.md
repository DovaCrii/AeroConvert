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
| F0.6 | Vendorizado | Bootstrap 5.3.3 y htmx 2.0.10 con SRI en `static/vendor/`, CSP `'self'` | ⬜ |

## Fase 1 — Ráster, de punta a punta

| # | Bloque | Entrega | Estado |
| --- | --- | --- | --- |
| F1.0 | Catálogo y detección | `apps.formats`: catálogo, lector TIFF/BigTIFF propio, firmas, `Crs`, `PuntoConCrs`, acompañantes | ✅ 2026-09-08 |
| F1.1 | Motores | Contrato, registro, sondas de GDAL/PROJ/PDAL/ECW/ODA, matriz de capacidades, `/motores/`, API | 🟨 lógica lista, falta `RegistroDeSonda` y la plantilla |
| F1.2 | Trabajos | `ConversionJob`, `JobEvent`, runner, despachador, reclamo atómico, latido, cancelación, escritura atómica | ✅ 2026-09-08 |
| F1.3 | Perfiles de destino | `apps.targets` y la tira de veredictos | ✅ 2026-09-08 |
| F1.4 | La mesa | Ficha del archivo, destino por software, modo experto, progreso htmx, el recibo, historial | ⬜ |
| F1.5 | Ráster GDAL | GeoTIFF/BigTIFF ↔ COG, JP2, IMG, ASC; reproyección, pirámides, alfa descartada, verificación con `gdalinfo` | ✅ 2026-09-08 |
| F1.6 | ECW | `gdal-ecw` con clave OEM y `ecw-externo`, tres motivos, alternativa COG/JP2, «reencolar como JP2» | ⬜ |
| F1.7 | Preajustes y pulido | `ConversionPreset`, repetir trabajo, estimación de memoria y espacio, detector de atasco, i18n | ⬜ |

**Valores por omisión ya decididos, y medidos** (ver `PRUEBAS_CON_ORACULO.md` §2):

- Archivo maestro → **GeoTIFF clásico, DEFLATE-9, predictor 2**. Idéntico bit a bit y 33 MB
  menos que LZW: LZW no tiene ninguna ventaja.
- Entrega y CAD → **JPEG 2000**. 13 % del peso con 51,7 dB y error máximo de 4 sobre 255 —
  mejor calidad *y* mejor comportamiento que un TIFF con JPEG q92.

## Fase 2 — Nubes de puntos

| # | Entrega | Estado |
| --- | --- | --- |
| F2.1 | LAS/LAZ → COPC portando `AeroBim/apps/web/scripts/a-copc.py` | ⬜ |
| F2.2 | E57 y diezmado con PDAL (`filters.sample`) | ⬜ |
| F2.3 | Lectura del CRS desde las VLR del LAS. **Aquí un CRS ausente es detención dura, sin excepción** | ⬜ |
| F2.4 | La aritmética de precisión: `float32` pierde 200 mm en el norte UTM si no se resta el desplazamiento de cabecera | ⬜ |

## Fase 3 — Vectorial, CAD y topografía

| # | Entrega | Estado |
| --- | --- | --- |
| F3.1 | OGR: SHP, GPKG, GeoJSON, GML, GPX, DXF | ⬜ |
| F3.2 | KML y KMZ reusando `AeroControl/apps/geo/kml/parse.py` | ⬜ |
| F3.3 | **Archivos de puntos PNEZD/PENZD/NEZ/ENZ, con vista previa en mapa antes de convertir** | ⬜ |
| F3.4 | DWG y DGN v8 por ODA; DGN v7 por GDAL | ⬜ |
| F3.5 | LandXML: superficies y alineamientos para Civil 3D | ⬜ |

## Fase 4 — BIM y malla

| # | Entrega | Estado |
| --- | --- | --- |
| F4.1 | IFC con `ifcopenshell`, OBJ, glTF/GLB, 3D Tiles | ⬜ |
| F4.2 | Integración con AeroBim, por archivo o API | ⬜ |

---

## Deuda conocida

| Qué | Por qué está | Cuándo se paga |
| --- | --- | --- |
| No hay plantillas ni CSS | La interfaz es F1.4. **Hoy solo se puede convertir desde el shell** | F1.4 |
| Sin `RegistroDeSonda` | La matriz se calcula en vivo; falta el historial de «el día que GDAL desapareció» | F1.1 |
| Sin remuestreo ni nodata configurables | El plan los acepta, el formulario aún no existe | F1.4 |
| El LAS no reporta su CRS | Vive en las VLR, que aún no se leen | F2.3 |
| Sin traducciones compiladas | No hay cadenas de interfaz todavía | F1.4 |
