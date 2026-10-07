"""La tipografía y los radios salen de la escala, no de un número escrito a mano (F9.4).

Había 14 tamaños de letra distintos (`0.82rem`, `0.84rem`, `0.88rem`, `0.9rem`, `0.92rem`…) que
no formaban escala, y `3px`, `4px`, `6px` y `999px` de radio. Cada hoja nueva traía el suyo.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CSS = (RAIZ / "static" / "css" / "app.css").read_text(encoding="utf-8")

#: Lo que sí puede ir a mano: un tamaño relativo al texto que lo rodea (`em`, para `<code>`), el
#: título fluido de la portada (`clamp`) y el círculo (`50%`). El radio de la marca es de la marca.
_FUERA_DE_ESCALA_DE_LETRA = re.compile(r"font-size:\s+(?!var\(--av-fs-|clamp\(|[\d.]+em;|inherit)")
_RADIO_A_MANO = re.compile(
    r"border-radius:\s+(?!var\(--av-radius|var\(--marca-radio|50%|0;|inherit)"
)


def _lineas(patron: re.Pattern[str]) -> list[str]:
    return [
        f"{n}: {linea.strip()}"
        for n, linea in enumerate(CSS.splitlines(), start=1)
        if patron.search(linea)
    ]


def test_ningun_tamano_de_letra_esta_fuera_de_la_escala():
    assert not _lineas(_FUERA_DE_ESCALA_DE_LETRA)


def test_ningun_radio_esta_escrito_a_mano():
    assert not _lineas(_RADIO_A_MANO)


def test_la_escala_de_letra_es_creciente_y_sin_huecos_de_nombre():
    valores = {
        nombre: float(valor) for nombre, valor in re.findall(r"--av-fs-(\w+):\s*([\d.]+)rem;", CSS)
    }
    orden = ["xs", "sm", "base", "md", "lg", "xl", "2xl"]
    assert [n for n in orden if n in valores] == orden
    assert [valores[n] for n in orden] == sorted(valores[n] for n in orden)


def test_ninguna_plantilla_lleva_estilo_en_linea_fijo():
    """F13.10: había 183 `style="..."` escritos a mano en 32 plantillas, fuera de la escala que
    vigilan estas pruebas. Ahora son clases (Bootstrap o `av-*`). **Solo se admite un valor
    calculado** (`{{ ... }}`), como el ancho de la barra de avance."""
    mal = []
    for ruta in sorted((RAIZ / "templates").rglob("*.html")):
        texto = ruta.read_text(encoding="utf-8")
        for numero, linea in enumerate(texto.splitlines(), start=1):
            for m in re.finditer(r'style="([^"]*)"', linea):
                if "{{" not in m.group(1):
                    mal.append(f"{ruta.relative_to(RAIZ).as_posix()}:{numero}: {m.group(1)}")
    assert not mal, "Estilos en línea fijos:\n" + "\n".join(mal)


def test_toda_utilidad_av_que_usa_una_plantilla_esta_en_la_hoja():
    """Una clase `av-*` que no existe no falla: simplemente no hace nada. Es justo el fallo que
    no se ve hasta mirar la pantalla."""
    usadas: set[str] = set()
    for ruta in (RAIZ / "templates").rglob("*.html"):
        for m in re.finditer(r'class="([^"]*)"', ruta.read_text(encoding="utf-8")):
            usadas |= {
                c for c in m.group(1).split() if re.fullmatch(r"av-(m|p|fs|gap|mw|w)[\w-]*", c)
            }
    definidas = set(re.findall(r"^\.(av-[\w-]+) \{", CSS, flags=re.MULTILINE))
    assert not usadas - definidas, sorted(usadas - definidas)


def test_los_radios_van_de_menor_a_mayor():
    r = {n: float(v) for n, v in re.findall(r"--av-radius-?(\w*):\s*([\d.]+)px;", CSS)}
    assert r["xs"] < r["sm"] < r[""]
