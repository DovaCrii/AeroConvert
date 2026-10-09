"""La portada «archivo primero» (F13.8): soltar, pista por la cabecera y herramientas."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.dashboard import acciones, views
from apps.documents.herramientas import HERRAMIENTAS
from apps.formats import catalogo

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def _pista(client, nombre: str, cabecera: bytes, tamano: int = 0):
    return client.post(
        reverse("dashboard:reconocer"),
        {
            "cabecera": SimpleUploadedFile("cabecera", cabecera),
            "nombre": nombre,
            "tamano": str(tamano),
        },
    )


class TestLaPortadaEmpiezaPorElArchivo:
    def test_la_zona_de_soltar_va_antes_que_el_buscador(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert cuerpo.count("data-zona-soltar") == 1
        assert 'data-reconoce="' in cuerpo
        assert 'id="reconocido"' in cuerpo and 'id="ficha"' in cuerpo
        assert cuerpo.index("data-zona-soltar") < cuerpo.index('id="q"')

    def test_convertir_sigue_teniendo_su_zona(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
        assert cuerpo.count("data-zona-soltar") == 1


class TestLaPistaPorLaCabecera:
    def test_un_pdf_se_reconoce_y_ofrece_sus_herramientas(self, sesion):
        cuerpo = _pista(sesion, "planos.pdf", b"%PDF-1.7\n%\xe2\xe3\n", 123456).content.decode()
        assert "planos.pdf" in cuerpo
        assert "por su cabecera" in cuerpo
        assert "Unir PDF" in cuerpo and "Organizar páginas" in cuerpo
        # Un PDF no obliga a esperar al final: la cabecera basta para reconocerlo.
        assert cuerpo.count("herramienta-marca") >= 5

    def test_un_bigtiff_avisa_de_que_lo_de_dentro_se_confirma_al_subir(self, sesion):
        cabecera = b"II\x2b\x00\x08\x00\x00\x00" + b"\x00" * 64
        cuerpo = _pista(sesion, "ortofoto.tif", cabecera, 20 * 1024**3).content.decode()
        assert "BigTIFF" in cuerpo
        assert "al final del archivo" in cuerpo
        assert "GB" in cuerpo

    def test_sin_firma_se_dice_que_es_solo_por_la_extension(self, sesion):
        cuerpo = _pista(sesion, "puntos.las", b"\x00" * 64).content.decode()
        assert "solo por su extensión" in cuerpo or "por su cabecera" in cuerpo

    def test_un_archivo_desconocido_dice_que_se_mirara_entero(self, sesion):
        cuerpo = _pista(sesion, "cosa.zzz", b"\x01\x02\x03").content.decode()
        assert "entero" in cuerpo

    def test_una_cabecera_que_pasa_del_tope_no_se_lee(self, sesion):
        grande = b"%PDF-1.7\n" + b"0" * (views.CABECERA_MAX_BYTES + 1)
        cuerpo = _pista(sesion, "a.pdf", grande).content.decode()
        assert "Parece" not in cuerpo

    def test_el_nombre_no_arrastra_carpetas(self, sesion):
        cuerpo = _pista(sesion, "../../etc/pase.pdf", b"%PDF-1.7\n").content.decode()
        assert "pase.pdf" in cuerpo and "etc/" not in cuerpo

    def test_pide_sesion_y_es_solo_post(self, client, sesion):
        assert sesion.get(reverse("dashboard:reconocer")).status_code == 405
        client.logout()
        assert client.post(reverse("dashboard:reconocer"), {}).status_code == 302


class TestLasHerramientasDelArchivo:
    def test_cada_id_de_la_tabla_existe(self):
        ids = {h["id"] for h in HERRAMIENTAS}
        for extension, usadas in acciones.HERRAMIENTAS_POR_EXTENSION.items():
            assert set(usadas) <= ids, extension

    def test_los_formatos_que_leen_al_final_existen_en_el_catalogo(self):
        assert views.LEEN_AL_FINAL <= set(catalogo.FORMATOS)

    def test_un_pdf_ofrece_las_de_pdf_y_una_foto_las_de_imagen(self):
        assert "pdf-unir" in {a.id for a in acciones.para_el_archivo("x.PDF")}
        assert {a.id for a in acciones.para_el_archivo("foto.jpg")} == {
            "pdf-imagenes",
            "pdf-imagenes_lote",
            "pdf-escanear",
        }
        assert acciones.para_el_archivo("sin_extension") == []


class TestElNavegadorSoloMandaLaCabecera:
    JS = (Path(settings.BASE_DIR) / "static" / "js" / "reconocer.js").read_text(encoding="utf-8")

    def test_usa_slice_con_el_mismo_tope_que_el_servidor(self):
        assert ".slice(0, CABECERA_BYTES)" in self.JS
        tope = re.search(r"CABECERA_BYTES = ([\d* ]+);", self.JS).group(1)
        assert math.prod(int(n) for n in tope.split("*")) == views.CABECERA_MAX_BYTES

    def test_si_falla_no_enseña_error(self):
        assert ".catch(" in self.JS
