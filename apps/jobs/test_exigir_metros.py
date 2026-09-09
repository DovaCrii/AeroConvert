"""Un destino que necesita metros no se llena de grados en silencio.

Es el fallo espejo del que ya tenía el KML, y con la misma cara de éxito. Un KMZ viene
siempre en EPSG:4326; convertirlo a DXF sin reproyectar escribe coordenadas como `-69,046`
y `-24,244`, así que el dibujo entero mide **dos milésimas de unidad**. Se comprobó sobre el
archivo real: abría en Civil 3D, no se veía nada, y el recibo decía «hecho».

Tres piezas lo resuelven, y las tres se prueban aquí porque solo tienen sentido juntas:

1. **El catálogo sabe qué formatos exigen metros** (`exige_metros`) y **cuáles imponen su
   sistema de referencia** (`crs_fijo`). Un KML solo existe en EPSG:4326: lo dice la norma,
   así que decirlo no es adivinar.
2. **`Crs.es_geografico`** distingue grados de metros preguntándole a PROJ.
3. **El runner se para antes de convertir**, porque un DXF no guarda sistema de referencia:
   mirando la salida no hay forma de saber en qué unidades está. El dato solo existe en el
   origen.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.formats import catalogo
from apps.formats import crs as crs_mod
from apps.formats.deteccion import inspeccionar
from apps.jobs import runner
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db

#: Un KML mínimo con un punto en la obra del cruce minero.
KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<name>P1</name><Point><coordinates>-69.0465,-24.2443,3042.641</coordinates></Point>
</Placemark></Document></kml>
"""


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def kml(tmp_path):
    ruta = tmp_path / "recinto.kml"
    ruta.write_text(KML, encoding="utf-8")
    return ruta


def _trabajo(usuario, origen, destino_codigo, **extra):
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code=destino_codigo,
        output_path=str(origen.with_suffix(".salida")),
        **extra,
    )


class TestElCatalogoLoSabe:
    def test_el_dxf_exige_metros(self):
        assert catalogo.FORMATOS["dxf"].exige_metros is True

    def test_y_los_demas_no(self):
        """La marca es corta a propósito: un GPKG o un GeoJSON en grados son legítimos."""
        con_metros = {c for c, f in catalogo.FORMATOS.items() if f.exige_metros}
        assert con_metros == {"dxf"}

    def test_kml_y_kmz_imponen_4326(self):
        """Lo dice la norma del formato, no una probabilidad."""
        assert catalogo.FORMATOS["kml"].crs_fijo == "4326"
        assert catalogo.FORMATOS["kmz"].crs_fijo == "4326"

    def test_ningun_otro_formato_impone_uno(self):
        """GeoJSON *suele* ir en 4326, pero admite otros: suponerlo sería adivinar."""
        con_crs_fijo = {c for c, f in catalogo.FORMATOS.items() if f.crs_fijo}
        assert con_crs_fijo == {"kml", "kmz"}


class TestGradosContraMetros:
    def test_4326_es_geografico(self):
        assert crs_mod.epsg(4326).es_geografico is True

    def test_32719_no_lo_es(self):
        assert crs_mod.epsg(32719).es_geografico is False

    def test_sin_crs_no_lo_es_y_no_revienta(self):
        """No saberlo no puede bloquear una conversión legítima."""
        assert crs_mod.SIN_CRS.es_geografico is False


class TestLaInspeccionDeUnKml:
    def test_le_pone_el_4326_que_manda_la_norma(self, kml):
        inspeccion = inspeccionar(kml)
        assert inspeccion.crs.codigo == "4326"

    def test_y_dice_de_donde_sale(self, kml):
        """Ni venía dentro del archivo ni lo eligió nadie: lo fija el formato. La ficha lo
        distingue, y esa distinción separa «lo sabemos» de «alguien lo supuso»."""
        inspeccion = inspeccionar(kml)
        assert inspeccion.crs.origen == crs_mod.POR_NORMA
        assert inspeccion.crs.procedencia == "lo fija el formato"


class TestElRunnerSePara:
    def test_un_kml_a_dxf_sin_reproyectar_no_se_convierte(self, usuario, kml):
        trabajo = _trabajo(usuario, kml, "dxf")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_metros(trabajo, inspeccionar(kml))
        assert fallo.value.codigo == "crs-en-grados"

    def test_y_el_mensaje_dice_la_consecuencia_no_el_diagnostico(self, usuario, kml):
        trabajo = _trabajo(usuario, kml, "dxf")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_metros(trabajo, inspeccionar(kml))
        assert "milésimas de unidad" in str(fallo.value)

    def test_declarando_el_destino_sigue_adelante(self, usuario, kml):
        trabajo = _trabajo(usuario, kml, "dxf", options={"crs_destino": "32719"})
        runner._exigir_metros(trabajo, inspeccionar(kml))

    def test_o_por_el_campo_del_trabajo(self, usuario, kml):
        """La API llega por `target_crs_code` y el formulario por las opciones. Las dos."""
        trabajo = _trabajo(
            usuario, kml, "dxf", target_crs_authority="EPSG", target_crs_code="32719"
        )
        runner._exigir_metros(trabajo, inspeccionar(kml))

    def test_el_mismo_kml_a_un_formato_que_no_exige_metros_pasa(self, usuario, kml):
        """Un GeoPackage en grados es perfectamente legítimo."""
        runner._exigir_metros(_trabajo(usuario, kml, "gpkg"), inspeccionar(kml))

    def test_un_origen_en_metros_a_dxf_pasa(self, usuario, tmp_path):
        """La libreta de puntos del cruce minero: ya está en UTM, no hay nada que arreglar."""
        libreta = tmp_path / "control.csv"
        libreta.write_text("P1,7318729.036,495279.406,3042.641,pr\n" * 3, encoding="utf-8")
        trabajo = _trabajo(
            usuario,
            libreta,
            "dxf",
            source_crs_authority="EPSG",
            source_crs_code="32719",
            source_crs_origin=crs_mod.DECLARADO,
        )
        runner._exigir_metros(trabajo, inspeccionar(libreta))
