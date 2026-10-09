/* El visor del vuelo: el recorrido, un punto por foto y la foto misma.
 *
 * ## Qué dibuja y con qué
 *
 * Todo en un `<canvas>`, **sin biblioteca ni mapa base**: no hay nada que vendorizar y nada sale del
 * equipo. Dibuja una retícula en metros del sistema de coordenadas **medido** (los valores de la
 * retícula son el Este y el Norte reales: se suma el origen que trae `vuelo.json`), la trayectoria,
 * y un punto por foto coloreado por su calidad. Pinchar un punto o una fila de la lista enseña la
 * foto y sus datos.
 *
 * ## Qué no inventa
 *
 * Una foto sin posición **no se dibuja** y se lista aparte con su motivo; una sin calidad
 * informada sale en gris y la leyenda lo dice. Los colores no se escriben aquí: se leen de las
 * variables de la hoja de estilos (`--av-ok`, `--av-warn`…), así que cambian solos con el tema.
 *
 * ## Por qué es un archivo
 *
 * La CSP es `script-src 'self'` sin `unsafe-inline`. Todo el contrato con la plantilla es por
 * `data-*` y por `id`. Los textos de las fotos (que vienen de un CSV) se ponen con `textContent`,
 * nunca como HTML.
 */
(function () {
  "use strict";

  const raiz = document.getElementById("visor");
  if (!raiz) return;

  const $ = (id) => document.getElementById(id);
  const lienzo = $("visor-lienzo");
  const contexto = lienzo.getContext("2d");
  const FILAS_MAXIMAS = 300;
  const RADIO_DE_PUNTERIA = 10;

  let datos = null;
  let fotos = [];
  let trayectoria = [];
  let seleccion = -1;
  let encima = -1;
  let visibles = [];
  let colores = {};
  let ancho = 0;
  let alto = 0;
  let pendiente = false;
  // Mientras nadie mueva ni acerque el mapa, un cambio de tamaño lo vuelve a ajustar: el lienzo
  // se mide antes de que la página termine de acomodarse y el primer ajuste quedaba corto.
  let tocada = false;
  const vista = { cx: 0, cy: 0, k: 1 };
  const filtro = { texto: "", calidad: "" };

  /* ---- Colores: de las variables de la hoja, no de aquí ---- */

  function leerColores() {
    const estilo = getComputedStyle(raiz);
    const v = (nombre) => estilo.getPropertyValue(nombre).trim() || "#888";
    colores = {
      buena: v("--av-ok"),
      flotante: v("--av-warn"),
      simple: v("--av-danger"),
      sin: v("--av-text-muted"),
      trayectoria: v("--av-info"),
      seleccion: v("--av-primary"),
      texto: v("--av-text-secondary"),
      rejilla: v("--av-border"),
      fondo: v("--av-surface-alt"),
    };
  }

  /* ---- Qué calidad tiene cada foto ---- */

  function clase(f) {
    if (f.x === undefined) return "ninguna";
    const c = (f.calidad || "").toLowerCase();
    if (c === "ppk" || c === "fija") return "buena";
    if (c === "flotante") return "flotante";
    if (["simple", "sbas", "dgps", "ppp"].includes(c)) return "simple";
    return "sin";
  }

  /* ---- Coordenadas: metros desde el origen <-> píxeles ---- */

  const aPantallaX = (x) => (x - vista.cx) * vista.k + ancho / 2;
  const aPantallaY = (y) => alto / 2 - (y - vista.cy) * vista.k;
  const aMetrosX = (px) => (px - ancho / 2) / vista.k + vista.cx;
  const aMetrosY = (py) => (alto / 2 - py) / vista.k + vista.cy;

  function ajustar() {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    const mira = (x, y) => {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    };
    trayectoria.forEach((p) => mira(p[0], p[1]));
    fotos.forEach((f) => f.x !== undefined && mira(f.x, f.y));
    if (!isFinite(minX)) return;
    const margen = 36;
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    vista.k = Math.min((ancho - 2 * margen) / bw, (alto - 2 * margen) / bh);
    vista.cx = (minX + maxX) / 2;
    vista.cy = (minY + maxY) / 2;
    pedir();
  }

  function acercar(factor, px, py) {
    tocada = true;
    const antesX = aMetrosX(px);
    const antesY = aMetrosY(py);
    vista.k = Math.max(0.01, Math.min(2000, vista.k * factor));
    // Que lo que estaba bajo el cursor siga bajo el cursor.
    vista.cx = antesX - (px - ancho / 2) / vista.k;
    vista.cy = antesY - (alto / 2 - py) / vista.k;
    pedir();
  }

  /* ---- Dibujo ---- */

  /**
   * Una marca por calidad, **de distinta forma además de distinto color**: regla de la casa, el color
   * nunca va solo (quien no distingue el verde del ámbar tiene que poder leer el mapa igual).
   * Círculo: PPK o fija · triángulo: flotante · cuadrado: simple · rombo: sin calidad informada.
   */
  function marca(c, tipo, px, py, r) {
    c.beginPath();
    if (tipo === "flotante") {
      c.moveTo(px, py - r * 1.25);
      c.lineTo(px + r * 1.15, py + r * 0.9);
      c.lineTo(px - r * 1.15, py + r * 0.9);
      c.closePath();
    } else if (tipo === "simple") {
      c.rect(px - r * 0.95, py - r * 0.95, r * 1.9, r * 1.9);
    } else if (tipo === "sin") {
      c.moveTo(px, py - r * 1.3);
      c.lineTo(px + r * 1.3, py);
      c.lineTo(px, py + r * 1.3);
      c.lineTo(px - r * 1.3, py);
      c.closePath();
    } else {
      c.arc(px, py, r, 0, 2 * Math.PI);
    }
  }

  function pedir() {
    if (pendiente) return;
    pendiente = true;
    const hacer = () => {
      if (!pendiente) return; // el otro de los dos ya dibujó
      pendiente = false;
      dibujar();
    };
    // `requestAnimationFrame` se detiene en una pestaña sin foco o en segundo plano, y entonces el
    // mapa se quedaba en blanco hasta que algo lo despertaba. El temporizador es el respaldo: dibujar
    // en un lienzo no necesita que la página esté a la vista.
    requestAnimationFrame(hacer);
    setTimeout(hacer, 80);
  }

  function paso(minimo) {
    // 1, 2 o 5 por una potencia de diez que sea al menos `minimo` metros.
    const potencia = Math.pow(10, Math.floor(Math.log10(minimo)));
    for (const f of [1, 2, 5, 10]) if (f * potencia >= minimo) return f * potencia;
    return 10 * potencia;
  }

  const miles = (n) => Math.round(n).toLocaleString("es-CL").replace(/\./g, " ");

  /**
   * Un Este o un Norte con sus milímetros: «414 884,611».
   *
   * Se formatea **desde el texto con tres decimales**, no redondeando el entero y pegándole los
   * decimales detrás (que subía un metro entero cada vez que la parte decimal pasaba de 0,5: el
   * 414 884,611 salía «414 885,611»). Lo vio una persona al comparar con Trimble.
   */
  const metros = (n) => {
    const [entero, decimales] = n.toFixed(3).split(".");
    return entero.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + "," + decimales;
  };

  function dibujarRejilla() {
    const c = contexto;
    const separacion = paso(90 / vista.k);
    const este0 = datos.origen.este;
    const norte0 = datos.origen.norte;
    c.lineWidth = 1;
    c.strokeStyle = colores.rejilla;
    c.fillStyle = colores.texto;
    c.font = "11px ui-monospace, Consolas, monospace";

    const x0 = Math.floor(aMetrosX(0) / separacion) * separacion;
    const x1 = aMetrosX(ancho);
    c.textAlign = "left";
    c.textBaseline = "top";
    for (let x = x0; x <= x1; x += separacion) {
      const px = Math.round(aPantallaX(x)) + 0.5;
      c.beginPath();
      c.moveTo(px, 0);
      c.lineTo(px, alto);
      c.stroke();
      c.fillText(miles(este0 + x), px + 3, 3);
    }
    const y0 = Math.floor(aMetrosY(alto) / separacion) * separacion;
    const y1 = aMetrosY(0);
    c.textBaseline = "bottom";
    for (let y = y0; y <= y1; y += separacion) {
      const py = Math.round(aPantallaY(y)) + 0.5;
      c.beginPath();
      c.moveTo(0, py);
      c.lineTo(ancho, py);
      c.stroke();
      c.fillText(miles(norte0 + y), 4, py - 2);
    }
  }

  function dibujarEscala() {
    const c = contexto;
    const metros = paso(110 / vista.k);
    const largo = metros * vista.k;
    const x = 16;
    const y = alto - 18;
    c.strokeStyle = colores.texto;
    c.fillStyle = colores.texto;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(x, y - 4);
    c.lineTo(x, y);
    c.lineTo(x + largo, y);
    c.lineTo(x + largo, y - 4);
    c.stroke();
    c.font = "12px ui-monospace, Consolas, monospace";
    c.textAlign = "left";
    c.textBaseline = "bottom";
    c.fillText(metros >= 1000 ? metros / 1000 + " km" : metros + " m", x, y - 6);
  }

  function dibujarNorte() {
    const c = contexto;
    const x = ancho - 28;
    const y = 44;
    c.strokeStyle = colores.texto;
    c.fillStyle = colores.texto;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(x, y + 14);
    c.lineTo(x, y - 12);
    c.moveTo(x - 5, y - 6);
    c.lineTo(x, y - 12);
    c.lineTo(x + 5, y - 6);
    c.stroke();
    c.font = "bold 12px system-ui, sans-serif";
    c.textAlign = "center";
    c.textBaseline = "top";
    c.fillText("N", x, y + 17);
  }

  function dibujar() {
    if (!datos) return;
    const c = contexto;
    c.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);
    c.clearRect(0, 0, ancho, alto);
    c.fillStyle = colores.fondo;
    c.fillRect(0, 0, ancho, alto);

    dibujarRejilla();

    // La trayectoria.
    if (trayectoria.length > 1) {
      c.strokeStyle = colores.trayectoria;
      c.lineWidth = 2;
      c.globalAlpha = 0.85;
      c.lineJoin = "round";
      c.beginPath();
      trayectoria.forEach((p, i) => {
        const px = aPantallaX(p[0]);
        const py = aPantallaY(p[1]);
        if (i === 0) c.moveTo(px, py);
        else c.lineTo(px, py);
      });
      c.stroke();
      c.globalAlpha = 1;
    }

    // Los puntos de las fotos, de menor a mayor importancia: lo seleccionado queda encima.
    const radio = fotos.length > 1500 ? 2.5 : 3.5;
    const enLista = new Set(visibles);
    fotos.forEach((f, i) => {
      if (f.x === undefined) return;
      const px = aPantallaX(f.x);
      const py = aPantallaY(f.y);
      if (px < -8 || px > ancho + 8 || py < -8 || py > alto + 8) return;
      c.globalAlpha = enLista.has(i) ? 1 : 0.18;
      c.fillStyle = colores[clase(f)];
      marca(c, clase(f), px, py, radio);
      c.fill();
    });
    c.globalAlpha = 1;

    [encima, seleccion].forEach((i, orden) => {
      if (i < 0 || fotos[i].x === undefined) return;
      const px = aPantallaX(fotos[i].x);
      const py = aPantallaY(fotos[i].y);
      c.lineWidth = 2.5;
      c.strokeStyle = orden === 1 ? colores.seleccion : colores.texto;
      c.fillStyle = colores[clase(fotos[i])];
      marca(c, clase(fotos[i]), px, py, orden === 1 ? 7 : 6);
      c.fill();
      c.stroke();
    });

    dibujarEscala();
    dibujarNorte();
  }

  /* ---- Tamaño del lienzo ---- */

  function medir() {
    const caja = $("visor-mapa").getBoundingClientRect();
    ancho = Math.max(200, Math.floor(caja.width));
    alto = Math.max(260, Math.floor(caja.height));
    const d = window.devicePixelRatio || 1;
    lienzo.width = Math.round(ancho * d);
    lienzo.height = Math.round(alto * d);
    lienzo.style.width = ancho + "px";
    lienzo.style.height = alto + "px";
    if (datos && !tocada) ajustar();
    else pedir();
  }

  /* ---- Elegir una foto ---- */

  function masCercana(px, py) {
    let mejor = -1;
    let distancia = RADIO_DE_PUNTERIA * RADIO_DE_PUNTERIA;
    const enLista = new Set(visibles);
    fotos.forEach((f, i) => {
      if (f.x === undefined || !enLista.has(i)) return;
      const dx = aPantallaX(f.x) - px;
      const dy = aPantallaY(f.y) - py;
      const d2 = dx * dx + dy * dy;
      if (d2 < distancia) {
        distancia = d2;
        mejor = i;
      }
    });
    return mejor;
  }

  function fechaGps(t) {
    const d = new Date(Date.UTC(1980, 0, 6) + t * 1000);
    return d.toISOString().replace("T", " ").slice(0, 21) + " GPST";
  }

  function fila(titulo, valor) {
    const dt = document.createElement("dt");
    dt.textContent = titulo;
    const dd = document.createElement("dd");
    dd.textContent = valor;
    return [dt, dd];
  }

  function mostrarFoto(i) {
    seleccion = i;
    const titulo = $("visor-foto-titulo");
    const imagen = $("visor-imagen");
    const vacia = $("visor-foto-vacia");
    const ficha = $("visor-ficha");
    const nav = $("visor-nav");
    ficha.replaceChildren();
    if (i < 0) {
      titulo.textContent = "Elija una foto";
      imagen.hidden = true;
      vacia.hidden = false;
      vacia.textContent = "Pinche un punto del mapa o una foto de la lista.";
      ficha.hidden = true;
      nav.hidden = true;
      pedir();
      pintarFilas();
      return;
    }
    const f = fotos[i];
    titulo.textContent = f.nombre || "Disparo " + f.n;
    nav.hidden = false;
    ficha.hidden = false;
    const filas = [fila("Disparo", String(f.n))];
    if (f.x === undefined) {
      filas.push(fila("Posición", "No tiene: " + f.motivo));
    } else {
      filas.push(
        fila("Calidad", f.calidad || "No informada"),
        fila("Este", metros(datos.origen.este + f.x)),
        fila("Norte", metros(datos.origen.norte + f.y)),
        fila("Latitud", f.lat.toFixed(9)),
        fila("Longitud", f.lon.toFixed(9)),
        fila("Altura", f.alt === null || f.alt === undefined ? "No informada" : f.alt.toFixed(3) + " m"),
        fila("Hora", fechaGps(f.t_gps_s))
      );
    }
    filas.forEach(([dt, dd]) => ficha.append(dt, dd));

    if (f.miniatura && raiz.dataset.miniaturas === "si") {
      imagen.alt = "Foto " + (f.nombre || f.n);
      imagen.src = raiz.dataset.miniatura.replace(/\/foto\/1\/$/, "/foto/" + f.n + "/");
      imagen.hidden = false;
      vacia.hidden = true;
    } else {
      imagen.hidden = true;
      vacia.hidden = false;
      vacia.textContent =
        raiz.dataset.miniaturas === "si"
          ? "Esta foto no está en la carpeta elegida."
          : "No se eligió la carpeta de fotos: no hay miniatura.";
    }

    // Si el punto quedó fuera de la vista, se lleva al centro.
    if (f.x !== undefined) {
      const px = aPantallaX(f.x);
      const py = aPantallaY(f.y);
      if (px < 20 || px > ancho - 20 || py < 20 || py > alto - 20) {
        vista.cx = f.x;
        vista.cy = f.y;
      }
    }
    pedir();
    pintarFilas();
  }

  $("visor-imagen").addEventListener("error", function () {
    this.hidden = true;
    const vacia = $("visor-foto-vacia");
    vacia.hidden = false;
    vacia.textContent = "No se pudo abrir la foto.";
  });

  function mover(delta) {
    if (!visibles.length) return;
    const actual = visibles.indexOf(seleccion);
    const siguiente = actual < 0 ? 0 : (actual + delta + visibles.length) % visibles.length;
    mostrarFoto(visibles[siguiente]);
  }

  /* ---- La lista ---- */

  function pasaElFiltro(f) {
    const c = clase(f);
    if (filtro.calidad && c !== filtro.calidad) return false;
    if (filtro.texto) {
      const texto = ((f.nombre || "") + " " + f.n).toLowerCase();
      if (!texto.includes(filtro.texto)) return false;
    }
    return true;
  }

  function filtrar() {
    visibles = [];
    fotos.forEach((f, i) => {
      if (pasaElFiltro(f)) visibles.push(i);
    });
    pintarFilas();
    pedir();
  }

  function pintarFilas() {
    const lista = $("visor-filas");
    lista.replaceChildren();
    const mostrar = visibles.slice(0, FILAS_MAXIMAS);
    // La foto elegida siempre está a la vista en la lista, aunque pase de las 300.
    if (seleccion >= 0 && visibles.includes(seleccion) && !mostrar.includes(seleccion)) {
      mostrar.unshift(seleccion);
    }
    mostrar.forEach((i) => {
      const f = fotos[i];
      const li = document.createElement("li");
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "visor-fila" + (i === seleccion ? " visor-fila-activa" : "");
      boton.dataset.indice = String(i);
      const punto = document.createElement("i");
      punto.className = "visor-punto visor-punto-" + clase(f);
      punto.setAttribute("aria-hidden", "true");
      const nombre = document.createElement("span");
      nombre.className = "visor-fila-nombre";
      nombre.textContent = f.nombre || "Disparo " + f.n;
      boton.append(punto, nombre);
      const calidad = document.createElement("span");
      calidad.className = "visually-hidden";
      calidad.textContent = f.x === undefined ? ", sin posición" : ", calidad " + (f.calidad || "no informada");
      boton.append(calidad);
      boton.title = f.x === undefined ? "Sin posición" : f.calidad || "Calidad no informada";
      if (i === seleccion) boton.setAttribute("aria-current", "true");
      li.append(boton);
      lista.append(li);
    });
    const mas = $("visor-mas-filas");
    if (visibles.length > FILAS_MAXIMAS) {
      mas.hidden = false;
      mas.textContent =
        "Se muestran " + FILAS_MAXIMAS + " de " + visibles.length + ". Afine la búsqueda para ver el resto.";
    } else {
      mas.hidden = true;
    }
    // Un vuelo con RTK no tiene trayectoria: no se dice «0 de 0 puntos».
    $("visor-pie").textContent =
      visibles.length + " de " + fotos.length + " fotos" +
      (datos.trayectoria_total
        ? " · trayectoria: " + trayectoria.length + " de " + datos.trayectoria_total + " puntos dibujados"
        : "");
  }

  /* ---- Ratón, rueda y teclado ---- */

  let arrastre = null;

  lienzo.addEventListener("pointerdown", (e) => {
    lienzo.setPointerCapture(e.pointerId);
    arrastre = { x: e.clientX, y: e.clientY, cx: vista.cx, cy: vista.cy, movido: false };
    lienzo.focus({ preventScroll: true });
  });

  lienzo.addEventListener("pointermove", (e) => {
    const caja = lienzo.getBoundingClientRect();
    const px = e.clientX - caja.left;
    const py = e.clientY - caja.top;
    if (arrastre) {
      const dx = e.clientX - arrastre.x;
      const dy = e.clientY - arrastre.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) arrastre.movido = true;
      if (arrastre.movido) {
        tocada = true;
        vista.cx = arrastre.cx - dx / vista.k;
        vista.cy = arrastre.cy + dy / vista.k;
        pedir();
      }
      return;
    }
    const i = masCercana(px, py);
    if (i !== encima) {
      encima = i;
      lienzo.style.cursor = i >= 0 ? "pointer" : "grab";
      if (i >= 0) $("visor-pie").textContent = fotos[i].nombre || "Disparo " + fotos[i].n;
      pedir();
    }
  });

  lienzo.addEventListener("pointerup", (e) => {
    const eraClic = arrastre && !arrastre.movido;
    arrastre = null;
    if (!eraClic) return;
    const caja = lienzo.getBoundingClientRect();
    const i = masCercana(e.clientX - caja.left, e.clientY - caja.top);
    mostrarFoto(i);
  });

  lienzo.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const caja = lienzo.getBoundingClientRect();
      acercar(Math.pow(1.0015, -e.deltaY), e.clientX - caja.left, e.clientY - caja.top);
    },
    { passive: false }
  );

  lienzo.addEventListener("keydown", (e) => {
    const teclas = {
      ArrowRight: () => mover(1),
      ArrowDown: () => mover(1),
      ArrowLeft: () => mover(-1),
      ArrowUp: () => mover(-1),
      "+": () => acercar(1.4, ancho / 2, alto / 2),
      "=": () => acercar(1.4, ancho / 2, alto / 2),
      "-": () => acercar(1 / 1.4, ancho / 2, alto / 2),
      0: ajustar,
      Escape: () => mostrarFoto(-1),
    };
    const accion = teclas[e.key];
    if (!accion) return;
    e.preventDefault();
    accion();
  });

  $("visor-ajustar").addEventListener("click", () => {
    tocada = false;
    ajustar();
  });
  $("visor-mas").addEventListener("click", () => acercar(1.5, ancho / 2, alto / 2));
  $("visor-menos").addEventListener("click", () => acercar(1 / 1.5, ancho / 2, alto / 2));
  $("visor-anterior").addEventListener("click", () => mover(-1));
  $("visor-siguiente").addEventListener("click", () => mover(1));
  $("visor-filas").addEventListener("click", (e) => {
    const boton = e.target.closest("[data-indice]");
    if (boton) mostrarFoto(parseInt(boton.dataset.indice, 10));
  });
  $("visor-buscar").addEventListener("input", (e) => {
    filtro.texto = e.target.value.trim().toLowerCase();
    filtrar();
  });
  $("visor-calidad").addEventListener("change", (e) => {
    filtro.calidad = e.target.value;
    filtrar();
  });

  if (window.ResizeObserver) new ResizeObserver(medir).observe($("visor-mapa"));
  else window.addEventListener("resize", medir);

  // El tema puede cambiar con la página abierta: los colores se vuelven a leer.
  new MutationObserver(() => {
    leerColores();
    pedir();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      leerColores();
      pedir();
    });
  }

  /* ---- Arranque ---- */

  fetch(raiz.dataset.datos, { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((json) => {
      datos = json;
      fotos = json.fotos;
      trayectoria = json.trayectoria;
      leerColores();
      $("visor-cargando").hidden = true;
      medir();
      ajustar();
      filtrar();
      lienzo.style.cursor = "grab";
    })
    .catch((fallo) => {
      const aviso = $("visor-cargando");
      aviso.hidden = false;
      aviso.textContent = "No se pudo cargar el vuelo (" + fallo.message + ").";
    });
})();
