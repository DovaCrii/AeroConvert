"""«Vuelo de dron con PPK», el camino de Trimble: de tres archivos a las fotos con posición (F18.4).

Entra lo que sacó Trimble Business Center del vuelo (la trayectoria PPK y, si se tiene, las
posiciones de sus fotos) más el `.MRK` del dron, y sale **un conjunto de entregables** y **los
datos del visor** que dibuja el recorrido, los puntos y las fotos:

- `fotos.csv`: la posición de cada foto, lista para Pix4D, Metashape o QGIS;
- `fotos.geojson` y `fotos.kmz`: para abrirlas en un mapa;
- `calidad.md`: cómo salió, con el sistema de coordenadas **medido** y, si hay posiciones de
  Trimble, el contraste foto por foto contra ellas;
- `vuelo.json`: lo que dibuja el visor (trayectoria y fotos en metros, con su sistema).

## Lo que se garantiza

- **El sistema de coordenadas se mide o se declara, nunca se supone.** Con las posiciones de Trimble
  (que traen latitud y longitud junto a Este y Norte) se prueba cada candidato y se usa el que
  coincide; si se declara uno, **se comprueba** contra ellas y se rechaza si no coincide. Sin ellas
  solo se puede declarar, y se dice que **no hay con qué comprobarlo**.
- **Se contrasta contra Trimble.** Con sus posiciones delante, el informe dice a cuántos milímetros
  coincide cada componente; si pasa de `UMBRAL_DE_CONTRASTE_M`, **avisa**: el tiempo, el desfase o
  la trayectoria no son los de esas fotos.
- **Todo o nada con los nombres**: las fotos se emparejan con los disparos solo si hay **tantas como
  disparos**.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from apps.documents.composicion import ComposicionInvalida

from . import ficha_foto, vuelo_pos, vuelo_sync, vuelo_trimble

#: Con cuántos metros de diferencia contra las posiciones de Trimble se avisa. El vuelo real
#: (2 505 fotos) quedó a 0,9 mm; cinco milímetros ya es un tiempo o un desfase equivocado.
UMBRAL_DE_CONTRASTE_M = 0.005

#: Cuántos puntos de la trayectoria lleva el visor. Siete mil puntos a 5 Hz se dibujan igual de
#: bien con tres mil, y el archivo pesa la mitad.
PUNTOS_DEL_VISOR = 3000

EXTENSIONES_DE_FOTO = (".jpg", ".jpeg")

ETIQUETA_DE_CALIDAD = {"PPK": "PPK"}


@dataclass
class Entregables:
    archivos: dict[str, bytes] = field(default_factory=dict)
    resumen: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    fotos: list = field(default_factory=list)  # las `FotoSincronizada`, para F18.5
    geografico: str = ""  # el marco de la latitud y la longitud
    referencia_de_altura: str = ""


@dataclass(frozen=True)
class SistemaElegido:
    epsg: int
    nombre: str
    como: str  # medido, o declarado y comprobado, o declarado sin con qué comprobarlo
    equivalentes: tuple[str, ...] = ()

    @property
    def geografico(self) -> str:
        """El marco de la latitud y la longitud, para un KML o un GeoJSON."""
        if self.epsg in (5361, 5362):
            return "SIRGAS-Chile 2002"
        if self.epsg in (31978, 31979, 31980):
            return "SIRGAS 2000"
        return "WGS84"


def fichas_de_la_carpeta(carpeta: Path) -> dict[str, ficha_foto.FichaFoto]:
    """La ficha de cada JPG de la carpeta, por nombre en minúsculas. Solo lee las cabeceras.

    Una foto que no se puede leer **se omite** (aquí la ficha solo da la orientación del gimbal;
    quien la necesite entera, como `vuelo_rtk.leer_carpeta`, se detiene).
    """
    fichas = {}
    for nombre in nombres_de_fotos(carpeta):
        try:
            fichas[nombre.lower()] = ficha_foto.leer_ficha(carpeta / nombre)
        except ComposicionInvalida:
            continue
    return fichas


def nombres_de_fotos(carpeta: Path) -> list[str]:
    """Los JPG de una carpeta, ordenados por nombre (en un DJI, el nombre ordena por disparo)."""
    return sorted(
        (p.name for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES_DE_FOTO),
        key=str.lower,
    )


def elegir_sistema(
    declarado: str, referencia: list[vuelo_trimble.PosicionDeFoto] | None
) -> tuple[SistemaElegido, list[vuelo_trimble.Candidato]]:
    """El sistema con que se leen Este y Norte. `declarado` es `medir` o un código EPSG."""
    con_ll = [r for r in (referencia or []) if r.lat is not None]
    candidatos = vuelo_trimble.identificar_sistema(con_ll) if con_ll else []

    if declarado in ("", "medir"):
        if not candidatos:
            raise ComposicionInvalida(
                "No hay con qué medir el sistema de las coordenadas: falta el archivo de "
                "posiciones de las fotos que trae latitud y longitud («… export_extended»). "
                "Súbalo, o declare el sistema a mano."
            )
        coinciden = [c for c in candidatos if c.coincide]
        if not coinciden:
            raise ComposicionInvalida(vuelo_trimble.veredicto(candidatos))
        usables = [c for c in coinciden if c.usable]
        if not usables:
            raise ComposicionInvalida(
                f"Las coordenadas están en {coinciden[0].nombre}, un sistema antiguo: pasarlas a "
                "latitud y longitud necesita una transformación de datum que no se adivina."
            )
        # Los que coinciden dan lo mismo: el orden por error sería ruido de submilímetro. Se usa el
        # de la tabla (WGS 84, SIRGAS-Chile, SIRGAS 2000), que es estable.
        orden = list(vuelo_trimble.CANDIDATOS)
        usables.sort(key=lambda c: orden.index(c.epsg))
        mejor = usables[0]
        otros = tuple(c.nombre for c in usables[1:])
        return SistemaElegido(
            mejor.epsg, mejor.nombre, "medido contra la latitud y la longitud de Trimble", otros
        ), candidatos

    try:
        epsg = int(declarado)
    except ValueError as fallo:
        raise ComposicionInvalida(f"«{declarado}» no es un código EPSG.") from fallo
    if epsg not in vuelo_trimble.CANDIDATOS:
        raise ComposicionInvalida(f"EPSG:{epsg} no es uno de los sistemas que se saben leer aquí.")
    if epsg not in vuelo_trimble.USABLES:
        raise ComposicionInvalida(
            f"{vuelo_trimble.CANDIDATOS[epsg]} es un sistema antiguo: haría falta una "
            "transformación de datum que no se adivina."
        )
    if candidatos:
        este = next(c for c in candidatos if c.epsg == epsg)
        if not este.coincide:
            raise ComposicionInvalida(
                f"Declaró {este.nombre}, pero las coordenadas de Trimble quedan a "
                f"{este.error_medio_m:.1f} m de la latitud y la longitud que traen. "
                + vuelo_trimble.veredicto(candidatos)
            )
        return SistemaElegido(
            epsg, este.nombre, "declarado y comprobado contra Trimble"
        ), candidatos
    return (
        SistemaElegido(
            epsg,
            vuelo_trimble.CANDIDATOS[epsg],
            "declarado; no hay con qué comprobarlo (sin las posiciones de Trimble)",
        ),
        candidatos,
    )


def _leer_disparos(datos: bytes, nombre: str) -> list[vuelo_sync.Disparo]:
    texto = vuelo_trimble._decodificar(datos)
    if nombre.lower().endswith(".mrk"):
        return vuelo_sync.leer_mrk(texto)
    return vuelo_sync.leer_lista_de_tiempos(texto)


def _contraste(fotos, referencia, transformador) -> dict | None:
    """Foto por foto, las nuestras contra las de Trimble, en metros (norte, este, altura)."""
    if not referencia or len(referencia) != len(fotos):
        return None
    dn, de, du = [], [], []
    for f, r in zip(fotos, referencia, strict=True):
        if not f.con_posicion:
            continue
        este, norte = transformador.transform(f.lon, f.lat)
        dn.append(r.norte - norte)
        de.append(r.este - este)
        du.append(r.altura - f.alt_m)
    if not dn:
        return None

    def datos(v):
        return {
            "media_mm": statistics.mean(v) * 1000,
            "desviacion_mm": statistics.pstdev(v) * 1000,
            "maximo_mm": max(abs(x) for x in v) * 1000,
        }

    return {"fotos": len(dn), "norte": datos(dn), "este": datos(de), "altura": datos(du)}


def procesar(
    *,
    trayectoria: bytes | None = None,
    disparos: bytes,
    nombre_de_disparos: str,
    referencia: bytes | None = None,
    nombres_en_carpeta: list[str] | None = None,
    escala_de_tiempo: str | None = None,
    sistema: str = "medir",
    aplicar_desfase: bool = True,
    progreso: Callable[[float, str], None] | None = None,
    trayectoria_ppk: vuelo_pos.Trayectoria | None = None,
    fichas: dict[str, ficha_foto.FichaFoto] | None = None,
) -> Entregables:
    """Todo el proceso. Levanta `ComposicionInvalida` con el motivo, y no deja nada a medias.

    La trayectoria es **una de dos**: el CSV que exportó Trimble (`trayectoria` y su
    `escala_de_tiempo`, que no se supone) o la que calculó RTKLIB (`trayectoria_ppk`, ya en
    latitud, longitud y altura elipsoidal, y en GPST porque `vuelo_pos.leer` no admite otra). Con
    la de RTKLIB la calidad de cada foto sale de la de sus épocas, y `sistema` solo dice en qué
    se proyectan los puntos del visor.

    `fichas` (nombre de la foto en minúsculas → su ficha, leída de la carpeta) da la orientación del
    gimbal para las columnas del CSV (F18.10); sin ella se toma del archivo de Trimble si lo trae.
    """
    if (trayectoria is None) == (trayectoria_ppk is None):
        raise ComposicionInvalida(
            "Hace falta una trayectoria, y solo una: la que exportó Trimble o la que calculó "
            "RTKLIB."
        )
    if trayectoria_ppk is None and not escala_de_tiempo:
        raise ComposicionInvalida("Falta la escala de tiempo de la trayectoria: no se supone.")

    def avance(fraccion: float, etiqueta: str) -> None:
        if progreso is not None:
            progreso(fraccion, etiqueta)

    from pyproj import Transformer

    avance(0.02, "Leyendo los disparos de la cámara")
    eventos = _leer_disparos(disparos, nombre_de_disparos)

    avance(0.10, "Leyendo la trayectoria")
    puntos = (
        vuelo_trimble.leer_trayectoria(trayectoria, escala_de_tiempo=escala_de_tiempo)
        if trayectoria_ppk is None
        else None
    )

    avance(0.22, "Leyendo las posiciones de las fotos de Trimble" if referencia else "Preparando")
    ref = vuelo_trimble.leer_posiciones_por_foto(referencia) if referencia else None

    avance(0.30, "Midiendo el sistema de coordenadas")
    elegido, candidatos = elegir_sistema(sistema, ref)
    avisos_de_escala: list[str] = []
    if ref is None and trayectoria_ppk is None:
        # La escala de tiempo no se puede comprobar sin las posiciones de Trimble: con una
        # trayectoria en UTC leída como GPST las fotos quedan 18 s corridas (cientos de metros) y
        # el resultado parece correcto. Se dice en el informe y en el aviso del trabajo.
        avisos_de_escala.append(
            f"Sin las posiciones de Trimble no hay con qué comprobar que la hora de la "
            f"trayectoria sea {escala_de_tiempo}: se leyó como usted la indicó. Si no es esa, "
            "las fotos quedan corridas."
        )

    # Los nombres: los de Trimble si los hay; si no, los de la carpeta. Solo con tantos como
    # disparos, y se dice cuál de las dos fuentes se usó.
    avisos: list[str] = list(avisos_de_escala)
    nombres: list[str] | None = None
    de_donde = ""
    if ref is not None:
        nombres = vuelo_sync.emparejar(eventos, [r.nombre for r in ref])
        de_donde = "el archivo de Trimble"
        if nombres_en_carpeta is not None:
            faltan = {n.lower() for n in nombres} - {n.lower() for n in nombres_en_carpeta}
            if faltan:
                avisos.append(
                    f"{len(faltan)} de las fotos de Trimble no están en la carpeta de fotos "
                    "(no tendrán miniatura)."
                )
    elif nombres_en_carpeta is not None:
        nombres = vuelo_sync.emparejar(eventos, nombres_en_carpeta)
        de_donde = "la carpeta de fotos, por orden de nombre"

    a_proyectado = Transformer.from_crs("EPSG:4326", f"EPSG:{elegido.epsg}", always_xy=True)
    if trayectoria_ppk is None:
        avance(0.42, "Pasando la trayectoria a latitud y longitud")
        tray = vuelo_trimble.a_trayectoria(puntos, elegido.epsg)
    else:
        avance(0.42, "Proyectando la trayectoria de RTKLIB para el visor")
        tray = trayectoria_ppk
        puntos = _puntos_proyectados(tray, a_proyectado)
    if tray.huecos():
        avisos.append(
            f"La trayectoria tiene {len(tray.huecos())} hueco(s): las fotos que caen en ellos "
            "quedan sin posición."
        )

    avance(0.55, "Sincronizando las fotos con la trayectoria")
    fotos = vuelo_sync.sincronizar(tray, eventos, nombres, aplicar_desfase=aplicar_desfase)
    sin = [f for f in fotos if not f.con_posicion]
    if sin:
        avisos.append(f"{len(sin)} foto(s) sin posición: {sin[0].motivo}.")
    if aplicar_desfase and any(d.desfase_n_mm is None for d in eventos):
        avisos.append(
            "El archivo de disparos no trae el desfase de la antena: las posiciones son las "
            "de la antena."
        )

    avance(0.68, "Contrastando con las posiciones de Trimble")
    contraste = _contraste(fotos, ref, a_proyectado)
    # La altura de Trimble no es la elipsoidal de RTKLIB (en el vuelo real, 35 m de diferencia):
    # con RTKLIB solo el plano decide si coinciden, y la altura se muestra sin juzgarla.
    componentes = ("norte", "este") if trayectoria_ppk is not None else ("norte", "este", "altura")
    if contraste:
        peor = max(contraste[c]["maximo_mm"] for c in componentes)
        if peor / 1000 > UMBRAL_DE_CONTRASTE_M:
            revisar = (
                "el desfase de la antena y que la trayectoria sea la de este vuelo."
                if trayectoria_ppk is not None
                else "la escala de tiempo, el desfase de la antena y que la trayectoria sea la "
                "de este vuelo."
            )
            avisos.append(
                f"Las posiciones no coinciden con las de Trimble: la diferencia llega a "
                f"{peor:.1f} mm. Revise {revisar}"
            )
    if trayectoria_ppk is not None:
        avisos.extend(_avisos_de_calidad(fotos))

    orientaciones, orientacion = orientaciones_de(fotos, fichas, ref)
    avisos.extend(orientacion.avisos)

    avance(0.80, "Escribiendo los entregables")
    resumen_sync = vuelo_sync.resumen(fotos)
    salida = Entregables(
        avisos=avisos,
        fotos=fotos,
        geografico=elegido.geografico,
        referencia_de_altura=tray.referencia_de_altura,
    )
    ref_altura = tray.referencia_de_altura
    salida.archivos["fotos.csv"] = vuelo_sync.a_csv(fotos, ref_altura, orientaciones).encode(
        "utf-8"
    )
    salida.archivos["fotos.geojson"] = vuelo_sync.a_geojson(fotos, elegido.geografico).encode(
        "utf-8"
    )
    if resumen_sync["con_posicion"]:
        salida.archivos["fotos.kml"] = vuelo_sync.a_kml(fotos, elegido.geografico).encode("utf-8")
    salida.archivos["calidad.md"] = _informe(
        elegido, candidatos, tray, fotos, resumen_sync, contraste, avisos, de_donde, ref_altura,
        aplicar_desfase, ref, trayectoria_ppk is not None, orientacion,
    ).encode("utf-8")  # fmt: skip

    avance(0.92, "Preparando el visor")
    salida.archivos["vuelo.json"] = json.dumps(
        # Con RTKLIB la calidad de cada foto es la suya, no la que dice Trimble (`ref` es solo para
        # contrastar): por eso al visor no se le pasa.
        _datos_del_visor(
            elegido,
            puntos,
            fotos,
            ref if trayectoria_ppk is None else None,
            a_proyectado,
            ref_altura,
            nombres_en_carpeta,
            aplicar_desfase,
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
        "puntos_de_trayectoria": len(puntos),
        "contraste_maximo_mm": (
            round(max(contraste[c]["maximo_mm"] for c in componentes), 2) if contraste else None
        ),
        "desfase_aplicado": sum(1 for f in fotos if f.desfase_aplicado),
        "con_orientacion": orientacion.con_orientacion,
        "orientacion_de": orientacion.de_donde,
        # La lista, no la cuenta: el corredor la recorre para dejar cada aviso en la bitácora.
        "avisos": list(avisos),
    }
    if trayectoria_ppk is not None:
        salida.resumen["trayectoria_de"] = "RTKLIB (PPK)"
        salida.resumen["fotos_con_posicion_fija"] = sum(
            1 for f in fotos if f.con_posicion and f.q == 1
        )
    avance(1.0, "Listo")
    return salida


# --- La orientación de la cámara (F18.10) -----------------------------------------------------


@dataclass
class ResumenDeOrientacion:
    de_las_fotos: int = 0
    de_trimble: int = 0
    total: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def con_orientacion(self) -> int:
        return self.de_las_fotos + self.de_trimble

    @property
    def de_donde(self) -> str:
        partes = []
        if self.de_las_fotos:
            partes.append("el XMP de las fotos")
        if self.de_trimble:
            partes.append("el archivo de Trimble")
        return " y ".join(partes)


def orientaciones_de(
    fotos, fichas: dict[str, ficha_foto.FichaFoto] | None, ref
) -> tuple[dict[str, vuelo_sync.Orientacion], ResumenDeOrientacion]:
    """La guiñada, el cabeceo y el alabeo del gimbal de cada foto, y de dónde salió cada uno.

    **El XMP de la foto manda**: es el dato del propio dron. El archivo de Trimble es el respaldo
    (trae las mismas columnas, y se comprobó que coinciden). Una foto que no está en ninguno de los
    dos queda sin orientación: vacía en el CSV, no en cero.
    """
    de_trimble = {r.nombre.lower(): r for r in (ref or [])}
    resultado: dict[str, vuelo_sync.Orientacion] = {}
    resumen = ResumenDeOrientacion(total=len(fotos))
    for f in fotos:
        clave = f.nombre.lower()
        ficha = (fichas or {}).get(clave)
        fuente = "foto"
        if (ficha is None or not ficha.con_orientacion) and clave in de_trimble:
            ficha = ficha_foto.ficha_de_trimble(f.nombre, de_trimble[clave].extras)
            fuente = "trimble"
        if ficha is not None and ficha.con_orientacion:
            resultado[clave] = (
                ficha.gimbal_guinada_deg,
                ficha.gimbal_cabeceo_deg,
                ficha.gimbal_alabeo_deg,
            )
            if fuente == "foto":
                resumen.de_las_fotos += 1
            else:
                resumen.de_trimble += 1
    sin = resumen.total - resumen.con_orientacion
    if sin and resumen.con_orientacion:
        resumen.avisos.append(
            f"{sin} foto(s) quedan sin orientación de la cámara: su XMP no la trae y Trimble "
            "tampoco."
        )
    return resultado, resumen


def _lineas_de_orientacion(orientacion: ResumenDeOrientacion) -> list[str]:
    lineas = ["", "## Orientación de la cámara", ""]
    if not orientacion.con_orientacion:
        lineas.append(
            "- Las columnas `gimbal_guinada_deg`, `gimbal_cabeceo_deg` y `gimbal_alabeo_deg` de "
            "`fotos.csv` van **vacías**: no hay de dónde leerlas. Elija la carpeta de fotos (su "
            "XMP de DJI las trae) o suba el archivo ampliado de Trimble."
        )
        return lineas
    lineas += [
        f"- Columnas `gimbal_guinada_deg`, `gimbal_cabeceo_deg` y `gimbal_alabeo_deg` de "
        f"`fotos.csv`: {orientacion.con_orientacion} de {orientacion.total} fotos, leídas de "
        f"{orientacion.de_donde}.",
        "- Es la convención de DJI, **sin convertir**: cabeceo −90° = cámara mirando al nadir, "
        "0° = "
        "horizontal; guiñada en grados respecto del norte. Los ejes de Metashape y de Pix4D "
        "tienen su propia convención: al importar, mapee las columnas y compruebe una cámara.",
        "- El XMP no dice si ese norte es el magnético o el geográfico: no se afirma uno.",
    ]
    return lineas


# --- El informe -------------------------------------------------------------------------------


def _puntos_proyectados(tray: vuelo_pos.Trayectoria, a_proyectado) -> list:
    """Las épocas de RTKLIB en Este y Norte del sistema elegido: lo que dibuja el visor."""
    puntos = []
    for e in tray.epocas:
        este, norte = a_proyectado.transform(e.lon, e.lat)
        puntos.append(vuelo_trimble.PuntoDeTrayectoria("", este, norte, e.alt_m, e.t_gps_s))
    return puntos


def _porcentajes(tray: vuelo_pos.Trayectoria) -> dict[str, float]:
    return {
        vuelo_pos.CALIDADES.get(q, f"código {q}"): tray.porcentaje(q)
        for q in sorted({e.q for e in tray.epocas})
    }


def _calidades_de_las_fotos(fotos) -> dict[str, int]:
    cuentas: dict[str, int] = {}
    for f in fotos:
        if f.con_posicion:
            nombre = f.calidad
            cuentas[nombre] = cuentas.get(nombre, 0) + 1
    return cuentas


def _avisos_de_calidad(fotos) -> list[str]:
    """Con RTKLIB la calidad **sí** se informa, y lo que no es fijo se dice."""
    cuentas = _calidades_de_las_fotos(fotos)
    no_fijas = sum(n for nombre, n in cuentas.items() if nombre != "fija")
    if not no_fijas:
        return []
    detalle = ", ".join(f"{n} {nombre}" for nombre, n in cuentas.items() if nombre != "fija")
    return [
        f"{no_fijas} foto(s) no tienen posición fija ({detalle}): su error es mayor que el de "
        "centímetro de una solución fija."
    ]


def _informe(
    elegido,
    candidatos,
    tray,
    fotos,
    resumen,
    contraste,
    avisos,
    de_donde,
    ref_altura,
    desfase,
    ref,
    desde_ppk=False,
    orientacion=None,
):
    lineas = ["# Vuelo de dron: cómo salió", ""]
    lineas += [
        "## Sistema de coordenadas",
        "",
        f"- **{elegido.nombre}** (EPSG:{elegido.epsg}), {elegido.como}.",
    ]
    if elegido.equivalentes:
        lineas.append(f"- Dan lo mismo, a nivel de milímetros: {', '.join(elegido.equivalentes)}.")
    lineas.append(f"- Latitud y longitud en {elegido.geografico}.")
    lineas.append(f"- Altura: {ref_altura}.")
    if candidatos:
        lineas += ["", "Lo que se probó contra la latitud y la longitud de Trimble:", ""]
        lineas += ["| Sistema | Diferencia media |", "| --- | ---: |"]
        for c in candidatos[:8]:
            marca = " ← coincide" if c.coincide else ""
            lineas.append(
                f"| {c.nombre} | {c.error_medio_m * 1000:,.1f} mm{marca} |".replace(",", " ")
            )
    lineas += ["", "## La trayectoria", ""]
    lineas.append(
        f"- {tray.n} puntos, uno cada {tray.intervalo_tipico_s:.2f} s "
        f"({tray.epocas[-1].t_gps_s - tray.epocas[0].t_gps_s:.0f} s en total)."
    )
    huecos = tray.huecos()
    lineas.append(f"- Huecos: {len(huecos)}." if huecos else "- Sin huecos.")
    if desde_ppk:
        lineas.append(
            "- Calculada con **RTKLIB** (PPK, hora GPST): la calidad de cada punto es la que "
            "informa RTKLIB."
        )
        lineas.append(
            "- Calidad de los puntos: "
            + ", ".join(f"{p:.1f} % {n}" for n, p in _porcentajes(tray).items())
            + "."
        )
    else:
        lineas.append("- La calidad de cada punto **no la informa** el archivo de Trimble.")

    lineas += ["", "## Las fotos", ""]
    lineas.append(
        f"- {resumen['fotos']} disparos; **{resumen['con_posicion']} con posición**"
        + (f" y {resumen['sin_posicion']} sin ella." if resumen["sin_posicion"] else ".")
    )
    if de_donde:
        lineas.append(f"- Los nombres salen de {de_donde}.")
    if desde_ppk:
        cuentas = _calidades_de_las_fotos(fotos)
        if cuentas:
            lineas.append(
                "- Calidad de las fotos (la peor de las dos épocas vecinas): "
                + ", ".join(f"{n} {nombre}" for nombre, n in cuentas.items())
                + "."
            )
    elif ref:
        calidades = sorted({r.calidad for r in ref if r.calidad})
        if calidades:
            lineas.append(f"- Calidad según Trimble: {', '.join(calidades)}.")
    lineas.append(
        "- Posición de la **cámara** (con el desfase de la antena del `.MRK`)."
        if desfase
        else "- Posición de la **antena** (sin el desfase del `.MRK`)."
    )

    if orientacion is not None:
        lineas += _lineas_de_orientacion(orientacion)

    lineas += ["", "## Contraste con las posiciones de Trimble", ""]
    if contraste:
        lineas += [
            f"Sobre {contraste['fotos']} fotos, nuestra posición contra la de Trimble:",
            "",
            "| Componente | Media | Desviación | Peor caso |",
            "| --- | ---: | ---: | ---: |",
        ]
        for nombre, clave in (("Norte", "norte"), ("Este", "este"), ("Altura", "altura")):
            d = contraste[clave]
            lineas.append(
                f"| {nombre} | {d['media_mm']:+.2f} mm | {d['desviacion_mm']:.2f} mm | "
                f"{d['maximo_mm']:.2f} mm |"
            )
        if desde_ppk:
            lineas += [
                "",
                "La altura de RTKLIB es **elipsoidal** y la de Trimble no lo es (suele ser sobre "
                "el nivel del mar): una diferencia de decenas de metros ahí es la ondulación del "
                "geoide, no un error. Solo el plano decide si coinciden.",
            ]
    else:
        lineas.append(
            "No se hizo: sin las posiciones de las fotos de Trimble no hay contra qué contrastar."
        )
    if avisos:
        lineas += ["", "## Avisos", ""] + [f"- {a}" for a in avisos]
    return "\n".join(lineas) + "\n"


# --- Los datos del visor ----------------------------------------------------------------------


def _datos_del_visor(
    elegido,
    puntos,
    fotos,
    ref,
    a_proyectado,
    ref_altura,
    nombres_en_carpeta,
    desfase_aplicado=False,
):
    """Lo que dibuja el visor. Sin `puntos` (un vuelo RTK no tiene trayectoria) no se dibuja
    ninguna línea: unir las fotos en orden sería inventar un recorrido."""
    proyectadas = {
        i: a_proyectado.transform(f.lon, f.lat) for i, f in enumerate(fotos) if f.con_posicion
    }
    este0 = round(min([p.este for p in puntos] or [e for e, _n in proyectadas.values()]), -2)
    norte0 = round(min([p.norte for p in puntos] or [n for _e, n in proyectadas.values()]), -2)
    paso = max(1, math.ceil(len(puntos) / PUNTOS_DEL_VISOR))
    elegidos = puntos[::paso]
    if elegidos and elegidos[-1] is not puntos[-1]:
        elegidos.append(puntos[-1])
    # nombre (en minúsculas) -> el nombre **real** en la carpeta: en Linux `dji.jpg` y `DJI.JPG` no
    # son el mismo archivo, y la miniatura se pide por el nombre que de verdad existe.
    en_carpeta = {n.lower(): n for n in (nombres_en_carpeta or [])}

    lista = []
    for i, f in enumerate(fotos):
        if not f.con_posicion:
            lista.append({"n": i + 1, "nombre": f.nombre, "motivo": f.motivo})
            continue
        este, norte = proyectadas[i]
        calidad = (ref[i].calidad if ref and ref[i].calidad else "") or f.calidad
        lista.append(
            {
                "n": i + 1,
                "nombre": f.nombre,
                "x": round(este - este0, 3),
                "y": round(norte - norte0, 3),
                "lat": round(f.lat, 9),
                "lon": round(f.lon, 9),
                "alt": round(f.alt_m, 3),
                "calidad": calidad,
                "t_gps_s": round(f.disparo.t_gps_s, 3),
                "miniatura": f.nombre.lower() in en_carpeta,
                # Solo si el archivo existe en la carpeta: un nombre hostil del CSV (`../x.jpg`) no
                # está ahí, así que nunca llega a ser una ruta.
                **(
                    {"archivo": en_carpeta[f.nombre.lower()]}
                    if f.nombre.lower() in en_carpeta
                    else {}
                ),
                **_lo_que_trae_el_disparo(f, desfase_aplicado),
                # Si la foto no está en la carpeta pero Trimble sí la describe, la ficha del
                # visor sale de aquí (F18.9). Si está en la carpeta, se lee del archivo.
                **(
                    {"ficha": ficha_foto.ficha_de_trimble(f.nombre, ref[i].extras).a_dict()}
                    if ref and ref[i].extras and f.nombre.lower() not in en_carpeta
                    else {}
                ),
            }
        )
    return {
        "version": 1,
        "sistema": {
            "epsg": elegido.epsg,
            "nombre": elegido.nombre,
            "como": elegido.como,
            "geografico": elegido.geografico,
            "equivalentes": list(elegido.equivalentes),
        },
        "altura": ref_altura,
        "origen": {"este": este0, "norte": norte0},
        "trayectoria_total": len(puntos),
        "trayectoria": [[round(p.este - este0, 2), round(p.norte - norte0, 2)] for p in elegidos],
        "fotos": lista,
    }


def _lo_que_trae_el_disparo(f, desfase_aplicado: bool) -> dict:
    """El desfase antena a cámara del `.MRK` de esta foto, para la ficha del visor."""
    d = f.disparo
    if d.desfase_n_mm is None or d.desfase_e_mm is None or d.desfase_v_mm is None:
        return {}
    return {
        "desfase": {
            "n_mm": d.desfase_n_mm,
            "e_mm": d.desfase_e_mm,
            "v_mm": d.desfase_v_mm,
            "aplicado": bool(f.desfase_aplicado and desfase_aplicado),
        }
    }
