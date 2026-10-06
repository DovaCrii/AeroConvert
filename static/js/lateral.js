/*
 * El lateral: reducirlo a iconos y ampliarlo.
 *
 * **La navegación no depende de esto.** Sin este fichero el lateral está siempre a la vista
 * (en pantallas estrechas, apilado encima del contenido) y los grupos abren y cierran porque son
 * `details`. La CSP es `script-src 'self'` sin `unsafe-inline`, y una navegación que dependiera
 * de JavaScript sería una navegación que puede desaparecer en silencio.
 *
 * Lo que añade esto es lo que un `details` no trae:
 *
 *   1. El botón de la barra reduce el lateral a una columna de iconos y lo vuelve a ampliar. En
 *      pantallas anchas se acuerda de lo que se dejó, en este navegador; en las estrechas el
 *      lateral nace plegado cada vez y el botón lo saca, porque ahí tapa el contenido.
 *   2. Escape lo cierra en pantallas estrechas y devuelve el foco al botón.
 *   3. Seguir un enlace del lateral lo cierra en pantallas estrechas: la página va a cambiar, y
 *      al volver atrás el navegador la restaura como estaba.
 *
 * Todo cuelga de clases en `<html>` (`js-lateral`, `lateral-compacto`, `lateral-abierto`) y no de
 * estilos en línea, por la misma CSP.
 */
(function () {
  "use strict";

  var CLAVE = "aeroconvert:lateral";
  var ANCHO_MINIMO = "(min-width: 56rem)";
  var raiz = document.documentElement;
  var boton = document.getElementById("lateral-alternar");
  var lateral = document.getElementById("lateral");

  if (!boton || !lateral) {
    return; // la pantalla de entrada no tiene lateral
  }

  function ancho() {
    return window.matchMedia(ANCHO_MINIMO).matches;
  }

  function leer() {
    try {
      return window.localStorage.getItem(CLAVE);
    } catch (e) {
      return null; // modo privado o almacenamiento bloqueado: queda a la vista
    }
  }

  function guardar(compacto) {
    try {
      window.localStorage.setItem(CLAVE, compacto ? "compacto" : "ancho");
    } catch (e) {
      /* sin almacenamiento no se recuerda, y no pasa nada */
    }
  }

  function visible() {
    return ancho() ? !raiz.classList.contains("lateral-compacto") : raiz.classList.contains("lateral-abierto");
  }

  function pintar() {
    boton.setAttribute("aria-expanded", visible() ? "true" : "false");
  }

  function poner(mostrar) {
    if (ancho()) {
      raiz.classList.toggle("lateral-compacto", !mostrar);
      guardar(!mostrar);
    } else {
      raiz.classList.toggle("lateral-abierto", mostrar);
    }
    pintar();
  }

  raiz.classList.add("js-lateral");
  // «oculto» es el valor de la versión anterior, que ocultaba el lateral entero.
  if (leer() === "compacto" || leer() === "oculto") {
    raiz.classList.add("lateral-compacto");
  }
  pintar();

  boton.addEventListener("click", function () {
    poner(!visible());
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && !ancho() && raiz.classList.contains("lateral-abierto")) {
      poner(false);
      boton.focus();
    }
  });

  lateral.addEventListener("click", function (evento) {
    if (!ancho() && evento.target.closest && evento.target.closest("a")) {
      poner(false);
    }
  });

  window.matchMedia(ANCHO_MINIMO).addEventListener("change", pintar);
})();
