"""La dirección visual «Plan de vuelo» y sus límites (D8, F13.14).

**Qué se decidió el 2026-10-09:** la persona eligió «A · Plan de vuelo» para toda la app, con dos
préstamos (esquinas de encuadre y cifras en monoespaciada de «Instrumento»; curvas de nivel de «Mesa
de luz», solo como textura de la zona de soltar). Eso **sustituye al «plano con color» de F13.7**
(2026-10-07: sin degradados, sin sombras, sin movimiento al pasar), y este archivo, que lo imponía,
se reescribió para las reglas nuevas en vez de borrarse. Las reglas nuevas siguen siendo reglas:

- degradados **solo** en la barra, el lateral y el fondo de la portada;
- sombras **solo** con los tokens `--av-elev-*` (o anillos sin difuminado);
- al pasar el ratón, **como mucho** `translateY(-3px)`, y siempre con transición de 150 a 300 ms;
- todo movimiento se apaga con `prefers-reduced-motion`;
- ninguna tipografía se descarga: pilas del sistema.

Estas pruebas leen `static/css/app.css` tal cual: lo que el navegador va a recibir.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CSS = (RAIZ / "static" / "css" / "app.css").read_text(encoding="utf-8")
SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)

REGLA = re.compile(r"([^{}]+)\{([^{}]*)\}")

#: Los únicos selectores que pueden llevar la sombra de lo que flota (`--av-elev-3`). Hoy no hay
#: ninguno: el menú de herramientas pasó al lateral. Si un día hay un diálogo, entra aquí.
FLOTANTES: tuple[str, ...] = ()

#: Los únicos sitios con degradado: la barra (y su filete), el lateral (el «vidrio») y el
#: resplandor del fondo de la portada.
CON_DEGRADADO = {
    ".barra",
    ".barra::after",
    ".lateral",
    ".cuerpo-app:has(.portada-soltar)",
}

#: Lo que se levanta al pasar el ratón: la base de su selector `:hover`.
SE_LEVANTAN = {".herramienta", ".destino", ".boton"}

#: Flechas de plegable que giran al abrir: es un cambio de estado, no movimiento al pasar.
GIROS_DE_ESTADO = {".lateral-flecha", ".grupo-resumen::before", ".repetibles-resumen::before"}

#: Lo que una transición puede animar: el estado (color, fondo, borde, opacidad), la sombra de la
#: elevación, el giro de un plegable y el ancho de la barra de avance.
TRANSICIONES_PERMITIDAS = {
    "color",
    "background-color",
    "background",
    "border-color",
    "opacity",
    "box-shadow",
    "transform",
    "width",
}


def _reglas():
    for m in REGLA.finditer(SIN_COMENTARIOS):
        yield m.group(1).strip(), m.group(2)


def _selectores(cabecera: str) -> list[str]:
    return [s.strip() for s in cabecera.split(",") if s.strip()]


def _capas(valor: str) -> list[str]:
    """Las capas de un `box-shadow`, separadas por comas **de primer nivel**."""
    capas, nivel, actual = [], 0, ""
    for c in valor:
        if c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
        if c == "," and nivel == 0:
            capas.append(actual.strip())
            actual = ""
        else:
            actual += c
    return [*capas, actual.strip()] if actual.strip() else capas


def _terminos(capa: str) -> list[str]:
    """Los términos de una capa, sin partir lo que va entre paréntesis (`color-mix(...)`)."""
    terminos, nivel, actual = [], 0, ""
    for c in capa:
        if c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
        if c.isspace() and nivel == 0:
            if actual:
                terminos.append(actual)
            actual = ""
        else:
            actual += c
    return [*terminos, actual] if actual else terminos


def _longitudes(capa: str) -> list[float]:
    return [
        float(x.replace("px", "")) for x in _terminos(capa) if re.fullmatch(r"-?[\d.]+(px)?", x)
    ]


def _es_anillo(capa: str) -> bool:
    """Un anillo o una barra: **sin difuminado**. Es un borde con otro nombre, no una sombra."""
    t = [x for x in _terminos(capa) if x != "inset"]
    if capa.strip() == "none" or t[:1] == ["none"]:
        return True
    longitudes = _longitudes(capa)
    # x, y, difuminado y, opcionalmente, extensión. El difuminado es el tercero.
    return len(longitudes) >= 3 and longitudes[2] == 0


def _proyecta(capa: str) -> bool:
    return not _es_anillo(capa)


def _definiciones(nombre: str) -> list[str]:
    return [v.strip() for v in re.findall(rf"{re.escape(nombre)}:\s*([^;]+);", SIN_COMENTARIOS)]


# --- Degradados -------------------------------------------------------------------------------


def test_los_degradados_viven_solo_en_la_barra_el_lateral_y_el_fondo_de_la_portada():
    donde: set[str] = set()
    mal = []
    for cabecera, cuerpo in _reglas():
        if "gradient(" not in cuerpo:
            continue
        for selector in _selectores(cabecera):
            donde.add(selector)
            if selector not in CON_DEGRADADO:
                mal.append(selector)
    assert not mal, f"Degradado fuera de la barra, el lateral o la portada: {mal}"
    # Y que de verdad estén: una prueba que pasa porque ya no hay ninguno no vigila nada.
    assert donde == CON_DEGRADADO, donde ^ CON_DEGRADADO


def test_ningun_degradado_se_esconde_en_una_variable():
    """Un `--token: linear-gradient(...)` esquivaría la lista de arriba."""
    assert not re.findall(r"--[\w-]+:\s*[^;]*gradient\(", SIN_COMENTARIOS)


# --- Sombras ----------------------------------------------------------------------------------


def test_ninguna_sombra_con_difuminado_fuera_de_los_tokens_de_elevacion():
    mal = []
    for selector, cuerpo in _reglas():
        for m in re.finditer(r"box-shadow:\s*([^;]+);", cuerpo):
            for capa in _capas(m.group(1)):
                if "var(--av-elev-3)" in capa:
                    if not any(f in selector for f in FLOTANTES):
                        mal.append(f"{selector}: {capa}")
                elif "var(--av-elev-" in capa or _es_anillo(capa):
                    continue
                else:
                    mal.append(f"{selector}: {capa}")
    assert not mal, "Sombras con difuminado escritas a mano:\n" + "\n".join(mal)


def test_los_niveles_de_elevacion_tienen_la_forma_acordada():
    """Cada nivel es anillo + (línea de luz) + sombras largas que recogen hacia dentro.

    Un nivel por tema (claro, oscuro y oscuro del sistema), así que cada token se define tres
    veces: sin la del oscuro del sistema, quien no ha tocado el interruptor ve el nivel del claro.
    """
    # nivel -> (mínimo y máximo de capas que proyectan)
    esperado = {
        "--av-elev-1": (1, 2),
        "--av-elev-2": (1, 2),
        "--av-elev-3": (1, 1),
        "--av-elev-hover": (1, 2),
        "--av-elev-boton": (1, 1),
    }
    for definicion in _definiciones("--av-elev-0"):
        assert all(_es_anillo(c) for c in _capas(definicion)), f"--av-elev-0: {definicion}"
    for nombre, (minimo, maximo) in esperado.items():
        definiciones = _definiciones(nombre)
        assert len(definiciones) == 3, f"{nombre}: {len(definiciones)} definiciones, no 3"
        for definicion in definiciones:
            proyectan = [c for c in _capas(definicion) if _proyecta(c)]
            assert minimo <= len(proyectan) <= maximo, f"{nombre}: {definicion}"
            for capa in proyectan:
                _, _, difuminado, *resto = _longitudes(capa)
                # Un difuminado largo sin extensión negativa es el halo gris sucio.
                if difuminado > 8:
                    assert resto and resto[0] < 0, f"{nombre}: {capa}"
            if nombre not in ("--av-elev-3", "--av-elev-boton"):
                # El anillo va dentro de la sombra, y es la primera capa.
                assert _es_anillo(_capas(definicion)[0]), f"{nombre}: {definicion}"


def test_los_tres_temas_redefinen_los_colores_de_la_sombra():
    """Una sombra azulada sobre un fondo casi negro no se ve: el oscuro la cambia por negro."""
    for token in ("--av-sombra-corta", "--av-sombra-larga", "--av-realce"):
        assert len(_definiciones(token)) == 3, token


# --- Movimiento -------------------------------------------------------------------------------


def _bloque(nombre_inicio: str) -> str:
    """El cuerpo de una regla `@…` por su cabecera, contando llaves."""
    i = SIN_COMENTARIOS.index(nombre_inicio)
    j = SIN_COMENTARIOS.index("{", i)
    nivel, k = 0, j
    while True:
        nivel += SIN_COMENTARIOS[k] == "{"
        nivel -= SIN_COMENTARIOS[k] == "}"
        k += 1
        if nivel == 0:
            return SIN_COMENTARIOS[j:k]


def _base(selector: str) -> str:
    """El selector sin su estado: `.destino:hover:not(:disabled)` es `.destino`."""
    return re.sub(r":(hover|focus-visible)|:not\(:disabled\)", "", selector)


def _al_pasar():
    for cabecera, cuerpo in _reglas():
        for selector in _selectores(cabecera):
            if re.search(r":(hover|focus-visible)", selector):
                yield selector, cuerpo


def test_al_pasar_el_raton_solo_se_levanta_hasta_3_px():
    mal, levantan = [], set()
    for selector, cuerpo in _al_pasar():
        for valor in re.findall(r"(?:^|[;\s])transform\s*:\s*([^;!]+)", cuerpo):
            valor = valor.strip()
            if valor == "none":
                continue
            m = re.fullmatch(r"translateY\(-(\d+(?:\.\d+)?)px\)", valor)
            if m and 0 < float(m.group(1)) <= 3:
                levantan.add(_base(selector))
            else:
                mal.append(f"{selector}: {valor}")
    assert not mal, f"Más que `translateY(-3px)` al pasar: {mal}"
    assert levantan == SE_LEVANTAN, levantan ^ SE_LEVANTAN


def test_lo_que_se_levanta_transiciona_el_transform_entre_150_y_300_ms():
    """Sin transición, subir 3 px es un salto. Y más de 300 ms es lento para una tarjeta."""
    for base in SE_LEVANTAN:
        duraciones = []
        for cabecera, cuerpo in _reglas():
            if base not in _selectores(cabecera):
                continue
            m = re.search(r"transition:\s*([^;]+);", cuerpo)
            if not m:
                continue
            for t in re.findall(r"transform\s+([\d.]+)(ms|s)\b", m.group(1)):
                duraciones.append(float(t[0]) * (1 if t[1] == "ms" else 1000))
        assert duraciones, f"{base} se levanta pero no transiciona el transform"
        assert all(150 <= d <= 300 for d in duraciones), (base, duraciones)


def test_nada_declara_la_transicion_del_movimiento_dentro_de_su_estado():
    """La transición va en la regla **base**; en `:hover` solo se anima la ida y no la vuelta."""
    mal = [s for s, cuerpo in _al_pasar() if re.search(r"transition[^;]*\btransform\b", cuerpo)]
    for cabecera, cuerpo in _reglas():
        if re.search(r":(active|focus)\b", cabecera) and re.search(
            r"transition[^;]*\btransform\b", cuerpo
        ):
            mal.append(cabecera)
    assert not mal, mal


def test_ninguna_transicion_es_all():
    assert not re.findall(r"transition\s*:\s*all\b", SIN_COMENTARIOS)


def test_las_transiciones_solo_animan_estado_elevacion_y_los_giros_de_los_plegables():
    mal = []
    for cabecera, cuerpo in _reglas():
        m = re.search(r"(?:^|[;\s])transition:\s*([^;]+);", cuerpo)
        if not m:
            continue
        propiedades = set(re.findall(r"(?:^|,)\s*([a-z-]+)\s+(?:var\(|[\d.]+m?s)", m.group(1)))
        if not propiedades:
            mal.append(f"{cabecera}: no se entiende «{m.group(1).strip()}»")
        if not propiedades <= TRANSICIONES_PERMITIDAS:
            mal.append(f"{cabecera}: {propiedades - TRANSICIONES_PERMITIDAS}")
        if "transform" in propiedades:
            quien = set(_selectores(cabecera))
            if not quien <= (SE_LEVANTAN | GIROS_DE_ESTADO):
                mal.append(f"{cabecera}: transform en algo que ni se levanta ni gira")
    assert not mal, mal


def test_la_entrada_suave_aparece_y_sube_como_mucho_8_px():
    cuerpo = _bloque("@keyframes av-aparecer")
    assert set(re.findall(r"([a-z-]+)\s*:", cuerpo)) == {"opacity", "transform"}
    desde = re.search(r"from\s*\{([^}]*)\}", cuerpo).group(1)
    sube = re.search(r"translateY\((\d+(?:\.\d+)?)px\)", desde)
    assert sube and 0 < float(sube.group(1)) <= 8
    # `backwards`: no deja un contexto de apilado por una animación ya terminada.
    assert re.search(r"animation:\s*av-aparecer[^;]*\bbackwards\b", SIN_COMENTARIOS)
    assert not re.search(r"animation:\s*av-aparecer[^;]*\b(both|forwards)\b", SIN_COMENTARIOS)


def test_con_movimiento_reducido_todo_es_instantaneo_y_nada_se_levanta():
    # El último bloque `@media (prefers-reduced-motion…)` de la hoja es el de esta dirección.
    bloques = re.findall(r"@media \(prefers-reduced-motion: reduce\)", SIN_COMENTARIOS)
    assert len(bloques) == 2, "el de F13.13 (instantáneo) y el de D8 (se detiene y no se levanta)"
    uno = _bloque("@media (prefers-reduced-motion: reduce)")
    assert "transition-duration: 0.01ms !important" in uno
    assert "animation-duration: 0.01ms !important" in uno
    ultimo = SIN_COMENTARIOS[SIN_COMENTARIOS.rindex("@media (prefers-reduced-motion: reduce)") :]
    # Lo infinito (la trayectoria punteada) se corta en una vuelta, y nada sube al pasar.
    assert "animation-iteration-count: 1 !important" in ultimo
    assert "transform: none !important" in ultimo
    for base in SE_LEVANTAN:
        assert f"{base}:hover" in ultimo, f"{base} sigue subiendo con movimiento reducido"


def test_toda_animacion_infinita_tiene_su_corte_con_movimiento_reducido():
    infinitas = [s for s, cuerpo in _reglas() if re.search(r"animation:[^;]*\binfinite\b", cuerpo)]
    assert infinitas, "la trayectoria de la zona de soltar es la única; si ya no está, quita esto"
    ultimo = SIN_COMENTARIOS[SIN_COMENTARIOS.rindex("@media (prefers-reduced-motion: reduce)") :]
    assert "animation-iteration-count: 1 !important" in ultimo


# --- Tipografía y adornos: nada se descarga ----------------------------------------------------


def test_no_se_descarga_ninguna_tipografia_ni_nada_de_fuera():
    """Descargar exige el permiso de la persona. Las OFL (Space Grotesk, Inter, JetBrains Mono) se
    vendorizarían con SRI cuando lo autorice: hasta entonces, pilas del sistema."""
    assert "@font-face" not in SIN_COMENTARIOS
    assert "@import" not in SIN_COMENTARIOS
    assert not re.search(r"url\(\s*[\"']?(https?:)?//", SIN_COMENTARIOS)


def test_las_pilas_de_letra_caen_a_una_fuente_del_sistema():
    texto = _definiciones("--av-fuente-texto")[0]
    titulos = _definiciones("--av-fuente-titulos")[0]
    cifras = _definiciones("--av-fuente-cifras")[0]
    assert "system-ui" in texto and texto.endswith("sans-serif")
    assert "system-ui" in titulos and titulos.endswith("sans-serif")
    assert cifras.endswith("monospace") and "Consolas" in cifras


def test_las_cifras_van_en_monoespaciada_en_las_lecturas():
    """Compatibilidad (cifras y versiones) y recibos (lecturas): D8, préstamo de «Instrumento»."""
    cuerpo = next(
        c for h, c in _reglas() if ".tira-cifra" in h and ".recibo dd" in h and "font-family" in c
    )
    assert "var(--av-fuente-cifras)" in cuerpo


def test_las_curvas_de_nivel_son_un_svg_valido_y_solo_adornan_la_zona_de_soltar():
    ruta = RAIZ / "static" / "img" / "curvas-de-nivel.svg"
    # Un `--` dentro de un comentario XML lo invalida, y el navegador deja la máscara en blanco
    # sin avisar: la textura desaparece y nada falla.
    arbol = ET.parse(ruta).getroot()
    assert arbol.tag.endswith("svg")
    usan = [h for h, cuerpo in _reglas() if "curvas-de-nivel.svg" in cuerpo]
    assert usan == [".soltar::before", ".portada-escena::before"], usan


def test_la_escena_de_la_entrada_es_propia_y_no_se_anuncia():
    """Sin imágenes de fuera ni datos de nadie: SVG en la plantilla, `aria-hidden`, sin `<image>` ni
    `<img>` de otro origen, y con los colores de los tokens (sigue al tema)."""
    plantilla = (RAIZ / "templates" / "core" / "entrar.html").read_text(encoding="utf-8")
    escena = plantilla.split('class="portada-escena"', 1)[1]
    assert 'aria-hidden="true"' in plantilla.split('class="portada-escena"', 1)[1][:60]
    assert "<image" not in escena and 'href="http' not in escena
    assert "style=" not in escena
    reglas = [c for h, c in _reglas() if ".escena" in h and "fill:" in c]
    assert reglas and all("#" not in c for c in reglas), "colores escritos a mano en la escena"


def test_los_adornos_de_la_zona_de_soltar_no_se_anuncian():
    plantilla = (RAIZ / "templates" / "dashboard" / "_zona_soltar.html").read_text(encoding="utf-8")
    svg = re.search(r"<svg[^>]*class=\"soltar-ruta\"[^>]*>", plantilla)
    assert svg and 'aria-hidden="true"' in svg.group(0)
    assert "<text" not in plantilla.split("soltar-ruta", 1)[1].split("</svg>", 1)[0]
