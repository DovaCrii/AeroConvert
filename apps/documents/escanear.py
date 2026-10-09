"""Escanear con el teléfono: fotos de hojas a un PDF, derechas y recortadas (F14.12).

Una foto de una hoja tomada con el teléfono lleva la hoja de lado, en perspectiva y rodeada de
mesa. Aquí se **detecta el borde de la hoja**, se **corrige la perspectiva** para que la página
quede rectangular, se recorta, se mejora el contraste si se pide y se junta todo en **un PDF con
una página por foto**, en el orden dado. Con Tesseract, si lo pide, el PDF sale además con su capa
de texto (`ocr.py`).

## Cómo se detecta la hoja, y por qué sin OpenCV

Solo con Pillow y Python: no hay NumPy ni OpenCV entre las dependencias, y para esto no hacen
falta. La foto se reduce a unos 360 px de lado y se hace lo que sigue.

1. **Blancura** de cada punto: el menor de sus tres canales. El papel es blanco, y una mesa de
   madera, una tela o un suelo suelen tener un canal bajo aunque su brillo sea alto.
2. **Umbral de Otsu** sobre esa blancura, un cierre morfológico y el relleno de los huecos (el
   texto y los dibujos de la hoja son huecos dentro del papel).
3. **La mayor región conectada** es la candidata.
4. Del casco convexo de la región se elige **el cuadrilátero de mayor área**: no depende de que la
   hoja venga derecha, ni de que sus esquinas estén redondeadas.

## No se inventa un recorte

Si la candidata no es creíble —ocupa muy poco, ocupa todo el cuadro, su forma no se parece a una
hoja, casi no contrasta con lo que la rodea— **no se recorta**: la foto queda entera y se dice por
qué (regla 4: nada se sustituye en silencio). La pantalla deja marcar las cuatro esquinas a mano.

## La proporción de la página no se mide con el borde de la foto

Una hoja vista en perspectiva tiene el lado cercano más largo que el lejano, y promediarlos da una
proporción equivocada. Se estima la proporción real de la hoja con el método de Zhang y He (2007),
que la saca de la propia perspectiva suponiendo el punto principal de la cámara en el centro de la
foto y el píxel cuadrado. Si el cálculo no es creíble (hoja casi de frente, esquinas marcadas a
mano muy torcidas) se usa la media de los lados.

## Qué se conserva y qué no se toca

- **La orientación EXIF** se aplica al abrir —una foto de teléfono lleva «girada 90°» en su
  EXIF—, y las esquinas se dan **sobre la foto ya derecha**, que es lo que ve la persona.
- **El original no se toca**: se abre en solo lectura y todo ocurre sobre copias en memoria o en
  una carpeta temporal que se borra sola.
- **Todo o nada**: si una foto no se abre o unas esquinas no valen, no sale un PDF a medias.
"""

from __future__ import annotations

import itertools
import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .composicion import ComposicionInvalida

#: Lado mayor, en píxeles, al que se reduce la foto para buscar la hoja.
LADO_DE_DETECCION = 360

#: Una hoja que ocupa menos de esto del cuadro no se distingue de un papel cualquiera de la mesa.
AREA_MINIMA = 0.15
#: Si lo «blanco» llena casi todo el cuadro no hay borde que detectar: la hoja ocupa toda la foto
#: o lo de alrededor también es claro.
AREA_MAXIMA = 0.97
#: Cuánto del área de la región tiene que caber en el cuadrilátero hallado. Una región con brazos
#: (la hoja pegada a un mantel claro) llena mal su cuadrilátero y no es una hoja.
RELLENO_MINIMO = 0.92
#: Diferencia mínima de blancura entre la hoja y lo que la rodea, de 0 a 255.
CONTRASTE_MINIMO = 25
#: Ángulos interiores que puede tener una hoja fotografiada en perspectiva.
ANGULO_MINIMO_GRADOS = 50
ANGULO_MAXIMO_GRADOS = 130
#: Un cuadrilátero marcado a mano tiene que ocupar al menos esto de la foto.
AREA_MINIMA_A_MANO = 0.02

#: Lado mayor máximo de la página resultante, en píxeles. A4 a unos 255 ppp.
LADO_MAXIMO_DE_PAGINA = 3000
#: Resolución con la que se dimensiona la página en el modo «hoja».
PPP_DE_HOJA = 200
#: A4 en puntos de PDF, en vertical.
A4_PT = (595.276, 841.89)

