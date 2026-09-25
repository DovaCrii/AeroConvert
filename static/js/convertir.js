// Soltar un archivo en la pantalla de convertir, y que se suba.
//
// ## Lo que había antes, y por qué no hacía nada
//
// Este fichero es de cuando la pantalla tenía una caja para pegar la ruta. Al soltar un
// archivo tomaba su **nombre** —el navegador no da la ruta completa, por seguridad— lo
// escribía en esa caja y enviaba solo si el texto llevaba una barra. La caja desapareció, el
// campo quedó oculto, y un nombre soltado **nunca lleva barra**: soltar un archivo no hacía
// absolutamente nada, debajo de un rótulo que decía «Arrastra el archivo aquí».
//
// ## Lo que hace ahora
//
// Pone los bytes soltados en el campo de archivo de «Desde tu equipo» y dispara `change`.
// A partir de ahí es exactamente el mismo camino que elegir con el botón: `subida.js` mira el
// tope antes de mandar nada, sube con su barra de avance, y la ficha llega por htmx.
//
// **Se puede soltar en cualquier sitio de la pantalla**, no solo sobre la tarjeta. Es lo que
// promete el paso 1 —«suelta cualquier archivo»— y además evita lo que pasaba al fallar la
// puntería: el navegador abría el archivo soltado en la pestaña y la pantalla se perdía.
//
// El botón de elegir sigue ahí, y tiene que seguir: arrastrar no puede ser la única forma
// (WCAG 2.5.7), ni para quien usa teclado ni para quien no puede arrastrar.
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var zona = document.querySelector("[data-zona-soltar]");
    var campo = zona && zona.querySelector("input[type=file]");
    if (!zona || !campo) {
      return;
    }

    // Cuántas veces se ha entrado sin salir. `dragenter` y `dragleave` saltan también al
    // pasar sobre cada hijo, así que sin contarlos la marca parpadea al mover el ratón por
    // encima del texto de la tarjeta.
    var dentro = 0;

    function llevaArchivos(evento) {
      var tipos = evento.dataTransfer && evento.dataTransfer.types;
      return !!tipos && Array.prototype.indexOf.call(tipos, "Files") !== -1;
    }

    document.addEventListener("dragenter", function (evento) {
      if (!llevaArchivos(evento)) return;
      evento.preventDefault();
      dentro += 1;
      zona.classList.add("encima");
    });

    document.addEventListener("dragover", function (evento) {
      if (!llevaArchivos(evento)) return;
      // Sin esto el navegador no considera la página un destino válido y, al soltar, abre el
      // archivo en la pestaña.
      evento.preventDefault();
      evento.dataTransfer.dropEffect = "copy";
    });

    document.addEventListener("dragleave", function (evento) {
      if (!llevaArchivos(evento)) return;
      dentro = Math.max(0, dentro - 1);
      if (dentro === 0) zona.classList.remove("encima");
    });

    document.addEventListener("drop", function (evento) {
      if (!llevaArchivos(evento)) return;
      evento.preventDefault();
      dentro = 0;
      zona.classList.remove("encima");

      var archivos = evento.dataTransfer.files;
      if (!archivos || !archivos.length) return;

      // **Uno solo**: el campo no es múltiple, y esta pantalla mira un archivo cada vez. Se
      // copia a una lista nueva porque asignar varios a un campo que no es `multiple` se
      // comporta distinto en cada navegador.
      var uno = new DataTransfer();
      uno.items.add(archivos[0]);
      campo.files = uno.files;

      // El mismo evento que al elegir con el botón: `subida.js` lo recoge, mira el tope y
      // sube con la barra. Una sola vía para las dos cosas, así que no pueden portarse
      // distinto.
      campo.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
})();
