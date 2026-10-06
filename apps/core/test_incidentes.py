"""F9.6: saber si algo mejoró. Un fallo deja rastro —sin datos personales— y el uso se cuenta.

Antes un 500, un 413 o la red cortada dejaban la pantalla quieta y ningún registro: no había forma
de distinguir «nadie lo usa» de «se usa y falla».
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.signals import got_request_exception
from django.test import RequestFactory
from django.urls import reverse

from apps.core import incidentes
from apps.core.models import Incidente
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


def _trabajo(ana, estado="done", destino="rinex", origen="ubx", motivo=""):
    return ConversionJob.objects.create(
        owner=ana,
        source_path="/x/a",
        source_name="a",
        source_format_code=origen,
        target_format_code=destino,
        output_path="/x/b",
        status=estado,
        reason_code=motivo,
    )


class TestRegistrar:
    def test_no_guarda_la_consulta_ni_mas_de_lo_necesario(self, ana):
        fila = incidentes.registrar(
            "navegador", "/trabajos/abc/progreso/?q=texto+privado#x", estado=500, usuario=ana
        )
        assert fila.ruta == "/trabajos/abc/progreso/"
        assert "privado" not in fila.ruta
        assert fila.owner == ana and fila.estado == 500

    def test_un_estado_fuera_de_rango_se_descarta(self):
        assert incidentes.registrar("navegador", "/x/", estado=99999).estado is None
        assert incidentes.registrar("navegador", "/x/", estado="500").estado is None

    def test_el_detalle_y_la_ruta_se_acotan(self):
        fila = incidentes.registrar("servidor-500", "/" + "a" * 500, detalle="d" * 900)
        assert len(fila.ruta) == 200 and len(fila.detalle) == 300

    def test_un_anonimo_no_se_guarda_como_dueno(self):
        from django.contrib.auth.models import AnonymousUser

        assert incidentes.registrar("navegador", "/x/", usuario=AnonymousUser()).owner is None

    def test_pasado_el_tope_por_hora_se_descarta_y_no_revienta(self, monkeypatch):
        monkeypatch.setattr(incidentes, "TOPE_POR_HORA", 3)
        hechos = [incidentes.registrar("navegador", "/x/", estado=500) for _ in range(5)]
        assert [h is not None for h in hechos] == [True, True, True, False, False]
        assert Incidente.objects.count() == 3

    def test_si_la_base_falla_no_levanta_otra_excepcion(self, monkeypatch):
        def explota(*a, **k):
            raise RuntimeError("base caída")

        monkeypatch.setattr(Incidente.objects, "create", explota)
        assert incidentes.registrar("navegador", "/x/") is None


class TestElErrorDelServidor:
    def test_un_500_deja_una_fila_con_la_clase_y_no_el_mensaje(self, ana):
        peticion = RequestFactory().get("/dashboard/inspeccionar/?q=secreto")
        peticion.user = ana
        try:
            raise ValueError("el archivo /mnt/entregas/cliente-secreto.tif no abre")
        except ValueError:
            got_request_exception.send(sender=None, request=peticion)

        fila = Incidente.objects.get()
        assert fila.tipo == "servidor-500" and fila.estado == 500
        assert fila.detalle == "ValueError", "la clase sí, el mensaje no"
        assert "secreto" not in fila.ruta + fila.detalle
        assert fila.owner == ana


class TestElAvisoDelNavegador:
    def _enviar(self, client, cuerpo, **extra):
        return client.post(
            reverse("incidente"), data=cuerpo, content_type="application/json", **extra
        )

    def test_sin_sesion_no_se_acepta_nada(self, client):
        respuesta = self._enviar(client, json.dumps({"ruta": "/x/", "estado": 500}))
        assert respuesta.status_code == 302
        assert not Incidente.objects.exists()

    def test_con_sesion_queda_anotado_y_responde_204(self, client, ana):
        client.force_login(ana)
        respuesta = self._enviar(
            client, json.dumps({"ruta": "/trabajos/x/progreso/", "estado": 502})
        )
        assert respuesta.status_code == 204
        fila = Incidente.objects.get()
        assert (fila.tipo, fila.estado, fila.owner) == ("navegador", 502, ana)

    def test_solo_por_post(self, client, ana):
        client.force_login(ana)
        assert client.get(reverse("incidente")).status_code == 405

    @pytest.mark.parametrize(
        "cuerpo", ["no es json", "{}", '{"ruta": "/x/"}', '{"ruta":"/x/","estado":"no"}']
    )
    def test_un_informe_ilegible_es_400(self, client, ana, cuerpo):
        client.force_login(ana)
        assert self._enviar(client, cuerpo).status_code == 400
        assert not Incidente.objects.exists()

    def test_un_informe_enorme_es_400(self, client, ana):
        client.force_login(ana)
        enorme = json.dumps({"ruta": "/" + "a" * 5000, "estado": 500})
        assert self._enviar(client, enorme).status_code == 400

    def test_exige_el_token_de_csrf(self, ana):
        """La prueba normal salta el CSRF; aquí se activa para comprobar que **no** hay una
        excepción hecha a mano en esta vista."""
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(ana)
        respuesta = cliente.post(
            reverse("incidente"),
            data=json.dumps({"ruta": "/x/", "estado": 500}),
            content_type="application/json",
        )
        assert respuesta.status_code == 403


class TestElResumenDeUso:
    def test_cuenta_trabajos_exito_y_motivos(self, ana):
        _trabajo(ana, "done", "rinex", "ubx")
        _trabajo(ana, "done", "rinex", "sbf")
        _trabajo(ana, "error", "cog", "geotiff", motivo="sin-motor")
        _trabajo(ana, "error", "cog", "geotiff", motivo="sin-motor")
        _trabajo(ana, "queued", "cog", "geotiff")
        incidentes.registrar("navegador", "/trabajos/x/", estado=500)

        resumen = incidentes.resumen_de_uso(30)
        assert resumen["trabajos"] == 5
        assert resumen["tasa_de_exito"] == 50.0, "2 hechos de 4 terminados; el encolado no cuenta"
        assert resumen["personas_activas"] == 1
        assert resumen["destinos_mas_pedidos"][0] == ("cog", 3)
        assert resumen["motivos_de_fallo"] == [("sin-motor", 2)]
        assert resumen["incidentes"] == 1
        assert resumen["incidentes_por_tipo"] == {"navegador": 1}

    def test_sin_trabajos_terminados_no_inventa_una_tasa(self, ana):
        _trabajo(ana, "queued")
        assert incidentes.resumen_de_uso()["tasa_de_exito"] is None

    def test_lo_de_antes_del_periodo_no_cuenta(self, ana):
        from datetime import timedelta

        from django.utils import timezone

        viejo = _trabajo(ana, "done")
        ConversionJob.objects.filter(pk=viejo.pk).update(
            created_at=timezone.now() - timedelta(days=90)
        )
        assert incidentes.resumen_de_uso(30)["trabajos"] == 0
        assert incidentes.resumen_de_uso(120)["trabajos"] == 1

    def test_el_comando_lo_imprime(self, ana):
        _trabajo(ana, "done")
        salida = StringIO()
        call_command("resumen_de_uso", "--dias", "7", stdout=salida)
        texto = salida.getvalue()
        assert "Uso de los últimos 7 días" in texto
        assert "Tasa de éxito: 100.0 %" in texto
