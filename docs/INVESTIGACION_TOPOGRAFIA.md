# Investigación para «Topografía» (bloque B15, 2026-10-13)

Lo que se leyó antes de reestructurar la parte geoespacial: cómo trabajan **DJI Terra** y **Emlid
Studio**, si **CesiumJS** sirve sin internet y con nuestra CSP, y qué ofrece la **API de NVIDIA** para
Tino. De Emlid y Terra se toman **conceptos y términos**, nunca código: el motor de Emlid es una
variante cerrada de RTKLIB («no hay códigos fuente que pueda compartir», personal de Emlid en su foro).

Lo marcado «sin verificar» viene de foros, blogs o resúmenes de terceros, no de la fuente oficial.

## 1. Cómo procesan Emlid Studio y DJI Terra

**Emlid Studio** separa el trabajo en flujos que se eligen arriba y se llenan en orden:

| Flujo | Entradas | Sale |
| --- | --- | --- |
| Estático | RINEX de la base local (con su altura de antena), RINEX de una CORS, navegación | `.pos` con un punto; ese punto se arrastra como base de otro flujo |
| Cinemático | RINEX del rover y de la base, coordenada de la base (encabezado, manual o un `.pos` estático), navegación | `.pos` y, si hay marcas, `_events.pos` |
| Datos de dron | Lo anterior + eventos de cámara; o un dron RTK con su `.MRK` | Fotos geoetiquetadas (copia o sobrescritas), con el XMP de DJI actualizado; exige tantas marcas como fotos |
| Stop & Go | `.pos` + el CSV de ocupaciones del colector | Cada punto promediado durante su ocupación |
| Convertir a RINEX | Crudos del receptor | RINEX, con satélites excluidos si se pide |

Además: **evaluación de los datos antes de procesar** (visibilidad de satélites, SNR por colores en
dBHz, saltos de ciclo, *skyplot*), **ajustes** (filtro adelante/atrás/combinado, máscara de elevación
y de SNR, resolución de ambigüedades GLONASS) y **colores de solución** en el mapa (fija, flotante,
autónoma).

**DJI Terra** mete el PPK dentro de la reconstrucción: en «POS Data» se elige «Local PPK», se añade el
archivo de la base (RINEX 2.1/3.0 o RTCM 3.x), se confirma el sistema y el centro de la base y se
calcula. Sin las observaciones y el `.mrk` no hay PPK. DJI insiste en que el sistema de la base y el
del proyecto coincidan o el resultado se desplaza: es la regla 3 de `AGENTS.md`.

**Lectura para AeroConvert:** Terra es una caja negra; Emlid enseña el proceso paso a paso. Nuestra
ventaja es el flujo explícito y verificable: contraste contra Trimble, motivo de cada foto sin
posición y el sistema medido o declarado, nunca supuesto.

## 2. Qué sumar (prioridad)

1. Estático de la base contra una CORS, encadenado como coordenada de la base del PPK.
2. Evaluación previa del RINEX (satélites, SNR, saltos de ciclo, traslape rover/base) con avisos.
3. Informe de calidad con gráficos (Q, satélites y ratio en el tiempo; fija/flotante por foto).
4. Filtro combinado, máscara de SNR, constelaciones y ventana de tiempo (RTKLIB ya los admite: `-c`,
   `-m`, `-sys`, `-ts/-te`).
5. Altura de antena y modelo ANTEX (R12i, NetR9, dron).
6. Stop & Go y promediado de puntos (necesita un CSV real de ocupaciones).

## 3. Términos

Procesamiento de trayectoria; posprocesamiento cinemático (PPK) y estático; estación base y rover;
observaciones RINEX y archivo de navegación (efemérides); solución fija, flotante y autónoma; ratio de
validación de ambigüedades; salto de ciclo; máscara de elevación y de SNR; filtro adelante, atrás y
combinado; altura de antena y centro de fase (ARP/PCO); eventos de cámara (`.MRK`); desfase
antena-cámara; geoetiquetado; punto de control (GCP); estación de referencia de operación continua
(CORS); marco de referencia; altura elipsoidal y ortométrica; informe de calidad.

