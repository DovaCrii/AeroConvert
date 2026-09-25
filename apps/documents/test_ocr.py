"""Reconocer el texto de un escaneo.

## Lo que estas pruebas pueden garantizar, y lo que no

**Tesseract no está en esta máquina ni en el servidor todavía**, así que lo que se comprueba
aquí es el sondeo, las negativas y el criterio — no el reconocimiento en sí. Las que necesitan
el programa se saltan solas y dicen por qué, igual que las de Office y las de Access.

Eso no es un hueco tapado: es exactamente el mismo trato que reciben GDAL, Office y el motor
de Access, y es lo que permite que la herramienta salga apagada con su motivo en vez de
reventar. **La prueba de extremo a extremo tiene que correrse donde Tesseract esté instalado**,
y hasta entonces no se puede decir que la conversión funcione.
"""

from __future__ import annotations

import shutil

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from . import ocr
from .composicion import ComposicionInvalida

hay_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract no está en esta máquina: la herramienta sale apagada, que es lo correcto",
)


@pytest.fixture
def con_texto(tmp_path):
    """Un PDF que ya trae su capa de texto: el caso en que **no** hay que hacer nada."""
    ruta = tmp_path / "acta.pdf"
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    hoja.drawString(72, 720, "Acta de recepcion provisional")
    hoja.showPage()
    hoja.save()
    return ruta


@pytest.fixture
def sin_texto(tmp_path):
    """Un PDF que es solo una imagen, que es lo que sale de un escáner."""
    from PIL import Image

    foto = tmp_path / "hoja.png"
    Image.new("RGB", (1200, 1600), "white").save(foto)

    ruta = tmp_path / "escaneo.pdf"
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    hoja.drawImage(str(foto), 20, 20, width=550, height=750)
    hoja.showPage()
    hoja.save()
    return ruta


class TestElSondeo:
    """**Se sondea, no se declara.** Tesseract no entra en `pyproject.toml`."""

    def test_no_se_declara_como_dependencia(self):
        from pathlib import Path

        from django.conf import settings

        texto = (Path(settings.BASE_DIR) / "pyproject.toml").read_text("utf-8")
        assert "tesseract" not in texto.lower(), (
            "Tesseract es un programa externo: si entra en las dependencias, la instalación "
            "empieza a fallar donde hoy simplemente sale apagado."
        )

    def test_cuando_no_esta_dice_por_que_y_como_ponerlo(self, monkeypatch):
        """**Un «no se puede» sin salida es una pared.** El motivo dice qué falta y la
        sugerencia dice qué hacer, que es la diferencia entre avisar y abandonar."""
        monkeypatch.setattr(ocr.shutil, "which", lambda _: None)
        estado = ocr.sondar(recordar=False)
        assert not estado
        assert "Tesseract" in estado.motivo
        assert "apt install" in estado.sugerencia

    def test_instalado_pero_sin_idiomas_tambien_es_no(self, monkeypatch):
        """El caso que se olvida: el binario está y no reconoce nada porque falta el paquete
        de datos. Sin esto saldría encendida y fallaría al pulsar."""
        monkeypatch.setattr(ocr.shutil, "which", lambda _: "/usr/bin/tesseract")

        class Vacio:
            stdout = "List of available languages (0):\n"

        monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: Vacio())
        estado = ocr.sondar(recordar=False)
        assert not estado
        assert "sin ningún idioma" in estado.motivo

    def test_un_idioma_compuesto_necesita_los_dos(self):
        """«Español e inglés mezclados» con solo `spa` instalado reconocería mal el inglés y
        nadie sabría por qué: Tesseract no se queja, simplemente acierta menos."""
        solo_espanol = ocr.Disponible(programa="/usr/bin/tesseract", idiomas=frozenset({"spa"}))
        assert solo_espanol.tiene("spa")
        assert not solo_espanol.tiene("spa+eng")

    def test_se_recuerda_para_no_lanzar_un_proceso_por_pantalla(self, monkeypatch):
        from django.core.cache import cache

        cache.delete(ocr.CLAVE_DE_CACHE)
        veces = []

        def contar():
            veces.append(1)
            return ocr.Disponible(programa="x", idiomas=frozenset({"spa"}))

        monkeypatch.setattr(ocr, "_mirar", contar)
        ocr.sondar()
        ocr.sondar()
        assert len(veces) == 1
        cache.delete(ocr.CLAVE_DE_CACHE)


class TestMirarAntesDeGastarMinutos:
    def test_un_pdf_con_texto_se_reconoce_como_tal(self, con_texto):
        """Pasarlo por OCR tardaría minutos para dejarlo **peor**: el reconocimiento se
        equivoca y el texto incrustado no."""
        assert ocr.ya_tiene_texto(con_texto)

    def test_un_escaneo_no(self, sin_texto):
        assert not ocr.ya_tiene_texto(sin_texto)

    def test_algo_que_no_es_un_pdf_no_revienta(self, tmp_path):
        """Se consulta antes de saber si el archivo vale: si esto lanzara, el mensaje que
        vería alguien sería el de una excepción interna y no «esto no es un PDF»."""
        falso = tmp_path / "falso.pdf"
        falso.write_bytes(b"no soy un PDF")
        assert ocr.ya_tiene_texto(falso) is False


