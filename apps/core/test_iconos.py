"""Los iconos: que existan, que no choquen y que sean una familia (F9.4, F13.4 y F13.5).

Un `<use href="#icon-x">` de un icono que no existe no falla: pinta un hueco. Es justo lo que no se
nota hasta que alguien mira la pantalla. Y un mismo icono con dos significados (QGIS y «Todas las
herramientas»; Tino y el mensaje informativo) obliga a leer el texto para saber de qué se habla,
que es justo lo que un icono tiene que ahorrar.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SPRITE = (RAIZ / "static" / "img" / "icons.svg").read_text(encoding="utf-8")
EXISTEN = set(re.findall(r'<symbol id="(icon-[\w-]+)"', SPRITE))
NOMBRE = re.compile(r"""["'#](icon-[a-z0-9]+(?:-[a-z0-9]+)*)["']""")

#: Iconos que sí se reparten entre varios usos, **dicho aquí y con su motivo**: cualquier otro uso
#: compartido es un choque.
COMPARTIDOS = {
    # El de reserva cuando una herramienta o un perfil no trae el suyo.
    "icon-destino": "icono de reserva",
    # El mismo veredicto («abre») en el remate de un trabajo, en un mensaje y en la matriz: es el
    # mismo significado en tres sitios, no tres significados.
    "icon-veredicto-abre": "el mismo veredicto",
    "icon-veredicto-reparos": "el mismo veredicto",
    "icon-veredicto-no": "el mismo veredicto",
}


def _nombrados() -> set[str]:
    fuentes = [
        p
        for p in [*(RAIZ / "apps").rglob("*.py"), *(RAIZ / "templates").rglob("*.html")]
        if not p.name.startswith("test_") and "tests" not in p.parts
    ]
    usados: set[str] = set()
    for fuente in fuentes:
        usados |= set(NOMBRE.findall(fuente.read_text(encoding="utf-8")))
    return usados


def test_todo_icono_nombrado_existe_en_el_sprite():
    assert not {i for i in _nombrados() if i not in EXISTEN}


def test_los_iconos_nuevos_estan_y_se_usan():
    nombrados = _nombrados()
    for icono in (
        "icon-destino-satelite",
        "icon-texto-pdf",
        "icon-texto-web",
        "icon-pdf-organizar",
        "icon-todas",
        "icon-tino",
        "icon-texto-csv",
        "icon-imagen-a-pdf",
        "icon-chevron",
    ):
        assert icono in EXISTEN
        assert icono in nombrados, f"{icono} está en el sprite y nadie lo usa"


# --- Un icono, un significado (F13.4) ----------------------------------------------------


def _significados() -> dict[str, set[str]]:
    """Qué entidades usan cada icono: herramientas, perfiles y los usos fijos de la interfaz."""
    from apps.dashboard.acciones import ICONOS_DE_PERFIL
    from apps.documents.herramientas import HERRAMIENTAS

    por_icono: dict[str, set[str]] = defaultdict(set)
    for herramienta in HERRAMIENTAS:
        por_icono[herramienta["icono"]].add(f"herramienta:{herramienta['id']}")
    for perfil, icono in ICONOS_DE_PERFIL.items():
        por_icono[icono].add(f"perfil:{perfil}")

    # Los usos fijos de `base.html` y de los mensajes: cada uno con el significado que tiene.
    fijos = {
        "icon-info": "mensaje informativo",
        "icon-tino": "el ayudante Tino",
        "icon-todas": "todas las herramientas",
        "icon-convertir": "convertir",
        "icon-historial": "historial",
        "icon-inicio": "inicio",
        "icon-compatibilidad": "compatibilidad",
        "icon-preajustes": "preajustes",
        "icon-chevron": "plegar o desplegar",
        "icon-menu": "mostrar u ocultar el lateral",
    }
    for icono, significado in fijos.items():
        por_icono[icono].add(f"interfaz:{significado}")
    return por_icono


def test_ningun_icono_tiene_dos_significados():
    choques = {
        icono: sorted(quienes)
        for icono, quienes in _significados().items()
        if len(quienes) > 1 and icono not in COMPARTIDOS
    }
    assert not choques, choques


def test_los_usos_fijos_de_la_interfaz_no_son_ninguna_herramienta():
    """`icon-info` era a la vez de Tino y del mensaje informativo, y `icon-destino-capas` de QGIS
    y de «Todas las herramientas»: lo fijo de la interfaz no puede ser de una herramienta."""
    base = (RAIZ / "templates" / "base.html").read_text(encoding="utf-8")
    lateral = base[base.index('<aside class="lateral"') : base.index("</aside>")]
    from apps.dashboard.acciones import ICONOS_DE_PERFIL

    de_perfil = set(ICONOS_DE_PERFIL.values())
    fijos = set(NOMBRE.findall(lateral.split("{% for grupo in menu_grupos %}")[0]))
    fijos |= set(NOMBRE.findall(lateral.split("{% endfor %}")[-1]))
    assert not fijos & de_perfil, sorted(fijos & de_perfil)


# --- Una familia (F13.5) ------------------------------------------------------------------

SIMBOLO = re.compile(r'<symbol id="([^"]+)"([^>]*)>(.*?)</symbol>', re.DOTALL)


def test_todo_el_sprite_usa_un_solo_trazo_de_1_75():
    """Había nueve grosores distintos en un mismo sprite (de 1,5 a 2,4): los iconos no parecían
    de la misma mano. Uno solo, y que no se cuele otro."""
    anchos = set(re.findall(r'stroke-width="([\d.]+)"', SPRITE))
    assert anchos == {"1.75"}, anchos


def test_todos_los_simbolos_son_de_24_por_24_con_extremos_redondeados():
    simbolos = SIMBOLO.findall(SPRITE)
    assert len(simbolos) >= 40
    for ident, atributos, _ in simbolos:
        assert 'viewBox="0 0 24 24"' in atributos, ident
        assert 'stroke-linecap="round"' in atributos, ident
        assert 'stroke-linejoin="round"' in atributos, ident
        assert 'fill="none"' in atributos, ident


def test_ninguna_plantilla_dibuja_un_svg_suelto():
    """La flecha del lateral estaba dibujada a mano en `base.html`, con su propio trazo. Todo
    dibujo va al sprite; las plantillas solo lo invocan con `<use>`."""
    sueltos = []
    for ruta in sorted((RAIZ / "templates").rglob("*.html")):
        # `500.html` es la página suelta que no puede cargar ni la hoja ni el sprite.
        if ruta.name == "500.html":
            continue
        texto = ruta.read_text(encoding="utf-8")
        for m in re.finditer(r"<svg\b([^>]*)>(.*?)</svg>", texto, re.DOTALL):
            # `dibujo-puntos` (los puntos de una libreta) y `mapa-svg` (la huella sobre la
            # retícula) son gráficos de datos, no iconos.
            if "dibujo-" in m.group(1) or "mapa-svg" in m.group(1):
                continue
            if re.search(r"<(path|circle|rect|line|polyline|polygon|ellipse)\b", m.group(2)):
                sueltos.append(ruta.relative_to(RAIZ).as_posix())
    assert not sueltos, sueltos
