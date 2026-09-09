"""Los estaticos: el manifiesto y el SRI.

Las dos comprobaciones de aqui vigilan fallos que **no revientan**. La pagina responde 200,
el gate se pone verde, y lo que llega a la pantalla es una maqueta sin estilos que se lee
como un error de diseno. Ese sintoma ya costo una tarde.
"""

import base64
import hashlib
import re
from pathlib import Path

import pytest
from django.conf import settings
from whitenoise.storage import CompressedManifestStaticFilesStorage

from apps.core.estaticos import MARCA_DE_MAPA, AlmacenDeEstaticos
from config.settings import base as ajustes_base

BASE_HTML = Path(settings.BASE_DIR) / "templates" / "base.html"


def _patrones_planos(patrones):
    for _glob, reglas in patrones:
        for regla in reglas:
            yield regla[0] if isinstance(regla, (tuple, list)) else regla


class TestElAlmacenNoPersigueLosMapasDeFuentes:
    """Un `.map` ausente no puede tumbar `collectstatic`. Ver `estaticos.py`."""

    def test_el_padre_si_los_persigue(self):
        """La premisa.

        Si una version de Django deja de traer el patron, esta prueba falla y avisa de que
        el filtro ya no hace nada, en vez de quedarse ahi dando una falsa sensacion.
        """
        assert any(
            MARCA_DE_MAPA in p
            for p in _patrones_planos(CompressedManifestStaticFilesStorage.patterns)
        ), (
            "El almacen de whitenoise ya no trae el patron de sourceMappingURL. Revisa si "
            "apps/core/estaticos.py sigue haciendo falta."
        )

    def test_el_nuestro_no(self):
        assert not any(MARCA_DE_MAPA in p for p in _patrones_planos(AlmacenDeEstaticos.patterns))

    def test_no_se_pierde_ningun_otro_patron(self):
        """Filtrar de menos rompe el arranque; filtrar de mas rompe las rutas dentro del CSS."""
        del_padre = [
            p
            for p in _patrones_planos(CompressedManifestStaticFilesStorage.patterns)
            if MARCA_DE_MAPA not in p
        ]
        assert list(_patrones_planos(AlmacenDeEstaticos.patterns)) == del_padre

    def test_el_almacen_configurado_es_el_nuestro(self):
        """En `base.py`, que es de donde lo heredan `taller` y `prod`.

        `dev` lo sustituye a proposito por uno sin manifiesto, asi que mirar `settings` a
        secas comprobaria justo el modo al que esto no le afecta.
        """
        backend = ajustes_base.STORAGES["staticfiles"]["BACKEND"]
        assert backend == "apps.core.estaticos.AlmacenDeEstaticos"


def _parejas_de_sri():
    """Saca de `base.html` las parejas (archivo vendorizado, hash declarado).

    Se apoya en que el `integrity` va en la misma etiqueta que el `href`/`src`, que es la
    unica forma en que el navegador los relaciona.
    """
    texto = BASE_HTML.read_text(encoding="utf-8")
    for etiqueta in re.findall(r"<(?:link|script)\b[^>]*>", texto, flags=re.S):
        integridad = re.search(r'integrity="(sha384-[^"]+)"', etiqueta)
        recurso = re.search(r"""\{%\s*static\s*['"]([^'"]+)['"]\s*%\}""", etiqueta)
        if integridad and recurso:
            yield recurso.group(1), integridad.group(1)


def _sri(ruta: Path) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(ruta.read_bytes()).digest()).decode()


def test_hay_recursos_con_sri_que_revisar():
    """Si la plantilla deja de declarar SRI, esto avisa en vez de pasar vacio."""
    assert list(_parejas_de_sri()), "base.html no declara ningun integrity."


@pytest.mark.parametrize("recurso,declarado", list(_parejas_de_sri()), ids=lambda v: str(v))
def test_el_sri_declarado_cuadra_con_el_archivo(recurso, declarado):
    """Un hash desparejado no da error visible: el navegador **descarta** el recurso.

    Descartada la hoja de Bootstrap, la pagina sale sin rejilla, sin tipografia y sin
    tabla — indistinguible de un CSS mal escrito. Por eso se comprueba aqui y no a ojo.

    Se hashea el archivo de `static/`, que es el que se vendoriza. El de `staticfiles/` sale
    de este por copia y el manifiesto no reescribe nada dentro de estos dos (comprobado:
    los hashes coinciden en los tres sitios).
    """
    if declarado.startswith("sha384-") is False:  # pragma: no cover - defensa del parser
        pytest.fail(f"{recurso}: el integrity no es sha384.")
    ruta = Path(settings.BASE_DIR) / "static" / recurso
    assert ruta.exists(), f"{recurso} se declara con SRI en base.html pero no esta en static/."
    assert _sri(ruta) == declarado, (
        f"{recurso}: el integrity de base.html no corresponde al archivo.\n"
        f"  declarado: {declarado}\n"
        f"  archivo:   {_sri(ruta)}\n"
        "El navegador descartaria el recurso y la pagina saldria sin estilos. Si "
        "re-vendorizaste el archivo, actualiza el hash en la plantilla."
    )
