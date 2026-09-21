"""Lo que ya has hecho, para poder volver a hacerlo sin buscarlo.

## Historial y no favoritos, y cuestan lo mismo

Los dos son «guarda lo que usas para tenerlo a mano», y la diferencia decide cuál sirve:
**uno se llena solo y el otro nace vacío**. Un panel de favoritos exige un acto deliberado
—acordarse de marcar algo mientras se está haciendo otra cosa— que casi nadie hace nunca, y
un panel vacío en la portada ocupa sitio sin dar nada. El historial existe ya: son las
conversiones que están en la base.

## Por destino y no por archivo, que es lo que lo hace útil

Un registro de las últimas cinco conversiones es un **historial**, y para eso está la
pantalla de historial. Lo que hace falta en la portada es otra cosa: **volver a hacer lo que
sueles hacer**, y eso no es un archivo, es un destino. Cinco ortofotos llevadas a QGIS son
una sola fila —«A QGIS»— y no cinco que empujan todo lo demás fuera de la pantalla.

El nombre del último archivo sí sale, en gris y detrás: no es donde lleva el enlace, es lo
que permite reconocer la fila de un vistazo sin leer el rótulo.

## Solo lo que salió bien

Un trabajo que falló no es algo que se quiera repetir a ciegas: repetirlo igual va a fallar
igual. Está en el historial con su motivo, que es donde sirve.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.formats import catalogo
from apps.targets import perfiles as perfiles_mod

from .acciones import ICONOS_DE_PERFIL

#: Cuántas filas. Cuatro y no diez: esto va encima del catálogo, y lo que empuja al catálogo
#: fuera de la pantalla deja de ser una ayuda para ser un estorbo.
CUANTAS = 4

#: De cuántos trabajos se sacan. Con el tope de filas puesto en cuatro destinos distintos,
#: mirar los últimos cuarenta basta y sobra, y no hace crecer la consulta con el uso.
DE_CUANTOS = 40


@dataclass(frozen=True)
class Repetible:
    """Algo que ya hiciste y que puedes volver a hacer en un clic."""

    #: Lo que la fila dice en grande: «A QGIS», «A GeoPackage».
    titulo: str
    #: A dónde lleva, ya con el destino elegido.
    enlace: str
    icono: str
    #: El último archivo que fue por ahí. Para reconocer la fila, no para abrirlo.
    ultimo_archivo: str
    cuando: object
    #: Cuántas veces, cuando es más de una. Es lo que distingue «lo que haces» de «lo que
    #: hiciste una vez»: una fila con «7 veces» se reconoce sin leerla.
    veces: int


def repetibles(usuario) -> list[Repetible]:
    """Los destinos a los que este usuario lleva cosas, el más reciente primero."""
    from apps.jobs.models import HECHO, ConversionJob

    trabajos = ConversionJob.objects.filter(owner=usuario, status=HECHO).order_by("-created_at")[
        :DE_CUANTOS
    ]

    vistos: dict[str, dict] = {}
    for trabajo in trabajos:
        clave, titulo, enlace, icono = _como_se_repite(trabajo)
        if not clave:
            continue
        if clave in vistos:
            vistos[clave]["veces"] += 1
            continue
        vistos[clave] = {
            "titulo": titulo,
            "enlace": enlace,
            "icono": icono,
            "ultimo_archivo": trabajo.source_name,
            "cuando": trabajo.created_at,
            "veces": 1,
        }

    return [Repetible(**fila) for fila in list(vistos.values())[:CUANTAS]]


def _como_se_repite(trabajo) -> tuple[str, str, str, str]:
    """Clave, rótulo, enlace e icono de un trabajo. Clave vacía si no se sabe repetir.

    **El perfil manda sobre el formato**, y en ese orden porque es el orden en que se eligió:
    quien pulsó «Llevarlo a QGIS» no eligió GeoPackage, eligió QGIS — y repetir su elección
    es volver a esa pantalla, no a un formato suelto que además podría cambiar el día que el
    perfil ajuste su salida.
    """
    from django.urls import reverse

    destino = reverse("dashboard:convertir")

    perfil = perfiles_mod.PERFILES.get(trabajo.target_profile_id or "")
    if perfil is not None:
        return (
            f"perfil:{perfil.id}",
            f"A {perfil.nombre}",
            f"{destino}?destino={perfil.id}",
            ICONOS_DE_PERFIL.get(perfil.id, "icon-destino"),
        )

    codigo = trabajo.target_format_code or ""
    formato = catalogo.FORMATOS.get(codigo)
    if formato is not None:
        return (
            f"formato:{codigo}",
            f"A {formato.nombre}",
            f"{destino}?formato={codigo}",
            "icon-destino",
        )

    # Un código que ya no está en el catálogo: el trabajo sigue en el historial con su ficha,
    # pero **no se ofrece repetir algo que hoy no se sabe hacer**.
    return "", "", "", ""
