// Construye `Cesium.js` (IIFE, minificado) para AeroConvert.
//
// Dos dependencias del motor se sustituyen por un vacío porque **compilan WebAssembly al cargar el
// módulo** (la CSP no lo admite) y el globo no las alcanza:
//  - `meshoptimizer`: glTF comprimido con meshopt (GltfBufferViewLoader, terreno de 3D Tiles).
//  - `@spz-loader/core`: módulo Emscripten con el wasm embebido, `WebAssembly.instantiate` y el
//    `new Function` de embind; lo usa solo `GltfSpzLoader` (gaussian splats en .spz).
const esbuild = require("esbuild");

const vacios = {
  meshoptimizer:
    "export const MeshoptDecoder = { supported: false, ready: Promise.resolve()," +
    " decodeGltfBuffer() { throw new Error('meshoptimizer no esta en este paquete'); }," +
    " decodeGltfBufferAsync() { return Promise.reject(new Error('meshoptimizer no esta en este paquete')); } };",
  "@spz-loader/core":
    "export async function loadSpz() { throw new Error('@spz-loader/core no esta en este paquete'); }",
};

const sinWasm = {
  name: "sin-wasm",
  setup(b) {
    b.onResolve({ filter: /^(meshoptimizer|@spz-loader\/core)$/ }, (a) => ({
      path: a.path,
      namespace: "vacio",
    }));
    b.onLoad({ filter: /.*/, namespace: "vacio" }, (a) => ({
      contents: vacios[a.path],
      loader: "js",
    }));
  },
};

esbuild
  .build({
    entryPoints: ["entrada.js"],
    bundle: true,
    minify: true,
    format: "iife",
    globalName: "Cesium",
    target: "es2022",
    outfile: "out/Cesium.js",
    legalComments: "external",
    plugins: [sinWasm],
    logLevel: "info",
  })
  .catch(() => process.exit(1));
