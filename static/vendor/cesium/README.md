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
- Dos diferencias con el paquete, en `construir.cjs`: `meshoptimizer` y `@spz-loader/core` se
  sustituyen por un vacío. Los dos **compilan WebAssembly al cargar el módulo** y la CSP no lo
  admite. `@spz-loader/core` es un módulo Emscripten con el wasm embebido, `WebAssembly.instantiate`
  y el `new Function` de embind; solo lo alcanza `GltfSpzLoader` (gaussian splats `.spz`), y
  `meshoptimizer` solo glTF comprimido con meshopt: el globo (imágenes por teselas sobre el
  elipsoide) no pasa por ninguno. **El bundle resultante no trae `new Function`, `eval(` ni
  `WebAssembly.`** (`apps/visor/test_3d.py` lo cuenta). Con eso **la CSP del proyecto no cambia en nada** (sin `'unsafe-eval'`, sin
  `'wasm-unsafe-eval'`, sin `worker-src` aparte): medido en el navegador, ver
  `docs/INVESTIGACION_TOPOGRAFIA.md` §4.

## Qué hay (solo lo que se sirve)

| Ruta | Para qué | sha256 |
| --- | --- | --- |
| `Cesium.js` (3 559 640 B) | el motor, IIFE minificado, deja `window.Cesium` | `9e8db246f456f428a3e46ba3af11663fc35a32dffe8d4fb1fa98d3e6e7f9eff5` |
| `Widgets/CesiumWidget/CesiumWidget.css` (2 265 B) | estilo del lienzo | `d177d8ab518dda483c404ece734142a51ba2389f2114d259f207b177c0840234` |
| `Assets/approximateTerrainHeights.json` (299 471 B) | alturas aproximadas del elipsoide | `36466e2dc84f6c173b609ffc704bc021cd9fdb33c287570bf57e4f566b58e6a6` |
| `Assets/IAU2006_XYS/` | orientación de la Tierra | |
| `Assets/Images/ion-credit.png` | el logotipo de crédito que `CreditDisplay` pide en cada carga (sin él, un 404); es un archivo local, no una petición a Ion | |
| `Cesium.js.LEGAL.txt`, `ThirdParty.json` | avisos de licencia de lo que el bundle trae de terceros (el segundo es el del paquete `cesium` 1.146.0, de las mismas dependencias) | |
| `Workers/` (62 archivos) | trabajos en segundo plano, mismo origen | |

**No se vendoriza:** `Source/` (fuentes), `Build/Assets/Textures` (entre otras, `NaturalEarthII`: es
el mapa de fondo por omisión, que aquí no se usa), `ThirdParty/*.wasm` (Draco, Basis, zip),
`Workers/transcodeKTX2.js` (llama a `new Function`), `lighter.css`, los logotipos de
Bing, Google Earth y `cesium_credit.png` (nadie los pide), ejemplos y mapas de fuentes. El Sol y la Luna no se piden (`skyBox: false`).

## Límites y navegadores medidos

- **`createImageBitmap` es obligatorio en la práctica.** Cesium decodifica las imágenes con él; sin
  él cae a `blob:` + `<img>` y la CSP (`img-src 'self' data:`) lo bloquea: en un navegador muy
  antiguo el globo se vería sin imagen. Sin WebGL, el JavaScript propio lo dice y ofrece el mapa
  plano (`/mapa/`).
- **Los workers** salen del mismo origen (`Workers/`); `worker-src` cae en `script-src 'self'` y
  no hace falta `blob:`.
- **Medido** (2026-10-13, Windows 11): solo **Chromium 152** (el navegador del panel de Claude,
  WebGL por software o GPU de la máquina). **Sin medir:** Firefox, Safari, móviles y una GPU
  dedicada con una ortofoto real; las teselas de la prueba eran sintéticas.
- `ThirdParty.json` es el del paquete `cesium` (el de `@cesium/engine` no lo trae).

## SRI

`integrity` en `templates/visor/mapa_3d.html` (una prueba lo compara con el archivo):

- `Cesium.js`: `sha384-1xRKomp12eDsdVMqCHjuWgwKFLZ7NZYICtXzlTU1CHma+dL/dtIQ36FFlhX4x8Wu`
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