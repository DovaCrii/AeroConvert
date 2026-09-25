/* Subir un archivo del propio equipo: el tope, el aviso y la barra de avance.
 *
 * ## Los dos fallos que esto arregla
 *
 * **Uno: subir 600 MB con el tope en 200 decía «No llegó ningún archivo».** El manejador del
 * servidor corta con `StopUpload`, que descarta el cuerpo entero, así que la vista recibía lo
 * mismo que si nadie hubiera elegido nada. Ahora el servidor lo distingue y lo dice — pero
 * decirlo al final, después de que alguien haya esperado a que suban 200 MB para que le
 * digan que no, sigue siendo malo. **El tamaño se mira aquí, antes de mandar un solo byte.**
 *
 * **Dos: no había ninguna señal de avance.** Un archivo grande dejaba «Mirando el archivo…»
 * en pantalla durante minutos, sin porcentaje, sin tiempo y sin forma de saber si seguía vivo.
 *
 * ## Por qué el porcentaje es de verdad
 *
 * `htmx:xhr:progress` trae `loaded` y `total` del propio `XMLHttpRequest`: son los bytes que
 * el navegador ya entregó, no una animación. Y el tiempo que falta **se mide**, no se estima:
 * se divide lo que queda entre la velocidad observada en esta misma subida. Los primeros
 * instantes esa velocidad es basura, así que no se enseña tiempo hasta pasados dos segundos.
 *
 * ## Las dos fases, que no son la misma espera
 *
 * Subir y mirar son cosas distintas y se nota: al llegar al 100 % la barra no desaparece,
 * cambia de texto. Mirar un GeoTIFF grande tarda, y una barra llena y quieta parece colgada
 * si no dice que ahora está pasando otra cosa.
 *
 * CSP: `script-src 'self'`. Delegación en `document`, contrato por `data-*`, como el resto.
 */
