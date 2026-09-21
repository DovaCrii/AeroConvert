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

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.tino import fuera, saber

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


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
        settings.TINO_CLAVE = "x" * 20
        settings.TINO_PROVEEDOR = ""
        assert not fuera.sondar()

    def test_el_proveedor_no_viene_decidido_en_el_codigo(self):
        """**A quién se le manda la pregunta de alguien es una decisión sobre los datos de
        la oficina**, no un ajuste técnico. El módulo define la forma de la llamada; el
        destinatario lo pone quien responde por esos datos."""
        from django.conf import settings as reales

        assert reales.TINO_PROVEEDOR == ""
        assert reales.TINO_CLAVE == ""


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
