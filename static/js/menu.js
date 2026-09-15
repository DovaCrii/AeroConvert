/*
 * El desplegable de la barra: cerrarlo cuando toca.
 *
 * **Lo que abre y cierra el menú es `details`/`summary`, no esto.** Sin este fichero el menú
 * funciona: se abre con clic, se recorre con el tabulador y se cierra volviendo a pulsar. Eso
 * es deliberado — la CSP es `script-src 'self'` sin `unsafe-inline`, y una navegación que
 * dependiera de JavaScript sería una navegación que puede desaparecer en silencio.
 *
 * Lo que añade esto es lo que `details` no trae y se espera de un menú:
 *
 *   1. Cerrarlo al pulsar fuera. Sin esto se queda abierto tapando media pantalla.
 *   2. Cerrarlo con Escape, y **devolver el foco al botón**: quien navega con teclado se
 *      quedaría con el foco dentro de un panel que ya no se ve.
 *   3. Cerrarlo al seguir un enlace de dentro. htmx no interviene aquí —son navegaciones de
 *      verdad— pero el navegador conserva el estado de `details` al volver atrás, y el menú
 *      reaparecía abierto.
 *
 * Delegación en `document` y no un `addEventListener` por elemento, como en `explorador.js`:
 * la barra es estática, pero la regla de la casa es esa y una excepción sin motivo se copia.
 */
(function () {
  "use strict";

  function abiertos() {
    return Array.prototype.slice.call(document.querySelectorAll("details.menu[open]"));
  }

  function cerrar(menu) {
    menu.removeAttribute("open");
  }

  document.addEventListener("click", function (evento) {
    var dentro = evento.target.closest ? evento.target.closest("details.menu") : null;

    abiertos().forEach(function (menu) {
      // El que contiene el clic se deja en paz: pulsar su propio `summary` ya lo alterna, y
      // cerrarlo aquí lo volvería a cerrar justo después de abrirse.
      if (menu !== dentro) {
        cerrar(menu);
      }
    });

    // Un enlace de dentro sí lo cierra: la página va a cambiar, y al volver atrás el
    // navegador restaura el `open` y el menú aparecía desplegado sin que nadie lo pidiera.
    if (dentro && evento.target.closest("a")) {
      cerrar(dentro);
    }
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "Escape") {
      return;
    }
    abiertos().forEach(function (menu) {
      cerrar(menu);
      // **El foco vuelve al botón.** Es la mitad que se olvida: sin esto el foco se queda en
      // un panel que ya no está en pantalla, y el siguiente tabulador salta a cualquier sitio.
      var boton = menu.querySelector("summary");
      if (boton) {
        boton.focus();
      }
    });
  });
})();
