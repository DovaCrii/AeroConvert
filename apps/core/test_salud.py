"""La sonda de salud.

Antes devolvía `{"estado": "ok"}` sin mirar nada, que es lo mismo que ya sabe systemd. Lo
que hace falta saber es si la base responde, si el obrero de conversiones sigue ahí, y sobre
todo **si la carpeta compartida está montada** — que es lo que va a fallar de verdad, y
cuyo síntoma hoy es «ya no hay ningún archivo en …» sobre rutas que la persona tiene delante.
"""

import json

import pytest

from apps.core import salud as salud_mod
from apps.core import views

pytestmark = pytest.mark.django_db


def _json(respuesta):
    return json.loads(respuesta.content)


class TestElContrato:
    def test_sigue_diciendo_ok(self, rf, settings, tmp_path):
        """`run.ps1` y `desplegar.sh` esperan a ver esta cadena. No se toca."""
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path)
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["estado"] == "ok", cuerpo

    def test_no_exige_entrar(self, client):
        """La consulta un monitor, no una persona."""
        assert client.get("/salud/").status_code == 200

    def test_no_filtra_rutas_ni_nombres(self, rf, settings, tmp_path):
        """Es un extremo sin autenticar: booleanos, conteos y gigabytes."""
        settings.RAICES_PERMITIDAS = str(tmp_path)
        crudo = views.salud(rf.get("/salud/")).content.decode()
        assert str(tmp_path) not in crudo
        assert str(settings.BASE_DIR) not in crudo


class TestLoQueComprueba:
    def test_la_base(self, rf):
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["base"]["ok"] is True
        assert "encolados" in cuerpo["base"]

    def test_una_raiz_que_desaparecio_se_nota(self, rf, settings, tmp_path):
        """Un montaje CIFS caído no desaparece: deja un directorio vacío en su sitio."""
        settings.RAICES_PERMITIDAS = str(tmp_path / "que-no-esta")
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["origenes"]["ok"] is False
        assert cuerpo["estado"] == "degradado"

    def test_una_raiz_que_si_esta(self, rf, settings, tmp_path):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["origenes"] == {"ok": True, "raices": 1, "legibles": 1}

    def test_el_disco(self, rf):
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["disco"]["ok"] is True
        assert cuerpo["disco"]["libre_gb"] > 0


class TestElDespachador:
    def test_sin_latido_se_da_por_caido(self, rf, settings, tmp_path):
        settings.CONVERSION_DISPATCHER_ENABLED = False
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.CARPETA_DE_TRABAJO = str(tmp_path)
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["despachador"] == {"ok": False, "motivo": "sin-latido"}

    def test_con_un_latido_reciente_esta_vivo(self, rf, settings, tmp_path):
        settings.CONVERSION_DISPATCHER_ENABLED = False
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.CARPETA_DE_TRABAJO = str(tmp_path)
        (tmp_path / salud_mod.ARCHIVO_DE_LATIDO).touch()
        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["despachador"]["ok"] is True

    def test_con_uno_viejo_no(self, rf, settings, tmp_path):
        import os

        settings.CONVERSION_DISPATCHER_ENABLED = False
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.CARPETA_DE_TRABAJO = str(tmp_path)
        latido = tmp_path / salud_mod.ARCHIVO_DE_LATIDO
        latido.touch()
        viejo = latido.stat().st_mtime - salud_mod.LATIDO_MAXIMO_S - 60
        os.utime(latido, (viejo, viejo))

        cuerpo = _json(views.salud(rf.get("/salud/")))
        assert cuerpo["despachador"]["ok"] is False
        assert cuerpo["despachador"]["ultimo_latido_s"] > salud_mod.LATIDO_MAXIMO_S

    def test_el_despachador_escribe_su_latido(self, settings, tmp_path):
        from apps.jobs import despachador

        settings.CARPETA_DE_TRABAJO = str(tmp_path)
        despachador.latir()
        assert (tmp_path / salud_mod.ARCHIVO_DE_LATIDO).exists()


class TestLosGrados:
    def test_degradado_devuelve_200_y_no_503(self, rf, settings, tmp_path):
        """Un 503 mientras el Samba aún no ha montado dejaría al guion de despliegue
        esperando para siempre: convertiría un aviso en un despliegue bloqueado."""
        settings.RAICES_PERMITIDAS = str(tmp_path / "que-no-esta")
        respuesta = views.salud(rf.get("/salud/"))
        assert respuesta.status_code == 200
        assert _json(respuesta)["estado"] == "degradado"

    def test_sin_base_si_es_503(self, rf, monkeypatch):
        """Ahí no hay aplicación que servir."""
        monkeypatch.setattr(salud_mod, "_base", lambda: {"ok": False, "motivo": "OperationalError"})
        respuesta = views.salud(rf.get("/salud/"))
        assert respuesta.status_code == 503
        assert _json(respuesta)["estado"] == "caido"


class TestLoQueNoComprueba:
    def test_no_lanza_ningun_proceso(self, rf, monkeypatch):
        """Una sonda que un monitor consulta cada diez segundos no puede forkar `gdalinfo`.
        Lo que hay instalado ya lo contesta la pantalla de compatibilidad."""
        import subprocess

        def prohibido(*_args, **_kwargs):  # pragma: no cover
            raise AssertionError("la sonda de salud lanzó un proceso")

        monkeypatch.setattr(subprocess, "run", prohibido)
        monkeypatch.setattr(subprocess, "Popen", prohibido)
        assert views.salud(rf.get("/salud/")).status_code == 200
