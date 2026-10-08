"""Firma digital PAdES y verificación (F14.5).

Se firma con **pyHanko** y se comprueba con **otro lector**: `firma_comprobar.py` calcula el
resumen con `hashlib`, lee el CMS con `asn1crypto` y verifica la firma con `cryptography`, sin
pasar por pyHanko. Un PDF alterado a propósito después de firmar tiene que salir **roto** en
los dos.
"""

from __future__ import annotations

import datetime
import hashlib
import io
from pathlib import Path

import pypdfium2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from reportlab.pdfgen import canvas

from apps.documents import firma_comprobar, firma_digital
from apps.documents.composicion import ComposicionInvalida

CLAVE = "una-clave-de-prueba"  # nosec B105


def _p12(
    nombre: str = "Ana Prueba",
    *,
    dias_desde: int = -1,
    dias_hasta: int = 30,
    curva: bool = False,
    clave: str = CLAVE,
) -> tuple[bytes, bytes]:
    """(`.p12`, certificado en PEM)."""
    privada = (
        ec.generate_private_key(ec.SECP256R1()) if curva else rsa.generate_private_key(65537, 2048)
    )
    sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(sujeto)
        .public_key(privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora + datetime.timedelta(days=dias_desde))
        .not_valid_after(ahora + datetime.timedelta(days=dias_hasta))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(privada, hashes.SHA256())
    )
    cifrado = serialization.BestAvailableEncryption(clave.encode())
    p12 = pkcs12.serialize_key_and_certificates(b"c", privada, cert, None, cifrado)
    return p12, cert.public_bytes(serialization.Encoding.PEM)


