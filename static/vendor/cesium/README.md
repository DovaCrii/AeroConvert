# CesiumJS (`@cesium/engine` 26.4.0) vendorizado para el globo 3D

Piloto F20.9 (`/mapa/3d/`). **Apache-2.0** (`LICENSE.md`, copiado del paquete). Se sirve del propio
servidor, sin Ion, sin terreno del mundo y sin mapa de fondo de internet (D5).

## Origen

- Paquete de npm **`@cesium/engine@26.4.0`** (el motor **sin widgets**: el paquete `cesium` trae
  Knockout, que llama a `eval` al cargar y rompería la CSP). `@cesium/core@0.1.0` entra como su
  dependencia. Integridad del tarball de `@cesium/engine` (`npm pack`):
  `sha512-OQkL54hPRBkOto0NmArLkEpbWZzTaWAhsx/mGNw85jXdr/nl/OvTqLC8QZv5wKSv4imuzHq/kT6IIy8/B3QLFQ==`.
- **`@cesium/engine` no trae un build para el navegador**: solo módulos ES en `Source/` y, en
  `Build/`, los `Workers/`, `Assets/`, `ThirdParty/` y la hoja del widget. Por eso `Cesium.js` se
  **construye aquí** con esbuild 0.28.2 a partir de `entrada.js` (solo las clases que usa el
  globo) con `construir.cjs`; `construccion-package-lock.json` fija las versiones exactas de las
  dependencias. El build oficial de `cesium` no sirve: incluye los widgets (Knockout, `eval`).
- Una sola diferencia con el paquete: `meshoptimizer` se sustituye por un vacío en `construir.cjs`
  (compila WebAssembly al cargar el módulo y la CSP no lo admite; el globo no abre glTF comprimido
  con meshopt). Con eso **la CSP del proyecto no cambia en nada** (sin `'unsafe-eval'`, sin
  `'wasm-unsafe-eval'`, sin `worker-src` aparte): medido en el navegador, ver
  `docs/INVESTIGACION_TOPOGRAFIA.md` §4.

## Qué hay (solo lo que se sirve)

| Ruta | Para qué | sha256 |
| --- | --- | --- |
| `Cesium.js` (3 835 937 B) | el motor, IIFE minificado, deja `window.Cesium` | `46f9fb85971b9b28c37697c5e0b49e9b668f538cb7351ea304b6d414ba7117ee` |
| `Widgets/CesiumWidget/CesiumWidget.css` (2 265 B) | estilo del lienzo | `d177d8ab518dda483c404ece734142a51ba2389f2114d259f207b177c0840234` |
| `Assets/approximateTerrainHeights.json` (299 471 B) | alturas aproximadas del elipsoide | `36466e2dc84f6c173b609ffc704bc021cd9fdb33c287570bf57e4f566b58e6a6` |
| `Assets/IAU2006_XYS/` | orientación de la Tierra | |
| `Assets/Images/` | logotipos de crédito (los pide el widget) | |
| `Workers/` (62 archivos) | trabajos en segundo plano, mismo origen | |

**No se vendoriza:** `Source/` (fuentes), `Build/Assets/Textures` (entre otras, `NaturalEarthII`: es
el mapa de fondo por omisión, que aquí no se usa), `ThirdParty/*.wasm` (Draco, Basis, zip),
`Workers/transcodeKTX2.js` (llama a `new Function`), ejemplos y mapas de fuentes.

## SRI

`integrity` en `templates/visor/mapa_3d.html` (una prueba lo compara con el archivo):

- `Cesium.js`: `sha384-3JgbFR6ihjyi/2Q4pP5kWCPq9ImxpfG/OsWneoJ5/R2uFhyxR9Z42FQjsqeKAZsv`
- `CesiumWidget.css`: `sha384-8Ks1t6G4x11950+T9lShhZ+d7qPxFg7sKXBwCy2LkRyHdWx4yD09qB3IiwGexpvZ`

## Cómo se actualiza

1. En una carpeta vacía fuera del repositorio: `npm init -y`, `npm i --save-exact
   @cesium/engine@<versión> esbuild`, y copiar `entrada.js` y `construir.cjs`.
2. `node construir.cjs` deja `out/Cesium.js`. Copiarlo aquí, junto con `Build/Workers`,
   `Build/Assets/IAU2006_XYS`, `Build/Assets/Images`, `Build/Assets/approximateTerrainHeights.json`,
   `Build/Widgets/CesiumWidget` y `LICENSE.md` del paquete (sin `transcodeKTX2.js`).
3. Recalcular sha256 y sha384 (receta de `static/vendor/README.md`), actualizar **esta tabla y la
   plantilla**. `apps/visor/test_3d.py` falla si no cuadran.
4. Repetir la medida en el navegador con la CSP real (consola sin errores, todas las peticiones al
   propio servidor).