#: Calidad JPEG de cada página dentro del PDF.
CALIDAD_JPEG = 88

#: Nivel mínimo del fondo al nivelar la iluminación: un bloque oscuro grande (una foto dentro del
#: documento) se aclara a gris en vez de desaparecer.
FONDO_MINIMO = 140

MAXIMO_HOJAS = 100

TAMANOS = {
    "hoja": "El de cada hoja, tal como salió del recorte",
    "a4": "A4, con la hoja centrada y sin deformarla",
}

#: Lo que se hizo con cada foto.
RECORTADA = "recortada"  # el borde se detectó
A_MANO = "a-mano"  # esquinas marcadas por la persona
ENTERA = "entera"  # sin recorte

MODOS = ("auto", "entera", "esquinas")

#: Códigos estables de por qué no se detectó una hoja, con su frase para una persona.
MOTIVOS_DE_DETECCION = {
    "hoja-pequena": "No se distingue una hoja: lo claro ocupa muy poco de la foto.",
    "sin-borde": "No se ve el borde de la hoja: lo claro llena casi toda la foto.",
    "forma-irregular": "Lo claro no tiene forma de hoja (está pegado a otra cosa o cortado).",
    "poco-contraste": "La hoja casi no se distingue de lo que tiene alrededor.",
    "esquinas-torcidas": "Lo que se detectó tiene ángulos que una hoja no tiene.",
}


@dataclass(frozen=True)
class Deteccion:
    """El resultado de buscar la hoja en una foto.

    `esquinas` va en el orden arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda,
    como fracciones (0 a 1) del ancho y del alto de la foto **ya derecha**. Es `None` cuando no
    hay una hoja creíble, y entonces `motivo` es uno de `MOTIVOS_DE_DETECCION`.
    """

    esquinas: tuple[tuple[float, float], ...] | None
    motivo: str = ""

    @property
    def explicacion(self) -> str:
        return MOTIVOS_DE_DETECCION.get(self.motivo, "")


@dataclass(frozen=True)
class Hoja:
    """Qué hacer con una foto: buscar la hoja (`auto`), dejarla entera o usar estas esquinas."""

    modo: str = "auto"
    esquinas: tuple[tuple[float, float], ...] | None = None


@dataclass(frozen=True)
class Tratada:
    nombre: str
    tratamiento: str
    motivo: str = ""


@dataclass(frozen=True)
class OpcionesDeOcr:
    """La ruta de Tesseract, que sondea el padre (el hijo no tiene Django), y el idioma."""

    programa: str
    idioma: str = "spa"


@dataclass
class Resultado:
    paginas: int
    hojas: list[Tratada] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    con_ocr: bool = False


# --- Abrir ------------------------------------------------------------------


