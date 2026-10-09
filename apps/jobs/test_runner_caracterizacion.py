"""Caracterización del corredor (F11.8, etapa 3): fija lo que hace **hoy**, antes de partirlo.

No son pruebas de diseño sino una red: cada una describe un camino del corredor tal como se
comporta en este momento —código de motivo, mensaje, nivel de la bitácora, lo que queda en
disco— para que el refactor que lo divide en módulos no pueda cambiar nada sin que alguna se
ponga roja. Los caminos felices y los de fallo van juntos; en todos los de fallo se comprueba
además que **el original sigue como estaba** (`sha256` y `mtime`), que es la regla cinco.

Los procesos hijos son de verdad (`MotorDeMentira` y un plan armado a mano con
`sys.executable`); lo único que no hay es GDAL.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.documents import motor as documentos
from apps.documents import secretos
from apps.engines import registry
from apps.engines.base import Disponibilidad, PlanDeEjecucion, Verificacion, ruta_parcial
from apps.engines.testing import MotorDeMentira
from apps.formats import crs as crs_mod
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import motivos as motivos_mod
from apps.jobs import runner
from apps.jobs.models import (
    CANCELADO,
    ENCOLADO,
    ERROR,
    HECHO,
    ConversionJob,
    EntradaDeTrabajo,
    JobEvent,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def origen(tmp_path):
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


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _trabajo(usuario, origen, tmp_path, **extra):
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="cog",
        output_path=str(tmp_path / "salida.tif"),
        **extra,
    )


def _eventos(job, **filtro):
    return list(JobEvent.objects.filter(job=job, **filtro).order_by("sequence"))


# --- Un motor que decide qué verifica y qué plan arma ------------------------------


class MotorConVeredicto(MotorDeMentira):
    """Igual que el de mentira, pero con el veredicto, los pasos posteriores y el plan a mano."""

    def __init__(self, *, veredicto=None, posteriores=(), salida_en_posteriores=False, **kw):
        super().__init__(**kw)
        self.veredicto = veredicto
        self.posteriores = posteriores
        self.salida_en_posteriores = salida_en_posteriores
        self.antes_de_verificar = None

    def plan(self, trabajo):
        plan = super().plan(trabajo)
        return replace(
            plan,
            posteriores=tuple(tuple(c) for c in self.posteriores),
            salida_en_posteriores=self.salida_en_posteriores,
        )

    def verificar(self, trabajo, salida):
        if self.antes_de_verificar:
            self.antes_de_verificar()
        if self.veredicto is not None:
            return self.veredicto
        return super().verificar(trabajo, salida)


def _py(codigo: str, *argumentos: str) -> tuple[str, ...]:
    return (sys.executable, "-c", codigo, *argumentos)


# =============================================================================
# Camino geoespacial
# =============================================================================


class TestOrigenYHuella:
    def test_un_origen_que_ya_no_existe_es_origen_no_legible(
        self, usuario, tmp_path, registro_limpio
    ):
        ausente = tmp_path / "nada.tif"
        job = _trabajo(usuario, ausente, tmp_path)

        resultado = runner.ejecutar(job)

        assert resultado.estado == ERROR
        assert resultado.codigo_motivo == "origen-no-legible"
        assert resultado.mensaje == f"Ya no hay ningún archivo en {ausente}."
        assert not (tmp_path / "salida.tif").exists()

    def test_un_archivo_que_no_es_nada_reconocible_levanta_el_motivo_de_la_inspeccion(
        self, usuario, tmp_path, registro_limpio
    ):
        vacio = tmp_path / "vacio.tif"
        vacio.write_bytes(b"")
        antes = _huella(vacio)

        resultado = runner.ejecutar(_trabajo(usuario, vacio, tmp_path))

        assert resultado.estado == ERROR
        assert resultado.codigo_motivo  # el que decida `deteccion.inspeccionar`
        assert _huella(vacio) == antes

    def test_guarda_el_tamano_del_original(self, usuario, origen, tmp_path, registro_limpio):
        registry.registrar(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.source_size_bytes == origen.stat().st_size


class TestElFinalDeCadaEstado:
    """`ejecutar` escribe el resultado en el trabajo y en la bitácora, siempre."""

    def test_hecho_deja_estado_y_evento_informativo(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        registry.registrar(MotorDeMentira())
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        job.refresh_from_db()
        assert (resultado.estado, resultado.codigo_motivo) == (HECHO, "")
        assert resultado.mensaje == "Convertido y verificado."
        assert job.status == HECHO
        assert job.reason_code == ""
        assert job.reason_detail == "Convertido y verificado."
        assert job.finished_at is not None
        ultimo = _eventos(job)[-1]
        assert (ultimo.level, ultimo.message) == (JobEvent.INFO, "Convertido y verificado.")

    def test_cancelado_es_un_aviso_y_no_un_error(self, usuario, origen, tmp_path, registro_limpio):
        from django.utils import timezone

        registry.registrar(MotorDeMentira(tarda_s=30, pasos=60))
        job = _trabajo(usuario, origen, tmp_path)
        ConversionJob.objects.filter(pk=job.pk).update(cancel_requested_at=timezone.now())

        resultado = runner.ejecutar(job)

        job.refresh_from_db()
        assert resultado.estado == CANCELADO
        assert resultado.mensaje == "Cancelado."
        assert job.status == CANCELADO
        ultimo = _eventos(job)[-1]
        assert ultimo.level == JobEvent.AVISO
        assert ultimo.reason_code == "cancelado-por-el-usuario"

    def test_un_error_es_un_evento_de_error_con_su_motivo(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        registry.registrar(MotorDeMentira(escribe="", codigo_de_salida=0))
        job = _trabajo(usuario, origen, tmp_path)

        runner.ejecutar(job)

        ultimo = _eventos(job)[-1]
        assert ultimo.level == JobEvent.ERROR
        assert ultimo.reason_code == "sin-salida"
        assert ultimo.message == "El motor termino sin escribir ningún archivo."

    def test_una_excepcion_inesperada_no_se_escapa(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        class MotorRoto(MotorDeMentira):
            def plan(self, trabajo):
                raise RuntimeError("se rompió el plan")

        registry.registrar(MotorRoto())
        antes = _huella(origen)
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)  # no levanta

        job.refresh_from_db()
        assert resultado.estado == ERROR
        assert resultado.codigo_motivo == "error-del-motor"
        assert resultado.mensaje == "RuntimeError: se rompió el plan"
        assert (job.status, job.reason_code) == (ERROR, "error-del-motor")
        assert _huella(origen) == antes

    def test_un_trabajo_sin_herramienta_no_toca_los_secretos(
        self, usuario, origen, tmp_path, registro_limpio, monkeypatch
    ):
        llamadas = []
        monkeypatch.setattr(secretos, "olvidar", lambda job: llamadas.append(job))
        registry.registrar(MotorDeMentira())
        runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert llamadas == []


class TestLaVerificacion:
    @pytest.mark.parametrize(
        ("veredicto", "codigo", "mensaje"),
        [
            (
                Verificacion(correcta=False, motivo="Está corrupta.", codigo_motivo="corrupta"),
                "corrupta",
                "Está corrupta.",
            ),
            (Verificacion(correcta=False, motivo="Vaya."), "salida-invalida", "Vaya."),
        ],
        ids=["con-codigo", "sin-codigo"],
    )
    def test_una_salida_que_no_verifica_se_borra_y_falla(
        self, usuario, origen, tmp_path, registro_limpio, veredicto, codigo, mensaje
    ):
        registry.registrar(MotorConVeredicto(veredicto=veredicto))
        antes = _huella(origen)
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert resultado.estado == ERROR
        assert (resultado.codigo_motivo, resultado.mensaje) == (codigo, mensaje)
        # La regla cinco: ni entregable ni parcial, y el original como estaba.
        assert not (tmp_path / "salida.tif").exists()
        assert not (tmp_path / "salida.parcial.tif").exists()
        assert _huella(origen) == antes

    def test_la_salida_vacia_no_verifica_aunque_el_codigo_sea_cero(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        """Regla uno: el motor escribe un archivo de cero bytes y sale con 0. `escribe=" "`
        no sirve (escribe un byte), así que se vacía el parcial en `plan`."""

        motor = MotorConVeredicto()

        def vaciar():
            parcial = ruta_parcial(motor.ultimo_plan.ruta_de_salida)
            parcial.write_bytes(b"")

        motor.antes_de_verificar = vaciar
        registry.registrar(motor)
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert (resultado.estado, resultado.codigo_motivo) == (ERROR, "salida-invalida")
        assert not (tmp_path / "salida.tif").exists()

    def test_lo_que_se_guarda_al_verificar(self, usuario, origen, tmp_path, registro_limpio):
        registry.registrar(
            MotorConVeredicto(
                veredicto=Verificacion(
                    correcta=True, detalles={"bytes": 7, "avisos": ["uno", "dos"]}
                ),
                escribe="contenido",
            )
        )
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        job.refresh_from_db()
        assert resultado.estado == HECHO, resultado.mensaje
        assert job.output_path == str(tmp_path / "salida.tif")
        assert job.output_size_bytes == len("contenido")
        assert job.verified_at is not None
        assert job.verification == {"bytes": 7, "avisos": ["uno", "dos"]}
        assert job.progress_percent == 100
        # Los avisos del motor quedan en la bitácora, con la etapa de verificación.
        avisos = _eventos(job, level=JobEvent.AVISO)
        assert [e.message for e in avisos] == ["uno", "dos"]
        assert {e.stage for e in avisos} == {"verificacion"}

    def test_el_original_que_cambia_durante_la_conversion_se_denuncia(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        motor = MotorConVeredicto()
        motor.antes_de_verificar = lambda: os.utime(
            origen, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000)
        )
        registry.registrar(motor)
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        # Sigue siendo `hecho`: se denuncia, no se revierte.
        assert resultado.estado == HECHO, resultado.mensaje
        errores = _eventos(job, level=JobEvent.ERROR)
        assert [e.message for e in errores] == [
            "El archivo de origen cambio durante la conversión. Revisa el motor."
        ]


class TestElLanzamiento:
    def test_un_ejecutable_que_no_existe_es_motor_no_disponible(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        class MotorSinBinario(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)
                return replace(plan, argv=("aeroconvert-no-existe-jamas", "--x"))

        registry.registrar(MotorSinBinario())
        antes = _huella(origen)

        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))

        assert resultado.codigo_motivo == "motor-no-disponible"
        assert resultado.mensaje == "No se pudo ejecutar aeroconvert-no-existe-jamas."
        assert _huella(origen) == antes

    def test_un_ejecutable_que_no_se_puede_lanzar_es_error_del_motor(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        class MotorConDirectorio(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)
                return replace(plan, argv=(str(tmp_path), "--x"))

        registry.registrar(MotorConDirectorio())

        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))

        assert resultado.codigo_motivo == "error-del-motor"
        assert resultado.mensaje.startswith("No se pudo lanzar el motor: ")

    def test_el_error_del_motor_lleva_la_ultima_linea_util(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        class MotorQueSeQueja(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)
                codigo = (
                    "import sys; print('0...50...', flush=True); "
                    "print('ERROR 4: no such file', file=sys.stderr); sys.exit(2)"
                )
                return replace(plan, argv=_py(codigo))

        registry.registrar(MotorQueSeQueja())
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert resultado.codigo_motivo == "error-del-motor"
        assert resultado.mensaje == "ERROR 4: no such file"
        evento = _eventos(job, level=JobEvent.ERROR)[0]
        assert evento.message == "El motor terminó con código 2."
        assert evento.payload["codigo_de_salida"] == 2
        assert "no such file" in evento.payload["stderr_cola"]

    def test_sin_linea_de_error_se_cita_el_codigo(self, usuario, origen, tmp_path, registro_limpio):
        class MotorMudo(MotorDeMentira):
            def plan(self, trabajo):
                return replace(super().plan(trabajo), argv=_py("import sys; sys.exit(5)"))

        registry.registrar(MotorMudo())
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert (resultado.codigo_motivo, resultado.mensaje) == ("error-del-motor", "Código 5.")

    def test_solo_se_guarda_el_final_de_la_salida(self, usuario, origen, tmp_path, registro_limpio):
        """Doscientas líneas como mucho: el principio de GDAL no dice nada que el argv no diga."""
        registry.registrar(MotorDeMentira(codigo_de_salida=1, pasos=260))
        job = _trabajo(usuario, origen, tmp_path)

        runner.ejecutar(job)

        cola = _eventos(job, level=JobEvent.ERROR)[0].payload["stderr_cola"].splitlines()
        assert len(cola) == 200
        assert cola[-1] == "100..."

    def test_el_mensaje_del_plazo(self, usuario, origen, tmp_path, registro_limpio):
        registry.registrar(MotorDeMentira(tarda_s=30, pasos=60, timeout_s=2))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "tardo-demasiado"
        assert resultado.mensaje == "La conversión paso de 0 minutos y se corto."
        assert not (tmp_path / "salida.parcial.tif").exists()

    def test_el_mensaje_del_atasco(self, usuario, origen, tmp_path, registro_limpio, settings):
        settings.SILENCIO_MAXIMO_S = 2
        registry.registrar(MotorDeMentira(tarda_s=30, pasos=1, timeout_s=3600))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "sin-avance"
        assert resultado.mensaje == "El motor lleva 0 minutos sin dar senales de vida."

    def test_un_motor_mudo_declarado_no_se_mata_por_silencio(
        self, usuario, origen, tmp_path, registro_limpio, settings
    ):
        """PDAL no emite avance: el silencio es su estado normal. Solo manda el plazo."""
        settings.SILENCIO_MAXIMO_S = 1

        class MotorMudoDeclarado(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)
                codigo = "import sys, time; time.sleep(3); open(sys.argv[1], 'wb').write(b'ok')"
                return replace(
                    plan,
                    argv=_py(codigo, str(ruta_parcial(plan.ruta_de_salida))),
                    emite_progreso=False,
                    analizador_de_progreso=None,
                )

        registry.registrar(MotorMudoDeclarado())
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.estado == HECHO, resultado.mensaje

    def test_el_progreso_con_etiqueta_pasa_a_la_barra(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        vistos = []

        def analizador(linea):
            if linea.startswith("50"):
                vistos.append(linea)
                return (0.5, "Mitad")
            return None

        class MotorConEtiqueta(MotorDeMentira):
            def plan(self, trabajo):
                return replace(super().plan(trabajo), analizador_de_progreso=analizador)

        registry.registrar(MotorConEtiqueta(pasos=2))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.estado == HECHO, resultado.mensaje
        assert vistos == ["50..."]


class TestLosPasosPosteriores:
    SUMAR = "import sys; open(sys.argv[1], 'ab').write(b'+')"

    def test_corren_en_orden_y_se_registran(self, usuario, origen, tmp_path, registro_limpio):
        parcial = str(tmp_path / "salida.parcial.tif")
        registry.registrar(
            MotorConVeredicto(
                escribe="base",
                posteriores=[_py(self.SUMAR, parcial), _py(self.SUMAR, parcial)],
            )
        )
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert resultado.estado == HECHO, resultado.mensaje
        assert (tmp_path / "salida.tif").read_bytes() == b"base++"
        pasos = [e.message for e in _eventos(job) if e.message.startswith("Paso posterior")]
        assert pasos == ["Paso posterior 1 de 2.", "Paso posterior 2 de 2."]
        assert (
            _eventos(job, message="Paso posterior 1 de 2.")[0].payload["argv"][0] == sys.executable
        )

    def test_un_paso_que_falla_borra_el_parcial_y_da_su_ultima_linea(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        fallo = "import sys; print('ERROR: piramides', file=sys.stderr); sys.exit(3)"
        registry.registrar(MotorConVeredicto(posteriores=[_py(fallo)]))
        antes = _huella(origen)
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert (resultado.estado, resultado.codigo_motivo) == (ERROR, "error-del-motor")
        assert resultado.mensaje == "ERROR: piramides"
        assert not (tmp_path / "salida.parcial.tif").exists()
        assert not (tmp_path / "salida.tif").exists()
        evento = _eventos(job, level=JobEvent.ERROR)[0]
        assert evento.message == "El paso posterior 1 termino con código 3."
        assert _huella(origen) == antes

    def test_un_paso_mudo_que_falla_dice_paso_fallido(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        registry.registrar(MotorConVeredicto(posteriores=[_py("import sys; sys.exit(1)")]))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert (resultado.codigo_motivo, resultado.mensaje) == ("error-del-motor", "Paso fallido.")

    def test_un_paso_que_no_se_puede_lanzar(self, usuario, origen, tmp_path, registro_limpio):
        registry.registrar(MotorConVeredicto(posteriores=[("aeroconvert-no-existe-jamas",)]))
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "error-del-motor"
        assert resultado.mensaje == "No se pudo lanzar el paso 1."
        assert not (tmp_path / "salida.parcial.tif").exists()

    def test_un_paso_que_pasa_del_plazo(self, usuario, origen, tmp_path, registro_limpio):
        registry.registrar(
            MotorConVeredicto(timeout_s=2, posteriores=[_py("import time; time.sleep(30)")])
        )
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.codigo_motivo == "tardo-demasiado"
        assert resultado.mensaje == "El paso 1 se corto."
        assert not (tmp_path / "salida.parcial.tif").exists()

    def test_la_salida_que_escribe_un_paso_posterior(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        parcial = str(tmp_path / "salida.parcial.tif")
        crear = "import sys; open(sys.argv[1], 'wb').write(b'del paso')"
        registry.registrar(
            MotorConVeredicto(
                escribe="", salida_en_posteriores=True, posteriores=[_py(crear, parcial)]
            )
        )
        resultado = runner.ejecutar(_trabajo(usuario, origen, tmp_path))
        assert resultado.estado == HECHO, resultado.mensaje
        assert (tmp_path / "salida.tif").read_bytes() == b"del paso"

    def test_si_ningun_paso_la_escribe_es_sin_salida(
        self, usuario, origen, tmp_path, registro_limpio
    ):
        registry.registrar(
            MotorConVeredicto(escribe="", salida_en_posteriores=True, posteriores=[_py("pass")])
        )
        job = _trabajo(usuario, origen, tmp_path)

        resultado = runner.ejecutar(job)

        assert (resultado.codigo_motivo, resultado.mensaje) == (
            "sin-salida",
            "El motor termino sin escribir ningún archivo.",
        )
        errores = [e.message for e in _eventos(job, level=JobEvent.ERROR)]
        assert "Los pasos posteriores terminaron sin escribir ningún archivo." in errores


class TestLosAcompanantes:
    def test_un_acompanante_que_no_se_puede_mover_se_denuncia(
        self, usuario, origen, tmp_path, registro_limpio, monkeypatch
    ):
        """El principal ya está en su sitio y parece correcto; hay que decir que falta algo."""
        registry.registrar(MotorDeMentira(escribe="x", escribe_acompanantes=(".shx",)))
        job = _trabajo(usuario, origen, tmp_path)
        job.target_format_code = "cog"
        job.save()
        from apps.formats import catalogo

        monkeypatch.setitem(
            catalogo.FORMATOS,
            "cog",
            replace(catalogo.FORMATOS["cog"], acompanantes=(".shx", ".dbf")),
        )
        reales = os.replace

        def replace_fallando(origen_, destino_):
            if str(destino_).endswith(".shx"):
                raise OSError("bloqueado")
            return reales(origen_, destino_)

        monkeypatch.setattr(os, "replace", replace_fallando)

        resultado = runner.ejecutar(job)

        assert resultado.estado == HECHO, resultado.mensaje
        errores = [e.message for e in _eventos(job, level=JobEvent.ERROR)]
        assert errores == [
            "No se pudo colocar salida.shx junto a la salida. El archivo puede no abrir sin el."
        ]


# =============================================================================
# El CRS
# =============================================================================


class _Insp:
    def __init__(self, crs=crs_mod.SIN_CRS, familia="raster"):
        self.crs = crs
        self.familia = familia


def _job_crs(usuario, origen="geotiff", destino="cog", **campos):
    return ConversionJob.objects.create(
        owner=usuario,
        source_path="/x/a",
        source_name="a",
        source_format_code=origen,
        target_format_code=destino,
        **campos,
    )


class TestExigirCrs:
    def test_un_crs_conocido_pasa_sin_decir_nada(self, usuario):
        job = _job_crs(usuario)
        conocido = crs_mod.Crs("EPSG", "32719", origen=crs_mod.INCRUSTADO)
        runner._exigir_crs(job, _Insp(conocido))
        assert _eventos(job) == []

    def test_una_observacion_gnss_no_echa_en_falta_el_sistema(self, usuario):
        job = _job_crs(usuario, origen="rinex", destino="rinex")
        runner._exigir_crs(job, _Insp(familia="gnss"))
        assert _eventos(job) == []

    def test_lo_declarado_a_mano_cuenta_y_queda_escrito(self, usuario):
        job = _job_crs(
            usuario,
            origen="puntos",
            destino="dxf",
            source_crs_origin=crs_mod.DECLARADO,
            source_crs_authority="EPSG",
            source_crs_code="32719",
        )
        runner._exigir_crs(job, _Insp(familia="vector"))
        evento = _eventos(job)[0]
        assert evento.level == JobEvent.AVISO
        assert evento.stage == "inspeccion"
        assert evento.message == (
            "El archivo no declara sistema de referencia. Se usa el declarado a mano: EPSG:32719."
        )

    def test_lo_declarado_sin_autoridad_se_toma_por_epsg(self, usuario):
        job = _job_crs(usuario, source_crs_origin=crs_mod.DECLARADO, source_crs_code="32719")
        runner._exigir_crs(job, _Insp())
        assert "EPSG:32719" in _eventos(job)[0].message

    def test_un_raster_hacia_un_destino_que_lo_exige_se_detiene(self, usuario):
        job = _job_crs(usuario, origen="png", destino="cog")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(job, _Insp())
        assert fallo.value.codigo == "crs-ausente"
        assert fallo.value.mensaje == (
            "El archivo no declara sistema de referencia y esta conversión lo necesita. "
            "Declara el EPSG: adivinarlo es peor que no tenerlo."
        )

    def test_reproyectar_sin_crs_se_detiene(self, usuario):
        job = _job_crs(usuario, origen="png", destino="jpeg", target_crs_code="32719")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(job, _Insp())
        assert fallo.value.codigo == "crs-ausente"

    def test_una_nube_sin_sistema_explica_por_que(self, usuario):
        job = _job_crs(usuario, origen="las", destino="copc")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(job, _Insp(familia="nube"))
        assert (
            "Una nube sin sistema de referencia no se puede cruzar con nada" in fallo.value.mensaje
        )

    def test_una_libreta_sin_sistema_explica_por_que(self, usuario):
        job = _job_crs(usuario, origen="puntos", destino="gpkg")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(job, _Insp(familia="vector"))
        assert "Una libreta de puntos no es más que coordenadas" in fallo.value.mensaje
        assert fallo.value.codigo == "crs-ausente"

    def test_si_nada_lo_exige_solo_avisa(self, usuario):
        job = _job_crs(usuario, origen="png", destino="jpeg")
        runner._exigir_crs(job, _Insp())
        evento = _eventos(job)[0]
        assert evento.level == JobEvent.AVISO
        assert evento.message == (
            "El archivo no declara sistema de referencia. Se convierte igual porque el destino "
            "tampoco lo exige, pero la salida tampoco lo tendra."
        )


class TestExigirMetros:
    def test_sin_destino_que_exija_metros_no_hace_nada(self, usuario):
        runner._exigir_metros(_job_crs(usuario, destino="cog"), _Insp())

    def test_un_origen_sin_crs_conocido_no_se_para(self, usuario):
        """Solo se para si **se sabe** que son grados: lo desconocido es asunto de `_exigir_crs`."""
        runner._exigir_metros(_job_crs(usuario, origen="kml", destino="dxf"), _Insp())

    def test_el_crs_declarado_del_trabajo_se_reconstruye(self, usuario):
        job = _job_crs(usuario, source_crs_code="4326", source_crs_authority="EPSG")
        crs = runner._crs_declarado_del_trabajo(job)
        assert (crs.autoridad, crs.codigo, crs.origen) == ("EPSG", "4326", crs_mod.DECLARADO)
        sin = runner._crs_declarado_del_trabajo(_job_crs(usuario))
        assert sin is crs_mod.SIN_CRS

    def test_grados_a_dxf_sin_destino_se_detiene_en_grados(self, usuario):
        job = _job_crs(usuario, origen="kml", destino="dxf", source_crs_code="4326")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_metros(job, _Insp())
        assert fallo.value.codigo == "crs-en-grados"

    def test_la_opcion_crs_destino_tambien_cuenta(self, usuario):
        job = _job_crs(
            usuario,
            origen="kml",
            destino="dxf",
            source_crs_code="4326",
            options={"crs_destino": "32719"},
        )
        runner._exigir_metros(job, _Insp())


class TestExigirCrudoEntero:
    def test_sin_trimble_no_mira_nada(self):
        runner._exigir_crudo_entero(None, SimpleNamespace(trimble=None))

    def test_un_crudo_entero_pasa(self, monkeypatch):
        from apps.formats import trimble

        monkeypatch.setattr(
            trimble, "comprobar_integridad", lambda ruta: trimble.IntegridadTrimble(54, 0)
        )
        runner._exigir_crudo_entero(None, SimpleNamespace(trimble=object(), ruta="/x/a.t02"))

    def test_un_crudo_sin_bloques(self, monkeypatch):
        from apps.formats import trimble

        monkeypatch.setattr(
            trimble, "comprobar_integridad", lambda ruta: trimble.IntegridadTrimble(0, 0)
        )
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crudo_entero(None, SimpleNamespace(trimble=object(), ruta="/x/a.t02"))
        assert fallo.value.codigo == "crudo-incompleto"
        assert fallo.value.mensaje == "El archivo no trae ningún bloque de datos."

    def test_un_crudo_cortado(self, monkeypatch):
        from apps.formats import trimble

        monkeypatch.setattr(
            trimble, "comprobar_integridad", lambda ruta: trimble.IntegridadTrimble(27, 1)
        )
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crudo_entero(None, SimpleNamespace(trimble=object(), ruta="/x/a.t02"))
        assert fallo.value.codigo == "crudo-incompleto"
        assert fallo.value.mensaje == (
            "El archivo está cortado: 1 de sus 27 bloques no llegan a su final."
        )


# =============================================================================
# Destino, espacio y renombrado
# =============================================================================


class TestDestinoLibre:
    def test_la_version_se_inserta_antes_de_la_primera_extension(self):
        assert runner._con_version(Path("a/salida.tif"), 2) == Path("a/salida_2.tif")
        assert runner._con_version(Path("a/nube.copc.laz"), 3) == Path("a/nube_3.copc.laz")
        assert runner._con_version(Path("a/salida"), 4) == Path("a/salida_4")

    def test_la_clave_de_ruta(self):
        assert runner._clave_de_ruta("") == ""
        assert runner._clave_de_ruta(None) == ""
        assert runner._clave_de_ruta("a/../b.tif") == os.path.normcase(str(Path("b.tif").resolve()))

    def test_nunca_el_propio_original(self, usuario, tmp_path):
        propio = tmp_path / "doc.pdf"
        propio.write_bytes(b"x")
        job = _trabajo(usuario, propio, tmp_path)
        assert runner._destino_libre(job, propio) == tmp_path / "doc_2.pdf"

    def test_la_entrada_de_un_trabajo_tambien_es_original(self, usuario, tmp_path):
        propio = tmp_path / "doc.pdf"
        propio.write_bytes(b"x")
        job = _trabajo(usuario, tmp_path / "otro.pdf", tmp_path)
        EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(propio), nombre="doc.pdf")
        assert runner._destino_libre(job, propio) == tmp_path / "doc_2.pdf"

    def test_su_propia_salida_anterior_se_reutiliza(self, usuario, origen, tmp_path):
        destino = tmp_path / "salida.tif"
        job = _trabajo(usuario, origen, tmp_path)
        assert runner._destino_libre(job, destino) == destino

    def test_cincuenta_versiones_bloquean(self, usuario, origen, tmp_path):
        destino = tmp_path / "salida.tif"
        otro = get_user_model().objects.create_user("otra", password="x" * 20)  # nosec B106
        for version in range(1, runner.MAXIMO_VERSIONES + 1):
            candidata = destino if version == 1 else runner._con_version(destino, version)
            ConversionJob.objects.create(
                owner=otro,
                source_path="/x",
                source_name="x",
                target_format_code="cog",
                output_path=str(candidata),
            )
        job = _trabajo(usuario, origen, tmp_path)

        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._destino_libre(job, destino)

        assert fallo.value.codigo == "salida-bloqueada"
        assert fallo.value.mensaje == (
            "Hay 50 versiones de salida.tif en esa carpeta. Revisa antes de seguir generando."
        )


class TestReservarDestino:
    def test_crea_la_carpeta_y_no_deja_testigos(self, tmp_path):
        destino = tmp_path / "a" / "b" / "salida.tif"
        runner._reservar_destino(destino)
        assert destino.parent.is_dir()
        assert list(destino.parent.iterdir()) == []

    def test_un_destino_existente_queda_como_estaba(self, tmp_path):
        destino = tmp_path / "salida.tif"
        destino.write_bytes(b"previo")
        runner._reservar_destino(destino)
        assert destino.read_bytes() == b"previo"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["salida.tif"]

    def test_un_testigo_previo_no_estorba(self, tmp_path):
        (tmp_path / "salida.tif.prueba").write_bytes(b"resto")
        runner._reservar_destino(tmp_path / "salida.tif")
        assert not (tmp_path / "salida.tif.prueba").exists()

    @pytest.mark.parametrize(
        ("excepcion", "esperado"),
        [
            (
                PermissionError("no"),
                "No se puede escribir en {carpeta}: sin permiso o carpeta bloqueada.",
            ),
            (OSError("disco roto"), "No se puede escribir en {carpeta}: disco roto"),
        ],
        ids=["permiso", "otro-os"],
    )
    def test_una_carpeta_en_la_que_no_se_puede_escribir(
        self, tmp_path, monkeypatch, excepcion, esperado
    ):
        import builtins

        reales = builtins.open

        def abrir(ruta, modo="r", *a, **k):
            if str(ruta).endswith(".prueba"):
                raise excepcion
            return reales(ruta, modo, *a, **k)

        monkeypatch.setattr(builtins, "open", abrir)
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._reservar_destino(tmp_path / "salida.tif")
        assert fallo.value.codigo == "salida-bloqueada"
        assert fallo.value.mensaje == esperado.format(carpeta=tmp_path)

    def test_un_destino_que_no_se_puede_renombrar_esta_en_uso(self, tmp_path, monkeypatch):
        destino = tmp_path / "salida.tif"
        destino.write_bytes(b"x")

        def no(a, b):
            raise OSError("en uso")

        monkeypatch.setattr(os, "replace", no)
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._reservar_destino(destino)
        assert fallo.value.codigo == "salida-bloqueada"
        assert (
            fallo.value.mensaje == "salida.tif esta abierto en otro programa. Cierralo y reintenta."
        )


class TestEspacio:
    def test_con_sitio_pasa(self, tmp_path):
        runner._exigir_espacio(tmp_path / "x.tif", 1)

    def test_sin_sitio_dice_cuanto_queda_y_cuanto_hace_falta(self, tmp_path, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(free=2_000_000_000))
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_espacio(tmp_path / "x.tif", 5_000_000_000)
        assert fallo.value.codigo == "sin-espacio"
        assert fallo.value.mensaje == ("Quedan 2.0 GB libres y la salida puede necesitar 5.0 GB.")

    def test_un_disco_que_no_se_puede_medir_no_rechaza(self, tmp_path, monkeypatch):
        import shutil

        def falla(p):
            raise OSError("no hay")

        monkeypatch.setattr(shutil, "disk_usage", falla)
        runner._exigir_espacio(tmp_path / "x.tif", 10**15)

    def test_sin_cabecera_de_tiff_no_se_estima_la_salida(self, usuario, origen, tmp_path):
        runner._exigir_espacio_de_la_salida(
            _trabajo(usuario, origen, tmp_path), SimpleNamespace(), tmp_path / "x.tif"
        )


class TestRenombrar:
    def test_renombra_y_el_parcial_desaparece(self, tmp_path):
        parcial = tmp_path / "s.tif.parcial"
        parcial.write_bytes(b"x")
        runner._renombrar(parcial, tmp_path / "s.tif")
        assert (tmp_path / "s.tif").read_bytes() == b"x"
        assert not parcial.exists()

    def test_un_fallo_que_no_es_de_permiso_no_se_reintenta(self, tmp_path):
        parcial = tmp_path / "s.tif.parcial"  # no existe
        inicio = time.monotonic()
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._renombrar(parcial, tmp_path / "s.tif")
        assert time.monotonic() - inicio < 0.4
        assert fallo.value.codigo == "salida-bloqueada"
        assert fallo.value.mensaje.startswith("No se pudo escribir s.tif: ")
        assert fallo.value.mensaje.endswith("Suele ser que este abierto en otro programa.")

    def test_el_permiso_se_reintenta_tres_veces_con_espera_creciente(self, tmp_path, monkeypatch):
        parcial = tmp_path / "s.tif.parcial"
        parcial.write_bytes(b"x")
        intentos, esperas = [], []

        def no(a, b):
            intentos.append(1)
            raise PermissionError("antivirus")

        monkeypatch.setattr(os, "replace", no)
        monkeypatch.setattr(time, "sleep", lambda s: esperas.append(s))
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._renombrar(parcial, tmp_path / "s.tif")
        assert len(intentos) == runner.REINTENTOS_DE_RENOMBRADO == 3
        assert esperas == [0.5, 1.0, 1.5]
        assert fallo.value.codigo == "salida-bloqueada"
        assert not parcial.exists()  # se borra: un parcial abandonado engaña

    def test_un_permiso_transitorio_acaba_bien(self, tmp_path, monkeypatch):
        parcial = tmp_path / "s.tif.parcial"
        parcial.write_bytes(b"x")
        reales = os.replace
        estado = {"n": 0}

        def a_la_segunda(a, b):
            estado["n"] += 1
            if estado["n"] < 2:
                raise PermissionError("antivirus")
            return reales(a, b)

        monkeypatch.setattr(os, "replace", a_la_segunda)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        runner._renombrar(parcial, tmp_path / "s.tif")
        assert (tmp_path / "s.tif").exists()


class TestBorrarYLimpiar:
    def test_borrar_un_archivo_que_no_esta_no_falla(self, tmp_path):
        runner._borrar(tmp_path / "no.txt")

    def test_borrar_un_parcial_se_lleva_lo_que_colgo_de_su_nombre(self, tmp_path):
        parcial = tmp_path / "s.tif.parcial"
        parcial.write_bytes(b"x")
        (tmp_path / "s.tif.parcial.aux.xml").write_text("<x/>")
        (tmp_path / "s.tif.parcial.gpkg").write_bytes(b"x")
        (tmp_path / "s.tif").write_bytes(b"destino")  # no cuelga del parcial
        runner._borrar(parcial)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["s.tif"]

    def test_solo_la_carpeta_lo_del_parcial_se_borra_y_otras_carpetas_no(self, tmp_path):
        parcial = tmp_path / "s.docx.parcial"
        parcial.write_bytes(b"x")
        trabajo = tmp_path / "s.docx.parcial.lo"
        trabajo.mkdir()
        (trabajo / "perfil").write_text("x")
        ajena = tmp_path / "s.docx.parcial.otra"
        ajena.mkdir()
        runner._borrar(parcial)
        assert not trabajo.exists()
        assert ajena.exists()

    def test_un_archivo_que_no_es_parcial_no_arrastra_nada(self, tmp_path):
        ruta = tmp_path / "a.tif"
        ruta.write_bytes(b"x")
        vecino = tmp_path / "a.tif.aux.xml"
        vecino.write_text("<x/>")
        runner._borrar(ruta)
        assert not ruta.exists()
        assert vecino.exists()

    def test_borrar_traga_un_oserror(self, tmp_path, monkeypatch):
        ruta = tmp_path / "a.tif.parcial"
        ruta.write_bytes(b"x")

        def no(self, missing_ok=False):
            raise OSError("abierto")

        monkeypatch.setattr(Path, "unlink", no)
        runner._borrar(ruta)  # no levanta

    def test_limpiar_restos_borra_por_prefijo_y_respeta_el_destino(self, tmp_path):
        parcial = tmp_path / "entrega.jp2.parcial"
        (tmp_path / "entrega.jp2.parcial.aux.xml").write_text("<x/>")
        (tmp_path / "entrega.jp2").write_bytes(b"destino")
        runner._limpiar_restos(parcial)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["entrega.jp2"]

    def test_limpiar_restos_traga_un_oserror(self, tmp_path, monkeypatch):
        def no(self, patron):
            raise OSError("raro")

        monkeypatch.setattr(Path, "glob", no)
        runner._limpiar_restos(tmp_path / "a.parcial")


class TestUltimaLineaUtil:
    def test_prefiere_la_ultima_que_diga_error_o_fail(self):
        texto = "0...10\nERROR 1: primero\nsolo ruido\nFAILED al cerrar\nfinal"
        assert runner._ultima_linea_util(texto) == "FAILED al cerrar"

    def test_sin_error_toma_la_ultima_no_vacia(self):
        assert runner._ultima_linea_util("uno\n\n  dos  \n\n") == "dos"

    def test_se_recorta_a_quinientos(self):
        assert len(runner._ultima_linea_util("ERROR " + "x" * 900)) == 500

    def test_vacio(self):
        assert runner._ultima_linea_util("") == ""


# =============================================================================
# Procesos
# =============================================================================


class TestLeerSalida:
    def _leer(self, trozos: list[bytes]):
        """Pasa los trozos por un hijo real y devuelve lo que sale del lector."""
        import queue

        codigo = (
            "import sys, time\n"
            "for t in sys.argv[1:]:\n"
            "    crudo = t.encode('latin1').decode('unicode_escape').encode('latin1')\n"
            "    sys.stdout.buffer.write(crudo)\n"
            "    sys.stdout.buffer.flush(); time.sleep(0.05)\n"
        )
        proceso = subprocess.Popen(  # nosec B603
            _py(codigo, *[t.decode("latin1") for t in trozos]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        cola: queue.Queue = queue.Queue()
        hilo = threading.Thread(target=runner._leer_salida, args=(proceso, cola), daemon=True)
        hilo.start()
        proceso.wait()
        hilo.join(5)
        salida = []
        while True:
            x = cola.get(timeout=5)
            if x is None:
                return salida
            salida.append(x)

    def test_corta_por_salto_y_por_retorno_de_carro(self):
        assert self._leer([b"uno\\ndos\\rtres\\n"]) == ["uno", "dos", "tres"]

    def test_emite_el_avance_de_gdal_sin_esperar_al_salto(self):
        # `0...10...` termina en punto: sale aunque no haya salto de línea.
        assert self._leer([b"0...10...", b"20...30...\\n"]) == ["0...10...", "0...10...20...30..."]

    def test_lo_que_queda_sin_cerrar_sale_al_terminar(self):
        assert self._leer([b"sin salto"]) == ["sin salto"]

    def test_las_lineas_en_blanco_no_salen(self):
        assert self._leer([b"\\n\\n  \\nhola\\n"]) == ["hola"]

    def test_los_bytes_raros_se_sustituyen(self):
        assert self._leer([b"a\\xffb\\n"]) == ["a�b"]

    def test_sin_stdout_solo_pone_el_fin(self):
        import queue

        cola: queue.Queue = queue.Queue()
        runner._leer_salida(SimpleNamespace(stdout=None), cola)
        assert cola.get_nowait() is None

    def test_un_descriptor_roto_acaba_igual(self):
        import queue

        class Roto:
            def fileno(self):
                raise ValueError("cerrado")

        cola: queue.Queue = queue.Queue()
        runner._leer_salida(SimpleNamespace(stdout=Roto()), cola)
        assert cola.get_nowait() is None


class TestGrupoDeProcesos:
    def test_las_opciones_de_grupo_segun_el_sistema(self):
        opciones = runner._opciones_de_grupo()
        if os.name == "nt":
            assert opciones == {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            assert opciones == {"start_new_session": True}

    def test_matar_termina_al_hijo(self):
        hijo = subprocess.Popen(  # nosec B603
            _py("import time; time.sleep(60)"), **runner._opciones_de_grupo()
        )
        runner._matar(hijo)
        assert hijo.poll() is not None

    def test_si_no_se_puede_senalar_el_arbol_se_cae_al_hijo(self, monkeypatch):
        llamadas = []

        class Falso:
            pid = 1

            def terminate(self):
                llamadas.append("terminate")

            def kill(self):
                llamadas.append("kill")

        def no(*a, **k):
            raise OSError("sin taskkill")

        monkeypatch.setattr(subprocess, "run", no)
        monkeypatch.setattr(os, "killpg", no, raising=False)
        runner._senalar_arbol(Falso(), a_la_fuerza=False)
        runner._senalar_arbol(Falso(), a_la_fuerza=True)
        assert llamadas == ["terminate", "kill"]

    def test_correr_en_grupo_devuelve_lo_que_dijo_el_hijo(self):
        resultado = runner._correr_en_grupo(
            list(_py("import sys; print('hola'); print('mal', file=sys.stderr); sys.exit(4)")),
            cwd=None,
            entorno=os.environ.copy(),
            timeout_s=30,
        )
        assert resultado.returncode == 4
        assert resultado.stdout.strip() == "hola"
        assert resultado.stderr.strip() == "mal"

    def test_correr_en_grupo_decodifica_utf8_aunque_la_pagina_de_codigos_sea_otra(self):
        """En Windows `text=True` sin `encoding` decodifica con cp1252 y «á» sale «Ã¡»."""
        codigo = (
            "import sys\n"
            "sys.stdout.buffer.write('pirámides'.encode('utf-8'))\n"
            "sys.stderr.buffer.write(b'ca\\xffo \\xc3\\xb1')\n"  # un byte inválido no tumba
        )
        resultado = runner._correr_en_grupo(
            list(_py(codigo)), cwd=None, entorno=os.environ.copy(), timeout_s=30
        )
        assert resultado.stdout == "pirámides"
        assert resultado.stderr.endswith("o ñ")
        assert "�" in resultado.stderr


# =============================================================================
# Reclamo y entregables ajenos
# =============================================================================


class TestReclamoCaracterizado:
    def test_reclamar_apunta_quien_lo_tiene(self, usuario, origen, tmp_path):
        import socket

        job = _trabajo(usuario, origen, tmp_path)
        assert runner.reclamar(job.pk) is True
        job.refresh_from_db()
        assert job.worker_host == socket.gethostname()[:80]
        assert job.started_at is not None and job.heartbeat_at is not None

    def test_no_reclama_lo_que_no_esta_encolado(self, usuario, origen, tmp_path):
        job = _trabajo(usuario, origen, tmp_path, status=ERROR)
        assert runner.reclamar(job.pk) is False
        job.refresh_from_db()
        assert job.attempt_count == 0


# =============================================================================
# Documentos
# =============================================================================


@pytest.fixture
def doc(usuario, tmp_path, monkeypatch):
    """Un trabajo de documentos y el motor de documentos sustituido por uno controlable.

    Lo único que se sustituye es `apps.documents.motor` (disponibilidad, plan, informe,
    verificación): el corredor lo importa y lo llama por atributo, así que esto vale igual
    antes y después de partirlo. Los procesos hijos son los de verdad."""
    origen = tmp_path / "entrada.pdf"
    origen.write_bytes(b"%PDF-1.4 de mentira")
    job = ConversionJob.objects.create(
        owner=usuario,
        herramienta="numerar",
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="doc:numerar",
        output_path=str(tmp_path / "entrada_numerado.pdf"),
        status=ENCOLADO,
    )
    EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(origen), nombre=origen.name)

    estado = SimpleNamespace(
        origen=origen,
        informe={},
        disponible=Disponibilidad.si("docs 1.0"),
        veredicto=Verificacion(correcta=True, detalles={"paginas_verificadas": 1}),
        hijo="import sys; open(sys.argv[1], 'wb').write(b'hecho')",
        hijo_codigo=0,
        salida_opcional=False,
        plan_levanta=None,
        auxiliares_borrados=0,
        informe_al_lanzar=None,
        tras_lanzar=None,
    )

    def plan(trabajo):
        if estado.plan_levanta:
            raise estado.plan_levanta
        destino = Path(trabajo.output_path)
        codigo = estado.hijo + f"\nsys.exit({estado.hijo_codigo})"
        return PlanDeEjecucion(
            argv=_py("import sys\n" + codigo, str(ruta_parcial(destino))),
            ruta_de_salida=destino,
            timeout_s=60,
            salida_opcional=estado.salida_opcional,
        )

    def leer_informe(trabajo):
        if estado.tras_lanzar:
            estado.tras_lanzar()
        return dict(estado.informe)

    def borrar_auxiliares(trabajo):
        estado.auxiliares_borrados += 1

    monkeypatch.setattr(documentos, "disponibilidad", lambda h, o=None: estado.disponible)
    monkeypatch.setattr(documentos, "plan", plan)
    monkeypatch.setattr(documentos, "leer_informe", leer_informe)
    monkeypatch.setattr(documentos, "borrar_auxiliares", borrar_auxiliares)
    monkeypatch.setattr(
        documentos, "verificar", lambda parcial, informe, plan=None: estado.veredicto
    )
    estado.job = job
    return estado


def _correr_doc(job):
    assert runner.reclamar(job.pk)
    job.refresh_from_db()
    resultado = runner.ejecutar(job)
    job.refresh_from_db()
    return resultado


class TestDocumentoCaminoFeliz:
    def test_hecho_con_huella_de_cada_entrada_y_salida_verificada(self, doc):
        antes = _huella(doc.origen)
        resultado = _correr_doc(doc.job)
        job = doc.job

        assert (resultado.estado, resultado.codigo_motivo) == (HECHO, "")
        assert resultado.mensaje == "Hecho y verificado."
        assert job.engine_id == "documentos"
        assert job.engine_version == "docs 1.0"
        assert Path(job.output_path).read_bytes() == b"hecho"
        assert job.output_size_bytes == 5
        assert job.verification == {"paginas_verificadas": 1}
        assert job.verified_at is not None
        assert job.desenlace == ""
        assert job.source_sha256 == antes[0]
        assert job.source_size_bytes == doc.origen.stat().st_size
        entrada = job.entradas.get()
        assert (entrada.sha256, entrada.mtime_ns) == antes
        assert job.progress_percent == 100
        assert doc.auxiliares_borrados == 1
        assert not list(doc.origen.parent.glob("*.parcial*"))
        assert _huella(doc.origen) == antes

    @pytest.mark.django_db(transaction=True)
    def test_sin_entradas_la_unica_es_source_path(self, doc):
        doc.job.entradas.all().delete()
        resultado = _correr_doc(doc.job)
        assert resultado.estado == HECHO, resultado.mensaje
        assert doc.job.entradas.count() == 0  # no hay fila que guardar
        assert doc.job.source_sha256 == hashlib.sha256(doc.origen.read_bytes()).hexdigest()

    def test_varias_entradas_se_huellan_todas_y_la_primera_manda(self, doc, tmp_path):
        segunda = tmp_path / "otra.pdf"
        segunda.write_bytes(b"otra cosa")
        EntradaDeTrabajo.objects.create(job=doc.job, orden=1, ruta=str(segunda), nombre="otra.pdf")
        resultado = _correr_doc(doc.job)
        assert resultado.estado == HECHO, resultado.mensaje
        filas = list(doc.job.entradas.order_by("orden"))
        assert filas[1].sha256 == hashlib.sha256(b"otra cosa").hexdigest()
        assert doc.job.source_sha256 == filas[0].sha256
        assert doc.job.source_size_bytes == filas[0].bytes + filas[1].bytes

    def test_los_avisos_del_informe_dejan_con_avisos(self, doc):
        doc.informe = {"avisos": ["una página sin texto", "otra"]}
        resultado = _correr_doc(doc.job)
        assert resultado.estado == HECHO, resultado.mensaje
        assert doc.job.desenlace == "con-avisos"
        avisos = _eventos(doc.job, level=JobEvent.AVISO)
        assert [e.message for e in avisos] == ["una página sin texto", "otra"]
        assert {e.stage for e in avisos} == {"verificacion"}

    def test_el_trabajo_de_documentos_suelta_las_subidas_y_olvida_el_secreto(
        self, doc, monkeypatch
    ):
        olvidados = []
        monkeypatch.setattr(secretos, "olvidar", lambda job: olvidados.append(job.pk))
        _correr_doc(doc.job)
        assert olvidados == [doc.job.pk]

    def test_tambien_olvida_el_secreto_si_fallo_antes_de_tomarlo(self, doc, monkeypatch):
        olvidados = []
        monkeypatch.setattr(secretos, "olvidar", lambda job: olvidados.append(job.pk))
        doc.origen.unlink()
        resultado = _correr_doc(doc.job)
        assert resultado.estado == ERROR
        assert olvidados == [doc.job.pk]

    def test_soltar_subidas_da_margen_para_reintentar(self, doc):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import ArchivoSubido
        from apps.core.subidas import HORAS_DE_VIDA

        subida = ArchivoSubido.objects.create(
            owner=doc.job.owner, nombre_original="s.pdf", size_bytes=1, expires_at=None
        )
        entrada = doc.job.entradas.get()
        entrada.subida = subida
        entrada.save()

        runner._soltar_subidas(doc.job)

        subida.refresh_from_db()
        assert subida.expires_at > timezone.now() + timedelta(hours=HORAS_DE_VIDA - 1)


class TestDocumentoFallos:
    @pytest.fixture(autouse=True)
    def _original(self, doc):
        self.antes = _huella(doc.origen)
        yield
        # La regla cinco, en **cada** camino de fallo de esta clase.
        assert _huella(doc.origen) == self.antes

    def test_una_entrada_que_ya_no_esta(self, doc):
        doc.origen.rename(doc.origen.with_name("movido.pdf"))
        resultado = _correr_doc(doc.job)
        assert resultado.codigo_motivo == "origen-no-legible"
        assert resultado.mensaje == f"Ya no hay ningún archivo en {doc.origen}."
        doc.origen.with_name("movido.pdf").rename(doc.origen)

    def test_la_herramienta_no_disponible_da_su_motivo(self, doc):
        doc.disponible = Disponibilidad.no("sin-office", "No hay Office.")
        resultado = _correr_doc(doc.job)
        assert (resultado.estado, resultado.codigo_motivo) == (ERROR, "sin-office")
        assert resultado.mensaje == "No hay Office."
        assert not Path(doc.job.output_path).exists()

    def test_sin_codigo_de_motivo_es_sin_motor(self, doc):
        doc.disponible = Disponibilidad.no("", "Nada.")
        resultado = _correr_doc(doc.job)
        assert resultado.codigo_motivo == "sin-motor"

    def test_falta_la_contrasena(self, doc):
        doc.plan_levanta = secretos.SinSecreto("Falta la contraseña de este trabajo.")
        resultado = _correr_doc(doc.job)
        assert resultado.codigo_motivo == "falta-la-contrasena"
        assert resultado.mensaje == "Falta la contraseña de este trabajo."

    def test_el_hijo_que_falla_dice_el_motivo_verdadero_por_el_informe(self, doc):
        doc.hijo_codigo = 1
        doc.informe = {"codigo": "contrasena-incorrecta", "mensaje": "La contraseña no abre."}
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == (
            "contrasena-incorrecta",
            "La contraseña no abre.",
        )

    def test_el_hijo_que_falla_sin_informe_es_error_del_motor(self, doc):
        doc.hijo_codigo = 1
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == ("error-del-motor", "Código 1.")
        assert doc.auxiliares_borrados == 1  # el `finally` corre también en el fallo

    def test_el_informe_sin_mensaje_conserva_el_del_corredor(self, doc):
        doc.hijo_codigo = 1
        doc.informe = {"codigo": "documento-invalido"}
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == ("documento-invalido", "Código 1.")

    def test_el_informe_que_declara_un_motivo_aunque_el_hijo_salga_bien(self, doc):
        doc.informe = {"codigo": "documento-invalido", "mensaje": "No es un PDF."}
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == (
            "documento-invalido",
            "No es un PDF.",
        )
        assert not list(doc.origen.parent.glob("*.parcial*"))
        assert not Path(doc.job.output_path).exists()

    def test_el_informe_con_motivo_sin_mensaje(self, doc):
        doc.informe = {"codigo": "documento-invalido"}
        resultado = _correr_doc(doc.job)
        assert resultado.codigo_motivo == "documento-invalido"
        assert resultado.mensaje == motivos_mod.mensaje("documento-invalido")

    def test_sin_archivo_el_corredor_lo_dice_antes_de_mirar_el_informe(self, doc):
        """Sin `salida_opcional`, `_lanzar` ya cierra el paso: código 0 y ningún archivo."""
        doc.hijo = "pass"
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == (
            "sin-salida",
            "El motor termino sin escribir ningún archivo.",
        )
        errores = [e.message for e in _eventos(doc.job, level=JobEvent.ERROR)]
        assert "El motor termino con código 0 pero no escribio ningún archivo." in errores

    def test_salida_opcional_sin_desenlace_es_sin_salida(self, doc):
        """La excepción a la regla uno exige que el hijo **diga por qué**."""
        doc.hijo = "pass"
        doc.salida_opcional = True
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == (
            "sin-salida",
            "La herramienta terminó sin escribir nada.",
        )
        errores = [e.message for e in _eventos(doc.job, level=JobEvent.ERROR)]
        assert "La herramienta terminó sin escribir ningún archivo y sin decir por qué." in errores

    def test_sin_archivo_y_desenlace_pero_sin_declarar_salida_opcional_sigue_siendo_sin_salida(
        self, doc
    ):
        """La excepción a la regla uno exige las **dos** cosas: plan y desenlace."""
        doc.hijo = "pass"
        doc.informe = {"desenlace": "no-valio-la-pena"}
        doc.salida_opcional = False
        assert _correr_doc(doc.job).codigo_motivo == "sin-salida"

    def test_salida_opcional_con_un_desenlace_que_no_existe_es_sin_salida(self, doc):
        doc.hijo = "pass"
        doc.informe = {"desenlace": "me-lo-invento"}
        doc.salida_opcional = True
        assert _correr_doc(doc.job).codigo_motivo == "sin-salida"

    def test_la_verificacion_que_falla_borra_el_parcial(self, doc):
        doc.veredicto = Verificacion(
            correcta=False, motivo="Sin páginas.", codigo_motivo="pdf-roto"
        )
        resultado = _correr_doc(doc.job)
        assert (resultado.codigo_motivo, resultado.mensaje) == ("pdf-roto", "Sin páginas.")
        assert not list(doc.origen.parent.glob("*.parcial*"))
        assert not Path(doc.job.output_path).exists()
        assert doc.auxiliares_borrados == 1

    def test_la_verificacion_sin_codigo_es_salida_invalida(self, doc):
        doc.veredicto = Verificacion(correcta=False, motivo="Mal.")
        assert _correr_doc(doc.job).codigo_motivo == "salida-invalida"

    def test_la_cancelacion_mata_al_hijo_y_borra_el_parcial(self, doc):
        from django.utils import timezone

        doc.hijo = "import time; time.sleep(60)"
        ConversionJob.objects.filter(pk=doc.job.pk).update(cancel_requested_at=timezone.now())
        resultado = _correr_doc(doc.job)
        assert resultado.estado == CANCELADO
        assert resultado.codigo_motivo == "cancelado-por-el-usuario"
        assert not list(doc.origen.parent.glob("*.parcial*"))

    def test_un_destino_que_es_el_propio_original_se_desvia(self, doc):
        """Una herramienta que escribe `.pdf` sobre un `.pdf`: nunca el propio original."""
        ConversionJob.objects.filter(pk=doc.job.pk).update(output_path=str(doc.origen))
        doc.job.refresh_from_db()
        resultado = _correr_doc(doc.job)
        assert resultado.estado == HECHO, resultado.mensaje
        assert Path(doc.job.output_path).name == "entrada_2.pdf"


class TestDocumentoSinArchivoPorDesenlace:
    def test_el_desenlace_declarado_es_un_hecho_sin_descarga(self, doc):
        doc.hijo = "pass"
        doc.informe = {"desenlace": "no-valio-la-pena", "detalles": {"antes": 10, "despues": 12}}
        doc.salida_opcional = True
        antes = _huella(doc.origen)

        resultado = _correr_doc(doc.job)
        job = doc.job

        assert (resultado.estado, resultado.codigo_motivo) == (HECHO, "")
        assert resultado.mensaje.startswith("Ya estaba comprimido")
        assert job.desenlace == "no-valio-la-pena"
        assert job.verification == {"antes": 10, "despues": 12}
        assert job.output_path == ""
        assert job.verified_at is not None
        assert job.progress_percent == 100
        assert _huella(doc.origen) == antes

    def test_sin_detalles_queda_un_diccionario_vacio(self, doc):
        doc.hijo = "pass"
        doc.informe = {"desenlace": "sin-imagenes"}
        doc.salida_opcional = True
        _correr_doc(doc.job)
        assert doc.job.verification == {}


class TestComprobarOriginales:
    def test_una_entrada_modificada_se_denuncia_con_su_nombre(self, doc):
        def tocar():
            os.utime(doc.origen, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))

        doc.tras_lanzar = tocar
        resultado = _correr_doc(doc.job)
        assert resultado.estado == HECHO, resultado.mensaje
        errores = [e.message for e in _eventos(doc.job, level=JobEvent.ERROR)]
        assert errores == [
            "El archivo de origen entrada.pdf cambió durante el trabajo. Revisa la herramienta."
        ]

    def test_tambien_se_denuncia_en_un_hecho_sin_archivo(self, doc):
        doc.hijo = "pass"
        doc.informe = {"desenlace": "sin-imagenes"}
        doc.salida_opcional = True
        doc.tras_lanzar = lambda: os.utime(
            doc.origen, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000)
        )
        _correr_doc(doc.job)
        assert len(_eventos(doc.job, level=JobEvent.ERROR)) == 1

    def test_una_entrada_que_desaparece_no_se_denuncia(self, doc):
        entrada = doc.job.entradas.get()
        entrada.mtime_ns = 1
        entrada.ruta = str(doc.origen.with_name("nada.pdf"))
        runner._comprobar_originales(doc.job, [entrada])
        assert _eventos(doc.job) == []

    def test_una_entrada_sin_huella_no_se_compara(self, doc):
        entrada = EntradaDeTrabajo(orden=0, ruta=str(doc.origen), nombre="entrada.pdf")
        runner._comprobar_originales(doc.job, [entrada])
        assert _eventos(doc.job) == []


class TestLaSuperficiePublica:
    """Lo que importan otros paquetes: si el refactor lo mueve, esto se pone rojo."""

    @pytest.mark.parametrize(
        "nombre",
        [
            "TrabajoFallido",
            "Resultado",
            "reclamar",
            "ejecutar",
            "LATIDO_S",
            "GRACIA_AL_CANCELAR_S",
            "REINTENTOS_DE_RENOMBRADO",
            "MAXIMO_VERSIONES",
            "_borrar",
            "_destino_libre",
            "_exigir_crs",
            "_exigir_metros",
            "_exigir_memoria",
            "_exigir_crudo_entero",
            "_exigir_espacio",
            "_exigir_espacio_de_la_salida",
            "_comprobar_originales",
            "_opciones_de_grupo",
            "_matar",
            "_correr_en_grupo",
            "_lanzar",
            "_renombrar",
            "_reservar_destino",
            "_limpiar_restos",
            "_ultima_linea_util",
            "_leer_salida",
            "_senalar_arbol",
            "_soltar_subidas",
        ],
    )
    def test_el_nombre_sigue_en_el_modulo(self, nombre):
        assert hasattr(runner, nombre)

    def test_resultado_y_el_fallo_conservan_su_forma(self):
        r = runner.Resultado(ERROR, "x", "y")
        assert (r.estado, r.codigo_motivo, r.mensaje) == (ERROR, "x", "y")
        f = runner.TrabajoFallido("sin-salida")
        assert f.codigo == "sin-salida"
        assert f.mensaje  # el del catálogo
        assert runner.TrabajoFallido("x", "texto").mensaje == "texto"
