// La pista de un archivo soltado, antes de que termine de subir (F13.8, «archivo primero»).
//
// Al elegir o soltar un archivo manda **solo los primeros megas** (`File.slice()`) a la
// dirección de `data-reconoce`, y pone la respuesta en `#reconocido`. Así quien suelta una
// ortofoto de 20 GB lee «Parece un BigTIFF» y lo que puede hacer con ella sin esperar a que
// suba entera.
//
// **Es una pista, no la inspección.** La ficha de verdad llega por el camino de siempre
// (`subida.js` sube el archivo entero y htmx pone la ficha). Esta petición va aparte y, si
// falla —red, permiso, un navegador sin `slice`—, no pasa nada: se queda la vía de respaldo,
// que es esperar a la ficha. Por eso nunca muestra un error.
//
// El mismo evento `change` lo recoge `subida.js`; ni este fichero ni aquel dependen del otro.
(function () {
  "use strict";

  // Los primeros 4 MiB, igual que `CABECERA_MAX_BYTES` en el servidor.
  var CABECERA_BYTES = 4 * 1024 * 1024;

  document.addEventListener("change", function (evento) {
    var campo = evento.target;
    if (!campo || !campo.matches || !campo.matches("input[type=file][data-reconoce]")) return;

    var destino = document.getElementById("reconocido");
    var archivo = campo.files && campo.files[0];
    if (!destino || !archivo || typeof archivo.slice !== "function") return;

    var forma = campo.form;
    var token = forma && forma.querySelector("input[name=csrfmiddlewaretoken]");
    var datos = new FormData();
    datos.append("cabecera", archivo.slice(0, CABECERA_BYTES), "cabecera");
    datos.append("nombre", archivo.name);
    datos.append("tamano", String(archivo.size));

    fetch(campo.getAttribute("data-reconoce"), {
      method: "POST",
      body: datos,
      credentials: "same-origin",
      headers: token ? { "X-CSRFToken": token.value } : {},
    })
      .then(function (respuesta) {
        return respuesta.ok ? respuesta.text() : "";
      })
      .then(function (html) {
        destino.innerHTML = html;
      })
      .catch(function () {
        // La vía de respaldo es la ficha; no se avisa de nada.
      });
  });
})();