def abrir_derecha(ruta: str | Path):
    """La foto en RGB con la orientación EXIF ya aplicada. Solo lectura: el original no se toca."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    from .imagenes_lote import LADO_MAXIMO_LEIDO, _registrar_heic

    ruta = Path(ruta)
    _registrar_heic()
    try:
        with Image.open(ruta) as abierta:
            abierta.load()
            derecha = ImageOps.exif_transpose(abierta)
            if derecha.mode != "RGB":
                if derecha.mode in ("RGBA", "LA", "P"):
                    convertida = derecha.convert("RGBA")
                    fondo = Image.new("RGB", convertida.size, "white")
                    fondo.paste(convertida, mask=convertida.getchannel("A"))
                    return _revisar_medida(fondo, ruta, LADO_MAXIMO_LEIDO)
                derecha = derecha.convert("RGB")
            return _revisar_medida(derecha.copy(), ruta, LADO_MAXIMO_LEIDO)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as fallo:
        raise ComposicionInvalida(f"{ruta.name} no se pudo abrir como imagen: {fallo}") from fallo


def _revisar_medida(imagen, ruta: Path, tope: int):
    if max(imagen.size) > tope:
        raise ComposicionInvalida(f"{ruta.name} mide más de {tope} px de lado.")
    return imagen


def vista_previa(ruta: str | Path, ancho_max: int = 900) -> bytes:
    """La foto derecha y más chica, en JPEG, para enseñarla en la pantalla."""
    import io

    from PIL import Image

    imagen = abrir_derecha(ruta)
    if max(imagen.size) > ancho_max:
        imagen.thumbnail((ancho_max, ancho_max), Image.Resampling.LANCZOS)
    salida = io.BytesIO()
    imagen.save(salida, "JPEG", quality=80)
    return salida.getvalue()


# --- Detectar la hoja -------------------------------------------------------


def _otsu(histograma: list[int]) -> int:
    total = sum(histograma)
    suma = sum(i * n for i, n in enumerate(histograma))
    fondo = peso_fondo = 0
    mejor, umbral = -1.0, 127
    for nivel in range(256):
        peso_fondo += histograma[nivel]
        if peso_fondo == 0:
            continue
        peso_frente = total - peso_fondo
        if peso_frente == 0:
            break
        fondo += nivel * histograma[nivel]
        media_fondo = fondo / peso_fondo
        media_frente = (suma - fondo) / peso_frente
        varianza = peso_fondo * peso_frente * (media_fondo - media_frente) ** 2
        if varianza > mejor:
            mejor, umbral = varianza, nivel
    return umbral


def _inundar(datos: bytearray, ancho: int, alto: int, semillas, de: int, a: int) -> None:
    """Cambia de `de` a `a` todo lo conectado (en cruz) a las semillas."""
    pila = []
    for p in semillas:
        if datos[p] == de:
            datos[p] = a
            pila.append(p)
    while pila:
        p = pila.pop()
        x = p % ancho
        vecinos = []
        if x > 0:
            vecinos.append(p - 1)
        if x < ancho - 1:
            vecinos.append(p + 1)
        if p >= ancho:
            vecinos.append(p - ancho)
        if p < ancho * (alto - 1):
            vecinos.append(p + ancho)
        for v in vecinos:
            if datos[v] == de:
                datos[v] = a
                pila.append(v)


def _mayor_region(datos: bytearray, ancho: int, alto: int) -> list[int]:
    """Los puntos de la mayor región de unos, conectada en cruz."""
    visto = bytearray(len(datos))
    mejor: list[int] = []
    for inicio in range(len(datos)):
        if datos[inicio] != 1 or visto[inicio]:
            continue
        pila = [inicio]
        visto[inicio] = 1
        region: list[int] = []
        while pila:
            p = pila.pop()
            region.append(p)
            x = p % ancho
            if x > 0 and datos[p - 1] == 1 and not visto[p - 1]:
                visto[p - 1] = 1
                pila.append(p - 1)
            if x < ancho - 1 and datos[p + 1] == 1 and not visto[p + 1]:
                visto[p + 1] = 1
                pila.append(p + 1)
            if p >= ancho and datos[p - ancho] == 1 and not visto[p - ancho]:
                visto[p - ancho] = 1
                pila.append(p - ancho)
            if p < ancho * (alto - 1) and datos[p + ancho] == 1 and not visto[p + ancho]:
                visto[p + ancho] = 1
                pila.append(p + ancho)
        if len(region) > len(mejor):
            mejor = region
    return mejor


def _casco_convexo(puntos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Cadena monótona de Andrew. Sin repetir el primero al final."""
    unicos = sorted(set(puntos))
    if len(unicos) <= 2:
        return unicos

    def cruz(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior: list[tuple[float, float]] = []
    for p in unicos:
        while len(inferior) >= 2 and cruz(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)
    superior: list[tuple[float, float]] = []
    for p in reversed(unicos):
        while len(superior) >= 2 and cruz(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)
    return inferior[:-1] + superior[:-1]


def _area(poligono) -> float:
    """Área con signo (fórmula del topógrafo). Positiva si va en el sentido de las agujas."""
    n = len(poligono)
    return (
        sum(
            poligono[i][0] * poligono[(i + 1) % n][1] - poligono[(i + 1) % n][0] * poligono[i][1]
            for i in range(n)
        )
        / 2
    )


def _simplificar(casco: list[tuple[float, float]], maximo: int = 12):
    """Quita, de uno en uno, el vértice cuya pérdida de área es menor, hasta quedar `maximo`."""
    casco = list(casco)
    while len(casco) > maximo:
        n = len(casco)
        menor, quitar = math.inf, 0
        for i in range(n):
            perdida = abs(_area([casco[i - 1], casco[i], casco[(i + 1) % n]]))
            if perdida < menor:
                menor, quitar = perdida, i
        del casco[quitar]
    return casco


def _recta(puntos):
    """Recta por mínimos cuadrados totales: `(centro, dirección)`."""
    n = len(puntos)
    cx = sum(p[0] for p in puntos) / n
    cy = sum(p[1] for p in puntos) / n
    sxx = sum((p[0] - cx) ** 2 for p in puntos)
    syy = sum((p[1] - cy) ** 2 for p in puntos)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in puntos)
    angulo = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (cx, cy), (math.cos(angulo), math.sin(angulo))


