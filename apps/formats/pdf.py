"""Leer un PDF: cuántas páginas, de qué tamaño y hacia dónde miran.

Es la base de la pantalla de unir PDF. Para poder elegir páginas, ordenarlas y girar algunas
láminas hay que poder **enseñarlas antes**, y para eso hace falta saber qué hay en cada una.

## El giro no es un detalle: es lo que se ve

Un PDF guarda dos cosas distintas y hay que combinarlas. La **caja** (`MediaBox`) dice el
tamaño del papel, y el **giro** (`/Rotate`) dice cuánto hay que rotarlo al mostrarlo.

Un plano A1 de verdad de esta oficina tiene la caja en 594 × 841 mm —vertical— y `/Rotate`
en 270. En pantalla y en el papel es una lámina **apaisada** de 841 × 594. Mirar solo la caja
haría que la aplicación llamara «vertical» a una lámina que todo el mundo ve tumbada, y eso
en una herramienta cuyo trabajo es precisamente poner unas hojas verticales y otras
apaisadas sería peor que no decir nada.

Así que la orientación sale de las dos, y el tamaño que se enseña es el que se ve.

## Y girar una página no la vuelve a dibujar

Cambiar `/Rotate` no toca el contenido: es un número en el diccionario de la página. Girar
una lámina para la entrega **no pierde un solo píxel ni un solo carácter**, y no engorda el
archivo. Es lo que hace que esto sea seguro de ofrecer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

#: Un punto PostScript son 1/72 de pulgada. Todo lo que se enseña va en milimetros porque
#: es lo que dice un plano.
MM_POR_PUNTO = 25.4 / 72

#: Tamanos normalizados, en milimetros y con su tolerancia. Decir «A1 apaisada» ahorra a
#: quien mira tener que interpretar «841 x 594».
NORMALIZADOS = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
    "Carta": (216, 279),
    "Oficio": (216, 356),
    "Tabloide": (279, 432),
}

#: Cuanto puede desviarse un tamano real del normalizado, en milimetros. Los PDF salen de
#: mil programas y casi ninguno da el milimetro exacto.
TOLERANCIA_MM = 3.0


class NoEsPdf(Exception):
    """El archivo no es un PDF legible."""


@dataclass(frozen=True)
class Pagina:
    """Una página, tal como se ve."""

    #: Empieza en 1, como en el visor.
    numero: int
    ancho_mm: float
    alto_mm: float
    #: Los grados que el PDF pide girar al mostrar: 0, 90, 180 o 270.
    giro: int

    @property
    def apaisada(self) -> bool:
        return self.ancho_mm > self.alto_mm

    @property
    def orientacion(self) -> str:
        return "apaisada" if self.apaisada else "vertical"

    @property
    def formato(self) -> str:
        """`A1`, `Carta`... o el tamaño en milímetros si no cuadra con ninguno."""
        for nombre, (corto, largo) in NORMALIZADOS.items():
            menor, mayor = sorted((self.ancho_mm, self.alto_mm))
            if abs(menor - corto) <= TOLERANCIA_MM and abs(mayor - largo) <= TOLERANCIA_MM:
                return nombre
        return f"{self.ancho_mm:.0f} × {self.alto_mm:.0f} mm"

    @property
    def etiqueta(self) -> str:
        """Lo que se lee en la tarjeta de la página: «A1 apaisada»."""
        return f"{self.formato} {self.orientacion}"


@dataclass(frozen=True)
class CabeceraPdf:
    """Lo que se sabe de un PDF sin dibujarlo."""

    paginas: tuple[Pagina, ...]
    #: `True` si pide contraseña. Entonces no hay nada que hacer sin ella.
    cifrado: bool = False
    titulo: str = ""
    #: Qué programa lo escribió. Un `AutoCAD PDF` y un `Microsoft Word` no dan los mismos
    #: problemas, y saberlo antes ahorra sorpresas.
    productor: str = ""
    #: Lo que pypdf protestó al leerlo. Los PDF del mundo real vienen rotos a menudo, y eso
    #: **no impide** trabajar con ellos; se dice y se sigue.
    avisos: tuple[str, ...] = ()

    @property
    def cuantas(self) -> int:
        return len(self.paginas)

    @property
    def resumen(self) -> str:
        """Una línea: «56 páginas · Carta vertical» o «12 páginas · tamaños mezclados»."""
        if not self.paginas:
            return "sin páginas"
        etiquetas = {p.etiqueta for p in self.paginas}
        detalle = etiquetas.pop() if len(etiquetas) == 1 else "tamaños mezclados"
        return f"{self.cuantas} página(s) · {detalle}"

    @property
    def mezcla_orientaciones(self) -> bool:
        """`True` si hay verticales y apaisadas. Es el caso que obliga a mirar antes."""
        return len({p.apaisada for p in self.paginas}) > 1


def _milimetros(pagina) -> tuple[float, float]:
    """El tamaño **tal como se ve**, con el giro ya aplicado."""
    caja = pagina.mediabox
    ancho = float(caja.width) * MM_POR_PUNTO
    alto = float(caja.height) * MM_POR_PUNTO

    giro = _giro(pagina)
    if giro in (90, 270):
        ancho, alto = alto, ancho
    return ancho, alto


def _giro(pagina) -> int:
    """Los grados de `/Rotate`, normalizados a 0, 90, 180 o 270.

    El valor puede venir negativo o pasado de vuelta —`-90`, `450`— y el visor lo normaliza
    igual. Aquí también, o dos páginas que se ven idénticas saldrían distintas en la lista.
    """
    try:
        crudo = int(pagina.get("/Rotate", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return crudo % 360 // 90 * 90


class _RecogerQuejas(logging.Handler):
    """Se queda con lo que pypdf protesta mientras lee, en vez de dejarlo ir a la consola.

    **Y hay que engancharlo al `logging`, no al `warnings`.** Es lo que costó descubrirlo:
    un plano real de la oficina suelta `Multiple definitions in dictionary for key
    /PageMode` y se lee perfectamente, pero esa queja sale por el registro de pypdf, así
    que capturar avisos con `warnings.catch_warnings` no recogía nada y el mensaje acababa
    en la consola del servidor — donde no lo lee quien está mirando el archivo.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, registro: logging.LogRecord) -> None:
        self.mensajes.append(registro.getMessage())


