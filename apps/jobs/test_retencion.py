"""Retencion y presupuesto de disco.

El objetivo declarado es que el servicio **no acumule nada**. Estas pruebas comprueban las
dos mitades: que lo escrito se borre, y que lo que aun no se ha escrito no quepa si no hay
sitio -- que es la mitad que de verdad protege el servidor.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from apps.jobs import despachador, retencion
from apps.jobs.models import EJECUTANDO, ERROR, HECHO, ConversionJob, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def carpeta(tmp_path, settings):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    return retencion.carpeta_de_trabajo()


def _salida(carpeta, nombre="salida.tif", megas=1):
    ruta = carpeta / nombre
    ruta.write_bytes(b"\x00" * (megas * 1_000_000))
    return ruta


def _trabajo(usuario, ruta=None, **extra):
    campos = {
        "owner": usuario,
        "source_name": "orto.tif",
        "target_format_code": "cog",
        "status": HECHO,
        "output_path": str(ruta) if ruta else "",
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


class TestPolitica:
    def test_taller_conserva_por_omision(self):
        """En taller la salida vive junto al original, en el disco de la persona. Barrerla
        seria borrarle su entregable."""
        with override_settings(MODO="taller", RETENCION=""):
            assert retencion.politica() == retencion.PERMANENTE

    def test_nube_es_efimera_por_omision(self):
        with override_settings(MODO="nube", RETENCION=""):
            assert retencion.politica() == retencion.EFIMERA

    def test_lo_configurado_manda(self):
        with override_settings(MODO="taller", RETENCION="temporal"):
            assert retencion.politica() == retencion.TEMPORAL

    def test_una_politica_inventada_no_se_acepta(self):
        """Un valor mal escrito en el `.env` no puede convertirse en «no borrar nunca» por
        accidente: se cae al valor por omision del modo."""
        with override_settings(MODO="nube", RETENCION="permamente"):
            assert retencion.politica() == retencion.EFIMERA


class TestCaducidad:
    def test_lo_permanente_no_caduca(self):
        with override_settings(MODO="taller", RETENCION="permanente"):
            assert retencion.caducidad_para() is None

    def test_lo_efimero_caduca_en_minutos(self):
        with override_settings(MODO="nube", RETENCION="efimera", EFIMERA_MINUTOS=30):
            falta = retencion.caducidad_para() - timezone.now()
        assert timedelta(minutes=29) < falta < timedelta(minutes=31)

    def test_lo_temporal_caduca_en_horas(self):
        with override_settings(MODO="nube", RETENCION="temporal", RETENCION_HORAS=24):
            falta = retencion.caducidad_para() - timezone.now()
        assert timedelta(hours=23) < falta < timedelta(hours=25)


class TestPresupuesto:
    """La mitad que de verdad protege el disco.

    Borrar al terminar no impide que tres conversiones simultaneas de 40 GB llenen el
    volumen a la vez. Lo impide medir antes de arrancar.
    """

    def test_un_trabajo_que_cabe_pasa(self, carpeta):
        with override_settings(PRESUPUESTO_GB=20):
            assert retencion.presupuesto_para(1_000_000_000).cabe is True

    def test_un_trabajo_que_no_cabe_en_el_tope_se_frena(self, carpeta):
        with override_settings(PRESUPUESTO_GB=1):
            presupuesto = retencion.presupuesto_para(2_000_000_000)
        assert presupuesto.cabe is False
        assert "tope" in presupuesto.motivo

    def test_se_pide_el_doble_de_la_entrada(self, carpeta):
        """La salida sin perdida puede quedar del mismo orden, y durante un instante
        conviven el parcial y el definitivo."""
        with override_settings(PRESUPUESTO_GB=100):
            assert retencion.presupuesto_para(1_000_000_000).necesario_bytes == 2_000_000_000

    def test_lo_ya_usado_cuenta(self, carpeta):
        _salida(carpeta, "ocupado.tif", megas=600)
        with override_settings(PRESUPUESTO_GB=1):
            assert retencion.presupuesto_para(300_000_000).cabe is False

    def test_el_despachador_espera_en_vez_de_fallar(self, usuario, carpeta):
        """Un disco lleno es transitorio: se libera cuando otro trabajo se descarga.
        Fallarlo obligaria a reencolar a mano por algo que se arregla solo."""
        job = _trabajo(usuario, status="queued", source_size_bytes=50_000_000_000)

        with override_settings(PRESUPUESTO_GB=1):
            assert despachador.procesar_una_vez() == 0

        job.refresh_from_db()
        assert job.status == "queued"

    def test_el_motivo_se_escribe_una_sola_vez(self, usuario, carpeta):
        """Un trabajo que espera media hora escribiria novecientas lineas iguales y
        volveria ilegible la bitacora justo cuando alguien va a leerla."""
        _trabajo(usuario, status="queued", source_size_bytes=50_000_000_000)

        with override_settings(PRESUPUESTO_GB=1):
            for _ in range(5):
                despachador.procesar_una_vez()

        assert JobEvent.objects.filter(reason_code="sin-espacio").count() == 1


class TestBarrido:
    def test_borra_una_salida_caducada(self, usuario, carpeta):
        ruta = _salida(carpeta)
        job = _trabajo(usuario, ruta, expires_at=timezone.now() - timedelta(minutes=1))

        resultado = retencion.barrer()

        assert resultado.salidas_caducadas == 1
        assert not ruta.exists()
        job.refresh_from_db()
        assert job.output_path == ""

    def test_no_borra_una_salida_vigente(self, usuario, carpeta):
        ruta = _salida(carpeta)
        _trabajo(usuario, ruta, expires_at=timezone.now() + timedelta(hours=1))

        retencion.barrer()

        assert ruta.exists()

    def test_no_borra_una_salida_permanente(self, usuario, carpeta):
        ruta = _salida(carpeta)
        _trabajo(usuario, ruta, expires_at=None)

        retencion.barrer()

        assert ruta.exists()

    def test_no_toca_un_trabajo_que_sigue_corriendo(self, usuario, carpeta):
        ruta = _salida(carpeta)
        _trabajo(usuario, ruta, status=EJECUTANDO, expires_at=timezone.now() - timedelta(hours=1))

        retencion.barrer()

        assert ruta.exists()

    def test_recoge_huerfanos_viejos(self, carpeta):
        """Un `.parcial` que sobrevivio a un proceso muerto. Nadie los reclama nunca."""
        import os

        huerfano = _salida(carpeta, "algo.tif.parcial")
        viejo = timezone.now().timestamp() - 7200
        os.utime(huerfano, (viejo, viejo))

        resultado = retencion.barrer()

        assert resultado.huerfanos == 1
        assert not huerfano.exists()

    def test_no_recoge_un_parcial_recien_escrito(self, carpeta):
        """Es la unica salvaguarda que hay para no borrarle el parcial a un trabajo que
        esta corriendo ahora mismo: el nombre no dice de quien es."""
        reciente = _salida(carpeta, "vivo.tif.parcial")

        resultado = retencion.barrer()

        assert resultado.huerfanos == 0
        assert reciente.exists()

    def test_ignora_los_archivos_que_no_son_de_trabajo(self, carpeta):
        import os

        normal = _salida(carpeta, "entregable.tif")
        viejo = timezone.now().timestamp() - 7200
        os.utime(normal, (viejo, viejo))

        retencion.barrer()

        assert normal.exists()

    def test_informa_de_lo_liberado(self, usuario, carpeta):
        ruta = _salida(carpeta, megas=5)
        _trabajo(usuario, ruta, expires_at=timezone.now() - timedelta(minutes=1))

        resultado = retencion.barrer()

        assert resultado.bytes_liberados == 5_000_000
        assert "MB liberados" in str(resultado)


class TestConsumir:
    def test_la_politica_efimera_borra_al_descargar(self, usuario, carpeta):
        ruta = _salida(carpeta)
        job = _trabajo(usuario, ruta)

        with override_settings(MODO="nube", RETENCION="efimera"):
            liberados = retencion.consumir(job)

        assert liberados == 1_000_000
        assert not ruta.exists()
        job.refresh_from_db()
        assert job.output_path == ""

    def test_las_demas_politicas_no_borran(self, usuario, carpeta):
        ruta = _salida(carpeta)
        job = _trabajo(usuario, ruta)

        for politica in ("temporal", "permanente"):
            with override_settings(MODO="nube", RETENCION=politica):
                assert retencion.consumir(job) == 0
            assert ruta.exists()


class TestDescarga:
    def test_se_entrega_y_desaparece(self, usuario, carpeta, client):
        ruta = _salida(carpeta)
        job = _trabajo(usuario, ruta)
        client.force_login(usuario)

        with override_settings(MODO="nube", RETENCION="efimera"):
            respuesta = client.get(f"/trabajos/{job.pk}/descargar/")
            assert respuesta.status_code == 200
            b"".join(respuesta.streaming_content)
            respuesta.close()

        assert not ruta.exists()

    def test_una_salida_que_ya_se_barrio_da_404_y_no_un_error(self, usuario, carpeta, client):
        job = _trabajo(usuario, carpeta / "no-esta.tif")
        client.force_login(usuario)
        assert client.get(f"/trabajos/{job.pk}/descargar/").status_code == 404

    def test_nadie_descarga_el_trabajo_de_otro(self, usuario, carpeta, client):
        ruta = _salida(carpeta)
        ajeno = get_user_model().objects.create_user("otro", password="y" * 20)  # nosec B106
        job = _trabajo(ajeno, ruta)
        client.force_login(usuario)

        assert client.get(f"/trabajos/{job.pk}/descargar/").status_code == 404

    def test_sin_entrar_no_se_descarga(self, usuario, carpeta, client):
        job = _trabajo(usuario, _salida(carpeta))
        respuesta = client.get(f"/trabajos/{job.pk}/descargar/")
        assert respuesta.status_code == 302
        assert "/entrar/" in respuesta["Location"]


class TestEntradasSubidas:
    def test_se_borran_siempre_al_terminar(self, usuario, carpeta):
        """Incluso con politica permanente: quien la subio ya la tiene, y guardarla duplica
        el archivo del cliente en nuestro servidor sin que nadie lo haya pedido."""
        from django.core.files.base import ContentFile

        job = _trabajo(usuario, status=ERROR)
        job.source_upload.save("entrada.tif", ContentFile(b"x" * 1000), save=True)
        nombre = job.source_upload.name

        with override_settings(RETENCION="permanente"):
            resultado = retencion.barrer()

        assert resultado.entradas_borradas == 1
        job.refresh_from_db()
        assert job.source_upload.name in ("", None)
        assert nombre
