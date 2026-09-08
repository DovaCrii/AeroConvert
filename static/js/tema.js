// El interruptor de tema.
//
// Va en un archivo y no en una etiqueta suelta dentro del <head> porque la CSP no admite
// `'unsafe-inline'` en `script-src`. Cuesta una peticion mas y evita abrir esa puerta.
//
// El acceso a localStorage va en try/catch porque **lanza** en una ventana privada de
// algunos navegadores: sin la guarda, la pagina entera se queda sin JavaScript.
(function () {
  "use strict";

  var CLAVE = "aeroconvert:tema";

  function guardado() {
    try {
      return window.localStorage.getItem(CLAVE);
    } catch (e) {
      return null;
    }
  }

  function guardar(valor) {
    try {
      window.localStorage.setItem(CLAVE, valor);
    } catch (e) {
      // Sin memoria persistente el tema dura lo que la pagina. Es aceptable.
    }
  }

  function aplicar(valor) {
    if (valor === "claro" || valor === "oscuro") {
      document.documentElement.setAttribute(
        "data-theme",
        valor === "oscuro" ? "dark" : "light"
      );
    } else {
      // Sin atributo, el CSS sigue a `prefers-color-scheme`. Es el estado por omision.
      document.documentElement.removeAttribute("data-theme");
    }
  }

  aplicar(guardado());

  document.addEventListener("DOMContentLoaded", function () {
    var boton = document.getElementById("cambiar-tema");
    if (!boton) {
      return;
    }
    boton.addEventListener("click", function () {
      var actual = document.documentElement.getAttribute("data-theme");
      var siguiente = actual === "dark" ? "claro" : "oscuro";
      aplicar(siguiente);
      guardar(siguiente);
    });
  });
})();
