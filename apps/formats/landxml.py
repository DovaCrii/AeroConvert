"""Leer un LandXML: qué trae dentro, sin abrirlo en Civil 3D.

Es el archivo que manda el proyectista. Trae una de tres cosas, o varias a la vez:

- **`CgPoints`** — grupos de puntos COGO. Es lo que `apps/vector/landxml.py` escribe, y lo
  único que hoy se sabe **convertir** de vuelta.
- **`Surface`** — superficies TIN: una nube de puntos y las caras del triangulado.
- **`Alignment`** — alineamientos: ejes de camino con sus curvas y su rasante.

## Lo que este módulo hace, y lo que a propósito no

Cuenta e identifica las tres. Contar `<Surface>` y `<Alignment>` es inequívoco: son
etiquetas, no interpretación. Así que aunque una superficie no se pueda convertir todavía,
soltar el archivo dice **qué hay dentro** — que es la mitad del valor del producto.

**Los puntos sí se leen enteros; las superficies y los alineamientos, no.** No es pereza:
no hay ningún LandXML de verdad con el que contrastar el resultado. Se buscó en la unidad
entera y no hay ninguno. Escribir un lector de TIN contra la especificación y validarlo
contra nuestro propio lector sería el código dándose la razón, y un triangulado mal leído
produce una superficie plausible y equivocada. Cuando aparezca un archivo real —de Civil 3D,
de Metashape, de quien sea— se hace y se contrasta contra él.

## El XML viene de fuera

Lo escribió otro programa y lo mandó otra oficina, así que se analiza con `defusedxml`: el
`xml.etree` de la biblioteca estándar sigue siendo vulnerable a la expansión de entidades, y
esto corre **antes** de que nadie haya decidido nada sobre el archivo.

Y se recorre con `iterparse`, liberando cada elemento: un LandXML de una superficie de obra
son decenas de megabytes, y mirar qué trae dentro no puede costar más memoria que
convertirlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from defusedxml.ElementTree import ParseError, iterparse

from .puntos import Punto

#: Cuántos puntos se guardan para dibujar la vista previa. El mismo tope que en las libretas.
MUESTRA_MAXIMA = 3_000


class NoEsLandXml(Exception):
    """El archivo no es un LandXML, o está roto."""


@dataclass(frozen=True)
class Superficie:
    nombre: str
    puntos: int
    caras: int


@dataclass(frozen=True)
class Alineamiento:
    nombre: str
    #: Lo que declara el atributo `length`. En metros, porque las `Units` lo son.
    longitud_m: float


@dataclass(frozen=True)
class CabeceraLandXml:
    """Lo que trae dentro un LandXML."""

    version: str = ""
    #: El EPSG que declara `<CoordinateSystem>`, si lo declara.
    epsg: str = ""
    nombre_crs: str = ""
    #: Quién lo escribió. Un `Application name="Civil 3D"` dice mucho de qué esperar.
    aplicacion: str = ""
    #: Nombres de los grupos de puntos, en orden.
    grupos_de_puntos: tuple[str, ...] = ()
    puntos_leidos: int = 0
    superficies: tuple[Superficie, ...] = ()
    alineamientos: tuple[Alineamiento, ...] = ()
    #: Una muestra de los puntos, para dibujar. Mismos nombres de atributo que
    #: `CabeceraPuntos` para que `vista_previa.dibujo_de_puntos` sirva igual.
    muestra: tuple[Punto, ...] = ()
    minimo: tuple[float, float, float] = (0.0, 0.0, 0.0)
    maximo: tuple[float, float, float] = (0.0, 0.0, 0.0)
    avisos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tiene_puntos(self) -> bool:
        return self.puntos_leidos > 0

    @property
    def solo_trae_lo_que_no_se_convierte(self) -> bool:
        """`True` si hay superficies o alineamientos y ni un punto.

        Es el caso que hay que decir en voz alta: el archivo se reconoce, se sabe qué trae,
        y aun así no hay conversión que ofrecer.
        """
        return not self.tiene_puntos and bool(self.superficies or self.alineamientos)

    @property
    def extension_m(self) -> tuple[float, float, float]:
        return (
            self.maximo[0] - self.minimo[0],
            self.maximo[1] - self.minimo[1],
            self.maximo[2] - self.minimo[2],
        )

    @property
    def resumen(self) -> str:
        """Una línea con lo que trae. Es lo que va en la ficha."""
        partes = []
        if self.puntos_leidos:
            partes.append(f"{self.puntos_leidos} puntos")
        if self.superficies:
            caras = sum(s.caras for s in self.superficies)
            detalle = f" con {caras} caras" if caras else ""
            partes.append(f"{len(self.superficies)} superficie(s){detalle}")
        if self.alineamientos:
            partes.append(f"{len(self.alineamientos)} alineamiento(s)")
        return " · ".join(partes) or "sin puntos, superficies ni alineamientos"


def _local(etiqueta: str) -> str:
    """`{urn}CgPoint` -> `CgPoint`. LandXML siempre trae espacio de nombres; casi siempre."""
    return etiqueta.rpartition("}")[2]


def _numero(texto: str | None) -> float | None:
    if not texto:
        return None
    try:
        return float(texto.strip())
    except ValueError:
        return None


def _punto_de(elemento, indice: int) -> Punto | None:
    """Un `<CgPoint>` en un `Punto`.

    **El contenido es norte, este, cota, en ese orden**, separado por espacios. Es la misma
    trampa que en PNEZD y en el mismo sitio, así que va con su prueba.
    """
    partes = (elemento.text or "").split()
    if len(partes) < 3:
        return None

    norte, este, cota = (_numero(p) for p in partes[:3])
    if norte is None or este is None or cota is None:
        return None

    return Punto(
        identificador=(elemento.get("name") or str(indice)).strip(),
        norte_m=norte,
        este_m=este,
        cota_m=cota,
        descripcion=(elemento.get("code") or elemento.get("desc") or "").strip(),
    )


def leer_cabecera(ruta: str | Path) -> CabeceraLandXml:
    """Recorre el archivo y devuelve qué trae dentro."""
    ruta = Path(ruta)

    version = epsg = nombre_crs = aplicacion = ""
    grupos: list[str] = []
    superficies: list[Superficie] = []
    alineamientos: list[Alineamiento] = []
    puntos: list[Punto] = []
    total_puntos = 0
    avisos: list[str] = []

    # Para contar los hijos de la superficie que se está recorriendo.
    superficie_actual: str | None = None
    puntos_de_superficie = 0
    caras_de_superficie = 0
    es_landxml = False

    try:
        # **Los dos eventos, y hay que distinguirlos.** Con `start` y `end` cada elemento
        # llega dos veces: contar sin mirar el evento daria el doble de caras en cada
        # superficie, y con una cifra plausible que nadie comprobaria.
        #
        # `start` hace falta para saber cuando se **entra** en una superficie, porque sus
        # vertices hay que contarlos segun pasan; esperar al `end` obligaria a tener la
        # superficie entera en memoria, que es justo lo que se quiere evitar.
        for evento, elemento in iterparse(str(ruta), events=("start", "end")):
            etiqueta = _local(elemento.tag)

            if etiqueta == "LandXML":
                es_landxml = True
                version = version or (elemento.get("version") or "")
                continue

            if etiqueta == "Surface":
                if evento == "start":
                    superficie_actual = (elemento.get("name") or "").strip() or "sin nombre"
                    puntos_de_superficie = caras_de_superficie = 0
                else:
                    superficies.append(
                        Superficie(
                            superficie_actual or "sin nombre",
                            puntos_de_superficie,
                            caras_de_superficie,
                        )
                    )
                    superficie_actual = None
                    elemento.clear()
                continue

            if evento == "start":
                # Del resto solo interesa el cierre: al abrir, ni el texto ni los hijos
                # estan leidos todavia.
                continue

            if superficie_actual is not None:
                # Dentro de una superficie: los `P` son sus vértices y los `F` sus caras.
                # **No se convierten en puntos del archivo**: son la malla, no topografía.
                if etiqueta == "P":
                    puntos_de_superficie += 1
                elif etiqueta == "F":
                    caras_de_superficie += 1
                elemento.clear()
                continue

            if etiqueta == "CoordinateSystem":
                epsg = epsg or (elemento.get("epsgCode") or "").strip()
                nombre_crs = nombre_crs or (elemento.get("name") or "").strip()
            elif etiqueta == "Application":
                aplicacion = aplicacion or (elemento.get("name") or "").strip()
            elif etiqueta == "CgPoints":
                nombre = (elemento.get("name") or "").strip()
                if nombre and nombre not in grupos:
                    grupos.append(nombre)
            elif etiqueta == "CgPoint":
                total_puntos += 1
                punto = _punto_de(elemento, total_puntos)
                if punto is None:
                    avisos.append("Hay puntos sin coordenadas legibles; se ignoran.")
                elif len(puntos) < MUESTRA_MAXIMA:
                    puntos.append(punto)
            elif etiqueta == "Alignment":
                alineamientos.append(
                    Alineamiento(
                        nombre=(elemento.get("name") or "").strip() or "sin nombre",
                        longitud_m=_numero(elemento.get("length")) or 0.0,
                    )
                )

            elemento.clear()
    except ParseError as fallo:
        raise NoEsLandXml(f"El XML no esta bien formado: {fallo}") from fallo
    except OSError as fallo:  # pragma: no cover - lo filtra la inspección antes
        raise NoEsLandXml(str(fallo)) from fallo

    if not es_landxml:
        raise NoEsLandXml("El archivo es XML pero su raiz no es <LandXML>.")

    limites = _limites(puntos)
    return CabeceraLandXml(
        version=version,
        epsg=epsg,
        nombre_crs=nombre_crs,
        aplicacion=aplicacion,
        grupos_de_puntos=tuple(grupos),
        puntos_leidos=total_puntos,
        superficies=tuple(superficies),
        alineamientos=tuple(alineamientos),
        muestra=tuple(puntos),
        minimo=limites[0],
        maximo=limites[1],
        # Repetido no aporta: el mismo aviso una vez por punto roto seria ruido.
        avisos=tuple(dict.fromkeys(avisos)),
    )


def _limites(puntos: list[Punto]):
    if not puntos:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (
        (
            min(p.norte_m for p in puntos),
            min(p.este_m for p in puntos),
            min(p.cota_m for p in puntos),
        ),
        (
            max(p.norte_m for p in puntos),
            max(p.este_m for p in puntos),
            max(p.cota_m for p in puntos),
        ),
    )


def iterar_puntos(ruta: str | Path):
    """Recorre **todos** los `CgPoint`, uno a uno, sin quedarse con ninguno.

    Lo mismo que `puntos.iterar()` y por lo mismo: quien tiene que escribir el archivo de
    salida no puede materializar cien mil dataclasses para copiarlas.
    """
    indice = 0
    try:
        for _evento, elemento in iterparse(str(ruta), events=("end",)):
            if _local(elemento.tag) != "CgPoint":
                elemento.clear()
                continue
            indice += 1
            punto = _punto_de(elemento, indice)
            elemento.clear()
            if punto is not None:
                yield punto
    except ParseError as fallo:
        raise NoEsLandXml(f"El XML no esta bien formado: {fallo}") from fallo
