"""F9.5: la paleta pasó de hexadecimal a OKLCH **sin cambiar lo que se ve**.

`PALETA_ANTERIOR` es la foto de los tres bloques de tema de `static/css/app.css` tal como estaban
el 2026-10-06, antes de la migración. Estas pruebas exigen que cada token siga dando **el mismo
byte** en cada canal, y que ninguno se haya quedado en hexadecimal.

Es una prueba de migración, no una prohibición: si un día se cambia un color a propósito, se
actualiza su fila aquí y el cambio queda a la vista en la revisión. Lo que no puede pasar es que
cambie por un redondeo.

**La prueba de verdad es el navegador**, no esta fórmula contra sí misma: cada token se pintó en
un `<canvas>` y se leyó el píxel (cifras fechadas en `docs/PRUEBAS_CON_ORACULO.md`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from apps.core import oklch

CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"

#: Los tokens de color de cada bloque, con el hexadecimal que tenían antes de la migración.
PALETA_ANTERIOR = {
    "claro": {
        "--av-navy": "#1b2a4a",
        "--av-magenta": "#f15bb5",
        "--av-primary": "#a3176f",
        "--av-primary-hover": "#85115a",
        "--av-primary-soft": "#fce7f3",
        "--av-sobre-accion": "#ffffff",
        "--av-bg": "#f4f7fb",
        "--av-surface": "#ffffff",
        "--av-surface-alt": "#f8fafc",
        "--av-border": "#dbe3ee",
        "--av-border-control": "#7f8b9e",
        "--av-text": "#172238",
        "--av-text-secondary": "#4f5b72",
        "--av-text-muted": "#5a667a",
        "--av-ok": "#0e7359",
        "--av-warn": "#8a5a00",
        "--av-danger": "#b53647",
        "--av-ok-soft": "#e4f6ea",
        "--av-warn-soft": "#fdf1dc",
        "--av-danger-soft": "#fce4e6",
        "--av-info": "#1a5aad",
        "--av-info-soft": "#e6eefb",
        "--av-fam-transformar": "#1b5fb8",
        "--av-fam-transformar-soft": "#e6eefb",
        "--av-fam-marcar": "#6b3fbf",
        "--av-fam-marcar-soft": "#ede8fb",
        "--av-fam-proteger": "#0f6d78",
        "--av-fam-proteger-soft": "#ddf1f3",
        "--av-fam-destino": "#2e4a8e",
        "--av-fam-destino-soft": "#e8ecfa",
        "--av-fam-texto": "#8f4418",
        "--av-fam-texto-soft": "#fbe9dd",
    },
    "oscuro": {
        "--av-magenta": "#f15bb5",
        "--av-primary": "#f5a8d3",
        "--av-primary-hover": "#f9c4e1",
        "--av-primary-soft": "#3a1030",
        "--av-sobre-accion": "#1b0d16",
        "--av-bg": "#0e141d",
        "--av-surface": "#1c2634",
        "--av-surface-alt": "#24303f",
        "--av-border": "#334054",
        "--av-border-control": "#74829a",
        "--av-text": "#eef1f6",
        "--av-text-secondary": "#bcc6d6",
        "--av-text-muted": "#9daabc",
        "--av-ok": "#5fd3ae",
        "--av-warn": "#f0b45e",
        "--av-danger": "#f08a97",
        "--av-ok-soft": "#14361f",
        "--av-warn-soft": "#3d2f14",
        "--av-danger-soft": "#3d1a1e",
        "--av-info": "#9cc6f8",
        "--av-info-soft": "#17325a",
        "--av-fam-componer-soft": "#46143a",
        "--av-fam-transformar": "#9cc6f8",
        "--av-fam-transformar-soft": "#17325a",
        "--av-fam-marcar": "#cdb4f8",
        "--av-fam-marcar-soft": "#2f1d5c",
        "--av-fam-proteger": "#7ddbe3",
        "--av-fam-proteger-soft": "#14444b",
        "--av-fam-destino": "#a9c0f2",
        "--av-fam-destino-soft": "#1d2c52",
        "--av-fam-texto": "#f0b088",
        "--av-fam-texto-soft": "#4a2a14",
    },
    "sistema": {
        "--av-primary": "#f5a8d3",
        "--av-primary-hover": "#f9c4e1",
        "--av-primary-soft": "#3a1030",
        "--av-sobre-accion": "#1b0d16",
        "--av-bg": "#0e141d",
        "--av-surface": "#1c2634",
        "--av-surface-alt": "#24303f",
        "--av-border": "#334054",
        "--av-border-control": "#74829a",
        "--av-text": "#eef1f6",
        "--av-text-secondary": "#bcc6d6",
        "--av-text-muted": "#9daabc",
        "--av-ok": "#5fd3ae",
        "--av-warn": "#f0b45e",
        "--av-danger": "#f08a97",
        "--av-ok-soft": "#14361f",
        "--av-warn-soft": "#3d2f14",
        "--av-danger-soft": "#3d1a1e",
        "--av-info": "#9cc6f8",
        "--av-info-soft": "#17325a",
        "--av-fam-componer-soft": "#46143a",
        "--av-fam-transformar": "#9cc6f8",
        "--av-fam-transformar-soft": "#17325a",
        "--av-fam-marcar": "#cdb4f8",
        "--av-fam-marcar-soft": "#2f1d5c",
        "--av-fam-proteger": "#7ddbe3",
        "--av-fam-proteger-soft": "#14444b",
        "--av-fam-destino": "#a9c0f2",
        "--av-fam-destino-soft": "#1d2c52",
        "--av-fam-texto": "#f0b088",
        "--av-fam-texto-soft": "#4a2a14",
    },
}

INICIO_DE_BLOQUE = {
    "claro": ":root {",
    "oscuro": ':root[data-theme="dark"]',
    "sistema": ':root:not([data-theme="light"])',
}


def _bloque(css: str, selector: str) -> str:
    inicio = css.index(selector)
    abre = css.index("{", inicio)
    cierra = css.index("}", abre)
    return css[abre:cierra]


@pytest.fixture(scope="module")
def tokens() -> dict[str, dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    return {
        tema: dict(re.findall(r"(--av-[a-z0-9-]+)\s*:\s*([^;]+);", _bloque(css, selector)))
        for tema, selector in INICIO_DE_BLOQUE.items()
    }


TODOS = [(tema, nombre, hexa) for tema, d in PALETA_ANTERIOR.items() for nombre, hexa in d.items()]


@pytest.mark.parametrize(("tema", "nombre", "hexa"), TODOS, ids=[f"{t}:{n}" for t, n, _ in TODOS])
def test_el_token_sigue_dando_el_mismo_color(tokens, tema, nombre, hexa):
    valor = tokens[tema][nombre].strip()
    assert valor.lower().startswith("oklch("), f"{nombre} ({tema}) sigue en hexadecimal: {valor}"
    assert oklch.de_texto(valor) == hexa, f"{nombre} ({tema}) cambió de color: {valor} no es {hexa}"


def test_ningun_token_de_color_quedo_en_hexadecimal(tokens):
    sobrantes = [
        f"{tema}:{nombre}"
        for tema, d in tokens.items()
        for nombre, valor in d.items()
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", valor.strip())
    ]
    assert not sobrantes, sobrantes


@pytest.mark.parametrize("hexa", sorted({h for _, _, h in TODOS}))
def test_ida_y_vuelta_exacta(hexa):
    """La precisión que se escribe en el CSS basta para recuperar el mismo byte."""
    assert oklch.de_texto(oklch.texto(hexa)) == hexa


@pytest.mark.parametrize("hexa", sorted({h for _, _, h in TODOS}))
def test_todo_cae_dentro_de_la_gama_srgb(hexa):
    """Ningún color pide más de lo que sRGB puede dar: el navegador no tiene que recortarlo."""
    for canal in oklch.a_rgb(*oklch.de_hex(hexa)):
        assert -0.6 <= canal <= 255.6, (hexa, canal)


class TestElConversor:
    def test_blanco_y_negro(self):
        assert oklch.texto("#ffffff") == "oklch(1.0000 0.0000 0.00)"
        assert oklch.texto("#000000") == "oklch(0.0000 0.0000 0.00)"

    def test_un_gris_no_tiene_croma(self):
        assert oklch.de_hex("#808080")[1] < 1e-4

    def test_el_hexadecimal_corto_se_entiende(self):
        assert oklch.de_hex("#fff") == oklch.de_hex("#ffffff")

    def test_lo_que_no_es_oklch_se_rechaza(self):
        with pytest.raises(ValueError):
            oklch.de_texto("rgb(1 2 3)")
        with pytest.raises(ValueError):
            oklch.de_texto("oklch(0.5 0.1 200 / 50%)")
