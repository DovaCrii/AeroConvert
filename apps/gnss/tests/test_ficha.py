"""La ficha de un crudo de Trimble, vista desde el navegador.

Sin esto, el motor existía y **no se podía usar**: la ficha solo ofrece destinos de los perfiles
que declaran la familia del archivo, y ninguno declaraba GNSS. Lo que se vigila aquí es el
recorrido de quien suelta un T02 — qué ve, qué se le ofrece, y qué no se le pregunta.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import registry, sondas
from apps.engines.base import Disponibilidad
from apps.formats.tests.constructor import trimble_minimo
from apps.gnss import motores
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    registry.registrar(motores.MotorTrimbleARinex())
    return client


@pytest.fixture
def crudo(tmp_path):
    ruta = tmp_path / "GMLA202301311700A.T02"
    ruta.write_bytes(trimble_minimo())
    return ruta


@pytest.fixture
def con_convertidor(monkeypatch):
    monkeypatch.setattr(
        sondas, "sondar_trimble_rinex", lambda: Disponibilidad.si("Trimble de mentira")
    )


@pytest.fixture
def sin_convertidor(monkeypatch):
    monkeypatch.setattr(
        sondas,
        "sondar_trimble_rinex",
        lambda: Disponibilidad.no(
            "sin-conversor-trimble",
            "No hay convertidor de Trimble configurado.",
            sugerencia="Lo trae Trimble Business Center.",
        ),
    )


def _ficha(sesion, ruta) -> str:
    respuesta = sesion.get(reverse("dashboard:inspeccionar"), {"ruta": str(ruta)})
    assert respuesta.status_code == 200
    return respuesta.content.decode()


class TestLoQueSeVe:
    def test_dice_de_que_receptor_viene(self, sesion, crudo, con_convertidor):
        cuerpo = _ficha(sesion, crudo)
        assert "TRIMBLE NETR9" in cuerpo
        assert "5303K49763" in cuerpo
        assert "/Internal/VUELOS/2023/01/31" in cuerpo

    def test_ofrece_rinex_como_destino(self, sesion, crudo, con_convertidor):
        cuerpo = _ficha(sesion, crudo)
        assert "Posproceso GNSS" in cuerpo
        assert "RINEX" in cuerpo

    def test_y_el_boton_no_sale_apagado(self, sesion, crudo, con_convertidor):
        cuerpo = _ficha(sesion, crudo)
        boton = cuerpo[cuerpo.index('value="posproceso"') :].split(">", 1)[0]
        assert "disabled" not in boton

    def test_dice_que_el_crudo_no_abre_en_posproceso(self, sesion, crudo, con_convertidor):
        """El veredicto de siempre, con su motivo: el T02 es cerrado y el posproceso quiere
        RINEX. Es lo que convierte la herramienta en una respuesta y no en un botón."""
        cuerpo = _ficha(sesion, crudo)
        assert "no abre" in cuerpo.lower()
        assert "Convertir a RINEX" in cuerpo

    def test_no_hay_nada_de_sistema_de_referencia(self, sesion, crudo, con_convertidor):
        """No hay CRS que echar en falta: son observaciones a satélites, no coordenadas. La
        tarjeta de «¿en qué sistema están estas coordenadas?» sería una pregunta absurda."""
        cuerpo = _ficha(sesion, crudo)
        assert "Sistema de referencia" not in cuerpo
        assert "id_crs_declarado" not in cuerpo
        assert "crs_local" not in cuerpo

    def test_no_se_ofrecen_los_programas_de_cad_ni_de_sig(self, sesion, crudo, con_convertidor):
        """Civil 3D, QGIS y compañía no tienen nada que decir de un crudo GNSS."""
        cuerpo = _ficha(sesion, crudo)
        for programa in ("Civil 3D", "ArcGIS", "Google Earth", "Visor web"):
            assert programa not in cuerpo, programa


class TestSinElConvertidor:
    def test_dice_por_que_no_se_puede_y_lo_dice_a_la_vista(self, sesion, crudo, sin_convertidor):
        """Regla 4: una capacidad ausente no se esconde, y se dice **con su motivo**. Ni en un
        `title` que solo se lee con el ratón, ni mandando a otra pantalla sin decir nada."""
        cuerpo = _ficha(sesion, crudo)
        assert "Posproceso GNSS" in cuerpo
        assert "No hay convertidor de Trimble configurado" in cuerpo
        assert 'title="No hay convertidor' not in cuerpo

    def test_y_no_ofrece_un_boton_que_no_lleva_a_nada(self, sesion, crudo, sin_convertidor):
        cuerpo = _ficha(sesion, crudo)
        assert 'name="perfil" value="posproceso"' not in cuerpo

    def test_sigue_enseñando_lo_que_es(self, sesion, crudo, sin_convertidor):
        """Que falte el convertidor no borra lo que se sabe del archivo."""
        assert "TRIMBLE NETR9" in _ficha(sesion, crudo)


class TestSeEncuentra:
    """Que el buscador del catálogo lleve a esto, con las palabras de quien tiene el archivo."""

    @pytest.mark.parametrize("escrito", ["t02", "t04", "rinex", "gnss", "trimble", "ppp"])
    def test_por_lo_que_se_escribe(self, escrito):
        from apps.dashboard import acciones

        nombres = [a.nombre for a in acciones.buscar(escrito)]
        assert "Datos de un receptor GNSS a RINEX" in nombres, escrito

    def test_va_en_su_propia_categoria_y_no_entre_los_planos(self):
        from apps.dashboard import acciones

        grupos = {g["clave"]: g for g in acciones.por_categoria()}
        assert "gnss" in grupos
        assert [a.nombre for a in grupos["gnss"]["acciones"]] == [
            "Datos de un receptor GNSS a RINEX"
        ]
        assert "GNSS" not in " ".join(a.nombre for a in grupos["planos"]["acciones"])

    def test_la_tarjeta_lleva_la_eleccion_puesta(self):
        """El defecto que ya tuvo el catálogo: tirar la elección y dejar en la pantalla genérica."""
        from apps.dashboard import acciones

        (tarjeta,) = [a for a in acciones.todas() if a.id == "perfil-posproceso"]
        assert tarjeta.enlace.endswith("?destino=posproceso")

    def test_dice_que_sale_rinex(self):
        from apps.dashboard import acciones

        (tarjeta,) = [a for a in acciones.todas() if a.id == "perfil-posproceso"]
        assert tarjeta.sale == "RINEX"

    def test_pasar_t02_a_rinex_se_contesta_como_un_par(self):
        """«¿Puedo pasar un t02 a rinex?» es una pregunta con respuesta exacta."""
        from apps.dashboard import acciones

        respuesta = acciones.conversion_pedida("t02 a rinex")
        assert respuesta is not None
        assert (respuesta.origen, respuesta.destino) == ("trimble_t0x", "rinex")


class TestEncolar:
    def test_se_encola_hacia_rinex_sin_pedir_sistema_de_referencia(
        self, sesion, crudo, con_convertidor
    ):
        respuesta = sesion.post(
            reverse("dashboard:encolar"), {"ruta": str(crudo), "perfil": "posproceso"}
        )
        assert respuesta.status_code == 302, respuesta.content.decode()[:400]

        job = ConversionJob.objects.get()
        assert job.target_format_code == "rinex"
        assert job.source_format_code == "trimble_t0x"
        assert job.output_path.endswith("GMLA202301311700A_posproceso.zip")
        assert job.options["version"] == "3.04"

    def test_a_mano_con_otra_version(self, sesion, crudo, con_convertidor):
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(crudo), "formato": "rinex", "version": "2.11"},
        )
        job = ConversionJob.objects.get()
        assert job.options.get("version") == "2.11"


class TestElRecibo:
    def test_enseña_lo_que_se_comprobo(self, sesion):
        job = ConversionJob.objects.create(
            owner=get_user_model().objects.get(username="topografo"),
            source_path="/x/GMLA.T02",
            source_name="GMLA.T02",
            source_format_code="trimble_t0x",
            target_format_code="rinex",
            status="done",
            output_path="/x/GMLA_rinex.zip",
            verification={
                "version": "3.04",
                "marcador": "GMLA",
                "receptor": "TRIMBLE NETR9",
                "antena": "TRM57971.00 NONE",
                "intervalo_s": 1.0,
                "epocas": 3600,
                "esperadas": 3600,
                "primera": "2023-01-31 17:00:00",
                "ultima": "2023-01-31 17:59:59",
                "duracion_s": 3599.0,
                "constelaciones": "E G R",
                "satelites_maximos": 21,
                "huecos": 2,
                "archivos": [
                    {"nombre": "GMLA.23o", "bytes": 9284918, "tipo": "O"},
                    {"nombre": "GMLA.23mix", "bytes": 88881, "tipo": "N"},
                ],
                "bloques_del_crudo": 54,
                "avisos": ["Faltan 3 épocas en 2 hueco(s). Puede ser del receptor."],
            },
        )
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": job.pk})).content.decode()
        assert "3600" in cuerpo or "3.600" in cuerpo
        assert "17:00:00" in cuerpo and "17:59:59" in cuerpo
        assert "TRIMBLE NETR9" in cuerpo
        assert "GMLA.23o" in cuerpo and "GMLA.23mix" in cuerpo
        assert "Faltan 3 épocas" in cuerpo, (
            "los avisos se leen en el recibo, no solo en la bitácora"
        )
        assert "E G R" in cuerpo
