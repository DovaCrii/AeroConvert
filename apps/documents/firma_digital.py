"""Firma digital de un PDF (PAdES) con el certificado de la persona
y verificación de las que se reciben.

Se firma y se valida con **pyHanko** (MIT). Esta no es la firma «visible» de `firma_visible.py`
(una imagen estampada): aquí hay un **sello criptográfico** que se rompe si cambia una coma.

## La clave privada no se queda en ningún lado

El certificado `.p12` y su contraseña llegan al obrero **como un solo secreto** (ver
`secretos.py`): cifrados en la carpeta de trabajo, leídos y borrados en el mismo paso, y
entregados al hijo por una variable de entorno que no se registra. **No van en `options`, ni en
la base, ni en el argv, ni en la bitácora.** El hijo los usa en memoria y no escribe el `.p12`
en disco.

## Qué se garantiza al firmar

- **Firma incremental**: lo que había en el PDF queda **byte por byte** al principio del archivo
  firmado, y una firma anterior sigue válida (se añade, no se reescribe).
- Un certificado **vencido o aún no vigente** no firma: el motivo se dice con las fechas.
- Un PDF **cifrado** no se firma aquí: quítele antes la contraseña.

## Qué dice la verificación (y qué no)

Dice, por cada firma, si el **documento está íntegro** (el resumen coincide y la firma matemática
cuadra), si **cubre el archivo entero** (o si se añadió algo después), quién firmó y cuándo
**según el propio firmante**. **La confianza en el emisor solo se afirma si el servidor tiene una
lista de emisores de confianza** (`AEROCONVERT_RAICES_DE_CONFIANZA`, un PEM): sin ella, un
certificado autofirmado y uno del Estado se ven igual de «no comprobados», y se dice así; no se
da por buena una cadena que no se pudo mirar.

## El sello de tiempo (opcional)

Sin sello, la hora de la firma es **la que dice el firmante**. Con `AEROCONVERT_TSA_URL` (una
autoridad de sello de tiempo, RFC 3161) la firma lleva además la hora certificada por un tercero
(PAdES B-T). **Si la autoridad está configurada y no responde, no se firma**: entregar una firma sin
sello cuando se pidió con sello sería entregar otra cosa sin decirlo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .composicion import ComposicionInvalida

VARIABLE_RAICES = "AEROCONVERT_RAICES_DE_CONFIANZA"
VARIABLE_TSA = "AEROCONVERT_TSA_URL"

#: Un `.p12` pesa unos pocos KB; esto corta lo que claramente no lo es.
TAMANO_MAXIMO_P12 = 256 * 1024


@dataclass(frozen=True)
class Certificado:
    firmante: str
    emisor: str
    desde: datetime
    hasta: datetime
    autofirmado: bool


@dataclass(frozen=True)
class Firmada:
    campo: str
    firmante: str
    previas: int  # firmas que ya traía el PDF y siguen intactas
    sellada: bool = False  # con sello de tiempo de una autoridad


@dataclass(frozen=True)
class Firma:
    campo: str
    firmante: str
    emisor: str
    fecha_dicha: str  # lo que dice el firmante: no es una hora certificada
    integra: bool
    cubre_todo: bool
    confianza: str  # «comprobada», «no comprobada» o «rota»
    vigente_al_firmar: bool | None
    problema: str = ""
    valida_desde: str = ""
    valida_hasta: str = ""
    sello: str = ""  # la hora certificada por la autoridad de sello de tiempo, si la trae


@dataclass
class Informe:
    firmas: list[Firma] = field(default_factory=list)
    raices: int = 0  # cuántos emisores de confianza tiene el servidor
    aviso_raices: str = ""  # la lista está configurada, pero no sirve


def _nombre(x509_nombre) -> str:
    from cryptography.x509.oid import NameOID

    for oid in (NameOID.COMMON_NAME, NameOID.ORGANIZATION_NAME):
        partes = x509_nombre.get_attributes_for_oid(oid)
        if partes:
            return str(partes[0].value)
    return x509_nombre.rfc4514_string() or "sin nombre"


def leer_certificado(p12: bytes, clave: str) -> Certificado:
    """Abre el `.p12` y dice de quién es. No lo escribe en ningún lado."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    if len(p12) > TAMANO_MAXIMO_P12:
        raise ComposicionInvalida("Ese archivo no parece un certificado: pesa demasiado.")
    try:
        privada, cert, _otros = pkcs12.load_key_and_certificates(p12, clave.encode("utf-8"))
    except ValueError as fallo:
        # No se distingue «contraseña mala» de «archivo malo» a propósito: dar más pistas sobre
        # un `.p12` ajeno ayuda a quien prueba claves.
        raise ComposicionInvalida(
            "El certificado no se abre: la contraseña no es la suya o el archivo no es un .p12."
        ) from fallo
    if privada is None or cert is None:
        raise ComposicionInvalida("El .p12 no trae la clave privada y el certificado juntos.")
    desde = cert.not_valid_before_utc
    hasta = cert.not_valid_after_utc
    ahora = datetime.now(UTC)
    if ahora < desde:
        raise ComposicionInvalida(
            f"El certificado de {_nombre(cert.subject)} empieza a valer el {desde:%d/%m/%Y}."
        )
    if ahora > hasta:
        raise ComposicionInvalida(
            f"El certificado de {_nombre(cert.subject)} venció el {hasta:%d/%m/%Y}."
        )
    return Certificado(
        _nombre(cert.subject), _nombre(cert.issuer), desde, hasta, cert.subject == cert.issuer
    )


