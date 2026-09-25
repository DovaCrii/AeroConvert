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
    """El que se lee. La cabecera del CSS promete 7,2:1 en claro y 8,3:1 en oscuro.

    Prometía 8,9 en oscuro, y medía 8,30: la cifra se escribió una vez y nada la comprobaba.
    """

    def test_las_cifras_de_la_cabecera_son_las_que_miden(self, claro, oscuro):
        assert round(contraste(claro["--av-primary"], claro["--av-surface"]), 1) == 7.2
        assert round(contraste(oscuro["--av-primary"], oscuro["--av-surface"]), 1) == 8.3

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


class TestElTextoAtenuado:
    """`--av-text-muted`, que es **el color de casi todo el texto secundario**.

    `.tenue` lo usa en cada tarjeta, en cada nota al pie, en cada «sale de…» y en la tecla
    que enseña el atajo. Es el segundo color más leído de la aplicación y no lo sostenía
    nada — un retoque de medio tono para «suavizarlo» lo habría bajado de AA en las tres
    pantallas a la vez sin que ninguna prueba dijera nada.

    **Contra las dos superficies**, no solo contra la principal: la alterna es más oscura en
    claro y más clara en oscuro, así que es siempre la peor de las dos, y es justo donde vive
    la tecla del atajo.
    """

    @pytest.mark.parametrize("fondo", ["--av-surface", "--av-surface-alt"])
    def test_en_claro(self, claro, fondo):
        assert contraste(claro["--av-text-muted"], claro[fondo]) >= TEXTO, fondo

    @pytest.mark.parametrize("fondo", ["--av-surface", "--av-surface-alt"])
    def test_en_oscuro(self, oscuro, fondo):
        assert contraste(oscuro["--av-text-muted"], oscuro[fondo]) >= TEXTO, fondo

    @pytest.mark.parametrize("fondo", ["--av-surface", "--av-surface-alt"])
    def test_y_en_el_oscuro_del_sistema(self, sistema_oscuro, fondo):
        """El bloque que manda por omisión, y el que ya se olvidó una vez con las familias."""
        assert contraste(sistema_oscuro["--av-text-muted"], sistema_oscuro[fondo]) >= TEXTO, fondo


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


# --- La tabla: todos los pares que se leen, en los tres temas --------------------
#
# **Por qué una tabla y no una clase por par.** La auditoría de la fase 9 midió siete pares
# por debajo de WCAG que ninguna prueba miraba: el foco sobre la barra (1,97), el borde del
# buscador (2,02), el rojo sobre su fondo (4,23), dos píldoras de estado y el atenuado sobre
# el fondo del menú. Cada uno era un par que a nadie se le ocurrió escribir. Una tabla hace
# que añadir un par sea añadir una línea, y que los tres temas salgan gratis.
#
# Los temas se miran **como los ve el navegador**: el oscuro hereda de `:root` lo que no
# redefine, y un `var()` se resuelve con el tema que manda. Leer cada bloque por separado,
# como hacen las pruebas de arriba, no ve un token declarado una sola vez en `:root` que
# apunta a otro que el oscuro sí cambia —`--av-link: var(--av-primary)`—.

#: La barra. No son tokens: el degradado va de este al navy.
NAVY = "#1b2a4a"
NAVY_ARRIBA = "#22335a"
BLANCO = "#ffffff"


def _rgb(color) -> tuple[int, int, int]:
    if isinstance(color, tuple):
        return color
    crudo = color.lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    return tuple(int(crudo[i : i + 2], 16) for i in (0, 2, 4))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def mezcla(color: str, fondo: str, alfa: float) -> str:
    """Lo que se ve de un color con transparencia sobre un fondo opaco.

    Es lo que hace `color-mix(in srgb, X 14%, transparent)` una vez pintado sobre la tarjeta,
    y lo que hace `rgb(255 255 255 / 45%)` sobre la barra. Medir el color sin mezclar daría un
    contraste que no existe en pantalla.
    """
    arriba, abajo = _rgb(color), _rgb(fondo)
    return _hex(tuple(round(alfa * a + (1 - alfa) * b) for a, b in zip(arriba, abajo, strict=True)))


