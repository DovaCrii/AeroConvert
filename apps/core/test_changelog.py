"""El registro de cambios tiene **una** sección de cada versión.

El 2026-10-08 una fusión de «los dos añadieron» dejó el `CHANGELOG.md` entero dos veces (dos «Sin
publicar», dos 0.11.0…) y ninguna prueba lo vio. Keep a Changelog: una sección por versión, la
de lo no publicado arriba, y las versiones de la más nueva a la más vieja.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
_SECCION = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


def _secciones() -> list[str]:
    return _SECCION.findall((RAIZ / "CHANGELOG.md").read_text(encoding="utf-8"))


def test_cada_version_aparece_una_sola_vez():
    secciones = _secciones()
    repetidas = sorted({s for s in secciones if secciones.count(s) > 1})
    assert not repetidas, f"Secciones repetidas en CHANGELOG.md: {repetidas}"


def test_lo_no_publicado_va_arriba_y_las_versiones_de_nueva_a_vieja():
    secciones = _secciones()
    assert secciones[0] == "Sin publicar"
    versiones = [tuple(int(n) for n in s.split(".")) for s in secciones[1:]]
    assert versiones == sorted(versiones, reverse=True)
