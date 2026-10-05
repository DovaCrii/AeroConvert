/* Recuerda, en este navegador, qué bloques plegables se dejaron cerrados.
 *
 * El plegado en sí es un `<details>` nativo y no necesita esto: sin JavaScript funciona igual,
 * solo que cada visita lo vuelve a abrir. Se marca con `data-recuerda="clave"`.
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
      return null; // modo privado o almacenamiento bloqueado: se abre, como siempre
    }
  }

  function guardar(clave, abierto) {
    try {
      if (abierto) {
        window.localStorage.removeItem(PREFIJO + clave);
      } else {
        window.localStorage.setItem(PREFIJO + clave, "cerrado");
      }
    } catch (e) {
      /* sin almacenamiento no se recuerda, y no pasa nada */
    }
  }

  function restaurar(raiz) {
    var bloques = (raiz || document).querySelectorAll("details[data-recuerda]");
    for (var i = 0; i < bloques.length; i++) {
      if (leer(bloques[i].getAttribute("data-recuerda")) === "cerrado") {
        bloques[i].open = false;
      }
    }
  }

  document.addEventListener(
    "toggle",
    function (evento) {
      var bloque = evento.target;
      if (bloque && bloque.matches && bloque.matches("details[data-recuerda]")) {
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
    });
  } else {
    restaurar(document);
  }
})();
