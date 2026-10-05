"""El motor con el `convertToRinex.exe` de Trimble **de verdad** y archivos de campo reales.

Es la prueba que no puede estar en la puerta de calidad: necesita un programa de Windows con
licencia propia y datos de un cliente. Por eso va marcada `oraculo` (queda fuera de
`pytest.ini`) y **las rutas de los datos vienen del entorno**, no del repositorio:

    $env:AEROCONVERT_PRUEBA_T02 = "D:\\ruta\\a\\un.T02"
    $env:AEROCONVERT_PRUEBA_T04 = "D:\\ruta\\a\\un.T04"
    uv run pytest -m oraculo apps/gnss/tests/test_con_trimble_real.py

No hay oráculo para la integridad del RINEX frente al crudo —el T0x es un formato cerrado—, y
no se finge. Lo que esto comprueba es lo comprobable: que la cadena entera funcione con el
programa real, que lo escrito se lea con un lector que no es el de Trimble, y que el original
no se toque. Las cifras de cada corrida van fechadas en `docs/PRUEBAS_CON_ORACULO.md`.
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry, sondas
from apps.gnss import motores
from apps.jobs import runner
from apps.jobs.models import ENCOLADO, HECHO, ConversionJob

pytestmark = [pytest.mark.oraculo, pytest.mark.django_db(transaction=True)]


def _datos(variable: str) -> Path:
    ruta = os.environ.get(variable, "").strip()
    if not ruta or not Path(ruta).is_file():
        pytest.skip(f"{variable} no apunta a un archivo: sin datos reales no se puede probar.")
    return Path(ruta)


@pytest.fixture(autouse=True)
def hay_convertidor(settings, tmp_path):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    if not sondas.sondar_trimble_rinex().disponible:
        pytest.skip("No hay convertidor de Trimble en esta máquina.")
    registry.registrar(motores.MotorTrimbleARinex())


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


@pytest.mark.parametrize("variable", ["AEROCONVERT_PRUEBA_T02", "AEROCONVERT_PRUEBA_T04"])
def test_convierte_un_crudo_real(tmp_path, variable):
    crudo = _datos(variable)
    antes = _huella(crudo)
    usuario = get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    job = ConversionJob.objects.create(
        owner=usuario,
        source_path=str(crudo),
        source_name=crudo.name,
        target_format_code="rinex",
        output_path=str(tmp_path / "salida_rinex.zip"),
        status=ENCOLADO,
    )
    assert runner.reclamar(job.pk)
    job.refresh_from_db()
    runner.ejecutar(job)
    job.refresh_from_db()

    assert job.status == HECHO, job.reason_detail
    d = job.verification
    assert d["epocas"] > 0
    assert d["huecos"] == 0, f"hay huecos: {d['avisos']}"
    assert d["receptor"].upper().startswith("TRIMBLE")
    assert d["bloques_del_crudo"] > 0
    assert not any("crudo es de un" in a for a in d["avisos"]), d["avisos"]

    with zipfile.ZipFile(job.output_path) as z:
        assert any(n.endswith("o") for n in z.namelist()), z.namelist()

    assert _huella(crudo) == antes, "el original cambió"
    assert not list((tmp_path / "trabajo").rglob("*")), "quedó algo en la carpeta de trabajo"
    print(
        f"\n{crudo.name}: {d['epocas']} épocas, {d['intervalo_s']} s, {d['primera']} a "
        f"{d['ultima']}, {d['receptor']}, {d['constelaciones']}, {len(d['archivos'])} archivos"
    )
