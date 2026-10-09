/* Ver una página en grande, para leerla antes de decidir (organizar, unir, dividir).
 *
 * **Sin JavaScript ya funciona**: cada miniatura es un enlace a la misma página dibujada a lo
 * ancho, que se abre en otra pestaña. Esto solo añade la versión cómoda: un `<dialog>` nativo
 * sobre la lista, con «anterior» y «siguiente» y Escape para cerrar, sin perder el sitio en la
 * lista ni lo que se llevaba ordenado. El foco vuelve a la miniatura al cerrar. */
(function () {
  "use strict";

  var dialogo = null;
  var imagen = null;
  var rotulo = null;
  var enlaces = [];
  var actual = -1;
  var origen = null;

  function crear() {
    dialogo = document.createElement("dialog");
    dialogo.className = "ampliada";
    dialogo.setAttribute("aria-label", "Página en grande");
    dialogo.innerHTML =
      '<div class="ampliada-barra">' +
      '<span class="ampliada-rotulo" aria-live="polite"></span>' +
      '<button type="button" class="boton-icono" data-ir="-1"><span aria-hidden="true">←</span><span class="visually-hidden">Página anterior</span></button>' +
      '<button type="button" class="boton-icono" data-ir="1"><span aria-hidden="true">→</span><span class="visually-hidden">Página siguiente</span></button>' +
      '<button type="button" class="boton-icono" data-cerrar><span aria-hidden="true">×</span><span class="visually-hidden">Cerrar</span></button>' +
      "</div>" +
      '<div class="ampliada-lienzo"><img alt=""></div>';
    document.body.appendChild(dialogo);
    imagen = dialogo.querySelector("img");
    rotulo = dialogo.querySelector(".ampliada-rotulo");

    dialogo.addEventListener("click", function (evento) {
      var boton = evento.target.closest("button");
      if (evento.target === dialogo) {
        dialogo.close(); // un clic fuera de la página cierra, como en cualquier visor
      } else if (boton && boton.hasAttribute("data-cerrar")) {
        dialogo.close();
      } else if (boton && boton.hasAttribute("data-ir")) {
        mostrar(actual + parseInt(boton.getAttribute("data-ir"), 10));
      }
    });
    dialogo.addEventListener("keydown", function (evento) {
      if (evento.key === "ArrowRight") mostrar(actual + 1);
      if (evento.key === "ArrowLeft") mostrar(actual - 1);
    });
    dialogo.addEventListener("close", function () {
      if (origen) origen.focus();
    });
  }

  function mostrar(indice) {
    if (indice < 0 || indice >= enlaces.length) return;
    actual = indice;
    var enlace = enlaces[indice];
    imagen.src = enlace.href;
    imagen.alt = enlace.getAttribute("data-ampliar") || "";
    rotulo.textContent = (enlace.getAttribute("data-ampliar") || "") + " (" + (indice + 1) + " de " + enlaces.length + ")";
    dialogo.querySelector('[data-ir="-1"]').disabled = indice === 0;
    dialogo.querySelector('[data-ir="1"]').disabled = indice === enlaces.length - 1;
  }

  document.addEventListener("click", function (evento) {
    var enlace = evento.target.closest && evento.target.closest("a[data-ampliar]");
    if (!enlace || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.button !== 0) return;
    if (typeof HTMLDialogElement === "undefined") return; // se abre en otra pestaña
    evento.preventDefault();
    if (!dialogo) crear();
    enlaces = Array.prototype.slice.call(document.querySelectorAll("a[data-ampliar]"));
    origen = enlace;
    mostrar(enlaces.indexOf(enlace));
    dialogo.showModal();
  });
})();
