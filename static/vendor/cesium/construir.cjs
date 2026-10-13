// Construye `Cesium.js` (IIFE, minificado) para AeroConvert. `meshoptimizer` se sustituye por un
// vacío: compila WebAssembly al cargar el módulo, la CSP no lo admite, y el globo no usa glTF
// comprimido con meshopt.
const esbuild = require("esbuild");
const sinMeshopt = {
  name: "sin-meshopt",
  setup(b) {
    b.onResolve({ filter: /^meshoptimizer$/ }, () => ({ path: "meshopt-vacio", namespace: "vacio" }));
    b.onLoad({ filter: /.*/, namespace: "vacio" }, () => ({
      contents:
        "export const MeshoptDecoder = { supported: false, ready: Promise.resolve()," +
        " decodeGltfBuffer() { throw new Error('meshoptimizer no esta en este paquete'); }," +
        " decodeGltfBufferAsync() { return Promise.reject(new Error('meshoptimizer no esta en este paquete')); } };",
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
    legalComments: "none",
    plugins: [sinMeshopt],
    logLevel: "info",
  })
  .catch(() => process.exit(1));