def _cruce(a, b):
    """Dónde se cortan dos rectas `(centro, dirección)`, o `None` si son casi paralelas."""
    (ax, ay), (adx, ady) = a
    (bx, by), (bdx, bdy) = b
    determinante = adx * bdy - ady * bdx
    if abs(determinante) < 0.2:  # menos de unos 11°: no definen un vértice
        return None
    t = ((bx - ax) * bdy - (by - ay) * bdx) / determinante
    return ax + t * adx, ay + t * ady


def _afinar(contorno, grueso):
    """Las esquinas como cruce de los cuatro lados, en vez de los vértices del casco.

    Un vértice del casco es un punto de la malla de píxeles, y en una esquina el suavizado y el
    umbral la achaflanan unos píxeles. Ajustar una recta a los puntos del contorno de cada lado,
    sin sus extremos, y cortarlas da la esquina con una fracción de píxel de error. Si algo no
    cuadra se queda el vértice.
    """
    rectas = []
    for k in range(4):
        a, b = grueso[k], grueso[(k + 1) % 4]
        largo = _distancia(a, b)
        if largo == 0:
            return grueso
        dx, dy = (b[0] - a[0]) / largo, (b[1] - a[1]) / largo
        del_lado = []
        for p in contorno:
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / largo
            distancia = abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx)
            if 0.1 <= t <= 0.9 and distancia <= 3:
                del_lado.append(p)
        if len(del_lado) < 8:
            return grueso
        rectas.append(_recta(del_lado))
    afinado = []
    for k in range(4):
        cruce = _cruce(rectas[k - 1], rectas[k])
        if cruce is None or _distancia(cruce, grueso[k]) > 8:
            afinado.append(grueso[k])
        else:
            afinado.append(cruce)
    return afinado


def _mejor_cuadrilatero(casco: list[tuple[float, float]], contorno):
    """Las cuatro esquinas del casco que encierran más área, en el orden del casco, afinadas."""
    simple = _simplificar(casco)
    if len(simple) < 4:
        return None
    mejor, area_mejor = None, -1.0
    for indices in itertools.combinations(range(len(simple)), 4):
        cuadro = [simple[i] for i in indices]
        area = abs(_area(cuadro))
        if area > area_mejor:
            mejor, area_mejor = cuadro, area
    return _afinar(contorno, mejor)


def _ordenar(cuadro: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    if _area(cuadro) < 0:  # en pantalla (y hacia abajo) el signo positivo va con las agujas
        cuadro = cuadro[::-1]
    inicio = min(range(4), key=lambda i: cuadro[i][0] + cuadro[i][1])
    return cuadro[inicio:] + cuadro[:inicio]


def _angulos_en_grados(cuadro) -> list[float]:
    angulos = []
    for i in range(4):
        a, b, c = cuadro[i - 1], cuadro[i], cuadro[(i + 1) % 4]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        largo = math.hypot(*v1) * math.hypot(*v2)
        if largo == 0:
            return [0.0] * 4
        coseno = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / largo))
        angulos.append(math.degrees(math.acos(coseno)))
    return angulos


def _es_convexo(cuadro) -> bool:
    signos = []
    for i in range(4):
        a, b, c = cuadro[i], cuadro[(i + 1) % 4], cuadro[(i + 2) % 4]
        signos.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    return all(s > 0 for s in signos) or all(s < 0 for s in signos)


