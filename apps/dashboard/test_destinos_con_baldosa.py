"""F7.2c: los destinos de la ficha son tarjetas con su baldosa y su «Sale:», como en la portada."""

from __future__ import annotations

import dataclasses
import re

import pytest
from django.contrib.auth import get_user_model

from apps.dashboard.acciones import ICONOS_DE_PERFIL
from apps.dashboard.views import DestinoOfrecido
from apps.formats.tests.constructor import bigtiff_minimo
from apps.targets import perfiles as perfiles_mod

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.MODO = "taller"
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


@pytest.fixture
def ortofoto(tmp_path):
    ruta = tmp_path / "Cruce Minero.tif"
    ruta.write_bytes(bigtiff_minimo(bandas=4, alfa=True, compresion=5))
    return ruta


@pytest.fixture
def con_motor():
    """Un motor de mentira que sabe los pasos de una ortofoto: sin él, en una máquina sin GDAL,
    todos los destinos salen apagados y no hay baldosa de uno encendido que mirar."""
    from apps.engines import registry
    from apps.engines.testing import MotorDeMentira

    guardado = registry.todos()
    registry.limpiar()
    registry.registrar(MotorDeMentira("mentira", (("bigtiff", "geotiff"), ("geotiff", "cog"))))
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


def _fichas(cuerpo: str) -> list[str]:
    """El HTML de cada botón de destino."""
    return re.findall(
        r'<button type="submit" name="perfil" value="[^"]+".*?</button>', cuerpo, re.S
    )


class TestLaBaldosa:
    def test_cada_destino_trae_su_icono_y_su_sale(self, sesion, ortofoto, con_motor):
        cuerpo = sesion.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        botones = [b for b in _fichas(cuerpo) if "disabled" not in b.split(">", 1)[0]]
        assert botones, "una ortofoto tiene destinos que sí se pueden"
        for boton in botones:
            assert "destino-marca" in boton, "falta la baldosa"
            assert "Sale:" in boton, "falta el formato de salida"
            assert 'aria-hidden="true"' in boton, "el icono es decoración"

    def test_el_icono_es_el_del_perfil_en_la_portada(self):
        for perfil_id, icono in ICONOS_DE_PERFIL.items():
            perfil = perfiles_mod.PERFILES[perfil_id]
            assert DestinoOfrecido(perfil=perfil, se_puede=True).icono == icono

    def test_un_perfil_sin_icono_propio_cae_al_generico(self):
        sin_icono = dataclasses.replace(perfiles_mod.QGIS, id="perfil-sin-icono")
        assert DestinoOfrecido(perfil=sin_icono, se_puede=True).icono == "icon-destino"

    def test_todo_perfil_de_fabrica_tiene_icono_propio(self):
        """Antes el de GNSS caía en la diana genérica, que no dice nada de un receptor."""
        assert set(perfiles_mod.PERFILES) <= set(ICONOS_DE_PERFIL)

    def test_los_apagados_siguen_diciendo_por_que_y_no_prometen_un_sale(
        self, sesion, ortofoto, con_motor
    ):
        """Regla 4: se apagan con motivo. Con un motor que solo sabe unos pasos, los demás
        destinos salen apagados: sin «Sale:» —no se puede— pero con su baldosa y su motivo."""
        cuerpo = sesion.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        apagados = [b for b in _fichas(cuerpo) if "disabled" in b.split(">", 1)[0]]
        assert apagados, "con un motor incompleto, algún destino tiene que salir apagado"
        for boton in apagados:
            assert "Sale:" not in boton
            assert "destino-marca" in boton
