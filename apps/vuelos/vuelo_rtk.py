"""«Vuelo de dron con RTK»: la posición que el dron ya escribió en cada foto (F18.8).

Cuando el dron voló con RTK, no hay PPK que hacer: la posición precisa **ya está en cada foto**, en
el XMP de DJI (`drone-dji:GpsLatitude`, `GpsLongitude`, `AbsoluteAltitude`), con su calidad
(`RtkFlag`) y sus desviaciones (`RtkStdLat`, `RtkStdLon`, `RtkStdHgt`). Aquí se **lee** esa
posición, se dice qué tan buena es y se entrega con los mismos archivos que «Corregir un vuelo»:
CSV, GeoJSON, KML, `calidad.md` y los datos del visor.

## Lo que se comprueba antes de entregar

El `.MRK` que graba el dron en la tarjeta es **obligatorio** en esta entrada, y no por trámite: es
el otro lector.

- **Que las fotos son de ese `.MRK`.** Cada foto se empareja con su disparo por orden (solo si hay
  tantas como disparos) y la posición de su XMP se compara con la que el `.MRK` dice para el mismo
  disparo. Si alguna difiere más de `UMBRAL_DE_EMPAREJADO_M`, **no se entrega nada** y se dice cuál:
  o el `.MRK` es de otro vuelo, o las fotos ya traen aplicado el desfase de la antena y sumarlo otra
  vez las correría. Con un vuelo real de una Matrice 3E la coincidencia fue de 0,7 mm.
- **Qué altura es.** El XMP dice `AltitudeType="RtkAlt"` pero no dice «elipsoidal». El `.MRK` sí
  nombra la suya (`Ellh`). Si la altura del XMP coincide con ella a `UMBRAL_DE_ALTURA_M`, la
  referencia es «elipsoidal», con la comprobación dicha; si no, **no se afirma**.
- **Qué calidad.** La de `RtkFlag`; `GpsStatus` no sirve (`ficha_foto.py` lo explica).

Con el desfase de la antena del `.MRK` (norte y este suman, `V` resta, como en `vuelo_sync.py`) se
entrega la posición de la **cámara**; sin él, la de la antena, y el CSV lo dice.

## Lo que no hace

No hay trayectoria: el visor no dibuja línea (unir las fotos en orden inventaría un
recorrido). Ni se
mide el sistema de coordenadas del visor (no hay Este y Norte contra los que medirlo): se declara.
El archivo no dice en qué marco está la corrección RTK (una red RTK puede estar en SIRGAS o ITRF y
el EXIF dice «WGS-84» de todos modos): se dice, no se corrige.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from apps.documents.composicion import ComposicionInvalida

from . import ficha_foto, vuelo_proceso, vuelo_sync

#: Con cuántos metros de diferencia entre el XMP y el `.MRK` se deja de creer que son del mismo
#: vuelo (o que el desfase no está aplicado ya). El vuelo real quedó a 0,7 mm; el `.MRK` redondea a
#: ocho decimales de grado (1 mm).
UMBRAL_DE_EMPAREJADO_M = 0.02

#: Con cuántos metros se dice que la altura del XMP es la `Ellh` del `.MRK`.
UMBRAL_DE_ALTURA_M = 0.005

_M_POR_GRADO_LAT = 111_132.0
_M_POR_GRADO_LON = 111_320.0


def leer_carpeta(
    carpeta: Path, progreso: Callable[[float, str], None] | None = None
) -> list[ficha_foto.FichaFoto]:
    """Las fichas de todas las fotos de la carpeta, por orden de nombre. **Solo lee** las cabeceras.

    Una foto que no se puede abrir detiene el trabajo con su nombre: seguir sin ella correría los
    nombres contra los disparos.
    """
    nombres = vuelo_proceso.nombres_de_fotos(carpeta)
    if not nombres:
        raise ComposicionInvalida("La carpeta no trae ninguna foto JPG.")
    fichas = []
    for i, nombre in enumerate(nombres, start=1):
        try:
            fichas.append(ficha_foto.leer_ficha(carpeta / nombre))
        except ComposicionInvalida as fallo:
            raise ComposicionInvalida(f"{nombre}: {fallo}") from fallo
        if progreso is not None and (i % 50 == 0 or i == len(nombres)):
            progreso(0.02 + 0.5 * i / len(nombres), f"Leyendo las fotos ({i} de {len(nombres)})")
    return fichas


def _distancia_m(lat_a, lon_a, lat_b, lon_b) -> float:
    dn = (lat_a - lat_b) * _M_POR_GRADO_LAT
    de = (lon_a - lon_b) * _M_POR_GRADO_LON * math.cos(math.radians(lat_b))
    return math.hypot(dn, de)


def _codigo(ficha: ficha_foto.FichaFoto) -> int | None:
    """El código de `CALIDADES` de una bandera RTK; `0` (no informada) si no hay bandera."""
    if ficha.rtk_bandera is None:
        return 0
    return ficha_foto.CODIGO_DE_CALIDAD.get(ficha.rtk_bandera)


def _comprobar_el_mrk(fichas, eventos) -> dict:
    """Que cada foto es de su disparo, y qué altura es. Levanta si no son del mismo vuelo."""
    peor = (0.0, "")
    pares = 0
    for f, e in zip(fichas, eventos, strict=True):
        if not f.con_posicion or e.lat is None or e.lon is None:
            continue
        pares += 1
        d = _distancia_m(f.lat, f.lon, e.lat, e.lon)
        if d > peor[0]:
            peor = (d, f.nombre)
    if peor[0] > UMBRAL_DE_EMPAREJADO_M:
        raise ComposicionInvalida(
            f"La posición de {peor[1]} queda a {peor[0]:.2f} m de la de su disparo en el .MRK "
            f"(el máximo aceptado son {UMBRAL_DE_EMPAREJADO_M * 100:.0f} cm). O el .MRK no es de "
            "este vuelo, o el dron ya aplicó a las fotos el desfase de la antena: sumarlo otra "
            "vez las correría. No se entregó nada."
        )
    alturas = [
        (f.alt_m - e.alt_elipsoidal_m)
        for f, e in zip(fichas, eventos, strict=True)
        if f.alt_m is not None and e.alt_elipsoidal_m is not None
    ]
    maxima = max((abs(a) for a in alturas), default=None)
    return {
        "pares_de_posicion": pares,
        "horizontal_maxima_mm": peor[0] * 1000 if pares else None,
        "pares_de_altura": len(alturas),
        "altura_maxima_mm": maxima * 1000 if maxima is not None else None,
        "altura_es_la_del_mrk": bool(alturas) and maxima <= UMBRAL_DE_ALTURA_M,
    }


def _referencia_de_altura(medida: dict) -> str:
    if medida["pares_de_altura"] == 0:
        return "del XMP de DJI; referencia no comprobada (el .MRK no trae su altura)"
    if medida["altura_es_la_del_mrk"]:
        return "elipsoidal (la del XMP coincide con la «Ellh» del .MRK)"
    return "del XMP de DJI; no coincide con la «Ellh» del .MRK: referencia no afirmada"


def procesar(
    *,
    fichas: list[ficha_foto.FichaFoto],
    disparos: bytes,
    nombre_de_disparos: str,
    sistema: str,
    aplicar_desfase: bool = True,
    progreso: Callable[[float, str], None] | None = None,
) -> vuelo_proceso.Entregables:
    """Todo el proceso. Levanta `ComposicionInvalida` con el motivo, y no deja nada a medias."""
    from pyproj import Transformer

    def avance(fraccion: float, etiqueta: str) -> None:
        if progreso is not None:
            progreso(fraccion, etiqueta)

    if not nombre_de_disparos.lower().endswith(".mrk"):
        raise ComposicionInvalida(
            "Con las fotos RTK hace falta el archivo .MRK del dron: con él se comprueba que las "
            "fotos son de ese vuelo y de qué altura se trata."
        )
    if sistema in ("", "medir"):
        raise ComposicionInvalida(
            "Con las fotos RTK no hay con qué medir el sistema de coordenadas del visor: "
            "declare uno."
        )
    if not fichas:
        raise ComposicionInvalida("No hay ninguna foto que leer.")

    avance(0.55, "Leyendo los disparos de la cámara")
    eventos = vuelo_proceso._leer_disparos(disparos, nombre_de_disparos)
    nombres = vuelo_sync.emparejar(eventos, [f.nombre for f in fichas])
    # Se valida el sistema (que sea de los que se saben leer), y se dice por qué se declara.
    elegido, _candidatos = vuelo_proceso.elegir_sistema(sistema, None)
    elegido = dataclasses.replace(
        elegido,
        como="declarado por usted, solo para dibujar el visor: las fotos traen latitud y longitud",
    )

    avance(0.60, "Comprobando las fotos contra el .MRK")
    medida = _comprobar_el_mrk(fichas, eventos)
    ref_altura = _referencia_de_altura(medida)

    avance(0.70, "Armando la posición de cada foto")
    fotos: list[vuelo_sync.FotoSincronizada] = []
    for f, e, nombre in zip(fichas, eventos, nombres, strict=True):
        if not f.con_posicion:
            fotos.append(
                vuelo_sync.FotoSincronizada(
                    e, nombre, None, None, None, None, None, None, None,
                    "la foto no trae posición (ni en su XMP ni en su EXIF)",
                )
            )  # fmt: skip
            continue
        lat, lon, alt = f.lat, f.lon, f.alt_m
        aplicado = False
        if (
            aplicar_desfase
            and e.desfase_n_mm is not None
            and e.desfase_e_mm is not None
            and e.desfase_v_mm is not None
        ):
            dlat, dlon = vuelo_sync._mover(
                lat, alt or 0.0, e.desfase_n_mm / 1000, e.desfase_e_mm / 1000
            )
            lat, lon = lat + dlat, lon + dlon
            if alt is not None:
                alt -= e.desfase_v_mm / 1000  # V es positivo hacia abajo
            aplicado = True
        fotos.append(
            vuelo_sync.FotoSincronizada(
                disparo=e,
                nombre=nombre,
                lat=lat,
                lon=lon,
                alt_m=alt,
                sdn_m=f.rtk_desv_lat_m,
                sde_m=f.rtk_desv_lon_m,
                sdu_m=f.rtk_desv_alt_m,
                q=_codigo(f),
                motivo="",
                desfase_aplicado=aplicado,
                calidad_texto=f.calidad,
            )
        )

    avisos = _avisos(fichas, fotos, eventos, elegido, medida, aplicar_desfase)

    avance(0.80, "Escribiendo los entregables")
    resumen_sync = vuelo_sync.resumen(fotos)
    salida = vuelo_proceso.Entregables(
        avisos=avisos,
        fotos=fotos,
        geografico=elegido.geografico,
        referencia_de_altura=ref_altura,
    )
    salida.archivos["fotos.csv"] = vuelo_sync.a_csv(fotos, ref_altura).encode("utf-8")
    salida.archivos["fotos.geojson"] = vuelo_sync.a_geojson(fotos, elegido.geografico).encode(
        "utf-8"
    )
    if resumen_sync["con_posicion"]:
        salida.archivos["fotos.kml"] = vuelo_sync.a_kml(fotos, elegido.geografico).encode("utf-8")
    salida.archivos["calidad.md"] = _informe(
        elegido, fichas, fotos, resumen_sync, medida, ref_altura, aplicar_desfase, avisos,
    ).encode("utf-8")  # fmt: skip

    avance(0.92, "Preparando el visor")
    a_proyectado = Transformer.from_crs("EPSG:4326", f"EPSG:{elegido.epsg}", always_xy=True)
    salida.archivos["vuelo.json"] = json.dumps(
        vuelo_proceso._datos_del_visor(
            elegido, [], fotos, None, a_proyectado, ref_altura, nombres, aplicar_desfase
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    salida.resumen = {
        "sistema": elegido.nombre,
        "sistema_epsg": elegido.epsg,
        "sistema_como": elegido.como,
        "fotos": resumen_sync["fotos"],
        "con_posicion": resumen_sync["con_posicion"],
        "sin_posicion": resumen_sync["sin_posicion"],
        "puntos_de_trayectoria": 0,
        "contraste_maximo_mm": None,
        "desfase_aplicado": sum(1 for f in fotos if f.desfase_aplicado),
        "avisos": list(avisos),
        "trayectoria_de": "las fotos (posición RTK del dron)",
        "fotos_con_posicion_fija": sum(1 for f in fotos if f.con_posicion and f.q == 1),
        "referencia_de_altura": ref_altura,
        "comprobado_contra_el_mrk_mm": (
            round(medida["horizontal_maxima_mm"], 2)
            if medida["horizontal_maxima_mm"] is not None
            else None
        ),
    }
    avance(1.0, "Listo")
    return salida


# --- Avisos e informe ---------------------------------------------------------------------------


def _avisos(fichas, fotos, eventos, elegido, medida, aplicar_desfase) -> list[str]:
    avisos: list[str] = []
    sin = [f for f in fotos if not f.con_posicion]
    if sin:
        avisos.append(f"{len(sin)} foto(s) sin posición: {sin[0].motivo}.")
    avisos.extend(vuelo_proceso._avisos_de_calidad(fotos))
    if medida["pares_de_posicion"] == 0:
        avisos.append(
            "El .MRK no trae la posición de sus disparos: no se pudo comprobar que sea el de "
            "estas fotos."
        )
    if medida["pares_de_altura"] and not medida["altura_es_la_del_mrk"]:
        avisos.append(
            f"La altura del XMP difiere de la «Ellh» del .MRK hasta "
            f"{medida['altura_maxima_mm'] / 1000:.3f} m: no se afirma que sea elipsoidal."
        )
    if aplicar_desfase and any(e.desfase_n_mm is None for e in eventos):
        avisos.append(
            "El .MRK no trae el desfase de la antena en todos los disparos: esas posiciones son "
            "las de la antena."
        )
    datums = {f.datum for f in fichas if f.datum}
    if datums == {"WGS-84"} and elegido.geografico != "WGS84":
        avisos.append(
            f"Las fotos dicen «WGS-84» y usted declaró {elegido.nombre} ({elegido.geografico}): "
            "las posiciones se entregan tal como vienen, sin transformar de marco."
        )
    return avisos


def _informe(elegido, fichas, fotos, resumen, medida, ref_altura, desfase, avisos) -> str:
    n = len(fichas)
    lineas = ["# Vuelo de dron con RTK: cómo salió", ""]
    lineas += [
        "## De dónde sale la posición",
        "",
        f"- De las **{n} fotos**: la que el dron escribió en el XMP (`GpsLatitude`, "
        "`GpsLongitude`, `AbsoluteAltitude`); si una no trae XMP, la de su EXIF. No hay "
        "trayectoria ni PPK: nada se recalculó.",
    ]
    datums = Counter(f.datum or "no dice" for f in fichas)
    lineas.append(
        "- Datum que dicen las fotos en su EXIF: "
        + ", ".join(f"«{d}» ({c})" for d, c in datums.items())
        + ". El archivo **no dice en qué marco está la corrección RTK**: una red puede estar en "
        "SIRGAS o ITRF y el EXIF decir «WGS-84» igual. Se entrega tal como viene."
    )
    lineas += ["", "## Sistema de coordenadas", ""]
    lineas.append(f"- **{elegido.nombre}** (EPSG:{elegido.epsg}), {elegido.como}.")
    lineas.append(f"- Latitud y longitud en {elegido.geografico}.")
    lineas.append(f"- Altura: {ref_altura}.")

    lineas += ["", "## La altura", ""]
    if medida["pares_de_altura"]:
        lineas.append(
            f"- La `AbsoluteAltitude` del XMP se contrastó con la «Ellh» (elipsoidal) del `.MRK` "
            f"en "
            f"{medida['pares_de_altura']} fotos: la diferencia máxima es "
            f"{medida['altura_maxima_mm']:.2f} mm. "
            + (
                "**Coinciden**: es la altura elipsoidal."
                if medida["altura_es_la_del_mrk"]
                else "**No coinciden**: no se afirma que sea elipsoidal."
            )
        )
    else:
        lineas.append(
            "- El `.MRK` no trae su altura: **no hay con qué comprobar** de qué referencia es la "
            "del XMP, y no se afirma."
        )
    tipos = Counter(f.tipo_de_altura or "no dice" for f in fichas)
    lineas.append(
        "- `AltitudeType` del XMP: " + ", ".join(f"«{t}» ({c})" for t, c in tipos.items()) + "."
    )

    lineas += ["", "## Calidad de la posición", ""]
    banderas = Counter(f.rtk_bandera for f in fichas)
    lineas += ["| Bandera `RtkFlag` | Calidad | Fotos |", "| ---: | --- | ---: |"]
    for bandera, cuenta in sorted(banderas.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        etiqueta = "—" if bandera is None else str(bandera)
        lineas.append(f"| {etiqueta} | {ficha_foto.calidad_de_la_bandera(bandera)} | {cuenta} |")
    lineas += [
        "",
        "- La calidad sale de `RtkFlag`: 50 fija, 34 flotante, 16 simple (sin corrección RTK) y 0 "
        "sin solución, según lo que publica DJI. **Solo el 16 se ha visto en un archivo real**; un "
        "código que no está en la tabla se dice «no reconocida», y una foto sin bandera, «no "
        "informada».",
    ]
    estados = Counter(f.gps_estado or "no dice" for f in fichas)
    if len(banderas) == 1 and None not in banderas and set(banderas) != {50}:
        lineas.append(
            "- `GpsStatus` del XMP dice "
            + ", ".join(f"«{e}» ({c})" for e, c in estados.items())
            + ", pero **no es la calidad**: con una posición simple lo dice igual."
        )
    desv = [f.rtk_desv_lat_m for f in fichas if f.rtk_desv_lat_m is not None]
    if desv:
        lineas.append(
            f"- Desviaciones que informa el dron (`RtkStdLat`, `RtkStdLon`, `RtkStdHgt`, en "
            f"metros) "
            f"van en las columnas `sdn_m`, `sde_m` y `sdu_m`; la de latitud llega a "
            f"{max(desv):.3f} m."
        )

    lineas += ["", "## Las fotos", ""]
    lineas.append(
        f"- {resumen['fotos']} fotos; **{resumen['con_posicion']} con posición**"
        + (f" y {resumen['sin_posicion']} sin ella." if resumen["sin_posicion"] else ".")
    )
    if medida["pares_de_posicion"]:
        lineas.append(
            f"- Emparejadas con el `.MRK` por orden (hay tantos disparos como fotos). La posición "
            f"del XMP coincide con la del `.MRK` a {medida['horizontal_maxima_mm']:.2f} mm como "
            f"máximo en {medida['pares_de_posicion']} fotos: es la de la **antena**."
        )
    lineas.append(
        "- Posición de la **cámara** (con el desfase de la antena del `.MRK`)."
        if desfase
        else "- Posición de la **antena** (sin el desfase del `.MRK`)."
    )
    if avisos:
        lineas += ["", "## Avisos", ""] + [f"- {a}" for a in avisos]
    return "\n".join(lineas) + "\n"
