"""Un vuelo de «Corregir un vuelo de dron» como capas del mapa (F19.3).

## De dónde sale

Del `vuelo.json` que deja el trabajo en su zip (el mismo que dibuja el visor del vuelo, F18.4). Este
módulo **lo lee, no lo escribe**, y no importa nada de `apps/vuelos` (`test_independencia.py` vigila
esa dirección): conoce el formato por el archivo.

## De quién es

De **quien pidió el trabajo**: `propio()` busca por `owner`, herramienta y estado, y todo lo demás
—«no existe», «es de otra persona», «no ha terminado»— es el mismo `VueloNoEncontrado`, que la vista
convierte en 404. Que sea distinto de un 403 es deliberado y es lo que hace el visor del vuelo:
confirmar que un identificador ajeno existe ya es una fuga. La miniatura y la ficha de cada foto las
sirven las vistas de `apps/vuelos`, con sus propias comprobaciones de dueño y de carpeta.

## Cómo se proyecta (regla 3: el sistema no se adivina)

Cada foto trae su latitud y longitud, y el mapa las pasa a EPSG:3857 con la misma fórmula de la
cuadrícula de teselas (`mercator.lonlat_a_mercator`). La trayectoria solo trae Este y Norte **en el
sistema que el trabajo midió o que la persona declaró** (`sistema.epsg`) y relativos a un origen: se
vuelven grados con PROJ, a la inversa de como el trabajo los calculó, y de ahí a Web Mercator. Si el
vuelo no declara ese sistema, **no se dibuja nada** y se dice por qué (`vuelo-sin-crs`):
ubicarlo con uno supuesto sería inventar dónde voló.

Una foto sin posición no se dibuja; se cuenta aparte. Un vuelo con RTK no tiene recorrido y no se
inventa uno uniendo las fotos. Los puntos de control los lee de `puntos_de_control` si el
archivo los trae (`nombre`, `lat`, `lon`); hoy el trabajo no los escribe, y la capa lo dice.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

from django.urls import reverse

from apps.jobs.motivos import MOTIVOS

from . import capas, mercator

HERRAMIENTA = "vuelo_dron"

#: Tope de tamaño del `vuelo.json` que se lee: el de un vuelo de miles de fotos pesa unos MB.
LIMITE_DEL_JSON_BYTES = 64 * 1024 * 1024


class VueloNoEncontrado(Exception):
    """No existe, no es de quien pregunta, o no terminó. Un solo mensaje para los tres."""


class VueloIlegible(Exception):
    """Es suyo y terminó, pero su zip no trae un `vuelo.json` que se pueda leer."""


def propio(usuario, pk):
    """El trabajo de vuelo **de esta persona**, terminado y con su resultado en el disco."""
    from apps.jobs.models import HECHO, ConversionJob

    try:
        job = ConversionJob.objects.get(pk=pk, owner=usuario, herramienta=HERRAMIENTA, status=HECHO)
    except (ConversionJob.DoesNotExist, ValueError, TypeError) as fallo:
        raise VueloNoEncontrado(str(pk)) from fallo
    try:
        existe = bool(job.output_path) and Path(job.output_path).is_file()
    except OSError:
        existe = False
    if not existe:
        raise VueloNoEncontrado(str(pk))
    return job


def propios(usuario, *, maximo: int = 12) -> list:
    """Los vuelos terminados de esta persona, del más reciente al más viejo, para elegir uno."""
    from apps.jobs.models import HECHO, ConversionJob

    elegidos = []
    trabajos = ConversionJob.objects.filter(
        owner=usuario, herramienta=HERRAMIENTA, status=HECHO
    ).exclude(output_path="")
    for job in trabajos.order_by("-finished_at")[:60]:
        try:
            if not Path(job.output_path).is_file():
                continue
        except OSError:
            continue
        elegidos.append(job)
        if len(elegidos) >= maximo:
            break
    return elegidos


def nombre_de(job) -> str:
    """Cómo se llama el vuelo en la lista: el nombre del resultado sin su sufijo."""
    base = Path(job.output_path).stem
    return base.removesuffix("_vuelo") or base or "Vuelo"


def leer_datos(job) -> dict:
    try:
        with zipfile.ZipFile(job.output_path) as paquete:
            info = paquete.getinfo("vuelo.json")
            if info.file_size > LIMITE_DEL_JSON_BYTES:
                raise VueloIlegible("vuelo.json demasiado grande")
            datos = json.loads(paquete.read(info))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as fallo:
        raise VueloIlegible(str(fallo)) from fallo
    if not isinstance(datos, dict) or not isinstance(datos.get("fotos"), list):
        raise VueloIlegible("vuelo.json sin fotos")
    return datos


def _motivo(codigo: str) -> dict:
    m = MOTIVOS[codigo]
    return {"codigo": codigo, "mensaje": m.mensaje, "sugerencia": m.sugerencia}


def _apagada(codigo: str) -> dict:
    return {"disponible": False, "puntos": [], **_motivo(codigo)}


def _finito(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _en_mercator(lon, lat) -> tuple[float, float] | None:
    if not (_finito(lon) and _finito(lat)) or not -180 <= lon <= 180:
        return None
    try:
        return mercator.lonlat_a_mercator(lon, lat)
    except ValueError:
        return None


def _transformador(sistema):
    """`(EPSG del vuelo → grados)` o `None` si el vuelo no declara un sistema que PROJ conozca."""
    if not isinstance(sistema, dict):
        return None
    epsg = sistema.get("epsg")
    if not isinstance(epsg, int) or isinstance(epsg, bool) or epsg <= 0:
        return None
    from pyproj import Transformer
    from pyproj.exceptions import CRSError, ProjError

    try:
        return Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    except (CRSError, ProjError):
        return None


def _trayectoria(datos: dict, a_grados) -> dict:
    puntos_crudos = datos.get("trayectoria") or []
    if not puntos_crudos:
        return _apagada("vuelo-sin-trayectoria")
    origen = datos.get("origen") or {}
    este0, norte0 = origen.get("este"), origen.get("norte")
    if not (_finito(este0) and _finito(norte0)):
        return _apagada("vuelo-sin-crs")
    puntos = []
    for par in puntos_crudos:
        if not (isinstance(par, list) and len(par) >= 2 and _finito(par[0]) and _finito(par[1])):
            continue
        lon, lat = a_grados.transform(este0 + par[0], norte0 + par[1])
        punto = _en_mercator(lon, lat)
        if punto is not None:
            puntos.append([round(punto[0], 3), round(punto[1], 3)])
    if len(puntos) < 2:
        return _apagada("vuelo-sin-trayectoria")
    return {"disponible": True, "puntos": puntos, "total": datos.get("trayectoria_total")}


def _fotos(datos: dict) -> dict:
    puntos, sin_posicion = [], 0
    for f in datos["fotos"]:
        if not isinstance(f, dict):
            continue
        punto = _en_mercator(f.get("lon"), f.get("lat"))
        if punto is None:
            sin_posicion += 1
            continue
        calidad = f.get("calidad") if isinstance(f.get("calidad"), str) else ""
        puntos.append(
            {
                "n": f.get("n"),
                "nombre": str(f.get("nombre") or ""),
                "lon": f["lon"],
                "lat": f["lat"],
                "mx": round(punto[0], 3),
                "my": round(punto[1], 3),
                "calidad": calidad,
                "clase": capas.clase_de_calidad(calidad),
                "miniatura": bool(f.get("miniatura")),
            }
        )
    if not puntos:
        return {**_apagada("vuelo-sin-fotos-con-posicion"), "sin_posicion": sin_posicion}
    return {"disponible": True, "puntos": puntos, "sin_posicion": sin_posicion}


def _control(datos: dict) -> dict:
    crudos = datos.get("puntos_de_control") or []
    puntos = []
    for c in crudos if isinstance(crudos, list) else []:
        if not isinstance(c, dict):
            continue
        punto = _en_mercator(c.get("lon"), c.get("lat"))
        if punto is not None:
            puntos.append(
                {
                    "nombre": str(c.get("nombre") or ""),
                    "lon": c["lon"],
                    "lat": c["lat"],
                    "mx": round(punto[0], 3),
                    "my": round(punto[1], 3),
                }
            )
    if not puntos:
        return _apagada("vuelo-sin-puntos-de-control")
    return {"disponible": True, "puntos": puntos}


def _caja(*grupos: list) -> list[float] | None:
    todos = [p for g in grupos for p in g]
    if not todos:
        return None
    xs = [p["mx"] if isinstance(p, dict) else p[0] for p in todos]
    ys = [p["my"] if isinstance(p, dict) else p[1] for p in todos]
    return [min(xs), min(ys), max(xs), max(ys)]


def para_el_mapa(job, datos: dict) -> dict:
    """Lo que el navegador dibuja de este vuelo, ya en metros de EPSG:3857.

    Con un vuelo que no declara su sistema: `dibujable` falso y **ninguna parte** con puntos.
    """
    sistema = datos.get("sistema") if isinstance(datos.get("sistema"), dict) else {}
    respuesta = {
        "pk": str(job.pk),
        "nombre": nombre_de(job),
        "sistema": {"epsg": sistema.get("epsg"), "nombre": sistema.get("nombre", "")},
        "urls": {
            "ver": reverse("documents:vuelo_ver", args=[job.pk]),
            "miniatura": reverse("documents:vuelo_miniatura", args=[job.pk, 0]).replace(
                "/foto/0/", "/foto/{n}/"
            ),
            "ficha": reverse("documents:vuelo_ficha", args=[job.pk, 0]).replace(
                "/foto/0/", "/foto/{n}/"
            ),
        },
        "con_miniaturas": bool((job.options or {}).get("carpeta_de_fotos")),
    }
    a_grados = _transformador(sistema)
    if a_grados is None:
        sin_sistema = _apagada("vuelo-sin-crs")
        return {
            **respuesta,
            "dibujable": False,
            **_motivo("vuelo-sin-crs"),
            "trayectoria": sin_sistema,
            "fotos": {**sin_sistema, "sin_posicion": 0},
            "control": sin_sistema,
            "caja_3857": None,
        }
    trayectoria = _trayectoria(datos, a_grados)
    fotos = _fotos(datos)
    control = _control(datos)
    caja = _caja(trayectoria["puntos"], fotos["puntos"], control["puntos"])
    return {
        **respuesta,
        "dibujable": caja is not None,
        **({} if caja is not None else _motivo("vuelo-sin-fotos-con-posicion")),
        "trayectoria": trayectoria,
        "fotos": fotos,
        "control": control,
        "caja_3857": caja,
    }
