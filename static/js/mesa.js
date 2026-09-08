// Arrastrar y soltar sobre la zona de la mesa.
//
// **Lo que se toma del archivo soltado es su nombre, no su contenido.** En modo taller la
// conversion lee del disco, asi que subir los bytes al servidor solo para volver a leerlos
// de ahi seria mover cientos de megabytes por nada.
//
// El navegador, por seguridad, **no entrega la ruta completa** de un archivo soltado: solo
// el nombre. Asi que soltar rellena lo que puede y lo dice; pegar la ruta sigue siendo el
// camino fiable, y por eso el campo de texto es el protagonista y no un adorno.
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var zona = document.getElementById("zona");
    var campo = document.getElementById("ruta");
    var forma = document.getElementById("forma-inspeccion");
    if (!zona || !campo || !forma) {
      return;
    }

    ["dragenter", "dragover"].forEach(function (evento) {
      zona.addEventListener(evento, function (e) {
        e.preventDefault();
        zona.classList.add("encima");
      });
    });

    ["dragleave", "drop"].forEach(function (evento) {
      zona.addEventListener(evento, function () {
        zona.classList.remove("encima");
      });
    });

    zona.addEventListener("drop", function (e) {
      e.preventDefault();
      var archivos = e.dataTransfer && e.dataTransfer.files;
      if (!archivos || !archivos.length) {
        return;
      }
      var actual = campo.value.trim();
      // Si ya hay una carpeta escrita, se completa con el nombre soltado. Es el caso comun:
      // se pega la carpeta una vez y luego se van soltando archivos.
      if (actual && /[\\/]$/.test(actual)) {
        campo.value = actual + archivos[0].name;
      } else {
        campo.value = archivos[0].name;
      }
      campo.focus();
      if (/[\\/]/.test(campo.value)) {
        forma.requestSubmit();
      }
    });

    // Pegar una ruta la limpia de las comillas que anade «Copiar como ruta» de Windows.
    campo.addEventListener("paste", function () {
      window.setTimeout(function () {
        campo.value = campo.value.trim().replace(/^"|"$/g, "");
      }, 0);
    });
  });
})();
