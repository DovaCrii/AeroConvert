"""Escanear con el teléfono (F14.12).

## El oráculo, y por qué no es la propia lectura

Hay una **hoja sintética de geometría conocida**: 210 × 297 mm con un rectángulo negro de
referencia en un sitio sabido (de 40 a 170 mm de ancho y de 70 a 130 mm de alto) y unas frases.
Se «fotografía» con una **cámara de agujero con la proyección calculada aquí a mano**: foco de
1 400 px, la hoja inclinada, girada y torcida, sobre una mesa. La foto se pinta recorriendo cada
punto del cuadro y buscando qué punto de la hoja ve (la intersección del rayo con el plano de la
hoja), **sin usar ninguna función del módulo**: si el módulo resolviera mal la homografía, la
prueba no cancelaría el error.

La comprobación la hace **PDFium** —el motor de Chrome, que no escribió el PDF—: dibuja la página
y se mide el rectángulo de referencia. Si la perspectiva está bien corregida, la página es
rectangular con la proporción de la hoja, los bordes del rectángulo son paralelos a los de la
página y quedan donde estaban en la hoja, con un margen del 2 % del tamaño de la página.

Con Tesseract (`@pytest.mark.oraculo`, se salta si no está) se lee una frase de control de la
hoja desde el PDF que entrega la herramienta con el reconocimiento pedido.
"""

from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont

from apps.documents import escanear, motor, ocr, tarea

pytestmark = pytest.mark.django_db

# --- La hoja y la cámara ----------------------------------------------------

#: La hoja: 210 × 297 mm a 6 px por mm.
PX_POR_MM = 6
HOJA_MM = (210, 297)
#: El rectángulo de referencia, en mm sobre la hoja: (izquierda, arriba, derecha, abajo).
REFERENCIA_MM = (40, 70, 170, 130)
FRASE = "CONTROL 7391 AEROCONVERT"

FOTO = (1600, 1200)
FOCO_PX = 1400.0


def _hoja_sintetica(referencia_mm=REFERENCIA_MM, fondo=(250, 250, 247, 255)) -> Image.Image:
    ancho, alto = (m * PX_POR_MM for m in HOJA_MM)
    hoja = Image.new("RGBA", (ancho, alto), fondo)
    dibujo = ImageDraw.Draw(hoja)
    izq, arr, der, aba = (m * PX_POR_MM for m in referencia_mm)
    dibujo.rectangle((izq, arr, der, aba), fill=(15, 15, 15, 255))
    letra = ImageFont.load_default(size=64)
    dibujo.text((120, 150), FRASE, fill=(10, 10, 10, 255), font=letra)
    dibujo.text((120, 1100), "Hoja de prueba sin datos reales", fill=(10, 10, 10, 255), font=letra)
    dibujo.text((120, 1250), "Segunda linea de texto corrido", fill=(10, 10, 10, 255), font=letra)
    return hoja


def _rotacion(cabeceo: float, guinada: float, alabeo: float):
    """R = Rz(alabeo) · Ry(guiñada) · Rx(cabeceo), en grados, como lista de filas."""
    a, b, c = (math.radians(g) for g in (cabeceo, guinada, alabeo))
    rx = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    ry = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
    rz = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]

    def por(m, n):
        return [[sum(m[i][k] * n[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return por(rz, por(ry, rx))


def _proyectar(R, distancia_mm: float, x_mm: float, y_mm: float) -> tuple[float, float]:
    """Dónde cae en la foto el punto (x, y) de la hoja, con el centro de la hoja en el eje."""
    px = R[0][0] * x_mm + R[0][1] * y_mm
    py = R[1][0] * x_mm + R[1][1] * y_mm
    pz = R[2][0] * x_mm + R[2][1] * y_mm + distancia_mm
    return FOTO[0] / 2 + FOCO_PX * px / pz, FOTO[1] / 2 + FOCO_PX * py / pz


def _foto_de_la_hoja(cabeceo=28.0, guinada=-16.0, alabeo=5.0, distancia_mm=560.0, hoja=None):
    """La foto, y las cuatro esquinas de la hoja en ella (px), arriba-izquierda primero."""
    R = _rotacion(cabeceo, guinada, alabeo)
    hoja = hoja if hoja is not None else _hoja_sintetica()
    medio = (HOJA_MM[0] / 2, HOJA_MM[1] / 2)
    normal = (R[0][2], R[1][2], R[2][2])

    def de_la_hoja(u: float, v: float) -> tuple[float, float]:
        """Qué punto de la hoja (px de la hoja) ve el píxel (u, v): rayo contra plano."""
        rayo = (u - FOTO[0] / 2, v - FOTO[1] / 2, FOCO_PX)
        t = normal[2] * distancia_mm / sum(n * d for n, d in zip(normal, rayo, strict=True))
        p = (t * rayo[0], t * rayo[1], t * rayo[2] - distancia_mm)
        x = R[0][0] * p[0] + R[1][0] * p[1] + R[2][0] * p[2]
        y = R[0][1] * p[0] + R[1][1] * p[1] + R[2][1] * p[2]
        return (x + medio[0]) * PX_POR_MM, (y + medio[1]) * PX_POR_MM

    paso = 40
    malla = []
    for y0 in range(0, FOTO[1], paso):
        for x0 in range(0, FOTO[0], paso):
            x1, y1 = x0 + paso, y0 + paso
            nw, sw, se, ne = (de_la_hoja(*p) for p in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)))
            malla.append(((x0, y0, x1, y1), (*nw, *sw, *se, *ne)))
    vista = hoja.transform(FOTO, Image.Transform.MESH, malla, Image.Resampling.BILINEAR)

    mesa = Image.new("RGBA", FOTO, (92, 64, 42, 255))
    sombra = ImageDraw.Draw(mesa)
    for y in range(0, FOTO[1], 9):
        sombra.line((0, y, FOTO[0], y + 14), fill=(80 + (y % 5) * 3, 56, 36, 255), width=2)
    mesa.alpha_composite(vista)

    esquinas = [
        _proyectar(R, distancia_mm, x - medio[0], y - medio[1])
        for x, y in ((0, 0), (HOJA_MM[0], 0), HOJA_MM, (0, HOJA_MM[1]))
    ]
    return mesa.convert("RGB"), esquinas


def _guardar_foto(carpeta: Path, nombre: str = "hoja1.jpg", exif=None, **geometria) -> Path:
    foto, _ = _foto_de_la_hoja(**geometria)
    ruta = carpeta / nombre
    if exif is not None:
        foto.save(ruta, "JPEG", quality=92, exif=exif)
    else:
        foto.save(ruta, "JPEG", quality=92)
    return ruta


# --- Medir lo que PDFium dibuja ---------------------------------------------


def _dibujar_pagina(pdf: Path, numero: int = 0, alto_px: int = 520):
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(pdf))
    try:
        pagina = documento[numero]
        ancho_pt, alto_pt = pagina.get_size()
        imagen = pagina.render(scale=alto_px / alto_pt).to_pil().convert("L")
    finally:
        documento.close()
    return imagen, ancho_pt, alto_pt


def _rectangulo_oscuro(imagen: Image.Image):
    """El mayor bloque oscuro: se borra el texto con una apertura (los trazos son finos)."""
    from PIL import ImageFilter

    oscuro = imagen.point(lambda v: 255 if v < 90 else 0)
    abierto = oscuro.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MaxFilter(9))
    caja = abierto.getbbox()
    return abierto, caja


