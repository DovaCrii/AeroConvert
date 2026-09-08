"""El runner, con procesos hijos de verdad y cero GDAL.

Estas son las pruebas del pegamento -- donde estan los errores caros. Cada una corresponde
a un fallo que de verdad ocurre en produccion y que no da sintoma hasta que es tarde.
"""

import os
import time
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.engines import registry
from apps.engines.testing import MotorDeMentira, analizar_progreso_de_gdal
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import despachador, runner
from apps.jobs.models import (
    CANCELADO,
    EJECUTANDO,
    ERROR,
    HECHO,
    ConversionJob,
    JobEvent,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def origen(tmp_path):
    """Un GeoTIFF de verdad, de unos 400 bytes."""
    ruta = tmp_path / "orto.tif"
    ruta.write_bytes(geotiff_minimo(bandas=3))
    return ruta


@pytest.fixture
def registro_limpio():
    guardado = registry.todos()
    registry.limpiar()
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


def _trabajo(usuario, origen, tmp_path, **extra):
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="cog",
        output_path=str(tmp_path / "salida.tif"),
        **extra,
    )


def _con_motor(motor):
    registry.registrar(motor)
    return motor


# --- El camino feliz -------------------------------------------------------


class TestConversionCorrecta:
    def test_termina_en_hecho_y_deja_el_archivo(self, usuario, origen, tmp_path, registro_limpio):
        _con_motor(MotorDeMentira(escribe="contenido convertido"))
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        job.refresh_from_db()
        assert resultado.estado == HECHO
        assert job.status == HECHO
        assert (tmp_path / "salida.tif").read_text() == "contenido convertido"

    def test_no_queda_ningun_parcial(self, usuario, origen, tmp_path, registro_limpio):
        _con_motor(MotorDeMentira())
        runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert not (tmp_path / "salida.tif.parcial").exists()
        assert not (tmp_path / "salida.tif.prueba").exists()

    def test_se_borran_los_acompanantes_que_dejo_el_motor(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        """GDAL cuelga un `.aux.xml` del nombre del parcial. Al renombrar el archivo ese
        acompañante se queda huérfano: nadie lo reclama y nadie lo borra. Son kilobytes,
        pero uno por conversión, y contradicen lo que se promete — que el entregable es un
        solo archivo que se basta a sí mismo."""

        class MotorSucio(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)
                # Simula lo que hace GDAL: escribir un acompañante junto al parcial.
                Path(str(plan.ruta_de_salida) + ".parcial.aux.xml").write_text("<PAMDataset/>")
                return plan

        _con_motor(MotorSucio())
        runner.ejecutar(_trabajo(usuario, origen, tmp_path))

        restantes = sorted(p.name for p in tmp_path.iterdir())
        assert restantes == ["orto.tif", "salida.tif"]

    def test_guarda_la_huella_del_original_no_la_de_la_salida(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        """Es la prueba de que entregable se convirtio. La de la salida cambiaria con la
        version del conversor aunque el original fuera el mismo."""
        import hashlib

        _con_motor(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.source_sha256 == hashlib.sha256(origen.read_bytes()).hexdigest()

    def test_congela_la_version_del_motor(self, usuario, origen, tmp_path, registro_limpio):
        """Un «ayer funcionaba» se diagnostica con esto."""
        _con_motor(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.engine_id == "mentira"
        assert job.engine_version == "mentira 1.0"

    def test_reconoce_el_formato_y_el_crs_del_origen(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.source_format_code == "geotiff"
        assert job.source_crs_code == "32719"
        assert job.source_crs_origin == "incrustado"

    def test_la_barra_llega_al_final(self, usuario, origen, tmp_path, registro_limpio):
        _con_motor(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.progress_percent == 100

    def test_el_argv_queda_en_la_bitacora(self, usuario, origen, tmp_path, registro_limpio):
        """Es lo primero que se mira cuando la salida no es la esperada."""
        _con_motor(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        evento = JobEvent.objects.filter(job=job, message__startswith="Lanzando").first()
        assert evento is not None
        assert evento.payload["argv"][0].endswith(("python.exe", "python", "python3"))


# --- El original no se toca ------------------------------------------------


class TestElOriginalNoSeToca:
    """Se comprueba en **cada** camino de fallo, no solo en el feliz: ahi es donde aparecen
    los `unlink` de limpieza mal apuntados."""

    @pytest.mark.parametrize(
        "motor",
        [
            MotorDeMentira(escribe="ok"),
            MotorDeMentira(codigo_de_salida=1),
            MotorDeMentira(escribe=""),
            MotorDeMentira(disponible=False),
        ],
        ids=["exito", "codigo-de-error", "sin-salida", "motor-apagado"],
    )
    def test_conserva_contenido_y_fecha(self, usuario, origen, tmp_path, registro_limpio, motor):
        antes_bytes = origen.read_bytes()
        antes_mtime = origen.stat().st_mtime_ns

        _con_motor(motor)
        runner.ejecutar(_trabajo(usuario, origen, tmp_path))

        assert origen.read_bytes() == antes_bytes
        assert origen.stat().st_mtime_ns == antes_mtime


# --- No creerle al codigo de salida ----------------------------------------


class TestNoSeCreeElCodigoDeSalida:
    """La regla numero uno del proyecto. ODA devuelve 0 sin convertir nada; GDAL devuelve 0
    tras dejar un archivo vacio si el controlador fallo al cerrar."""

    def test_codigo_cero_sin_archivo_es_sin_salida(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira(escribe="", codigo_de_salida=0))
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert resultado.estado == ERROR
        assert resultado.codigo_motivo == "sin-salida"
        assert not (tmp_path / "salida.tif").exists()

    def test_codigo_distinto_de_cero_es_error_del_motor(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira(escribe="algo", codigo_de_salida=3))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "error-del-motor"

    def test_un_fallo_borra_el_parcial(self, usuario, origen, tmp_path, registro_limpio):
        """Un parcial abandonado se confunde con un entregable a medias."""
        _con_motor(MotorDeMentira(escribe="a medias", codigo_de_salida=1))
        runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert not (tmp_path / "salida.tif.parcial").exists()

    def test_la_cola_de_stderr_se_guarda_para_diagnosticar(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira(codigo_de_salida=1, pasos=3))
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        evento = JobEvent.objects.filter(job=job, level=JobEvent.ERROR).first()
        assert "stderr_cola" in evento.payload


# --- Cancelacion y tiempo --------------------------------------------------


class TestCancelacion:
    def test_cancelar_mata_al_hijo_y_borra_el_parcial(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        from django.utils import timezone

        _con_motor(MotorDeMentira(tarda_s=30, pasos=60))
        job = _trabajo(usuario, origen, tmp_path)
        # Se pide la cancelacion antes de arrancar: el runner la ve en su primer latido.
        ConversionJob.objects.filter(pk=job.pk).update(cancel_requested_at=timezone.now())

        empezo = time.monotonic()
        resultado = runner.ejecutar(job)
        tardo = time.monotonic() - empezo

        assert resultado.estado == CANCELADO
        assert resultado.codigo_motivo == "cancelado-por-el-usuario"
        assert not (tmp_path / "salida.tif.parcial").exists()
        # Si de verdad mato al hijo, no espero los 30 segundos.
        assert tardo < 20


class TestTiempo:
    def test_el_presupuesto_agotado_da_tardo_demasiado(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira(tarda_s=30, pasos=60, timeout_s=3))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "tardo-demasiado"

    @override_settings(SILENCIO_MAXIMO_S=3)
    def test_el_silencio_prolongado_da_sin_avance(self, usuario, origen, tmp_path, registro_limpio):
        """El detector util. El presupuesto total tiene que ser generoso -- un ECW de 40 GB
        tarda horas legitimamente -- asi que lo que delata un atasco es el silencio."""
        _con_motor(MotorDeMentira(tarda_s=30, pasos=1, timeout_s=3600))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "sin-avance"


# --- El sistema de referencia ----------------------------------------------


class TestCrsAusente:
    def test_reproyectar_sin_crs_de_origen_se_detiene(self, usuario, tmp_path, registro_limpio):
        _con_motor(MotorDeMentira())
        sin_crs = tmp_path / "sin_crs.tif"
        sin_crs.write_bytes(geotiff_minimo(bandas=3, epsg=None, escala_m=None, origen=None))
        job = _trabajo(usuario, sin_crs, tmp_path, target_crs_code="32719")

        resultado = runner.ejecutar(job)

        assert resultado.codigo_motivo == "crs-ausente"

    def test_sin_reproyectar_solo_avisa(self, usuario, tmp_path, registro_limpio):
        """Convertir un raster sin georreferencia a otro sin georreferencia es legitimo.
        Negarlo convertiria la herramienta en un estorbo."""
        _con_motor(MotorDeMentira(pares_=((("geotiff", "png")),)))
        sin_crs = tmp_path / "sin_crs.tif"
        sin_crs.write_bytes(geotiff_minimo(bandas=3, epsg=None, escala_m=None, origen=None))
        job = _trabajo(usuario, sin_crs, tmp_path)
        job.target_format_code = "png"
        job.save()

        resultado = runner.ejecutar(job)

        assert resultado.estado == HECHO
        assert JobEvent.objects.filter(job=job, level=JobEvent.AVISO).exists()


# --- El destino ------------------------------------------------------------


class TestDestino:
    def test_un_destino_abierto_falla_al_principio_no_al_final(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        """Lo caro no es que falle: es que falle tras horas de conversion."""
        if os.name != "nt":
            pytest.skip("El bloqueo obligatorio de archivos es de Windows.")

        _con_motor(MotorDeMentira(tarda_s=20, pasos=40))
        destino = tmp_path / "salida.tif"
        destino.write_bytes(b"ocupado")
        job = _trabajo(usuario, origen, tmp_path)

        with open(destino, "ab"):
            empezo = time.monotonic()
            resultado = runner.ejecutar(job)
            tardo = time.monotonic() - empezo

        assert resultado.codigo_motivo == "salida-bloqueada"
        assert tardo < 10, "fallo al final en vez de al principio"


# --- Sin motor -------------------------------------------------------------


class TestSinMotor:
    def test_un_par_que_nadie_sabe_da_sin_motor(self, usuario, origen, tmp_path, registro_limpio):
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "sin-motor"

    def test_un_motor_apagado_no_se_usa(self, usuario, origen, tmp_path, registro_limpio):
        _con_motor(MotorDeMentira(disponible=False, motivo="sin-clave-ecw"))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "sin-clave-ecw"


# --- El reclamo atomico ----------------------------------------------------


class TestReclamo:
    def test_solo_uno_se_lo_lleva(self, usuario, origen, tmp_path):
        """`runserver` con el recargador son DOS procesos, asi que este caso es el normal,
        no el raro. Sin el `UPDATE` atomico, el archivo se escribiria dos veces."""
        job = _trabajo(usuario, origen, tmp_path)

        assert runner.reclamar(job.pk) is True
        assert runner.reclamar(job.pk) is False

    def test_reclamar_cuenta_el_intento(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path)
        runner.reclamar(job.pk)
        job.refresh_from_db()
        assert job.attempt_count == 1
        assert job.status == EJECUTANDO
        assert job.worker_pid == os.getpid()


# --- El despachador --------------------------------------------------------


class TestDespachador:
    def test_procesar_una_vez_ejecuta_el_siguiente(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        _con_motor(MotorDeMentira())
        _trabajo(usuario, origen, tmp_path)

        assert despachador.procesar_una_vez() == 1

        assert ConversionJob.objects.get().status == HECHO

    def test_sin_cola_no_hace_nada(self, registro_limpio):
        assert despachador.procesar_una_vez() == 0

    def test_respeta_el_maximo_de_simultaneos(self, usuario, origen, tmp_path, registro_limpio):
        """Por omision uno: GDAL ya usa todos los nucleos, y dos conversiones compitiendo
        por el mismo disco es mas lento, no mas rapido."""
        _con_motor(MotorDeMentira())
        _trabajo(usuario, origen, tmp_path, status=EJECUTANDO)
        _trabajo(usuario, origen, tmp_path)

        with override_settings(TRABAJOS_SIMULTANEOS=1):
            assert despachador.procesar_una_vez() == 0

    def test_no_arranca_el_hilo_en_las_pruebas(self):
        """Una prueba que arranca un hilo es una prueba que falla los martes."""
        with override_settings(CONVERSION_DISPATCHER_ENABLED=False):
            assert despachador.arrancar() is False

    def test_recoge_un_trabajo_cuyo_obrero_ya_no_existe(self, usuario, origen, tmp_path):
        from datetime import timedelta

        from django.utils import timezone

        job = _trabajo(
            usuario,
            origen,
            tmp_path,
            status=EJECUTANDO,
            worker_pid=999_999,
            heartbeat_at=timezone.now() - timedelta(hours=1),
        )

        assert despachador.recoger_muertos() == 1

        job.refresh_from_db()
        assert job.status == ERROR
        assert job.reason_code == "interrumpido"

    def test_no_recoge_uno_que_sigue_vivo(self, usuario, origen, tmp_path):
        from datetime import timedelta

        from django.utils import timezone

        _trabajo(
            usuario,
            origen,
            tmp_path,
            status=EJECUTANDO,
            worker_pid=os.getpid(),
            heartbeat_at=timezone.now() - timedelta(hours=1),
        )
        assert despachador.recoger_muertos() == 0


# --- El analizador de progreso ---------------------------------------------


class TestAnalizadorDeProgreso:
    def test_lee_el_formato_de_gdal(self):
        assert analizar_progreso_de_gdal("0...10...20...30") == pytest.approx(0.30)

    def test_cien_es_uno(self):
        assert analizar_progreso_de_gdal("0...10...100 - done.") == pytest.approx(1.0)

    def test_una_linea_que_no_habla_de_progreso_devuelve_none(self):
        """Y acaba en la bitacora. Perder un aviso por no entenderlo seria peor que no leer
        el progreso."""
        assert analizar_progreso_de_gdal("ERROR 4: no such file") is None
        assert analizar_progreso_de_gdal("") is None


# --- El modelo -------------------------------------------------------------


class TestModelo:
    def test_la_bitacora_no_se_puede_editar(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path)
        job.registrar("algo paso")
        with pytest.raises(NotImplementedError):
            JobEvent.objects.filter(job=job).update(message="otra cosa")
        with pytest.raises(NotImplementedError):
            JobEvent.objects.filter(job=job).delete()

    def test_la_cola_de_stderr_se_recorta(self, usuario, origen, tmp_path):
        """GDAL con `CPL_DEBUG=ON` escupe megabytes, y una fila no es un archivo de log."""
        job = _trabajo(usuario, origen, tmp_path)
        evento = job.registrar("ruidoso", stderr_cola="x" * 100_000)
        assert len(evento.payload["stderr_cola"]) == JobEvent.MAXIMO_STDERR
        assert evento.payload["stderr_recortado"] is True

    def test_el_sondeo_se_espacia_con_el_tiempo(self, usuario, origen, tmp_path):
        """Un trabajo de tres horas no puede generar 10.800 peticiones."""
        from datetime import timedelta

        from django.utils import timezone

        job = _trabajo(usuario, origen, tmp_path)
        job.started_at = timezone.now()
        assert job.intervalo_de_sondeo_s == 1
        job.started_at = timezone.now() - timedelta(minutes=1)
        assert job.intervalo_de_sondeo_s == 2
        job.started_at = timezone.now() - timedelta(hours=1)
        assert job.intervalo_de_sondeo_s == 5

    def test_los_estados_terminales_paran_el_sondeo(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path)
        assert job.es_terminal is False
        job.status = HECHO
        assert job.es_terminal is True

    def test_calcula_la_reduccion(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path)
        job.source_size_bytes = 466_000_000
        job.output_size_bytes = 60_000_000
        assert job.reduccion == pytest.approx(0.871, abs=0.001)

    def test_solo_se_reintenta_lo_que_mejora_repitiendolo(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path, status=ERROR)
        job.reason_code = "sin-clave-ecw"
        assert job.es_reintentable is False
        job.reason_code = "origen-bloqueado"
        assert job.es_reintentable is True

    def test_no_se_reintenta_mas_alla_del_tope(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path, status=ERROR, attempt_count=3, max_attempts=3)
        job.reason_code = "origen-bloqueado"
        assert job.es_reintentable is False
