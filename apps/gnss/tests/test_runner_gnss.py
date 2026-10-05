"""El corredor con el convertidor de Trimble, **con un proceso hijo de verdad**.

El convertidor es de mentira (`convertidor_falso.py`) pero el resto no: el corredor lo lanza
como proceso, lee su salida, lanza el empaquetado, verifica y renombra. Lo que se vigila es lo
que se midió en el de Trimble el 2026-10-05: **sale con 0 y dice «Success» en todos los
casos**, así que el corredor tiene que mirar los archivos.

Y la regla 5 de `AGENTS.md`: el original, con su `sha256` y su `mtime` intactos en cada camino
de fallo y no solo en el feliz.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry
from apps.formats.tests.constructor import trimble_minimo
from apps.gnss import motores
from apps.jobs import runner
from apps.jobs.models import ENCOLADO, ERROR, HECHO, ConversionJob, JobEvent

pytestmark = pytest.mark.django_db(transaction=True)

GUION = Path(__file__).with_name("convertidor_falso.py")


@pytest.fixture(autouse=True)
def entorno(tmp_path, settings, monkeypatch):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.WINEPREFIX = ""
    monkeypatch.setattr(motores, "_bajo_wine", lambda: False)

    if os.name == "nt":
        lanzador = tmp_path / "convertToRinex.bat"
        lanzador.write_text(f'@"{sys.executable}" "{GUION}" %*\r\n')
    else:
        lanzador = tmp_path / "convertToRinex"
        lanzador.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{GUION}" "$@"\n')
        lanzador.chmod(0o755)
    settings.TRIMBLE_RINEX = str(lanzador)

    # Otras pruebas vacían el registro; este motor se declara solo en `ready()`.
    registry.registrar(motores.MotorTrimbleARinex())


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def crudo(tmp_path) -> Path:
    ruta = tmp_path / "GMLA202301311700A.T02"
    ruta.write_bytes(trimble_minimo())
    return ruta


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _trabajo(usuario, crudo: Path, **opciones) -> ConversionJob:
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(crudo),
        source_name=crudo.name,
        target_format_code="rinex",
        output_path=str(crudo.with_name(f"{crudo.stem}_rinex.zip")),
        options=opciones,
        status=ENCOLADO,
    )


def _correr(job: ConversionJob) -> ConversionJob:
    assert runner.reclamar(job.pk)
    job.refresh_from_db()
    runner.ejecutar(job)
    job.refresh_from_db()
    return job


def _sin_restos(tmp_path: Path) -> None:
    assert not list(tmp_path.glob("*.parcial*")), "quedó un parcial junto al destino"
    trabajo = tmp_path / "trabajo"
    if trabajo.exists():
        assert not any(trabajo.rglob("*")), "quedó algo en la carpeta de trabajo"


class TestElCaminoFeliz:
    def test_convierte_y_entrega_un_zip(self, usuario, crudo, tmp_path):
        antes = _huella(crudo)
        job = _correr(_trabajo(usuario, crudo))

        assert job.status == HECHO, job.reason_detail
        salida = Path(job.output_path)
        assert salida.name == "GMLA202301311700A_rinex.zip"
        with zipfile.ZipFile(salida) as z:
            assert sorted(z.namelist()) == [
                "GMLA202301311700A.23mix",
                "GMLA202301311700A.23o",
            ]
        assert job.engine_id == "trimble-rinex"
        assert _huella(crudo) == antes
        _sin_restos(tmp_path)

    def test_el_recibo_dice_lo_que_se_comprobo(self, usuario, crudo):
        job = _correr(_trabajo(usuario, crudo))
        d = job.verification
        assert d["epocas"] == 10
        assert d["version"] == "3.04"
        assert d["receptor"] == "TRIMBLE NETR9"
        assert d["bloques_del_crudo"] == 1
        assert d["avisos"] == []

    def test_no_dice_nada_del_sistema_de_referencia(self, usuario, crudo):
        """Una observación GNSS no es una coordenada: el aviso de «la salida tampoco lo tendrá»
        habría sido una mentira."""
        job = _correr(_trabajo(usuario, crudo))
        mensajes = " ".join(e.message for e in JobEvent.objects.filter(job=job))
        assert "sistema de referencia" not in mensajes

    def test_pasa_la_version_y_el_marcador_al_convertidor(self, usuario, crudo):
        job = _correr(_trabajo(usuario, crudo, version="3.05", marcador="PUNTO7"))
        assert job.status == HECHO, job.reason_detail
        assert job.verification["version"] == "3.05"
        assert job.verification["marcador"] == "PUNTO7"

    def test_la_bitacora_guarda_el_argv_para_diagnosticar(self, usuario, crudo):
        job = _correr(_trabajo(usuario, crudo))
        lanzado = JobEvent.objects.filter(job=job, message__contains="Lanzando").first()
        assert lanzado is not None
        assert "-mx" in lanzado.payload["argv"]
        assert "-p" in lanzado.payload["argv"]


@pytest.mark.parametrize(
    ("modo", "codigo"),
    [
        ("nada", "error-del-motor"),
        ("no_rinex", "rinex-invalido"),
        ("sin_epocas", "rinex-sin-epocas"),
        ("truncado", "rinex-invalido"),
        ("version_mala", "rinex-invalido"),
    ],
)
class TestElConvertidorDiceExitoYNoLoEs:
    """**Todos salen con código 0 y escriben «Success».** Lo que cambia es lo que hay en la
    carpeta, y es lo único que el corredor puede creer."""

    def test_falla_con_su_motivo(self, usuario, crudo, tmp_path, monkeypatch, modo, codigo):
        monkeypatch.setenv("CONVERTIDOR_FALSO", modo)
        job = _correr(_trabajo(usuario, crudo))
        assert job.status == ERROR
        assert job.reason_code == codigo

    def test_no_entrega_nada(self, usuario, crudo, tmp_path, monkeypatch, modo, codigo):
        monkeypatch.setenv("CONVERTIDOR_FALSO", modo)
        job = _correr(_trabajo(usuario, crudo))
        assert not Path(job.output_path).exists()
        _sin_restos(tmp_path)

    def test_y_el_original_sigue_exactamente_igual(
        self, usuario, crudo, tmp_path, monkeypatch, modo, codigo
    ):
        antes = _huella(crudo)
        monkeypatch.setenv("CONVERTIDOR_FALSO", modo)
        _correr(_trabajo(usuario, crudo))
        assert _huella(crudo) == antes


class TestLoQueSoloAvisa:
    def test_un_hueco_entrega_y_deja_el_aviso_en_la_bitacora(
        self, usuario, crudo, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("CONVERTIDOR_FALSO", "hueco")
        job = _correr(_trabajo(usuario, crudo))
        assert job.status == HECHO, job.reason_detail
        assert Path(job.output_path).exists()
        avisos = JobEvent.objects.filter(job=job, level=JobEvent.AVISO)
        assert any("Faltan 2 épocas" in e.message for e in avisos)

    def test_sin_navegacion_entrega_y_avisa(self, usuario, crudo, monkeypatch):
        monkeypatch.setenv("CONVERTIDOR_FALSO", "sin_navegacion")
        job = _correr(_trabajo(usuario, crudo))
        assert job.status == HECHO
        assert any("navegación" in a for a in job.verification["avisos"])


class TestUnCrudoCortado:
    """El convertidor de Trimble no se queja de un T02 partido por la mitad: entrega un RINEX
    válido que dura la mitad. Se para antes, y ni siquiera se lanza."""

    @pytest.fixture
    def cortado(self, tmp_path) -> Path:
        entero = trimble_minimo()
        ruta = tmp_path / "CORTADO.T02"
        ruta.write_bytes(entero[: len(entero) - 12])
        return ruta

    def test_se_para_con_su_motivo(self, usuario, cortado):
        job = _correr(_trabajo(usuario, cortado))
        assert job.status == ERROR
        assert job.reason_code == "crudo-incompleto"
        assert "cortado" in job.reason_detail

    def test_el_convertidor_ni_se_lanza(self, usuario, cortado, tmp_path):
        job = _correr(_trabajo(usuario, cortado))
        assert not JobEvent.objects.filter(job=job, message__contains="Lanzando").exists()
        _sin_restos(tmp_path)

    def test_y_el_original_no_se_toca(self, usuario, cortado):
        antes = _huella(cortado)
        _correr(_trabajo(usuario, cortado))
        assert _huella(cortado) == antes

    def test_un_crudo_entero_pasa(self, usuario, crudo):
        assert _correr(_trabajo(usuario, crudo)).status == HECHO


class TestSinElConvertidor:
    def test_no_hay_convertidor(self, usuario, crudo, tmp_path, settings, monkeypatch):
        from apps.engines import sondas

        settings.TRIMBLE_RINEX = ""
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: "")
        antes = _huella(crudo)
        job = _correr(_trabajo(usuario, crudo))
        assert job.status == ERROR
        assert job.reason_code == "sin-conversor-trimble"
        assert _huella(crudo) == antes

    def test_la_matriz_lo_pinta_apagado_con_su_motivo(self, monkeypatch):
        """Regla 4: una capacidad ausente se muestra apagada, con motivo y sin esconderse."""
        from apps.engines import sondas
        from apps.engines.base import ParDeFormatos

        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: "")
        celda = registry.celda(ParDeFormatos("trimble_t0x", "rinex"))
        assert not celda.se_puede
        assert celda.codigo_motivo == "sin-conversor-trimble"
