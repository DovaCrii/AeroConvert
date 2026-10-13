"""Tino, y sobre todo la puerta por la que podría salir algo de este equipo.

## Lo que más importa de este archivo

El argumento entero de AeroConvert es que un plano bajo acuerdo de confidencialidad no sale
de la máquina, y la aplicación está publicada en internet abierto. Un ayudante es justo
donde eso se rompería sin que nadie se entere: alguien pega la ruta del archivo en la
pregunta, y esa ruta dice el cliente, la obra y el nombre del proyecto.

Así que la mitad de estas pruebas no comprueban que Tino conteste bien. Comprueban que
**la puerta nace cerrada** y que, cuando se abra, salga la pregunta y nada más.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from apps.tino import fuera, saber

pytestmark = pytest.mark.django_db


@pytest.fixture
def entrada(client):
    """Alguien que ha entrado, con Tino **como viene de fábrica: apagado**."""
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


@pytest.fixture
def sesion(entrada, settings):
    """Lo mismo, con Tino encendido: es lo que ejercitan casi todas estas pruebas."""
    settings.TINO_VISIBLE = True
    return entrada


class TestApagadoYSinRastro:
    """Decidido el 2026-10-05: de momento el equipo no lo necesita, y no debe quedar ni un
    enlace que lleve a algo que ya no está. **No se borró código**; se enciende con
    `AEROCONVERT_TINO_VISIBLE=true`."""

    def test_de_fabrica_esta_apagado(self):
        from django.conf import settings as reales

        assert reales.TINO_VISIBLE is False

    def test_su_pantalla_no_existe(self, entrada):
        """404 y no «no disponible»: un aviso confirmaría que hubo algo."""
        assert entrada.get(reverse("tino:preguntar")).status_code == 404

    def test_tampoco_con_una_pregunta(self, entrada):
        assert entrada.get(reverse("tino:preguntar"), {"p": "¿qué es un COG?"}).status_code == 404

    def test_ni_siquiera_a_un_fragmento_de_htmx(self, entrada):
        respuesta = entrada.get(reverse("tino:preguntar"), HTTP_HX_REQUEST="true")
        assert respuesta.status_code == 404

    def test_el_menu_no_lo_nombra(self, entrada):
        cuerpo = entrada.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Tino" not in cuerpo
        assert reverse("tino:preguntar") not in cuerpo

    def test_el_buscador_sin_resultados_no_lo_ofrece(self, entrada):
        cuerpo = entrada.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "xilofono"}
        ).content.decode()
        assert "Nada coincide" in cuerpo
        assert "Tino" not in cuerpo
        assert reverse("tino:preguntar") not in cuerpo

    def test_ninguna_pantalla_de_las_de_siempre_lo_nombra(self, entrada):
        for nombre in ("dashboard:convertir", "jobs:lista", "engines:matriz", "presets:lista"):
            cuerpo = entrada.get(reverse(nombre)).content.decode()
            assert "Tino" not in cuerpo, nombre
            assert reverse("tino:preguntar") not in cuerpo, nombre

    def test_encendido_vuelve_a_aparecer(self, entrada, settings):
        """Que se pueda volver atrás es la razón de no haber borrado nada."""
        settings.TINO_VISIBLE = True
        assert entrada.get(reverse("tino:preguntar")).status_code == 200
        cuerpo = entrada.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert reverse("tino:preguntar") in cuerpo


class TestLaPuertaNaceCerrada:
    """**Y no se abre por tener una biblioteca instalada.** Hace falta una clave, a mano."""

    def test_de_fabrica_esta_apagada(self, settings):
        settings.TINO_CLAVE = ""
        settings.TINO_PROVEEDOR = ""
        estado = fuera.sondar()
        assert not estado
        assert estado.motivo
        assert estado.sugerencia, "Un «no» sin salida es una pared"

    def test_con_clave_pero_sin_proveedor_tampoco(self, settings):
        """Medio configurado es no configurado. Lo contrario sería mandar la pregunta a un
        sitio que nadie eligió."""
        settings.TINO_VISIBLE = True
        settings.TINO_CLAVE = "x" * 20
        settings.TINO_PROVEEDOR = ""
        assert not fuera.sondar()

    def test_con_clave_pero_apagado_tampoco(self, settings):
        settings.TINO_VISIBLE = False
        settings.TINO_CLAVE = "x" * 20
        assert not fuera.sondar()

    def test_de_fabrica_no_hay_clave_y_el_proveedor_es_nvidia(self):
        """D9: el destinatario está decidido, pero **la clave no viene en el código**."""
        from django.conf import settings as reales

        assert reales.TINO_PROVEEDOR == "nvidia"
        assert reales.TINO_CLAVE == ""
        assert reales.TINO_URL == "https://integrate.api.nvidia.com/v1"

    def test_sin_clave_dice_su_codigo_estable(self, settings):
        from apps.jobs import motivos

        settings.TINO_CLAVE = ""
        assert fuera.sondar().codigo in motivos.MOTIVOS
        assert fuera.consultar("¿qué es un COG?").codigo == "sin-clave-ia"

    def test_modelo_vacio_usa_el_recomendado_y_los_de_respaldo(self, settings):
        settings.TINO_MODELO = ""
        assert fuera.modelos()[0] == fuera.MODELO_RECOMENDADO
        assert len(fuera.modelos()) == 3
        settings.TINO_MODELO = "otro/modelo"
        assert fuera.modelos()[0] == "otro/modelo"


class TestCoordenadasNoViajan:
    @pytest.mark.parametrize(
        "coordenada",
        [
            "-33.456789, -70.648312",
            "-33.4567",
            "345678.12",
            "6301234",
            "E 345678 N 6301234",
        ],
    )
    def test_no_salen(self, coordenada):
        limpia = fuera.limpiar(f"el punto {coordenada} cae fuera del huso")
        for numero in re.findall(r"-?\d[\d.]{3,}", coordenada):
            assert numero not in limpia.texto
        assert limpia.se_toco

    def test_un_epsg_o_una_cifra_corta_no_se_toca(self):
        limpia = fuera.limpiar("pasar de EPSG:32719 a EPSG:4326 con 12 bandas y 0.5 m")
        assert not limpia.se_toco


class _Falsa(BaseHTTPRequestHandler):
    """La API de NVIDIA, de mentira: registra lo que recibe y contesta lo que se le diga."""

    recibidas: list = []
    #: modelo -> (estado, cuerpo)
    guion: dict = {}
    demora_s = 0.0

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo))
        type(self).recibidas.append(
            {"ruta": self.path, "auth": self.headers.get("Authorization"), "cuerpo": cuerpo}
        )
        if type(self).demora_s:
            time.sleep(type(self).demora_s)
        estado, salida = type(self).guion.get(cuerpo["model"], (200, "Respuesta de prueba."))
        datos = json.dumps({"choices": [{"message": {"content": salida}}]}).encode()
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):  # noqa: N802
        datos = json.dumps({"data": [{"id": "b/modelo"}, {"id": "a/modelo"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *args):
        pass


CLAVE_INVENTADA = "nvapi-CLAVE-INVENTADA-solo-para-pruebas"


@pytest.fixture
def api(settings):
    _Falsa.recibidas = []
    _Falsa.guion = {}
    _Falsa.demora_s = 0.0
    servidor = HTTPServer(("127.0.0.1", 0), _Falsa)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    settings.TINO_URL = f"http://127.0.0.1:{servidor.server_port}/v1"
    settings.TINO_CLAVE = CLAVE_INVENTADA
    settings.TINO_PROVEEDOR = "nvidia"
    settings.TINO_VISIBLE = True
    settings.TINO_MODELO = ""
    yield _Falsa
    servidor.shutdown()
    servidor.server_close()


class TestLlamadaAFuera:
    """Contra un servidor local: **ninguna llamada real** en las pruebas."""

    def test_solo_llega_el_texto_limpio_con_bearer_y_modelo(self, api):
        consulta = fuera.consultar(
            r"por que falla D:\obras\minera\vuelo_norte.tif en -33.456789, -70.648312 "
            "o en 345678.12"
        )
        assert consulta.texto == "Respuesta de prueba."
        (llegada,) = api.recibidas
        assert llegada["ruta"] == "/v1/chat/completions"
        assert llegada["auth"] == f"Bearer {CLAVE_INVENTADA}"
        cuerpo = llegada["cuerpo"]
        assert cuerpo["model"] == fuera.MODELO_RECOMENDADO
        assert {"temperature", "max_tokens"} <= set(cuerpo)
        roles = [m["role"] for m in cuerpo["messages"]]
        assert roles == ["system", "user"]
        todo = json.dumps(cuerpo, ensure_ascii=False)
        for secreto in ("minera", "vuelo_norte", "obras", "33.456789", "70.648312", "345678"):
            assert secreto not in todo
        assert cuerpo["messages"][1]["content"] == consulta.enviado
        assert CLAVE_INVENTADA not in todo

    def test_404_prueba_el_modelo_de_respaldo(self, api, settings):
        settings.TINO_MODELO = "m/primero"
        settings.TINO_MODELOS_RESPALDO = "m/segundo"
        api.guion = {"m/primero": (404, "")}
        consulta = fuera.consultar("¿qué es un COG?")
        assert consulta.modelo == "m/segundo"
        assert [r["cuerpo"]["model"] for r in api.recibidas] == ["m/primero", "m/segundo"]

    @pytest.mark.parametrize("estado", [401, 429, 500, 503])
    def test_error_http_cae_al_modo_local_con_su_motivo(self, api, estado, caplog):
        api.guion = {fuera.MODELO_RECOMENDADO: (estado, "")}
        consulta = fuera.consultar("¿qué es un COG?")
        assert not consulta
        assert consulta.codigo == "ia-no-disponible"
        assert len(api.recibidas) == 1, "Un 401 o un 429 no se arregla con otro modelo"
        assert CLAVE_INVENTADA not in caplog.text

    def test_plazo_vencido(self, api, monkeypatch, caplog):
        monkeypatch.setattr(fuera, "PLAZO_S", 0.2)
        api.demora_s = 1.0
        consulta = fuera.consultar("¿qué es un COG?")
        assert consulta.codigo == "ia-no-disponible"
        assert CLAVE_INVENTADA not in caplog.text

    def test_servidor_caido(self, api, settings):
        settings.TINO_URL = "http://127.0.0.1:1/v1"
        assert fuera.consultar("¿qué es un COG?").codigo == "ia-no-disponible"

    def test_respuesta_con_otra_forma(self, api):
        api.guion = {m: (200, "") for m in fuera.modelos()}
        assert fuera.consultar("¿qué es un COG?").codigo == "ia-no-disponible"

    def test_esquema_raro_no_se_abre(self, api, settings):
        settings.TINO_URL = "file:///etc"
        assert fuera.consultar("¿qué es un COG?").codigo == "ia-no-disponible"

    def test_listar_modelos(self, api):
        assert fuera.listar_modelos() == ["a/modelo", "b/modelo"]

    def test_comando_sin_clave_dice_que_falta(self, settings):
        settings.TINO_CLAVE = ""
        salida = StringIO()
        call_command("tino_probar", stdout=salida)
        assert "Falta AEROCONVERT_TINO_CLAVE" in salida.getvalue()

    def test_comando_con_clave_no_la_imprime(self, api):
        salida = StringIO()
        call_command("tino_probar", stdout=salida)
        assert "a/modelo" in salida.getvalue()
        assert "Respuesta de" in salida.getvalue()
        assert CLAVE_INVENTADA not in salida.getvalue()


class TestPantallaConFuera:
    PREGUNTA = r"algo raro con D:\obras\vuelo.tif en -33.456789, -70.648312"

    def test_no_se_llama_con_cada_tecla(self, sesion, api):
        sesion.get(reverse("tino:preguntar"), {"p": self.PREGUNTA})
        assert api.recibidas == []

    def test_al_pulsar_se_llama_y_se_dice_que_salio(self, sesion, api):
        r = sesion.get(reverse("tino:preguntar"), {"p": self.PREGUNTA, "fuera": "1"})
        cuerpo = r.content.decode()
        assert "Respuesta de prueba." in cuerpo
        assert "Salió esto y solo esto" in cuerpo
        assert len(api.recibidas) == 1
        assert CLAVE_INVENTADA not in cuerpo

    def test_si_falla_dice_por_que_y_no_la_clave(self, sesion, api):
        api.guion = {fuera.MODELO_RECOMENDADO: (401, "")}
        cuerpo = sesion.get(
            reverse("tino:preguntar"), {"p": self.PREGUNTA, "fuera": "1"}
        ).content.decode()
        assert "ia-no-disponible" in cuerpo
        assert CLAVE_INVENTADA not in cuerpo

    def test_sin_clave_el_boton_no_existe_y_no_sale_nada(self, sesion, api, settings):
        settings.TINO_CLAVE = ""
        cuerpo = sesion.get(
            reverse("tino:preguntar"), {"p": self.PREGUNTA, "fuera": "1"}
        ).content.decode()
        assert api.recibidas == []
        assert "sin-clave-ia" in cuerpo


class TestQueSoloSalgaLaPregunta:
    """La regla que define el resto: **la pregunta escrita, y nada más**."""

    @pytest.mark.parametrize(
        "pegado",
        [
            r"D:\obras\minera-escondida\vuelo_2026.tif",
            "/home/topografo/proyectos/cliente/plano.dwg",
            r"\\servidor\entregas\acta_confidencial.pdf",
            "levantamiento_norte.las",
        ],
    )
    def test_una_ruta_pegada_en_la_pregunta_no_viaja(self, pegado):
        """Una pregunta escrita a las prisas trae pegada la ruta, y esa ruta dice el
        cliente, la obra y el nombre del proyecto — que es exactamente lo que esta
        aplicación existe para no publicar."""
        limpia = fuera.limpiar(f"por que no puedo convertir {pegado}")
        assert pegado not in limpia.texto
        assert limpia.se_toco

    def test_y_se_dice_que_se_quito(self, tmp_path):
        """Decir «se quitó algo» sin decir qué deja a alguien sin saber si su pregunta sigue
        significando lo mismo."""
        limpia = fuera.limpiar(r"no abre D:\obras\vuelo.tif")
        assert limpia.retirado
        assert "vuelo.tif" in limpia.retirado[0]

    def test_una_pregunta_normal_no_se_toca(self):
        limpia = fuera.limpiar("¿puedo pasar una ortofoto a JPEG 2000?")
        assert not limpia.se_toco
        assert "ortofoto" in limpia.texto

    def test_hay_un_tope_de_longitud(self):
        """Sin tope, alguien pega el contenido de un archivo en la caja y lo manda entero."""
        limpia = fuera.limpiar("a" * 5000)
        assert len(limpia.texto) <= fuera.TOPE_CARACTERES

    def test_el_encargo_no_lleva_datos_de_nadie(self):
        """Lo único que acompaña a la pregunta es la descripción de la aplicación, que es
        pública y está en el README."""
        assert "D:" not in fuera.ENCARGO
        assert "no lo sabes, dilo" in fuera.ENCARGO.lower()


class TestLoQueContestaSinSalirDeAqui:
    def test_un_par_de_formatos_se_contesta_con_la_matriz(self):
        """La pregunta de más valor de esta aplicación, y ya la contesta el buscador. Se
        reutiliza entera: **dos respuestas distintas a la misma pregunta sería lo peor**."""
        respuesta = saber.contestar("¿puedo pasar un tif a jp2?")
        assert respuesta is not None
        assert "matriz" in respuesta.fuente

    def test_un_formato_se_explica_con_su_nota(self):
        respuesta = saber.contestar("¿qué es un dwg?")
        assert respuesta is not None
        assert "catálogo de formatos" in respuesta.fuente
        assert respuesta.detalle

    def test_una_herramienta_se_encuentra_por_lo_que_hace(self):
        respuesta = saber.contestar("quitar la contraseña de un pdf")
        assert respuesta is not None
        assert respuesta.enlace

    def test_toda_respuesta_dice_de_donde_sale(self):
        """**No es adorno**: es lo que permite comprobar la respuesta en vez de creérsela, y
        es la diferencia entre un ayudante y un oráculo."""
        for pregunta in ("tif a jp2", "¿qué es un dwg?", "quitar la contraseña de un pdf"):
            respuesta = saber.contestar(pregunta)
            assert respuesta is not None and respuesta.fuente, pregunta


class TestQueSepaDecirQueNoSabe:
    """En una herramienta cuyo valor es decir la verdad sobre lo que se puede, una respuesta
    inventada sobre un sistema de referencia hace daño de verdad."""

    @pytest.mark.parametrize(
        "pregunta", ["", "   ", "xilofono", "¿cuándo llega el camión de la obra?"]
    )
    def test_lo_que_no_sabe_devuelve_nada(self, pregunta):
        assert saber.contestar(pregunta) is None

    def test_varias_herramientas_posibles_tampoco_es_una_respuesta(self):
        """«Puede que sea una de estas seis» no contesta nada: es el catálogo otra vez, y el
        catálogo ya está a un clic."""
        from apps.dashboard import acciones

        pregunta = "pasar esto a markdown"
        assert len([a for a in acciones.buscar(pregunta) if a.disponible]) > 1
        assert acciones.mejor(pregunta) is None
        assert saber.contestar(pregunta) is None

    def test_mencionar_un_formato_no_es_preguntar_por_el(self):
        """**Una respuesta correcta a otra pregunta es peor que un «no sé»**, porque parece
        que te han entendido. «Por qué no puedo convertir vuelo.tif» contestaba «GeoTIFF
        clásico: es el que abre en cualquier parte» — cierto, y no era lo que se preguntaba.
        """
        assert saber.contestar("me falla al abrir el vuelo tif en el equipo del cliente") is None
        # Y preguntando de verdad por él, sí contesta.
        assert saber.contestar("¿qué es un tif?") is not None

    def test_la_pantalla_lo_dice_como_respuesta_y_no_como_error(self, sesion):
        cuerpo = sesion.get(reverse("tino:preguntar"), {"p": "xilofono"}).content.decode()
        assert "no lo sé" in cuerpo.lower()
        assert "inventar" in cuerpo.lower()


class TestLaPantalla:
    def test_dice_en_pantalla_que_no_sale_nada(self, sesion, settings):
        """**Cada vez**, no en una página de condiciones que nadie abre."""
        settings.TINO_CLAVE = ""
        cuerpo = sesion.get(reverse("tino:preguntar")).content.decode()
        assert "No sale nada de este equipo" in cuerpo

    def test_y_enseña_lo_que_saldria_antes_de_que_salga(self, sesion):
        """La única forma honesta de pedir permiso es enseñar la frase exacta que viajaría.

        **La ruta sí aparece en la pantalla**, y tiene que aparecer: es la de quien pregunta,
        en su propia sesión, y hay que decirle qué se le quitó para que sepa si su pregunta
        sigue significando lo mismo. Lo que no puede llevarla es el texto que sale.
        """
        respuesta = sesion.get(
            reverse("tino:preguntar"), {"p": r"algo raro con D:\obras\vuelo.tif"}
        )
        assert "saldría esto y solo esto" in respuesta.content.decode()

        saldria = respuesta.context["saldria"]
        assert "obras" not in saldria.texto
        assert "vuelo.tif" not in saldria.texto
        assert "«el archivo»" in saldria.texto

    def test_los_tres_ejemplos_se_contestan_aqui(self):
        """Un ejemplo que no encuentra nada es peor que ninguno: enseña que no funciona. Y
        estos además demuestran el argumento entero — respuesta exacta, sin salir nada."""
        from apps.tino.views import EJEMPLOS

        for pregunta in EJEMPLOS:
            assert saber.contestar(pregunta) is not None, pregunta

    def test_se_llega_desde_la_busqueda_que_no_encontro_nada(self, sesion):
        """**Es el momento exacto en que hace falta**, y por eso está ahí y no en una barra
        flotante que persigue a la gente por la aplicación."""
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "xilofono"}
        ).content.decode()
        assert reverse("tino:preguntar") in cuerpo

    def test_hay_que_haber_entrado(self, client):
        respuesta = client.get(reverse("tino:preguntar"))
        assert respuesta.status_code == 302