def _medidas_del_rectangulo(pdf: Path):
    imagen, ancho_pt, alto_pt = _dibujar_pagina(pdf)
    abierto, caja = _rectangulo_oscuro(imagen)
    assert caja is not None, "no hay rectángulo de referencia en la página"
    izq, arr, der, aba = caja
    ancho, alto = imagen.size

    # Dónde empieza el borde izquierdo y el superior en dos sitios distintos del rectángulo:
    # si la perspectiva no está corregida, no son iguales.
    def borde_izquierdo(fila):
        xs = [x for x in range(ancho) if abierto.getpixel((x, fila))]
        return xs[0]

    def borde_derecho(fila):
        xs = [x for x in range(ancho) if abierto.getpixel((x, fila))]
        return xs[-1]

    def borde_superior(col):
        ys = [y for y in range(alto) if abierto.getpixel((col, y))]
        return ys[0]

    def borde_inferior(col):
        ys = [y for y in range(alto) if abierto.getpixel((col, y))]
        return ys[-1]

    cerca_arriba, cerca_abajo = arr + 6, aba - 6
    cerca_izq, cerca_der = izq + 6, der - 6
    return {
        "caja": caja,
        "tamano_px": (ancho, alto),
        "tamano_pt": (ancho_pt, alto_pt),
        "izq_arriba": borde_izquierdo(cerca_arriba),
        "izq_abajo": borde_izquierdo(cerca_abajo),
        "der_arriba": borde_derecho(cerca_arriba),
        "der_abajo": borde_derecho(cerca_abajo),
        "arr_izq": borde_superior(cerca_izq),
        "arr_der": borde_superior(cerca_der),
        "aba_izq": borde_inferior(cerca_izq),
        "aba_der": borde_inferior(cerca_der),
    }


