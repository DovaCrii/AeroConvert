/* Ver en el mapa: una ortofoto por teselas, con zoom y paneo, sobre una retícula de coordenadas.
 *
 * ## Qué dibuja y con qué
 *
 * Todo en un `<canvas>`, **sin biblioteca ni mapa base** (D5: nada sale del equipo): una retícula
 * de meridianos y paralelos como fondo (la de la ficha del archivo, F13.11), las teselas PNG de
 * 256 × 256 en EPSG:3857 que corta el servidor del propio archivo (`apps/visor/teselas.py`) y el
 * contorno de la capa. No hay ninguna petición a otro origen: las teselas, la ficha de la capa y el
 * punto bajo el cursor son del mismo servidor, con la sesión de quien mira.
 *
 * ## Cómo se maneja
 *
 * Ratón o dedo: arrastrar mueve, la rueda y el pellizco acercan, doble clic acerca un nivel. Teclado
 * (con el mapa enfocado): las flechas mueven, `+` y `-` acercan y alejan, `0` o Inicio encuadra la
 * capa, Intro pide el valor del píxel del centro. **Nada depende de pasar el ratón por encima.**
 *
 * ## Terreno (F19.4)
 *
 * Si la capa es un DEM (`capa.es_dem`), un panel deja elegir cómo se ve (grises, sombreado o color
 * por cota; con su leyenda escrita), la cota bajo el cursor sale con su unidad y su referencia
 * vertical **solo si el archivo las declara**, y «Marcar perfil» traza una línea entre dos puntos
 * (A y B, con letra y forma) y dibuja su perfil en un SVG propio, con su tabla y su CSV. Lo que no
 * tiene dato queda como hueco en la línea, nunca se une ni se interpola.
 *
 * ## Varias capas y su orden (F19.3)
 *
 * El mapa es una **pila de capas**: imágenes (la primera es la principal, la del terreno y el
 * perfil), el mapa base propio de la casa (F19.5) y las tres partes de un vuelo de «Corregir un
 * vuelo de dron» (trayectoria, fotos y puntos de control). Cada capa se enciende o se apaga, tiene su
 * transparencia (0 % opaca, 100 % no se ve) y su lugar en la lista; subir y bajar son **botones**
 * (nada depende de arrastrar). La lista, el orden y la transparencia se guardan en la dirección
 * (`e=id:transparencia:visible,…`) con `history.replaceState`, para volver a abrir el mapa tal cual.
 * Las posiciones del vuelo llegan del servidor **ya en Web Mercator**; la calidad de cada foto se
 * dibuja con color **y** forma (círculo, triángulo, cuadrado, rombo), y su leyenda está escrita.
 * Una capa que no se puede dibujar (sin sistema, sin permiso, sin datos) lo dice **en su fila**.
 *
 * ## Qué no inventa
 *
 * El sistema del archivo y las coordenadas **en él** las dice el servidor (PROJ), no este archivo. Un
 * valor «sin dato» sale como tal. Todo texto que viene del servidor entra con `textContent`.
 *
 * ## Por qué es un archivo
 *
 * La CSP es `script-src 'self'` sin `unsafe-inline`. El contrato con la plantilla es por `data-*` y
 * por `id`.
 */