(function () {
  "use strict";

  var MB = 1048576;
  /** Antes de esto la velocidad medida no vale para nada: son dos o tres paquetes. */
  var MINIMO_PARA_ESTIMAR_MS = 2000;

  function panelDe(forma) {
    return forma.querySelector("[data-avance-subida]");
  }

  function mostrar(panel, html) {
    if (!panel) return;
    panel.innerHTML = html;
    panel.hidden = false;
  }

  function esconder(panel) {
    if (!panel) return;
    panel.hidden = true;
    panel.innerHTML = "";
  }

  /** «1,2 GB», «840 MB», «12 KB». */
  function pesar(bytes) {
    if (bytes >= 1024 * MB) return (bytes / (1024 * MB)).toFixed(1).replace(".", ",") + " GB";
    if (bytes >= MB) return Math.round(bytes / MB) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  /** En palabras, no en segundos crudos: «unos 3 min» se lee mejor que «187 s». */
  function faltar(segundos) {
    if (segundos < 10) return "unos segundos";
    if (segundos < 90) return "unos " + Math.round(segundos / 5) * 5 + " s";
    var minutos = Math.round(segundos / 60);
    return "unos " + minutos + (minutos === 1 ? " min" : " min");
  }

  /**
   * El aviso de que no cabe, **antes de mandar nada**.
   *
   * Devuelve `true` si hay que parar. El tope viene del servidor en `data-tope-mb`: escrito
   * aquí a mano se quedaría desfasado el día que alguien cambie `AEROCONVERT_TOPE_MB`.
   */
  function noCabe(campo, archivo) {
    var tope = parseInt(campo.dataset.topeMb || "0", 10);
    if (!tope || archivo.size <= tope * MB) return false;

    var forma = campo.form;
    mostrar(
      forma && panelDe(forma),
      '<p class="error" style="margin:0;"><strong>«' +
        escapar(archivo.name) +
        "» ocupa " +
        pesar(archivo.size) +
        ", y por el navegador caben " +
        tope +
        " MB.</strong><br>Déjalo en la carpeta compartida: por ahí no hay tope, y copiar con " +
        "el Explorador se reanuda si se corta.</p>"
    );
    // Se vacía el campo: dejarlo puesto invita a pulsar otra vez y esperar lo mismo.
    campo.value = "";
    return true;
  }

  function escapar(texto) {
    var caja = document.createElement("span");
    caja.textContent = texto;
    return caja.innerHTML;
  }

  /** Elegir un archivo envía el formulario solo: el clic de «subir» ya se dio al elegirlo. */
  document.addEventListener("change", function (evento) {
    var campo = evento.target;
    if (!campo.matches || !campo.matches("input[type=file][data-envia-solo]")) return;
    if (!campo.files || campo.files.length === 0) return;

    for (var i = 0; i < campo.files.length; i++) {
      if (noCabe(campo, campo.files[i])) return;
    }

    if (campo.form) {
      esconder(panelDe(campo.form));
      campo.form.dataset.arrancada = String(Date.now());
      campo.form.requestSubmit();
    }
  });

  /**
   * Y para las pantallas que **no** se envían solas.
   *
   * Las nueve de PDF llevan un botón explícito, porque allí elegir el documento no es la
   * última decisión: antes hay que decir qué se le va a hacer. Ahí el tope se mira al enviar.
   */
  document.addEventListener("submit", function (evento) {
    var forma = evento.target;
    if (!forma.querySelectorAll) return;

    var campos = forma.querySelectorAll("input[type=file][data-tope-mb]");
    for (var i = 0; i < campos.length; i++) {
      var campo = campos[i];
      for (var j = 0; campo.files && j < campo.files.length; j++) {
        if (noCabe(campo, campo.files[j])) {
          evento.preventDefault();
          return;
        }
      }
    }
    forma.dataset.arrancada = String(Date.now());
  });

  document.addEventListener("htmx:xhr:progress", function (evento) {
    var forma = evento.target.closest ? evento.target.closest("form") : null;
    if (!forma || !panelDe(forma)) return;

    var detalle = evento.detail;
    // Sin `lengthComputable` no hay porcentaje posible: se dice que va, y ya está.
    if (!detalle || !detalle.lengthComputable || !detalle.total) {
      mostrar(panelDe(forma), '<p class="tenue" style="margin:0;">Subiendo…</p>');
      return;
    }

    var porciento = Math.min(100, Math.round((detalle.loaded / detalle.total) * 100));
    var transcurrido = Date.now() - parseInt(forma.dataset.arrancada || "0", 10);

    var cola = "";
    if (porciento >= 100) {
      // **La barra no se va al llegar al final: cambia de frase.** Lo que sigue es leer el
      // archivo en el servidor, que en un GeoTIFF grande tarda, y una barra llena y quieta
      // parece un cuelgue.
      cola = "Subido. Mirando qué es…";
    } else if (transcurrido > MINIMO_PARA_ESTIMAR_MS && detalle.loaded > 0) {
      var porSegundo = detalle.loaded / (transcurrido / 1000);
      cola =
        pesar(detalle.loaded) +
        " de " +
        pesar(detalle.total) +
        " · falta " +
        faltar((detalle.total - detalle.loaded) / porSegundo);
    } else {
      cola = pesar(detalle.loaded) + " de " + pesar(detalle.total);
    }

    mostrar(
      panelDe(forma),
      '<div class="avance" role="progressbar" aria-valuemin="0" aria-valuemax="100" ' +
        'aria-valuenow="' +
        porciento +
        '"><span class="avance-relleno" style="width:' +
        porciento +
        '%"></span></div>' +
        '<p class="avance-texto"><strong>' +
        porciento +
        " %</strong> · " +
        cola +
        "</p>"
    );
  });

  function formaDe(evento) {
    var elt = evento.detail && evento.detail.requestConfig && evento.detail.requestConfig.elt;
    return elt && elt.closest ? elt.closest("form") : null;
  }

  /** Cuando la ficha ya está en pantalla, el panel sobra: lo que hay que mirar es la ficha. */
  document.addEventListener("htmx:afterSwap", function (evento) {
    var contenedor = formaDe(evento);
    if (contenedor) esconder(panelDe(contenedor));
  });

  /**
   * **Y cuando no llega, también sobra.** Esto es lo que faltaba: solo se escondía tras un
   * éxito, así que un 500 o un corte de red dejaban la barra llena y quieta en «Subido.
   * Mirando qué es…» para siempre. El motivo lo pinta `respuestas.js` donde iba la ficha.
   */
  ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(function (nombre) {
    document.addEventListener(nombre, function (evento) {
      var contenedor = formaDe(evento);
      if (contenedor) esconder(panelDe(contenedor));
    });
  });
})();
