/* Atajos de teclado, y son dos.
 *
 * ## La regla que evita el desastre
 *
 * **Descubrir un atajo no puede ser necesario.** Todo lo que hay aquí se puede hacer con el
 * ratón exactamente igual, y el atajo solo ahorra el viaje. Por eso no hay ninguna hoja de
 * trucos escondida: la barra «/» se enseña dentro del propio campo de búsqueda, que es donde
 * hace falta saberla, y quien no la vea nunca no pierde nada.
 *
 * ## Por qué solo dos
 *
 * Porque solo hay dos cosas que se repitan de verdad con cinco personas de uso diario:
 * buscar, y volver del resultado de una búsqueda. Un juego de quince atajos para una
 * aplicación que se abre tres veces al día es un juego que nadie memoriza.
 *
 * ## Y por qué no pisan nada
 *
 * Con cualquier modificador —Ctrl, Alt, Cmd, Shift— esto no hace nada: `Ctrl+/`, `Cmd+F` y
 * compañía siguen siendo del navegador. Y escribiendo en un campo tampoco: la barra tiene
 * que poder teclearse en una ruta o en una contraseña sin que la pantalla salte a otro sitio.
 *
 * Fichero aparte y no `onkeydown=` porque la política de contenido de esta aplicación es
 * `script-src 'self'` sin `unsafe-inline`: un manejador en el atributo no se ejecutaría, y
 * **no avisaría de nada** — simplemente no pasaría nada al pulsar.
 */
(function () {
  "use strict";

  function escribiendo(elemento) {
    if (!elemento) return false;
    if (elemento.isContentEditable) return true;
    var etiqueta = (elemento.tagName || "").toLowerCase();
    return etiqueta === "input" || etiqueta === "textarea" || etiqueta === "select";
  }

  document.addEventListener("keydown", function (evento) {
    // Cualquier modificador y esto no existe: los atajos del navegador son suyos.
    if (evento.ctrlKey || evento.metaKey || evento.altKey || evento.shiftKey) return;

    var caja = document.getElementById("q");

    if (evento.key === "/" && !escribiendo(document.activeElement) && caja) {
      // `preventDefault` porque si no la barra se escribe dentro del campo que acabamos de
      // enfocar, y lo primero que ve quien lo usa es que el atajo ensucia su búsqueda.
      evento.preventDefault();
      caja.focus();
      caja.select();
      return;
    }

    // Escape dentro de la búsqueda: vaciar y volver al catálogo entero. Es el camino de
    // vuelta, que sin esto es seleccionar el texto y borrarlo a mano.
    if (evento.key === "Escape" && caja && document.activeElement === caja && caja.value) {
      caja.value = "";
      // Lo mismo que dispara htmx al teclear, para que el catálogo vuelva solo. Si htmx no
      // está —o falló al cargar— el campo queda vacío igual y el formulario sigue enviándose
      // con Intro, que es lo que pasaba antes de que existiera este fichero.
      caja.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
})();