def _sha_y_mtime(ruta: Path):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestLaGeometriaDeLaPrueba:
    """Antes de fiarse del oráculo, que el oráculo esté bien: la foto tiene que ser una foto."""

    def test_la_hoja_se_ve_torcida_y_en_perspectiva(self):
        _, esquinas = _foto_de_la_hoja()
        (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = esquinas
        arriba, abajo = trx - tlx, brx - blx
        assert abs(arriba - abajo) > 80, "sin perspectiva la prueba no prueba nada"
        assert abs(tly - try_) > 30
        assert all(0 < x < FOTO[0] and 0 < y < FOTO[1] for x, y in esquinas)


# --- Fotos de prueba, hechas una vez ----------------------------------------


@pytest.fixture(scope="module")
def jpeg_de_la_hoja() -> bytes:
    import io

    foto, _ = _foto_de_la_hoja()
    buffer = io.BytesIO()
    foto.save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


@pytest.fixture
def hoja1(tmp_path, jpeg_de_la_hoja) -> Path:
    ruta = tmp_path / "hoja1.jpg"
    ruta.write_bytes(jpeg_de_la_hoja)
    return ruta


def _esquinas_reales() -> list[tuple[float, float]]:
    _, esquinas = _foto_de_la_hoja()
    return [(x / FOTO[0], y / FOTO[1]) for x, y in esquinas]


def _cerca(medido: float, esperado: float, tamano: float, margen: float = 0.02) -> bool:
    """Dentro del `margen` (el 2 % por omisión) del tamaño de la página."""
    return abs(medido - esperado) <= margen * tamano


def _comprobar_pagina_derecha(pdf: Path, numero: int = 0):
    """El oráculo: PDFium dibuja la página y se mide el rectángulo de referencia."""
    medidas = _medidas_del_rectangulo(pdf)
    ancho, alto = medidas["tamano_px"]
    izq, arr, der, aba = medidas["caja"]
    esperado = REFERENCIA_MM
    # Dónde debería caer cada borde del rectángulo, calculado de la hoja y no de la salida.
    # (La caja sale de una apertura simétrica: no sesga ningún lado.)
    assert _cerca(izq, esperado[0] / HOJA_MM[0] * ancho, ancho), ("izquierda", medidas)
    assert _cerca(der, esperado[2] / HOJA_MM[0] * ancho, ancho), ("derecha", medidas)
    assert _cerca(arr, esperado[1] / HOJA_MM[1] * alto, alto), ("arriba", medidas)
    assert _cerca(aba, esperado[3] / HOJA_MM[1] * alto, alto), ("abajo", medidas)
    # Paralelos: el mismo borde medido en dos sitios distintos del rectángulo.
    assert _cerca(medidas["izq_arriba"], medidas["izq_abajo"], ancho), medidas
    assert _cerca(medidas["der_arriba"], medidas["der_abajo"], ancho), medidas
    assert _cerca(medidas["arr_izq"], medidas["arr_der"], alto), medidas
    assert _cerca(medidas["aba_izq"], medidas["aba_der"], alto), medidas
    return medidas


class TestLaPaginaQuedaRectangular:
    """El oráculo del plan: bordes paralelos y en su sitio, con el 2 % de margen."""

    def test_con_perspectiva_la_pagina_sale_rectangular_y_con_la_proporcion_de_la_hoja(
        self, tmp_path, hoja1
    ):
        destino = tmp_path / "salida.pdf"
        resultado = escanear.escanear([hoja1], destino)
        assert resultado.paginas == 1
        assert [h.tratamiento for h in resultado.hojas] == [escanear.RECORTADA]
        assert resultado.avisos == []
        medidas = _comprobar_pagina_derecha(destino)
        ancho_pt, alto_pt = medidas["tamano_pt"]
        assert abs(ancho_pt / alto_pt - HOJA_MM[0] / HOJA_MM[1]) <= 0.02 * (HOJA_MM[0] / HOJA_MM[1])

    def test_en_a4_la_pagina_mide_a4_y_el_rectangulo_sigue_en_su_sitio(self, tmp_path, hoja1):
        destino = tmp_path / "a4.pdf"
        escanear.escanear([hoja1], destino, tamano="a4")
        medidas = _comprobar_pagina_derecha(destino)
        ancho_pt, alto_pt = medidas["tamano_pt"]
        assert (round(ancho_pt), round(alto_pt)) == (595, 842)

    def test_la_orientacion_exif_se_conserva(self, tmp_path):
        """La foto guardada de lado con su marca EXIF (6) sale igual de derecha que la normal."""
        foto, _ = _foto_de_la_hoja()
        de_lado = foto.rotate(90, expand=True)  # CCW: lo que guarda un teléfono vertical
        exif = Image.Exif()
        exif[0x0112] = 6  # «girar 90° a la derecha para verla bien»
        origen = tmp_path / "de_lado.jpg"
        de_lado.save(origen, "JPEG", quality=92, exif=exif)
        destino = tmp_path / "salida.pdf"
        resultado = escanear.escanear([origen], destino)
        assert resultado.hojas[0].tratamiento == escanear.RECORTADA
        _comprobar_pagina_derecha(destino)

    def test_otra_perspectiva_tambien(self, tmp_path):
        origen = _guardar_foto(tmp_path, "b.jpg", cabeceo=-22.0, guinada=20.0, alabeo=-9.0)
        destino = tmp_path / "b.pdf"
        escanear.escanear([origen], destino)
        _comprobar_pagina_derecha(destino)

    def test_mejorar_el_contraste_aclara_el_fondo_y_deja_la_tinta(self, tmp_path):
        """Una hoja con tono de papel viejo y tinta: el fondo sube a blanco, la tinta se queda."""
        hoja = _hoja_sintetica(fondo=(214, 208, 190, 255))
        foto, _ = _foto_de_la_hoja(hoja=hoja)
        origen = tmp_path / "amarilla.jpg"
        foto.save(origen, "JPEG", quality=92)

        def fondo_y_tinta(pdf):
            imagen, _, _ = _dibujar_pagina(pdf)
            ancho, alto = imagen.size
            fondo = imagen.getpixel((ancho // 2, int(alto * 0.60)))  # papel sin nada
            tinta = imagen.crop((0, int(alto * 0.03), ancho, int(alto * 0.12))).getextrema()[0]
            return fondo, tinta

        sin = tmp_path / "sin.pdf"
        con = tmp_path / "con.pdf"
        escanear.escanear([origen], sin)
        escanear.escanear([origen], con, mejorar=True)
        fondo_sin, _ = fondo_y_tinta(sin)
        fondo_con, tinta_con = fondo_y_tinta(con)
        assert fondo_sin < 225, "la prueba necesita un papel que no sea blanco"
        assert fondo_con >= 245
        assert tinta_con < 90

    def test_varias_fotos_son_varias_paginas_en_el_orden_dado(self, tmp_path, hoja1):
        ancha = _guardar_foto(tmp_path, "ancha.jpg", hoja=_hoja_sintetica((20, 70, 190, 130)))
        destino = tmp_path / "dos.pdf"
        resultado = escanear.escanear([ancha, hoja1], destino)
        assert resultado.paginas == 2
        assert [h.nombre for h in resultado.hojas] == ["ancha.jpg", "hoja1.jpg"]
        primera = _medidas_del_rectangulo(destino)
        segunda = _medidas_del_rectangulo_en(destino, 1)
        # El rectángulo de la primera mide 170 mm de ancho y el de la segunda 130.
        assert primera["caja"][2] - primera["caja"][0] > segunda["caja"][2] - segunda["caja"][0]
        inverso = tmp_path / "inverso.pdf"
        escanear.escanear([hoja1, ancha], inverso)
        assert (
            _medidas_del_rectangulo(inverso)["caja"][2]
            - _medidas_del_rectangulo(inverso)["caja"][0]
            < _medidas_del_rectangulo_en(inverso, 1)["caja"][2]
            - _medidas_del_rectangulo_en(inverso, 1)["caja"][0]
        )


def _tamanos_de_paginas(pdf: Path) -> list[tuple[float, float]]:
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(pdf))
    try:
        return [documento[i].get_size() for i in range(len(documento))]
    finally:
        documento.close()


def _medidas_del_rectangulo_en(pdf: Path, numero: int):
    imagen, ancho_pt, alto_pt = _dibujar_pagina(pdf, numero)
    _, caja = _rectangulo_oscuro(imagen)
    return {"caja": caja, "tamano_px": imagen.size, "tamano_pt": (ancho_pt, alto_pt)}


class TestLaProporcion:
    def test_con_las_esquinas_exactas_sale_la_de_la_hoja(self):
        _, esquinas = _foto_de_la_hoja()
        razon = escanear.proporcion_de_la_hoja(esquinas, *FOTO)
        assert abs(razon - HOJA_MM[0] / HOJA_MM[1]) < 0.005

    def test_la_media_de_los_lados_se_equivoca_y_por_eso_no_se_usa(self):
        _, (tl, tr, br, bl) = _foto_de_la_hoja()
        ingenua = (math_dist(tl, tr) + math_dist(bl, br)) / (math_dist(tl, bl) + math_dist(tr, br))
        verdadera = HOJA_MM[0] / HOJA_MM[1]
        assert abs(ingenua - verdadera) / verdadera > 0.05, "sin esto la prueba no prueba nada"

    def test_sin_perspectiva_cae_a_los_lados(self):
        puntos = [(100.0, 100.0), (500.0, 100.0), (500.0, 600.0), (100.0, 600.0)]
        assert escanear.proporcion_de_la_hoja(puntos, 800, 700) == pytest.approx(0.8)


def math_dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class TestSiNoSeDistingueLaHoja:
    """Regla 4: no se inventa un recorte. Se deja la foto entera y se dice."""

    def _guardar(self, tmp_path, imagen: Image.Image, nombre="sin_hoja.jpg") -> Path:
        ruta = tmp_path / nombre
        imagen.save(ruta, "JPEG", quality=92)
        return ruta

    def _sin_hoja(self) -> Image.Image:
        imagen = Image.new("RGB", (1200, 900), (96, 70, 50))
        dibujo = ImageDraw.Draw(imagen)
        for y in range(0, 900, 17):
            dibujo.line((0, y, 1200, y + 9), fill=(70, 52, 36), width=3)
        return imagen

    def test_una_mesa_sin_hoja_no_da_esquinas_y_dice_por_que(self):
        hallada = escanear.detectar_hoja(self._sin_hoja())
        assert hallada.esquinas is None
        assert hallada.motivo in escanear.MOTIVOS_DE_DETECCION
        assert hallada.explicacion

    def test_la_foto_queda_entera_y_el_aviso_la_nombra(self, tmp_path):
        origen = self._guardar(tmp_path, self._sin_hoja())
        destino = tmp_path / "salida.pdf"
        resultado = escanear.escanear([origen], destino)
        assert [h.tratamiento for h in resultado.hojas] == [escanear.ENTERA]
        assert resultado.hojas[0].motivo in escanear.MOTIVOS_DE_DETECCION
        assert len(resultado.avisos) == 1
        assert "sin_hoja.jpg" in resultado.avisos[0] and "foto entera" in resultado.avisos[0]
        _, ancho_pt, alto_pt = _dibujar_pagina(destino)
        assert abs(ancho_pt / alto_pt - 1200 / 900) < 0.01, "la página es la foto entera"

    def test_una_hoja_que_llena_todo_el_cuadro_no_tiene_borde(self):
        blanca = Image.new("RGB", (800, 600), (245, 245, 240))
        ImageDraw.Draw(blanca).text((100, 100), "texto", fill=(10, 10, 10))
        assert escanear.detectar_hoja(blanca).motivo == "sin-borde"

    def test_una_hoja_diminuta_no_es_la_hoja(self):
        foto = self._sin_hoja()
        ImageDraw.Draw(foto).rectangle((500, 400, 640, 520), fill=(245, 245, 240))
        assert escanear.detectar_hoja(foto).motivo == "hoja-pequena"

    def test_un_papel_casi_del_color_de_la_mesa_no_se_da_por_hoja(self):
        mesa = Image.new("RGB", (800, 600), (228, 226, 222))
        ImageDraw.Draw(mesa).rectangle((150, 100, 650, 500), fill=(247, 246, 243))
        hallada = escanear.detectar_hoja(mesa)
        assert hallada.esquinas is None and hallada.motivo

    def test_la_forma_de_una_ele_no_es_una_hoja(self):
        foto = self._sin_hoja()
        dibujo = ImageDraw.Draw(foto)
        dibujo.rectangle((100, 100, 700, 330), fill=(245, 245, 240))
        dibujo.rectangle((100, 100, 330, 800), fill=(245, 245, 240))
        assert escanear.detectar_hoja(foto).motivo == "forma-irregular"

    def test_pedir_la_foto_entera_no_busca_ni_avisa(self, tmp_path, hoja1):
        destino = tmp_path / "salida.pdf"
        resultado = escanear.escanear([hoja1], destino, [escanear.Hoja("entera")])
        assert [h.tratamiento for h in resultado.hojas] == [escanear.ENTERA]
        assert resultado.avisos == []
        _, ancho_pt, alto_pt = _dibujar_pagina(destino)
        assert abs(ancho_pt / alto_pt - FOTO[0] / FOTO[1]) < 0.01


class TestEsquinasAMano:
    def test_marcadas_por_la_persona_enderezan_igual(self, tmp_path, hoja1):
        destino = tmp_path / "salida.pdf"
        mano = escanear.Hoja("esquinas", tuple(_esquinas_reales()))
        resultado = escanear.escanear([hoja1], destino, [mano])
        assert [h.tratamiento for h in resultado.hojas] == [escanear.A_MANO]
        _comprobar_pagina_derecha(destino)

    def test_una_foto_en_la_que_no_se_detecta_se_arregla_marcando(self, tmp_path):
        """Una hoja blanca sobre una mesa blanca: la detección se rinde y las esquinas lo salvan."""
        foto, esquinas = _foto_de_la_hoja()
        # Se pinta la «mesa» clara bajo la hoja en vez de la oscura de siempre.
        clara = Image.new("RGBA", FOTO, (238, 236, 232, 255))
        R_foto = foto.convert("RGBA")
        mascara = Image.new("L", FOTO, 0)
        ImageDraw.Draw(mascara).polygon([tuple(p) for p in esquinas], fill=255)
        clara.paste(R_foto, mask=mascara)
        origen = tmp_path / "blanca.jpg"
        clara.convert("RGB").save(origen, "JPEG", quality=95)
        auto = escanear.escanear([origen], tmp_path / "auto.pdf")
        assert auto.hojas[0].tratamiento == escanear.ENTERA and auto.avisos
        fracciones = tuple((x / FOTO[0], y / FOTO[1]) for x, y in esquinas)
        manual = escanear.escanear(
            [origen], tmp_path / "mano.pdf", [escanear.Hoja("esquinas", fracciones)]
        )
        assert manual.hojas[0].tratamiento == escanear.A_MANO
        _comprobar_pagina_derecha(tmp_path / "mano.pdf")

    @pytest.mark.parametrize(
        ("esquinas", "dice"),
        [
            # El orden equivocado (se cruzan los lados).
            (((0.2, 0.2), (0.8, 0.8), (0.8, 0.2), (0.2, 0.8)), "no forman una hoja"),
            # Una esquina fuera de la foto.
            (((0.2, 0.2), (0.8, 0.2), (0.8, 1.2), (0.2, 0.8)), "fuera de la foto"),
            # Un cuadradito de nada.
            (((0.5, 0.5), (0.52, 0.5), (0.52, 0.52), (0.5, 0.52)), "muy poco"),
            # Solo tres.
            (((0.2, 0.2), (0.8, 0.2), (0.8, 0.8)), "las cuatro"),
        ],
    )
    def test_unas_esquinas_que_no_valen_se_rechazan_diciendo_por_que(
        self, tmp_path, hoja1, esquinas, dice
    ):
        destino = tmp_path / "salida.pdf"
        with pytest.raises(escanear.ComposicionInvalida, match=dice):
            escanear.escanear([hoja1], destino, [escanear.Hoja("esquinas", esquinas)])
        assert not destino.exists(), "todo o nada"


class TestTodoONadaYElOriginalNoSeToca:
    def test_una_foto_rota_no_deja_pdf_y_dice_cual(self, tmp_path, hoja1):
        rota = tmp_path / "rota.jpg"
        rota.write_bytes(b"esto no es una foto")
        destino = tmp_path / "salida.pdf"
        with pytest.raises(escanear.ComposicionInvalida, match="rota.jpg no se pudo abrir"):
            escanear.escanear([hoja1, rota], destino)
        assert not destino.exists()
        assert list(tmp_path.glob("*.parcial*")) == []

    def test_los_originales_no_cambian_ni_en_el_camino_feliz_ni_en_los_de_fallo(
        self, tmp_path, hoja1
    ):
        rota = tmp_path / "rota.jpg"
        rota.write_bytes(b"esto no es una foto")
        antes = {r: _sha_y_mtime(r) for r in (hoja1, rota)}

        escanear.escanear([hoja1], tmp_path / "ok.pdf", mejorar=True, tamano="a4")
        for pedido in (
            dict(origenes=[hoja1, rota]),
            dict(
                origenes=[hoja1],
                hojas=[escanear.Hoja("esquinas", ((0, 0), (1, 1), (1, 0), (0, 1)))],
            ),
            dict(origenes=[hoja1], tamano="tabloide"),
            dict(origenes=[]),
        ):
            with pytest.raises(escanear.ComposicionInvalida):
                escanear.escanear(destino=tmp_path / "mal.pdf", **pedido)
        assert {r: _sha_y_mtime(r) for r in (hoja1, rota)} == antes

    def test_opciones_fuera_de_lo_que_se_ofrece(self, tmp_path, hoja1):
        with pytest.raises(escanear.ComposicionInvalida, match="tamaño"):
            escanear.escanear([hoja1], tmp_path / "x.pdf", tamano="carta")
        with pytest.raises(escanear.ComposicionInvalida, match="forma de tratar"):
            escanear.escanear([hoja1], tmp_path / "x.pdf", [escanear.Hoja("adivinar")])
        with pytest.raises(escanear.ComposicionInvalida, match="número de fotos"):
            escanear.escanear([hoja1], tmp_path / "x.pdf", [escanear.Hoja(), escanear.Hoja()])
        with pytest.raises(escanear.ComposicionInvalida, match="Faltan las esquinas"):
            escanear.escanear([hoja1], tmp_path / "x.pdf", [escanear.Hoja("esquinas")])
        with pytest.raises(escanear.ComposicionInvalida, match="máximo"):
            escanear.escanear([hoja1] * (escanear.MAXIMO_HOJAS + 1), tmp_path / "x.pdf")

    def test_las_hojas_que_encola_la_pantalla_se_leen(self):
        hojas = escanear.hojas_desde_opciones(
            [{"modo": "entera"}, {"modo": "esquinas", "esquinas": [[0.1, 0.1]] * 4}], 2
        )
        assert [h.modo for h in hojas] == ["entera", "esquinas"]
        assert all(h.modo == "auto" for h in escanear.hojas_desde_opciones(None, 3))
        with pytest.raises(escanear.ComposicionInvalida):
            escanear.hojas_desde_opciones([{"modo": "entera"}], 2)
        with pytest.raises(escanear.ComposicionInvalida):
            escanear.hojas_desde_opciones([{"modo": "raro"}], 1)


# --- El reconocimiento de texto ----------------------------------------------


@pytest.fixture
def tesseract_de_mentira(monkeypatch):
    """Escribe lo que `ocr.reconocer` entregaría: copia el PDF y apunta cómo se le llamó."""
    llamadas = []

    def reconocer(origen, *, idioma="spa", destino=None, programa=None, progreso=None):
        llamadas.append({"origen": Path(origen), "idioma": idioma, "programa": programa})
        shutil.copy(origen, destino)
        if progreso is not None:
            progreso(1.0)
        return Path(destino)

    monkeypatch.setattr(ocr, "reconocer", reconocer)
    return llamadas


class TestElReconocimiento:
    def test_con_ocr_el_pdf_pasa_por_tesseract_con_su_programa_y_su_idioma(
        self, tmp_path, hoja1, tesseract_de_mentira
    ):
        destino = tmp_path / "salida.pdf"
        avances: list[float] = []
        resultado = escanear.escanear(
            [hoja1],
            destino,
            ocr=escanear.OpcionesDeOcr("/usr/bin/tesseract", "eng"),
            progreso=avances.append,
        )
        assert resultado.con_ocr
        assert [(c["programa"], c["idioma"]) for c in tesseract_de_mentira] == [
            ("/usr/bin/tesseract", "eng")
        ]
        assert destino.exists()
        assert avances == sorted(avances) and avances[-1] == pytest.approx(1.0)

    def test_sin_ocr_no_se_llama_a_tesseract(self, tmp_path, hoja1, tesseract_de_mentira):
        escanear.escanear([hoja1], tmp_path / "salida.pdf")
        assert tesseract_de_mentira == []


@pytest.mark.oraculo
@pytest.mark.skipif(
    not (ocr.sondar(recordar=False).tiene("eng") or ocr.sondar(recordar=False).tiene("spa")),
    reason="Tesseract no está en esta máquina: esta prueba tiene que correr donde esté (p340)",
)
class TestTesseractLeeLaFraseDeControl:
    def test_la_frase_de_la_hoja_se_lee_del_pdf_que_entrega_la_herramienta(self, tmp_path, hoja1):
        import pypdfium2

        estado = ocr.sondar(recordar=False)
        idioma = "eng" if estado.tiene("eng") else "spa"
        destino = tmp_path / "con_texto.pdf"
        escanear.escanear([hoja1], destino, ocr=escanear.OpcionesDeOcr(estado.programa, idioma))
        documento = pypdfium2.PdfDocument(str(destino))
        try:
            texto = documento[0].get_textpage().get_text_range()
        finally:
            documento.close()
        # El lector es PDFium; el que escribió esa capa de texto fue Tesseract.
        normal = " ".join(texto.upper().split())
        assert "7391" in normal and "CONTROL" in normal, normal


# --- En la cola --------------------------------------------------------------


class TestEnLaTarea:
    def test_la_tarea_escribe_el_pdf_y_cuenta_lo_que_hizo(self, tmp_path, hoja1):
        sin_hoja = tmp_path / "mesa.jpg"
        Image.new("RGB", (400, 300), (90, 66, 48)).save(sin_hoja, "JPEG")
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "escanear",
            {
                "entradas": [{"ruta": str(hoja1)}, {"ruta": str(sin_hoja)}],
                "opciones": {"tamano": "hoja"},
            },
            parcial,
        )
        assert "codigo" not in informe, informe
        detalles = informe["detalles"]
        assert detalles["paginas"] == 2 and detalles["con_ocr"] is False
        assert [h["tratamiento"] for h in detalles["hojas"]] == ["recortada", "entera"]
        assert len(informe["avisos"]) == 1 and "mesa.jpg" in informe["avisos"][0]
        assert motor.verificar(_como_pdf(parcial), informe).correcta

    def test_con_ocr_y_sin_la_ruta_del_programa_es_sin_tesseract(
        self, tmp_path, hoja1, monkeypatch
    ):
        monkeypatch.delenv(tarea.VARIABLE_TESSERACT, raising=False)
        informe = tarea.ejecutar(
            "escanear",
            {"entradas": [{"ruta": str(hoja1)}], "opciones": {"ocr": True}},
            tmp_path / "s.parcial",
        )
        assert informe["codigo"] == "sin-tesseract"

    def test_con_ocr_la_tarea_usa_la_ruta_que_le_da_el_padre(
        self, tmp_path, hoja1, monkeypatch, tesseract_de_mentira
    ):
        monkeypatch.setenv(tarea.VARIABLE_TESSERACT, "tesseract-falso")
        informe = tarea.ejecutar(
            "escanear",
            {"entradas": [{"ruta": str(hoja1)}], "opciones": {"ocr": True, "idioma": "eng"}},
            tmp_path / "s.parcial",
        )
        assert informe["detalles"]["con_ocr"] is True
        assert (tesseract_de_mentira[0]["programa"], tesseract_de_mentira[0]["idioma"]) == (
            "tesseract-falso",
            "eng",
        )

    def test_un_fallo_de_la_herramienta_llega_con_su_codigo(self, tmp_path):
        rota = tmp_path / "rota.jpg"
        rota.write_bytes(b"no es una foto")
        informe = tarea.ejecutar(
            "escanear", {"entradas": [{"ruta": str(rota)}], "opciones": {}}, tmp_path / "s.parcial"
        )
        assert informe["codigo"] == "documento-invalido"
        assert "rota.jpg" in informe["mensaje"]


def _como_pdf(parcial: Path) -> Path:
    """El verificador decide por la extensión; el corredor le pasa el parcial ya con `.pdf`."""
    destino = parcial.with_name("verificar.pdf")
    shutil.copy(parcial, destino)
    return destino


class TestDisponibilidadYPlan:
    """El reconocimiento depende de algo de fuera, y se prueba en los dos casos."""

    def test_sin_ocr_la_herramienta_no_exige_nada(self, monkeypatch):
        monkeypatch.setattr(ocr, "sondar", lambda **_: ocr.Disponible())
        assert motor.disponibilidad("escanear", {}).disponible
        assert motor.disponibilidad("escanear").disponible

    def test_con_ocr_y_sin_tesseract_esta_apagada_con_motivo_y_sugerencia(self, monkeypatch):
        monkeypatch.setattr(
            ocr, "sondar", lambda **_: ocr.Disponible(motivo="No está.", sugerencia="Instálelo.")
        )
        estado = motor.disponibilidad("escanear", {"ocr": True})
        assert not estado.disponible
        assert (estado.codigo_motivo, estado.mensaje, estado.sugerencia) == (
            "sin-tesseract",
            "No está.",
            "Instálelo.",
        )

    def test_con_ocr_y_con_tesseract_esta_disponible_y_lo_dice_en_el_recibo(self, monkeypatch):
        monkeypatch.setattr(
            ocr, "sondar", lambda **_: ocr.Disponible("t", frozenset({"spa", "eng"}))
        )
        estado = motor.disponibilidad("escanear", {"ocr": True, "idioma": "eng"})
        assert estado.disponible and "OCR" in estado.version

    def test_con_ocr_y_un_idioma_que_no_esta_se_apaga_diciendo_cuales_hay(self, monkeypatch):
        monkeypatch.setattr(ocr, "sondar", lambda **_: ocr.Disponible("t", frozenset({"spa"})))
        estado = motor.disponibilidad("escanear", {"ocr": True, "idioma": "eng"})
        assert not estado.disponible and "spa" in estado.sugerencia

    def _trabajo(self, tmp_path, hoja1, **opciones):
        from apps.jobs.models import ConversionJob, EntradaDeTrabajo

        usuario, _ = get_user_model().objects.get_or_create(username="ana")
        job = ConversionJob.objects.create(
            owner=usuario,
            herramienta="escanear",
            source_path=str(hoja1),
            source_name=hoja1.name,
            target_format_code="doc:escanear",
            output_path=str(tmp_path / "hoja1_escaneado.pdf"),
            options=opciones,
        )
        EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(hoja1), nombre=hoja1.name)
        return job

    def test_el_plan_pasa_la_ruta_de_tesseract_solo_si_se_pidio(
        self, tmp_path, hoja1, monkeypatch, settings
    ):
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        monkeypatch.setattr(ocr, "sondar", lambda **_: ocr.Disponible("tesseract-falso"))
        sin = motor.plan(self._trabajo(tmp_path, hoja1))
        assert tarea.VARIABLE_TESSERACT not in sin.env
        con = motor.plan(self._trabajo(tmp_path, hoja1, ocr=True, idioma="spa"))
        assert con.env[tarea.VARIABLE_TESSERACT] == "tesseract-falso"
        assert con.timeout_s > sin.timeout_s
        assert con.emite_progreso and motor.carril_de("escanear") == "pesado"


