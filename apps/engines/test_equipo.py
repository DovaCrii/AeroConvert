"""«Cómo dejar listo el equipo» (F17.3): cada motivo de «falta algo» trae su paso."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import equipo, registry
from apps.engines.testing import MotorDeMentira
from apps.jobs import motivos


def _de_equipo() -> set[str]:
    """Los motivos del catálogo que dicen «falta algo en esta máquina»."""
    return {
        c
        for c in motivos.MOTIVOS
        if c.startswith("sin-")
        or c in {"motor-no-disponible", "proj-descolocado", "formato-propietario"}
    } - {"sin-motor", "sin-salida", "sin-avance", "sin-espacio"}


class TestElCatalogo:
    def test_cada_motivo_de_falta_algo_trae_su_paso(self):
        faltan = sorted(_de_equipo() - set(equipo.PASOS))
        assert not faltan, f"Motivos sin paso en apps/engines/equipo.py: {faltan}"

    def test_no_hay_pasos_de_motivos_que_no_existen(self):
        assert set(equipo.PASOS) <= set(motivos.MOTIVOS)

    def test_cada_paso_dice_quien_y_que_hacer_en_los_dos_sitios(self):
        for codigo, paso in equipo.PASOS.items():
            assert paso.quien in {equipo.GUION, equipo.PERSONA, equipo.NADIE}, codigo
            assert paso.servidor.strip() and paso.estacion.strip(), codigo

    def test_lo_que_arregla_el_guion_lo_nombra(self):
        for codigo, paso in equipo.PASOS.items():
            if paso.quien == equipo.GUION:
                assert equipo.INSTALAR_FALTANTES in paso.servidor, codigo

    def test_los_codigos_que_arma_la_sonda_estan_en_el_catalogo(self):
        """`sondar_lectura_gdal` arma `sin-driver-{formato}`: MrSID salía apagado con un código
        que el catálogo de motivos no tenía (se vio en esta misma pantalla, 2026-10-08)."""
        from apps.raster.motores import ORIGENES_PROPIETARIOS

        for formato in ORIGENES_PROPIETARIOS:
            assert f"sin-driver-{formato}" in motivos.MOTIVOS, formato
            assert f"sin-driver-{formato}" in equipo.PASOS, formato

    def test_las_herramientas_de_documentos_se_traducen_a_su_codigo(self):
        assert equipo.codigo_de_herramienta({"exige_office": True}) == "sin-office"
        assert equipo.codigo_de_herramienta({"exige_tesseract": True}) == "sin-tesseract"
        assert equipo.codigo_de_herramienta({}) == ""


@pytest.fixture
def entrado(client, db):
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


class TestLaPantalla:
    def test_sin_sesion_redirige(self, client, db):
        respuesta = client.get(reverse("engines:equipo"))
        assert respuesta.status_code == 302 and "/entrar/" in respuesta["Location"]

    def test_lo_apagado_sale_con_su_paso_en_vivo(self, entrado):
        registry.limpiar()
        registry.registrar(MotorDeMentira("apagado", disponible=False, motivo="sin-rtklib"))
        cuerpo = entrado.get(reverse("engines:equipo")).content.decode()
        assert "sin-rtklib" in cuerpo and "apagado" in cuerpo
        assert equipo.INSTALAR_FALTANTES in cuerpo and "se arregla con un guion" in cuerpo

    def test_un_motivo_sin_paso_se_dice_y_no_se_esconde(self, entrado):
        registry.limpiar()
        registry.registrar(MotorDeMentira("raro", disponible=False, motivo="motivo-nuevo"))
        cuerpo = entrado.get(reverse("engines:equipo")).content.decode()
        assert "motivo-nuevo" in cuerpo and "sin paso escrito" in cuerpo

    def test_estan_todos_los_pasos_aunque_nada_este_apagado(self, entrado):
        registry.limpiar()
        cuerpo = entrado.get(reverse("engines:equipo")).content.decode()
        for codigo in equipo.PASOS:
            assert codigo in cuerpo

    def test_la_pantalla_de_compatibilidad_enlaza_aqui(self, entrado):
        cuerpo = entrado.get(reverse("engines:matriz")).content.decode()
        assert reverse("engines:equipo") in cuerpo
