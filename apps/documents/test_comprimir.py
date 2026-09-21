"""Comprimir un PDF, y sobre todo negarse cuando no vale la pena.

El caso real no es «ocupa mucho»: es que **un juego de planos no entra en un correo**, el
envío rebota y la entrega se retrasa un día. Por eso lo que hay que fijar no es cuánto baja
—eso depende del archivo— sino que **no estropee el plano** y que **no empeore el problema**.
"""

from __future__ import annotations

import random

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .composicion import ComposicionInvalida
from .comprimir import LADO_MINIMO, RESOLUCIONES, comprimir


@pytest.fixture
def pesado(tmp_path):
    """Un PDF con una imagen grande dentro, que es un plano escaneado en pequeño.

    El ruido aleatorio es deliberado: una imagen lisa se comprime tanto de origen que no
    quedaría nada que bajar, y la prueba pasaría sin demostrar nada.
    """
    foto = tmp_path / "grande.jpg"
    imagen = Image.new("RGB", (2400, 1600))
    pixeles = imagen.load()
    random.seed(7)  # nosec B311 - ruido para una imagen de prueba, no criptografía
    for y in range(0, 1600, 8):
        for x in range(0, 2400, 8):
            color = tuple(random.randrange(256) for _ in range(3))  # nosec B311
            for dy in range(8):
                for dx in range(8):
                    if y + dy < 1600 and x + dx < 2400:
                        pixeles[x + dx, y + dy] = color
    imagen.save(foto, quality=95)

    ruta = tmp_path / "planos.pdf"
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    hoja.drawImage(str(foto), 20, 300, width=550, height=400)
    hoja.drawString(40, 100, "Plano de prueba")
    hoja.showPage()
    hoja.save()
    return ruta


@pytest.fixture
def ligero(tmp_path):
    """Un PDF que ya no tiene nada que bajar: solo texto."""
    ruta = tmp_path / "acta.pdf"
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    hoja.drawString(72, 720, "Acta de entrega")
    hoja.showPage()
    hoja.save()
    return ruta


class TestQueBajeDeVerdad:
    def test_un_plano_escaneado_baja_mucho(self, pesado):
        """El umbral es 20 % y no un número más alto **porque cuánto baja depende del
        archivo**, no de la herramienta: sobre este PDF de prueba da un 30 %, y sobre un
        escaneo real de 7,2 MB medido el 2026-09-21 dio un **83 %**.

        Poner aquí el 83 sería fijar la prueba al resultado de un archivo concreto y hacerla
        fallar el día que alguien cambie el ruido del fixture. Lo que tiene que garantizar es
        que baja de verdad, no una cifra.
        """
        destino, resultado = comprimir(pesado, ppp=200)
        assert destino is not None
        assert resultado.reduccion_pct >= 20, f"Solo bajó {resultado.reduccion_pct} %"
        assert resultado.imagenes_tocadas == 1

    def test_menos_resolucion_pesa_menos(self, pesado, tmp_path):
        _, doscientos = comprimir(pesado, ppp=200, destino=tmp_path / "a.pdf")
        _, ciento_cincuenta = comprimir(pesado, ppp=150, destino=tmp_path / "b.pdf")
        assert ciento_cincuenta.salida_bytes < doscientos.salida_bytes


class TestQueNoEstropeeElPlano:
    def test_el_texto_sigue_dentro(self, pesado):
        """**Lo que separa comprimir de romper.** El texto y las líneas no pesan en
        comparación con las imágenes, así que no hay razón para tocarlos — y si se tocaran,
        el plano dejaría de servir para lo que sirve."""
        destino, _ = comprimir(pesado, ppp=150)
        leido = PdfReader(str(destino))
        assert "Plano de prueba" in (leido.pages[0].extract_text() or "")

    def test_no_se_pierde_ninguna_pagina(self, pesado):
        destino, resultado = comprimir(pesado, ppp=200)
        assert len(PdfReader(str(destino)).pages) == resultado.paginas

    def test_el_original_no_se_toca(self, pesado):
        antes = pesado.read_bytes()
        comprimir(pesado, ppp=150)
        assert pesado.read_bytes() == antes


class TestQueNoEmpeoreElProblema:
    """**El único caso de la casa donde la respuesta correcta puede ser «no hagas nada».**"""

    def test_un_pdf_ya_ligero_no_se_reescribe(self, ligero, tmp_path):
        destino, resultado = comprimir(ligero, ppp=200, destino=tmp_path / "salida.pdf")
        if not resultado.merecio_la_pena:
            assert destino is None
            assert not (tmp_path / "salida.pdf").exists()

    def test_y_no_deja_el_parcial(self, ligero, tmp_path):
        comprimir(ligero, ppp=0, destino=tmp_path / "salida.pdf")
        assert not list(tmp_path.glob("*.parcial"))

    def test_el_resultado_se_devuelve_aunque_no_se_escriba(self, ligero, tmp_path):
        """Devolverlo es lo que permite decir «ya estaba comprimido, pesa 4 KB y así se
        queda» en vez de un error — porque no es un error."""
        _, resultado = comprimir(ligero, ppp=200, destino=tmp_path / "salida.pdf")
        assert resultado.origen_bytes > 0
        assert resultado.paginas == 1


class TestLoQueSeRechaza:
    def test_una_resolucion_que_no_se_ofrece(self, pesado):
        """Un campo libre de ppp invita a teclear 72 y descubrir que los planos salieron
        ilegibles cuando el cliente ya los tiene."""
        with pytest.raises(ComposicionInvalida):
            comprimir(pesado, ppp=72)

    def test_un_pdf_con_contrasena_dice_que_lo_es(self, tmp_path):
        from .seguridad import proteger

        claro = tmp_path / "claro.pdf"
        hoja = canvas.Canvas(str(claro), pagesize=A4)
        hoja.drawString(72, 720, "x")
        hoja.showPage()
        hoja.save()
        cerrado = tmp_path / "cerrado.pdf"
        proteger(claro, cerrado, "clave-larga-2026")

        with pytest.raises(ComposicionInvalida) as fallo:
            comprimir(cerrado, ppp=200)
        assert "contraseña" in str(fallo.value)

    def test_algo_que_no_es_un_pdf(self, tmp_path):
        falso = tmp_path / "falso.pdf"
        falso.write_bytes(b"esto no es un PDF")
        with pytest.raises(ComposicionInvalida):
            comprimir(falso, ppp=200)


class TestLasResolucionesOfrecidas:
    def test_cada_una_dice_para_que_sirve(self):
        """Un número solo no ayuda a elegir: «150» no dice si eso sirve para entregar."""
        assert all(texto for texto in RESOLUCIONES.values())

    def test_esta_la_opcion_de_no_tocar_las_imagenes(self):
        """Es la única que no puede estropear nada, y tiene que poder elegirse."""
        assert 0 in RESOLUCIONES

    def test_el_lado_minimo_protege_a_los_logotipos(self):
        """Un logotipo de 200 px no tiene nada que bajar, y recomprimirlo solo le añade
        artefactos sin ahorrar un byte que se note."""
        assert LADO_MINIMO >= 200
