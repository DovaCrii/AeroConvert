"""Lo que Tino sabe **sin preguntarle a nadie de fuera**.

## La idea que cambia el resto

Las tres cosas que se le van a preguntar a un ayudante aquí —«¿por qué no puedo hacer
esto?», «¿con cuál de las veinte herramientas?», «¿por qué JPEG 2000 y no ECW?»— **esta
máquina ya las sabe contestar**. Están en la matriz de capacidades, en el catálogo de
acciones y en las notas del catálogo de formatos, y son la respuesta correcta, no una
aproximación: cuando la matriz dice que falta PDAL, es que falta PDAL.

Así que Tino empieza por aquí. Lo que contesta desde esta máquina:

- es exacto, porque sale de lo mismo que decide la conversión,
- **no sale del equipo**, que es el argumento entero de esta aplicación,
- y funciona sin configurar nada ni pagar nada.

Un modelo de fuera solo hace falta para lo que quede después, y con eso **lo que sale es la
pregunta escrita y nada más**. Ver `apps/tino/fuera.py`.

## Y sabe decir «no sé»

En una herramienta cuyo valor es decir la verdad sobre lo que se puede y lo que no, una
respuesta inventada sobre un sistema de referencia hace daño de verdad: alguien entrega un
KML a cientos de kilómetros de la obra. Cuando no hay respuesta, esto devuelve `None` y la
pantalla lo dice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.dashboard import acciones as acciones_mod
from apps.formats import catalogo


@dataclass(frozen=True)
class Respuesta:
    """Lo que Tino contesta. Con de dónde lo sacó, que es lo que la hace comprobable."""

    #: La frase corta. Lo primero y a veces lo único que alguien lee.
    titulo: str
    #: El porqué, si lo hay.
    detalle: str = ""
    #: A dónde ir. Texto y dirección; sin dirección no se pinta enlace.
    accion: str = ""
    enlace: str = ""
    #: **De dónde sale.** «la matriz de capacidades», «el catálogo de
    #: formatos». No es adorno: es lo que permite a alguien comprobar la respuesta en vez de
    #: creérsela, y es la diferencia entre un ayudante y un oráculo.
    fuente: str = ""
    #: Otras cosas que quizá quería preguntar. Vacío casi siempre.
    tambien: tuple[str, ...] = field(default_factory=tuple)


def contestar(pregunta: str) -> Respuesta | None:
    """La respuesta de esta máquina, o `None` si aquí no se sabe.

    **El orden importa y es de más concreto a más vago.** Quien escribe «tif a jp2» quiere
    un sí o un no, no una lista de herramientas parecidas; quien escribe «juntar planos»
    quiere la herramienta. Al revés, el par de formatos se perdería entre las coincidencias
    de texto.
    """
    pregunta = (pregunta or "").strip()
    if not pregunta:
        return None

    return (
        _sobre_una_conversion(pregunta)
        or _sobre_un_formato(pregunta)
        or _sobre_una_herramienta(pregunta)
    )


def _sobre_una_conversion(pregunta: str) -> Respuesta | None:
    """«¿se puede tif a jp2?» — y sobre todo **por qué no**, cuando no se puede.

    Es la pregunta de más valor que contesta esta aplicación, y ya la resuelve el buscador
    de la portada. Aquí se reutiliza entera: dos respuestas distintas a la misma pregunta
    sería el peor resultado posible.
    """
    conversion = acciones_mod.conversion_pedida(pregunta)
    if conversion is None:
        return None

    if conversion.se_puede:
        return Respuesta(
            titulo=f"Sí: {conversion.nombre_origen} → {conversion.nombre_destino} se puede aquí.",
            detalle="Elige el archivo y pide ese formato en «ajustar a mano».",
            accion=f"Convertir a {conversion.nombre_destino}",
            enlace=f"/convertir/?formato={conversion.destino}",
            fuente="la matriz de capacidades",
        )

    return Respuesta(
        titulo=f"No: {conversion.nombre_origen} → {conversion.nombre_destino} no se puede aquí.",
        detalle=" ".join(t for t in (conversion.motivo, conversion.sugerencia) if t),
        accion="Ver la tabla completa",
        enlace="/motores/",
        fuente="la matriz de capacidades",
    )


#: Lo que convierte «menciona un formato» en «pregunta por un formato».
#:
#: **Sin esto, nombrar un archivo bastaba para disparar la explicación.** «Por qué no puedo
#: convertir vuelo.tif» contestaba «GeoTIFF clásico: TIFF clásico, es el que abre en
#: cualquier parte» — cierto, y no era la pregunta. Una respuesta correcta a otra pregunta
#: es peor que un «no sé», porque parece que te han entendido.
PREGUNTA_POR_LA_COSA = (
    "que es",
    "qué es",
    "que son",
    "para que",
    "para qué",
    "por que",
    "por qué",
    "cuando uso",
    "cuando usar",
    "diferencia",
    "sirve",
    "significa",
)


def _sobre_un_formato(pregunta: str) -> Respuesta | None:
    """«¿qué es un COG?», «¿por qué ECW no?» — lo que el catálogo ya tiene escrito.

    Tres condiciones a la vez, y las tres hacen falta:

    1. Que se nombre el formato.
    2. Que el catálogo tenga una nota sobre él — «GeoTIFF es GeoTIFF» no es una respuesta.
    3. **Que la pregunta sea sobre el formato**, no sobre otra cosa que lo menciona. Ver
       `PREGUNTA_POR_LA_COSA`. Un nombre suelto —«cog»— también cuenta: ahí no hay otra
       pregunta posible.
    """
    texto = acciones_mod.sin_tildes(pregunta.lower())
    palabras = _palabras(texto)

    pide_explicacion = any(marca in texto for marca in PREGUNTA_POR_LA_COSA) or len(palabras) <= 2
    if not pide_explicacion:
        return None

    palabras = set(palabras)

    for codigo, formato in catalogo.FORMATOS.items():
        nota = str(getattr(formato, "nota", "") or "")
        if not nota:
            continue
        nombres = {codigo, *(e.lstrip(".") for e in formato.extensiones)}
        if not (nombres & palabras):
            continue
        return Respuesta(
            titulo=str(formato.nombre),
            detalle=nota,
            accion="Ver qué se puede hacer con él",
            enlace="/motores/",
            fuente="el catálogo de formatos",
        )
    return None


def _sobre_una_herramienta(pregunta: str) -> Respuesta | None:
    """«¿con qué junto tres planos?» — el catálogo de acciones, que ya entiende sinónimos.

    **Una que destaque contesta; un empate, no.** Devolver el primero de una lista empatada
    es contestar al azar con cara de seguridad, y aquí eso es peor que callarse. La regla
    entera está en `acciones.mejor`, que es donde vive la búsqueda — para que el ayudante y
    el buscador no puedan dar dos respuestas distintas a la misma pregunta.
    """
    accion = acciones_mod.mejor(pregunta)
    if accion is None:
        return None
    return Respuesta(
        titulo=accion.nombre,
        detalle=accion.que_hace,
        accion=f"Ir a {accion.nombre}",
        enlace=accion.enlace,
        fuente="el catálogo de herramientas",
    )


def _palabras(texto: str) -> list[str]:
    limpio = "".join(c if c.isalnum() else " " for c in texto)
    return [p for p in limpio.split() if p]
