"""La regla de las pantallas de documentos, comprobada y no prometida.

## Por qué existe este archivo

Las decisiones de forma se tomaron una por una y se fueron aplicando **pantalla a pantalla**,
que es exactamente como se pierden: se quitaron las cajas de «pega la ruta» de cinco pantallas
y quedaron tres sin tocar; se añadió el tope de subida y la barra de avance a dos y no a las
demás; y las de Markdown nacieron heredando un `accept=".pdf"` que impedía elegir un `.xlsx`.

Ese último es el que enseña el problema de fondo: **el botón estaba, la pantalla estaba, y el
archivo que hacía falta no se podía seleccionar.** Alguien del equipo lo reportó como «no
funciona», que es exactamente lo que parecía.

Un documento con la regla escrita no lo habría impedido. Esto sí.

## La regla, en cuatro puntos

1. **Ninguna pantalla pide teclear una ruta.** Dos vías: subir del propio equipo, o andar la
   carpeta compartida. En el servidor, quien pega la ruta de su equipo recibe «fuera de las
   carpetas permitidas» y no hay forma de adivinar por qué.
2. **Todo campo de archivo declara el tope**, para que el navegador lo pare antes de mandar
   nada en vez de después de subir dos gigabytes.
3. **Todo formulario que sube algo tiene dónde pintar el avance.**
4. **Ninguno filtra por un tipo que no es el suyo.**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

PANTALLAS = Path(settings.BASE_DIR) / "templates" / "documents"

#: Las que llevan formulario de archivo. `_origen.html` es el trozo compartido y se mira aparte;
#: `descargar` y `miniatura` no tienen pantalla.
CON_ARCHIVO = sorted(
    p.name
    for p in PANTALLAS.glob("*.html")
    if not p.name.startswith("_") and p.name != "inicio.html"
)


@pytest.fixture(scope="module")
def textos() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in PANTALLAS.glob("*.html")}


def _sin_comentarios(html: str) -> str:
    """El HTML de verdad, sin los bloques `comment`.

    Sin esto, un comentario que **explica** por qué ya no se piden rutas —y que por tanto
    menciona el patrón— haría fallar la prueba que comprueba que no se piden. Ha pasado.
    """
    return re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", html, flags=re.S)


class TestNadieTecleaUnaRuta:
    @pytest.mark.parametrize("pantalla", CON_ARCHIVO)
    def test_sin_caja_de_ruta_visible(self, textos, pantalla):
        """**El campo puede existir; lo que no puede es pedirse.**

        En «unir» y en «imágenes» sigue habiendo un `textarea`: es donde el explorador acumula
        lo que se pincha y es lo que viaja en el POST. Pero va `hidden`, sin etiqueta y sin
        ejemplo de `D:\\obras\\...`, porque lo que sobra es pedirle a alguien que lo escriba.
        """
        html = _sin_comentarios(textos[pantalla])
        assert "form-control ruta" not in html, f"{pantalla} enseña una caja de ruta"

    @pytest.mark.parametrize("pantalla", CON_ARCHIVO)
    def test_sin_ejemplos_de_rutas_de_windows(self, textos, pantalla):
        """Un `placeholder` con `D:\\obras\\entrega\\plano.pdf` es una instrucción: dice «aquí
        se escribe una ruta». Da igual que el campo acepte otra cosa."""
        html = _sin_comentarios(textos[pantalla])
        assert not re.search(r'placeholder="[A-Z]:\\\\', html), f"{pantalla} invita a pegar rutas"

    @pytest.mark.parametrize("pantalla", CON_ARCHIVO)
    def test_ofrece_las_dos_vias(self, textos, pantalla):
        """Subir del equipo **y** andar la carpeta compartida. Una sola deja fuera a la mitad:
        quien tiene el archivo en su portátil, o quien lo tiene en la unidad de red."""
        html = textos[pantalla]
        tiene_las_dos = '{% include "documents/_origen.html"' in html or (
            'type="file"' in html and "dashboard/_buscador.html" in html
        )
        assert tiene_las_dos, f"{pantalla} no ofrece las dos vías"


class TestElTopeYElAvance:
    @pytest.mark.parametrize("pantalla", [*CON_ARCHIVO, "_origen.html"])
    def test_todo_campo_de_archivo_declara_el_tope(self, textos, pantalla):
        """Sin `data-tope-mb`, el navegador manda el archivo entero y el servidor lo corta a
        mitad. Es lo que le pasó a una ortofoto de 600 MB: minutos de subida para recibir
        «No llegó ningún archivo»."""
        html = _sin_comentarios(textos[pantalla])
        for campo in re.findall(r"<input[^>]*type=\"file\"[^>]*>", html):
            assert "data-tope-mb" in campo, f"{pantalla}: un campo de archivo sin tope"

    @pytest.mark.parametrize("pantalla", [*CON_ARCHIVO, "_origen.html"])
    def test_donde_se_sube_hay_donde_pintar_el_avance(self, textos, pantalla):
        """Un archivo grande sin barra deja la pantalla quieta durante minutos, sin
        porcentaje, sin tiempo y sin forma de saber si sigue viva."""
        html = _sin_comentarios(textos[pantalla])
        if 'type="file"' not in html:
            return
        assert "data-avance-subida" in html, f"{pantalla} sube sin sitio para el avance"


class TestLoQueHayQueSaberVaDelante:
    """**Lo que hace falta para decidir se lee antes de decidir.**

    Las advertencias de cada pantalla —de qué formatos se saca, qué se pierde por el camino,
    qué se comprueba— vivían en una tarjeta al final, debajo del formulario y del resultado.
    Quien bajaba hasta ahí lo hacía porque algo le había salido raro; quien no bajaba, no se
    enteraba nunca.

    Es la misma clase de error que el `accept=".pdf"` heredado: la información estaba, y en un
    sitio donde no servía.
    """

    #: Las que avisan de algo que cambia la decisión: qué entra, qué se pierde, qué se
    #: comprueba. Las de PDF puro no lo necesitan — «Unir PDF» no tiene letra pequeña.
    CON_AVISO = [
        "a_markdown.html",
        "de_markdown.html",
        "catalogo_a_excel.html",
        "excel_a_catalogo.html",
    ]

    @pytest.mark.parametrize("pantalla", CON_AVISO)
    def test_el_aviso_va_antes_del_formulario(self, textos, pantalla):
        html = _sin_comentarios(textos[pantalla])
        assert "antes-de-empezar" in html, f"{pantalla} no dice qué va a pasar"
        assert html.index("antes-de-empezar") < html.index("<form"), (
            f"{pantalla} lo dice después del formulario, que es cuando ya no sirve"
        )


class TestElFiltroDeTipo:
    """**El fallo que se reportó como «no funciona».**

    `_origen.html` traía `accept=".pdf"` fijo. Las pantallas de Markdown lo heredaron, así que
    el diálogo del sistema no dejaba elegir un `.xlsx`: el botón estaba, la pantalla estaba, y
    el archivo que hacía falta no se podía seleccionar.
    """

    def test_el_trozo_compartido_deja_cambiar_el_filtro(self, textos):
        assert "acepta|default:'.pdf'" in textos["_origen.html"], (
            "`accept` volvió a estar fijo: cualquier pantalla que no sea de PDF queda rota."
        )

    @pytest.mark.parametrize(
        ("pantalla", "extension"),
        [
            ("a_markdown.html", ".xlsx"),
            ("de_markdown.html", ".md"),
            ("office.html", ".docx"),
            ("catalogo_a_excel.html", ".mdb"),
            ("excel_a_catalogo.html", ".xlsx"),
        ],
    )
    def test_cada_pantalla_acepta_lo_suyo(self, textos, pantalla, extension):
        assert extension in textos[pantalla], f"{pantalla} no deja elegir un {extension}"
