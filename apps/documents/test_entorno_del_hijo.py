"""Lo que vive en el `.env` y el hijo lee de su entorno, se lo pasa el padre.

`python-decouple` lee el `.env` sin copiarlo a `os.environ`, y el servicio de `p340` no tiene
`EnvironmentFile`: la lista de emisores de confianza y la autoridad de sello, leídas por el hijo
 con `os.environ`, quedaban vacías en el servidor aunque estuvieran configuradas.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.documents import motor
from apps.documents.firma_digital import VARIABLE_RAICES, VARIABLE_TSA
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


def _trabajo(tmp_path, herramienta="verificar_firma"):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    return ConversionJob.objects.create(
        owner=get_user_model().objects.create_user("ana", password="x" * 20),  # nosec B106
        source_path=str(pdf),
        source_name="a.pdf",
        herramienta=herramienta,
        target_format_code="md",
        output_path=str(tmp_path / "a.md"),
    )


def test_el_padre_le_pasa_al_hijo_lo_que_leyo_del_env(settings, tmp_path):
    settings.RAICES_DE_CONFIANZA = "/srv/raices.pem"
    settings.TSA_URL = "https://tsa.ejemplo.test"
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "t")
    herramienta = "verificar_firmas"
    entorno = motor.plan(_trabajo(tmp_path, herramienta)).env
    assert entorno[VARIABLE_RAICES] == "/srv/raices.pem"
    assert entorno[VARIABLE_TSA] == "https://tsa.ejemplo.test"


def test_sin_configurar_no_se_pasa_nada(settings, tmp_path):
    settings.RAICES_DE_CONFIANZA = ""
    settings.TSA_URL = ""
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "t")
    herramienta = "verificar_firmas"
    entorno = motor.plan(_trabajo(tmp_path, herramienta)).env
    assert VARIABLE_RAICES not in entorno and VARIABLE_TSA not in entorno
