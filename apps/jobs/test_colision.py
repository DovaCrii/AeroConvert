"""Que nadie se descargue el archivo de otro.

La ruta de salida se construye de forma determinista -- `ortofoto_civil3d.tif` -- y en una
carpeta compartida dos personas que conviertan cada una su `ortofoto.tif` con el mismo
perfil producían **exactamente la misma ruta**. La segunda conversión sobrescribía a la
primera, y la descarga sirve lo que haya en `output_path`.

Eso no es una molestia de nombres: es que alguien se baja el archivo de otro creyendo que es
el suyo. No da ningún error, no queda en ninguna bitácora, y solo se nota si alguien abre el
archivo y reconoce que no es el que esperaba.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import runner
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106


@pytest.fixture
def registro_limpio():
    guardado = registry.todos()
    registry.limpiar()
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


def _trabajo(duena, carpeta, nombre="orto.tif", salida="orto_civil3d.tif"):
    origen = carpeta / nombre
    if not origen.exists():
        origen.write_bytes(geotiff_minimo(bandas=3))
    return ConversionJob.objects.create(
        owner=duena,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="cog",
        output_path=str(carpeta / salida),
    )


class TestElDestinoLibre:
    def test_si_nadie_lo_reclama_se_usa_tal_cual(self, ana, tmp_path):
        trabajo = _trabajo(ana, tmp_path)
        libre = runner._destino_libre(trabajo, tmp_path / "orto_civil3d.tif")
        assert libre.name == "orto_civil3d.tif"

    def test_lo_mio_lo_puedo_pisar(self, ana, tmp_path):
        """Volver a convertir el mismo archivo y encontrarse el resultado donde estaba es
        lo que uno espera. Obligar a `_2`, `_3`, `_4` cada vez sería cambiar un fallo por
        una molestia diaria."""
        _trabajo(ana, tmp_path)
        otro = _trabajo(ana, tmp_path)
        libre = runner._destino_libre(otro, tmp_path / "orto_civil3d.tif")
        assert libre.name == "orto_civil3d.tif"

    def test_lo_de_otra_persona_no(self, ana, beto, tmp_path):
        """El fallo entero, en una prueba."""
        _trabajo(ana, tmp_path)
        de_beto = _trabajo(beto, tmp_path)
        libre = runner._destino_libre(de_beto, tmp_path / "orto_civil3d.tif")
        assert libre.name == "orto_civil3d_2.tif"

    def test_y_se_sigue_contando(self, ana, beto, tmp_path):
        """Con dos nombres ya tomados por otra persona, el tercero es el que queda."""
        _trabajo(ana, tmp_path)
        segunda = _trabajo(ana, tmp_path)
        segunda.output_path = str(tmp_path / "orto_civil3d_2.tif")
        segunda.save(update_fields=["output_path"])

        de_beto = _trabajo(beto, tmp_path)
        libre = runner._destino_libre(de_beto, tmp_path / "orto_civil3d.tif")
        assert libre.name == "orto_civil3d_3.tif"

    def test_conserva_las_extensiones_compuestas(self, ana, beto, tmp_path):
        """`nube.copc.laz` no puede volverse `nube.copc_2.laz`: media herramienta
        geoespacial deduce el formato de la extensión, que es la misma razón por la que
        `ruta_parcial()` corta en el primer punto."""
        _trabajo(ana, tmp_path, salida="nube.copc.laz")
        de_beto = _trabajo(beto, tmp_path, salida="nube.copc.laz")
        libre = runner._destino_libre(de_beto, tmp_path / "nube.copc.laz")
        assert libre.name == "nube_2.copc.laz"

    def test_un_archivo_sin_extension(self, ana, beto, tmp_path):
        _trabajo(ana, tmp_path, salida="salida")
        de_beto = _trabajo(beto, tmp_path, salida="salida")
        assert runner._destino_libre(de_beto, tmp_path / "salida").name == "salida_2"


class TestDePuntaAPunta:
    def test_dos_personas_con_el_mismo_nombre_acaban_con_dos_archivos(
        self, ana, beto, tmp_path, registro_limpio
    ):
        """La prueba que importa: el motor de verdad escribe, y quedan los dos."""
        registry.registrar(MotorDeMentira("mentira", escribe="de ana"))

        carpeta_ana = tmp_path / "ana"
        carpeta_ana.mkdir()
        trabajo_ana = _trabajo(ana, carpeta_ana)
        runner.ejecutar(trabajo_ana)

        # Beto convierte **su** archivo, que se llama igual, a la misma carpeta compartida.
        trabajo_beto = _trabajo(beto, carpeta_ana, nombre="orto2.tif")
        runner.ejecutar(trabajo_beto)

        trabajo_ana.refresh_from_db()
        trabajo_beto.refresh_from_db()

        assert trabajo_ana.output_path != trabajo_beto.output_path
        assert sorted(p.name for p in carpeta_ana.glob("orto_civil3d*.tif")) == [
            "orto_civil3d.tif",
            "orto_civil3d_2.tif",
        ]

    def test_y_cada_una_se_descarga_lo_suyo(self, ana, beto, tmp_path, client, registro_limpio):
        registry.registrar(MotorDeMentira("mentira", escribe="esto es de ana"))

        trabajo_ana = _trabajo(ana, tmp_path)
        runner.ejecutar(trabajo_ana)
        trabajo_beto = _trabajo(beto, tmp_path, nombre="orto2.tif")
        runner.ejecutar(trabajo_beto)

        client.force_login(ana)
        respuesta = client.get(reverse("jobs:descargar", kwargs={"pk": trabajo_ana.pk}))
        assert b"".join(respuesta.streaming_content) == b"esto es de ana"


class TestLaDescarga:
    def test_si_alguien_reemplaza_el_archivo_no_se_entrega(
        self, ana, tmp_path, client, registro_limpio
    ):
        """`_destino_libre` impide que otra conversión escriba encima, pero nada impide que
        alguien reemplace el archivo desde la carpeta compartida con el Explorador."""
        registry.registrar(MotorDeMentira("mentira", escribe="el bueno"))
        trabajo = _trabajo(ana, tmp_path)
        runner.ejecutar(trabajo)
        trabajo.refresh_from_db()

        from pathlib import Path

        Path(trabajo.output_path).write_bytes(b"otra cosa completamente distinta")

        client.force_login(ana)
        respuesta = client.get(reverse("jobs:descargar", kwargs={"pk": trabajo.pk}))
        # 410 y no 404: el recibo sigue, y la pagina lo ensena y ofrece rehacerla.
        assert respuesta.status_code == 410
        assert "no es el que se generó" in respuesta.content.decode()
