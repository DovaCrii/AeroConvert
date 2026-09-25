/* Lo que pasa cuando una respuesta de htmx llega, o no llega.
 *
 * ## El fallo que esto arregla, y por qué era el peor de la aplicación
 *
 * **htmx no pinta nada cuando el servidor contesta con un error.** Es lo correcto por omisión
 * —no quiere meter una página de error de Django dentro de una tarjeta— pero aquí no había
 * nada más: ningún manejador en ningún fichero. Un 500 al mirar un archivo, un 413 al subirlo,
 * o la red cortada, dejaban la pantalla exactamente como estaba, en silencio. Con la barra de
 * subida quieta en «Subido. Mirando qué es…» para siempre.
 *
 * Es lo que más probablemente vio el equipo el 15 de septiembre y describió como «no
 * funciona». No se puede probar, pero es la clase de fallo que se describe así.
 *
 * ## Las tres cosas que hace
 *
 * 1. **El error, en el sitio donde iba la respuesta**, con `role="alert"` y diciendo qué hacer.
 * 2. **La respuesta, a la vista.** Un destino con `data-enfocar` se desplaza a la pantalla y
 *    enfoca su título al llegar. La ficha aparecía debajo de las tarjetas de origen, fuera de
 *    la vista, y parecía que no había pasado nada.
 * 3. **Una frase para el lector de pantalla** en `#anuncio`: el título de lo que ha llegado, o
 *    el texto de un `[data-anunciar]` que traiga la propia respuesta.
 *
 * Fichero aparte y no manejadores en los atributos porque la CSP es `script-src 'self'` sin
 * `unsafe-inline`: un `hx-on` o un `onclick` no se ejecutarían, y **no avisarían**.
 */
(function () {
  "use strict";

  function anunciar(texto) {
    var region = document.getElementById("anuncio");
    if (!region || !texto) return;
    // Vaciar y volver a escribir en el siguiente ciclo: si el texto es igual al anterior, un
    // lector de pantalla no lo repite a menos que la región cambie de verdad.
    region.textContent = "";
    window.setTimeout(function () {
      region.textContent = texto.replace(/\s+/g, " ").trim();
    }, 50);
  }

  function escapar(texto) {
    var caja = document.createElement("span");
    caja.textContent = texto;
    return caja.innerHTML;
  }

  /** Qué decirle a alguien según lo que haya contestado el servidor. **Sin jerga.** */
  function queDecir(estado) {
    if (estado === 0) {
      return {
        titulo: "No se pudo hablar con el servidor.",
        detalle: "Comprueba la conexión y vuelve a intentarlo.",
      };
    }
    if (estado === 413) {
      return {
        titulo: "El archivo es demasiado grande para subirlo por aquí.",
        detalle: "Déjalo en la carpeta compartida y elígelo desde allí.",
      };
    }
    if (estado === 403) {
      return {
        titulo: "La sesión ya no vale.",
        detalle: "Recarga la página; si te pide entrar, vuelve a entrar.",
      };
    }
    if (estado === 404) {
      return {
        titulo: "Eso ya no está.",
        detalle: "Puede que se haya movido o caducado. Recarga la página.",
      };
    }
    if (estado >= 500) {
      return {
        titulo: "El servidor falló al hacerlo.",
        detalle: "No es por tu archivo. Vuelve a intentarlo; si se repite, avisa y di el código.",
      };
    }
    return {
      titulo: "No salió bien.",
      detalle: "Vuelve a intentarlo.",
    };
  }

  function pintarFallo(destino, estado) {
    var mensaje = queDecir(estado);
    if (destino) {
      destino.innerHTML =
        '<div class="error" role="alert"><strong>' +
        escapar(mensaje.titulo) +
        "</strong> " +
        escapar(mensaje.detalle) +
        (estado
          ? '<details class="detalle-tecnico"><summary>Detalle para soporte</summary>' +
            "<code>HTTP " +
            estado +
            "</code></details>"
          : "") +
        "</div>";
    }
    anunciar(mensaje.titulo);
  }

  function destinoDe(evento) {
    return (evento.detail && evento.detail.target) || evento.target || null;
  }

  document.addEventListener("htmx:responseError", function (evento) {
    var xhr = evento.detail && evento.detail.xhr;
    pintarFallo(destinoDe(evento), xhr ? xhr.status : 0);
  });

  // Sin respuesta ninguna: la red, un proxy que corta, el servidor reiniciándose.
  document.addEventListener("htmx:sendError", function (evento) {
    pintarFallo(destinoDe(evento), 0);
  });

  document.addEventListener("htmx:timeout", function (evento) {
    pintarFallo(destinoDe(evento), 0);
  });

  document.addEventListener("htmx:afterSwap", function (evento) {
    var destino = destinoDe(evento);
    // Con `hx-swap="outerHTML"` —el progreso de un trabajo— el destino del evento es el
    // elemento **viejo**, que ya no está en el documento. El nuevo tiene el mismo `id`.
    if (destino && !destino.isConnected && destino.id) {
      destino = document.getElementById(destino.id);
    }
    if (!destino || !destino.querySelector) return;

    // Lo que la propia respuesta pida anunciar tiene prioridad: sabe mejor que nadie qué
    // es lo importante de lo que trae.
    var marcado = destino.querySelector("[data-anunciar]");
    var titulo = destino.querySelector("h1, h2, h3");

    if (destino.hasAttribute("data-enfocar")) {
      var ancla = destino.querySelector('[role="alert"]') || titulo || destino.firstElementChild;
      if (ancla) {
        // `tabindex=-1` hace enfocable un título sin meterlo en el recorrido del tabulador.
        if (!ancla.hasAttribute("tabindex")) ancla.setAttribute("tabindex", "-1");
        var quieto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        ancla.scrollIntoView({ behavior: quieto ? "auto" : "smooth", block: "start" });
        ancla.focus({ preventScroll: true });
      }
    }

    if (marcado) {
      anunciar(marcado.textContent);
    } else if (destino.hasAttribute("data-enfocar") && titulo) {
      anunciar(titulo.textContent);
    }
  });

  // **Y cuando la respuesta llega con la página**, no por htmx. Es lo que pasa cuando
  // `encolar` no puede encolar: devuelve la pantalla entera con la ficha y el error dentro.
  // No hay ningún swap que enfocar, así que sin esto el error quedaría abajo, fuera de la
  // vista, que es exactamente lo que se estaba arreglando.
  document.addEventListener("DOMContentLoaded", function () {
    var fallos = document.querySelectorAll("[data-enfocar] [role=alert]");
    if (!fallos.length) return;
    var primero = fallos[0];
    if (!primero.hasAttribute("tabindex")) primero.setAttribute("tabindex", "-1");
    primero.scrollIntoView({ block: "center" });
    primero.focus({ preventScroll: true });
  });
})();
