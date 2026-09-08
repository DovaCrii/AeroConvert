# Integración con AeroBim

**Por archivo o por API, nunca por base de datos compartida.** Es la regla estructural de la
familia, y aquí se cumple sin excepción.

---

## Qué necesita AeroBim, y qué le da AeroConvert

AeroBim lee tres formatos y nada más — es lo que lo mantiene simple:

| AeroBim lee | AeroConvert entrega desde |
| --- | --- |
| **COPC** (LAZ 1.4 con octree) | LAS, LAZ, E57, PLY — fase F2 |
| **DXF** | DWG y DGN vía ODA, y cualquier vectorial vía OGR — fase F3 |
| **IFC** 2x3 / 4 | Se pasa tal cual; AeroConvert no lo transforma |

Y para la fase 6 de AeroBim —vista geoespacial con ortofoto y terreno propios—:

| AeroBim necesitará | AeroConvert entrega |
| --- | --- |
| Ortofoto en **COG** | Desde GeoTIFF, BigTIFF, JP2, ECW o IMG — ya disponible |
| Terreno DEM/DSM en **COG** | Desde ASC, DEM, HGT, GeoTIFF float32 — ya disponible |
| Nubes en **3D Tiles** | Fase F2, con `py3dtiles` |

## Lo que ya está resuelto en AeroBim y aquí se reutiliza

No se reescribe: se porta con su historia.

- **`apps/web/scripts/a-copc.py`** (371 líneas) — LAS/LAZ → COPC con `laspy[lazrs]`,
  `copclib`, `numpy` y `pyproj`. Construye el octree a mano, lee por
  `chunk_iterator(4_000_000)` porque la nube del proyecto son 3,37 GB, y **verifica después**:
  recuento, extensión, y que cada punto caiga dentro de la caja de su nodo.
- **`packages/bim-core/src/nubes/precision.ts`** — el hallazgo caro: **`float32` pierde
  200 mm en el norte UTM** (Santiago, EPSG:32719). Hay que restar el desplazamiento de
  cabecera antes de llenar el `Float32Array`. Cualquier motor de nubes de AeroConvert que
  toque coordenadas tiene que respetarlo.
- **`docs/NUBES_DE_PUNTOS.md`** — la comparativa medida COPC vs Potree vs 3D Tiles, y la
  regla que aquí es ley: *si el CRS viene vacío, la conversión para y se le pregunta al
  topógrafo*.

## El contrato, cuando llegue

Por ahora **por archivo**: AeroConvert escribe el COG o el COPC donde el expediente de
AeroBim lo espera, y AeroBim lo carga como cualquier otro documento.

Si más adelante hace falta una API, será **de solo lectura y versionada**, igual que la que
AeroControl consume de AeroLink. Ninguna de las dos escribe en el dominio de la otra, y
ninguna toca la base de la otra.

## Un detalle de despliegue que no se puede olvidar

AeroBim tiene dos reglas no negociables que **no aplican a AeroConvert pero conviene no
romper si algún día comparten servidor**: nunca servir `COOP`/`COEP` —activan el WASM
multihilo de `web-ifc` y el visor se cuelga sin error—, y su CSP necesita
`'wasm-unsafe-eval'` y `worker-src 'self' blob:`.

La CSP de AeroConvert es `'self'` a secas. Si se sirven desde el mismo nginx, cada
aplicación mantiene la suya.
