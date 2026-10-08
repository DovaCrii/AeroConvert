"""El sello de tiempo de una firma digital (P14, F14.5).

La autoridad es la de prueba de pyHanko (`DummyTimeStamper`), con un certificado hecho aquí. El
**oráculo es otro lector**: se saca el CMS del `/Contents` del PDF con una expresión regular, se
abre con `asn1crypto` y se comprueba con `hashlib` que el sello (RFC 3161) certifica justo **esta**
firma: la huella que trae el sello es el SHA-256 del valor de la firma. pyHanko, que escribió el
archivo, no participa de esa comprobación.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from pathlib import Path

import pytest
from asn1crypto import cms, keys, tsp
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from apps.documents import firma_digital
from apps.documents.composicion import ComposicionInvalida
from apps.documents.test_firma_digital import CLAVE, _p12, _pdf, _sha


def _autoridad():
    from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper

    privada = rsa.generate_private_key(65537, 2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TSA de prueba")])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(days=1))
        .not_valid_after(ahora + datetime.timedelta(days=30))
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(privada, hashes.SHA256())
    )
    return DummyTimeStamper(
        tsa_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        tsa_key=keys.PrivateKeyInfo.load(
            privada.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        ),
    )


def _cms_de(pdf: bytes) -> cms.ContentInfo:
    """El CMS de la última firma, leído a mano del `/Contents` (sin pyHanko)."""
    (*_, hexa) = re.findall(rb"/Contents\s*<([0-9A-Fa-f]+)>", pdf)
    crudo = bytes.fromhex(hexa.decode()).rstrip(b"\x00")
    return cms.ContentInfo.load(crudo)


def _sello(info: cms.ContentInfo):
    firmante = info["content"]["signer_infos"][0]
    sin_firmar = firmante["unsigned_attrs"]
    if not sin_firmar or sin_firmar.native is None:
        return firmante, None
    for atributo in sin_firmar:
        if atributo["type"].native == "signature_time_stamp_token":
            return firmante, atributo["values"][0]
    return firmante, None


class TestElSello:
    def test_el_sello_certifica_justo_esta_firma(self, tmp_path):
        p12, _ = _p12()
        hecha = firma_digital.firmar(
            _pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE, sellador=_autoridad()
        )
        assert hecha.sellada
        firmante, token = _sello(_cms_de((tmp_path / "f.pdf").read_bytes()))
        assert token is not None, "la firma no trae sello de tiempo"
        tst = token["content"]["encap_content_info"]["content"].parsed
        assert isinstance(tst, tsp.TSTInfo)
        huella = tst["message_imprint"]["hashed_message"].native
        assert huella == hashlib.sha256(firmante["signature"].native).digest()
        hora = tst["gen_time"].native
        assert abs((hora - datetime.datetime.now(datetime.UTC)).total_seconds()) < 300

    def test_la_verificacion_dice_la_hora_del_sello(self, tmp_path):
        p12, _ = _p12()
        firma_digital.firmar(
            _pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE, sellador=_autoridad()
        )
        (f,) = firma_digital.verificar(tmp_path / "f.pdf").firmas
        assert f.sello and f.integra
        texto = firma_digital.a_markdown(firma_digital.verificar(tmp_path / "f.pdf"), "f.pdf")
        assert "Sello de tiempo" in texto and "no se comprobó si esa autoridad" in texto

    def test_sin_autoridad_configurada_no_hay_sello(self, tmp_path, monkeypatch):
        monkeypatch.delenv(firma_digital.VARIABLE_TSA, raising=False)
        p12, _ = _p12()
        hecha = firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert not hecha.sellada
        assert _sello(_cms_de((tmp_path / "f.pdf").read_bytes()))[1] is None
        assert not firma_digital.verificar(tmp_path / "f.pdf").firmas[0].sello


class TestLaAutoridadConfigurada:
    def test_se_usa_la_de_la_variable(self, tmp_path, monkeypatch):
        import pyhanko.sign.timestamps as ts

        pedidas = []
        autoridad = _autoridad()

        def falsa(url, timeout=None):
            pedidas.append((url, timeout))
            return autoridad

        monkeypatch.setattr(ts, "HTTPTimeStamper", falsa)
        monkeypatch.setenv(firma_digital.VARIABLE_TSA, "https://tsa.ejemplo.test/sello")
        p12, _ = _p12()
        hecha = firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert hecha.sellada and pedidas == [("https://tsa.ejemplo.test/sello", 20)]

    def test_una_direccion_que_no_es_http_se_rechaza(self, tmp_path, monkeypatch):
        monkeypatch.setenv(firma_digital.VARIABLE_TSA, "file:///etc/passwd")
        p12, _ = _p12()
        with pytest.raises(ComposicionInvalida, match="no es una dirección"):
            firma_digital.firmar(_pdf(tmp_path / "a.pdf"), tmp_path / "f.pdf", p12, CLAVE)
        assert not (tmp_path / "f.pdf").exists()

    def test_si_la_autoridad_no_responde_no_se_firma_y_el_original_queda(self, tmp_path):
        class Caida:
            def __getattr__(self, nombre):
                raise ConnectionError("sin respuesta")

        p12, _ = _p12()
        original = _pdf(tmp_path / "a.pdf")
        huella = (_sha(original), original.stat().st_mtime_ns)
        with pytest.raises(ComposicionInvalida, match="no se firma sin el sello"):
            firma_digital.firmar(original, tmp_path / "f.pdf", p12, CLAVE, sellador=Caida())
        assert not (tmp_path / "f.pdf").exists()
        assert (_sha(original), original.stat().st_mtime_ns) == huella


def test_la_variable_esta_documentada():
    raiz = Path(__file__).resolve().parents[2]
    assert "AEROCONVERT_TSA_URL=" in (raiz / ".env.example").read_text(encoding="utf-8")
