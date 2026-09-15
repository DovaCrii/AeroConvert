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


@pytest.fixture(scope="module")
def sistema_oscuro(css: str) -> dict[str, str]:
    """El tercer bloque, que es el que **manda por omisión** y no se estaba mirando.

    Quien tiene el sistema en oscuro y no ha tocado el interruptor no cae en
    `[data-theme="dark"]`: cae aquí. Y aquí faltaban los ocho colores de familia, así que
    heredaba los del tema claro — baldosas casi blancas sobre tarjetas oscuras.
    """
    return _variables(_bloque(css, ':root:not([data-theme="light"])'))


#: Las seis familias. Cuatro de las herramientas de PDF (`HERRAMIENTAS` en
#: `apps/documents/views.py`), más los destinos geoespaciales y el grupo de texto.
FAMILIAS = ("componer", "transformar", "marcar", "proteger", "destino", "texto")


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


class TestNadaSePintaDeBlancoFuraDeLaBarra:
    """**Blanco sobre blanco: invisible, pero ahí.**

    `.boton-icono` nació para la barra navy con `color: #fff`. Después la reutilizaron las
    filas de páginas de «unir» —subir, bajar, girar, quitar— que viven dentro de una tarjeta.
    En tema oscuro la tarjeta es `#1c2634` y se veían; en claro es blanca, y los cuatro
    botones desaparecían. Se pulsaban por casualidad o no se pulsaban.

    Duró porque **solo fallaba en un tema**, y quien lo probó lo probó en oscuro.
    """

    def test_el_boton_de_icono_hereda_el_color(self, css):
        bloque = _bloque(css, "\n.boton-icono {")
        assert "#fff" not in bloque, "Vuelve a ser blanco fijo: invisible en cualquier tarjeta."
        assert "currentcolor" in bloque.lower()

    def test_y_la_barra_lo_pone_blanco_ella(self, css):
        """La barra sí es navy, así que ahí el blanco es lo correcto — pero lo declara ella."""
        assert ".barra .boton-icono" in css


class TestLosColoresDeFamilia:
    """Cada icono contra su propia baldosa, en los **tres** bloques de tema."""

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
    def test_y_en_el_oscuro_del_sistema(self, sistema_oscuro, familia):
        """**El que faltaba, y es el que más gente ve.**

        Sin declararlos aquí el bloque heredaba los del tema claro, y una baldosa `#e6eefb`
        sobre una tarjeta `#1c2634` no es un contraste malo: es una pegatina blanca. El
        cálculo no lo habría cazado nunca porque nadie leía este bloque.
        """
        color = sistema_oscuro[f"--av-fam-{familia}"]
        fondo = sistema_oscuro[f"--av-fam-{familia}-soft"]
        assert contraste(color, fondo) >= TEXTO, f"{familia} en el oscuro del sistema"

    # **Aquí NO va una prueba de «la baldosa se despega de la tarjeta».**
    #
    # Se intentó, medida con esta misma fórmula, y el resultado enseña por qué no vale: en
    # oscuro `componer` está a 1,03 de la tarjeta y se distingue sin esfuerzo. El contraste
    # de WCAG mide **luminancia**, y estas baldosas separan por **tono** — un ciruela `#46143a`
    # y un pizarra `#1c2634` tienen casi la misma luz y no se parecen en nada.
    #
    # Un umbral ajustado hasta que pasaran los seis valores actuales no afirmaría nada: sería
    # una copia de los valores con forma de prueba. Lo que sí vigila esto es el par
    # icono/baldosa, que es donde la luminancia sí es el instrumento correcto.

    @pytest.mark.parametrize("familia", FAMILIAS)
    def test_y_tambien_contra_la_tarjeta(self, claro, familia):
        """La baldosa es translúcida por el degradado, así que el icono acaba viéndose
        parcialmente contra la superficie de la tarjeta. Aquí basta el piso de lo gráfico."""
        color = claro[f"--av-fam-{familia}"]
        assert contraste(color, claro["--av-surface"]) >= GRAFICO, f"{familia} sobre tarjeta"

    def test_las_baldosas_se_distinguen_entre_si(self, claro):
        """Seis colores que no se diferencian son un color con seis nombres."""
        fondos = {claro[f"--av-fam-{f}-soft"] for f in FAMILIAS}
        assert len(fondos) == len(FAMILIAS)
        colores = {claro[f"--av-fam-{f}"] for f in FAMILIAS}
        assert len(colores) == len(FAMILIAS)

    def test_y_no_pisan_a_los_estados(self, claro):
        """Verde, ámbar y rojo significan “salió bien”, “cuidado” y “falló” en toda la
        aplicación. Una familia con uno de esos colores diría algo que no es."""
        estados = {claro["--av-ok"], claro["--av-warn"], claro["--av-danger"]}
        for familia in FAMILIAS:
            assert claro[f"--av-fam-{familia}"] not in estados
