/* Recuerda, en este navegador, qué bloques plegables se abrieron o se cerraron.
 *
 * El plegado en sí es un `<details>` nativo y no necesita esto: sin JavaScript funciona igual,
 * solo que cada visita lo deja como lo trae el servidor. Se marca con `data-recuerda="clave"`.
 *
 * Se guardan **los dos estados**: unos bloques nacen abiertos (el recibo, el primer grupo) y
 * otros cerrados (los demás grupos), y recordar solo «cerrado» no dejaría abrir los segundos.
 *
 * Los fragmentos llegan por htmx y reemplazan el bloque, así que se restaura en cada carga y
 * el cambio se escucha en la captura del documento: `toggle` no burbujea. */
(function () {
  "use strict";

  var PREFIJO = "aeroconvert:plegado:";

  function leer(clave) {
    try {
      return window.localStorage.getItem(PREFIJO + clave);
    } catch (e) {
      return null; // modo privado o almacenamiento bloqueado: queda como lo trae el servidor
    }
  }

  function guardar(clave, abierto) {
    try {
      window.localStorage.setItem(PREFIJO + clave, abierto ? "abierto" : "cerrado");
    } catch (e) {
      /* sin almacenamiento no se recuerda, y no pasa nada */
    }
  }

  function restaurar(raiz) {
    var bloques = (raiz || document).querySelectorAll("details[data-recuerda]");
    for (var i = 0; i < bloques.length; i++) {
      var estado = leer(bloques[i].getAttribute("data-recuerda"));
      if (estado === "cerrado") {
        bloques[i].open = false;
      } else if (estado === "abierto") {
        bloques[i].open = true;
      }
    }
  }

  // Un enlace con `#grupo-…` (el lateral reducido lleva así a cada grupo) abre ese grupo aunque
  // la persona lo hubiera dejado cerrado: se llegó pidiéndolo. Va después de restaurar.
  function abrirElDelEnlace() {
    var id = window.location.hash.slice(1);
    if (!id) return;
    var bloque = document.getElementById(id);
    if (bloque && bloque.tagName === "DETAILS") {
      bloque.open = true;
      bloque.scrollIntoView();
    }
  }

  // El grupo del lateral que contiene la pantalla donde se está se abre siempre, y el enlace se
  // trae a la vista: llegar a «Corregir un vuelo» con su grupo cerrado no dice dónde se está.
  // **No se guarda**: es una apertura de paso, no una preferencia de la persona.
  function abrirElDeLaPagina() {
    var actual = document.querySelector(".lateral details [aria-current='page']");
    if (!actual) return;
    var bloque = actual.closest("details");
    if (bloque && !bloque.open) {
      bloque.setAttribute("data-sin-guardar", "");
      bloque.open = true;
    }
    if (actual.scrollIntoView) actual.scrollIntoView({ block: "nearest" });
  }

  window.addEventListener("hashchange", abrirElDelEnlace);

  document.addEventListener(
    "toggle",
    function (evento) {
      var bloque = evento.target;
      if (bloque && bloque.matches && bloque.matches("details[data-recuerda]")) {
        if (bloque.hasAttribute("data-sin-guardar")) {
          bloque.removeAttribute("data-sin-guardar");
          return;
        }
        guardar(bloque.getAttribute("data-recuerda"), bloque.open);
      }
    },
    true
  );

  document.addEventListener("htmx:load", function (evento) {
    restaurar(evento.target);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      restaurar(document);
      abrirElDelEnlace();
      abrirElDeLaPagina();
    });
  } else {
    restaurar(document);
    abrirElDelEnlace();
    abrirElDeLaPagina();
  }
})();
