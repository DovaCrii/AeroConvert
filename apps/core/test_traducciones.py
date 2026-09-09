"""El catálogo de traducción: que exista, que esté completo, y que el `.mo` esté al día.

Existe por un fallo que no daba ningún error y se veía en cada pantalla: la aplicación
declara `LANGUAGE_CODE = "es"` y escribe los msgid en inglés —que es la convención de
gettext— pero **el catálogo español nunca se creó**. Sin él, Django cae al msgid, así que la
píldora de un trabajo terminado decía `Done` y la etapa decía `Conversion`.

Y el fallo que viene después es peor, porque es intermitente: el `.mo` es lo que Django lee
de verdad, y se genera del `.po` con `compilemessages`. Editar el `.po` y olvidar compilar
deja la traducción vieja aplicándose, sin aviso. Por eso aquí se compara **lo compilado**
contra **lo escrito**, y no el `.po` consigo mismo.
"""

import gettext
import re
from pathlib import Path

import pytest
from django.conf import settings

CARPETA = Path(settings.BASE_DIR) / "locale"
PO = CARPETA / "es" / "LC_MESSAGES" / "django.po"
MO = CARPETA / "es" / "LC_MESSAGES" / "django.mo"

#: Un `.po` es texto plano: entradas separadas por una línea en blanco, con `msgid` y
#: `msgstr` que pueden venir partidos en varias líneas entre comillas.
ENTRADA = re.compile(
    r'^msgid\s+((?:"[^"]*"\s*)+)^msgstr\s+((?:"[^"]*"\s*)+)',
    re.MULTILINE,
)


def _juntar(bloque: str) -> str:
    """`"uno" "dos"` en varias líneas -> `unodos`."""
    return "".join(re.findall(r'"([^"]*)"', bloque))


def _entradas() -> dict[str, str]:
    texto = PO.read_text(encoding="utf-8")
    return {
        _juntar(msgid): _juntar(msgstr)
        for msgid, msgstr in ENTRADA.findall(texto)
        if _juntar(msgid)  # la primera entrada, con msgid vacío, es la cabecera
    }


def test_el_catalogo_existe():
    """Si falta, la interfaz sale en inglés y nadie se entera hasta verla."""
    assert PO.is_file(), f"Falta {PO}. Genéralo con `manage.py makemessages -l es`."


def test_el_compilado_existe_y_se_versiona():
    """Es lo que Django lee de verdad.

    Se versiona a propósito: `compilemessages` necesita `msgfmt` en la máquina, y la promesa
    de esta aplicación es «un `.ps1` y listo». Ver el comentario en `.gitignore`.
    """
    assert MO.is_file(), (
        f"Falta {MO}. Compílalo con "
        "`manage.py compilemessages --ignore=.venv --ignore=staticfiles`."
    )


def test_no_queda_ninguna_cadena_sin_traducir():
    sin_traducir = sorted(clave for clave, valor in _entradas().items() if not valor)
    assert not sin_traducir, (
        f"Estas cadenas se quedaron sin traducir y saldrán en inglés: {sin_traducir}"
    )


def test_no_queda_ninguna_marcada_como_dudosa():
    """`#, fuzzy` es una traducción que gettext **no aplica**: sale el inglés igual."""
    assert "#, fuzzy" not in PO.read_text(encoding="utf-8")


@pytest.mark.parametrize("msgid,msgstr", sorted(_entradas().items()))
def test_lo_compilado_coincide_con_lo_escrito(msgid, msgstr):
    """El `.mo` al día respecto del `.po`.

    Es la comprobación que atrapa el olvido de recompilar, que no da error y deja la
    traducción vieja aplicándose.
    """
    catalogo = gettext.translation("django", localedir=str(CARPETA), languages=["es"])
    assert catalogo.gettext(msgid) == msgstr, (
        f"«{msgid}» está traducido como «{msgstr}» en el .po pero el .mo dice "
        f"«{catalogo.gettext(msgid)}». Falta recompilar."
    )


def test_los_estados_de_un_trabajo_salen_en_espanol():
    """La prueba de arriba compara archivos; esta comprueba lo que llega a la pantalla.

    `Done` en la píldora de un trabajo terminado fue el síntoma que destapó todo esto.
    """
    from django.utils import translation

    from apps.jobs.models import ESTADOS, HECHO

    with translation.override("es"):
        por_codigo = {codigo: str(etiqueta) for codigo, etiqueta in ESTADOS}
        assert por_codigo[HECHO] == "Hecho"
        assert "Done" not in por_codigo.values()
