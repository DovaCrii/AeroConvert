"""Los contrastes de la paleta, calculados y no prometidos.

La cabecera de `static/css/app.css` afirmaba que «hay una prueba que lee este archivo, calcula
los contrastes con la fórmula de WCAG 2.1 y falla si alguno baja del piso», y que por eso los
números «no son una afirmación: son una prueba».

**No la había.** Este archivo es esa prueba, escrita al añadir los cuatro colores de familia
de las herramientas de PDF: cuatro pares nuevos de color y fondo son cuatro sitios donde una
elección a ojo puede dejar un icono ilegible en uno de los dos temas, y a ojo no se ve — sobre
todo en el claro, donde todo «se lee bien» hasta que alguien lo mira en una pantalla mala o a
contraluz en terreno.

## Los pisos, y por qué son esos

- **4,5:1 para texto**, que es el nivel AA de WCAG 2.1 para tamaño normal.
- **3:1 para lo gráfico** — iconos y bordes de control: el mismo nivel AA, que para elementos
  no textuales es más bajo porque una forma se reconoce con menos contraste que una letra.

Los iconos de familia se exigen a **4,5** y no a 3 a propósito: son el elemento por el que se
distingue una herramienta de otra en una rejilla de nueve, y quedarse en el mínimo de lo
gráfico sería aprobar por los pelos algo que se mira todo el día.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"

#: El piso de AA para texto normal.
TEXTO = 4.5
#: El piso de AA para elementos no textuales.
GRAFICO = 3.0


def _canal(valor: int) -> float:
    """Un canal de 0-255 a luz lineal, segun WCAG 2.1."""
    proporcion = valor / 255
    if proporcion <= 0.04045:
        return proporcion / 12.92
    return ((proporcion + 0.055) / 1.055) ** 2.4


def _luminancia(hexadecimal: str) -> float:
    crudo = hexadecimal.lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    r, g, b = (int(crudo[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _canal(r) + 0.7152 * _canal(g) + 0.0722 * _canal(b)


def contraste(uno: str, otro: str) -> float:
    a, b = _luminancia(uno), _luminancia(otro)
    claro, oscuro = max(a, b), min(a, b)
    return (claro + 0.05) / (oscuro + 0.05)


def _bloque(css: str, selector: str) -> str:
    """El cuerpo del primer bloque de ese selector.

    A mano y sin un analizador de CSS: son dos bloques planos y sin anidar, y una dependencia
    más para leer veinte líneas no se paga.
    """
    inicio = css.index(selector)
    abre = css.index("{", inicio)
    cierra = css.index("}", abre)
    return css[abre:cierra]


def _variables(bloque: str) -> dict[str, str]:
    """Las variables con color literal. Las que apuntan a otra (`var(...)`) se resuelven."""
    crudas = dict(re.findall(r"(--av-[a-z-]+)\s*:\s*([^;]+);", bloque))
    resueltas: dict[str, str] = {}
    for nombre, valor in crudas.items():
        valor = valor.strip()
        apunta = re.fullmatch(r"var\((--av-[a-z-]+)\)", valor)
        if apunta:
            valor = crudas.get(apunta.group(1), "").strip()
        if valor.startswith("#"):
            resueltas[nombre] = valor
    return resueltas


@pytest.fixture(scope="module")
def css() -> str:
    assert CSS.exists(), f"Falta {CSS}. Si cambió de sitio, actualiza esto."
    return CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def claro(css: str) -> dict[str, str]:
    return _variables(_bloque(css, ":root {"))


@pytest.fixture(scope="module")
def oscuro(css: str) -> dict[str, str]:
    return _variables(_bloque(css, ':root[data-theme="dark"]'))


#: Las cuatro familias de herramientas de PDF. Ver `HERRAMIENTAS` en `apps/documents/views.py`.
FAMILIAS = ("componer", "transformar", "marcar", "proteger")


class TestElColorDeAccion:
    """El que se lee. La cabecera del CSS promete 7,2:1 en claro y 8,9:1 en oscuro."""

    def test_en_claro(self, claro):
        assert contraste(claro["--av-primary"], claro["--av-surface"]) >= TEXTO

    def test_en_oscuro(self, oscuro):
        assert contraste(oscuro["--av-primary"], oscuro["--av-surface"]) >= TEXTO


class TestElMagentaDeMarca:
    """**Y que el magenta siga sin valer para texto.**

    No es una restricción que sobre: es la razón de que exista `--av-primary`. Si alguien
    «arreglara» el magenta para que pasara AA, la regla de la familia —la marca pinta, la
    acción se lee— se habría perdido sin que nadie lo note.
    """

    def test_no_llega_al_piso_de_texto_sobre_blanco(self, claro):
        assert contraste(claro["--av-magenta"], "#ffffff") < TEXTO


class TestLosCuatroColoresDeFamilia:
    """Cada icono contra su propia baldosa, en los dos temas."""

    @pytest.mark.parametrize("familia", FAMILIAS)
    def test_en_claro(self, claro, familia):
        color = claro[f"--av-fam-{familia}"]
        fondo = claro[f"--av-fam-{familia}-soft"]
        assert contraste(color, fondo) >= TEXTO, f"{familia} en claro"

    @pytest.mark.parametrize("familia", FAMILIAS)
    def test_en_oscuro(self, oscuro, familia):
        color = oscuro[f"--av-fam-{familia}"]
        fondo = oscuro[f"--av-fam-{familia}-soft"]
        assert contraste(color, fondo) >= TEXTO, f"{familia} en oscuro"

    @pytest.mark.parametrize("familia", FAMILIAS)
    def test_y_tambien_contra_la_tarjeta(self, claro, familia):
        """La baldosa es translúcida por el degradado, así que el icono acaba viéndose
        parcialmente contra la superficie de la tarjeta. Aquí basta el piso de lo gráfico."""
        color = claro[f"--av-fam-{familia}"]
        assert contraste(color, claro["--av-surface"]) >= GRAFICO, f"{familia} sobre tarjeta"

    def test_las_cuatro_baldosas_se_distinguen_entre_si(self, claro):
        """Cuatro colores que no se diferencian son un color con cuatro nombres."""
        fondos = {claro[f"--av-fam-{f}-soft"] for f in FAMILIAS}
        assert len(fondos) == len(FAMILIAS)

    def test_y_no_pisan_a_los_estados(self, claro):
        """Verde, ámbar y rojo significan “salió bien”, “cuidado” y “falló” en toda la
        aplicación. Una familia con uno de esos colores diría algo que no es."""
        estados = {claro["--av-ok"], claro["--av-warn"], claro["--av-danger"]}
        for familia in FAMILIAS:
            assert claro[f"--av-fam-{familia}"] not in estados