# --- La pantalla -------------------------------------------------------------


def _porcentajes(esquinas) -> dict:
    campos = {}
    for k, (x, y) in enumerate(esquinas):
        campos[f"e0_{k}x"] = f"{x * 100:.2f}"
        campos[f"e0_{k}y"] = f"{y * 100:.2f}"
    return campos


class TestLaPantalla:
    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def _mirar(self, sesion, *fotos):
        return sesion.post(
            reverse("documents:escanear"),
            {"archivos_texto": "\n".join(str(f) for f in fotos), "accion": "mirar"},
        )

    def test_las_dos_vistas_piden_sesion(self, client):
        assert client.get(reverse("documents:escanear")).status_code == 302
        assert client.get(reverse("documents:escanear_foto")).status_code == 302

    def test_el_primer_paso_pide_las_fotos(self, sesion):
        cuerpo = sesion.get(reverse("documents:escanear")).content.decode()
        assert "Buscar las hojas" in cuerpo and 'accept="image/*' in cuerpo

    def test_sin_fotos_avisa(self, sesion):
        respuesta = self._mirar(sesion)
        assert "No indicó ninguna foto" in respuesta.content.decode()

    def test_lo_que_no_es_una_imagen_se_rechaza_antes_de_mirar(self, sesion, tmp_path):
        plano = tmp_path / "plano.dwg"
        plano.write_bytes(b"AC1015")
        assert "no es una imagen" in self._mirar(sesion, plano).content.decode()

    def test_mirar_enseña_la_hoja_hallada_con_sus_esquinas_donde_estan(self, sesion, hoja1):
        import re

        cuerpo = self._mirar(sesion, hoja1).content.decode()
        assert "Se encontró la hoja" in cuerpo
        assert 'value="esquinas" checked' in cuerpo
        verdaderas = _esquinas_reales()
        for k, (x, y) in enumerate(verdaderas):
            valor_x = re.search(rf'name="e0_{k}x" value="([\d.]+)"', cuerpo).group(1)
            valor_y = re.search(rf'name="e0_{k}y" value="([\d.]+)"', cuerpo).group(1)
            assert abs(float(valor_x) - x * 100) < 1.0 and abs(float(valor_y) - y * 100) < 1.0
        # El recuadro y las dos formas de marcar a mano, sin nada que dependa del cursor.
        assert '<polygon points="' in cuerpo and 'points=""' not in cuerpo
        assert "data-marcar" in cuerpo and "Poner o ajustar las esquinas con números" in cuerpo

    def test_sin_hoja_la_tarjeta_lo_dice_y_deja_la_foto_entera(self, sesion, tmp_path):
        mesa = tmp_path / "mesa.jpg"
        Image.new("RGB", (800, 600), (90, 66, 48)).save(mesa, "JPEG")
        cuerpo = self._mirar(sesion, mesa).content.decode()
        assert "No se encontró la hoja" in cuerpo and "queda la foto entera" in cuerpo
        assert 'value="entera" checked' in cuerpo
        assert 'value="esquinas" checked' not in cuerpo

    def test_la_foto_se_sirve_derecha_y_mas_chica(self, sesion, hoja1):
        respuesta = sesion.get(reverse("documents:escanear_foto"), {"ruta": str(hoja1)})
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "image/jpeg"
        import io

        with Image.open(io.BytesIO(respuesta.content)) as foto:
            assert max(foto.size) <= 1100

    def test_la_foto_de_fuera_de_las_carpetas_permitidas_se_niega(self, sesion, settings, tmp_path):
        settings.RAICES_PERMITIDAS = str(tmp_path / "otra")
        assert (
            sesion.get(reverse("documents:escanear_foto"), {"ruta": "C:/x.jpg"}).status_code == 400
        )

    def _hacer(self, sesion, fotos, **campos):
        datos = {
            "archivos_texto": "\n".join(str(f) for f in fotos),
            "accion": "hacer",
            "tamano": "hoja",
            **campos,
        }
        return sesion.post(reverse("documents:escanear"), datos)

    def test_hacer_encola_y_el_pdf_sale_rectangular_por_la_cola(self, sesion, hoja1):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = self._hacer(
            sesion,
            [hoja1],
            modo_0="esquinas",
            orden_0="1",
            **_porcentajes(_esquinas_reales()),
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.output_path.endswith("_escaneado.pdf")
        _comprobar_pagina_derecha(Path(trabajo.output_path))
        assert trabajo.options["hojas"][0]["modo"] == "esquinas"

    def test_el_orden_elegido_manda_sobre_el_de_la_lista(self, sesion, tmp_path, hoja1):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        # Dos fotos enteras que se distinguen por su forma: una apaisada y otra vertical.
        vertical = tmp_path / "vertical.jpg"
        Image.new("RGB", (600, 800), (120, 120, 120)).save(vertical, "JPEG")
        campos = {"modo_0": "entera", "modo_1": "entera", "orden_0": "2", "orden_1": "1"}
        respuesta = self._hacer(sesion, [hoja1, vertical], **campos)
        assert respuesta.status_code == 302
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert [e.nombre for e in trabajo.entradas.order_by("orden")] == [
            "vertical.jpg",
            "hoja1.jpg",
        ]
        formas = [ancho > alto for ancho, alto in _tamanos_de_paginas(Path(trabajo.output_path))]
        assert formas == [False, True], "primero la vertical, que se pidió en la posición 1"

    def test_faltan_esquinas_y_no_se_encola(self, sesion, hoja1):
        from apps.jobs.models import ConversionJob

        respuesta = self._hacer(sesion, [hoja1], modo_0="esquinas", orden_0="1")
        assert respuesta.status_code == 200
        assert "Faltan las esquinas de la foto 1" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_unas_esquinas_cruzadas_se_dicen_con_el_numero_de_la_foto(self, sesion, hoja1):
        cruzadas = [(0.2, 0.2), (0.8, 0.8), (0.8, 0.2), (0.2, 0.8)]
        respuesta = self._hacer(
            sesion, [hoja1], modo_0="esquinas", orden_0="1", **_porcentajes(cruzadas)
        )
        cuerpo = respuesta.content.decode()
        assert (
            respuesta.status_code == 200 and "Foto 1" in cuerpo and "no forman una hoja" in cuerpo
        )

    def test_lo_que_se_puso_a_mano_se_conserva_al_volver_con_un_error(self, sesion, hoja1):
        cruzadas = [(0.2, 0.2), (0.8, 0.8), (0.8, 0.2), (0.2, 0.8)]
        cuerpo = self._hacer(
            sesion, [hoja1], modo_0="esquinas", orden_0="1", **_porcentajes(cruzadas)
        ).content.decode()
        assert 'name="e0_1x" value="80.00"' in cuerpo

    def test_un_tamano_o_un_idioma_fuera_de_lo_que_se_ofrece_no_encola(self, sesion, hoja1):
        from apps.jobs.models import ConversionJob

        base = dict(modo_0="entera", orden_0="1")
        assert "tamaño" in self._hacer(sesion, [hoja1], **base, tamano="tabloide").content.decode()
        assert (
            "idioma" in self._hacer(sesion, [hoja1], **base, ocr="on", idioma="xx").content.decode()
        )
        assert not ConversionJob.objects.exists()

    def test_pedir_ocr_sin_tesseract_se_niega_con_el_motivo_y_no_sustituye(
        self, sesion, hoja1, monkeypatch
    ):
        from apps.jobs.models import ConversionJob

        monkeypatch.setattr(
            ocr,
            "sondar",
            lambda **_: ocr.Disponible(motivo="Falta Tesseract.", sugerencia="Instálelo."),
        )
        respuesta = self._hacer(sesion, [hoja1], modo_0="entera", orden_0="1", ocr="on")
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200 and "Falta Tesseract." in cuerpo
        assert not ConversionJob.objects.exists(), (
            "no se entrega un PDF sin texto donde se pidió con él"
        )

    def test_sin_tesseract_la_casilla_sale_apagada_con_su_motivo_y_su_alternativa(
        self, sesion, hoja1, monkeypatch
    ):
        monkeypatch.setattr(
            ocr,
            "sondar",
            lambda **_: ocr.Disponible(motivo="Falta Tesseract.", sugerencia="Instálelo."),
        )
        cuerpo = self._mirar(sesion, hoja1).content.decode()
        assert 'name="ocr" disabled' in cuerpo
        assert "no disponible ahora" in cuerpo and "Falta Tesseract." in cuerpo
        assert "Reconocer texto (OCR)" in cuerpo  # la alternativa, dicha

    def test_con_tesseract_se_ofrece_y_encola_con_ocr(self, sesion, hoja1, monkeypatch):
        from apps.jobs.models import ConversionJob

        monkeypatch.setattr(
            ocr, "sondar", lambda **_: ocr.Disponible("tesseract-falso", frozenset({"spa", "eng"}))
        )
        assert 'name="ocr" id="id_ocr"' in self._mirar(sesion, hoja1).content.decode()
        respuesta = self._hacer(
            sesion, [hoja1], modo_0="entera", orden_0="1", ocr="on", idioma="eng", mejorar="on"
        )
        assert respuesta.status_code == 302
        trabajo = ConversionJob.objects.get()
        assert trabajo.options["ocr"] is True and trabajo.options["idioma"] == "eng"
        assert trabajo.options["mejorar"] is True

    def test_la_ficha_recuerda_repasar_las_paginas(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        trabajo = ConversionJob.objects.create(
            owner=get_user_model().objects.get(username="ana"),
            herramienta="escanear",
            source_name="hoja1.jpg",
            source_path=str(tmp_path / "hoja1.jpg"),
            target_format_code="doc:escanear",
            status="done",
            output_path=str(tmp_path / "x.pdf"),
        )
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert "Repase cada página" in cuerpo

    def test_una_subida_de_otra_persona_no_se_sirve(self, sesion, hoja1):
        """La vista de la foto pasa por la puerta única: un identificador ajeno no se abre."""
        respuesta = sesion.get(reverse("documents:escanear_foto"), {"ruta": "subida:no-existe"})
        assert respuesta.status_code == 400