def _pdf(ruta: Path, texto: str = "Contrato de prueba") -> Path:
    memoria = io.BytesIO()
    lienzo = canvas.Canvas(memoria)
    lienzo.drawString(100, 700, texto)
    lienzo.showPage()
    lienzo.save()
    ruta.write_bytes(memoria.getvalue())
    return ruta


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class TestFirmar:
    def test_el_resultado_se_comprueba_con_otro_lector(self, tmp_path):
        p12, _ = _p12()
        hecha = firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert hecha.campo == "Firma1" and hecha.firmante == "Ana Prueba" and hecha.previas == 0
        (c,) = firma_comprobar.comprobar((tmp_path / "f.pdf").read_bytes())
        assert c.resumen_cuadra and c.firma_cuadra is True and c.cubre_el_archivo
        assert c.algoritmo == "sha256"

    def test_con_clave_de_curva_eliptica_tambien(self, tmp_path):
        p12, _ = _p12(curva=True)
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        (c,) = firma_comprobar.comprobar((tmp_path / "f.pdf").read_bytes())
        assert c.resumen_cuadra and c.firma_cuadra is True

    def test_la_firma_es_incremental_y_no_toca_lo_anterior(self, tmp_path):
        p12, _ = _p12()
        original = _pdf(tmp_path / "a.pdf")
        firma_digital.firmar(original, tmp_path / "f.pdf", p12, CLAVE)
        firmado = (tmp_path / "f.pdf").read_bytes()
        assert firmado.startswith(original.read_bytes())

    def test_el_pdf_firmado_abre_con_pdfium(self, tmp_path):
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert len(pypdfium2.PdfDocument(str(tmp_path / "f.pdf"))) == 1

    def test_una_segunda_firma_deja_valida_la_primera(self, tmp_path):
        a, _ = _p12("Ana Prueba")
        b, _ = _p12("Beto Prueba")
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "1.pdf", a, CLAVE)
        hecha = firma_digital.firmar(tmp_path / "1.pdf", tmp_path / "2.pdf", b, CLAVE)
        assert hecha.campo == "Firma2" and hecha.previas == 1
        primera, segunda = firma_comprobar.comprobar((tmp_path / "2.pdf").read_bytes())
        assert primera.resumen_cuadra and primera.firma_cuadra is True
        assert not primera.cubre_el_archivo  # la segunda se añadió después, y eso es lo normal
        assert segunda.resumen_cuadra and segunda.firma_cuadra is True and segunda.cubre_el_archivo

    def test_motivo_y_lugar_quedan_en_el_archivo(self, tmp_path):
        p12, _ = _p12()
        firma_digital.firmar(
            _pdf(tmp_path / "a.pdf"),
            tmp_path / "f.pdf",
            p12,
            CLAVE,
            motivo="Aprobación",
            lugar="Santiago",
        )
        datos = (tmp_path / "f.pdf").read_bytes()
        assert b"Aprob" in datos and b"Santiago" in datos

    def test_contrasena_equivocada_no_firma_ni_deja_archivo(self, tmp_path):
        p12, _ = _p12()
        with pytest.raises(ComposicionInvalida, match="no se abre"):
            firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, "otra")
        assert not (tmp_path / "f.pdf").exists()

    def test_un_certificado_vencido_no_firma_y_dice_la_fecha(self, tmp_path):
        p12, _ = _p12(dias_desde=-60, dias_hasta=-5)
        with pytest.raises(ComposicionInvalida, match="venció el"):
            firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)

    def test_un_certificado_aun_no_vigente_no_firma(self, tmp_path):
        p12, _ = _p12(dias_desde=5, dias_hasta=40)
        with pytest.raises(ComposicionInvalida, match="empieza a valer"):
            firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)

    def test_un_archivo_que_no_es_p12_se_rechaza(self, tmp_path):
        with pytest.raises(ComposicionInvalida, match="no se abre"):
            firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", b"nada", CLAVE)

    def test_un_pdf_cifrado_se_rechaza(self, tmp_path):
        import pikepdf

        p12, _ = _p12()
        with pikepdf.open(_pdf(tmp_path / "a.pdf")) as pdf:
            pdf.save(tmp_path / "c.pdf", encryption=pikepdf.Encryption(user="u", owner="o"))
        with pytest.raises(ComposicionInvalida):
            firma_digital.firmar(tmp_path / "c.pdf", tmp_path / "f.pdf", p12, CLAVE)
        assert not (tmp_path / "f.pdf").exists()

    def test_lo_que_no_es_pdf_se_rechaza(self, tmp_path):
        (tmp_path / "x.pdf").write_bytes(b"no soy un pdf")
        p12, _ = _p12()
        with pytest.raises(ComposicionInvalida):
            firma_digital.firmar(tmp_path / "x.pdf", tmp_path / "f.pdf", p12, CLAVE)

    def test_el_original_no_se_toca_ni_al_fallar(self, tmp_path):
        original = _pdf(tmp_path / "a.pdf")
        antes = (_sha(original), original.stat().st_mtime_ns)
        p12, _ = _p12()
        firma_digital.firmar(original, tmp_path / "f.pdf", p12, CLAVE)
        with pytest.raises(ComposicionInvalida):
            firma_digital.firmar(original, tmp_path / "g.pdf", p12, "mala")
        assert (_sha(original), original.stat().st_mtime_ns) == antes


class TestOriginalIntacto:
    """Regla 5: el original no cambia en **cada** camino de fallo, no solo en el feliz."""

    def _casos(self, tmp_path):
        import pikepdf

        p12, _ = _p12()
        bueno = _pdf(tmp_path / "bueno.pdf")
        with pikepdf.open(_pdf(tmp_path / "base.pdf")) as pdf:
            pdf.save(tmp_path / "cifrado.pdf", encryption=pikepdf.Encryption(user="u", owner="o"))
        (tmp_path / "no_es.pdf").write_bytes(b"no soy un pdf")
        return [
            ("clave", bueno, p12, "mala"),
            ("vencido", bueno, _p12(dias_desde=-9, dias_hasta=-1)[0], CLAVE),
            ("p12 roto", bueno, b"basura", CLAVE),
            ("cifrado", tmp_path / "cifrado.pdf", p12, CLAVE),
            ("no es pdf", tmp_path / "no_es.pdf", p12, CLAVE),
        ]

    def test_cada_camino_de_fallo(self, tmp_path):
        for nombre, origen, p12, clave in self._casos(tmp_path):
            antes = (_sha(origen), origen.stat().st_mtime_ns)
            destino = tmp_path / f"{nombre.replace(' ', '_')}.pdf.parcial"
            with pytest.raises(ComposicionInvalida):
                firma_digital.firmar(origen, destino, p12, clave)
            assert (_sha(origen), origen.stat().st_mtime_ns) == antes, nombre
            assert not destino.exists(), f"{nombre}: dejó una salida a medias"


