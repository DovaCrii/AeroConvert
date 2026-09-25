"""El catalogo de motivos.

Un codigo estable que se convierte en un typo deja de ser estable, y nadie se entera: el
mensaje sigue saliendo bien. Estas pruebas cierran esa puerta.
"""

from apps.engines import base as engines_base
from apps.formats import deteccion
from apps.jobs import motivos


class TestCatalogoCerrado:
    def test_cada_motivo_lleva_su_codigo_como_clave(self):
        for codigo, motivo in motivos.MOTIVOS.items():
            assert codigo == motivo.codigo

    def test_todos_los_codigos_van_en_kebab_case(self):
        for codigo in motivos.MOTIVOS:
            assert codigo == codigo.lower()
            assert " " not in codigo
            assert "_" not in codigo

    def test_todos_tienen_mensaje(self):
        for codigo, motivo in motivos.MOTIVOS.items():
            assert motivo.mensaje.strip(), codigo

    def test_los_reintentables_existen_en_el_catalogo(self):
        assert motivos.REINTENTABLES <= set(motivos.MOTIVOS)


class TestLosDesenlaces:
    """**Terminó bien pero sin archivo, o con algo que leer.** Otro catálogo, y cerrado igual.

    Existe porque la cola suponía que «hecho» es «hay un archivo», y tres herramientas de
    documentos contestan legítimamente con otra cosa.
    """

    def test_misma_forma_que_los_motivos(self):
        for codigo, desenlace in motivos.DESENLACES.items():
            assert codigo == desenlace.codigo
            assert codigo == codigo.lower() and " " not in codigo and "_" not in codigo
            assert desenlace.mensaje.strip(), codigo

    def test_no_se_cruzan_con_los_motivos(self):
        """Un desenlace no es un fallo. Si un código estuviera en los dos catálogos, la
        misma palabra significaría «hecho» en una pantalla y «falló» en otra."""
        assert not set(motivos.DESENLACES) & set(motivos.MOTIVOS)

    def test_estan_los_tres_que_hacen_falta(self):
        assert {"no-valio-la-pena", "sin-texto-que-sacar", "con-avisos"} <= set(motivos.DESENLACES)

    def test_ninguno_se_reintenta(self):
        """Reintentar «ya estaba comprimido» daría la misma respuesta, correcta, otra vez."""
        assert not set(motivos.DESENLACES) & motivos.REINTENTABLES


class TestLosMotivosDeDocumentos:
    def test_estan(self):
        for codigo in (
            "documento-invalido",
            "contrasena-incorrecta",
            "falta-la-contrasena",
            "demasiadas-paginas",
            "sin-office",
            "sin-access",
            "sin-tesseract",
        ):
            assert codigo in motivos.MOTIVOS, codigo

    def test_la_contrasena_perdida_no_se_reintenta(self):
        """Por diseño no se guarda. Reintentar volvería a no encontrarla."""
        assert not motivos.es_reintentable("falta-la-contrasena")


class TestVocabularioHeredado:
    """Se extiende el vocabulario que ya usa AeroBim en vez de inventar uno paralelo."""

    def test_estan_los_cuatro_motivos_de_aerobim(self):
        for codigo in (
            "sin-conversor",
            "extension-no-convertible",
            "sin-salida",
            "tardo-demasiado",
        ):
            assert codigo in motivos.MOTIVOS


class TestReintentar:
    def test_por_omision_no_se_reintenta(self):
        """Reintentar `sin-clave-ecw` tres veces es gastar el tiempo de alguien
        confirmando lo mismo."""
        assert motivos.es_reintentable("sin-clave-ecw") is False
        assert motivos.es_reintentable("crs-ausente") is False
        assert motivos.es_reintentable("par-no-soportado") is False

    def test_un_codigo_que_no_existe_tampoco_se_reintenta(self):
        assert motivos.es_reintentable("inventado-ahora-mismo") is False

    def test_lo_transitorio_si_se_reintenta(self):
        for codigo in ("origen-bloqueado", "salida-bloqueada", "interrumpido"):
            assert motivos.es_reintentable(codigo) is True


class TestCodigosUsadosEnElCodigo:
    """Todo codigo que otro modulo escriba tiene que estar en el catalogo. Es lo que evita
    que un motivo se quede sin mensaje el dia que alguien lo teclee mal."""

    def test_los_de_la_deteccion_estan(self):
        for codigo in ("origen-no-legible", "origen-bloqueado", "solo-marcador-en-la-nube"):
            assert codigo in motivos.MOTIVOS

    def test_los_de_los_motores_estan(self):
        for codigo in (
            "sin-motor",
            "motor-no-disponible",
            "sin-driver-ecw",
            "sin-clave-ecw",
            "sin-binario-ecw",
            "proj-descolocado",
            "sin-salida",
            "salida-invalida",
        ):
            assert codigo in motivos.MOTIVOS

    def test_los_del_modo_estan(self):
        for codigo in ("ruta-no-permitida", "ruta-demasiado-larga", "excede-tope"):
            assert codigo in motivos.MOTIVOS

    def test_el_estado_no_soportado_del_registro_tiene_su_motivo(self):
        assert engines_base.NO_SOPORTADO == "no-soportado"
        assert "sin-motor" in motivos.MOTIVOS

    def test_la_deteccion_declara_sus_niveles_de_confianza(self):
        assert deteccion.CONFIANZA_FIRMA in deteccion.ETIQUETAS_CONFIANZA
        assert deteccion.CONFIANZA_DESCONOCIDA in deteccion.ETIQUETAS_CONFIANZA


class TestMensaje:
    def test_devuelve_el_texto_del_catalogo(self):
        assert motivos.mensaje("sin-motor") == motivos.MOTIVOS["sin-motor"].mensaje

    def test_un_codigo_desconocido_se_devuelve_tal_cual(self):
        """Mejor mostrar el codigo crudo que una cadena vacia: al menos se puede buscar."""
        assert motivos.mensaje("no-existe") == "no-existe"
