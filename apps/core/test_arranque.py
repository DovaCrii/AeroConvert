"""Invariantes del arranque: que `run.ps1` levante algo que de verdad funciona.

Existe por un fallo que se veia como un problema de diseno y no lo era. La pantalla llegaba
con el HTML nuevo y la hoja de estilos vieja: iconos a tamano natural, la barra de
navegacion sin repartir, los pasos con vinetas. La conclusion natural es «el CSS esta mal
escrito», y estaba bien escrito.

Eran dos cosas encadenadas:

1. `taller` corre con `DEBUG=False` y con `CompressedManifestStaticFilesStorage`. Sin
   `staticfiles.json`, la primera etiqueta `{% static %}` revienta y **todas** las paginas
   devuelven 500. `run.ps1` no ejecutaba `collectstatic`, asi que el modo para el que se
   diseno la aplicacion no arrancaba en una maquina limpia.
2. Al no funcionar `taller`, lo que quedaba mirando era el servidor de desarrollo. Ahi la
   URL de un estatico no lleva huella de contenido (`/static/css/app.css`, igual hoy que
   ayer) y la respuesta no trae `Cache-Control` ni `ETag`, solo `Last-Modified`. Con eso el
   navegador aplica cache heuristica: reutiliza su copia sin preguntar.

El manifiesto arregla los dos: pone el hash en el nombre, asi que un archivo editado estrena
URL y la copia guardada deja de poder aplicarse.

Un fallo que se disfraza de error de diseno cuesta mucho mas de encontrar que uno que revienta,
y este ya se cobro una tarde. De ahi la prueba.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

from config.settings import base as ajustes_base

RUN_PS1 = Path(settings.BASE_DIR) / "scripts" / "run.ps1"


@pytest.fixture(scope="module")
def guion() -> str:
    assert RUN_PS1.exists(), f"Falta {RUN_PS1}. Si el lanzador cambio de sitio, actualiza esto."
    return RUN_PS1.read_text(encoding="utf-8")


def test_run_ps1_selecciona_un_modulo_de_ajustes(guion: str):
    """La premisa de las demas pruebas: el lanzador fija los ajustes de forma explicita."""
    assert re.search(r'DJANGO_SETTINGS_MODULE\s*=\s*"config\.settings\.\w+"', guion), (
        "run.ps1 tiene que fijar DJANGO_SETTINGS_MODULE; si no, cae en el de manage.py."
    )


def test_el_almacen_de_estaticos_exige_manifiesto(guion: str):
    """Ancla el *por que* de la prueba siguiente.

    Si algun dia se cambia el almacen por uno sin manifiesto, esta prueba falla y obliga a
    releer el razonamiento en vez de dejar una comprobacion cuyo motivo ya no existe.

    Se mira lo que declara `base.py` y no `settings` a secas: las pruebas corren con los
    ajustes de desarrollo, que a proposito sustituyen el almacen por uno sin manifiesto. Lo
    que le importa a `run.ps1` es el de `taller`, que hereda el de `base`.
    """
    backend = ajustes_base.STORAGES["staticfiles"]["BACKEND"]
    assert "Manifest" in backend or backend.startswith("apps.core.estaticos"), (
        f"El almacen de estaticos es {backend}, ya sin manifiesto. Revisa si "
        "`collectstatic` sigue siendo obligatorio antes de arrancar."
    )


def test_run_ps1_recolecta_los_estaticos_antes_de_arrancar(guion: str):
    """Y **antes**, no en cualquier orden: despues de `runserver` no sirve de nada."""
    assert "collectstatic" in guion, (
        "run.ps1 no ejecuta collectstatic. Con DEBUG=False y almacen con manifiesto, todas "
        "las paginas devuelven 500."
    )
    assert guion.index("collectstatic") < guion.index("runserver"), (
        "collectstatic aparece despues de runserver: el servidor arrancaria sin manifiesto."
    )


def test_run_ps1_no_se_recarga(guion: str):
    """Con el recargador, `runserver` son dos procesos y arrancan dos despachadores."""
    assert "--noreload" in guion
