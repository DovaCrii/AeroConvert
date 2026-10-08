"""La interfaz es plana, pero con color (F13.7).

**Qué se decidió el 2026-10-07:** nada de degradados, de sombras proyectadas ni de movimiento al
pasar el ratón. La jerarquía se hace con un anillo de 1 px, con el cambio de superficie y con el
color de cada familia, que en las baldosas sigue siendo fuerte también en oscuro. Antes había 8
degradados, 31 sombras y tarjetas que subían un píxel y crecían al pasar el ratón.

Estas pruebas leen `static/css/app.css` tal cual: lo que el navegador va a recibir.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CSS = (RAIZ / "static" / "css" / "app.css").read_text(encoding="utf-8")
SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)

REGLA = re.compile(r"([^{}]+)\{([^{}]*)\}")

#: Los únicos selectores que pueden llevar la sombra de lo que flota (`--av-elev-3`). Hoy no hay
#: ninguno: el menú de herramientas pasó al lateral. Si un día hay un diálogo, entra aquí.
FLOTANTES: tuple[str, ...] = ()


def _reglas():
    for m in REGLA.finditer(SIN_COMENTARIOS):
        yield m.group(1).strip(), m.group(2)


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


def _es_anillo(capa: str) -> bool:
    """Un anillo o una barra: **sin difuminado**. Es un borde con otro nombre, no una sombra."""
    t = [x for x in _terminos(capa) if x != "inset"]
    if capa.strip() == "none" or t[:1] == ["none"]:
        return True
    longitudes = [x for x in t if re.fullmatch(r"-?[\d.]+(px)?", x)]
    # x, y, difuminado y, opcionalmente, extensión. El difuminado es el tercero.
    return len(longitudes) >= 3 and float(longitudes[2].replace("px", "")) == 0


def test_no_hay_ningun_degradado():
    assert "gradient(" not in SIN_COMENTARIOS, [
        linea.strip() for linea in SIN_COMENTARIOS.splitlines() if "gradient(" in linea
    ]


def test_ninguna_sombra_proyectada_fuera_de_lo_que_flota():
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
    assert not mal, "Sombras con difuminado:\n" + "\n".join(mal)


def test_los_niveles_de_elevacion_son_un_anillo_y_solo_el_ultimo_proyecta_sombra():
    for nivel in ("0", "1", "2"):
        for valor in re.findall(rf"--av-elev-{nivel}:\s*([^;]+);", SIN_COMENTARIOS):
            assert all(_es_anillo(c) for c in _capas(valor)), f"--av-elev-{nivel}: {valor}"
    proyectan = [
        v
        for v in re.findall(r"--av-elev-3:\s*([^;]+);", SIN_COMENTARIOS)
        if not all(_es_anillo(c) for c in _capas(v))
    ]
    assert len(proyectan) == 3, "las tres definiciones (claro, oscuro y oscuro del sistema)"
    for v in proyectan:
        # Una sola capa que proyecta, además del anillo: un solo nivel de sombra.
        assert sum(not _es_anillo(c) for c in _capas(v)) == 1, v


def test_pasar_el_ratón_no_mueve_nada():
    mal = []
    for selector, cuerpo in _reglas():
        if ":hover" in selector and re.search(r"(^|[;\s])transform\s*:", cuerpo):
            mal.append(selector)
    assert not mal, f"`transform` al pasar el ratón: {mal}"


# --- F13.13: transiciones de estado y entrada suave -------------------------------------------


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


def test_ninguna_transicion_es_all():
    assert not re.findall(r"transition\s*:\s*all\b", SIN_COMENTARIOS)


def test_nada_transiciona_el_movimiento_al_pasar_o_enfocar():
    mal = []
    for selector, cuerpo in _reglas():
        if re.search(r":(hover|focus|focus-visible|active)", selector) and re.search(
            r"transition[^;]*\btransform\b", cuerpo
        ):
            mal.append(selector)
    assert not mal, mal


def test_los_botones_y_baldosas_transicionan_solo_estado():
    permitidas = {"color", "background-color", "background", "border-color", "opacity"}
    cuerpo = next(c for s, c in _reglas() if s.strip().startswith(".boton,"))
    propiedades = set(re.findall(r"(?:^|,)\s*([a-z-]+)\s+var\(", cuerpo.split("transition:")[1]))
    assert propiedades and propiedades <= permitidas, propiedades


def test_la_entrada_suave_solo_cambia_la_opacidad():
    cuerpo = _bloque("@keyframes av-aparecer")
    assert set(re.findall(r"([a-z-]+)\s*:", cuerpo)) == {"opacity"}
    # `backwards`: no deja un contexto de apilado por una animación ya terminada.
    assert re.search(r"animation:\s*av-aparecer[^;]*\bbackwards\b", SIN_COMENTARIOS)
    assert not re.search(r"animation:\s*av-aparecer[^;]*\b(both|forwards)\b", SIN_COMENTARIOS)


def test_con_movimiento_reducido_todo_es_instantaneo():
    cuerpo = _bloque("@media (prefers-reduced-motion: reduce)")
    assert "transition-duration: 0.01ms !important" in cuerpo
    assert "animation-duration: 0.01ms !important" in cuerpo