def detectar_hoja(imagen) -> Deteccion:
    """Busca la hoja en una foto (RGB, ya derecha). Ver la explicación del módulo."""
    from PIL import Image, ImageChops, ImageFilter

    ancho0, alto0 = imagen.size
    escala = min(1.0, LADO_DE_DETECCION / max(ancho0, alto0))
    ancho = max(8, round(ancho0 * escala))
    alto = max(8, round(alto0 * escala))
    chica = imagen.resize((ancho, alto), Image.Resampling.BOX) if escala < 1.0 else imagen

    rojo, verde, azul = chica.split()
    blancura = ImageChops.darker(ImageChops.darker(rojo, verde), azul).filter(
        ImageFilter.GaussianBlur(1)
    )
    umbral = _otsu(blancura.histogram())
    mascara = blancura.point(lambda v: 1 if v > umbral else 0)
    # Cierre: los trazos finos del texto dejan de ser huecos antes de rellenar los grandes.
    mascara = mascara.point(lambda v: 255 * v).filter(ImageFilter.MaxFilter(5))
    mascara = mascara.filter(ImageFilter.MinFilter(5)).point(lambda v: 1 if v else 0)

    datos = bytearray(mascara.tobytes())
    borde = [x for x in range(ancho)] + [(alto - 1) * ancho + x for x in range(ancho)]
    borde += [y * ancho for y in range(alto)] + [y * ancho + ancho - 1 for y in range(alto)]
    _inundar(datos, ancho, alto, borde, 0, 2)  # el fondo, conectado al borde del cuadro
    for p, valor in enumerate(datos):
        if valor == 0:  # un hueco dentro de la región: texto, un dibujo, una sombra
            datos[p] = 1
    for p, valor in enumerate(datos):
        if valor == 2:
            datos[p] = 0

    region = _mayor_region(datos, ancho, alto)
    fraccion = len(region) / (ancho * alto)
    if fraccion < AREA_MINIMA:
        return Deteccion(None, "hoja-pequena")
    if fraccion > AREA_MAXIMA:
        return Deteccion(None, "sin-borde")

    # El contorno, en bordes de píxel: por fila el primero y el último, por columna el primero y
    # el último. De ahí sale el casco y de ahí se ajustan los lados.
    izquierda: dict[int, int] = {}
    derecha: dict[int, int] = {}
    arriba: dict[int, int] = {}
    abajo: dict[int, int] = {}
    for p in region:
        y, x = divmod(p, ancho)
        if y not in izquierda or x < izquierda[y]:
            izquierda[y] = x
        if y not in derecha or x > derecha[y]:
            derecha[y] = x
        if x not in arriba or y < arriba[x]:
            arriba[x] = y
        if x not in abajo or y > abajo[x]:
            abajo[x] = y
    puntos: list[tuple[float, float]] = []
    contorno: list[tuple[float, float]] = []
    for y in izquierda:
        puntos += [
            (izquierda[y], y),
            (izquierda[y], y + 1),
            (derecha[y] + 1, y),
            (derecha[y] + 1, y + 1),
        ]
        contorno += [(izquierda[y], y + 0.5), (derecha[y] + 1, y + 0.5)]
    for x in arriba:
        contorno += [(x + 0.5, arriba[x]), (x + 0.5, abajo[x] + 1)]
    cuadro = _mejor_cuadrilatero(_casco_convexo(puntos), contorno)
    if cuadro is None:
        return Deteccion(None, "forma-irregular")
    cuadro = _ordenar(cuadro)

    area_cuadro = abs(_area(cuadro))
    if area_cuadro == 0 or len(region) / area_cuadro < RELLENO_MINIMO:
        return Deteccion(None, "forma-irregular")
    if not _es_convexo(cuadro):
        return Deteccion(None, "forma-irregular")
    if any(
        not ANGULO_MINIMO_GRADOS <= a <= ANGULO_MAXIMO_GRADOS for a in _angulos_en_grados(cuadro)
    ):
        return Deteccion(None, "esquinas-torcidas")
    if area_cuadro / (ancho * alto) < AREA_MINIMA:
        return Deteccion(None, "hoja-pequena")

    # Contraste: la blancura media dentro de la región frente a la de fuera.
    brillos = blancura.tobytes()
    dentro = [brillos[p] for p in region]
    marcados = bytearray(len(datos))
    for p in region:
        marcados[p] = 1
    fuera = [brillos[p] for p in range(len(brillos)) if not marcados[p]]
    if fuera and (sum(dentro) / len(dentro) - sum(fuera) / len(fuera)) < CONTRASTE_MINIMO:
        return Deteccion(None, "poco-contraste")

    return Deteccion(tuple((x / ancho, y / alto) for x, y in cuadro))


# --- Corregir la perspectiva ------------------------------------------------


