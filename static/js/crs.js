// Elegir un sistema de referencia de la lista de resultados, en vez de teclear su EPSG.
//
// El buscador (`dashboard:buscar_crs`) llega por htmx y pinta botones con `data-crs-codigo`.
// Pulsar uno **declara** ese sistema: pone el número en el campo `#id_crs_declarado`, que es el
// que el servidor valida igual que si se hubiera tecleado, y dice cuál se eligió. No hay
// ninguno elegido de antemano.
//
// Delegado en `document` porque la ficha entera llega y se reemplaza por htmx.
(function () {
  "use strict";

  document.addEventListener("click", function (evento) {
    var boton = evento.target.closest && evento.target.closest("[data-crs-codigo]");
    if (!boton) return;

    var campo = document.getElementById("id_crs_declarado");
    if (!campo) return;

    campo.value = boton.getAttribute("data-crs-codigo");
    campo.dispatchEvent(new Event("input", { bubbles: true }));

    var dicho = document.getElementById("crs-elegido");
    if (dicho) {
      dicho.textContent =
        "Elegido: " + boton.getAttribute("data-crs-nombre") + " (EPSG:" + campo.value + ")";
    }
    var lista = document.getElementById("crs-resultados");
    if (lista) lista.innerHTML = "";
    campo.focus();
  });

  // Teclear el número a mano deja sin efecto el «Elegido»: ya no es lo que se pulsó.
  document.addEventListener("input", function (evento) {
    if (!evento.isTrusted || evento.target.id !== "id_crs_declarado") return;
    var dicho = document.getElementById("crs-elegido");
    if (dicho) dicho.textContent = "";
  });
})();