(function () {
  "use strict";

  const raiz = document.getElementById("mapa-visor");
  if (!raiz) return;

  const $ = (id) => document.getElementById(id);
  const lienzo = $("mapa-lienzo");
  const contexto = lienzo.getContext("2d");

  /* ---- La cuadrícula de Web Mercator (la misma de `apps/visor/mercator.py`) ---- */

  const RADIO = 6378137;
  const ORIGEN = Math.PI * RADIO; // 20037508,342789244
  const LADO = 256;
  const LATITUD_MAXIMA = 85.0511287798066;

  const resolucion = (z) => (2 * ORIGEN) / (LADO * Math.pow(2, z)); // metros por píxel
  const aLon = (x) => (x / RADIO) * (180 / Math.PI);
  const aLat = (y) => (2 * Math.atan(Math.exp(y / RADIO)) - Math.PI / 2) * (180 / Math.PI);
  const deLon = (lon) => RADIO * (lon * Math.PI) / 180;
  const deLat = (lat) => RADIO * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

  /* ---- Estado ---- */

  const MAXIMO_EN_VUELO = 6;
  const MAXIMO_EN_MEMORIA = 400;
  const MAXIMO_VISIBLES = 120;
  const ESPERA_DEL_PUNTO_MS = 150;
  const REINTENTO_DE_ERROR_MS = 8000;

  // La ficha de la capa principal (`null` si el mapa es solo de vuelos). Todo lo del terreno y el
  // perfil, y la lectura del píxel, es de esta capa.
  let capa = null;
  let principal = null;
  const pila = []; // las capas, de arriba (0) a abajo
  const vuelos = new Map(); // id del trabajo -> { datos, urls, estado, mensaje }
  let iniciado = false;
  let foto = null; // { vuelo, i }: la foto elegida
  let colores = {};
  let ancho = 0;
  let alto = 0;
  let densidad = 1;
  let pendiente = false;
  let tocada = false; // mientras nadie la toque, un cambio de tamaño vuelve a encuadrar
  const vista = { cx: 0, cy: 0, z: 0 };

  // Cada capa ráster guarda sus teselas en `l.imagenes` ("z/x/y" -> { img, listo, error, hasta });
  // la cola de lo que falta por pedir es de todas, y el tope de peticiones a la vez también.
  const cola = [];
  let enVuelo = 0;
  let falladas = 0;

  const punteros = new Map();
  let arrastre = null; // { x, y, movido }
  let cursor = null; // { x, y } en píxeles del lienzo, o null si no hay puntero encima
  let marca = null; // { mx, my } donde se pidió el valor del píxel
  let esperaPunto = 0;
  let controlPunto = null;

  // Terreno (F19.4): solo lo usa un DEM. `modo` es lo que se pide en cada tesela.
  let modo = { nombre: "gris", az: "315", alt: "45", zf: "1.0" };
  // El perfil: los dos puntos (en metros de Web Mercator), el último resultado y su petición.
  const perfil = { activo: false, a: null, b: null, datos: null, control: null };

  /* ---- Colores: de las variables de la hoja, no de aquí ---- */

  function leerColores() {
    const estilo = getComputedStyle(raiz);
    const v = (nombre, resto) => estilo.getPropertyValue(nombre).trim() || resto;
    colores = {
      fondo: v("--av-surface-alt", "#f4f6f8"),
      rejilla: v("--av-border", "#ccd"),
      texto: v("--av-text-secondary", "#555"),
      contorno: v("--av-primary", "#a0207a"),
      marca: v("--av-danger", "#c00"),
      escala: v("--av-text", "#111"),
      papel: v("--av-surface", "#fff"),
      // El vuelo (F19.3): cada marca lleva además un borde `papel`, así que se lee sobre cualquier
      // imagen de fondo. La prueba de contraste de `apps/core/test_paleta.py` mide estos tokens.
      buena: v("--av-ok", "#287a3e"),
      flotante: v("--av-warn", "#8a5a00"),
      simple: v("--av-danger", "#c00"),
      sin: v("--av-text-muted", "#666"),
      trayectoria: v("--av-info", "#1a5f9e"),
      control: v("--av-primary", "#a0207a"),
    };
  }

  /* ---- Texto con coma decimal, como el resto de la aplicación ---- */

  const formato = (valor, decimales) =>
    new Intl.NumberFormat("es-CL", {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales,
    }).format(valor);

  /* ---- Pantalla <-> metros de Web Mercator ---- */

  const aPantallaX = (mx) => (mx - vista.cx) / resolucion(vista.z) + ancho / 2;
  const aPantallaY = (my) => alto / 2 - (my - vista.cy) / resolucion(vista.z);
  const aMetrosX = (px) => (px - ancho / 2) * resolucion(vista.z) + vista.cx;
  const aMetrosY = (py) => (alto / 2 - py) * resolucion(vista.z) + vista.cy;

  /* ---- Qué es cada capa y dónde está ---- */

  const esRaster = (l) => l.tipo === "raster" || l.tipo === "fondo";
  const esVuelo = (l) => l.tipo.indexOf("vuelo-") === 0;
  // `lista`: tiene qué dibujar. Cualquier otro estado (`cargando`, `apagada`, `error`) se dice en su fila.
  const dibujable = (l) => l.estado === "lista";

  function cajaDe(l) {
    if (esRaster(l)) return l.ficha.caja_3857;
    const v = vuelos.get(l.vuelo);
    return v && v.datos ? v.datos.caja_3857 : null;
  }

  /* La caja (metros de Web Mercator) que cubren las capas listas. Con `conFondo` falso, sin el mapa
   * base: encuadrar sobre un mosaico de la región entera dejaría la ortofoto del tamaño de un punto. */
  function cajaUnida(conFondo) {
    let caja = null;
    pila.forEach(function (l) {
      if (!dibujable(l) || (l.tipo === "fondo" && !conFondo)) return;
      const c = cajaDe(l);
      if (!c) return;
      caja = caja
        ? [Math.min(caja[0], c[0]), Math.min(caja[1], c[1]), Math.max(caja[2], c[2]), Math.max(caja[3], c[3])]
        : c.slice();
    });
    return caja;
  }

  function limitesDeZoom() {
    let minimo = Infinity;
    let maximo = -Infinity;
    pila.forEach(function (l) {
      if (!esRaster(l) || !dibujable(l)) return;
      minimo = Math.min(minimo, l.ficha.zoom_minimo - 1);
      maximo = Math.max(maximo, l.ficha.zoom_maximo + 2);
    });
    // Un mapa solo de vuelos no tiene teselas que acotarlo: hasta donde se ve un punto.
    if (!isFinite(minimo)) return { minimo: 0, maximo: 22 };
    return { minimo: Math.max(0, minimo), maximo: maximo };
  }

  function limitar() {
    const l = limitesDeZoom();
    vista.z = Math.min(Math.max(vista.z, l.minimo), l.maximo);
    // El centro no sale de lo que hay en el mapa: un mapa donde uno se pierde no sirve.
    const caja = cajaUnida(true);
    if (!caja) return;
    vista.cx = Math.min(Math.max(vista.cx, caja[0]), caja[2]);
    vista.cy = Math.min(Math.max(vista.cy, caja[1]), caja[3]);
  }

  function encuadrar() {
    const caja = cajaUnida(false) || cajaUnida(true);
    if (!caja) return;
    const [x0, y0, x1, y1] = caja;
    const margen = 24;
    const alcance = Math.max(
      (x1 - x0) / Math.max(ancho - 2 * margen, 50),
      (y1 - y0) / Math.max(alto - 2 * margen, 50)
    );
    vista.z = Math.log2((2 * ORIGEN) / (LADO * alcance));
    vista.cx = (x0 + x1) / 2;
    vista.cy = (y0 + y1) / 2;
    limitar();
    pedir();
    actualizarLectura();
  }

  /* ---- Teselas ---- */

  // La dirección de teselas sale de la plantilla (`data-teselas` termina en `0/0/0.png`).
  const BASE_DE_TESELAS = raiz.dataset.teselas.replace(/0\/0\/0\.png$/, "");

  function direccion(l, z, x, y) {
    // El modo de terreno (sombreado, color por cota) es de la capa principal; las demás, en grises.
    return (
      BASE_DE_TESELAS + z + "/" + x + "/" + y + ".png?ruta=" + encodeURIComponent(l.token) +
      (l === principal ? consultaDeTerreno() : "")
    );
  }

  /* El modo de un DEM va en la petición, con **todos** sus parámetros: el servidor los comprueba (un
   * azimut de 400° es un error con su mensaje, no se recorta) y los pone en la clave de la tesela. */
  function consultaDeTerreno() {
    if (!capa.es_dem || modo.nombre === "gris") return "";
    let consulta = "&modo=" + modo.nombre;
    if (modo.nombre === "sombra") {
      consulta +=
        "&az=" + encodeURIComponent(modo.az) +
        "&alt=" + encodeURIComponent(modo.alt) +
        "&zf=" + encodeURIComponent(modo.zf);
    }
    return consulta;
  }

  function tesela(l, z, x, y) {
    return l.imagenes.get(z + "/" + x + "/" + y);
  }

  function pedirTesela(l, z, x, y) {
    const clave = z + "/" + x + "/" + y;
    const previa = l.imagenes.get(clave);
    if (previa && (!previa.error || Date.now() < previa.hasta)) return;
    const registro = { img: null, listo: false, error: false, hasta: 0 };
    l.imagenes.set(clave, registro);
    cola.push({ capa: l, clave: clave, z: z, x: x, y: y, registro: registro });
    // La memoria acotada (por capa): se suelta lo que hace más tiempo que se pidió.
    if (l.imagenes.size > MAXIMO_EN_MEMORIA) {
      const primera = l.imagenes.keys().next().value;
      const suelta = l.imagenes.get(primera);
      if (suelta && suelta.img && suelta.img.close) suelta.img.close();
      l.imagenes.delete(primera);
    }
    sacarDeLaCola();
  }

  function sacarDeLaCola() {
    while (enVuelo < MAXIMO_EN_VUELO && cola.length) {
      // Primero lo más cercano al centro de lo que se mira.
      const mx = vista.cx;
      const my = vista.cy;
      let mejor = 0;
      let menor = Infinity;
      for (let i = 0; i < cola.length; i++) {
        const t = cola[i];
        const lado = (2 * ORIGEN) / Math.pow(2, t.z);
        const d = Math.hypot(-ORIGEN + (t.x + 0.5) * lado - mx, ORIGEN - (t.y + 0.5) * lado - my);
        if (d < menor) {
          menor = d;
          mejor = i;
        }
      }
      const t = cola.splice(mejor, 1)[0];
      if (t.capa.imagenes.get(t.clave) !== t.registro) continue; // ya se soltó de la memoria
      enVuelo++;
      cargarTesela(t);
    }
    estado();
  }

  /* Con `fetch` y no con `<img>`: una imagen que falla no dice por qué, y la respuesta del servidor
   * trae el motivo (`codigo` y `mensaje`, p. ej. el 504 «conviértala a COG»). */
  function cargarTesela(t) {
    const registro = t.registro;
    fetch(direccion(t.capa, t.z, t.x, t.y), { credentials: "same-origin" })
      .then(function (r) {
        if (r.ok) return r.blob();
        return r
          .json()
          .catch(function () {
            return {};
          })
          .then(function (datos) {
            throw { datos: datos, estado: r.status };
          });
      })
      .then(function (blob) {
        return createImageBitmap(blob);
      })
      .then(function (imagen) {
        registro.img = imagen;
        registro.listo = true;
        enVuelo--;
        estado();
        pedir();
        sacarDeLaCola();
      })
      .catch(function (fallo) {
        enVuelo--;
        registro.error = true;
        registro.hasta = Date.now() + REINTENTO_DE_ERROR_MS;
        falladas++;
        const datos = (fallo && fallo.datos) || {};
        avisarDeLaTesela(t.capa, datos.codigo || "tesela-sin-respuesta", datos.mensaje);
        estado();
        sacarDeLaCola();
      });
  }

  /* ---- Avisos: una sola vez, a la vista y leídos en voz alta ---- */

  let claveDelAviso = "";
  const avisados = new Set();

  function mostrarAviso(clave, texto) {
    const caja = $("mapa-aviso");
    if (!caja) return;
    claveDelAviso = clave;
    $("mapa-aviso-texto").textContent = texto;
    caja.hidden = false;
  }

  function quitarAviso(clave) {
    if (claveDelAviso !== clave) return;
    claveDelAviso = "";
    $("mapa-aviso").hidden = true;
  }

  /* Un motivo de tesela se dice **una vez** por capa y código: decenas de teselas con el mismo fallo
   * no son decenas de avisos. Con varias capas, el aviso dice de cuál habla. */
  function avisarDeLaTesela(l, codigo, mensaje) {
    const clave = l.id + ":" + codigo;
    if (avisados.has(clave)) return;
    avisados.add(clave);
    mostrarAviso(
      "tesela:" + clave,
      "«" + l.nombre + "»: " +
        (mensaje ||
          "no se pudo cortar una tesela y el servidor no dijo por qué. Si la imagen es muy grande, " +
            "conviértala a COG.")
    );
  }

  function estado() {
    const cargando = enVuelo + cola.length;
    const caja = $("mapa-estado");
    if (!caja) return;
    let texto = "";
    if (cargando) texto = "Cargando " + cargando + (cargando === 1 ? " tesela…" : " teselas…");
    else if (falladas) texto = "Hay teselas que no se pudieron cortar: se reintentará al mover el mapa.";
    caja.textContent = texto;
    caja.classList.toggle("visor-estado-error", !cargando && falladas > 0);
  }

  /* ---- Dibujo ---- */

  function pedir() {
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(function () {
      pendiente = false;
      dibujar();
    });
  }

  function pasoRedondo(extension) {
    const bruto = Math.max(extension / 5, 1e-9);
    const potencia = Math.pow(10, Math.floor(Math.log10(bruto)));
    for (const f of [1, 2, 5, 10]) if (bruto <= f * potencia) return f * potencia;
    return 10 * potencia;
  }

  function grados(valor, decimales, positivo, negativo) {
    return formato(Math.abs(valor), decimales) + "° " + (valor >= 0 ? positivo : negativo);
  }

  // Las etiquetas de la retícula se anotan al dibujar las líneas y se pintan **después** de las
  // teselas, con un fondo: debajo de la imagen no se leerían.
  let etiquetas = [];

  function dibujarReticula() {
    etiquetas = [];
    const lonIzq = aLon(aMetrosX(0));
    const lonDer = aLon(aMetrosX(ancho));
    const latSup = aLat(aMetrosY(0));
    const latInf = aLat(aMetrosY(alto));
    const pasoLon = pasoRedondo(Math.abs(lonDer - lonIzq));
    const pasoLat = pasoRedondo(Math.abs(latSup - latInf));
    const decLon = Math.max(0, -Math.floor(Math.log10(pasoLon) + 1e-9));
    const decLat = Math.max(0, -Math.floor(Math.log10(pasoLat) + 1e-9));

    contexto.save();
    contexto.strokeStyle = colores.rejilla;
    contexto.lineWidth = 1;
    contexto.setLineDash([3, 4]);
    for (let l = Math.ceil(lonIzq / pasoLon); l <= Math.floor(lonDer / pasoLon); l++) {
      const lon = l * pasoLon;
      const x = Math.round(aPantallaX(deLon(lon))) + 0.5;
      contexto.beginPath();
      contexto.moveTo(x, 0);
      contexto.lineTo(x, alto);
      contexto.stroke();
      etiquetas.push({ texto: grados(lon, decLon, "E", "O"), x: x, y: 4, alinear: "centro" });
    }
    const arriba = Math.min(latSup, LATITUD_MAXIMA);
    const abajo = Math.max(latInf, -LATITUD_MAXIMA);
    for (let l = Math.ceil(abajo / pasoLat); l <= Math.floor(arriba / pasoLat); l++) {
      const lat = l * pasoLat;
      const y = Math.round(aPantallaY(deLat(lat))) + 0.5;
      contexto.beginPath();
      contexto.moveTo(0, y);
      contexto.lineTo(ancho, y);
      contexto.stroke();
      etiquetas.push({ texto: grados(lat, decLat, "N", "S"), x: 4, y: y - 18, alinear: "izquierda" });
    }
    contexto.restore();
  }

  function dibujarEtiquetas() {
    contexto.save();
    contexto.font = "12px system-ui, sans-serif";
    contexto.textBaseline = "top";
    contexto.textAlign = "left";
    for (const e of etiquetas) {
      const ancha = contexto.measureText(e.texto).width + 8;
      const izq = e.alinear === "centro" ? e.x - ancha / 2 : e.x;
      contexto.fillStyle = colores.papel;
      contexto.fillRect(izq, e.y - 2, ancha, 17);
      contexto.fillStyle = colores.texto;
      contexto.fillText(e.texto, izq + 4, e.y);
    }
    contexto.restore();
  }

  function teselasVisibles(l, zt) {
    const lado = (2 * ORIGEN) / Math.pow(2, zt);
    const [cx0, cy0, cx1, cy1] = l.ficha.caja_3857;
    const x0 = Math.max(aMetrosX(0), cx0);
    const x1 = Math.min(aMetrosX(ancho), cx1);
    const yAlta = Math.min(aMetrosY(0), cy1);
    const yBaja = Math.max(aMetrosY(alto), cy0);
    if (x1 <= x0 || yAlta <= yBaja) return [];
    const maximo = Math.pow(2, zt) - 1;
    const tx0 = Math.min(Math.max(Math.floor((x0 + ORIGEN) / lado), 0), maximo);
    const tx1 = Math.min(Math.max(Math.floor((x1 + ORIGEN) / lado), 0), maximo);
    const ty0 = Math.min(Math.max(Math.floor((ORIGEN - yAlta) / lado), 0), maximo);
    const ty1 = Math.min(Math.max(Math.floor((ORIGEN - yBaja) / lado), 0), maximo);
    const lista = [];
    for (let ty = ty0; ty <= ty1; ty++) for (let tx = tx0; tx <= tx1; tx++) lista.push([tx, ty]);
    return lista;
  }

  function dibujarTeselas(l) {
    const f = l.ficha;
    const sesgo = Math.log2(Math.min(densidad, 2));
    const zt = Math.min(Math.max(Math.round(vista.z + sesgo), f.zoom_minimo), f.zoom_maximo);
    const lado = (2 * ORIGEN) / Math.pow(2, zt);
    const lista = teselasVisibles(l, zt);
    if (lista.length > MAXIMO_VISIBLES) {
      // Un encuadre así pediría cientos de teselas: no se piden, y se dice qué hacer.
      mostrarAviso(
        "demasiadas:" + l.id,
        "«" + l.nombre + "»: hay " +
          lista.length +
          " teselas a la vista, demasiadas para pedirlas todas. Acerque el mapa para verlas."
      );
      return;
    }
    quitarAviso("demasiadas:" + l.id);
    const ampliada = resolucion(zt) / resolucion(vista.z) > 1.5;
    contexto.imageSmoothingEnabled = !ampliada; // acercado, el píxel se ve cuadrado y se puede contar

    for (const [tx, ty] of lista) {
      const izq = Math.round(aPantallaX(-ORIGEN + tx * lado));
      const der = Math.round(aPantallaX(-ORIGEN + (tx + 1) * lado));
      const sup = Math.round(aPantallaY(ORIGEN - ty * lado));
      const inf = Math.round(aPantallaY(ORIGEN - (ty + 1) * lado));
      const w = der - izq;
      const h = inf - sup;
      if (der < 0 || izq > ancho || inf < 0 || sup > alto) continue;
      const r = tesela(l, zt, tx, ty);
      if (r && r.listo) {
        contexto.drawImage(r.img, izq, sup, w, h);
        continue;
      }
      if (!r || (r.error && Date.now() >= r.hasta)) pedirTesela(l, zt, tx, ty);
      // Mientras llega, lo que ya se tiene de un nivel más lejano, estirado.
      for (let d = 1; d <= 3 && zt - d >= 0; d++) {
        const padre = tesela(l, zt - d, tx >> d, ty >> d);
        if (padre && padre.listo) {
          const trozo = LADO / Math.pow(2, d);
          const sx = (tx - ((tx >> d) << d)) * trozo;
          const sy = (ty - ((ty >> d) << d)) * trozo;
          contexto.drawImage(padre.img, sx, sy, trozo, trozo, izq, sup, w, h);
          break;
        }
      }
    }
  }

  function dibujarContorno(l) {
    const f = l.ficha;
    contexto.save();
    contexto.strokeStyle = colores.contorno;
    contexto.lineWidth = 2;
    contexto.lineJoin = "round";
    contexto.setLineDash([]);
    contexto.beginPath();
    f.contorno_3857.forEach(function (p, i) {
      const x = aPantallaX(p[0]);
      const y = aPantallaY(p[1]);
      if (i === 0) contexto.moveTo(x, y);
      else contexto.lineTo(x, y);
    });
    contexto.closePath();
    contexto.stroke();
    // Las cuatro esquinas, cuadradas: el contorno no se apoya solo en el color.
    contexto.fillStyle = colores.contorno;
    f.esquinas_4326.forEach(function (p) {
      const x = aPantallaX(deLon(p[0]));
      const y = aPantallaY(deLat(p[1]));
      contexto.fillRect(x - 3, y - 3, 6, 6);
    });
    contexto.restore();
  }

  function dibujarEscala() {
    const lat = aLat(vista.cy);
    const metrosPorPixel = resolucion(vista.z) * Math.cos((lat * Math.PI) / 180);
    const objetivo = metrosPorPixel * 110;
    const potencia = Math.pow(10, Math.floor(Math.log10(objetivo)));
    let metros = potencia;
    for (const f of [1, 2, 5, 10]) if (f * potencia <= objetivo) metros = f * potencia;
    const largo = metros / metrosPorPixel;
    const etiqueta = metros >= 1000 ? formato(metros / 1000, 0) + " km" : formato(metros, 0) + " m";
    const x = 12;
    const y = alto - 30;
    contexto.save();
    contexto.fillStyle = colores.papel;
    contexto.fillRect(x - 6, y - 18, largo + 12, 36);
    contexto.strokeStyle = colores.escala;
    contexto.fillStyle = colores.escala;
    contexto.lineWidth = 2;
    contexto.beginPath();
    contexto.moveTo(x, y - 5);
    contexto.lineTo(x, y);
    contexto.lineTo(x + largo, y);
    contexto.lineTo(x + largo, y - 5);
    contexto.stroke();
    contexto.font = "12px system-ui, sans-serif";
    contexto.textBaseline = "top";
    contexto.fillText(etiqueta, x, y + 3);
    contexto.restore();
  }

  function dibujarMarca() {
    if (!marca) return;
    const x = aPantallaX(marca.mx);
    const y = aPantallaY(marca.my);
    contexto.save();
    contexto.strokeStyle = colores.marca;
    contexto.lineWidth = 2;
    contexto.beginPath();
    contexto.arc(x, y, 7, 0, Math.PI * 2);
    contexto.moveTo(x - 12, y);
    contexto.lineTo(x + 12, y);
    contexto.moveTo(x, y - 12);
    contexto.lineTo(x, y + 12);
    contexto.stroke();
    contexto.restore();
  }

  /* La línea del perfil y sus extremos A y B. Cada extremo lleva **forma y letra** (cuadrado «A»,
   * rombo «B»), no solo color, y un borde claro: el fondo es una imagen cualquiera. */
  function trazarPerfil() {
    contexto.beginPath();
    if (perfil.datos && perfil.datos.muestras.length) {
      perfil.datos.muestras.forEach(function (m, i) {
        const x = aPantallaX(deLon(m.lon));
        const y = aPantallaY(deLat(m.lat));
        if (i === 0) contexto.moveTo(x, y);
        else contexto.lineTo(x, y);
      });
    } else if (perfil.a && perfil.b) {
      contexto.moveTo(aPantallaX(perfil.a.mx), aPantallaY(perfil.a.my));
      contexto.lineTo(aPantallaX(perfil.b.mx), aPantallaY(perfil.b.my));
    }
  }

  function dibujarExtremo(punto, letra, rombo) {
    const x = aPantallaX(punto.mx);
    const y = aPantallaY(punto.my);
    contexto.save();
    contexto.translate(x, y);
    if (rombo) contexto.rotate(Math.PI / 4);
    contexto.fillStyle = colores.papel;
    contexto.fillRect(-8, -8, 16, 16);
    contexto.fillStyle = colores.contorno;
    contexto.fillRect(-5, -5, 10, 10);
    contexto.restore();
    contexto.save();
    contexto.font = "bold 12px system-ui, sans-serif";
    contexto.textBaseline = "middle";
    const ancha = contexto.measureText(letra).width + 8;
    contexto.fillStyle = colores.papel;
    contexto.fillRect(x + 12, y - 9, ancha, 18);
    contexto.fillStyle = colores.escala;
    contexto.fillText(letra, x + 16, y);
    contexto.restore();
  }

  function dibujarPerfil() {
    if (!capa.es_dem || !perfil.a) return;
    if (perfil.b) {
      contexto.save();
      contexto.lineJoin = "round";
      contexto.setLineDash([]);
      trazarPerfil();
      contexto.strokeStyle = colores.papel;
      contexto.lineWidth = 5;
      contexto.stroke();
      trazarPerfil();
      contexto.strokeStyle = colores.contorno;
      contexto.lineWidth = 2.5;
      contexto.setLineDash([7, 5]);
      contexto.stroke();
      contexto.restore();
    }
    dibujarExtremo(perfil.a, "A", false);
    if (perfil.b) dibujarExtremo(perfil.b, "B", true);
  }

  function dibujarCentro() {
    // Con el teclado no hay cursor: el centro es el «puntero», y se ve.
    if (cursor || document.activeElement !== lienzo) return;
    contexto.save();
    contexto.strokeStyle = colores.escala;
    contexto.lineWidth = 1.5;
    contexto.beginPath();
    contexto.moveTo(ancho / 2 - 10, alto / 2);
    contexto.lineTo(ancho / 2 + 10, alto / 2);
    contexto.moveTo(ancho / 2, alto / 2 - 10);
    contexto.lineTo(ancho / 2, alto / 2 + 10);
    contexto.stroke();
    contexto.restore();
  }

  /* ---- El vuelo: trayectoria, fotos y puntos de control ---- */

  /* Una marca por calidad, **de distinta forma además de distinto color** (círculo: PPK o fija ·
   * triángulo: flotante · cuadrado: simple · rombo: sin calidad informada). Las mismas de
   * `vuelo.js`. El control es una cruz dentro de un cuadrado: otra forma más. */
  function trazarMarca(tipo, px, py, r) {
    contexto.beginPath();
    if (tipo === "flotante") {
      contexto.moveTo(px, py - r * 1.25);
      contexto.lineTo(px + r * 1.15, py + r * 0.9);
      contexto.lineTo(px - r * 1.15, py + r * 0.9);
      contexto.closePath();
    } else if (tipo === "simple") {
      contexto.rect(px - r * 0.95, py - r * 0.95, r * 1.9, r * 1.9);
    } else if (tipo === "sin") {
      contexto.moveTo(px, py - r * 1.3);
      contexto.lineTo(px + r * 1.3, py);
      contexto.lineTo(px, py + r * 1.3);
      contexto.lineTo(px - r * 1.3, py);
      contexto.closePath();
    } else if (tipo === "control") {
      contexto.moveTo(px - r * 1.4, py);
      contexto.lineTo(px + r * 1.4, py);
      contexto.moveTo(px, py - r * 1.4);
      contexto.lineTo(px, py + r * 1.4);
    } else {
      contexto.arc(px, py, r, 0, 2 * Math.PI);
    }
  }

  function dibujarTrayectoria(l) {
    const puntos = vuelos.get(l.vuelo).datos.trayectoria.puntos;
    if (puntos.length < 2) return;
    contexto.save();
    contexto.lineJoin = "round";
    contexto.setLineDash([]);
    const trazo = function () {
      contexto.beginPath();
      puntos.forEach(function (p, i) {
        const x = aPantallaX(p[0]);
        const y = aPantallaY(p[1]);
        if (i === 0) contexto.moveTo(x, y);
        else contexto.lineTo(x, y);
      });
    };
    // Un borde claro debajo: la línea se lee sobre una imagen oscura y sobre una clara.
    trazo();
    contexto.strokeStyle = colores.papel;
    contexto.lineWidth = 5;
    contexto.stroke();
    trazo();
    contexto.strokeStyle = colores.trayectoria;
    contexto.lineWidth = 2.5;
    contexto.stroke();
    contexto.restore();
  }

  function dibujarMarcaDeFoto(clase, px, py, radio, elegida) {
    contexto.save();
    contexto.lineJoin = "round";
    trazarMarca(clase, px, py, radio);
    contexto.fillStyle = colores[clase];
    contexto.fill();
    contexto.strokeStyle = elegida ? colores.escala : colores.papel;
    contexto.lineWidth = elegida ? 3 : 1.5;
    contexto.stroke();
    contexto.restore();
  }

  function dibujarFotos(l) {
    const puntos = vuelos.get(l.vuelo).datos.fotos.puntos;
    const radio = puntos.length > 1500 ? 3 : 4;
    puntos.forEach(function (f, i) {
      const px = aPantallaX(f.mx);
      const py = aPantallaY(f.my);
      if (px < -10 || px > ancho + 10 || py < -10 || py > alto + 10) return;
      if (foto && foto.vuelo === l.vuelo && foto.i === i) return; // la elegida va encima de todas
      dibujarMarcaDeFoto(f.clase, px, py, radio, false);
    });
    if (foto && foto.vuelo === l.vuelo) {
      const f = puntos[foto.i];
      dibujarMarcaDeFoto(f.clase, aPantallaX(f.mx), aPantallaY(f.my), radio + 3, true);
    }
  }

  function dibujarControl(l) {
    const puntos = vuelos.get(l.vuelo).datos.control.puntos;
    puntos.forEach(function (c) {
      const px = aPantallaX(c.mx);
      const py = aPantallaY(c.my);
      if (px < -10 || px > ancho + 10 || py < -10 || py > alto + 10) return;
      contexto.save();
      // Un cuadrado claro con una cruz: la cruz es la forma, el cuadrado el borde que la despega
      // de la imagen.
      contexto.fillStyle = colores.papel;
      contexto.fillRect(px - 8, py - 8, 16, 16);
      contexto.strokeStyle = colores.control;
      contexto.lineWidth = 3;
      trazarMarca("control", px, py, 4.5);
      contexto.stroke();
      contexto.restore();
    });
  }

  function dibujarCapa(l) {
    if (!l.visible || !dibujable(l) || l.transparencia >= 100) return;
    contexto.save();
    contexto.globalAlpha = 1 - l.transparencia / 100;
    if (esRaster(l)) {
      dibujarTeselas(l);
      if (l.tipo === "raster") dibujarContorno(l);
    } else if (l.tipo === "vuelo-trayectoria") dibujarTrayectoria(l);
    else if (l.tipo === "vuelo-fotos") dibujarFotos(l);
    else if (l.tipo === "vuelo-control") dibujarControl(l);
    contexto.restore();
  }

  function dibujar() {
    if (!iniciado) return;
    contexto.setTransform(densidad, 0, 0, densidad, 0, 0);
    contexto.fillStyle = colores.fondo;
    contexto.fillRect(0, 0, ancho, alto);
    dibujarReticula();
    // De abajo (el final de la lista) a arriba (el principio): la primera capa de la lista queda
    // encima, sea imagen o vuelo. Las etiquetas de la retícula, después: debajo no se leerían.
    for (let i = pila.length - 1; i >= 0; i--) dibujarCapa(pila[i]);
    dibujarEtiquetas();
    dibujarPerfil();
    dibujarMarca();
    dibujarEscala();
    dibujarCentro();
    const nivel = $("mapa-nivel");
    if (nivel) nivel.textContent = formato(vista.z, 1);
  }

  function medir() {
    const caja = lienzo.getBoundingClientRect();
    densidad = Math.min(window.devicePixelRatio || 1, 2);
    ancho = Math.max(Math.round(caja.width), 1);
    alto = Math.max(Math.round(caja.height), 1);
    lienzo.width = Math.round(ancho * densidad);
    lienzo.height = Math.round(alto * densidad);
    if (iniciado && !tocada) encuadrar();
    else pedir();
  }

  /* ---- Lo que hay bajo el cursor ---- */

  function lecturaDe(mx, my) {
    return { mx: mx, my: my, lon: aLon(mx), lat: aLat(my) };
  }

  function actualizarLectura(sinPreguntar) {
    // Prioridad: el cursor, si lo hay; el punto que se eligió (clic, toque o Intro); el centro.
    let punto;
    let de;
    if (cursor) {
      punto = lecturaDe(aMetrosX(cursor.x), aMetrosY(cursor.y));
      de = "del cursor";
    } else if (marca) {
      punto = lecturaDe(marca.mx, marca.my);
      de = "del punto elegido";
    } else {
      punto = lecturaDe(vista.cx, vista.cy);
      de = "del centro del mapa";
    }
    $("mapa-origen").textContent = de;
    $("mapa-lon-lat").textContent =
      "latitud " + formato(punto.lat, 6) + "°, longitud " + formato(punto.lon, 6) + "°";
    clearTimeout(esperaPunto);
    // Sin imagen principal (un mapa solo de vuelos) no hay píxel que leer: queda la posición.
    if (sinPreguntar || !capa) return;
    esperaPunto = setTimeout(function () {
      preguntarPunto(punto, false);
    }, ESPERA_DEL_PUNTO_MS);
  }

  function preguntarPunto(punto, conValor) {
    if (controlPunto) controlPunto.abort();
    controlPunto = new AbortController();
    const url =
      capa.puntoUrl +
      "?ruta=" +
      encodeURIComponent(capa.ruta) +
      "&lon=" +
      punto.lon.toFixed(9) +
      "&lat=" +
      punto.lat.toFixed(9) +
      // Un DEM pide el valor siempre: la cota bajo el cursor es lo que se quiere ver al pasar.
      (conValor || capa.es_dem ? "&valor=1" : "");
    fetch(url, { credentials: "same-origin", signal: controlPunto.signal })
      .then(function (r) {
        return r.json().then(function (datos) {
          return { ok: r.ok, datos: datos };
        });
      })
      .then(function (respuesta) {
        if (!respuesta.ok) {
          $("mapa-en-su-sistema").textContent = respuesta.datos.mensaje || "No disponible.";
          return;
        }
        pintarPunto(respuesta.datos, conValor);
      })
      .catch(function (fallo) {
        if (fallo && fallo.name === "AbortError") return;
        $("mapa-en-su-sistema").textContent = "No se pudo leer el punto.";
      });
  }

  function pintarPunto(d, conValor) {
    const unidad = d.unidad ? " " + d.unidad : "";
    const nombre = d.epsg ? "EPSG:" + d.epsg : d.sistema;
    if (d.x === null || d.y === null) {
      $("mapa-en-su-sistema").textContent = "Fuera del alcance de " + nombre + ".";
    } else {
      $("mapa-en-su-sistema").textContent =
        "X " + formato(d.x, 2) + ", Y " + formato(d.y, 2) + unidad + "  (" + nombre + ")";
    }
    if (d.columna === null) {
      $("mapa-pixel").textContent = "—";
    } else if (!d.dentro) {
      $("mapa-pixel").textContent = "Fuera de la imagen";
    } else {
      $("mapa-pixel").textContent =
        "columna " + Math.floor(d.columna) + ", fila " + Math.floor(d.fila);
    }
    if (capa.es_dem) pintarCota(d);
    if (conValor && $("mapa-valor")) {
      let texto;
      if (!d.dentro) texto = "Ese punto cae fuera de la imagen.";
      else if (!d.valores.length) texto = "GDAL no devolvió ningún valor.";
      else
        texto =
          "Valores de las bandas en la columna " +
          Math.floor(d.columna) +
          ", fila " +
          Math.floor(d.fila) +
          ": " +
          d.valores
            .map(function (v) {
              return v === null ? "sin dato" : formato(v, Number.isInteger(v) ? 0 : 3);
            })
            .join(", ");
      $("mapa-valor").textContent = texto;
    }
  }

  function pedirValor(mx, my) {
    // Si la imagen principal no se pudo leer (lo dice su fila), no hay píxel que preguntar.
    if (!capa) return;
    marca = { mx: mx, my: my };
    $("mapa-valor").textContent = "Leyendo el valor del píxel…";
    // La lectura de coordenadas es la de este punto, y la pregunta al servidor va **con valor**:
    // si la hiciera también la espera de 150 ms, una cancelaría a la otra y se perdería el valor.
    actualizarLectura(true);
    preguntarPunto(lecturaDe(mx, my), true);
    pedir();
  }

  /* Un clic, un toque o Intro: con «Marcar perfil» activo pone un extremo; si no, lee el valor. */
  function accionDePunto(mx, my) {
    if (capa && capa.es_dem && perfil.activo) {
      marcarPerfil(mx, my);
      return;
    }
    // Un punto de foto cerca: se elige la foto. Si no, se lee el píxel de la imagen principal.
    const cercana = fotoCercana(aPantallaX(mx), aPantallaY(my));
    if (cercana) elegirFoto(cercana.vuelo, cercana.i);
    else if (capa) pedirValor(mx, my);
  }

  /* ---- Terreno: cómo se ve un DEM, su leyenda y la cota bajo el cursor ---- */

  const unidadV = () => (capa.unidad_vertical ? " " + capa.unidad_vertical : "");

  function pintarCota(d) {
    const caja = $("terreno-cota");
    if (!caja) return;
    let texto;
    if (d.columna === null || !d.dentro) texto = "Fuera del modelo.";
    else if (!d.valores.length || d.valores[0] === null) texto = "Sin dato en esta celda.";
    else {
      // Solo lo que el archivo declara: sin unidad no se dice «metros», y sin referencia no se dice
      // «sobre el nivel del mar».
      texto =
        formato(d.valores[0], 2) +
        (capa.unidad_vertical ? " " + capa.unidad_vertical : " (unidad no declarada)") +
        ", " +
        (capa.referencia_vertical
          ? "referencia vertical: " + capa.referencia_vertical
          : "referencia vertical no declarada");
    }
    caja.textContent = texto;
  }

  function elemento(etiqueta, clase, texto) {
    const e = document.createElement(etiqueta);
    if (clase) e.className = clase;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  function pintarLeyenda() {
    const caja = $("terreno-leyenda");
    if (!caja) return;
    caja.replaceChildren();
    const rango = capa.escala && capa.escala.length === 2 ? capa.escala : null;
    if (modo.nombre === "gris") {
      if (rango) {
        caja.appendChild(
          elemento(
            "p",
            "av-m-0",
            "Más oscuro es más bajo (" + formato(rango[0], 1) + unidadV() + "); más claro, más alto (" +
              formato(rango[1], 1) + unidadV() + "). Rango medido de forma aproximada."
          )
        );
      }
    } else if (modo.nombre === "sombra") {
      caja.appendChild(
        elemento(
          "p",
          "av-m-0",
          "Más claro es la ladera que mira al sol; más oscuro, la que queda en sombra. Sol a " +
            modo.az + "° de azimut y " + modo.alt + "° de altura, relieve exagerado " + modo.zf + " veces."
        )
      );
    } else if (capa.rampa && capa.rampa.length) {
      const primero = capa.rampa[0][0];
      const ultimo = capa.rampa[capa.rampa.length - 1][0];
      const rgb = (c) => "rgb(" + c[0] + ", " + c[1] + ", " + c[2] + ")";
      const paradas = capa.rampa.map(function (p) {
        return rgb(p[1]) + " " + (((p[0] - primero) / (ultimo - primero)) * 100).toFixed(1) + "%";
      });
      caja.appendChild(
        elemento(
          "p",
          "av-mb-1",
          "Cota" + (capa.unidad_vertical ? " (" + capa.unidad_vertical + ")" : " (unidad no declarada)")
        )
      );
      const barra = elemento("div", "terreno-rampa");
      barra.style.background = "linear-gradient(to right, " + paradas.join(", ") + ")";
      barra.setAttribute("aria-hidden", "true");
      caja.appendChild(barra);
      // La escala **escrita**: el color nunca va solo.
      const lista = elemento("ul", "terreno-rampa-paradas");
      capa.rampa.forEach(function (p) {
        const fila = elemento("li");
        const muestra = elemento("i", "terreno-muestra");
        muestra.style.background = rgb(p[1]);
        muestra.setAttribute("aria-hidden", "true");
        fila.appendChild(muestra);
        fila.appendChild(elemento("span", "", formato(p[0], 1) + unidadV()));
        lista.appendChild(fila);
      });
      caja.appendChild(lista);
      caja.appendChild(
        elemento("p", "tenue av-fs-xs av-mt-2 av-mb-0", "Rango medido de forma aproximada: fuera de él, el color de la punta.")
      );
    }
  }

  /* Cambió cómo se ve la capa principal (el modo de terreno): sus teselas ya no valen. Las de las
   * demás capas no cambian. */
  function reiniciarTeselas() {
    for (let i = cola.length - 1; i >= 0; i--) {
      if (cola[i].capa === principal) cola.splice(i, 1);
    }
    principal.imagenes.forEach(function (r) {
      if (r.img && r.img.close) r.img.close();
    });
    principal.imagenes.clear();
    falladas = 0;
    avisados.clear();
    if (claveDelAviso.indexOf("tesela:") === 0) quitarAviso(claveDelAviso);
    estado();
    pedir();
  }

  function leerModo() {
    const marcado = document.querySelector('input[name="terreno-modo"]:checked');
    modo = {
      nombre: marcado ? marcado.value : "gris",
      az: $("terreno-az").value,
      alt: $("terreno-alt").value,
      zf: $("terreno-zf").value,
    };
    $("terreno-sol").hidden = modo.nombre !== "sombra";
    pintarLeyenda();
  }

  function iniciarTerreno() {
    if (!capa.es_dem || !$("terreno")) return;
    leerModo();
    document.querySelectorAll('input[name="terreno-modo"]').forEach(function (e) {
      e.addEventListener("change", function () {
        leerModo();
        reiniciarTeselas();
      });
    });
    ["terreno-az", "terreno-alt", "terreno-zf"].forEach(function (id) {
      $(id).addEventListener("change", function () {
        leerModo();
        if (modo.nombre === "sombra") reiniciarTeselas();
      });
    });
  }

  /* ---- Perfil entre dos puntos ---- */

  // El espacio de nombres de SVG sale de un elemento `<svg>` de la plantilla, no de una dirección
  // escrita aquí: este archivo no nombra ningún origen.
  const SVG = $("perfil-ns") ? $("perfil-ns").namespaceURI : null;

  function nodo(etiqueta, atributos, texto) {
    const e = document.createElementNS(SVG, etiqueta);
    Object.keys(atributos || {}).forEach(function (k) {
      e.setAttribute(k, atributos[k]);
    });
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  const decimalesDe = (paso) => Math.max(0, -Math.floor(Math.log10(paso) + 1e-9));

  function textoDeCota(m) {
    return m.cota === null ? "sin dato" : formato(m.cota, 2);
  }

  function dibujarGrafico(datos) {
    const caja = $("perfil-grafico");
    caja.replaceChildren();
    const W = Math.max(caja.clientWidth, 260);
    const H = 270;
    const izq = 62;
    const der = 14;
    const arriba = 26;
    const abajo = 56;
    const ancho = W - izq - der;
    const alto = H - arriba - abajo;
    const valida = datos.muestras.filter((m) => m.cota !== null);
    const km = datos.longitud_m >= 2000;
    const divisor = km ? 1000 : 1;

    const svg = nodo("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-labelledby": "perfil-svg-titulo perfil-svg-desc" });
    svg.appendChild(nodo("title", { id: "perfil-svg-titulo" }, "Perfil de elevación entre A y B"));
    svg.appendChild(
      nodo(
        "desc",
        { id: "perfil-svg-desc" },
        datos.n + " muestras en " + formato(datos.longitud_m, 1) + " m. " +
          (valida.length
            ? "Cota de " + formato(datos.minimo, 2) + " a " + formato(datos.maximo, 2) + unidadV() + "."
            : "Ninguna muestra tiene cota.") +
          " Los valores están en la tabla de abajo."
      )
    );

    const minimo = valida.length ? datos.minimo : 0;
    const maximo = valida.length ? datos.maximo : 1;
    const holgura = (maximo - minimo) * 0.08 || 1;
    const y0 = minimo - holgura;
    const y1 = maximo + holgura;
    const aX = (d) => izq + (d / datos.longitud_m) * ancho;
    const aY = (v) => arriba + (1 - (v - y0) / (y1 - y0)) * alto;

    // Rejilla y marcas de los dos ejes.
    const pasoX = pasoRedondo(datos.longitud_m / divisor) * divisor;
    const decX = decimalesDe(pasoX / divisor);
    for (let d = 0; d <= datos.longitud_m + 1e-9; d += pasoX) {
      const x = aX(d);
      svg.appendChild(nodo("line", { class: "perfil-rejilla", x1: x, x2: x, y1: arriba, y2: arriba + alto }));
      svg.appendChild(nodo("text", { class: "perfil-texto", x: x, y: arriba + alto + 14, "text-anchor": "middle" }, formato(d / divisor, decX)));
    }
    const pasoY = pasoRedondo(y1 - y0);
    const decY = decimalesDe(pasoY);
    for (let v = Math.ceil(y0 / pasoY) * pasoY; v <= y1; v += pasoY) {
      const y = aY(v);
      svg.appendChild(nodo("line", { class: "perfil-rejilla", x1: izq, x2: izq + ancho, y1: y, y2: y }));
      svg.appendChild(nodo("text", { class: "perfil-texto", x: izq - 6, y: y + 4, "text-anchor": "end" }, formato(v, decY)));
    }
    svg.appendChild(nodo("line", { class: "perfil-eje", x1: izq, x2: izq, y1: arriba, y2: arriba + alto }));
    svg.appendChild(nodo("line", { class: "perfil-eje", x1: izq, x2: izq + ancho, y1: arriba + alto, y2: arriba + alto }));
    svg.appendChild(
      nodo("text", { class: "perfil-texto", x: izq + ancho / 2, y: H - 22, "text-anchor": "middle" },
        "Distancia desde A (" + (km ? "km" : "m") + ")")
    );
    const ejeY = nodo(
      "text",
      { class: "perfil-texto", x: 0, y: 0, "text-anchor": "middle", transform: "translate(13 " + (arriba + alto / 2) + ") rotate(-90)" },
      "Cota (" + (capa.unidad_vertical || "unidad no declarada") + ")"
    );
    svg.appendChild(ejeY);
    if (valida.length < datos.muestras.length) {
      svg.appendChild(
        nodo("text", { class: "perfil-texto", x: izq, y: H - 6 },
          "Las barras en la base marcan huecos: sin dato o fuera del modelo.")
      );
    }
    svg.appendChild(nodo("text", { class: "perfil-rotulo", x: izq, y: 14 }, "A"));
    svg.appendChild(nodo("text", { class: "perfil-rotulo", x: izq + ancho, y: 14, "text-anchor": "end" }, "B"));

    // La línea, **cortada** en cada hueco: lo que no se midió no se une ni se interpola.
    let trazo = "";
    let tramo = 0;
    const cerrar = function (ultima) {
      if (tramo === 1) svg.appendChild(nodo("circle", { class: "perfil-punto", cx: aX(ultima.d), cy: aY(ultima.cota), r: 3 }));
      tramo = 0;
    };
    let previa = null;
    datos.muestras.forEach(function (m) {
      if (m.cota === null) {
        if (previa) cerrar(previa);
        previa = null;
        trazo += " ";
        // La marca del hueco es una barra en la base: forma, no solo color.
        svg.appendChild(nodo("line", { class: "perfil-hueco", x1: aX(m.d), x2: aX(m.d), y1: arriba + alto - 10, y2: arriba + alto }));
        return;
      }
      trazo += (tramo === 0 ? " M " : " L ") + aX(m.d).toFixed(1) + " " + aY(m.cota).toFixed(1);
      tramo += 1;
      previa = m;
    });
    if (previa) cerrar(previa);
    if (valida.length) svg.appendChild(nodo("path", { class: "perfil-linea", d: trazo.trim() }));
    caja.appendChild(svg);
  }

  function llenarTabla(datos) {
    const cuerpo = $("perfil-filas");
    cuerpo.replaceChildren();
    $("perfil-col-cota").textContent = "Cota (" + (capa.unidad_vertical || "unidad no declarada") + ")";
    datos.muestras.forEach(function (m) {
      const fila = elemento("tr", "cifra");
      fila.appendChild(elemento("td", "", String(m.i + 1)));
      fila.appendChild(elemento("td", "", formato(m.d, 1)));
      fila.appendChild(elemento("td", "", formato(m.lat, 6) + "°"));
      fila.appendChild(elemento("td", "", formato(m.lon, 6) + "°"));
      fila.appendChild(elemento("td", "", m.dentro ? textoDeCota(m) : "fuera del modelo"));
      cuerpo.appendChild(fila);
    });
    $("perfil-tabla").hidden = false;
  }

  function urlDelPerfil(formatoSalida) {
    const a = perfil.a;
    const b = perfil.b;
    return (
      capa.perfilUrl +
      "?ruta=" + encodeURIComponent(capa.ruta) +
      "&lon1=" + aLon(a.mx).toFixed(9) + "&lat1=" + aLat(a.my).toFixed(9) +
      "&lon2=" + aLon(b.mx).toFixed(9) + "&lat2=" + aLat(b.my).toFixed(9) +
      "&n=" + encodeURIComponent($("perfil-n").value) +
      (formatoSalida ? "&formato=" + formatoSalida : "")
    );
  }

  function decirDelPerfil(texto) {
    $("perfil-estado").textContent = texto;
  }

  function limpiarResultadoDelPerfil() {
    perfil.datos = null;
    $("perfil-grafico").replaceChildren();
    $("perfil-tabla").hidden = true;
    const enlace = $("perfil-csv");
    enlace.setAttribute("aria-disabled", "true");
    enlace.setAttribute("tabindex", "-1");
    enlace.removeAttribute("href");
  }

  function pedirPerfil() {
    if (perfil.control) perfil.control.abort();
    perfil.control = new AbortController();
    decirDelPerfil("Calculando el perfil…");
    fetch(urlDelPerfil(""), { credentials: "same-origin", signal: perfil.control.signal })
      .then(function (r) {
        return r.json().then(function (datos) {
          return { ok: r.ok, datos: datos };
        });
      })
      .then(function (respuesta) {
        if (!respuesta.ok) {
          limpiarResultadoDelPerfil();
          decirDelPerfil(respuesta.datos.mensaje || "No se pudo calcular el perfil.");
          pedir();
          return;
        }
        const d = respuesta.datos;
        perfil.datos = d;
        dibujarGrafico(d);
        llenarTabla(d);
        const enlace = $("perfil-csv");
        enlace.href = urlDelPerfil("csv");
        enlace.removeAttribute("aria-disabled");
        enlace.removeAttribute("tabindex");
        let texto =
          "Perfil de " + formato(d.longitud_m, 1) + " m en " + d.n + " muestras" +
          (d.minimo === null
            ? ", sin ninguna cota."
            : ": cota de " + formato(d.minimo, 2) + " a " + formato(d.maximo, 2) + unidadV() + ".");
        if (d.sin_dato) texto += " " + d.sin_dato + " sin dato.";
        if (d.fuera) texto += " " + d.fuera + " fuera del modelo.";
        decirDelPerfil(texto);
        pedir();
      })
      .catch(function (fallo) {
        if (fallo && fallo.name === "AbortError") return;
        limpiarResultadoDelPerfil();
        decirDelPerfil("No se pudo calcular el perfil. Compruebe la conexión con el servidor.");
      });
  }

  function marcarPerfil(mx, my) {
    if (perfil.a && perfil.b) {
      // Un tercer punto empieza otro perfil.
      perfil.a = null;
      perfil.b = null;
      limpiarResultadoDelPerfil();
    }
    if (!perfil.a) {
      perfil.a = { mx: mx, my: my };
      decirDelPerfil("Punto A marcado. Marque el punto B.");
      $("perfil-quitar").disabled = false;
    } else {
      perfil.b = { mx: mx, my: my };
      pedirPerfil();
    }
    pedir();
  }

  function iniciarPerfil() {
    if (!capa.es_dem || !$("perfil")) return;
    $("perfil-marcar").addEventListener("click", function () {
      perfil.activo = !perfil.activo;
      this.setAttribute("aria-pressed", perfil.activo ? "true" : "false");
      // El estado se **dice** en el botón (no solo se pinta): «Dejar de marcar» mientras está activo.
      this.textContent = perfil.activo ? "Dejar de marcar" : "Marcar perfil";
      if (perfil.activo && !perfil.a) decirDelPerfil("Marque el punto A: pinche, toque o pulse Intro en el centro del mapa.");
      else if (!perfil.activo && !perfil.a) decirDelPerfil("Todavía no hay un perfil: marque los puntos A y B.");
    });
    $("perfil-quitar").addEventListener("click", function () {
      perfil.a = null;
      perfil.b = null;
      if (perfil.control) perfil.control.abort();
      limpiarResultadoDelPerfil();
      decirDelPerfil(
        perfil.activo
          ? "Perfil quitado. Marque el punto A: pinche, toque o pulse Intro en el centro del mapa."
          : "Perfil quitado. Active «Marcar perfil» para empezar otro."
      );
      this.disabled = true;
      pedir();
    });
    $("perfil-n").addEventListener("change", function () {
      if (perfil.a && perfil.b) pedirPerfil();
    });
    // El gráfico se dibuja a la medida del ancho de la tarjeta: al cambiarlo, se rehace.
    let anchoAnterior = $("perfil-grafico").clientWidth;
    new ResizeObserver(function () {
      const ahora = $("perfil-grafico").clientWidth;
      if (perfil.datos && Math.abs(ahora - anchoAnterior) > 2) dibujarGrafico(perfil.datos);
      anchoAnterior = ahora;
    }).observe($("perfil-grafico"));
  }

  /* ---- Zoom y paneo ---- */

  function acercar(delta, px, py) {
    tocada = true;
    const antesX = aMetrosX(px);
    const antesY = aMetrosY(py);
    vista.z += delta;
    const l = limitesDeZoom();
    vista.z = Math.min(Math.max(vista.z, l.minimo), l.maximo);
    // Lo que estaba bajo el cursor sigue bajo el cursor.
    vista.cx = antesX - (px - ancho / 2) * resolucion(vista.z);
    vista.cy = antesY + (py - alto / 2) * resolucion(vista.z);
    limitar();
    pedir();
    actualizarLectura();
  }

  function mover(dx, dy) {
    tocada = true;
    const r = resolucion(vista.z);
    vista.cx -= dx * r;
    vista.cy += dy * r;
    limitar();
    pedir();
    actualizarLectura();
  }

  function posicion(evento) {
    const caja = lienzo.getBoundingClientRect();
    return { x: evento.clientX - caja.left, y: evento.clientY - caja.top };
  }

  lienzo.addEventListener("pointerdown", function (evento) {
    try {
      lienzo.setPointerCapture(evento.pointerId);
    } catch (fallo) {
      // Sin captura el arrastre sigue funcionando mientras el puntero esté sobre el mapa.
    }
    const p = posicion(evento);
    punteros.set(evento.pointerId, p);
    arrastre = { x: p.x, y: p.y, movido: false };
    lienzo.focus({ preventScroll: true });
  });

  lienzo.addEventListener("pointermove", function (evento) {
    const p = posicion(evento);
    if (punteros.has(evento.pointerId)) {
      const antes = punteros.get(evento.pointerId);
      punteros.set(evento.pointerId, p);
      if (punteros.size === 2) {
        // Pellizco: el cambio de distancia entre los dos dedos acerca o aleja.
        const otros = Array.from(punteros.entries()).filter((e) => e[0] !== evento.pointerId)[0][1];
        const antesD = Math.hypot(antes.x - otros.x, antes.y - otros.y);
        const ahoraD = Math.hypot(p.x - otros.x, p.y - otros.y);
        if (antesD > 0 && ahoraD > 0) {
          acercar(Math.log2(ahoraD / antesD), (p.x + otros.x) / 2, (p.y + otros.y) / 2);
        }
        if (arrastre) arrastre.movido = true;
      } else if (arrastre) {
        if (Math.abs(p.x - arrastre.x) + Math.abs(p.y - arrastre.y) > 4) arrastre.movido = true;
        if (arrastre.movido) mover(p.x - antes.x, p.y - antes.y);
      }
    }
    if (evento.pointerType !== "touch") {
      cursor = p;
      actualizarLectura();
    }
  });

  function soltar(evento) {
    const p = posicion(evento);
    const eraClic = arrastre && !arrastre.movido && punteros.size === 1;
    punteros.delete(evento.pointerId);
    if (eraClic && evento.type === "pointerup") accionDePunto(aMetrosX(p.x), aMetrosY(p.y));
    if (!punteros.size) arrastre = null;
  }
  lienzo.addEventListener("pointerup", soltar);
  lienzo.addEventListener("pointercancel", soltar);
  lienzo.addEventListener("pointerleave", function (evento) {
    if (evento.pointerType !== "touch") {
      cursor = null;
      actualizarLectura();
    }
  });

  lienzo.addEventListener(
    "wheel",
    function (evento) {
      evento.preventDefault();
      const p = posicion(evento);
      const paso = Math.max(-0.5, Math.min(0.5, -evento.deltaY * 0.0015));
      acercar(paso, p.x, p.y);
    },
    { passive: false }
  );

  lienzo.addEventListener("dblclick", function (evento) {
    const p = posicion(evento);
    acercar(1, p.x, p.y);
  });

  lienzo.addEventListener("keydown", function (evento) {
    const paso = evento.shiftKey ? 320 : 80;
    switch (evento.key) {
      case "ArrowLeft":
        mover(paso, 0);
        break;
      case "ArrowRight":
        mover(-paso, 0);
        break;
      case "ArrowUp":
        mover(0, paso);
        break;
      case "ArrowDown":
        mover(0, -paso);
        break;
      case "+":
      case "=":
        acercar(1, ancho / 2, alto / 2);
        break;
      case "-":
      case "_":
        acercar(-1, ancho / 2, alto / 2);
        break;
      case "0":
      case "Home":
        tocada = false;
        encuadrar();
        break;
      case "Enter":
      case " ":
        accionDePunto(vista.cx, vista.cy);
        break;
      case "[":
        moverFoto(-1);
        break;
      case "]":
        moverFoto(1);
        break;
      case "Escape":
        if (!foto) return;
        elegirFoto(null, -1);
        break;
      default:
        return;
    }
    evento.preventDefault();
  });

  lienzo.addEventListener("focus", pedir);
  lienzo.addEventListener("blur", pedir);

  $("mapa-ajustar").addEventListener("click", function () {
    tocada = false;
    encuadrar();
  });
  $("mapa-menos").addEventListener("click", function () {
    acercar(-1, ancho / 2, alto / 2);
  });
  $("mapa-mas").addEventListener("click", function () {
    acercar(1, ancho / 2, alto / 2);
  });
  if ($("mapa-valor-centro")) {
    $("mapa-valor-centro").addEventListener("click", function () {
      pedirValor(vista.cx, vista.cy);
    });
  }

  /* ---- Las fotos de un vuelo: elegir una, su miniatura y su ficha ---- */

  const RADIO_DE_PUNTERIA = 12;

  // Las capas de fotos que se ven ahora, de arriba abajo.
  function fotosVisibles() {
    return pila.filter(function (l) {
      return l.tipo === "vuelo-fotos" && l.visible && dibujable(l) && l.transparencia < 100;
    });
  }

  function fotoCercana(px, py) {
    let mejor = null;
    let distancia = RADIO_DE_PUNTERIA * RADIO_DE_PUNTERIA;
    fotosVisibles().forEach(function (l) {
      vuelos.get(l.vuelo).datos.fotos.puntos.forEach(function (f, i) {
        const dx = aPantallaX(f.mx) - px;
        const dy = aPantallaY(f.my) - py;
        const d2 = dx * dx + dy * dy;
        if (d2 < distancia) {
          distancia = d2;
          mejor = { vuelo: l.vuelo, i: i };
        }
      });
    });
    return mejor;
  }

  function elegirFoto(idDelVuelo, i) {
    foto = i < 0 || idDelVuelo === null ? null : { vuelo: idDelVuelo, i: i };
    mostrarFoto();
    pedir();
  }

  function moverFoto(delta) {
    const capasDeFotos = fotosVisibles();
    if (!capasDeFotos.length) return;
    const idDelVuelo = foto ? foto.vuelo : capasDeFotos[0].vuelo;
    const total = vuelos.get(idDelVuelo).datos.fotos.puntos.length;
    let i;
    if (foto && foto.vuelo === idDelVuelo) i = (foto.i + delta + total) % total;
    else i = delta > 0 ? 0 : total - 1;
    elegirFoto(idDelVuelo, i);
    // Si el punto quedó fuera de la vista, se lleva al centro.
    const f = vuelos.get(idDelVuelo).datos.fotos.puntos[i];
    const px = aPantallaX(f.mx);
    const py = aPantallaY(f.my);
    if (px < 20 || px > ancho - 20 || py < 20 || py > alto - 20) {
      tocada = true;
      vista.cx = f.mx;
      vista.cy = f.my;
      limitar();
      pedir();
      actualizarLectura();
    }
  }

  function actualizarNavegacionDeFotos() {
    const anterior = $("vuelo-foto-anterior");
    if (!anterior) return;
    const hay = fotosVisibles().length > 0;
    anterior.disabled = !hay;
    $("vuelo-foto-siguiente").disabled = !hay;
  }

  function filaDeFicha(titulo, valor) {
    return [elemento("dt", "", titulo), elemento("dd", "", valor)];
  }

  let fichaPedida = 0;

  function mostrarFoto() {
    const detalle = $("vuelo-foto-detalle");
    if (!detalle) return;
    const peticion = ++fichaPedida;
    $("vuelo-exif-grupos").replaceChildren();
    if (!foto) {
      detalle.hidden = true;
      $("vuelo-foto-vacia").hidden = false;
      $("vuelo-foto-quitar").hidden = true;
      return;
    }
    const v = vuelos.get(foto.vuelo);
    const f = v.datos.fotos.puntos[foto.i];
    detalle.hidden = false;
    $("vuelo-foto-vacia").hidden = true;
    $("vuelo-foto-quitar").hidden = false;
    $("vuelo-foto-nombre").textContent = f.nombre || "Disparo " + f.n;

    const datos = $("vuelo-foto-datos");
    datos.replaceChildren();
    [
      ["Disparo", String(f.n)],
      ["Calidad", f.calidad || "No informada"],
      ["Latitud", formato(f.lat, 9) + "°"],
      ["Longitud", formato(f.lon, 9) + "°"],
    ].forEach(function (par) {
      filaDeFicha(par[0], par[1]).forEach(function (nodoDeFila) {
        datos.appendChild(nodoDeFila);
      });
    });

    // La miniatura y la ficha las sirven las vistas del vuelo (con su comprobación de dueño y de
    // carpeta): aquí solo se arma la dirección. El número es el del disparo, un entero.
    const imagen = $("vuelo-foto-imagen");
    const sinImagen = $("vuelo-foto-sin-imagen");
    const urls = v.datos.urls;
    if (f.miniatura && v.datos.con_miniaturas && Number.isInteger(f.n)) {
      imagen.alt = "Foto " + (f.nombre || f.n);
      imagen.src = urls.miniatura.replace("{n}", String(f.n));
      imagen.hidden = false;
      sinImagen.textContent = "";
    } else {
      imagen.hidden = true;
      sinImagen.textContent = v.datos.con_miniaturas
        ? "Esta foto no está en la carpeta elegida."
        : "No se eligió la carpeta de fotos: no hay miniatura.";
    }

    const fuente = $("vuelo-exif-fuente");
    if (!Number.isInteger(f.n)) {
      fuente.textContent = "Esta foto no trae número de disparo: no hay ficha.";
      return;
    }
    fuente.textContent = "Leyendo la ficha…";
    fetch(urls.ficha.replace("{n}", String(f.n)), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (json) {
        if (peticion !== fichaPedida) return; // se eligió otra foto mientras tanto
        fuente.textContent = json.fuente_texto;
        const grupos = $("vuelo-exif-grupos");
        json.grupos.forEach(function (g) {
          const grupo = elemento("details", "visor-exif-grupo");
          grupo.open = true;
          grupo.appendChild(elemento("summary", "", g.titulo));
          const lista = elemento("dl", "visor-ficha");
          g.filas.forEach(function (par) {
            filaDeFicha(par.rotulo, par.valor).forEach(function (nodoDeFila) {
              lista.appendChild(nodoDeFila);
            });
          });
          grupo.appendChild(lista);
          grupos.appendChild(grupo);
        });
      })
      .catch(function (fallo) {
        if (peticion !== fichaPedida) return;
        fuente.textContent =
          fallo.message === "HTTP 404"
            ? "Esta foto no tiene ficha: no está en la carpeta elegida y no hay posiciones de Trimble que la describan."
            : "No se pudo leer la ficha (" + fallo.message + ").";
      });
  }

  if ($("vuelo-foto-imagen")) {
    $("vuelo-foto-imagen").addEventListener("error", function () {
      this.hidden = true;
      $("vuelo-foto-sin-imagen").textContent = "No se pudo abrir la foto.";
    });
    $("vuelo-foto-anterior").addEventListener("click", function () {
      moverFoto(-1);
    });
    $("vuelo-foto-siguiente").addEventListener("click", function () {
      moverFoto(1);
    });
    $("vuelo-foto-quitar").addEventListener("click", function () {
      elegirFoto(null, -1);
    });
  }

  /* ---- La lista de capas: orden, visibilidad y transparencia ---- */

  const ROTULOS = {
    raster: "Imagen",
    fondo: "Mapa de fondo",
    "vuelo-trayectoria": "Trayectoria del vuelo",
    "vuelo-fotos": "Fotos del vuelo",
    "vuelo-control": "Puntos de control del vuelo",
  };

  function decirDeLasCapas(texto) {
    const caja = $("capas-aviso");
    if (caja) caja.textContent = texto;
  }

  /* `e=id:transparencia:visible,…`, de arriba abajo. Es lo mismo que lee y normaliza el servidor
   * (`apps/visor/capas.py`): el estado de las capas es un dato de la dirección, no de este archivo. */
  function textoDeEstado() {
    return pila
      .map(function (l) {
        return l.id + ":" + l.transparencia + ":" + (l.visible ? 1 : 0);
      })
      .join(",");
  }

  function guardarEstado() {
    const texto = textoDeEstado();
    const campo = $("capas-estado");
    if (campo) campo.value = texto;
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("e", texto);
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (fallo) {
      // Sin historial el mapa funciona igual; solo no se puede volver a abrir con el enlace.
    }
  }

  function quitarCapa(l) {
    const f = l.fuente;
    if (!f) return;
    try {
      const url = new URL(window.location.href);
      if (f.poner !== undefined) {
        url.searchParams.set(f.param, f.poner);
      } else {
        const quedan = url.searchParams.getAll(f.param).filter(function (v) {
          return v !== f.valor;
        });
        url.searchParams.delete(f.param);
        quedan.forEach(function (v) {
          url.searchParams.append(f.param, v);
        });
      }
      // Lo que se queda conserva su orden y su transparencia; lo que se va, sale del estado.
      const se_van = pila.filter(function (otra) {
        return otra === l || (l.vuelo && otra.vuelo === l.vuelo);
      });
      url.searchParams.set(
        "e",
        pila
          .filter(function (otra) {
            return se_van.indexOf(otra) < 0;
          })
          .map(function (otra) {
            return otra.id + ":" + otra.transparencia + ":" + (otra.visible ? 1 : 0);
          })
          .join(",")
      );
      window.location.assign(url.pathname + url.search);
    } catch (fallo) {
      decirDeLasCapas("No se pudo quitar la capa.");
    }
  }

  function boton(texto, nombreAccesible, accion, desactivado) {
    const b = elemento("button", "boton boton-suave boton-pequeno capa-boton", texto);
    b.type = "button";
    b.setAttribute("aria-label", nombreAccesible);
    b.dataset.accion = texto;
    b.disabled = !!desactivado;
    b.addEventListener("click", accion);
    return b;
  }

  function moverCapa(id, delta) {
    const i = pila.findIndex(function (l) {
      return l.id === id;
    });
    const j = i + delta;
    if (i < 0 || j < 0 || j >= pila.length) return;
    const l = pila[i];
    pila.splice(i, 1);
    pila.splice(j, 0, l);
    pintarCapas();
    // El foco se queda en el mismo botón; si ya no se puede (llegó al borde), en el contrario.
    const fila = $("capas-lista").querySelector('[data-id="' + id + '"]');
    if (fila) {
      const preferido = fila.querySelector('[data-accion="' + (delta < 0 ? "Subir" : "Bajar") + '"]');
      const otro = fila.querySelector('[data-accion="' + (delta < 0 ? "Bajar" : "Subir") + '"]');
      if (preferido && !preferido.disabled) preferido.focus();
      else if (otro) otro.focus();
    }
    decirDeLasCapas("«" + l.nombre + "» es ahora la capa " + (j + 1) + " de " + pila.length + ".");
    guardarEstado();
    pedir();
  }

  function filaDeCapa(l, posicion) {
    const lista = dibujable(l);
    const fila = elemento("li", "capa-fila" + (lista ? "" : " capa-sin-dibujar"));
    fila.dataset.id = l.id;

    const cabeza = elemento("div", "capa-cabeza");
    const etiqueta = elemento("label", "capa-visible");
    const casilla = document.createElement("input");
    casilla.type = "checkbox";
    casilla.checked = l.visible && lista;
    casilla.disabled = !lista;
    casilla.addEventListener("change", function () {
      l.visible = casilla.checked;
      guardarEstado();
      actualizarNavegacionDeFotos();
      pedir();
    });
    etiqueta.appendChild(casilla);
    etiqueta.appendChild(elemento("span", "capa-nombre", l.nombre));
    cabeza.appendChild(etiqueta);
    fila.appendChild(cabeza);

    fila.appendChild(elemento("p", "capa-tipo", ROTULOS[l.tipo]));

    const acciones = elemento("div", "capa-orden");
    acciones.appendChild(
      boton("Subir", "Subir «" + l.nombre + "»", function () { moverCapa(l.id, -1); }, posicion === 0)
    );
    acciones.appendChild(
      boton("Bajar", "Bajar «" + l.nombre + "»", function () { moverCapa(l.id, 1); }, posicion === pila.length - 1)
    );
    if (l.fuente) {
      acciones.appendChild(
        boton(
          "Quitar",
          l.vuelo ? "Quitar el vuelo entero («" + l.nombre + "» y sus otras capas)" : "Quitar «" + l.nombre + "»",
          function () { quitarCapa(l); },
          false
        )
      );
    }
    fila.appendChild(acciones);

    if (lista) {
      const idRango = "capa-transparencia-" + l.id;
      const bloque = elemento("div", "capa-transparencia");
      const rotulo = elemento("label", "terreno-campo-rotulo", "Transparencia");
      rotulo.htmlFor = idRango;
      const rango = document.createElement("input");
      rango.type = "range";
      rango.id = idRango;
      rango.min = "0";
      rango.max = "100";
      rango.step = "5";
      rango.value = String(l.transparencia);
      rango.className = "capa-rango";
      rango.setAttribute("aria-label", "Transparencia de «" + l.nombre + "»");
      const salida = elemento("output", "capa-valor cifra", l.transparencia + " %");
      salida.htmlFor = idRango;
      // Sin volver a pintar la lista: se destruiría el control mientras se arrastra.
      rango.addEventListener("input", function () {
        l.transparencia = parseInt(rango.value, 10) || 0;
        salida.textContent = l.transparencia + " %";
        rango.setAttribute("aria-valuetext", l.transparencia + " % de transparencia");
        guardarEstado();
        actualizarNavegacionDeFotos();
        pedir();
      });
      bloque.appendChild(rotulo);
      bloque.appendChild(rango);
      bloque.appendChild(salida);
      fila.appendChild(bloque);
    }

    // Lo que la capa dice de sí: cuántos puntos tiene, o por qué no se dibuja. Siempre escrito.
    const nota = notaDeCapa(l);
    if (nota) fila.appendChild(elemento("p", "capa-nota" + (lista ? "" : " capa-nota-aviso"), nota));
    return fila;
  }

  function notaDeCapa(l) {
    if (l.estado === "cargando") return "Cargando…";
    if (l.estado !== "lista") return "No se dibuja: " + l.mensaje;
    const v = esVuelo(l) ? vuelos.get(l.vuelo).datos : null;
    if (l.tipo === "vuelo-fotos") {
      const n = v.fotos.puntos.length;
      const sin = v.fotos.sin_posicion;
      return n + (n === 1 ? " foto" : " fotos") + (sin ? "; " + sin + " sin posición, que no se dibujan" : "");
    }
    if (l.tipo === "vuelo-trayectoria") return v.trayectoria.puntos.length + " puntos del recorrido";
    if (l.tipo === "vuelo-control") return v.control.puntos.length + " puntos de control";
    if (l.tipo === "raster" && l.ficha.es_dem && !l.principal) {
      return "Modelo de elevación: se ve en grises (el sombreado es de la imagen principal).";
    }
    return "";
  }

  function pintarCapas() {
    const lista = $("capas-lista");
    if (!lista) return;
    const activo = document.activeElement;
    const filaActiva = activo && activo.closest ? activo.closest("#capas-lista > li") : null;
    const idActivo = filaActiva ? filaActiva.dataset.id : "";
    lista.replaceChildren();
    pila.forEach(function (l, i) {
      lista.appendChild(filaDeCapa(l, i));
    });
    // Si el foco estaba en la lista y se perdió al repintar, vuelve a la misma capa.
    if (idActivo && document.activeElement === document.body) {
      const fila = lista.querySelector('[data-id="' + idActivo + '"]');
      const control = fila ? fila.querySelector("input, button") : null;
      if (control) control.focus();
    }
  }

  /* ---- Carga de lo que cada capa necesita ---- */

  function leerDeclaradas() {
    try {
      const crudo = JSON.parse(raiz.dataset.capas || "[]");
      return Array.isArray(crudo) ? crudo : [];
    } catch (fallo) {
      return [];
    }
  }

  function crearCapa(d) {
    return {
      id: String(d.id),
      tipo: String(d.tipo),
      nombre: String(d.nombre || ""),
      token: String(d.token || ""),
      vuelo: String(d.vuelo || ""),
      datos: String(d.datos || ""),
      fuente: d.fuente || null,
      principal: !!d.principal,
      visible: d.visible !== false,
      transparencia: Math.max(0, Math.min(100, parseInt(d.transparencia, 10) || 0)),
      estado: "cargando",
      mensaje: "",
      ficha: null,
      imagenes: new Map(),
    };
  }

  function leerJson(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(
      function (r) {
        return r
          .json()
          .catch(function () {
            return {};
          })
          .then(function (datos) {
            return { ok: r.ok, datos: datos };
          });
      }
    );
  }

  function cargarFicha(l) {
    return leerJson(raiz.dataset.capa + "?ruta=" + encodeURIComponent(l.token))
      .then(function (respuesta) {
        if (!respuesta.ok) {
          l.estado = "error";
          l.mensaje = respuesta.datos.mensaje || "no se pudo leer la capa.";
        } else if (respuesta.datos.dibujable === false) {
          l.estado = "apagada";
          l.mensaje = respuesta.datos.detalle || "el archivo no se puede dibujar en el mapa.";
        } else {
          l.ficha = respuesta.datos;
          l.estado = "lista";
        }
      })
      .catch(function () {
        l.estado = "error";
        l.mensaje = "no se pudo leer la capa. Compruebe la conexión con el servidor.";
      });
  }

  function cargarVuelo(id, url) {
    const v = { datos: null, estado: "cargando", mensaje: "" };
    vuelos.set(id, v);
    return leerJson(url)
      .then(function (respuesta) {
        if (!respuesta.ok) {
          v.estado = "error";
          v.mensaje = respuesta.datos.mensaje || "no se pudo leer el vuelo.";
        } else {
          v.datos = respuesta.datos;
          v.estado = "lista";
        }
      })
      .catch(function () {
        v.estado = "error";
        v.mensaje = "no se pudo leer el vuelo. Compruebe la conexión con el servidor.";
      });
  }

  /* Cada parte del vuelo se apaga **con su motivo** (sin sistema, sin recorrido, sin control…): la
   * regla 4. Una parte apagada no se dibuja ni se esconde de la lista. */
  function estadoDeLaParte(l) {
    const v = vuelos.get(l.vuelo);
    if (v.estado === "error") {
      l.estado = "error";
      l.mensaje = v.mensaje;
      return;
    }
    const d = v.datos;
    const parte = l.tipo === "vuelo-trayectoria" ? d.trayectoria : l.tipo === "vuelo-fotos" ? d.fotos : d.control;
    if (!parte.disponible) {
      l.estado = "apagada";
      l.mensaje = (parte.mensaje || "") + (parte.sugerencia ? " " + parte.sugerencia : "");
    } else {
      l.estado = "lista";
    }
  }

  /* ---- Arranque ---- */

  function fallo(mensaje) {
    const caja = $("mapa-cargando");
    caja.hidden = false;
    caja.textContent = mensaje;
  }

  function terminarDeCargar() {
    pila.forEach(function (l) {
      if (esVuelo(l)) estadoDeLaParte(l);
    });
    if (principal && principal.estado === "lista") {
      capa = principal.ficha;
      capa.puntoUrl = raiz.dataset.punto;
      capa.perfilUrl = raiz.dataset.perfil;
      capa.ruta = principal.token;
      iniciarTerreno();
      iniciarPerfil();
    }
    pintarCapas();
    if (!pila.some(dibujable)) {
      const sinNada = pila.length ? pila[0].mensaje : "";
      fallo(sinNada ? "No se pudo dibujar el mapa: " + sinNada : "No hay nada que dibujar.");
      return;
    }
    $("mapa-cargando").hidden = true;
    iniciado = true;
    actualizarNavegacionDeFotos();
    medir();
    encuadrar();
  }

  function arrancar() {
    leerColores();
    // El tema puede cambiar con el mapa abierto: se vuelven a leer los colores.
    new MutationObserver(function () {
      leerColores();
      pedir();
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    if (window.matchMedia) {
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .addEventListener("change", function () {
          leerColores();
          pedir();
        });
    }
    new ResizeObserver(medir).observe(lienzo);

    const tiposConocidos = Object.keys(ROTULOS);
    leerDeclaradas().forEach(function (d) {
      if (d && d.id && tiposConocidos.indexOf(d.tipo) >= 0) pila.push(crearCapa(d));
    });
    principal =
      pila.find(function (l) {
        return l.tipo === "raster" && l.principal;
      }) || null;
    pintarCapas();

    // Cada imagen pide su ficha y cada vuelo sus datos, **en paralelo**; una que falla lo dice en su
    // fila y no tumba a las demás.
    const promesas = [];
    const pedidos = new Set();
    pila.forEach(function (l) {
      if (esRaster(l)) promesas.push(cargarFicha(l));
      else if (l.vuelo && !pedidos.has(l.vuelo)) {
        pedidos.add(l.vuelo);
        promesas.push(cargarVuelo(l.vuelo, l.datos));
      }
    });
    Promise.all(promesas).then(terminarDeCargar);
  }

  arrancar();
})();
