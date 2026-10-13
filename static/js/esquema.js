/* Mantiene al día el esquema del flujo de «Procesamiento de trayectoria» (F20.2).
 *
 * El servidor ya pinta marcada la ruta con que se abre la pantalla (`aria-current`), y el CSS
 * (`:has()`) la resalta sin JavaScript. Esto solo mueve el `aria-current` cuando la persona cambia
 * de entrada en el paso 1, para que el lector de pantalla diga lo mismo que se ve.
 *
 * Es un archivo y no un `onchange=` en la plantilla por la CSP: `script-src 'self'`, sin
 * `unsafe-inline`.
 */
(function () {
  "use strict";

  function marcar(valor) {
    const rutas = document.querySelectorAll("[data-esquema] .vuelo-ruta[data-ruta]");
    rutas.forEach(function (ruta) {
      if (ruta.dataset.ruta === valor) {
        ruta.setAttribute("aria-current", "true");
      } else {
        ruta.removeAttribute("aria-current");
      }
    });
  }

  document.addEventListener("change", function (evento) {
    const campo = evento.target;
    if (campo && campo.name === "origen" && campo.type === "radio" && campo.checked) {
      marcar(campo.value);
    }
  });
})();