def _crudas(bloque: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"(--av-[a-z-]+)\s*:\s*([^;]+);", bloque)}


def _resolver(crudas: dict[str, str]) -> dict[str, str]:
    resueltas: dict[str, str] = {}
    for nombre, valor in crudas.items():
        for _ in range(5):  # cadenas de var() cortas; cinco saltos sobran
            apunta = re.fullmatch(r"var\((--av-[a-z-]+)\)", valor)
            if not apunta:
                break
            valor = crudas.get(apunta.group(1), "")
        if valor.startswith("#"):
            resueltas[nombre] = valor
    return resueltas


@pytest.fixture(scope="module")
def temas(css: str) -> dict[str, dict[str, str]]:
    base = _crudas(_bloque(css, ":root {"))
    return {
        "claro": _resolver(base),
        "oscuro": _resolver({**base, **_crudas(_bloque(css, ':root[data-theme="dark"]'))}),
        "sistema": _resolver({**base, **_crudas(_bloque(css, ':root:not([data-theme="light"])'))}),
    }


def _par(tema: dict[str, str], valor: str) -> str:
    return tema[valor] if valor.startswith("--") else valor


def _pildora(estado: str):
    """La píldora pinta su texto sobre el 14 % de su propio color encima de la tarjeta."""
    return lambda t: (t[estado], mezcla(t[estado], t["--av-surface"], 0.14))


def _sobre_barra(color: str, alfa: float):
    """Algo translúcido sobre la barra, medido contra la barra."""
    return lambda t: (mezcla(color, NAVY, alfa), NAVY)


#: (nombre, cómo sacar el par de un tema, piso). El par es (primer plano, fondo).
PARES = [
    # El texto, sobre los tres fondos donde vive.
    *[
        (f"{texto} sobre {fondo}", (texto, fondo), TEXTO)
        for texto in ("--av-text", "--av-text-secondary", "--av-text-muted")
        for fondo in ("--av-surface", "--av-surface-alt", "--av-bg")
    ],
    # El atenuado sobre el fondo del menú al pasar por encima: 4,32 antes de la fase 9.
    ("atenuado sobre primary-soft", ("--av-text-muted", "--av-primary-soft"), TEXTO),
    ("secundario sobre primary-soft", ("--av-text-secondary", "--av-primary-soft"), TEXTO),
    # Los enlaces: no había token y se pintaban con el azul de Bootstrap.
    *[
        (f"enlace sobre {fondo}", ("--av-link", fondo), TEXTO)
        for fondo in ("--av-surface", "--av-surface-alt", "--av-bg")
    ],
    ("enlace al pasar por encima", ("--av-link-hover", "--av-surface"), TEXTO),
    # Cada estado, sobre su fondo suave (`.aviso`, `.error`, `.mensaje-*`) y en su píldora.
    *[
        (f"{estado} sobre su fondo", (f"--av-{estado}", f"--av-{estado}-soft"), TEXTO)
        for estado in ("ok", "warn", "danger", "info")
    ],
    ("píldora hecho", _pildora("--av-ok"), TEXTO),
    ("píldora error", _pildora("--av-danger"), TEXTO),
    ("píldora en curso", _pildora("--av-primary"), TEXTO),
    ("píldora cancelado", _pildora("--av-text-muted"), TEXTO),
    # El texto dentro del botón principal, en reposo y al pasar por encima.
    ("texto sobre acción", ("--av-sobre-accion", "--av-primary"), TEXTO),
    ("texto sobre acción, hover", ("--av-sobre-accion", "--av-primary-hover"), TEXTO),
    # Lo que no es texto: el borde que dice «aquí se escribe», y el anillo de foco.
    *[
        (f"borde de control sobre {fondo}", ("--av-border-control", fondo), GRAFICO)
        for fondo in ("--av-surface", "--av-surface-alt", "--av-bg")
    ],
    *[
        (f"foco sobre {fondo}", ("--av-foco", fondo), GRAFICO)
        for fondo in ("--av-surface", "--av-surface-alt", "--av-bg")
    ],
    # La barra es navy en los tres temas, y ahí el foco de todo lo demás daba 1,97.
    ("foco sobre la barra", ("--av-foco-barra", NAVY), GRAFICO),
    ("foco sobre lo alto de la barra", ("--av-foco-barra", NAVY_ARRIBA), GRAFICO),
    ("borde del buscador de la barra", _sobre_barra(BLANCO, 0.45), GRAFICO),
    # La barra de progreso: el relleno es lo que informa, contra la pista y la tarjeta.
    ("relleno del progreso sobre su pista", ("--av-primary", "--av-border"), GRAFICO),
]


