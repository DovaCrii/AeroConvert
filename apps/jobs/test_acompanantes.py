"""Un Shapefile no es un archivo: son cinco. Y hay que entregarlos todos.

Este archivo existe por el peor fallo que ha tenido el proyecto, porque es el único que
entregaba algo **inservible con el recibo en verde**.

El motor escribe `salida.parcial.shp` y, al lado, `salida.parcial.shx`, `.dbf` y `.prj`. La
verificación corre sobre el parcial, cuando los cuatro se llaman igual, así que pasaba y
anotaba «5 entidades, EPSG:32719». Después el renombrado movía **solo el `.shp`** y dejaba
a los otros tres huérfanos con el nombre viejo.

El resultado: `salida.shp` sin su `.shx` al lado. `ogrinfo` responde «Unable to open
salida.shx» y no lo abre; QGIS y ArcGIS tampoco. Se comprobó sobre el archivo entregado.

Lo que lo arregla es mover el juego entero, y **qué acompaña a qué lo dice el catálogo** —el
mismo dato que ya usa la ficha para avisar de que falta un `.prj`—, no una lista escrita en
el runner.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats import catalogo
from apps.jobs import runner
from apps.jobs.models import HECHO, ConversionJob

pytestmark = pytest.mark.django_db

#: Los que de verdad hacen falta para que un Shapefile abra.
IMPRESCINDIBLES = (".shx", ".dbf", ".prj")


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def origen(tmp_path):
    ruta = tmp_path / "entrada.csv"
    ruta.write_text("P1,7318729.036,495279.406,3042.641,pr\n" * 3, encoding="utf-8")
    return ruta


@pytest.fixture(autouse=True)
def registro_limpio():
    registry.limpiar()
    yield
    registry.limpiar()


def _convertir_a_shp(usuario, origen, tmp_path, acompanantes=IMPRESCINDIBLES):
    registry.registrar(
        MotorDeMentira(
            "shp-de-mentira",
            pares_=(("puntos", "shp"),),
            escribe_acompanantes=acompanantes,
        )
    )
    destino = tmp_path / "entrega.shp"
    trabajo = ConversionJob.objects.create(
        owner=usuario,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="shp",
        output_path=str(destino),
        source_crs_authority="EPSG",
        source_crs_code="32719",
        source_crs_origin="declarado",
    )
    runner.ejecutar(trabajo)
    trabajo.refresh_from_db()
    return trabajo, destino


class TestElCatalogoDiceQuienAcompana:
    def test_un_shapefile_no_va_solo(self):
        acompanantes = catalogo.FORMATOS["shp"].acompanantes
        for extension in IMPRESCINDIBLES:
            assert extension in acompanantes


class TestSeEntreganTodos:
    def test_el_trabajo_termina_bien(self, usuario, origen, tmp_path):
        trabajo, _ = _convertir_a_shp(usuario, origen, tmp_path)
        assert trabajo.status == HECHO

    def test_y_los_acompanantes_quedan_junto_a_la_salida(self, usuario, origen, tmp_path):
        """Esta es la prueba. Sin ella el recibo dice «verificado» sobre algo que no abre."""
        _, destino = _convertir_a_shp(usuario, origen, tmp_path)
        for extension in IMPRESCINDIBLES:
            hermano = destino.with_suffix(extension)
            assert hermano.exists(), f"Falta {hermano.name}: el .shp no abrirá sin él."

    def test_y_no_queda_ninguno_con_el_nombre_del_parcial(self, usuario, origen, tmp_path):
        """Huérfanos con el nombre viejo: ni sirven ni los reclama nadie."""
        _convertir_a_shp(usuario, origen, tmp_path)
        restos = sorted(p.name for p in tmp_path.glob("*parcial*"))
        assert restos == []

    def test_el_acompanante_que_no_escribio_el_motor_no_estorba(self, usuario, origen, tmp_path):
        """El catálogo lista `.sbn` y `.cpg`, que OGR no siempre escribe. Se mueve lo que
        hay, y lo que no hay no es un error."""
        trabajo, destino = _convertir_a_shp(usuario, origen, tmp_path, acompanantes=(".shx",))
        assert trabajo.status == HECHO
        assert destino.with_suffix(".shx").exists()
        assert not destino.with_suffix(".dbf").exists()


class TestUnFormatoDeUnSoloArchivo:
    def test_no_cambia_nada(self, usuario, origen, tmp_path):
        """Un GeoPackage es un archivo y ya. El arreglo no puede inventarle hermanos."""
        registry.registrar(MotorDeMentira("gpkg-de-mentira", pares_=(("puntos", "gpkg"),)))
        destino = tmp_path / "entrega.gpkg"
        trabajo = ConversionJob.objects.create(
            owner=usuario,
            source_path=str(origen),
            source_name=origen.name,
            target_format_code="gpkg",
            output_path=str(destino),
            source_crs_authority="EPSG",
            source_crs_code="32719",
            source_crs_origin="declarado",
        )
        runner.ejecutar(trabajo)
        trabajo.refresh_from_db()

        assert trabajo.status == HECHO
        assert destino.exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["entrada.csv", "entrega.gpkg"]