## 4. CesiumJS

- **Licencia Apache-2.0**; Cesium ion es un servicio aparte y opcional. `@cesium/engine` (sin
  widgets) ronda los 27 MB en npm; lo que se sirve es bastante menos.
- **Sin internet: sí**, si no se usa nada de ion: `baseLayer: false` (o una capa propia),
  `geocoder: false`, sin `createWorldTerrain()`, `Ion.defaultAccessToken` vacío. Imágenes con
  `UrlTemplateImageryProvider` (`{z}/{x}/{y}`), que encaja con las teselas que ya corta `apps/visor`.
  Terreno propio: `CesiumTerrainProvider` con quantized-mesh generado desde el DEM (no hay teselas
  globales gratuitas ya hechas).
- **CSP: riesgo abierto.** El paquete con widgets usa `eval` (Knockout); se recomienda
  `@cesium/engine`. Workers y decodificadores WASM podrían pedir `worker-src blob:` y
  `'wasm-unsafe-eval'` (sin verificar). Por eso **piloto primero** con la CSP real; respaldo:
  MapLibre GL JS (BSD-3) con su worker del mismo origen.
- **Nubes en 3D Tiles**: py3dtiles (Apache-2.0) convierte LAS/LAZ a `tileset.json` + `.pnts`.

## 5. API de NVIDIA (para Tino)

- `POST https://integrate.api.nvidia.com/v1/chat/completions`, **formato OpenAI**; clave `nvapi-…`
  (cabecera `Authorization: Bearer`, sin verificar en la fuente oficial). Modelos: Llama 3.3 70B,
  gpt-oss, Qwen3, Nemotron. Embeddings y rerank multilingües para buscar en documentación propia.
- **Capa gratuita**: unos 40 peticiones por minuto, sin SLA (foros). **Privacidad sin garantía
  escrita** de no retención (resúmenes de terceros): por eso solo sale la pregunta escrita, ya limpia
  de rutas, nombres y coordenadas (`apps/tino/fuera.limpiar`), y nunca un archivo.
- **NIM autoalojado**: funciona sin internet, pero en producción exige NVIDIA AI Enterprise (unos
  4.500 USD por GPU al año, FAQ de NVIDIA).

## 6. Stack

Seguir orquestando herramientas externas desde Python (RTKLIB, GDAL, PDAL; un motor de fotogrametría
externo si llega). El cuello de botella es CPU, GPU y E/S de esas herramientas, no Python. Un lenguaje
nuevo solo para un paso propio que se haya **medido** lento.

## Fuentes

- https://docs.emlid.com/emlid-studio/ · https://emlid.com/es/emlid-studio/
- https://docs.emlid.com/emlid-studio/static-processing-workflow/
- https://docs.emlid.com/emlid-studio/kinematic-processing-workflow/
- https://docs.emlid.com/emlid-studio/drone-data-processing/drone-data-processing-workflow/
- https://docs.emlid.com/emlid-studio/drone-data-processing/rtk-drone-data-processing-workflow/
- https://docs.emlid.com/emlid-studio/stop-n-go-with-ef-workflow/
- https://docs.emlid.com/emlid-studio/analyzing-logs/assessing-raw-data/
- https://community.emlid.com/t/emlid-studio-rtklib-source/42311
- https://enterprise.dji.com/dji-terra · https://enterprise-insights.dji.com/blog/ppk-post-processed-kinematics-workflow
- https://github.com/CesiumGS/cesium · https://cesium.com/learn/cesiumjs/ref-doc/UrlTemplateImageryProvider.html
- https://community.cesium.com/t/using-cesium-with-csp-settings/12663
- https://maplibre.org/maplibre-gl-js/docs/guides/v5-to-v6-migration-guide/
- https://py3dtiles.readthedocs.io/
- https://docs.api.nvidia.com/nim/reference/llm-apis · https://docs.api.nvidia.com/nim/docs/product
