"""Aplicar un paquete de entrega a un archivo o a una carpeta entera (F16.1 y F16.2).

Un **lote** es el trabajo padre: agrupa los trabajos hijos de aplicar un paquete a cada archivo de
una carpeta (o a uno solo). Cada hijo es un `ConversionJob` de siempre, con su motor, su
verificación y su oráculo; el lote **no convierte nada por su cuenta**.

## Lo que no hace

- **No adivina el CRS.** Un archivo sin sistema de coordenadas se encola igual que en la pantalla de
  convertir: sin sistema declarado. Si el paquete reproyecta, o el destino lo exige, el corredor lo
  detiene con `crs-ausente` y el lote lo dice, con el nombre del archivo. No hay un sistema
  «para todo el lote».
- **No pisa el original.** Si el nombre que da el patrón coincide con el del archivo de origen, el
  paquete no se aplica a ese archivo: dice por qué.
- **No esconde lo que dejó fuera.** Los archivos que no se reconocen, o para los que no hay motor,
  quedan en `omitidos` con su motivo, a la vista en la ficha del lote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.db import models, transaction

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.engines import registry
from apps.engines.base import ParDeFormatos
from apps.formats import catalogo, deteccion
from apps.jobs.models import ConversionJob, LoteDeTrabajos

from .models import ConversionPreset
from .paquetes import PaqueteInvalido, expandir

#: Un lote de mil archivos inspeccionados de una vez en la petición es un servidor colgado.
MAXIMO_DE_ARCHIVOS_POR_LOTE = 200


@dataclass
class ResultadoDelLote:
    lote: LoteDeTrabajos
    trabajos: list[ConversionJob] = field(default_factory=list)
    omitidos: list[dict] = field(default_factory=list)


def _ruta_de_salida(origen: Path, nombre: str, formato: str) -> Path:
    definicion = catalogo.FORMATOS.get(formato)
    extension = definicion.extension_para_escribir if definicion else ".out"
    if modo_mod.es_taller():
        return origen.with_name(f"{nombre}{extension}")

    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{nombre}{extension}"


def _codigo_epsg(texto: str) -> str:
    texto = (texto or "").strip()
    return texto.split(":")[-1] if texto else ""


def encolar_paquete_para_un_archivo(
    *,
    usuario,
    paquete,
    origen: entrada_mod.Origen,
    inspeccion,
    lote: LoteDeTrabajos,
    fecha: date,
    salidas_usadas: set[str],
    originales: frozenset[str] = frozenset(),
) -> list[ConversionJob]:
    """Los trabajos de un archivo, **todos o ninguno**: si un paso no se puede, ninguno se encola.

    Levanta `PaqueteInvalido` con el motivo dicho para una persona.
    """
    preajustes = {
        p.slug: p
        for p in ConversionPreset.visibles_para(usuario).filter(slug__in=list(paquete.pasos or []))
    }
    pasos = expandir(paquete, preajustes, nombre_origen=Path(origen.nombre).stem, fecha=fecha)

    ruta_origen = Path(inspeccion.ruta)
    previstos = []
    for paso in pasos:
        par = ParDeFormatos(inspeccion.codigo_formato, paso.formato)
        if registry.motor_para(par) is None:
            celda = registry.celda(par)
            raise PaqueteInvalido(
                f"El paso {paso.orden} («{paso.formato}») no se puede hacer con este archivo: "
                f"{celda.mensaje or 'ningún motor sabe esa conversión.'}"
            )
        salida = _ruta_de_salida(ruta_origen, paso.nombre_de_salida, paso.formato)
        if salida.resolve() == ruta_origen.resolve() or (
            salida.name.lower() == ruta_origen.name.lower() and salida.parent == ruta_origen.parent
        ):
            raise PaqueteInvalido(
                f"El paso {paso.orden} escribiría sobre el archivo original ({salida.name}). "
                "Cambie el patrón del nombre."
            )
        if _clave(salida) in originales:
            raise PaqueteInvalido(
                f"El paso {paso.orden} escribiría sobre {salida.name}, que ya está en la carpeta y "
                "puede ser un original. Cambie el patrón del nombre."
            )
        if str(salida).lower() in salidas_usadas:
            raise PaqueteInvalido(
                f"El paso {paso.orden} daría el mismo archivo de salida ({salida.name}) que "
                "otro del lote. Ponga {origen} en el patrón del nombre."
            )
        previstos.append((paso, salida))

    trabajos = []
    for paso, salida in previstos:
        salidas_usadas.add(str(salida).lower())
        crs = inspeccion.crs
        destino_crs = _codigo_epsg(paso.crs_destino)
        trabajo = ConversionJob.objects.create(
            owner=usuario,
            lote=lote,
            source_path=str(ruta_origen),
            source_name=origen.nombre,
            source_size_bytes=inspeccion.bytes_totales,
            source_format_code=inspeccion.codigo_formato,
            source_format_confidence=inspeccion.confianza,
            source_crs_authority=crs.autoridad,
            source_crs_code=crs.codigo,
            source_crs_origin=crs.origen,
            target_format_code=paso.formato,
            target_profile_id=paso.perfil_id,
            target_crs_authority="EPSG" if destino_crs else "",
            target_crs_code=destino_crs,
            options=dict(paso.opciones),
            output_path=str(salida),
        )
        trabajo.registrar(
            f"Paso {paso.orden} del paquete «{paquete.nombre}» (lote {lote.pk}): "
            f"{paso.formato}" + (f", sistema {paso.crs_destino}" if destino_crs else "") + "."
        )
        trabajos.append(trabajo)
    return trabajos


def _clave(ruta: Path) -> str:
    """La ruta como se compara: resuelta y sin distinguir mayúsculas (Windows no las distingue)."""
    try:
        return str(ruta.resolve()).lower()
    except OSError:
        return str(ruta).lower()


def _archivos_de(ruta: Path) -> list[Path]:
    """Los archivos de una carpeta (sin entrar en subcarpetas), en orden, sin los ocultos."""
    return sorted(
        (p for p in ruta.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )


def aplicar_paquete(*, usuario, paquete, ruta: str, fecha: date | None = None) -> ResultadoDelLote:
    """Aplica `paquete` a un archivo o a todos los de una carpeta, y devuelve el lote.

    Levanta `PaqueteInvalido` si no hay nada que aplicar (carpeta vacía, demasiados archivos,
    ninguno reconocible). **La ruta pasa por `modo.comprobar_ruta`**: fuera de las carpetas
    permitidas no se mira.
    """
    fecha = fecha or date.today()
    try:
        raiz = modo_mod.comprobar_ruta(ruta)
    except modo_mod.RutaNoPermitida as fallo:
        raise PaqueteInvalido(str(fallo)) from fallo

    if raiz.is_dir():
        archivos = _archivos_de(raiz)
        carpeta = str(raiz)
    elif raiz.is_file():
        archivos = [raiz]
        carpeta = str(raiz.parent)
    else:
        raise PaqueteInvalido("Esa ruta no es un archivo ni una carpeta.")
    if not archivos:
        raise PaqueteInvalido("La carpeta no tiene archivos.")
    if len(archivos) > MAXIMO_DE_ARCHIVOS_POR_LOTE:
        raise PaqueteInvalido(
            f"La carpeta tiene {len(archivos)} archivos y un lote admite hasta "
            f"{MAXIMO_DE_ARCHIVOS_POR_LOTE}. Elija una subcarpeta o divida el trabajo."
        )

    # **Todo lo que ya hay en la carpeta es un original** hasta que se demuestre lo contrario: una
    # salida que cayera sobre `a_cog.tif` (otro archivo de la carpeta) lo reemplazaría sin aviso.
    originales = frozenset(_clave(a) for a in archivos)
    with transaction.atomic():
        return _aplicar(usuario, paquete, archivos, carpeta, fecha, originales)


def _aplicar(usuario, paquete, archivos, carpeta, fecha, originales) -> ResultadoDelLote:
    lote = LoteDeTrabajos.objects.create(
        owner=usuario, nombre=paquete.nombre, carpeta=carpeta, paquete_slug=paquete.slug
    )
    resultado = ResultadoDelLote(lote=lote)
    usadas: set[str] = set()

    for archivo in archivos:
        try:
            origen = entrada_mod.resolver(str(archivo), usuario=usuario)
            inspeccion = deteccion.inspeccionar(origen.ruta)
        except (modo_mod.RutaNoPermitida, deteccion.OrigenIlegible) as fallo:
            resultado.omitidos.append(
                {
                    "nombre": archivo.name,
                    "codigo": getattr(fallo, "codigo", "") or "origen-no-legible",
                    "motivo": str(fallo),
                }
            )
            continue
        try:
            resultado.trabajos += encolar_paquete_para_un_archivo(
                usuario=usuario,
                paquete=paquete,
                origen=origen,
                inspeccion=inspeccion,
                lote=lote,
                fecha=fecha,
                salidas_usadas=usadas,
                originales=originales,
            )
        except PaqueteInvalido as fallo:
            resultado.omitidos.append(
                {"nombre": archivo.name, "codigo": "paquete-no-aplicable", "motivo": str(fallo)}
            )

    lote.omitidos = resultado.omitidos
    lote.save(update_fields=["omitidos", "updated_at"])
    if not resultado.trabajos:
        lote.delete()  # y nada queda a medias: lo creado en esta llamada se va con él
        primero = resultado.omitidos[0]["motivo"] if resultado.omitidos else ""
        raise PaqueteInvalido(
            "No se encoló nada: ningún archivo se pudo tratar con este paquete."
            + (f" Por ejemplo, {resultado.omitidos[0]['nombre']}: {primero}" if primero else "")
        )

    type(paquete).objects.filter(pk=paquete.pk).update(veces_usado=models.F("veces_usado") + 1)
    return resultado
