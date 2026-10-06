"""B-07 y B-08 de la auditoría de seguridad del 2026-10-05: la cola y los procesos.

- **B-08**: cancelar o agotar el plazo mataba solo al hijo directo. ODA, Wine, `Xvfb` y Office
  lanzan nietos que seguían vivos, con el archivo bloqueado y la memoria ocupada.
- **B-07**: `worker_pid` se pisaba con el PID del motor; al terminar el motor, el despachador veía
  un PID muerto y un latido viejo y marcaba «interrumpido» un trabajo que el obrero seguía haciendo.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import despachador, runner
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db

#: Un hijo que lanza un nieto dormilón, anota su PID y se queda esperando.
PADRE = """
import subprocess, sys, time
nieto = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w").write(str(nieto.pid))
time.sleep(120)
"""


def _esperar_pid(ruta: Path, hasta_s: float = 15.0) -> int:
    limite = time.monotonic() + hasta_s
    while time.monotonic() < limite:
        if ruta.exists() and ruta.read_text().strip():
            return int(ruta.read_text().strip())
        time.sleep(0.1)
    pytest.fail("el hijo no llegó a lanzar a su nieto")


def _murio(pid: int, hasta_s: float = 15.0) -> bool:
    limite = time.monotonic() + hasta_s
    while time.monotonic() < limite:
        if not despachador._vive(pid):
            return True
        time.sleep(0.1)
    return False


def _rematar(pid: int) -> None:
    """Que la prueba no deje un proceso de dos minutos si el arreglo falla."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
        else:
            os.kill(pid, 9)
    except OSError:
        pass


class TestB08MatarElArbol:
    def test_cancelar_mata_tambien_al_nieto(self, tmp_path):
        anotacion = tmp_path / "nieto.pid"
        hijo = subprocess.Popen(
            [sys.executable, "-c", PADRE, str(anotacion)], **runner._opciones_de_grupo()
        )
        nieto = _esperar_pid(anotacion)
        try:
            runner._matar(hijo)
            assert hijo.poll() is not None, "el hijo directo murió"
            assert _murio(nieto), "el nieto sobrevivió a la cancelación"
        finally:
            _rematar(nieto)

    def test_un_paso_posterior_que_se_pasa_de_plazo_mata_tambien_al_nieto(self, tmp_path):
        anotacion = tmp_path / "nieto.pid"
        with pytest.raises(subprocess.TimeoutExpired):
            runner._correr_en_grupo(
                [sys.executable, "-c", PADRE, str(anotacion)],
                cwd=None,
                entorno=os.environ.copy(),
                timeout_s=2,
            )
        nieto = _esperar_pid(anotacion)
        try:
            assert _murio(nieto), "el nieto sobrevivió al plazo del paso"
        finally:
            _rematar(nieto)

    def test_un_paso_normal_devuelve_su_salida_y_su_codigo(self):
        resultado = runner._correr_en_grupo(
            [sys.executable, "-c", "import sys; print('hola'); sys.exit(3)"],
            cwd=None,
            entorno=os.environ.copy(),
            timeout_s=30,
        )
        assert resultado.returncode == 3
        assert "hola" in resultado.stdout


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def registro_limpio():
    guardado = registry.todos()
    registry.limpiar()
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


class TestB07ElPidEsElDelObrero:
    def test_ejecutar_no_pisa_el_pid_del_obrero_con_el_del_motor(
        self, usuario, tmp_path, registro_limpio
    ):
        origen = tmp_path / "orto.tif"
        origen.write_bytes(geotiff_minimo(bandas=3))
        registry.registrar(MotorDeMentira(escribe="convertido"))
        job = ConversionJob.objects.create(
            owner=usuario,
            source_path=str(origen),
            source_name=origen.name,
            target_format_code="cog",
            output_path=str(tmp_path / "salida.tif"),
        )
        # Por el despachador, que es quien reclama el trabajo y fija el PID del obrero.
        assert despachador.procesar_una_vez() == 1
        job.refresh_from_db()
        assert job.status == "done", job.reason_detail
        assert job.worker_pid == os.getpid(), (
            "el PID guardado es el del obrero que ejecuta, no el de un hijo que ya terminó"
        )
