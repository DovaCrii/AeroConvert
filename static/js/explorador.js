/* El explorador de la carpeta compartida, y el selector de archivos del equipo.
 *
 * ## Por qué esto es un archivo y no un `onchange=` en la plantilla
 *
 * La CSP de la familia es `script-src 'self'` **sin** `unsafe-inline`. Un manejador escrito
 * en el atributo del elemento no se ejecuta: no da error visible, sencillamente no pasa nada
 * al elegir el archivo. Es el peor fallo posible — el que parece que la aplicación se colgó.
 *
 * ## Qué hace
 *
 * Dos cosas, y las dos son «pegar la ruta por ti»:
 *
 * 1. Elegir un archivo del equipo envía su formulario solo. Un botón «subir» aparte obliga a
 *    dos clics para una decisión que ya se tomó al elegir el archivo.
 * 2. Pinchar un archivo del explorador escribe su ruta en el campo que diga el panel. Cada
 *    pantalla dice cuál es el suyo y si se reemplaza o se añade, porque «unir» acumula y las
 *    demás sustituyen.
 */
(function () {
  "use strict";

  /** Envía el formulario en cuanto se elige un archivo. */
  document.addEventListener("change", function (evento) {
    const campo = evento.target;
    if (!campo.matches || !campo.matches("input[type=file][data-envia-solo]")) return;
    if (!campo.files || campo.files.length === 0) return;
    if (campo.form) campo.form.requestSubmit();
  });

  /**
   * Pincha un archivo del explorador.
   *
   * Se escucha en el documento y no en cada botón **a propósito**: el listado lo reemplaza
   * htmx cada vez que se entra en una carpeta, así que cualquier escucha atada a los botones
   * dejaría de existir al primer clic en una carpeta.
   */
  document.addEventListener("click", function (evento) {
    const boton = evento.target.closest ? evento.target.closest("[data-ruta]") : null;
    if (!boton) return;

    const panel = boton.closest("[data-destino]");
    if (!panel) return;

    const destino = document.querySelector(panel.dataset.destino);
    if (!destino) return;

    const ruta = boton.dataset.ruta;
    if (panel.dataset.modo === "anadir") {
      const actual = destino.value.replace(/\s+$/, "");
      // Sin repetir: pinchar dos veces el mismo archivo es un resbalón, no una intención.
      const lineas = actual ? actual.split("\n") : [];
      if (!lineas.includes(ruta)) lineas.push(ruta);
      destino.value = lineas.join("\n") + "\n";
    } else {
      destino.value = ruta;
    }

    // Que quien escuche el campo se entere: htmx y los formularios reaccionan a `change`,
    // no a que alguien le asigne `.value` por detrás.
    destino.dispatchEvent(new Event("change", { bubbles: true }));
    destino.dispatchEvent(new Event("input", { bubbles: true }));

    if (panel.dataset.enviar) {
      const forma = document.querySelector(panel.dataset.enviar);
      if (forma) forma.requestSubmit();
    }
  });
})();
