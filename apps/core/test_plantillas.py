"""Invariantes de las plantillas.

Existe porque el mismo fallo apareció **dos veces**: un comentario escrito como `{# … #}`
repartido en varias líneas. Django solo trata esa forma como comentario cuando abre y
cierra en la misma línea; en varias, la imprime literal en la página.

Y no falla de forma ruidosa. La plantilla renderiza, la prueba de la vista pasa, el gate se
pone verde — y el texto aparece en pantalla, delante de quien esté mirando. La primera vez
salió en el recibo de una conversión; la segunda, en la portada.

Cuando algo se rompe dos veces del mismo modo, el arreglo no es tener más cuidado.
"""

from pathlib import Path

import pytest
from django.conf import settings

CARPETA = Path(settings.BASE_DIR) / "templates"


def _plantillas():
    return sorted(CARPETA.rglob("*.html"))


def test_hay_plantillas_que_revisar():
    """Si la carpeta cambia de sitio, esta prueba avisa en vez de pasar vacía."""
    assert _plantillas()


@pytest.mark.parametrize("plantilla", _plantillas(), ids=lambda p: p.name)
def test_ningun_comentario_corto_se_queda_abierto(plantilla):
    """`{# … #}` tiene que abrir y cerrar en la misma línea.

    Para un comentario de varias líneas existe `{% comment %}`, y es lo que hay que usar.
    """
    for numero, linea in enumerate(plantilla.read_text(encoding="utf-8").splitlines(), 1):
        if "{#" in linea and "#}" not in linea:
            raise AssertionError(
                f"{plantilla.name}:{numero} abre un comentario «{{#» que no cierra en la "
                "misma línea. Django lo imprimirá tal cual en la página. "
                "Usa {% comment %} … {% endcomment %}."
            )


@pytest.mark.parametrize("plantilla", _plantillas(), ids=lambda p: p.name)
def test_todo_comment_se_cierra(plantilla):
    """El error simétrico: un `{% comment %}` sin su cierre se come el resto de la página."""
    texto = plantilla.read_text(encoding="utf-8")
    assert texto.count("{% comment %}") == texto.count("{% endcomment %}"), (
        f"{plantilla.name}: hay {texto.count('{% comment %}')} aperturas de comentario y "
        f"{texto.count('{% endcomment %}')} cierres."
    )