def _firmas_que_trae(origen: Path) -> int:
    from pyhanko.pdf_utils.reader import PdfFileReader

    with open(origen, "rb") as f:
        return len(PdfFileReader(f).embedded_signatures)


def firmar(
    origen: str | Path,
    destino: str | Path,
    p12: bytes,
    clave: str,
    *,
    motivo: str = "",
    lugar: str = "",
    sellador=None,
) -> Firmada:
    """Firma `origen` y deja el resultado en `destino`. El original no se toca.

    `sellador` es la autoridad de sello de tiempo; sin pasarla, se usa la de `AEROCONVERT_TSA_URL`
    si está configurada.
    """
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.misc import PdfError
    from pyhanko.sign import fields, signers
    from pyhanko.sign.timestamps.common_utils import TimestampRequestError

    origen, destino = Path(origen), Path(destino)
    certificado = leer_certificado(p12, clave)  # primero lo barato: contraseña y vigencia
    try:
        previas = _firmas_que_trae(origen)
        firmante = signers.SimpleSigner.load_pkcs12_data(
            p12, other_certs=[], passphrase=clave.encode("utf-8")
        )
        campo = f"Firma{previas + 1}"
        with open(origen, "rb") as entrada:
            escritor = IncrementalPdfFileWriter(entrada)
            if escritor.prev.encrypted:
                raise ComposicionInvalida(
                    f"{origen.name} tiene contraseña: quítesela antes de firmar."
                )
            metadatos = signers.PdfSignatureMetadata(
                field_name=campo,
                md_algorithm="sha256",
                subfilter=fields.SigSeedSubFilter.PADES,
                reason=motivo or None,
                location=lugar or None,
            )
            sellador = sellador if sellador is not None else _sellador_configurado()
            with open(destino, "wb") as salida:
                signers.sign_pdf(
                    escritor, metadatos, signer=firmante, timestamper=sellador, output=salida
                )
    except ComposicionInvalida:
        destino.unlink(missing_ok=True)
        raise
    except (ConnectionError, TimeoutError, TimestampRequestError) as fallo:
        # Antes que `OSError`: un `ConnectionError` también lo es, y diría «no se pudo firmar el
        # PDF» cuando lo que falló fue la autoridad de sello.
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(
            "La autoridad de sello de tiempo no respondió como debía; no se firma sin el sello "
            f"que está configurado ({type(fallo).__name__})."
        ) from fallo
    except (PdfError, ValueError, OSError) as fallo:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(f"No se pudo firmar {origen.name}: {fallo}") from fallo
    except Exception as fallo:  # noqa: BLE001 - la autoridad de sello no respondió o respondió mal
        destino.unlink(missing_ok=True)
        if sellador is None:
            raise
        raise ComposicionInvalida(
            "La autoridad de sello de tiempo no respondió como debía; no se firma sin el sello "
            f"que está configurado ({type(fallo).__name__})."
        ) from fallo
    return Firmada(campo, certificado.firmante, previas, sellada=sellador is not None)


