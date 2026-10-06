"""A-05 de la auditoría de seguridad del 2026-10-05: sin cuota por persona, veinte subidas de 2 GB
seguidas llenaban el disco. El tope de `TOPE_MB` es por archivo y no lo impedía."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import subidas
from apps.core.models import ArchivoSubido

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def entorno(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.TOPE_MB = 10
    settings.CUOTA_DE_SUBIDAS_MB = 3


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


def _mb(n: int, nombre="a.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(nombre, b"0" * (n * 1_048_576))


class TestLaCuota:
    def test_lo_que_cabe_se_guarda(self, ana):
        subidas.guardar(_mb(1, "a.pdf"), usuario=ana)
        subidas.guardar(_mb(2, "b.pdf"), usuario=ana)
        assert ArchivoSubido.objects.filter(owner=ana).count() == 2

    def test_lo_que_pasa_se_rechaza_antes_de_escribir_nada(self, ana, tmp_path):
        subidas.guardar(_mb(2, "a.pdf"), usuario=ana)
        with pytest.raises(ValidationError, match="máximo por persona"):
            subidas.guardar(_mb(2, "b.pdf"), usuario=ana)
        assert ArchivoSubido.objects.filter(owner=ana).count() == 1
        escritos = [p for p in (tmp_path / "media").rglob("*") if p.is_file()]
        assert len(escritos) == 1, "el rechazado no dejó nada en disco"

    def test_el_mensaje_dice_cuanto_hay_y_que_hacer(self, ana):
        subidas.guardar(_mb(2, "a.pdf"), usuario=ana)
        with pytest.raises(ValidationError) as fallo:
            subidas.guardar(_mb(2, "b.pdf"), usuario=ana)
        texto = " ".join(fallo.value.messages)
        assert "2 MB subidos" in texto and "carpeta compartida" in texto

    def test_la_cuota_es_de_cada_persona(self, ana):
        beto = get_user_model().objects.create_user("beto", password="y" * 20)  # nosec B106
        subidas.guardar(_mb(3, "a.pdf"), usuario=ana)
        subidas.guardar(_mb(3, "b.pdf"), usuario=beto)  # no le cuenta lo de Ana

    def test_borrar_una_subida_libera_cuota(self, ana):
        primera = subidas.guardar(_mb(3, "a.pdf"), usuario=ana)
        with pytest.raises(ValidationError):
            subidas.guardar(_mb(1, "b.pdf"), usuario=ana)
        primera.delete()
        subidas.guardar(_mb(1, "b.pdf"), usuario=ana)

    def test_en_cero_se_apaga(self, ana, settings):
        settings.CUOTA_DE_SUBIDAS_MB = 0
        for n in range(5):
            subidas.guardar(_mb(2, f"{n}.pdf"), usuario=ana)
        assert ArchivoSubido.objects.filter(owner=ana).count() == 5

    def test_el_tope_por_archivo_sigue_mandando(self, ana):
        with pytest.raises(ValidationError, match="MB"):
            subidas.guardar(_mb(11, "grande.pdf"), usuario=ana)
