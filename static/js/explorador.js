/* El explorador de la carpeta compartida.
 *
 * ## Por qué esto es un archivo y no un `onclick=` en la plantilla
 *
 * La CSP de la familia es `script-src 'self'` **sin** `unsafe-inline`. Un manejador escrito
 * en el atributo del elemento no se ejecuta: no da error visible, sencillamente no pasa nada
 * al pinchar. Es el peor fallo posible — el que parece que la aplicación se colgó.
 *
 * ## Qué hace
 *
 * Pinchar un archivo del explorador escribe su ruta en el campo que diga el panel. Cada
 * pantalla dice cuál es el suyo y si se reemplaza o se añade, porque «unir» acumula y las
 * demás sustituyen.
 *
 * **Lo de elegir un archivo del propio equipo vive en `subida.js`.** Estaba aquí, y ahí es
 * donde había que enviar el formulario solo; pero al entrar el tope de tamaño y la barra de
 * avance, tener media subida en un fichero llamado «explorador» y la otra media en otro era
 * la forma segura de que las dos dejaran de estar de acuerdo.
 */
(function () {
  "use strict";

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