class TestAlteraciones:
    """Lo que el sello existe para detectar."""

    def _firmado(self, tmp_path) -> bytes:
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        return (tmp_path / "f.pdf").read_bytes()

    def test_cambiar_un_byte_cubierto_rompe_las_dos_comprobaciones(self, tmp_path):
        datos = bytearray(self._firmado(tmp_path))
        sitio = datos.index(b"ReportLab")  # en el diccionario de información, que va sin comprimir
        datos[sitio] ^= 0x01  # una sola letra distinta
        (tmp_path / "roto.pdf").write_bytes(bytes(datos))
        (c,) = firma_comprobar.comprobar(bytes(datos))
        assert not c.resumen_cuadra
        (firma,) = firma_digital.verificar(tmp_path / "roto.pdf").firmas
        assert not firma.integra and firma.confianza == "rota"

    def test_lo_anadido_despues_se_dice_y_no_rompe_la_firma(self, tmp_path):
        datos = self._firmado(tmp_path) + b"\n%% anotacion posterior\n"
        (tmp_path / "mas.pdf").write_bytes(datos)
        (c,) = firma_comprobar.comprobar(datos)
        assert c.resumen_cuadra and c.firma_cuadra is True and not c.cubre_el_archivo

    def test_cambiar_la_firma_matematica_la_rompe_aunque_el_resumen_cuadre(self, tmp_path):
        datos = bytearray(self._firmado(tmp_path))
        inicio = datos.index(b"/Contents <") + len(b"/Contents <")
        fin = datos.index(b">", inicio)
        hexa = bytes(datos[inicio:fin]).rstrip(b"0")
        # Un dígito dentro de los últimos bytes del CMS: ahí está el valor de la firma.
        sitio = inicio + len(hexa) - 12
        datos[sitio] = ord("0") if datos[sitio] != ord("0") else ord("1")
        (c,) = firma_comprobar.comprobar(bytes(datos))
        assert c.resumen_cuadra, "los bytes del documento no se tocaron"
        assert c.firma_cuadra is False, "la firma alterada tiene que dejar de verificar"


