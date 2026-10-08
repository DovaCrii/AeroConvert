"""El historial de las sondas (F16.6): una fila por cambio, no una por mirada."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from apps.engines import historial, registry
from apps.engines.models import RegistroDeSonda
from apps.engines.testing import MotorDeMentira

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def registro_limpio():
    registry.limpiar()
    yield
    registry.limpiar()


def _motor(**kw) -> MotorDeMentira:
    motor = MotorDeMentira("m1", **kw)
    registry.registrar(motor)
    return motor


class TestRegistrar:
    def test_la_primera_vez_deja_una_fila(self):
        _motor()
        (cambio,) = historial.registrar()
        assert cambio.antes == "" and cambio.ahora.startswith("disponible")
        assert RegistroDeSonda.objects.count() == 1

    def test_mirar_otra_vez_sin_cambios_no_escribe(self):
        _motor()
        historial.registrar()
        assert historial.registrar() == []
        assert historial.registrar() == []
        assert RegistroDeSonda.objects.count() == 1

    def test_el_dia_que_desaparecio_queda_anotado_con_su_motivo(self):
        motor = _motor()
        historial.registrar()
        motor._disponible = False
        motor._motivo = "motor-no-disponible"
        (cambio,) = historial.registrar()
        assert cambio.antes.startswith("disponible")
        assert cambio.ahora == "apagado: motor-no-disponible"
        ultima = RegistroDeSonda.objects.first()
        assert not ultima.disponible and ultima.codigo_motivo == "motor-no-disponible"

    def test_cuando_vuelve_tambien_queda(self):
        motor = _motor()
        historial.registrar()
        motor._disponible = False
        historial.registrar()
        motor._disponible = True
        (cambio,) = historial.registrar()
        assert cambio.ahora.startswith("disponible")
        assert RegistroDeSonda.objects.filter(motor="m1").count() == 3

    def test_cambiar_solo_el_motivo_tambien_es_un_cambio(self):
        motor = _motor(disponible=False, motivo="sin-driver-ecw")
        historial.registrar()
        motor._motivo = "sin-clave-ecw"
        assert len(historial.registrar()) == 1

    def test_cada_motor_lleva_su_propio_historial(self):
        _motor()
        registry.registrar(MotorDeMentira("m2", disponible=False))
        historial.registrar()
        assert set(RegistroDeSonda.objects.values_list("motor", flat=True)) == {"m1", "m2"}
        assert historial.registrar() == []

    def test_las_recientes_vienen_de_la_mas_nueva_a_la_mas_vieja(self):
        motor = _motor()
        historial.registrar()
        motor._disponible = False
        historial.registrar()
        filas = historial.recientes()
        assert [f.disponible for f in filas] == [False, True]


class TestComando:
    def test_dice_lo_que_cambio_y_luego_que_no_hay_cambios(self, capsys):
        _motor()
        call_command("registrar_sondas")
        assert "m1: (primera vez que se ve) → disponible" in capsys.readouterr().out
        call_command("registrar_sondas")
        assert "Sin cambios" in capsys.readouterr().out


class TestPantalla:
    @pytest.fixture
    def sesion(self, client):
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("engines:matriz")).status_code == 302

    def test_mirar_la_pantalla_anota_y_la_pinta(self, sesion):
        motor = _motor()
        sesion.get(reverse("engines:matriz"))
        motor._disponible = False
        motor._motivo = "motor-no-disponible"
        cuerpo = sesion.get(reverse("engines:matriz")).content.decode()
        assert "Lo que cambió en este equipo" in cuerpo
        assert "apagado: motor-no-disponible" in cuerpo
        assert RegistroDeSonda.objects.filter(motor="m1").count() == 2
