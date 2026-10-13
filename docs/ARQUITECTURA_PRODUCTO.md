# AeroConvert, motor geoespacial de la suite Aero (decisión D11, 2026-10-13)

Parte de la guía `AeroConvert_Product_Architecture.md` que entregó la persona. Aquí queda **lo que se adopta, lo
que se ajusta y el estado real** contra el código. Las filas están en la Fase 21 de `MASTER_PLAN.md` y el
bloque B16 de `docs/planes/SEGUIMIENTO.md`.

## Propósito

AeroConvert transforma, procesa, optimiza, visualiza y publica datos geoespaciales: ráster, ortofotos, nubes de
puntos, vectores, superficies y topografía, con reproyección y CRS. **No es un convertidor genérico ni un GIS
general.** El diferenciador es el flujo completo:

```text
archivo bruto → transformar → procesar → ver → mapa automático → lámina técnica → entregable
```

**Regla de separación:** si el archivo necesita coordenadas, CRS, extensión espacial, geometría, ráster
georreferenciado, LiDAR, terreno o relación con cartografía, es de AeroConvert. Si no necesita lógica espacial
(PDF, Office, EPUB, OCR, video, imágenes comunes), es de otra aplicación de la suite. Hoy son 42 herramientas de
documentos que viven aquí: salen **por etapas** (F21.2 y F21.11).

## Qué se adopta y qué se ajusta

| La guía dice | Decisión |
| --- | --- |
| Posicionamiento, módulos Transformar · Procesar · Ver · Mapa · Lámina · Automatizar | **Se adopta** (F21.1) |
| Mapas y láminas automáticos como diferenciador | **Se adopta**, es la prioridad (F21.5) |
| Plantilla = reglas técnicas, prompt = variables; IA como asistente | **Se adopta** (F21.8) |
| Proveedor de IA intercambiable; Ollama local para privacidad | **Ya es así**: el cliente de Tino usa formato OpenAI y `AEROCONVERT_TINO_URL`; la clave la pone la persona en el `.env` |
| React, TypeScript, FastAPI | **No.** Django + 69 plantillas + htmx + JS propio funcionan, con CSP `'self'` y sin empaquetador. La propia guía pide cambios incrementales |
| **RustGIS** como motor de mapas, con `.rgislayout` y MCP | **No ahora.** Tiene dos días de vida (v0.1.0 el 2026-10-12), su CLI no se publica para Linux, el PDF no está probado y `.rgislayout` no existe. Se vigila y se reevalúa en uno o dos trimestres |
| Mapas y láminas | **Generador propio** (GDAL corta la vista, reportlab compone el PDF vectorial). QGIS sin pantalla solo si hace falta (F21.10): es GPL, solo como programa externo, y su paquete para Ubuntu 26.04 no está confirmado |
| Cesium como visor 3D | **Piloto en F20.9** (PR 119): funciona bajo la CSP sin tocarla |
| Konva para el editor de láminas | **Después del MVP** (F21.9): MIT, 196 kB, sin empaquetador; el PDF sigue saliendo del servidor |
| Identidad visual de AeroAcademy (cian y violeta) | **Magenta se queda** (D8, D9), con estructura más moderna e ilustraciones (F21.7) |
| Rust para procesar | Según D10: solo para un paso medido como lento |

## Estado real (2026-10-13)

| Módulo | Estado | Dónde |
| --- | --- | --- |
| **Transformar: ráster** (GeoTIFF, BigTIFF, COG, JP2, ECW y MrSID de lectura, IMG, PNG, JPG, WebP, GPKG, MBTiles, VRT) | Implementado | `apps/raster/motores.py`, `apps/formats/catalogo.py` |
| **Transformar: nubes** (LAS, LAZ, COPC, PLY, XYZ) | Implementado con PDAL | `apps/pointcloud/motores.py` |
| Nubes E57 y ReCap | E57 parcial (el PDAL local no lo trae); ReCap no se lee a propósito | `apps/pointcloud/motores.py` |
| **Transformar: vector** (SHP, GPKG, GeoJSON, KML, KMZ, GML, GPX, DXF, DWG y DGN por ODA, CSV de puntos, LandXML) | Implementado | `apps/vector/motores.py` |
| **GeoParquet, FlatGeobuf, PMTiles** | **Ausente** (solo en `docs/FORMATOS.md`) | F21.4 |
| IFC, OBJ, glTF | Planeado | `apps/mesh/` vacío, F4.1 |
| **GNSS** (RINEX, crudos Trimble, RTCM, UBX) y vuelos | Implementado | `apps/gnss/`, `apps/vuelos/` |
| **Procesar: reproyección, overviews, curvas de nivel** | Implementado | `apps/raster/motores.py` |
| Procesar: DEM, sombreado, color por cota | Implementado **solo dentro del visor** | `apps/visor/terreno.py` |
| **Procesar: recorte por polígono y mosaico** | **Ausente** | F21.3 |
| Procesar: filtros de nube | Parcial (reproyección y diezmado) | `apps/pointcloud/motores.py` |
| **Ver: visor 2D** (teselas, capas, vuelos, terreno, perfil) | Implementado | `apps/visor/` |
| Ver: Cesium 3D | Piloto (PR 119) | `/mapa/3d/` |
| **Lámina: DXF a PDF/SVG, portada** | Implementado | `apps/documents/dxf_lamina.py` |
| Lámina: cajetín y logos | Parcial | F21.5 |
| **Mapa automático** | **Ausente** | F21.5 |
| **Automatizar: lotes, paquetes, preajustes, API** | Implementado | `apps/jobs/`, `apps/presets/` |
| Automatizar: Tino con IA | Parcial (cliente de NVIDIA hecho, falta la clave real) | `apps/tino/` |
| **Proyecto/obra** | **Ausente** como modelo (hoy es una carpeta) | F21.6 |

## Cuello de botella funcional

Lo que más separa la guía del código es **recorte y mosaico, el generador de mapas y el modelo de proyecto**.
Por eso el orden es: frontera de documentos y navegación (F21.1, F21.2), el Process que falta (F21.3) y los
formatos (F21.4) en paralelo con el **mapa automático MVP** (F21.5), y después proyecto, visual, IA y editor.

## Criterios y métricas

Los de la guía se mantienen. Se miden con lo que ya existe: el recibo de cada trabajo (tiempo, tamaño antes y
después), `resumen_de_uso` y la bitácora. Lo nuevo (mapas generados, tiempo de un plano) se suma en F21.5.