@pytest.mark.parametrize("tema", ["claro", "oscuro", "sistema"])
@pytest.mark.parametrize(("nombre", "par", "piso"), PARES, ids=[p[0] for p in PARES])
def test_cada_par_llega_a_su_piso(temas, tema, nombre, par, piso):
    colores = temas[tema]
    delante, detras = (
        par(colores) if callable(par) else (_par(colores, par[0]), _par(colores, par[1]))
    )
    medido = contraste(delante, detras)
    assert medido >= piso, f"{nombre} en {tema}: {medido:.2f}:1 ({delante} sobre {detras})"


class TestLoQueUsaLosTokens:
    """Un token que pasa y una regla que no lo usa es lo mismo que no tener el token."""

    def test_el_foco_de_la_barra_usa_su_color(self, css):
        assert "outline-color: var(--av-foco-barra)" in _bloque(css, ".barra :focus-visible")

    def test_el_buscador_de_la_barra_tiene_el_borde_que_se_mide(self, css):
        """La fila de la tabla mide el 45 %; si la regla vuelve al 22 %, esto lo dice."""
        assert "rgb(255 255 255 / 45%)" in _bloque(css, "\n.buscador-barra input {")

    def test_los_enlaces_usan_el_token(self, css):
        assert "var(--av-link)" in _bloque(css, "\na {")

    def test_enfocar_un_campo_pone_un_anillo_y_no_solo_cambia_el_borde(self, css):
        """Entre el borde gris y el magenta había 2,09:1, con el mismo grosor."""
        bloque = _bloque(css, ".form-control:focus,")
        assert "outline: 2px solid var(--av-foco)" in bloque


class TestLoQueSePulsaMideAlMenos24:
    """WCAG 2.5.8: 24 × 24 px para algo que se pulsa. Las migas del explorador medían ~20."""

    @pytest.mark.parametrize("selector", ["\n.miga {", "\n.ejemplo {", "\n.boton-pequeno {"])
    def test_tiene_alto_minimo(self, css, selector):
        encontrado = re.search(r"min-height:\s*(\d+)px", _bloque(css, selector))
        assert encontrado, f"{selector.strip()} sin min-height en px"
        assert int(encontrado.group(1)) >= 24


class TestLaPaginaDeError:
    """`500.html` no puede cargar `app.css` —ver `HANDOFF.md`—, así que copia los colores.

    Y la copia se desvió: el fondo oscuro era `#131a26` cuando el token es `#0e141d`. Aquí se
    exige que cada color que escribe sea el de algún token de los dos temas.
    """

    def test_cada_color_es_de_la_paleta(self, temas):
        pagina = (Path(settings.BASE_DIR) / "templates" / "500.html").read_text(encoding="utf-8")
        tokens = {_hex(_rgb(v)) for t in temas.values() for v in t.values()}
        tokens |= {NAVY, BLANCO}
        usados = {_hex(_rgb(c)) for c in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", pagina)}
        assert usados - tokens == set()
