"""El nucleo: los dos modos, y la puerta por la que entra una ruta del disco."""

import pytest
from django.test import override_settings

from apps.core import checks, context_processors, middleware, modo, views


class TestRaicesPermitidas:
    # `override_settings` va como gestor de contexto y no como decorador de clase:
    # decorar la clase solo funciona sobre `SimpleTestCase`, y estas son clases de pytest.

    def test_se_separan_con_punto_y_coma(self):
        """Con `:` no se puede: en Windows aparece dentro de cada ruta (`D:\\`)."""
        with override_settings(MODO="taller", RAICES_PERMITIDAS=r"D:\obras;C:\datos"):
            assert len(modo.raices_permitidas()) == 2

    def test_una_raiz_vacia_se_ignora(self):
        with override_settings(RAICES_PERMITIDAS=r"D:\obras;;  ;C:\datos"):
            assert len(modo.raices_permitidas()) == 2

    def test_sin_configurar_no_hay_ninguna(self):
        with override_settings(RAICES_PERMITIDAS=""):
            assert modo.raices_permitidas() == ()


class TestComprobarRuta:
    def test_una_ruta_dentro_de_la_raiz_pasa(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            objetivo = tmp_path / "obra" / "orto.tif"
            assert modo.comprobar_ruta(objetivo) == objetivo.resolve()

    def test_la_propia_raiz_pasa(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            assert modo.comprobar_ruta(tmp_path) == tmp_path.resolve()

    def test_una_ruta_fuera_se_rechaza(self, tmp_path):
        permitida = tmp_path / "permitida"
        permitida.mkdir()
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(permitida)):
            with pytest.raises(modo.RutaNoPermitida) as fallo:
                modo.comprobar_ruta(tmp_path / "otra" / "secreto.tif")
        assert fallo.value.codigo == "ruta-no-permitida"

    def test_no_se_escapa_con_dos_puntos(self, tmp_path):
        """`..` es la forma clasica de salirse. `resolve()` la deshace antes de comparar."""
        permitida = tmp_path / "permitida"
        permitida.mkdir()
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(permitida)):
            with pytest.raises(modo.RutaNoPermitida):
                modo.comprobar_ruta(permitida / ".." / ".." / "windows" / "system32")

    def test_una_ruta_vacia_se_rechaza(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            with pytest.raises(modo.RutaNoPermitida):
                modo.comprobar_ruta("   ")

    def test_se_quitan_las_comillas_que_pega_el_explorador(self, tmp_path):
        """«Copiar como ruta» de Windows entrega la ruta entre comillas."""
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            objetivo = tmp_path / "orto.tif"
            assert modo.comprobar_ruta(f'"{objetivo}"') == objetivo.resolve()

    def test_una_ruta_larguisima_da_su_propio_motivo(self, tmp_path):
        """El tope **depende del sistema**, y la prueba tenía metido el de Windows.

        Con 300 caracteres fijos pasaba aquí y fallaba en Linux, donde el límite son 4096 —
        que es justo el motivo de que el tope se calcule y no sea una constante: en la VM,
        una carpeta de obra de verdad pasa de 255 sin esfuerzo.
        """
        pasada = "x" * (modo.LARGO_MAXIMO_DE_RUTA + 1)
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            with pytest.raises(modo.RutaNoPermitida) as fallo:
                modo.comprobar_ruta(str(tmp_path / pasada))
        assert fallo.value.codigo == "ruta-demasiado-larga"

    def test_sin_raices_configuradas_no_se_lee_nada(self):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=""):
            with pytest.raises(modo.RutaNoPermitida):
                modo.comprobar_ruta(r"C:\Windows")

    def test_en_modo_nube_no_se_leen_rutas_del_disco(self, tmp_path):
        with override_settings(MODO="nube", RAICES_PERMITIDAS=str(tmp_path)):
            with pytest.raises(modo.RutaNoPermitida):
                modo.comprobar_ruta(tmp_path / "x.tif")


class TestRevisarConfiguracion:
    def test_taller_sin_raices_es_un_error_de_arranque(self):
        """Tiene que notarse al arrancar, no media hora despues con alguien esperando."""
        with override_settings(MODO="taller", RAICES_PERMITIDAS=""):
            problemas = modo.revisar_configuracion()
        assert problemas
        assert "AEROCONVERT_RAICES_PERMITIDAS" in problemas[0]

    def test_manage_check_lo_reporta_como_error(self):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=""):
            errores = checks.revisar_modo(None)
        assert errores and errores[0].id == "aeroconvert.E001"

    def test_una_raiz_que_no_existe_se_avisa(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path / "no-esta")):
            problemas = modo.revisar_configuracion()
        assert any("no existe" in p for p in problemas)

    def test_nube_no_exige_raices(self):
        with override_settings(MODO="nube", RAICES_PERMITIDAS=""):
            assert modo.revisar_configuracion() == ()

    def test_taller_bien_configurado_no_se_queja(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            assert modo.revisar_configuracion() == ()


class TestChapa:
    def test_taller_dice_que_los_archivos_no_salen(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            chapa = modo.chapa()
            assert modo.es_taller() is True
            assert modo.es_nube() is False
        assert chapa.etiqueta == "Taller"
        assert "no salen" in chapa.explicacion

    def test_nube_anuncia_el_tope(self):
        with override_settings(MODO="nube", TOPE_MB=2048):
            chapa = modo.chapa()
            assert modo.es_nube() is True
            assert modo.es_taller() is False
        assert chapa.etiqueta == "Nube"
        assert "2048" in chapa.explicacion

    def test_va_en_el_contexto_de_todas_las_pantallas(self, tmp_path):
        with override_settings(MODO="taller", RAICES_PERMITIDAS=str(tmp_path)):
            contexto = context_processors.modo(None)
        assert contexto["chapa"].modo == "taller"


class TestSeguridad:
    def test_la_csp_no_admite_scripts_de_fuera(self):
        assert "script-src 'self'" in middleware.CSP
        assert "unsafe-inline" not in middleware.CSP.split("style-src")[0]

    def test_la_csp_prohibe_que_nos_metan_en_un_iframe(self):
        assert "frame-ancestors 'none'" in middleware.CSP

    def test_el_middleware_pone_las_cabeceras(self):
        class Respuesta(dict):
            def setdefault(self, clave, valor):
                return dict.setdefault(self, clave, valor)

        capa = middleware.ContentSecurityPolicyMiddleware(lambda _: Respuesta())
        respuesta = capa(None)
        assert respuesta["Content-Security-Policy"] == middleware.CSP
        assert respuesta["Referrer-Policy"] == "same-origin"

    def test_no_pisa_una_csp_ya_puesta(self):
        class Respuesta(dict):
            pass

        previa = Respuesta({"Content-Security-Policy": "default-src 'none'"})
        capa = middleware.ContentSecurityPolicyMiddleware(lambda _: previa)
        assert capa(None)["Content-Security-Policy"] == "default-src 'none'"


class TestSalud:
    def test_responde_para_que_run_ps1_sepa_cuando_abrir_el_navegador(self, rf):
        respuesta = views.salud(rf.get("/salud/"))
        assert respuesta.status_code == 200
        assert b"ok" in respuesta.content