class TestVerificar:
    def test_sin_firmas_es_un_resultado(self, tmp_path):
        informe = firma_digital.verificar(_pdf(tmp_path / "a.pdf"))
        assert informe.firmas == []
        assert "no trae ninguna firma" in firma_digital.a_markdown(informe, "a.pdf")

    def test_firma_integra_pero_emisor_sin_comprobar_si_no_hay_lista(self, tmp_path, monkeypatch):
        monkeypatch.delenv(firma_digital.VARIABLE_RAICES, raising=False)
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        informe = firma_digital.verificar(tmp_path / "f.pdf")
        (f,) = informe.firmas
        assert f.integra and f.cubre_todo and f.firmante == "Ana Prueba"
        assert f.confianza == "no comprobada" and f.vigente_al_firmar is True
        texto = firma_digital.a_markdown(informe, "f.pdf")
        assert "no tiene una lista de emisores" in texto and "íntegro" in texto

    def test_con_la_lista_del_servidor_la_confianza_se_comprueba(self, tmp_path, monkeypatch):
        p12, pem = _p12()
        (tmp_path / "raices.pem").write_bytes(pem)
        monkeypatch.setenv(firma_digital.VARIABLE_RAICES, str(tmp_path / "raices.pem"))
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        informe = firma_digital.verificar(tmp_path / "f.pdf")
        assert informe.raices == 1 and informe.firmas[0].confianza == "comprobada"

    def test_una_lista_ajena_no_da_confianza(self, tmp_path, monkeypatch):
        p12, _ = _p12("Ana")
        _, pem_ajeno = _p12("Otro emisor")
        (tmp_path / "raices.pem").write_bytes(pem_ajeno)
        monkeypatch.setenv(firma_digital.VARIABLE_RAICES, str(tmp_path / "raices.pem"))
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert firma_digital.verificar(tmp_path / "f.pdf").firmas[0].confianza == "no comprobada"

    def test_lo_anadido_despues_no_se_describe_como_sin_cambios(self, tmp_path):
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        con_mas = tmp_path / "mas.pdf"
        con_mas.write_bytes((tmp_path / "f.pdf").read_bytes() + b"\n% anotacion posterior\n")
        informe = firma_digital.verificar(con_mas)
        assert informe.firmas[0].integra and not informe.firmas[0].cubre_todo
        texto = firma_digital.a_markdown(informe, "mas.pdf")
        assert "no cambió desde que se firmó" not in texto
        assert "se añadió contenido después" in texto

    def test_una_lista_de_emisores_ilegible_se_avisa(self, tmp_path, monkeypatch):
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        monkeypatch.setenv(firma_digital.VARIABLE_RAICES, str(tmp_path / "no_existe.pem"))
        informe = firma_digital.verificar(tmp_path / "f.pdf")
        assert informe.raices == 0 and informe.aviso_raices
        texto = firma_digital.a_markdown(informe, "f.pdf")
        assert "Aviso de configuración" in texto and "no tiene una lista" not in texto

    def test_una_lista_vacia_tambien_se_avisa(self, tmp_path, monkeypatch):
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        (tmp_path / "vacia.pem").write_text("nada de certificados", encoding="utf-8")
        monkeypatch.setenv(firma_digital.VARIABLE_RAICES, str(tmp_path / "vacia.pem"))
        assert firma_digital.verificar(tmp_path / "f.pdf").aviso_raices

    def test_una_firma_rota_nunca_sale_comprobada_aunque_haya_lista(self, tmp_path, monkeypatch):
        p12, pem = _p12()
        (tmp_path / "raices.pem").write_bytes(pem)
        monkeypatch.setenv(firma_digital.VARIABLE_RAICES, str(tmp_path / "raices.pem"))
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        datos = bytearray((tmp_path / "f.pdf").read_bytes())
        datos[datos.index(b"ReportLab")] ^= 0x01
        (tmp_path / "roto.pdf").write_bytes(bytes(datos))
        assert firma_digital.verificar(tmp_path / "roto.pdf").firmas[0].confianza == "rota"

    def test_dos_firmas_salen_las_dos(self, tmp_path):
        a, _ = _p12("Ana Prueba")
        b, _ = _p12("Beto Prueba")
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "1.pdf", a, CLAVE)
        firma_digital.firmar(tmp_path / "1.pdf", tmp_path / "2.pdf", b, CLAVE)
        informe = firma_digital.verificar(tmp_path / "2.pdf")
        assert [f.firmante for f in informe.firmas] == ["Ana Prueba", "Beto Prueba"]
        assert all(f.integra for f in informe.firmas)
        assert not informe.firmas[0].cubre_todo and informe.firmas[1].cubre_todo

    def test_lo_que_no_es_pdf_se_rechaza(self, tmp_path):
        (tmp_path / "x.pdf").write_bytes(b"no")
        with pytest.raises(ComposicionInvalida):
            firma_digital.verificar(tmp_path / "x.pdf")

    def test_verificar_no_modifica_el_archivo(self, tmp_path):
        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        f = tmp_path / "f.pdf"
        antes = (_sha(f), f.stat().st_mtime_ns)
        firma_digital.verificar(f)
        assert (_sha(f), f.stat().st_mtime_ns) == antes


# --- Las pantallas ----------------------------------------------------------------------------


