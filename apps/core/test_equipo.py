"""Lo que cambia cuando la aplicación deja de ser de una persona.

Las tres cosas que se arreglan aquí son de las que **no dan un error**: el bloqueo que deja
fuera a todo el equipo, la chapa que promete algo falso, y un tope de ruta que en Linux
rechaza carpetas legítimas. Ninguna se nota probando en una sola máquina, que es justo por
lo que llevaban ahí.
"""

import os

import pytest

from apps.core import ip as ip_mod
from apps.core import modo as modo_mod

pytestmark = pytest.mark.django_db


class TestDeDondeVieneLaPeticion:
    """Detrás de nginx, `REMOTE_ADDR` es siempre el proxy."""

    def test_se_lee_la_cabecera_y_no_el_proxy(self, rf):
        peticion = rf.get("/", HTTP_X_FORWARDED_FOR="10.0.0.7", REMOTE_ADDR="127.0.0.1")
        assert ip_mod.ip_del_cliente(peticion) == "10.0.0.7"

    def test_sin_cabecera_se_cae_a_remote_addr(self, rf):
        peticion = rf.get("/", REMOTE_ADDR="10.0.0.9")
        assert ip_mod.ip_del_cliente(peticion) == "10.0.0.9"

    def test_de_una_lista_se_toma_la_ultima(self, rf):
        """La última es la que observó el proxy más cercano; la primera es la que pudo
        inventarse quien llamó. Si alguien cambia nginx para que anexe en vez de
        sobrescribir, esto es lo que queda en pie."""
        peticion = rf.get("/", HTTP_X_FORWARDED_FOR="9.9.9.9, 10.0.0.7")
        assert ip_mod.ip_del_cliente(peticion) == "10.0.0.7"

    def test_una_cabecera_kilometrica_no_revienta_la_base(self, rf):
        peticion = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4" * 200)
        assert len(ip_mod.ip_del_cliente(peticion)) <= ip_mod.MAXIMO


class TestElBloqueo:
    def test_no_es_solo_por_ip(self, settings):
        """La prueba que impide volver atrás. Con `["ip_address"]` a secas y un nginx
        delante, ocho equivocaciones de cualquiera dejan fuera a las cinco personas."""
        aplanado = []
        for parametro in settings.AXES_LOCKOUT_PARAMETERS:
            aplanado.extend(parametro if isinstance(parametro, list) else [parametro])
        assert "username" in aplanado

    def test_y_tampoco_solo_por_usuario(self, settings):
        """Solo por usuario dejaría que cualquiera bloquee a otro fallando ocho veces con
        su nombre."""
        aplanado = []
        for parametro in settings.AXES_LOCKOUT_PARAMETERS:
            aplanado.extend(parametro if isinstance(parametro, list) else [parametro])
        assert "ip_address" in aplanado

    def test_la_ip_la_da_nuestra_funcion(self, settings):
        """`AXES_IPWARE_*` no haría nada: axes solo los mira si `django-ipware` está
        instalado, y no lo está."""
        assert settings.AXES_CLIENT_IP_CALLABLE == "apps.core.ip.ip_del_cliente"

    def test_entrar_bien_borra_la_cuenta(self, settings):
        assert settings.AXES_RESET_ON_SUCCESS is True


class TestLaChapa:
    def test_en_una_estacion_dice_que_no_sale_nada(self, settings):
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
        chapa = modo_mod.chapa()
        assert chapa.etiqueta == "Taller"
        assert "no salen de esta máquina" in chapa.explicacion

    def test_en_una_vm_compartida_no_promete_eso(self, settings):
        """Sería mentira, y se pinta en todas las pantallas."""
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        chapa = modo_mod.chapa()
        assert chapa.etiqueta == "Equipo"
        assert "no salen de esta máquina" not in chapa.explicacion
        assert "todo el equipo" in chapa.explicacion


class TestElLargoDeLaRuta:
    def test_en_linux_no_son_255(self):
        """Una carpeta de obra de verdad pasa de 255 sin esfuerzo, y el mensaje decía
        «mueve el archivo» sobre una carpeta compartida que nadie puede mover."""
        esperado = 255 if os.name == "nt" else 4096
        assert modo_mod.LARGO_MAXIMO_DE_RUTA == esperado

    @pytest.mark.skipif(os.name == "nt", reason="el limite de Windows si son 255")
    def test_una_ruta_larga_de_obra_se_acepta(self, settings, tmp_path):
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        larga = tmp_path / ("CC 716 - BHP/" * 20) / "ortofoto.tif"
        assert len(str(larga)) > 255
        assert modo_mod.comprobar_ruta(str(larga))


class TestLasRaicesDeUnaMaquinaCompartida:
    def test_en_una_estacion_el_disco_entero_es_legitimo(self, settings, tmp_path):
        """Es tu disco y eres la única que entra: ese es el sentido del modo taller."""
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["localhost"]
        settings.RAICES_PERMITIDAS = tmp_path.anchor or "/"
        assert modo_mod.revisar_configuracion() == ()

    def test_en_una_compartida_se_avisa(self, settings, tmp_path):
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.RAICES_PERMITIDAS = tmp_path.anchor or "/"
        problemas = modo_mod.revisar_configuracion()
        assert any("volumen entero" in p for p in problemas)

    def test_y_se_avisa_si_incluye_el_propio_codigo(self, settings):
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.RAICES_PERMITIDAS = str(settings.BASE_DIR)
        problemas = modo_mod.revisar_configuracion()
        assert any("arbol de codigo" in p for p in problemas)

    def test_una_carpeta_concreta_no_se_queja(self, settings, tmp_path):
        compartida = tmp_path / "entregas"
        compartida.mkdir()
        settings.MODO = "taller"
        settings.ALLOWED_HOSTS = ["aeroconvert.jej.cl"]
        settings.RAICES_PERMITIDAS = str(compartida)
        assert modo_mod.revisar_configuracion() == ()
