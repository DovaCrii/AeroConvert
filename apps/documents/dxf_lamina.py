"""Un plano DXF a una **lámina** PDF (o SVG), a escala y sin abrir un programa de dibujo.

Se lee con `ezdxf` (MIT, Python puro) y se dibuja con `reportlab`: líneas, polilíneas (con
arcos), círculos, arcos, elipses, splines, textos y puntos, con el color de su capa. Los bloques
(`INSERT`) y las cotas (`DIMENSION`) se expanden.

## Lo que no se hace en silencio

- **Lo que no se dibuja se cuenta, por tipo** (`HATCH`, `IMAGE`, `3DFACE`…): una lámina que parece
  completa y le falta el sombreado de los lotes es peor que una que lo dice.
- **La escala solo se dice si el dibujo declara sus unidades** (`$INSUNITS`). Sin ellas, la lámina
  sale **ajustada al papel** y no trae «1:500» inventado: la escala, como el CRS, no se adivina.
- Las capas apagadas o congeladas no se dibujan, como en el programa de dibujo, y se cuenta cuántas.
- Un DWG no se lee aquí: se pasa antes a DXF con el conversor de DWG (ODA), que es otra herramienta.

## Qué se garantiza

El dibujo ocupa la lámina **centrado y con margen fijo** (`MARGEN_MM`): lo que hay de punta a punta
del plano toca ese margen en el eje que manda. La prueba lo mide leyendo la lámina con PDFium, no
repitiendo la cuenta que la dibujó.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from pathlib import Path

from .composicion import ComposicionInvalida

PAPELES_MM = {
    "a4": (297.0, 210.0),
    "a3": (420.0, 297.0),
    "a2": (594.0, 420.0),
    "a1": (841.0, 594.0),
    "a0": (1189.0, 841.0),
}

ETIQUETAS_PAPEL = {
    "a4": "A4",
    "a3": "A3",
    "a2": "A2",
    "a1": "A1",
    "a0": "A0",
}

FORMATOS = {"pdf": "PDF — para imprimir", "svg": "SVG — para abrir en un editor de dibujo"}

MARGEN_MM = 10.0

#: Unidades de dibujo (`$INSUNITS`) → milímetros por unidad. Las demás: «sin declarar».
MM_POR_UNIDAD = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}

#: Tipos de entidad que se dibujan por su trayectoria.
_POR_TRAYECTORIA = {"LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "LWPOLYLINE", "POLYLINE"}

_PROFUNDIDAD_MAXIMA = 6
_PUNTOS_MAXIMOS = 3_000_000


@dataclass
class Trazo:
    puntos: list[tuple[float, float]]
    cerrado: bool
    color: tuple[int, int, int]


@dataclass
class Texto:
    x: float
    y: float
    altura: float
    texto: str
    rotacion: float
    color: tuple[int, int, int]


@dataclass
class Dibujo:
    trazos: list[Trazo] = field(default_factory=list)
    textos: list[Texto] = field(default_factory=list)
    puntos: list[tuple[float, float, tuple[int, int, int]]] = field(default_factory=list)
    omitidas: dict[str, int] = field(default_factory=dict)
    dibujadas: int = 0
    capas_apagadas: int = 0
    unidades: int = 0


@dataclass(frozen=True)
class Lamina:
    entidades: int
    trazos: int
    omitidas: dict[str, int]
    capas_apagadas: int
    papel: str
    ancho_mm: float
    alto_mm: float
    escala: str  # «1:500», o vacío si el dibujo no declara sus unidades
    ajuste: float  # milímetros de papel por unidad de dibujo


def _rgb(entidad, documento) -> tuple[int, int, int]:
    from ezdxf import colors

    if entidad.dxf.hasattr("true_color"):
        r, g, b = colors.int2rgb(entidad.dxf.true_color)
        return _contra_blanco((r, g, b))
    indice = entidad.dxf.color if entidad.dxf.hasattr("color") else 256
    if indice in (0, 256):  # DEL BLOQUE o DE LA CAPA
        try:
            indice = abs(documento.layers.get(entidad.dxf.layer).color)
        except Exception:  # noqa: BLE001 - capa que no está en la tabla: el color estándar
            indice = 7
    if not 1 <= indice <= 255:
        indice = 7
    return _contra_blanco(colors.int2rgb(colors.DXF_DEFAULT_COLORS[indice]))


def _contra_blanco(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """El blanco (el «7» de AutoCAD) se dibuja negro: sobre papel blanco no se vería."""
    return (0, 0, 0) if sum(rgb) > 3 * 235 else rgb


def _capa_visible(entidad, documento) -> bool:
    try:
        capa = documento.layers.get(entidad.dxf.layer)
    except Exception:  # noqa: BLE001 - sin capa en la tabla: se dibuja
        return True
    return not (capa.is_off() or capa.is_frozen())


def _recorrer(entidades, documento, dibujo: Dibujo, distancia: float, profundidad: int = 0):
    from ezdxf import path

    for e in entidades:
        tipo = e.dxftype()
        if not _capa_visible(e, documento):
            dibujo.capas_apagadas += 1
            continue
        if tipo in ("INSERT", "DIMENSION", "LEADER", "MLEADER"):
            if profundidad >= _PROFUNDIDAD_MAXIMA:
                dibujo.omitidas[tipo] = dibujo.omitidas.get(tipo, 0) + 1
                continue
            try:
                hijas = list(e.virtual_entities())
            except Exception:  # noqa: BLE001 - un bloque que no se expande se cuenta, no se calla
                dibujo.omitidas[tipo] = dibujo.omitidas.get(tipo, 0) + 1
                continue
            _recorrer(hijas, documento, dibujo, distancia, profundidad + 1)
            dibujo.dibujadas += 1
            continue
        color = _rgb(e, documento)
        if tipo in _POR_TRAYECTORIA:
            try:
                trayecto = path.make_path(e)
                trozos = list(trayecto.sub_paths())
            except Exception:  # noqa: BLE001 - p. ej. una malla 3D: no es una trayectoria plana
                dibujo.omitidas[tipo] = dibujo.omitidas.get(tipo, 0) + 1
                continue
            for trozo in trozos:
                vertices = [(v.x, v.y) for v in trozo.flattening(distancia, segments=16)]
                if len(vertices) >= 2:
                    dibujo.trazos.append(Trazo(vertices, bool(trozo.is_closed), color))
            dibujo.dibujadas += 1
        elif tipo == "POINT":
            p = e.dxf.location
            dibujo.puntos.append((p.x, p.y, color))
            dibujo.dibujadas += 1
        elif tipo in ("TEXT", "MTEXT"):
            texto = e.plain_text() if tipo == "MTEXT" else e.dxf.text
            if not str(texto).strip():
                continue
            origen = e.dxf.insert
            altura = e.dxf.char_height if tipo == "MTEXT" else e.dxf.height
            giro = e.dxf.get("rotation", 0.0)
            dibujo.textos.append(
                Texto(origen.x, origen.y, float(altura or 1.0), texto, giro, color)
            )
            dibujo.dibujadas += 1
        else:
            dibujo.omitidas[tipo] = dibujo.omitidas.get(tipo, 0) + 1


def _caja(dibujo: Dibujo) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for t in dibujo.trazos:
        xs += [p[0] for p in t.puntos]
        ys += [p[1] for p in t.puntos]
    for x, y, _ in dibujo.puntos:
        xs.append(x)
        ys.append(y)
    for t in dibujo.textos:
        largo = t.altura * 0.6 * len(t.texto)
        xs += [t.x, t.x + largo * math.cos(math.radians(t.rotacion))]
        ys += [t.y, t.y + largo * math.sin(math.radians(t.rotacion)), t.y + t.altura]
    if not xs:
        raise ComposicionInvalida("El plano no trae nada que se pueda dibujar.")
    return min(xs), min(ys), max(xs), max(ys)


def leer(ruta: str | Path) -> Dibujo:
    import ezdxf
    from ezdxf import bbox

    ruta = Path(ruta)
    if ruta.suffix.lower() == ".dwg":
        raise ComposicionInvalida(
            "Un DWG no se lee aquí: páselo antes a DXF desde «Convertir», con el conversor de DWG."
        )
    try:
        documento = ezdxf.readfile(str(ruta))
    except (OSError, ezdxf.DXFError, UnicodeDecodeError) as fallo:
        raise ComposicionInvalida(f"{ruta.name} no se lee como un DXF: {fallo}") from fallo

    espacio = documento.modelspace()
    extension = bbox.extents(espacio, fast=True)
    if not extension.has_data:
        raise ComposicionInvalida("El plano no trae nada que se pueda dibujar.")
    mayor = max(extension.size.x, extension.size.y, 1e-9)
    dibujo = Dibujo(unidades=int(documento.header.get("$INSUNITS", 0) or 0))
    _recorrer(espacio, documento, dibujo, distancia=mayor / 5000)
    if sum(len(t.puntos) for t in dibujo.trazos) > _PUNTOS_MAXIMOS:
        raise ComposicionInvalida("El plano es demasiado denso para dibujarlo en una lámina.")
    if not (dibujo.trazos or dibujo.textos or dibujo.puntos):
        raise ComposicionInvalida("El plano no trae nada que se pueda dibujar.")
    return dibujo


def _colocar(dibujo: Dibujo, papel: str) -> tuple[float, float, float, float, float]:
    """(ancho, alto, escala, desplazamientos x e y) con el dibujo centrado en la lámina."""
    if papel not in PAPELES_MM:
        raise ComposicionInvalida(f"«{papel}» no es un papel de los que se ofrecen.")
    x0, y0, x1, y1 = _caja(dibujo)
    ancho_d, alto_d = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    mayor, menor = PAPELES_MM[papel]
    ancho, alto = (mayor, menor) if ancho_d >= alto_d else (menor, mayor)
    escala = min((ancho - 2 * MARGEN_MM) / ancho_d, (alto - 2 * MARGEN_MM) / alto_d)
    dx = MARGEN_MM + ((ancho - 2 * MARGEN_MM) - ancho_d * escala) / 2 - x0 * escala
    dy = MARGEN_MM + ((alto - 2 * MARGEN_MM) - alto_d * escala) / 2 - y0 * escala
    return ancho, alto, escala, dx, dy


def _escala_texto(unidades: int, ajuste: float) -> str:
    mm = MM_POR_UNIDAD.get(unidades)
    if not mm:
        return ""
    return f"1:{round(mm / ajuste):,}".replace(",", ".")


def _escribir_pdf(dibujo: Dibujo, destino: Path, ancho, alto, escala, dx, dy) -> None:
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    lienzo = canvas.Canvas(str(destino), pagesize=(ancho * mm, alto * mm), pageCompression=1)
    lienzo.setLineWidth(0.25)
    lienzo.setLineJoin(1)
    for t in dibujo.trazos:
        lienzo.setStrokeColorRGB(*(c / 255 for c in t.color))
        ruta = lienzo.beginPath()
        primero = t.puntos[0]
        ruta.moveTo((primero[0] * escala + dx) * mm, (primero[1] * escala + dy) * mm)
        for x, y in t.puntos[1:]:
            ruta.lineTo((x * escala + dx) * mm, (y * escala + dy) * mm)
        if t.cerrado:
            ruta.close()
        lienzo.drawPath(ruta, stroke=1, fill=0)
    for x, y, color in dibujo.puntos:
        lienzo.setFillColorRGB(*(c / 255 for c in color))
        lienzo.circle((x * escala + dx) * mm, (y * escala + dy) * mm, 0.4 * mm, stroke=0, fill=1)
    for t in dibujo.textos:
        lienzo.saveState()
        lienzo.setFillColorRGB(*(c / 255 for c in t.color))
        lienzo.translate((t.x * escala + dx) * mm, (t.y * escala + dy) * mm)
        lienzo.rotate(t.rotacion)
        lienzo.setFont("Helvetica", max(t.altura * escala * mm, 1.0))
        lienzo.drawString(0, 0, t.texto.encode("cp1252", "replace").decode("cp1252"))
        lienzo.restoreState()
    lienzo.showPage()
    lienzo.save()


def _color_svg(c: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def _escribir_svg(dibujo: Dibujo, destino: Path, ancho, alto, escala, dx, dy) -> None:
    def xy(x: float, y: float) -> str:
        return f"{x * escala + dx:.3f},{alto - (y * escala + dy):.3f}"

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}mm" height="{alto}mm" '
        f'viewBox="0 0 {ancho} {alto}">',
        '<g fill="none" stroke-width="0.25" stroke-linejoin="round">',
    ]
    for t in dibujo.trazos:
        orden = "M" + " L".join(xy(x, y) for x, y in t.puntos) + (" Z" if t.cerrado else "")
        partes.append(f'<path d="{orden}" stroke="{_color_svg(t.color)}"/>')
    for x, y, color in dibujo.puntos:
        cx, cy = xy(x, y).split(",")
        partes.append(
            f'<circle cx="{cx}" cy="{cy}" r="0.4" fill="{_color_svg(color)}" stroke="none"/>'
        )
    partes.append("</g>")
    for t in dibujo.textos:
        px, py = xy(t.x, t.y).split(",")
        partes.append(
            f'<text x="{px}" y="{py}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="{max(t.altura * escala, 0.5):.3f}" fill="{_color_svg(t.color)}" '
            f'transform="rotate({-t.rotacion:.3f} {px} {py})">{html.escape(t.texto)}</text>'
        )
    partes.append("</svg>\n")
    destino.write_text("".join(partes), encoding="utf-8")


def convertir(origen: str | Path, destino: str | Path, *, papel: str = "a3", formato: str = "pdf"):
    """Escribe la lámina en `destino` y dice qué se dibujó y qué no."""
    if formato not in FORMATOS:
        raise ComposicionInvalida(f"«{formato}» no es un formato de salida de los que se ofrecen.")
    dibujo = leer(origen)
    ancho, alto, escala, dx, dy = _colocar(dibujo, papel)
    destino = Path(destino)
    if formato == "pdf":
        _escribir_pdf(dibujo, destino, ancho, alto, escala, dx, dy)
    else:
        _escribir_svg(dibujo, destino, ancho, alto, escala, dx, dy)
    return Lamina(
        entidades=dibujo.dibujadas,
        trazos=len(dibujo.trazos),
        omitidas=dict(sorted(dibujo.omitidas.items())),
        capas_apagadas=dibujo.capas_apagadas,
        papel=papel,
        ancho_mm=ancho,
        alto_mm=alto,
        escala=_escala_texto(dibujo.unidades, escala),
        ajuste=escala,
    )