@pytest.mark.django_db
class TestPantallas:
    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        from django.contrib.auth import get_user_model

        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def _enviar(self, sesion, tmp_path, *, p12=None, clave=CLAVE, nombre="ana.p12", **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse

        pdf = _pdf(tmp_path / "contrato.pdf")
        datos = {"ruta": str(pdf), "clave": clave, **extra}
        if p12 is None:
            p12 = _p12()[0]
        datos["certificado"] = SimpleUploadedFile(nombre, p12)
        return pdf, sesion.post(reverse("documents:firmar"), datos)

    def test_sin_sesion_redirigen(self, client):
        from django.urls import reverse

        assert client.get(reverse("documents:firmar")).status_code == 302
        assert client.get(reverse("documents:verificar_firmas")).status_code == 302

    def test_se_abren(self, sesion):
        from django.urls import reverse

        pantallas = (
            ("firmar", "Firmar con certificado"),
            ("verificar_firmas", "Verificar firmas"),
        )
        for nombre, titulo in pantallas:
            respuesta = sesion.get(reverse(f"documents:{nombre}"))
            assert respuesta.status_code == 200 and titulo in respuesta.content.decode()

    def test_firmar_de_extremo_a_extremo_y_el_secreto_no_queda(self, sesion, tmp_path):
        import base64

        from apps.documents import secretos
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        p12, _ = _p12()
        pdf, respuesta = self._enviar(sesion, tmp_path, p12=p12, motivo="Aprobación")
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        trabajo = ConversionJob.objects.latest("created_at")

        # Ni la contraseña ni el certificado están en lo que se guarda del trabajo.
        guardado = repr(trabajo.options) + repr(trabajo.__dict__)
        assert CLAVE not in guardado and base64.b64encode(p12).decode()[:60] not in guardado
        assert trabajo.options.get("pide_contrasena") is True

        antes = (_sha(pdf), pdf.stat().st_mtime_ns)
        assert despachador.procesar_una_vez() == 1
        trabajo.refresh_from_db()
        assert trabajo.status == "done", trabajo.reason_detail
        assert (_sha(pdf), pdf.stat().st_mtime_ns) == antes
        assert not secretos.ruta(trabajo).exists()

        salida = Path(trabajo.output_path)
        (c,) = firma_comprobar.comprobar(salida.read_bytes())
        assert c.resumen_cuadra and c.firma_cuadra is True and c.cubre_el_archivo
        # El certificado no se escribió en ningún archivo de la carpeta de pruebas.
        assert not [f for f in tmp_path.rglob("*") if f.suffix in (".p12", ".pfx")]

    def test_centinela_ni_el_certificado_ni_la_contrasena_quedan_en_ningun_sitio(
        self, sesion, tmp_path, caplog
    ):
        """La prueba que pide el plan: se busca el certificado y la clave por todas partes."""
        import base64
        import json

        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob, JobEvent

        centinela = "centinela-" + "k9Zq-no-debe-aparecer"
        p12, _ = _p12(clave=centinela)
        with caplog.at_level("DEBUG"):
            _, respuesta = self._enviar(sesion, tmp_path, p12=p12, clave=centinela)
            assert respuesta.status_code == 302
            despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail

        agujas = [centinela.encode(), p12[:48], base64.b64encode(p12)[:64]]
        for archivo in tmp_path.rglob("*"):
            if archivo.is_file() and archivo != Path(trabajo.output_path):
                contenido = archivo.read_bytes()
                for aguja in agujas:
                    assert aguja not in contenido, f"{aguja!r} en {archivo.name}"
        filas = repr(list(ConversionJob.objects.values())) + repr(list(JobEvent.objects.values()))
        assert centinela not in filas and base64.b64encode(p12).decode()[:64] not in filas
        assert centinela not in caplog.text and centinela not in json.dumps(trabajo.options)

    def test_si_el_trabajo_falla_en_el_obrero_tampoco_queda_nada(self, sesion, tmp_path, caplog):
        import base64

        from apps.documents import secretos
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob, JobEvent

        centinela = "centinela-" + "fallo-no-debe-aparecer"
        p12, _ = _p12(clave=centinela)
        pdf, respuesta = self._enviar(sesion, tmp_path, p12=p12, clave=centinela)
        assert respuesta.status_code == 302
        pdf.write_bytes(b"ya no soy un pdf")  # lo que firmar ve cuando llega el obrero
        antes = (_sha(pdf), pdf.stat().st_mtime_ns)
        with caplog.at_level("DEBUG"):
            despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status != "done"
        assert (_sha(pdf), pdf.stat().st_mtime_ns) == antes
        assert not secretos.ruta(trabajo).exists(), (
            "el secreto tiene que borrarse también al fallar"
        )
        filas = repr(list(ConversionJob.objects.values())) + repr(list(JobEvent.objects.values()))
        for aguja in (centinela, base64.b64encode(p12).decode()[:64]):
            assert aguja not in filas and aguja not in caplog.text
        for archivo in tmp_path.rglob("*"):
            if archivo.is_file():
                assert centinela.encode() not in archivo.read_bytes(), archivo.name

    def test_contrasena_mala_se_dice_con_el_formulario_delante(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        _, respuesta = self._enviar(sesion, tmp_path, clave="clave-equivocada")
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200 and "no se abre" in cuerpo
        assert not ConversionJob.objects.exists()
        assert "clave-equivocada" not in cuerpo  # la contraseña no vuelve al formulario

    def test_certificado_vencido_se_dice_antes_de_encolar(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        vencido = _p12(dias_desde=-60, dias_hasta=-1)[0]
        _, respuesta = self._enviar(sesion, tmp_path, p12=vencido)
        assert "venció el" in respuesta.content.decode() and not ConversionJob.objects.exists()

    def test_extension_y_falta_de_certificado(self, sesion, tmp_path):
        from django.urls import reverse

        _, respuesta = self._enviar(sesion, tmp_path, nombre="ana.txt")
        assert ".p12 o .pfx" in respuesta.content.decode()
        pdf = _pdf(tmp_path / "otro.pdf")
        respuesta = sesion.post(reverse("documents:firmar"), {"ruta": str(pdf), "clave": CLAVE})
        assert "Falta el certificado" in respuesta.content.decode()

    def test_verificar_de_extremo_a_extremo(self, sesion, tmp_path):
        from django.urls import reverse

        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        p12, _ = _p12("Beto Prueba")
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        respuesta = sesion.post(
            reverse("documents:verificar_firmas"), {"ruta": str(tmp_path / "f.pdf")}
        )
        assert respuesta.status_code == 302
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        informe = Path(trabajo.output_path).read_text(encoding="utf-8")
        assert "Beto Prueba" in informe and "íntegro" in informe
        assert "no tiene una lista de emisores" in informe

    def test_una_firma_rota_se_declara_rota_en_el_informe(self, sesion, tmp_path):
        from django.urls import reverse

        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        datos = bytearray((tmp_path / "f.pdf").read_bytes())
        datos[datos.index(b"ReportLab")] ^= 0x01
        (tmp_path / "roto.pdf").write_bytes(bytes(datos))
        sesion.post(reverse("documents:verificar_firmas"), {"ruta": str(tmp_path / "roto.pdf")})
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")
        assert "ROTO" in Path(trabajo.output_path).read_text(encoding="utf-8")


class TestVerificadorDelMotor:
    def test_un_firmado_que_no_cuadra_se_rechaza(self, tmp_path):
        from apps.documents import motor

        p12, _ = _p12()
        firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert motor._verificar_firmado(tmp_path / "f.pdf", {"firmas_previas": 0}).correcta
        datos = bytearray((tmp_path / "f.pdf").read_bytes())
        datos[datos.index(b"ReportLab")] ^= 0x01
        (tmp_path / "roto.pdf").write_bytes(bytes(datos))
        assert not motor._verificar_firmado(tmp_path / "roto.pdf", {"firmas_previas": 0}).correcta

    def test_firmante_equivocado_o_original_cambiado_se_rechazan(self, tmp_path):
        from apps.documents import motor

        p12, _ = _p12("Ana Prueba")
        original = _pdf(tmp_path / "a.pdf")
        firma_digital.firmar(original, tmp_path / "f.pdf", p12, CLAVE)
        n, sha = original.stat().st_size, _sha(original)
        base = {"firmas_previas": 0, "firmante": "Ana Prueba", "bytes_original": n}
        assert motor._verificar_firmado(
            tmp_path / "f.pdf", {**base, "sha256_original": sha}
        ).correcta
        otro = motor._verificar_firmado(
            tmp_path / "f.pdf", {**base, "firmante": "Otra Persona", "sha256_original": sha}
        )
        assert not otro.correcta and "Otra Persona" in otro.motivo
        cambiado = motor._verificar_firmado(
            tmp_path / "f.pdf", {**base, "sha256_original": "0" * 64}
        )
        assert not cambiado.correcta and "no empieza por el original" in cambiado.motivo

    def test_una_firma_de_menos_se_rechaza(self, tmp_path):
        from apps.documents import motor

        _pdf(tmp_path / "sin.pdf")
        veredicto = motor._verificar_firmado(tmp_path / "sin.pdf", {"firmas_previas": 0})
        assert not veredicto.correcta

    def test_registradas(self):
        from apps.documents import motor, tarea

        assert motor.ESPECIFICACIONES["firmar"].con_secreto
        assert "firmar" in tarea.TAREAS and "verificar_firmas" in tarea.TAREAS
