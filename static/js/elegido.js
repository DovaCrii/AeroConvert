/* Muestra qué se eligió en cada paso de «Corregir un vuelo de dron».
 *
 * El campo de la carpeta compartida es oculto, y el explorador solo le escribe la ruta: sin esto
 * quien eligió no ve nada y no sabe si lo hizo bien. Tampoco se ve el nombre de un archivo subido
 * del equipo en un campo que el navegador reinicia al volver atrás.
 *
 * Es un archivo y no un `onchange=` en la plantilla por la CSP: `script-src 'self'`, sin
 * `unsafe-inline`.
 */
(function () {
  "use strict";

  document.addEventListener("change", function (evento) {
    const campo = evento.target;
    if (!campo || !campo.dataset || !campo.dataset.muestraEn) return;
    const sitio = document.querySelector(campo.dataset.muestraEn);
    if (!sitio) return;

    let nombre = "";
    if (campo.type === "file") {
      nombre = campo.files && campo.files[0] ? campo.files[0].name : "";
    } else {
      // De una ruta, solo el nombre: la carpeta compartida puede ser larga.
      nombre = (campo.value || "").split(/[\\/]/).filter(Boolean).pop() || "";
    }
    sitio.textContent = nombre ? "Elegido: " + nombre : "";
    sitio.hidden = !nombre;
  });
})();
