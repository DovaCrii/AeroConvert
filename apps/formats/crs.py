"""El sistema de referencia, con su procedencia pegada.

La regla viene escrita de AeroBim (`docs/NUBES_DE_PUNTOS.md`) y aca se hereda entera:
**si el CRS viene vacio, la conversion para y se pregunta. Adivinarlo es peor que no
tenerlo.** Un DEM en UTM leido como si fueran grados devuelve elevaciones de otro
continente, y lo hace en silencio.

Por eso `Crs` guarda `origen`: no es lo mismo un EPSG que venia incrustado en el archivo
que uno que alguien tecleo en un formulario a las siete de la tarde. Cuando algo salga mal
en seis meses, esa distincion es la que permite reconstruir que paso.

Y por eso existe `PuntoConCrs`: **ninguna funcion del proyecto acepta un `(x, y)` pelado.**
El tipo lo hace imposible.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

#: De donde salio el CRS. El orden es de mas fiable a menos.
INCRUSTADO = "incrustado"
SIDECAR_PRJ = "sidecar-prj"
DECLARADO = "declarado"
#: Lo impone el formato. KML y KMZ solo existen en EPSG:4326: lo dice la norma.
#:
#: Es un origen aparte de `INCRUSTADO` porque no viene escrito dentro del archivo, y aparte
#: de `DECLARADO` porque no lo eligio nadie. La ficha lo dice tal cual, y esa distincion es
#: la que separa «lo sabemos» de «alguien lo supuso».
POR_NORMA = "por-norma"
DESCONOCIDO = "desconocido"

ETIQUETAS_ORIGEN = {
    INCRUSTADO: "venia dentro del archivo",
    SIDECAR_PRJ: "venia en el .prj de al lado",
    DECLARADO: "lo declaro una persona",
    POR_NORMA: "lo fija el formato",
    DESCONOCIDO: "no se sabe",
}


class CrsInvalido(Exception):
    def __init__(self, mensaje: str, codigo: str = "crs-invalido") -> None:
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class Crs:
    autoridad: str
    codigo: str
    wkt: str = ""
    origen: str = DESCONOCIDO
    nombre: str = ""

    def __str__(self) -> str:
        return f"{self.autoridad}:{self.codigo}"

    @property
    def conocido(self) -> bool:
        return bool(self.autoridad and self.codigo)

    @property
    def procedencia(self) -> str:
        return ETIQUETAS_ORIGEN.get(self.origen, self.origen)

    @property
    def es_declarado(self) -> bool:
        """`True` si lo puso una persona. La interfaz lo marca distinto a proposito."""
        return self.origen == DECLARADO

    @property
    def es_geografico(self) -> bool:
        """`True` si sus coordenadas son **grados** y no metros.

        Importa porque hay destinos donde eso hace el archivo inservible sin dar ningun
        error. Un DXF en EPSG:4326 es un dibujo de 0,002 unidades de ancho: abre en Civil
        3D, no se ve nada, y no hay nada que diga por que.

        Devuelve `False` cuando no se puede saber -- sin pyproj o con un codigo que PROJ no
        conoce -- porque la alternativa seria bloquear conversiones legitimas por no poder
        comprobar algo.
        """
        if not self.conocido:
            return False
        try:
            from pyproj import CRS as PyprojCRS
        except ImportError:  # pragma: no cover - pyproj es dependencia dura
            return False
        try:
            return bool(PyprojCRS.from_user_input(str(self)).is_geographic)
        except Exception:  # pragma: no cover - un codigo que PROJ no conoce
            return False


#: El CRS que no se sabe. Se usa en vez de `None` para que el codigo que lo consume no
#: tenga que preguntar dos cosas distintas.
SIN_CRS = Crs(autoridad="", codigo="", origen=DESCONOCIDO)


@lru_cache(maxsize=512)
def _nombre_epsg(codigo: int) -> str:
    """Nombre legible de un EPSG. Cadena vacia si pyproj no lo conoce.

    Cacheado porque la ficha del archivo lo pide en cada pintada y abrir la base de PROJ
    no es gratis.
    """
    try:
        from pyproj import CRS as PyprojCRS
    except ImportError:  # pragma: no cover - pyproj es dependencia declarada
        return ""
    try:
        return PyprojCRS.from_epsg(codigo).name
    except Exception:
        return ""


def epsg(codigo: int | str, *, origen: str = INCRUSTADO) -> Crs:
    """Construye un `Crs` desde un codigo EPSG, con su nombre resuelto."""
    numero = int(str(codigo).strip().upper().removeprefix("EPSG:"))
    return Crs(
        autoridad="EPSG",
        codigo=str(numero),
        origen=origen,
        nombre=_nombre_epsg(numero),
    )


def validar_declarado(texto: str) -> Crs:
    """Valida un EPSG tecleado por una persona.

    Acepta `32719` y `EPSG:32719`. **No sugiere nada y no tiene valor por omision**: la
    idea es que quien lo escriba tenga que saberlo, no elegir de una lista de probables.

    Levanta `CrsInvalido` con motivo de codigo estable cuando no cuadra.
    """
    limpio = (texto or "").strip().upper().removeprefix("EPSG:").strip()
    if not limpio:
        raise CrsInvalido("No se declaro ningun sistema de referencia.", "crs-ausente")
    if not limpio.isdigit():
        raise CrsInvalido(
            f"'{texto}' no es un codigo EPSG. Se espera un numero, por ejemplo 32719.",
            "crs-invalido",
        )

    numero = int(limpio)
    try:
        from pyproj import CRS as PyprojCRS
    except ImportError:  # pragma: no cover
        return Crs(autoridad="EPSG", codigo=str(numero), origen=DECLARADO)

    try:
        resuelto = PyprojCRS.from_epsg(numero)
    except Exception as fallo:
        raise CrsInvalido(f"EPSG:{numero} no existe en la base de PROJ.", "crs-invalido") from fallo

    return Crs(
        autoridad="EPSG",
        codigo=str(numero),
        wkt=resuelto.to_wkt(),
        origen=DECLARADO,
        nombre=resuelto.name,
    )


#: Las claves de `to_dict()` que definen la proyeccion. Se comparan para verificar un EPSG
#: que el WKT declara de si mismo. `datum`/`ellps` quedan fuera a proposito: son justo lo
#: que difiere entre el WKT de Metashape y el canonico, y no mueven un solo metro cuando
#: ambos son WGS 84.
CLAVES_DE_PROYECCION = (
    "proj",
    "zone",
    "south",
    "lat_0",
    "lon_0",
    "k",
    "k_0",
    "x_0",
    "y_0",
    "units",
)


def _autoridad_declarada(wkt: str) -> tuple[str, str] | None:
    """El nodo `AUTHORITY` mas externo del WKT, que es el ultimo del texto."""
    import re

    encontrados = re.findall(r'AUTHORITY\s*\[\s*"([^"]+)"\s*,\s*"(\d+)"\s*\]', wkt, re.IGNORECASE)
    return (encontrados[-1][0].upper(), encontrados[-1][1]) if encontrados else None


def _coincide_con_epsg(resuelto, codigo: int) -> bool:
    """`True` si el CRS del WKT y `EPSG:<codigo>` describen la misma proyeccion.

    No se comparan los WKT ni los datums: se comparan los parametros que mueven
    coordenadas. Dos descripciones del mismo UTM 19S tienen que coincidir en proyeccion,
    huso, hemisferio, meridiano central, factor de escala y falsos origenes. Si coinciden
    en todo eso, son el mismo sistema aunque el texto difiera.
    """
    try:
        from pyproj import CRS as PyprojCRS

        canonico = PyprojCRS.from_epsg(codigo)
    except Exception:
        return False

    # `to_dict()` pasa por una cadena PROJ4 y avisa de que se pierde informacion. Es
    # cierto y no importa aca: lo que se compara son justo los parametros que PROJ4 si
    # conserva, y lo que se pierde -- el nombre del datum -- es lo que estamos ignorando a
    # proposito. El aviso se silencia para que no ensucie cada inspeccion.
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            a, b = resuelto.to_dict(), canonico.to_dict()
    except Exception:
        return False

    for clave in CLAVES_DE_PROYECCION:
        va, vb = a.get(clave), b.get(clave)
        if va is None and vb is None:
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if abs(float(va) - float(vb)) > 1e-9:
                return False
        elif va != vb:
            return False
    return True


def desde_wkt(wkt: str, *, origen: str = SIDECAR_PRJ) -> Crs:
    """Lee un `.prj` y saca su autoridad.

    Tres pasadas, y la tercera hace falta de verdad:

    1. `to_authority()` con la confianza por omision (70).
    2. La misma con confianza 25, el escalon que la propia pyproj define para «coincide
       salvo detalles del datum».
    3. **El EPSG que el propio WKT declara, verificado.** Con las dos primeras, pyproj
       **no reconoce el `.prj` que escribe Metashape** -- ni siquiera con confianza 20:
       devuelve una lista de candidatos vacia, porque el WKT lleva un `TOWGS84` de ceros y
       llama al datum «World Geodetic System 1984 ensemble». Y sin embargo ese archivo
       termina literalmente en `AUTHORITY["EPSG","32719"]`.

       Dar «CRS desconocido» ante un archivo que dice su EPSG en la ultima linea seria
       absurdo, pero creerle sin mas seria adivinar, que es lo que este proyecto no hace.
       Asi que se lee el codigo declarado y **se comprueba contra la definicion canonica**:
       si los parametros de proyeccion coinciden, se acepta; si no, se descarta y el CRS
       queda sin codigo. La comprobacion es la diferencia entre confiar y verificar.

    Si nada identifica el sistema, se devuelve el WKT sin codigo: tenerlo sin poder
    nombrarlo sigue siendo mejor que perderlo.
    """
    if not (wkt or "").strip():
        return SIN_CRS
    try:
        from pyproj import CRS as PyprojCRS

        resuelto = PyprojCRS.from_wkt(wkt)
    except Exception:
        return Crs(autoridad="", codigo="", wkt=wkt, origen=origen, nombre=_seguro(wkt))

    # **Un CRS compuesto se resuelve por su componente horizontal.**
    #
    # PDAL escribe las nubes con un `COMPD_CS`: el UTM de siempre más un sistema vertical
    # que casi nunca trae datum conocido. Ese compuesto no lo identifica nadie, y entonces
    # entraba la heurística del `AUTHORITY` declarado -- que toma el **último** del texto, y
    # en un compuesto ese es el del metro del sistema vertical, `EPSG:9001`, no el 32719.
    # Resultado: una nube perfectamente georreferenciada se reportaba sin CRS.
    #
    # Se informa del horizontal porque es el que sitúa el dato en el mapa. El WKT completo
    # se conserva en `wkt`, así que la parte vertical no se pierde: solo no da el nombre.
    objetivo, texto_declarado = _componente_horizontal(resuelto, wkt)

    try:
        autoridad = objetivo.to_authority() or objetivo.to_authority(min_confidence=25)
    except Exception:
        autoridad = None

    if autoridad is None:
        declarada = _autoridad_declarada(texto_declarado)
        if declarada and declarada[0] == "EPSG" and _coincide_con_epsg(objetivo, int(declarada[1])):
            autoridad = declarada

    if autoridad is None:
        return Crs(autoridad="", codigo="", wkt=wkt, origen=origen, nombre=_seguro(wkt))
    return Crs(
        autoridad=autoridad[0],
        codigo=autoridad[1],
        wkt=wkt,
        origen=origen,
        nombre=objetivo.name,
    )


def _componente_horizontal(resuelto, wkt: str):
    """El sub-CRS que sitúa el dato en el mapa, y el WKT con el que identificarlo.

    Devuelve el propio CRS cuando no es compuesto, y también cuando pyproj no puede
    descomponerlo — que es un caso real con WKT raros. Volver al compuesto entero es peor
    que fallar aquí: al menos la resolución estricta sigue teniendo una oportunidad.
    """
    try:
        if resuelto.is_compound and resuelto.sub_crs_list:
            horizontal = resuelto.sub_crs_list[0]
            return horizontal, horizontal.to_wkt()
    except Exception:
        return resuelto, wkt
    return resuelto, wkt


def _seguro(wkt: str) -> str:
    """El nombre que abre el WKT, sin depender de pyproj."""
    inicio = wkt.find('["')
    if inicio == -1:
        return ""
    fin = wkt.find('"', inicio + 2)
    return wkt[inicio + 2 : fin] if fin != -1 else ""


@dataclass(frozen=True)
class PuntoConCrs:
    """Una coordenada que sabe en que sistema esta.

    Las unidades van en el nombre y son SI: es la convencion de toda la familia Aero, y
    existe porque `x` a secas ha costado horas en mas de un proyecto.
    """

    x_m: float
    y_m: float
    crs: Crs
    z_m: float | None = None

    def __str__(self) -> str:
        cota = f", {self.z_m:.3f}" if self.z_m is not None else ""
        return f"({self.x_m:.3f}, {self.y_m:.3f}{cota}) {self.crs}"
