"""Conversión entre sRGB de 8 bits (`#rrggbb`) y OKLCH, para la paleta de `static/css/app.css`.

## Para qué existe

La paleta pasó de hexadecimal a `oklch(L C H)` (F9.5). OKLCH es perceptual: un cambio de `L` es un
cambio de luminosidad que **se ve** como tal, y `C` y `H` son croma y tono, así que «el mismo
color, un poco más claro» es tocar un número y no adivinar tres canales. Eso ahorra hacer a ojo
cada nueva variante de una familia.

Lo que **no** puede cambiar es lo que se ve. Este módulo sirve a dos cosas:

- `texto()` escribe un hex como `oklch(...)` con la precisión justa para que, al pintarlo, el
  navegador vuelva a dar **el mismo byte** de cada canal;
- `a_hex()` hace el camino contrario, y es lo que usan las pruebas de contraste de WCAG
  (`test_paleta.py`) para seguir calculando sobre sRGB.

Las matrices son las de Björn Ottosson (<https://bottosson.github.io/posts/oklab/>, dominio
público). La prueba de verdad no es esta fórmula contra sí misma sino **el navegador**: se pintó
cada token en un `<canvas>` y se leyó el píxel (ver `docs/PRUEBAS_CON_ORACULO.md`).
"""

from __future__ import annotations

import math

# Precisión de lo que se escribe en el CSS. Con 4 decimales de L, 4 de C y 2 de H, los 66 colores
# de la paleta vuelven al mismo byte en los tres canales (lo comprueba `test_oklch.py`).
DECIMALES_L = 4
DECIMALES_C = 4
DECIMALES_H = 2


def _a_lineal(canal: int) -> float:
    c = canal / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _de_lineal(valor: float) -> float:
    valor = max(0.0, min(1.0, valor))
    c = valor * 12.92 if valor <= 0.0031308 else 1.055 * valor ** (1 / 2.4) - 0.055
    return c * 255


def _rgb(hexadecimal: str) -> tuple[int, int, int]:
    crudo = hexadecimal.lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    return tuple(int(crudo[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def de_hex(hexadecimal: str) -> tuple[float, float, float]:
    """`#rrggbb` a `(L, C, H)`: L en 0..1, C en 0..~0,4 y H en grados 0..360."""
    r, g, b = (_a_lineal(c) for c in _rgb(hexadecimal))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    claridad = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    croma = math.hypot(a, b_)
    tono = math.degrees(math.atan2(b_, a)) % 360 if croma > 1e-7 else 0.0
    return claridad, croma, tono


def a_rgb(claridad: float, croma: float, tono: float) -> tuple[float, float, float]:
    """`(L, C, H)` a sRGB **sin redondear**, en 0..255 (puede salirse un poco si está fuera de
    gama; `a_hex` lo recorta como hace el navegador)."""
    a = croma * math.cos(math.radians(tono))
    b = croma * math.sin(math.radians(tono))
    l_ = (claridad + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (claridad - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (claridad - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    azul = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return _de_lineal(r), _de_lineal(g), _de_lineal(azul)


def a_hex(claridad: float, croma: float, tono: float) -> str:
    r, g, b = (round(c) for c in a_rgb(claridad, croma, tono))
    return f"#{r:02x}{g:02x}{b:02x}"


def texto(hexadecimal: str) -> str:
    """El hex como `oklch(L C H)`, listo para pegar en el CSS."""
    claridad, croma, tono = de_hex(hexadecimal)
    return f"oklch({claridad:.{DECIMALES_L}f} {croma:.{DECIMALES_C}f} {tono:.{DECIMALES_H}f})"


def de_texto(valor: str) -> str:
    """`oklch(0.4210 0.1820 340.50)` a `#rrggbb`. Levanta `ValueError` si no es eso."""
    import re

    encontrado = re.fullmatch(
        r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)", valor.strip(), re.IGNORECASE
    )
    if not encontrado:
        raise ValueError(f"No es un oklch(L C H) sin alfa: «{valor}»")
    return a_hex(*(float(g) for g in encontrado.groups()))
