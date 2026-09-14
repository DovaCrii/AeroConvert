"""Leer ECW y MrSID: capacidades que dependen de con qué se compiló GDAL.

## El verde falso

`ecw` y `mrsid` estaban en la misma lista de orígenes que GeoTIFF, y el motor general daba
por buenas sus ocho columnas comprobando solo que GDAL existe. Pero ninguna compilación
corriente trae esos dos controladores: son de terceros y con su licencia.

Así que la matriz pintaba **`ecw → cog` en verde**, alguien lo pedía, y la conversión moría
con un error de GDAL sobre un controlador desconocido. La pantalla de compatibilidad existe
literalmente para que eso no pase — «lo que falta aparece apagado y dice qué falta y qué sirve
en su lugar»— y decía lo contrario.

Escribir ECW es otra cosa, la contesta `sondar_ecw` y tiene su propio motor: leer es gratis,
escribir necesita una clave OEM de pago.
"""

import pytest
from django.core.cache import cache

from apps.engines import registry, sondas

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def registro_limpio(monkeypatch):
    """El registro de motores es global y varias pruebas lo vacían, así que aquí se siembra
    explícitamente en vez de confiar en lo que dejó el `ready()` de la aplicación.

    Y la caché con él: la sonda de GDAL se guarda diez minutos, así que sin vaciarla la
    segunda prueba leería lo que dejó la primera.

    PROJ se da por presente: el motor raster lo comprueba además de GDAL, y aquí lo que se
    mide es otra cosa. Sin esto, la máquina que corra las pruebas sin PROJ las tumba todas
    por un motivo que no tiene nada que ver con lo que prueban.
    """
    from .motores import registrar_todos

    cache.clear()
    registry.limpiar()
    registrar_todos()
    monkeypatch.setattr(sondas, "sondar_proj", lambda: sondas.Disponibilidad.si("PROJ 9.8"))
    yield
    cache.clear()
    registry.limpiar()


def _gdal_con(controladores, escribibles=frozenset()):
    return lambda: sondas.EstadoGdal(
        disponible=True,
        version="GDAL 3.12.4",
        ejecutable="gdalinfo",
        controladores=frozenset(controladores),
        escribibles=frozenset(escribibles),
    )


class TestSinElControlador:
    def test_ecw_no_se_ofrece_como_origen(self, monkeypatch):
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "COG"}))
        celda = registry.matriz_de_capacidades().get(("ecw", "cog"))
        assert celda is not None, "La fila no se oculta: se apaga."
        assert celda.estado != "disponible"

    def test_y_lo_dice_con_su_motivo(self, monkeypatch):
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "COG"}))
        estado = sondas.sondar_lectura_gdal("ECW", formato="ecw", de_donde="El plugin de X.")
        assert estado.codigo_motivo == "sin-driver-ecw"
        assert "ni para leer" in estado.mensaje
        assert "plugin" in estado.sugerencia

    def test_mrsid_va_por_separado(self, monkeypatch):
        """Dos instalaciones distintas. Con el plugin de ECW puesto y el de MrSID no, una
        respuesta única mentiría sobre uno de los dos."""
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "COG", "ECW"}))
        capacidades = registry.matriz_de_capacidades()
        assert capacidades[("ecw", "cog")].estado == "disponible"
        assert capacidades[("mrsid", "cog")].estado != "disponible"


class TestConElControlador:
    def test_ecw_se_lee_y_la_celda_se_enciende(self, monkeypatch):
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "COG", "ECW"}))
        celda = registry.matriz_de_capacidades()[("ecw", "cog")]
        assert celda.estado == "disponible"

    def test_pero_escribirlo_sigue_necesitando_la_clave(self, monkeypatch, settings):
        """**La distinción que el plugin de solo lectura no resuelve.** Leer ECW es gratis;
        crear un ECW exige la clave OEM de Hexagon, y son diez conversiones distintas."""
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "ECW"}, {"GTIFF"}))
        settings.ECW_BIN = ""
        settings.ECW_ENCODE_KEY = ""
        settings.ECW_ENCODE_COMPANY = ""
        celda = registry.matriz_de_capacidades()[("geotiff", "ecw")]
        assert celda.estado != "disponible"


class TestLosFormatosCorrientes:
    def test_geotiff_no_depende_de_ningun_plugin(self, monkeypatch):
        monkeypatch.setattr(sondas, "sondar_gdal", _gdal_con({"GTIFF", "COG"}))
        celda = registry.matriz_de_capacidades()[("geotiff", "cog")]
        assert celda.estado == "disponible"
