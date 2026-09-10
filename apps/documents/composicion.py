"""Componer un PDF: qué páginas, en qué orden y hacia dónde miran.

No es una conversión, y por eso vive aparte. El resto de AeroConvert coge **un** archivo y
lo lleva a otro formato; aquí se cogen **varios**, se eligen páginas sueltas de cada uno, se
ordenan a mano y algunas se giran. El resultado no cambia de formato: sigue siendo un PDF.

## La receta es un dato, no una secuencia de llamadas

Toda la composición se describe con una lista de `PaginaElegida` —archivo, página, giro— y
esta función la ejecuta. Es la misma decisión que hace que los motores describan un plan en
vez de ejecutarlo: una receta se puede enseñar en pantalla antes de aplicarla, se puede
guardar, y se puede probar sin escribir un archivo.

## Girar no vuelve a dibujar nada

Poner una lámina apaisada es sumarle grados a `/Rotate`, que es un número en el diccionario
de la página. **No se pierde un píxel ni un carácter, y el archivo no engorda.** Por eso se
puede ofrecer sin advertencias: no hay nada que se degrade.

## Lo que sí hay que vigilar

**Que no salga un PDF vacío.** Un archivo de cero páginas es un PDF perfectamente válido
que abre en cualquier visor y no enseña nada, así que componer sin páginas es un error y no
un resultado. Es la misma regla que en el resto del proyecto: el código de salida no prueba
que funcionó.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: Los giros que se pueden pedir. Cualquier otro valor es un error del formulario, no una
#: rotación rara: un PDF solo admite múltiplos de 90.
GIROS = (0, 90, 180, 270)

ETIQUETAS_DE_GIRO = {
    0: "sin girar",
    90: "girada 90° a la derecha",
    180: "boca abajo",
    270: "girada 90° a la izquierda",
}


class ComposicionInvalida(Exception):
    """La receta no se puede aplicar. El mensaje dice por qué, en una frase."""


@dataclass(frozen=True)
class PaginaElegida:
    """Una página de un archivo, con el giro que se le quiere dar.

    `giro` es **relativo a como se ve ahora**, no absoluto. Es lo que espera quien mira la
    pantalla: ve una lámina vertical, pulsa «girar» y quiere verla tumbada. Que por dentro
    esa página ya tuviera `/Rotate=270` no es asunto suyo.
    """

    archivo: Path
    #: Empieza en 1, como en el visor y como en la lista que se enseña.
    numero: int
    giro: int = 0

    def __post_init__(self) -> None:
        if self.giro not in GIROS:
            raise ComposicionInvalida(
                f"El giro tiene que ser 0, 90, 180 o 270 grados, y llegó {self.giro}."
            )
        if self.numero < 1:
            raise ComposicionInvalida(f"Las páginas se cuentan desde 1, y llegó {self.numero}.")


@dataclass(frozen=True)
class Resultado:
    paginas_escritas: int
    bytes_escritos: int
    #: Cuántas venían de cada archivo, para el recibo.
    por_archivo: tuple[tuple[str, int], ...]


def componer(receta: Iterable[PaginaElegida], destino: str | Path) -> Resultado:
    """Escribe el PDF que describe la receta y devuelve qué hizo.

    Los archivos de origen **se abren y no se tocan**: pypdf lee y escribe en un documento
    nuevo.
    """
    from pypdf import PdfReader, PdfWriter

    receta = list(receta)
    if not receta:
        raise ComposicionInvalida(
            "No hay ninguna página elegida. Un PDF de cero páginas abre en cualquier visor "
            "y no enseña nada."
        )

    destino = Path(destino)
    # Un lector por archivo, no uno por página: abrir cincuenta veces el mismo plano de
    # 40 MB es tiempo y memoria por nada.
    lectores: dict[Path, object] = {}
    cuenta: dict[str, int] = {}

    escritor = PdfWriter()
    for elegida in receta:
        ruta = Path(elegida.archivo)
        if ruta not in lectores:
            if not ruta.is_file():
                raise ComposicionInvalida(f"No hay ningún archivo en {ruta}.")
            try:
                lectores[ruta] = PdfReader(str(ruta))
            except Exception as fallo:
                raise ComposicionInvalida(f"No se pudo leer {ruta.name}: {fallo}") from fallo

        lector = lectores[ruta]
        total = len(lector.pages)
        if elegida.numero > total:
            raise ComposicionInvalida(
                f"{ruta.name} tiene {total} página(s) y se pidió la {elegida.numero}."
            )

        pagina = lector.pages[elegida.numero - 1]
        if elegida.giro:
            # Suma sobre lo que la página ya traía: el giro que se pide en pantalla es
            # relativo a como se ve, no absoluto.
            pagina.rotate(elegida.giro)
        escritor.add_page(pagina)
        cuenta[ruta.name] = cuenta.get(ruta.name, 0) + 1

    with open(destino, "wb") as salida:
        escritor.write(salida)

    escritas = len(escritor.pages)
    if not escritas:  # pragma: no cover - la receta vacia se rechaza antes
        raise ComposicionInvalida("El PDF salió sin páginas.")

    return Resultado(
        paginas_escritas=escritas,
        bytes_escritos=destino.stat().st_size,
        por_archivo=tuple(cuenta.items()),
    )


def receta_de_archivos(archivos: Iterable[str | Path]) -> list[PaginaElegida]:
    """La receta más simple: todos los archivos enteros, en el orden dado.

    Es el punto de partida de la pantalla —«junta estos PDF»— sobre el que después se quitan
    páginas, se reordenan y se gira alguna.
    """
    from ..formats import pdf as lectura

    elegidas: list[PaginaElegida] = []
    for archivo in archivos:
        ruta = Path(archivo)
        cabecera = lectura.leer_cabecera(ruta)
        if cabecera.cifrado:
            raise ComposicionInvalida(
                f"{ruta.name} pide contraseña. Ábrelo y guárdalo sin ella para poder usarlo."
            )
        elegidas.extend(PaginaElegida(ruta, pagina.numero) for pagina in cabecera.paginas)
    return elegidas
