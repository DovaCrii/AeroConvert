/* Escanear con el teléfono: marcar las cuatro esquinas de la hoja sobre su foto.
 *
 * **Sin JavaScript ya funciona**: cada foto trae sus ocho campos numéricos (un porcentaje del
 * ancho y del alto por esquina), que es también la vía del teclado. Esto solo añade lo cómodo:
 * un botón «Marcar las esquinas en la foto» que deja tocar o pulsar cada esquina en su orden
 * (arriba a la izquierda, arriba a la derecha, abajo a la derecha, abajo a la izquierda), el
 * recuadro que se redibuja al cambiar un número, y los cuatro puntos numerados.
 *
 * Funciona con ratón y con el dedo (`click` llega igual desde un toque) y no hay nada que
 * dependa de pasar el cursor por encima. Escape cancela y deja las esquinas como estaban. */
(function () {
  "use strict";

  var NOMBRES = [
    "arriba a la izquierda",
    "arriba a la derecha",
    "abajo a la derecha",
    "abajo a la izquierda",
  ];

  function campos(tarjeta, k) {
    return {
      x: tarjeta.querySelector('[data-esquina="' + k + '"][data-eje="x"]'),
      y: tarjeta.querySelector('[data-esquina="' + k + '"][data-eje="y"]'),
    };
  }

  function numero(campo) {
    var texto = (campo.value || "").replace(",", ".").trim();
    if (texto === "") return null;
    var valor = parseFloat(texto);
    return isFinite(valor) && valor >= 0 && valor <= 100 ? valor : null;
  }

  function leer(tarjeta) {
    var esquinas = [];
    for (var k = 0; k < 4; k++) {
      var c = campos(tarjeta, k);
      esquinas.push([numero(c.x), numero(c.y)]);
    }
    return esquinas;
  }

  function iniciar(tarjeta) {
    var foto = tarjeta.querySelector("[data-foto]");
    var imagen = foto.querySelector("img");
    var poligono = foto.querySelector("polygon");
    var boton = tarjeta.querySelector("[data-marcar]");
    var ayuda = tarjeta.querySelector("[data-ayuda-marcar]");
    var modoEsquinas = tarjeta.querySelector('input[type="radio"][value="esquinas"]');
    var modoEntera = tarjeta.querySelector('input[type="radio"][value="entera"]');
    var puntos = [];
    var marcando = false;
    var siguiente = 0;
    var respaldo = null;

    for (var k = 0; k < 4; k++) {
      var punto = document.createElement("span");
      punto.className = "hoja-esquina";
      punto.setAttribute("aria-hidden", "true");
      punto.textContent = String(k + 1);
      punto.hidden = true;
      foto.appendChild(punto);
      puntos.push(punto);
    }

    function pintar() {
      var esquinas = leer(tarjeta);
      var completas = esquinas.every(function (e) {
        return e[0] !== null && e[1] !== null;
      });
      poligono.setAttribute(
        "points",
        completas
          ? esquinas
              .map(function (e) {
                return e[0] + "," + e[1];
              })
              .join(" ")
          : ""
      );
      esquinas.forEach(function (e, i) {
        var hay = e[0] !== null && e[1] !== null;
        puntos[i].hidden = !hay;
        if (hay) {
          puntos[i].style.left = e[0] + "%";
          puntos[i].style.top = e[1] + "%";
        }
      });
      return completas;
    }

    function decir(texto) {
      ayuda.textContent = texto;
    }

    function terminar() {
      marcando = false;
      foto.classList.remove("marcando");
      boton.textContent = "Marcar las esquinas en la foto";
      boton.setAttribute("aria-pressed", "false");
    }

    function pedir() {
      decir(
        "Esquina " + (siguiente + 1) + " de 4: toque " + NOMBRES[siguiente] +
          " de la hoja. Escape cancela."
      );
    }

    function empezar() {
      respaldo = leer(tarjeta).map(function (e, i) {
        var c = campos(tarjeta, i);
        return [c.x.value, c.y.value];
      });
      for (var i = 0; i < 4; i++) {
        var c = campos(tarjeta, i);
        c.x.value = "";
        c.y.value = "";
      }
      marcando = true;
      siguiente = 0;
      foto.classList.add("marcando");
      boton.textContent = "Cancelar el marcado";
      boton.setAttribute("aria-pressed", "true");
      pintar();
      pedir();
    }

    function cancelar() {
      if (!marcando) return;
      for (var i = 0; i < 4; i++) {
        var c = campos(tarjeta, i);
        c.x.value = respaldo[i][0];
        c.y.value = respaldo[i][1];
      }
      terminar();
      pintar();
      decir("Marcado cancelado: las esquinas quedaron como estaban.");
    }

    boton.hidden = false; // sin JavaScript el botón no se ofrece: queda la vía de los números
    boton.setAttribute("aria-pressed", "false");
    boton.addEventListener("click", function () {
      if (marcando) cancelar();
      else empezar();
    });

    foto.addEventListener("click", function (evento) {
      if (!marcando) return;
      var caja = imagen.getBoundingClientRect();
      if (caja.width === 0 || caja.height === 0) return;
      var x = ((evento.clientX - caja.left) / caja.width) * 100;
      var y = ((evento.clientY - caja.top) / caja.height) * 100;
      x = Math.max(0, Math.min(100, x));
      y = Math.max(0, Math.min(100, y));
      var c = campos(tarjeta, siguiente);
      c.x.value = x.toFixed(2);
      c.y.value = y.toFixed(2);
      siguiente += 1;
      pintar();
      if (siguiente < 4) {
        pedir();
        return;
      }
      terminar();
      modoEsquinas.checked = true;
      decir("Las cuatro esquinas están marcadas. Compruebe que el recuadro rodea la hoja.");
    });

    tarjeta.addEventListener("keydown", function (evento) {
      if (evento.key === "Escape" && marcando) cancelar();
    });

    tarjeta.addEventListener("input", function (evento) {
      if (!evento.target.matches("[data-esquina]")) return;
      var completas = pintar();
      if (completas && modoEntera.checked) modoEsquinas.checked = true;
    });

    pintar();
  }

  document.querySelectorAll("[data-escanear] .hoja-escaneada").forEach(iniciar);
})();