def _sellador_configurado():
    """La autoridad de `AEROCONVERT_TSA_URL`, o `None` si no hay ninguna configurada."""
    url = os.environ.get(VARIABLE_TSA, "").strip()
    if not url:
        return None
    if not url.lower().startswith(("https://", "http://")):
        raise ComposicionInvalida(f"{VARIABLE_TSA} no es una dirección http(s).")
    from pyhanko.sign.timestamps import HTTPTimeStamper

    return HTTPTimeStamper(url, timeout=20)


# --- Verificación de las firmas de un PDF recibido -------------------------------------------


def _raices() -> tuple[list, str]:
    """(los emisores de confianza del servidor, y un aviso si la lista está configurada y rota).

    Una lista **configurada pero ilegible** no es lo mismo que no tener lista: la persona cree que
    la hay, y callarlo escondería que la configuración está mal.
    """
    ruta = os.environ.get(VARIABLE_RAICES, "").strip()
    if not ruta:
        return [], ""
    from pyhanko.keys import load_certs_from_pemder_data

    try:
        raices = list(load_certs_from_pemder_data(Path(ruta).read_bytes()))
    except (OSError, ValueError) as fallo:
        return [], f"el archivo de emisores de confianza no se pudo leer ({type(fallo).__name__})"
    if not raices:
        return [], "el archivo de emisores de confianza no trae ningún certificado"
    return raices, ""