class TestLoQueSeRechaza:
    def test_sin_tesseract_se_niega_con_el_motivo(self, monkeypatch, sin_texto):
        monkeypatch.setattr(ocr, "sondar", lambda: ocr.Disponible(motivo="No está Tesseract."))
        with pytest.raises(ComposicionInvalida) as fallo:
            ocr.reconocer(sin_texto)
        assert "Tesseract" in str(fallo.value)

    def test_un_idioma_que_no_se_ofrece(self, monkeypatch, sin_texto):
        """El idioma va al proceso: sin lista cerrada, lo que se teclee entra como argumento."""
        monkeypatch.setattr(
            ocr, "sondar", lambda: ocr.Disponible(programa="x", idiomas=frozenset({"spa"}))
        )
        with pytest.raises(ComposicionInvalida):
            ocr.reconocer(sin_texto, idioma="; rm -rf /")

    def test_un_idioma_que_falta_dice_cuales_hay(self, monkeypatch, sin_texto):
        monkeypatch.setattr(
            ocr, "sondar", lambda: ocr.Disponible(programa="x", idiomas=frozenset({"eng"}))
        )
        with pytest.raises(ComposicionInvalida) as fallo:
            ocr.reconocer(sin_texto, idioma="spa")
        assert "eng" in str(fallo.value)

    def test_algo_que_no_es_un_pdf(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            ocr, "sondar", lambda: ocr.Disponible(programa="x", idiomas=frozenset({"spa"}))
        )
        falso = tmp_path / "falso.pdf"
        falso.write_bytes(b"no soy un PDF")
        with pytest.raises(ComposicionInvalida):
            ocr.reconocer(falso)


class TestElCriterio:
    def test_la_resolucion_no_baja_de_trescientos(self):
        """Por debajo, las letras pequeñas de un cajetín se convierten en manchas y el
        reconocimiento **empieza a inventar**, que es peor que no reconocer nada."""
        assert ocr.PPP >= 300

    def test_hay_un_tope_de_paginas_y_el_plazo_lo_cubre(self):
        """El tope existe para poder decirlo antes, no para impedirlo. **Era 100 y no era el
        límite de verdad**: dentro de la petición, gunicorn cortaba a los 120 s. En la cola
        el plazo crece con las páginas, y lo que se vigila es que cubra el tope entero con
        el peor tiempo por página medido (cinco segundos)."""
        assert 0 < ocr.TOPE_PAGINAS <= 500
        assert ocr.plazo_s(ocr.TOPE_PAGINAS) >= ocr.TOPE_PAGINAS * 5

    def test_cada_idioma_tiene_nombre_en_castellano(self):
        """«spa» no es una opción legible. Lo que se elige en pantalla es «Español»."""
        assert all(nombre and nombre[0].isupper() for nombre in ocr.IDIOMAS.values())


@pytest.fixture
def escaneo_legible(tmp_path):
    """Un «escaneo» con palabras de verdad dibujadas, para ver si vuelven.

    Con la fuente de mapa de bits que trae Pillow por omisión el reconocimiento no acierta, y
    una prueba que falla por la fuente y no por el código no dice nada. Si no hay una
    TrueType a mano, **se salta diciéndolo** en vez de afirmar algo que no se comprobó.
    """
    from PIL import Image, ImageDraw, ImageFont

    for candidata in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            letra = ImageFont.truetype(candidata, 72)
            break
        except OSError:
            continue
    else:
        pytest.skip("Sin una fuente TrueType no se puede dibujar un escaneo legible")

    foto = tmp_path / "hoja.png"
    lienzo = Image.new("RGB", (1700, 600), "white")
    ImageDraw.Draw(lienzo).text((60, 200), "ACTA DE RECEPCION", fill="black", font=letra)
    lienzo.save(foto)

    ruta = tmp_path / "escaneo_legible.pdf"
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    hoja.drawImage(str(foto), 20, 400, width=555, height=196)
    hoja.showPage()
    hoja.save()
    return ruta


@hay_tesseract
class TestDondeTesseractEsta:
    """Lo que solo se puede comprobar con el programa instalado.

    Se salta en el servidor y en esta estación **a propósito y dejándolo dicho**: mientras se
    salte, la conversión no está verificada de extremo a extremo.
    """

    def test_un_escaneo_sale_con_texto_dentro(self, escaneo_legible, tmp_path):
        """**La promesa entera, en una línea.** Antes no se podía buscar; ahora sí."""
        assert not ocr.ya_tiene_texto(escaneo_legible)
        destino = ocr.reconocer(escaneo_legible, destino=tmp_path / "salida.pdf")
        assert ocr.ya_tiene_texto(destino)

    def test_no_se_pierden_paginas(self, sin_texto, tmp_path):
        from pypdf import PdfReader

        destino = ocr.reconocer(sin_texto, destino=tmp_path / "salida.pdf")
        assert len(PdfReader(str(destino)).pages) == 1

    def test_el_original_no_se_toca(self, sin_texto, tmp_path):
        antes = sin_texto.read_bytes()
        ocr.reconocer(sin_texto, destino=tmp_path / "salida.pdf")
        assert sin_texto.read_bytes() == antes

    def test_no_deja_el_parcial(self, sin_texto, tmp_path):
        ocr.reconocer(sin_texto, destino=tmp_path / "salida.pdf")
        assert not list(tmp_path.glob("*.parcial"))