def _distancia(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def comprobar_esquinas(esquinas, ancho: int, alto: int) -> list[tuple[float, float]]:
    """Las esquinas en píxeles, o `ComposicionInvalida` si no forman una hoja."""
    try:
        puntos = [(float(x) * ancho, float(y) * alto) for x, y in esquinas]
    except (TypeError, ValueError) as fallo:
        raise ComposicionInvalida("Las esquinas no son números.") from fallo
    if len(puntos) != 4:
        raise ComposicionInvalida("Hacen falta las cuatro esquinas de la hoja.")
    if any(not (0 <= x <= ancho and 0 <= y <= alto) for x, y in puntos):
        raise ComposicionInvalida("Una esquina cae fuera de la foto.")
    if not _es_convexo(puntos):
        raise ComposicionInvalida(
            "Las esquinas no forman una hoja: se cruzan o no van en el orden arriba a la "
            "izquierda, arriba a la derecha, abajo a la derecha, abajo a la izquierda."
        )
    if abs(_area(puntos)) < AREA_MINIMA_A_MANO * ancho * alto:
        raise ComposicionInvalida("Las esquinas encierran muy poco de la foto.")
    return puntos


def proporcion_de_la_hoja(puntos, ancho: int, alto: int) -> float:
    """Ancho entre alto de la hoja real, a partir de su cuadrilátero en la foto.

    Zhang y He, «Whiteboard scanning and image enhancement» (2007), con el punto principal en el
    centro de la foto. Cae a la media de los lados si el cálculo no es creíble.
    """
    tl, tr, br, bl = puntos
    por_lados = (_distancia(tl, tr) + _distancia(bl, br)) / (
        _distancia(tl, bl) + _distancia(tr, br)
    )
    cx, cy = ancho / 2, alto / 2
    m1, m2, m3, m4 = ((x - cx, y - cy, 1.0) for x, y in (tl, tr, bl, br))

    def cruz(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def punto(a, b) -> float:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    base = cruz(m1, m4)
    divisor2 = punto(cruz(m2, m4), m3)
    divisor3 = punto(cruz(m3, m4), m2)
    if abs(divisor2) < 1e-12 or abs(divisor3) < 1e-12:
        return por_lados
    k2 = punto(base, m3) / divisor2
    k3 = punto(base, m2) / divisor3
    n2 = tuple(k2 * a - b for a, b in zip(m2, m1, strict=True))
    n3 = tuple(k3 * a - b for a, b in zip(m3, m1, strict=True))
    if abs(n2[2] * n3[2]) < 1e-9:  # sin perspectiva: los lados ya dicen la proporción
        return por_lados
    focal2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
    if not math.isfinite(focal2) or focal2 <= 0:
        return por_lados
    focal = focal2

    def norma2(n) -> float:
        return (n[0] ** 2 + n[1] ** 2) / focal + n[2] ** 2

    divisor = norma2(n3)
    if divisor <= 0:
        return por_lados
    razon = math.sqrt(max(norma2(n2), 0.0) / divisor)
    if not math.isfinite(razon) or not 0.2 <= razon <= 5 or not 0.6 <= razon / por_lados <= 1.7:
        return por_lados
    return razon


def _homografia(salida, entrada) -> list[float]:
    """Coeficientes de `Image.transform(PERSPECTIVE)`: de cada punto de salida a uno de entrada."""
    matriz: list[list[float]] = []
    for (x, y), (u, v) in zip(salida, entrada, strict=True):
        matriz.append([x, y, 1, 0, 0, 0, -x * u, -y * u, u])
        matriz.append([0, 0, 0, x, y, 1, -x * v, -y * v, v])
    n = 8
    for col in range(n):
        pivote = max(range(col, n), key=lambda f: abs(matriz[f][col]))
        if abs(matriz[pivote][col]) < 1e-12:
            raise ComposicionInvalida("Las esquinas no permiten enderezar la hoja.")
        matriz[col], matriz[pivote] = matriz[pivote], matriz[col]
        for fila in range(n):
            if fila != col:
                factor = matriz[fila][col] / matriz[col][col]
                for j in range(col, n + 1):
                    matriz[fila][j] -= factor * matriz[col][j]
    return [matriz[i][n] / matriz[i][i] for i in range(n)]


def enderezar(imagen, esquinas):
    """La hoja recortada y de frente, una imagen rectangular. `esquinas` van como fracciones."""
    from PIL import Image

    ancho, alto = imagen.size
    puntos = comprobar_esquinas(esquinas, ancho, alto)
    tl, tr, br, bl = puntos
    arriba, abajo = _distancia(tl, tr), _distancia(bl, br)
    izquierda, derecha = _distancia(tl, bl), _distancia(tr, br)
    razon = proporcion_de_la_hoja(puntos, ancho, alto)

    ancho_origen = max(arriba, abajo)
    alto_origen = max(izquierda, derecha)
    ancho_sal = max(ancho_origen, alto_origen * razon)
    alto_sal = ancho_sal / razon
    tope = LADO_MAXIMO_DE_PAGINA / max(ancho_sal, alto_sal)
    if tope < 1:
        ancho_sal, alto_sal = ancho_sal * tope, alto_sal * tope

    # Si la salida es bastante más chica que el origen se reduce antes: el muestreo bicúbico de
    # `transform` no promedia, y reducir a saltos deja dientes en el texto.
    reduccion = min(1.0, ancho_sal / ancho_origen, alto_sal / alto_origen)
    if reduccion < 0.75:
        imagen = imagen.resize(
            (max(1, round(ancho * reduccion)), max(1, round(alto * reduccion))),
            Image.Resampling.LANCZOS,
        )
        puntos = [(x * imagen.width / ancho, y * imagen.height / alto) for x, y in puntos]

    ancho_final, alto_final = max(16, round(ancho_sal)), max(16, round(alto_sal))
    coeficientes = _homografia(
        [(0, 0), (ancho_final, 0), (ancho_final, alto_final), (0, alto_final)], puntos
    )
    return imagen.transform(
        (ancho_final, alto_final),
        Image.Transform.PERSPECTIVE,
        coeficientes,
        Image.Resampling.BICUBIC,
        fillcolor=(255, 255, 255),
    )


# --- Mejorar el contraste ---------------------------------------------------


def mejorar_documento(imagen):
    """Aclara el fondo y oscurece la tinta: de una foto con sombras, una hoja que parece escaneada.

    Estima la iluminación (el fondo) quitando los trazos con un filtro de máximo y suavizando, y
    la resta de la foto. Pensado para texto: un bloque oscuro grande queda en gris, no se pierde.
    """
    from PIL import Image, ImageChops, ImageFilter, ImageOps

    ancho, alto = imagen.size
    paso = max(1, max(ancho, alto) // 400)
    chica = imagen.reduce(paso) if paso > 1 else imagen.copy()
    fondo = chica.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(5))
    fondo = fondo.point(lambda v: max(v, FONDO_MINIMO)).resize(
        imagen.size, Image.Resampling.BILINEAR
    )
    nivelada = ImageChops.subtract(imagen, fondo, 1.0, 255)
    return ImageOps.autocontrast(nivelada, cutoff=1)


# --- El PDF -----------------------------------------------------------------


def _pagina_pdf(ancho_px: int, alto_px: int, tamano: str):
    """`(ancho_pt, alto_pt, x, y, ancho_dibujo, alto_dibujo)` de una página y su imagen."""
    if tamano == "hoja":
        ancho_pt, alto_pt = ancho_px / PPP_DE_HOJA * 72, alto_px / PPP_DE_HOJA * 72
        return ancho_pt, alto_pt, 0.0, 0.0, ancho_pt, alto_pt
    corto, largo = A4_PT
    ancho_pt, alto_pt = (largo, corto) if ancho_px > alto_px else (corto, largo)
    ajuste = min(ancho_pt / ancho_px, alto_pt / alto_px)
    dibujo = (ancho_px * ajuste, alto_px * ajuste)
    return ancho_pt, alto_pt, (ancho_pt - dibujo[0]) / 2, (alto_pt - dibujo[1]) / 2, *dibujo


def _escribir_pdf(paginas: list[tuple[Path, int, int]], destino: Path, tamano: str) -> None:
    from reportlab.pdfgen import canvas

    lienzo = canvas.Canvas(str(destino), pageCompression=1)
    for ruta, ancho_px, alto_px in paginas:
        ancho_pt, alto_pt, x, y, ancho_d, alto_d = _pagina_pdf(ancho_px, alto_px, tamano)
        lienzo.setPageSize((ancho_pt, alto_pt))
        lienzo.drawImage(str(ruta), x, y, width=ancho_d, height=alto_d)
        lienzo.showPage()
    lienzo.save()


def _esquinas_de(valor) -> tuple[tuple[float, float], ...] | None:
    if valor is None:
        return None
    return tuple((float(x), float(y)) for x, y in valor)


def hojas_desde_opciones(opciones: list[dict] | None, cuantas: int) -> list[Hoja]:
    """Lo que la pantalla encola (`[{"modo": …, "esquinas": …}]`) como `Hoja`. Sin nada, `auto`."""
    if not opciones:
        return [Hoja() for _ in range(cuantas)]
    if len(opciones) != cuantas:
        raise ComposicionInvalida("Hay un número de fotos y otro de ajustes.")
    hojas = []
    for pedida in opciones:
        modo = pedida.get("modo", "auto")
        if modo not in MODOS:
            raise ComposicionInvalida(f"«{modo}» no es una forma de tratar la foto.")
        try:
            esquinas = _esquinas_de(pedida.get("esquinas"))
        except (TypeError, ValueError) as fallo:
            raise ComposicionInvalida("Las esquinas no son números.") from fallo
        hojas.append(Hoja(modo, esquinas))
    return hojas


def escanear(
    origenes: list[str | Path],
    destino: str | Path,
    hojas: list[Hoja] | None = None,
    *,
    mejorar: bool = False,
    tamano: str = "hoja",
    ocr: OpcionesDeOcr | None = None,
    progreso: Callable[[float], None] | None = None,
) -> Resultado:
    """Escribe un PDF con una página por foto, en el orden dado. Todo o nada."""
    from PIL import Image

    rutas = [Path(o) for o in origenes]
    destino = Path(destino)
    if not rutas:
        raise ComposicionInvalida("No indicó ninguna foto.")
    if len(rutas) > MAXIMO_HOJAS:
        raise ComposicionInvalida(f"El máximo son {MAXIMO_HOJAS} fotos por PDF.")
    if tamano not in TAMANOS:
        raise ComposicionInvalida(f"«{tamano}» no es un tamaño de página de los que se ofrecen.")
    hojas = hojas if hojas is not None else [Hoja() for _ in rutas]
    if len(hojas) != len(rutas):
        raise ComposicionInvalida("Hay un número de fotos y otro de ajustes.")
    for hoja in hojas:
        if hoja.modo not in MODOS:
            raise ComposicionInvalida(f"«{hoja.modo}» no es una forma de tratar la foto.")
        if hoja.modo == "esquinas" and not hoja.esquinas:
            raise ComposicionInvalida("Faltan las esquinas de una foto.")

    resultado = Resultado(paginas=len(rutas), con_ocr=ocr is not None)
    parte_de_imagen = 0.6 if ocr else 0.95

    try:
        with tempfile.TemporaryDirectory(prefix="aeroconvert-escaneo-") as carpeta:
            temporal = Path(carpeta)
            paginas: list[tuple[Path, int, int]] = []
            for numero, (ruta, hoja) in enumerate(zip(rutas, hojas, strict=True), start=1):
                imagen = abrir_derecha(ruta)
                esquinas = None
                tratamiento, motivo = ENTERA, ""
                if hoja.modo == "esquinas":
                    esquinas, tratamiento = hoja.esquinas, A_MANO
                elif hoja.modo == "auto":
                    hallada = detectar_hoja(imagen)
                    if hallada.esquinas:
                        esquinas, tratamiento = hallada.esquinas, RECORTADA
                    else:
                        motivo = hallada.motivo
                        resultado.avisos.append(
                            f"{ruta.name}: {hallada.explicacion} Se dejó la foto entera."
                        )
                pagina = imagen
                if esquinas:
                    try:
                        pagina = enderezar(imagen, esquinas)
                    except ComposicionInvalida as fallo:
                        raise ComposicionInvalida(f"{ruta.name}: {fallo}") from fallo
                    imagen.close()
                if mejorar:
                    mejorada = mejorar_documento(pagina)
                    pagina.close()
                    pagina = mejorada
                jpg = temporal / f"{numero:04d}.jpg"
                pagina.save(jpg, "JPEG", quality=CALIDAD_JPEG, optimize=True)
                paginas.append((jpg, *pagina.size))
                pagina.close()
                resultado.hojas.append(Tratada(ruta.name, tratamiento, motivo))
                if progreso is not None:
                    progreso(numero / len(rutas) * parte_de_imagen)

            if ocr is None:
                _escribir_pdf(paginas, destino, tamano)
            else:
                from . import ocr as ocr_mod

                sin_texto = temporal / "sin_texto.pdf"
                _escribir_pdf(paginas, sin_texto, tamano)

                def avance(fraccion: float) -> None:
                    if progreso is not None:
                        progreso(parte_de_imagen + (1 - parte_de_imagen) * fraccion)

                ocr_mod.reconocer(
                    sin_texto,
                    idioma=ocr.idioma,
                    destino=destino,
                    programa=ocr.programa,
                    progreso=avance,
                )
    except ComposicionInvalida:
        destino.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as fallo:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(f"No se pudo escribir el PDF: {fallo}") from fallo
    return resultado
