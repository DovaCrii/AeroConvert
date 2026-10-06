"""Cada icono que el código nombra existe en el sprite (F9.4).

Un `<use href="#icon-x">` de un icono que no existe no falla: pinta un hueco. Es justo lo que
no se nota hasta que alguien mira la pantalla.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SPRITE = (RAIZ / "static" / "img" / "icons.svg").read_text(encoding="utf-8")
EXISTEN = set(re.findall(r'<symbol id="(icon-[\w-]+)"', SPRITE))
NOMBRE = re.compile(r"""["'#](icon-[a-z0-9]+(?:-[a-z0-9]+)*)["']""")


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
    for icono in ("icon-destino-satelite", "icon-texto-pdf", "icon-texto-web"):
        assert icono in EXISTEN
        assert icono in nombrados, f"{icono} está en el sprite y nadie lo usa"
