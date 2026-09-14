"""La puerta única: una ruta del disco o una subida.

Sustituye a llamar a `comprobar_ruta()` por su cuenta desde nueve sitios, y lo que hay detrás
—la inspección, los motores, las herramientas de PDF— sigue recibiendo un `Path` y no se
entera de nada.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import entrada, subidas
from apps.core.models import ArchivoSubido

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106


@pytest.fixture
def medios(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "medios")
    return settings.MEDIA_ROOT


def _subir(usuario, nombre="plano.pdf", contenido=b"%PDF-1.7 finge que soy un pdf"):
    return subidas.guardar(SimpleUploadedFile(nombre, contenido), usuario=usuario)


class TestUnaRutaDelDisco:
    def test_se_resuelve_como_siempre(self, ana, settings, tmp_path):
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        archivo = tmp_path / "orto.tif"
        archivo.write_bytes(b"x")

        origen = entrada.resolver(str(archivo), usuario=ana)
        assert origen.ruta == archivo
        assert origen.nombre == "orto.tif"
        assert not origen.es_subida

    def test_una_de_fuera_se_sigue_rechazando(self, ana, settings, tmp_path):
        """Levanta la clase **padre**, que es la que ya capturan las nueve vistas: para una
        ruta, la comprobación sigue siendo exactamente la de siempre."""
        from apps.core import modo

        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        with pytest.raises(modo.RutaNoPermitida):
            entrada.resolver("C:\\Windows\\System32\\config\\SAM", usuario=ana)

    def test_y_las_vistas_que_ya_la_capturan_siguen_valiendo(self, ana):
        """El motivo de que `EntradaNoPermitida` herede: ni un `except` que tocar."""
        from apps.core import modo

        assert issubclass(entrada.EntradaNoPermitida, modo.RutaNoPermitida)

    def test_con_comillas_alrededor(self, ana, settings, tmp_path):
        """«Copiar como ruta» del Explorador las pone."""
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        archivo = tmp_path / "orto.tif"
        archivo.write_bytes(b"x")
        assert entrada.resolver(f'"{archivo}"', usuario=ana).ruta == archivo

    def test_el_token_de_una_ruta_es_la_ruta(self, ana, settings, tmp_path):
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        archivo = tmp_path / "orto.tif"
        archivo.write_bytes(b"x")
        assert entrada.resolver(str(archivo), usuario=ana).token == str(archivo)


class TestUnaSubida:
    def test_se_resuelve_a_su_archivo(self, ana, medios):
        subida = _subir(ana)
        origen = entrada.resolver(subida.token, usuario=ana)
        assert origen.es_subida
        assert origen.ruta.read_bytes().startswith(b"%PDF")

    def test_conserva_el_nombre_que_la_persona_reconoce(self, ana, medios):
        subida = _subir(ana, nombre="Plano de detalle.pdf")
        assert entrada.resolver(subida.token, usuario=ana).nombre == "Plano de detalle.pdf"

    def test_el_token_es_el_identificador_y_no_la_ruta(self, ana, medios):
        """**La línea donde equivocarse sería una fuga.** Si el formulario recibiera de vuelta
        la ruta de `MEDIA_ROOT`, el POST siguiente la usaría como si fuera una ruta del
        disco."""
        subida = _subir(ana)
        origen = entrada.resolver(subida.token, usuario=ana)
        assert origen.token == f"subida:{subida.pk}"
        assert str(origen.ruta) not in origen.token

    def test_dos_personas_pueden_subir_el_mismo_nombre(self, ana, beto, medios):
        """Una carpeta por identificador: si no, Django renombraría el segundo con un sufijo
        aleatorio y el nombre que la persona reconoce se perdería."""
        de_ana = _subir(ana, contenido=b"%PDF de ana")
        de_beto = _subir(beto, contenido=b"%PDF de beto")

        assert de_ana.nombre_original == de_beto.nombre_original == "plano.pdf"
        assert de_ana.ruta != de_beto.ruta
        assert de_ana.ruta.read_bytes() == b"%PDF de ana"
        assert de_beto.ruta.read_bytes() == b"%PDF de beto"


class TestLaSubidaEsDeSuDueno:
    def test_la_de_otra_persona_no_se_resuelve(self, ana, beto, medios):
        """La carpeta compartida la ve el equipo a propósito; subir algo del propio equipo
        es otra cosa."""
        subida = _subir(ana)
        with pytest.raises(entrada.EntradaNoPermitida):
            entrada.resolver(subida.token, usuario=beto)

    def test_y_dice_lo_mismo_que_si_no_existiera(self, ana, beto, medios):
        """Distinguir «no es tuya» de «no existe» confirmaría que un identificador ajeno es
        válido. Es el mismo criterio por el que las fichas dan 404 y no 403."""
        subida = _subir(ana)
        ajena = _mensaje(lambda: entrada.resolver(subida.token, usuario=beto))
        fantasma = _mensaje(lambda: entrada.resolver(f"subida:{uuid.uuid4()}", usuario=beto))
        assert ajena == fantasma


def _mensaje(llamada) -> str:
    try:
        llamada()
    except entrada.EntradaNoPermitida as fallo:
        return str(fallo)
    raise AssertionError("no levantó")  # pragma: no cover


class TestLoQueNoSeAdivina:
    def test_un_identificador_inventado_no_cae_a_ruta(self, ana, settings, tmp_path):
        """**Nunca se cae de vuelta a interpretarlo como ruta.** Adivinar es exactamente
        cómo una de las dos vías se cuela por la puerta de la otra."""
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        with pytest.raises(entrada.EntradaNoPermitida):
            entrada.resolver("subida:no-soy-un-uuid", usuario=ana)

    def test_ni_uno_que_parece_una_ruta(self, ana, settings, tmp_path):
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        archivo = tmp_path / "orto.tif"
        archivo.write_bytes(b"x")
        with pytest.raises(entrada.EntradaNoPermitida):
            entrada.resolver(f"subida:{archivo}", usuario=ana)

    def test_nada_es_nada(self, ana):
        with pytest.raises(entrada.EntradaNoPermitida, match="ningún archivo"):
            entrada.resolver("   ", usuario=ana)

    def test_una_subida_cuyo_archivo_se_barrio(self, ana, medios):
        subida = _subir(ana)
        subida.ruta.unlink()
        with pytest.raises(entrada.EntradaNoPermitida, match="caducó"):
            entrada.resolver(subida.token, usuario=ana)


class TestVarios:
    def test_una_linea_por_origen(self, ana, medios, settings, tmp_path):
        settings.MODO = "taller"
        settings.RAICES_PERMITIDAS = str(tmp_path)
        archivo = tmp_path / "memoria.pdf"
        archivo.write_bytes(b"%PDF")
        subida = _subir(ana)

        origenes = entrada.resolver_varios(f"{archivo}\n{subida.token}\n", usuario=ana, maximo=20)
        assert [o.nombre for o in origenes] == ["memoria.pdf", "plano.pdf"]

    def test_el_tope_cuenta_las_dos_vias_juntas(self, ana, medios):
        """Si no, alguien sube veinte y pega otras veinte."""
        tokens = "\n".join(_subir(ana, nombre=f"p{n}.pdf").token for n in range(5))
        assert len(entrada.resolver_varios(tokens, usuario=ana, maximo=3)) == 3


class TestElTope:
    def test_lo_que_pasa_del_tope_no_se_guarda(self, ana, medios, settings):
        """La tercera comprobación, la inevadible: cubre la API y el panel de
        administración, donde ni nginx ni el manejador miran."""
        settings.TOPE_MB = 1
        grande = SimpleUploadedFile("enorme.pdf", b"x" * (2 * 1_048_576))
        with pytest.raises(ValidationError, match="tope"):
            subidas.guardar(grande, usuario=ana)
        assert ArchivoSubido.objects.count() == 0

    def test_y_manda_a_la_carpeta_compartida(self, ana, medios, settings):
        """El mensaje tiene que decir qué hacer, no solo que no."""
        settings.TOPE_MB = 1
        grande = SimpleUploadedFile("enorme.pdf", b"x" * (2 * 1_048_576))
        try:
            subidas.guardar(grande, usuario=ana)
        except ValidationError as fallo:
            assert "carpeta compartida" in str(fallo)

    def test_el_manejador_corta_mientras_llega(self, settings):
        """`DATA_UPLOAD_MAX_MEMORY_SIZE` no sirve: limita los datos del formulario que **no**
        son archivos. Sin esto, un cuerpo de veinte gigabytes se escribe entero en el
        temporal del sistema antes de que nadie lo rechace."""
        from django.core.files.uploadhandler import StopUpload

        from apps.core.manejador import SubidaConTope

        settings.TOPE_MB = 1
        manejador = SubidaConTope()
        manejador.new_file("f", "grande.pdf", "application/pdf", None, None)

        with pytest.raises(StopUpload):
            for trozo in range(3):
                manejador.receive_data_chunk(b"x" * 1_048_576, trozo * 1_048_576)

    def test_esta_puesto_en_los_ajustes(self, settings):
        assert "apps.core.manejador.SubidaConTope" in settings.FILE_UPLOAD_HANDLERS


class TestElBarrido:
    def test_se_lleva_una_subida_que_nadie_uso(self, ana, medios):
        """Alguien arrastró un PDF, se lo pensó mejor y cerró la pestaña. Sin esto,
        `MEDIA_ROOT` crece y no lo vacía nadie nunca."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.jobs import retencion

        subida = _subir(ana)
        ruta = subida.ruta
        ArchivoSubido.objects.filter(pk=subida.pk).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )

        resultado = retencion.barrer()
        assert resultado.subidas_caducadas == 1
        assert not ruta.exists()
        assert ArchivoSubido.objects.count() == 0

    def test_y_deja_en_paz_a_una_reciente(self, ana, medios):
        from apps.jobs import retencion

        subida = _subir(ana)
        retencion.barrer()
        assert ArchivoSubido.objects.filter(pk=subida.pk).exists()

    def test_ni_a_una_que_ya_reclamo_un_trabajo(self, ana, medios):
        """La división es **por estado, no por tiempo**: en cuanto un trabajo la reclama se
        le quita la caducidad, y a partir de ahí la borra el barrido de entradas al terminar
        ese trabajo."""
        from apps.jobs import retencion

        subida = _subir(ana)
        ArchivoSubido.objects.filter(pk=subida.pk).update(expires_at=None)
        retencion.barrer()
        assert ArchivoSubido.objects.filter(pk=subida.pk).exists()