def _fecha(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def verificar(origen: str | Path) -> Informe:
    """Una `Firma` por cada firma del PDF. Sin firmas es un resultado, no un error."""
    from pyhanko.pdf_utils.misc import PdfError
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    origen = Path(origen)
    raices, aviso = _raices()
    informe = Informe(raices=len(raices), aviso_raices=aviso)
    try:
        with open(origen, "rb") as f:
            lector = PdfFileReader(f)
            if lector.encrypted:
                raise ComposicionInvalida(
                    f"{origen.name} tiene contraseña: quítesela antes de verificar."
                )
            contexto = ValidationContext(trust_roots=raices, allow_fetching=False)
            for incrustada in lector.embedded_signatures:
                try:
                    estado = validate_pdf_signature(incrustada, contexto)
                except Exception as fallo:  # noqa: BLE001 - una firma ilegible se cuenta
                    informe.firmas.append(
                        Firma(
                            incrustada.field_name,
                            "(ilegible)",
                            "",
                            "",
                            False,
                            False,
                            "rota",
                            None,
                            problema=f"No se pudo leer la firma: {fallo}",
                        )
                    )
                    continue
                cert = estado.signing_cert
                dt = estado.signer_reported_dt
                desde, hasta = cert.not_valid_before, cert.not_valid_after
                vigente = bool(dt and desde <= dt <= hasta)
                if not (estado.intact and estado.valid):
                    confianza = "rota"
                elif raices and estado.trusted:
                    confianza = "comprobada"
                else:
                    confianza = "no comprobada"
                informe.firmas.append(
                    Firma(
                        campo=incrustada.field_name,
                        firmante=_nombre_asn1(cert.subject),
                        emisor=_nombre_asn1(cert.issuer),
                        fecha_dicha=_fecha(dt),
                        integra=bool(estado.intact and estado.valid),
                        cubre_todo=str(estado.coverage).endswith("ENTIRE_FILE"),
                        confianza=confianza,
                        vigente_al_firmar=vigente if dt else None,
                        valida_desde=_fecha(desde),
                        valida_hasta=_fecha(hasta),
                        sello=_hora_del_sello(estado),
                    )
                )
    except PdfError as fallo:
        raise ComposicionInvalida(f"{origen.name} no se lee como un PDF: {fallo}") from fallo
    except OSError as fallo:
        raise ComposicionInvalida(f"{origen.name} no se pudo abrir: {fallo}") from fallo
    return informe


def _hora_del_sello(estado) -> str:
    """La hora certificada por la autoridad, si la firma trae sello y el sello está íntegro."""
    sello = getattr(estado, "timestamp_validity", None)
    if sello is None or not getattr(sello, "intact", False):
        return ""
    return _fecha(getattr(sello, "timestamp", None))


def _nombre_asn1(nombre) -> str:
    humano = getattr(nombre, "human_friendly", "") or ""
    for linea in humano.splitlines():
        if linea.lower().startswith("common name:"):
            return linea.split(":", 1)[1].strip()
    return humano.replace("\n", ", ") or "sin nombre"


def a_markdown(informe: Informe, nombre_pdf: str) -> str:
    """El informe como texto: lo que hay que decir, sin adornos y sin dar por buena una cadena."""
    lineas = [f"# Firmas de {nombre_pdf}", ""]
    if not informe.firmas:
        lineas += ["Este PDF **no trae ninguna firma digital**.", ""]
        return "\n".join(lineas)
    lineas.append(f"Firmas encontradas: **{len(informe.firmas)}**.")
    if informe.aviso_raices:
        lineas.append(
            f"**Aviso de configuración:** {informe.aviso_raices}. La integridad se comprueba, "
            "pero quién emitió el certificado queda sin comprobar."
        )
    elif informe.raices:
        lineas.append(
            f"Emisores de confianza del servidor: {informe.raices}. «Comprobada» quiere decir que "
            "la cadena llega a uno de ellos; **no se consultó si el certificado fue revocado**."
        )
    else:
        lineas.append(
            "El servidor **no tiene una lista de emisores de confianza**: la integridad se "
            "comprueba, pero quién emitió el certificado queda sin comprobar."
        )
    lineas.append("")
    for n, f in enumerate(informe.firmas, start=1):
        lineas += [f"## {n}. {f.firmante}", ""]
        lineas.append(f"- Campo: `{f.campo}`")
        if f.problema:
            lineas.append(f"- **Problema:** {f.problema}")
        if not f.integra:
            lineas.append("- Documento: **ROTO**: cambió después de firmarse o la firma no cuadra.")
        elif f.cubre_todo:
            lineas.append("- Documento: **íntegro**, no cambió desde que se firmó.")
        else:
            lineas.append(
                "- Documento: **lo firmado no cambió**, pero **se añadió contenido después** que "
                "esta firma no cubre (otra firma, o cambios que conviene revisar)."
            )
        if f.emisor:
            lineas.append(f"- Emisor del certificado: {f.emisor}")
        if f.sello:
            lineas.append(
                f"- **Sello de tiempo:** {f.sello} (hora certificada por una autoridad de sello; "
                "no se comprobó si esa autoridad es de confianza)."
            )
        if f.fecha_dicha:
            lineas.append(
                f"- Fecha según el firmante: {f.fecha_dicha} (no es una hora certificada)."
            )
        if f.valida_desde:
            lineas.append(f"- Certificado válido del {f.valida_desde} al {f.valida_hasta}.")
        if f.vigente_al_firmar is False:
            lineas.append("- **Aviso:** el certificado no estaba vigente en la fecha que dice.")
        lineas.append(
            {
                "comprobada": "- Confianza en el emisor: **comprobada** (lista del servidor).",
                "no comprobada": "- Confianza en el emisor: **no comprobada**.",
                "rota": "- Confianza en el emisor: no aplica (la firma está rota).",
            }[f.confianza]
        )
        lineas.append("")
    return "\n".join(lineas)
