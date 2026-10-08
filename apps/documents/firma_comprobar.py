"""Comprobar una firma PDF **sin pyHanko**: el otro lector (reglas 1 y 2 de `AGENTS.md`).

`firma_digital.py` firma y valida con pyHanko; si esa biblioteca tuviera un error al firmar, validar
con ella misma lo daría por bueno. Aquí se hace la cuenta a mano, con otras manos: se lee el
`/ByteRange` y el `/Contents` del propio archivo, se calcula el resumen con `hashlib`, se lee el
CMS con `asn1crypto` y se verifica la firma matemática con `cryptography`.

Lo que dice por cada firma:

- `resumen_cuadra`: el resumen de los bytes cubiertos es el que el CMS declara firmado;
- `firma_cuadra`: la firma sobre los atributos firmados se verifica con la clave pública del
  certificado incluido (RSA PKCS#1 v1.5 y ECDSA; otro algoritmo es `None`, **«no se pudo
  comprobar»**, y no `True`);
- `cubre_el_archivo`: el último byte cubierto es el final del archivo (nada se añadió después).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_RANGO = re.compile(rb"/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]")


@dataclass(frozen=True)
class Comprobacion:
    resumen_cuadra: bool
    firma_cuadra: bool | None
    cubre_el_archivo: bool
    algoritmo: str
    firmante: str = ""


def _contenido_cms(datos: bytes, a: int, b: int, c: int) -> bytes:
    hueco = datos[a + b : c]
    if not (hueco.startswith(b"<") and hueco.endswith(b">")):
        raise ValueError("El hueco de la firma no es una cadena hexadecimal.")
    return bytes.fromhex(hueco[1:-1].decode("ascii"))


def _verificar_matematica(informacion, certificado, atributos_dump: bytes, firma: bytes):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.x509 import load_der_x509_certificate

    clave = load_der_x509_certificate(certificado.dump()).public_key()
    resumen = {"sha256": hashes.SHA256(), "sha384": hashes.SHA384(), "sha512": hashes.SHA512()}.get(
        informacion["digest_algorithm"]["algorithm"].native
    )
    if resumen is None:
        return None
    algoritmo = informacion["signature_algorithm"].signature_algo
    try:
        if isinstance(clave, rsa.RSAPublicKey) and algoritmo == "rsassa_pkcs1v15":
            clave.verify(firma, atributos_dump, padding.PKCS1v15(), resumen)
            return True
        if isinstance(clave, ec.EllipticCurvePublicKey) and algoritmo == "ecdsa":
            clave.verify(firma, atributos_dump, ec.ECDSA(resumen))
            return True
    except InvalidSignature:
        return False
    return None


def comprobar(datos: bytes) -> list[Comprobacion]:
    """Una `Comprobacion` por cada firma del archivo, en el orden en que aparecen."""
    # pyHanko añade sus propios OID a las tablas de asn1crypto **al importarse**, y asn1crypto
    # arma su tabla inversa la primera vez que se usa: si esto corriera antes que pyHanko en el
    # mismo proceso, la firma que viniera después fallaría con «signing_certificate_v2». Importarlo
    # aquí fija el orden. No se usa para comprobar nada: eso se hace con las otras tres bibliotecas.
    import pyhanko.sign.general  # noqa: F401
    from asn1crypto import cms

    resultado = []
    for coincidencia in _RANGO.finditer(datos):
        a, b, c, d = (int(x) for x in coincidencia.groups())
        cubierto = datos[a : a + b] + datos[c : c + d]
        contenedor = cms.ContentInfo.load(_contenido_cms(datos, a, b, c), strict=False)
        firmado = contenedor["content"]
        informacion = firmado["signer_infos"][0]
        nombre = informacion["digest_algorithm"]["algorithm"].native
        resumen = hashlib.new(nombre, cubierto).digest()

        atributos = informacion["signed_attrs"]
        declarado = next(
            (x["values"][0].native for x in atributos if x["type"].native == "message_digest"),
            None,
        )
        # El resumen que los atributos firmados dicen haber visto, contra el que sale de los bytes.
        resumen_cuadra = declarado == resumen

        # Se busca el certificado del firmante por emisor y número de serie.
        sid = informacion["sid"].chosen
        certificado = next(
            (
                x.chosen
                for x in firmado["certificates"]
                if x.name == "certificate"
                and x.chosen.serial_number == sid["serial_number"].native
                and x.chosen.issuer == sid["issuer"]
            ),
            None,
        )
        firma_cuadra = None
        if certificado is not None:
            # Los atributos se firman como SET (etiqueta 0x31), no con la etiqueta implícita [0].
            firma_cuadra = _verificar_matematica(
                informacion, certificado, atributos.untag().dump(), informacion["signature"].native
            )
        quien = ""
        if certificado is not None:
            quien = str(certificado.subject.native.get("common_name", ""))
        resultado.append(
            Comprobacion(resumen_cuadra, firma_cuadra, c + d == len(datos), nombre, quien)
        )
    return resultado