def leer_cabecera(ruta: str | Path) -> CabeceraPdf:
    """Recorre el PDF y devuelve qué páginas tiene."""
    import warnings

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    ruta = Path(ruta)
    avisos: list[str] = []

    quejas = _RecogerQuejas()
    registro_pypdf = logging.getLogger("pypdf")
    registro_pypdf.addHandler(quejas)
    try:
        # **Los PDF del mundo real vienen rotos**, y eso no impide trabajar con ellos: se
        # dice y se sigue.
        with warnings.catch_warnings(record=True) as recogidos:
            warnings.simplefilter("always")
            lector = PdfReader(str(ruta))
            cifrado = bool(lector.is_encrypted)
            paginas = (
                ()
                if cifrado
                else tuple(
                    Pagina(numero=i, ancho_mm=a, alto_mm=h, giro=_giro(p))
                    for i, p in enumerate(lector.pages, start=1)
                    for a, h in (_milimetros(p),)
                )
            )
            informacion = {} if cifrado else (lector.metadata or {})
            avisos = [str(aviso.message) for aviso in recogidos] + quejas.mensajes
    except PdfReadError as fallo:
        raise NoEsPdf(f"No se pudo leer el PDF: {fallo}") from fallo
    except OSError as fallo:  # pragma: no cover - lo filtra la inspección antes
        raise NoEsPdf(str(fallo)) from fallo
    except Exception as fallo:  # pypdf levanta de todo con archivos rotos
        raise NoEsPdf(f"No se pudo leer el PDF: {fallo}") from fallo
    finally:
        registro_pypdf.removeHandler(quejas)

    return CabeceraPdf(
        paginas=paginas,
        cifrado=cifrado,
        titulo=str(informacion.get("/Title", "") or "").strip(),
        productor=str(informacion.get("/Producer", "") or "").strip(),
        # Sin repetir: un PDF roto suelta el mismo aviso una vez por página.
        avisos=tuple(dict.fromkeys(avisos)),
    )
