/* Globo 3D (piloto F20.9): CesiumJS sin Ion, sin terreno del mundo y sin mapa de fondo de internet.
 *
 * Cesium (`@cesium/engine`, sin widgets) se sirve de `static/vendor/cesium/` y deja `window.Cesium`.
 * Aquí solo se arma el globo:
 *  - `Ion.defaultAccessToken = ""`: ninguna petición a Ion, ni por descuido;
 *  - `baseLayer: false`: sin el mapa de fondo que Cesium trae por omisión; el fondo es una retícula
 *    de meridianos y paralelos (`GridImageryProvider`) sobre un color liso;
 *  - sin `createWorldTerrain` ni selector de capas ni buscador: el terreno es el elipsoide;
 *  - la imagen elegida entra por `UrlTemplateImageryProvider` contra las **mismas teselas** que
 *    sirve `visor:tesela` (`{z}/{x}/{y}.png?ruta=<ficha>`), con la sesión de quien mira.
 *
 * Todo lo que necesita viaja en `data-*` de la plantilla (la CSP no admite scripts en la página) y
 * no nombra ninguna dirección absoluta: `apps/visor/test_sin_salida.py` lo comprueba.
 */
(function () {
  "use strict";

  const raiz = document.getElementById("globo-visor");
  const contenedor = document.getElementById("globo-3d");
  const estado = document.getElementById("globo-estado");
  if (!raiz || !contenedor || typeof window.Cesium === "undefined") return;

  const C = window.Cesium;

  function decir(texto) {
    if (estado) estado.textContent = texto;
  }

  function leerCapa() {
    try {
      return JSON.parse(raiz.dataset.capa3d || "{}");
    } catch (fallo) {
      return {};
    }
  }

  // Sin Ion: ni token ni servicio. Una petición a `api.cesium.com` aquí sería un fallo.
  C.Ion.defaultAccessToken = "";
  // Workers, ThirdParty y Assets salen del propio servidor.
  C.buildModuleUrl.setBaseUrl(raiz.dataset.baseCesium);

  let globo;
  try {
    globo = new C.CesiumWidget(contenedor, {
      baseLayer: false,
      skyBox: false,
      skyAtmosphere: false,
      orderIndependentTranslucency: false,
      // Solo dibuja cuando algo cambia: un globo parado no gasta la tarjeta gráfica.
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
    });
  } catch (fallo) {
    // Regla 4: apagado con motivo y alternativa, no oculto ni sustituido en silencio.
    decir(
      "Este navegador no puede dibujar el globo (hace falta WebGL). " +
        "Use «Ver en el mapa plano», que no lo necesita."
    );
    return;
  }

  const escena = globo.scene;
  escena.globe.baseColor = C.Color.fromCssColorString("#1d2b3a");
  escena.globe.enableLighting = false;
  escena.backgroundColor = C.Color.fromCssColorString("#0c121a");
  // El elipsoide liso: nada de terreno del mundo.
  escena.globe.depthTestAgainstTerrain = false;

  // La retícula, siempre: es lo que se ve si no hay imagen y lo que da escala si la hay.
  globo.imageryLayers.add(
    new C.ImageryLayer(
      new C.GridImageryProvider({
        cells: 8,
        color: C.Color.fromCssColorString("#6f8aa6"),
        glowColor: C.Color.fromCssColorString("#6f8aa6"),
        glowWidth: 2,
        backgroundColor: C.Color.TRANSPARENT,
        canvasSize: 256,
      })
    )
  );

  const capa = leerCapa();
  const hayImagen = typeof capa.teselas === "string" && capa.token;
  if (hayImagen) {
    const base = capa.teselas.replace(/0\/0\/0\.png$/, "");
    const rectangulo = C.Rectangle.fromDegrees(capa.oeste, capa.sur, capa.este, capa.norte);
    const proveedor = new C.UrlTemplateImageryProvider({
      url: base + "{z}/{x}/{y}.png?ruta=" + encodeURIComponent(capa.token),
      tilingScheme: new C.WebMercatorTilingScheme(),
      rectangle: rectangulo,
      maximumLevel: capa.zoom_maximo,
      tileWidth: 256,
      tileHeight: 256,
      hasAlphaChannel: true,
    });
    let falladas = 0;
    proveedor.errorEvent.addEventListener(function () {
      falladas += 1;
      decir(
        "Hay " + falladas + (falladas === 1 ? " tesela" : " teselas") +
          " que no se pudieron cortar; se reintentará al mover el globo."
      );
    });
    globo.imageryLayers.add(new C.ImageryLayer(proveedor));
    globo.camera.setView({ destination: rectangulo });
    decir("Imagen sobre el globo. Arrastre para girar; rueda o pellizco para acercar.");
  } else {
    globo.camera.setView({
      destination: C.Cartesian3.fromDegrees(-70.0, -20.0, 18000000.0),
    });
    decir("Globo sin imagen. Elija abajo una ortofoto para verla aquí.");
  }

  escena.renderError.addEventListener(function (_escena, error) {
    decir("El globo dejó de dibujar: " + (error && error.message ? error.message : error));
  });

  // Cambió el tamaño de la ventana o del contenedor: el globo se reencuadra solo.
  window.addEventListener("resize", function () {
    globo.resize();
    globo.scene.requestRender();
  });
})();
