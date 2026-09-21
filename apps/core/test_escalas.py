"""Las escalas del sistema visual: que existan, que estén completas, y que se usen.

## Por qué hace falta vigilarlas

El 2026-09-21 se auditó la hoja de estilos y salió esto: **cero tokens de espaciado**, 17
valores distintos de `gap` que no forman progresión, 24 tamaños de letra —el 43 % escritos a
mano—, y **`--av-fs-base` y `--av-fs-xl` definidos y sin usar ni una sola vez**.

Ese último detalle es el que explica por qué esta prueba existe y no basta con un documento:
**los tokens ya estaban; nadie los usó**. Una escala que nadie aplica no es una escala, es una
lista de buenas intenciones al principio de un fichero.

## Lo que NO comprueba, y a propósito

No comprueba que el CSS sea bonito ni que las medidas estén bien elegidas. Comprueba tres
cosas que sí son verificables: que la escala **exista**, que no tenga **huecos**, y que no haya
**tokens muertos**. Lo demás lo decide el ojo, y para eso están las capturas.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


def _declarados(css: str) -> set[str]:
    return set(re.findall(r"(--av-[a-z0-9-]+)\s*:", css))


def _usados(css: str) -> set[str]:
    return set(re.findall(r"var\(\s*(--av-[a-z0-9-]+)", css))


class TestLaEscalaDeEspaciado:
    """Base 4, que es la de Primer. No había ninguna."""

    def test_existe_y_no_tiene_huecos(self, css):
        escala = _declarados(css) & {f"--av-s-{n}" for n in range(1, 13)}
        assert escala, "Desapareció la escala de espaciado."
        # Los pasos bajos son los que se usan a diario: si falta uno, el sitio que lo
        # necesitaba volverá a escribir un píxel a mano.
        for n in (1, 2, 3, 4, 5, 6):
            assert f"--av-s-{n}" in escala, f"Falta el paso {n}"

    def test_cada_paso_es_multiplo_de_cuatro(self, css):
        for nombre, valor in re.findall(r"(--av-s-\d+)\s*:\s*(\d+)px", css):
            assert int(valor) % 4 == 0, f"{nombre} vale {valor}px y rompe la base 4"

    def test_hay_un_ritmo_vertical_con_nombre(self, css):
        """El ritmo entre bloques vivía en un `style="margin-bottom:14px"` escrito a mano 19
        veces. Tener el token es la condición para poder vaciarlos."""
        assert "--av-ritmo" in _declarados(css)


class TestLaEscalaDeElevacion:
    """Tres niveles con papel asignado, como Radix. Había dos y de un salto enorme."""

    @pytest.mark.parametrize("nivel", ["--av-elev-0", "--av-elev-1", "--av-elev-2", "--av-elev-3"])
    def test_estan_los_cuatro(self, css, nivel):
        assert nivel in _declarados(css)

    def test_el_anillo_va_dentro_de_la_sombra(self, css):
        """**El cambio con más efecto por línea tocada.** Hoy la profundidad se sustituye por
        `border: 1px solid var(--av-border)` —19 veces literal— y así el borde y la sombra son
        dos decisiones que nadie coordina. Con el anillo dentro, son una."""
        bloque = css[css.index("--av-elev-1:") : css.index("--av-elev-2:")]
        assert "0 0 0 1px" in bloque

    def test_cada_nivel_lleva_dos_capas(self, css):
        """Primer se mueve entre el 3 % y el 12 % con dos capas. Una sombra sola y marcada es
        lo que delata una interfaz hecha a ojo."""
        for nivel in ("--av-elev-1", "--av-elev-2", "--av-elev-3"):
            inicio = css.index(f"{nivel}:")
            bloque = css[inicio : css.index(";", inicio)]
            # Se cuentan las capas, no los `rgb(`: el anillo usa `var(--av-anillo)` y no
            # lleva ninguno. Contar colores daba dos y la prueba fallaba por su propia culpa.
            assert bloque.count(",") >= 2, f"{nivel} no tiene anillo y dos capas"

    def test_usa_spread_negativo(self, css):
        """Recoge la sombra hacia dentro y evita el halo gris sucio. Es de Polaris."""
        inicio = css.index("--av-elev-2:")
        assert re.search(r"-\d+px", css[inicio : css.index(";", inicio)])

    def test_los_tres_bloques_de_tema_la_declaran(self, css):
        """El de `prefers-color-scheme` es el que manda por omisión, y ya se olvidó una vez
        con los colores de familia: se heredaban los del tema claro."""
        assert css.count("--av-elev-1:") == 3


class TestLaEscalaTipografica:
    """Siete escalones, no veintiocho."""

    ESCALONES = ["xs", "sm", "base", "md", "lg", "xl", "2xl"]

    @pytest.mark.parametrize("paso", ESCALONES)
    def test_estan_los_siete(self, css, paso):
        assert f"--av-fs-{paso}" in _declarados(css)

    def test_los_pasos_crecen(self, css):
        valores = [
            float(re.search(rf"--av-fs-{p}:\s*([\d.]+)rem", css).group(1)) for p in self.ESCALONES
        ]
        assert valores == sorted(valores), f"La escala no es monótona: {valores}"

    def test_no_hay_dos_pasos_indistinguibles(self, css):
        """**El núcleo del problema.** Había nueve tamaños entre 0,82 y 0,95 rem, ninguno
        distinguible de su vecino — y eso es la sensación de planitud: sin saltos claros no
        hay jerarquía, por mucha sombra que se añada."""
        valores = [
            float(re.search(rf"--av-fs-{p}:\s*([\d.]+)rem", css).group(1)) for p in self.ESCALONES
        ]
        for menor, mayor in zip(valores, valores[1:], strict=False):
            assert mayor / menor >= 1.07, f"{menor}rem y {mayor}rem no se distinguen"

    def test_hay_con_que_marcar_jerarquia_sin_tocar_el_tamano(self, css):
        """Material distingue dos roles distintos a 16 px usando solo **peso y tracking**.
        Sin tokens de peso no se puede hacer eso, y solo queda subir el tamaño."""
        declarados = _declarados(css)
        assert {"--av-peso-medio", "--av-peso-fuerte"} <= declarados
        assert {"--av-alto-apretado", "--av-alto-normal"} <= declarados


class TestQueNoHayaTokensMuertos:
    """**La prueba que justifica todas las demás.**

    `--av-fs-base` y `--av-fs-xl` estaban definidos y no se usaban ni una sola vez, y
    `--av-fs-lg` se usaba una. De cinco tokens tipográficos, dos eran código muerto.

    Un token que nadie usa no es neutro: hace creer que hay un sistema donde no lo hay, y el
    siguiente que llega escribe su píxel a mano porque «total, esto no se usa».
    """

    #: Los que se declaran para que estén disponibles aunque hoy no toque usarlos. Cada uno
    #: con su motivo, para que la lista no se convierta en el cajón donde se esconde todo.
    PERMITIDOS = {
        # Se retiran al aplicar la elevación, en la tanda siguiente. Hoy lo usa `.menu-panel`
        # y el objetivo de esta tanda es no mover nada.
        "--av-shadow-alto",
        # Escalones altos: entran al vaciar los estilos en línea de las plantillas.
        "--av-s-10",
        "--av-s-12",
        # Niveles de elevación que se aplican en la tanda siguiente. Van en la lista con
        # fecha: si siguen aquí dentro de dos tandas, es que la siguiente no llegó.
        "--av-elev-0",
        "--av-elev-1",
        "--av-elev-2",
        "--av-elev-3",
        # El peso normal es el de fábrica del navegador, así que casi nunca hay que
        # declararlo. Está para poder **volver** a normal dentro de un bloque que lo subió.
        "--av-peso-normal",
    }

    def test_todo_token_declarado_se_usa(self, css):
        muertos = _declarados(css) - _usados(css) - self.PERMITIDOS
        assert not muertos, (
            f"Tokens declarados y sin usar: {sorted(muertos)}. "
            "O se usan, o se borran, o se añaden a PERMITIDOS con su motivo escrito."
        )

    def test_y_todo_token_usado_esta_declarado(self, css):
        """El fallo simétrico: un `var()` a un token que no existe no da error, se queda con
        el valor de respaldo — o con nada, y entonces la regla entera se descarta."""
        fantasmas = _usados(css) - _declarados(css)
        assert not fantasmas, f"Se usan tokens que nadie declara: {sorted(fantasmas)}"
