"""La vista previa de una libreta de puntos: dibujarlos **antes** de convertir.

## Para qué sirve de verdad

Para que el orden de columnas se vea, no se explique. `apps.formats.puntos` deduce el orden
del rango UTM y acierta, pero hay un caso en que no puede decidir -- las dos columnas caben
como este -- y entonces alguien tiene que elegir. Un dibujo resuelve esa duda en un segundo:
un levantamiento leído bien tiene forma de levantamiento, y leído al revés es un puñado de
puntos en diagonal perfecta o una nube sin sentido.

Es también la comprobación que pide el plan: «si aparecen en el Pacífico, el orden está mal».

## Dos detalles que, mal hechos, convierten el dibujo en una mentira

**1. El eje Y va al contrario.** En SVG la Y crece hacia abajo y el norte crece hacia arriba.
Sin invertirlo, el dibujo sale reflejado: un levantamiento que sube hacia el noreste se
enseña bajando hacia el sureste. Y como sigue pareciendo un levantamiento plausible, nadie
lo nota.

**2. La escala tiene que ser la misma en los dos ejes.** Estirar cada eje para llenar la
caja hace que una franja de 200 × 20 m se dibuje cuadrada. Quien mira una vista previa está
juzgando **la forma**, así que deformarla es peor que no dibujar nada.

## Y por qué no es un mapa con fondo

Porque la CSP de la familia es `'self'` y no hay CDN: un mapa base son teselas de un
servidor ajeno. Lo que se dibuja es la geometría propia, con las coordenadas al lado en
grados para quien quiera comprobarlas en otro sitio.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.formats import puntos as puntos_mod

#: Caja del dibujo, en unidades del `viewBox`. No son píxeles: el SVG escala.
ANCHO = 600.0
ALTO = 360.0

#: Margen para que un punto en el borde no quede cortado por la mitad.
MARGEN = 14.0

#: Radio del punto dibujado.
RADIO = 3.2

#: A partir de cuántos puntos se dejan de dibujar los rótulos. Cinco puntos de control
#: piden su nombre al lado; tres mil rótulos son una mancha negra.
MAXIMO_CON_ROTULO = 24


@dataclass(frozen=True)
class PuntoDibujado:
    x: float
    y: float
    identificador: str
    descripcion: str
    #: Para el `<title>`, que es lo que lee un lector de pantalla y lo que sale al pasar el
    #: ratón. Un dibujo sin esto no es accesible: es una imagen sin alternativa.
    titulo: str


@dataclass(frozen=True)
class DibujoDePuntos:
    puntos: tuple[PuntoDibujado, ...]
    ancho: float = ANCHO
    alto: float = ALTO
    radio: float = RADIO
    con_rotulos: bool = False
    #: Metros que mide el lado más largo del levantamiento. Va como pie del dibujo: un
    #: dibujo sin escala no dice si son 200 m o 200 km.
    lado_mayor_m: float = 0.0

    @property
    def hay_algo(self) -> bool:
        return bool(self.puntos)


def dibujo_de_puntos(cabecera: puntos_mod.CabeceraPuntos) -> DibujoDePuntos:
    """Convierte la muestra leída en coordenadas de dibujo."""
    muestra = cabecera.muestra
    if not muestra:
        return DibujoDePuntos(puntos=())

    norte_min, este_min, _ = cabecera.minimo
    norte_max, este_max, _ = cabecera.maximo

    ancho_m = este_max - este_min
    alto_m = norte_max - norte_min

    # Un solo punto, o todos en la misma línea: no hay extensión que escalar. Se dibuja en
    # el centro en vez de dividir por cero.
    utiles_x = ANCHO - 2 * MARGEN
    utiles_y = ALTO - 2 * MARGEN
    if ancho_m <= 0 and alto_m <= 0:
        escala = 1.0
    else:
        # **La misma escala en los dos ejes.** Manda el que se quede más apretado.
        escala = min(
            utiles_x / ancho_m if ancho_m > 0 else float("inf"),
            utiles_y / alto_m if alto_m > 0 else float("inf"),
        )

    # Centrado: lo que sobra se reparte a los dos lados.
    sobra_x = (utiles_x - ancho_m * escala) / 2 if ancho_m > 0 else utiles_x / 2
    sobra_y = (utiles_y - alto_m * escala) / 2 if alto_m > 0 else utiles_y / 2

    dibujados = []
    for punto in muestra:
        x = MARGEN + sobra_x + (punto.este_m - este_min) * escala
        # El menos es el detalle 1: en SVG la Y crece hacia abajo.
        y = ALTO - MARGEN - sobra_y - (punto.norte_m - norte_min) * escala
        etiqueta = punto.identificador or f"{punto.norte_m:.2f}, {punto.este_m:.2f}"
        titulo = (
            f"{etiqueta} · N {punto.norte_m:.3f} · E {punto.este_m:.3f} · cota {punto.cota_m:.3f}"
        )
        if punto.descripcion:
            titulo += f" · {punto.descripcion}"
        dibujados.append(
            PuntoDibujado(
                x=round(x, 2),
                y=round(y, 2),
                identificador=punto.identificador,
                descripcion=punto.descripcion,
                titulo=titulo,
            )
        )

    return DibujoDePuntos(
        puntos=tuple(dibujados),
        con_rotulos=len(dibujados) <= MAXIMO_CON_ROTULO,
        lado_mayor_m=round(max(ancho_m, alto_m), 1),
    )
