"""Redactar de verdad (F14.8).

**El oráculo son tres lectores que no escribieron el archivo**: `pypdf` extrae el texto,
`pikepdf` decodifica **todos los flujos** del documento y busca el texto en los bytes, y PDFium
dibuja la página y se mira si el sitio está negro. Un rectángulo negro encima del texto pasaría
la tercera y fallaría las dos primeras: por eso están las tres.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from apps.documents import redactar, tarea

pytestmark = pytest.mark.django_db

A4 = (595.2756, 841.8898)
RUT = "12.345.678-9"
NOMBRE = "Juan Pérez Soto"


def _pdf(carpeta: Path, nombre: str = "informe.pdf") -> Path:
    """Dos páginas: la primera con un nombre, un RUT y una imagen; la segunda sin datos."""
    foto = carpeta / "foto.png"
    Image.new("RGB", (120, 60), (200, 40, 40)).save(foto)
    ruta = carpeta / nombre
    lienzo = canvas.Canvas(str(ruta), pagesize=A4)
    lienzo.setFont("Helvetica", 14)
    lienzo.drawString(72, 700, f"Cliente: {NOMBRE}")
    lienzo.drawString(72, 670, f"RUT {RUT}")
    lienzo.drawString(72, 640, "Observaciones generales de la obra")
    lienzo.drawImage(str(foto), 72, 500, width=120, height=60)
    lienzo.showPage()
    lienzo.setFont("Helvetica", 14)
    lienzo.drawString(72, 700, "Esta página no tiene nada reservado")
    lienzo.showPage()
    lienzo.save()
    return ruta


def _texto_pypdf(ruta: Path) -> str:
    return " ".join(p.extract_text() or "" for p in PdfReader(str(ruta)).pages)


def _bytes_de_todos_los_flujos(ruta: Path) -> bytes:
    """Todo lo que hay en el archivo, **decodificado**: un texto comprimido también aparece."""
    juntos = bytearray(ruta.read_bytes())
    with pikepdf.open(ruta) as pdf:
        for objeto in pdf.objects:
            if isinstance(objeto, pikepdf.Stream):
                try:
                    juntos += objeto.read_bytes()
                except Exception:  # un flujo de imagen con un filtro que no se decodifica
                    juntos += objeto.read_raw_bytes()
    return bytes(juntos)


def _oscuros_en(ruta: Path, caja_pt, pagina: int = 0) -> float:
    """Fracción de píxeles oscuros dentro de una caja (izq, abajo, der, arriba) en puntos."""
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        hoja = documento[pagina]
        try:
            imagen = hoja.render(scale=1).to_pil().convert("L")
            alto = hoja.get_size()[1]
        finally:
            hoja.close()
    finally:
        documento.close()
    izq, abajo, der, arriba = caja_pt
    recorte = imagen.crop((int(izq), int(alto - arriba), int(der), int(alto - abajo)))
    negro = recorte.point(lambda p: 255 if p < 60 else 0).histogram()[255]
    return negro / max(recorte.size[0] * recorte.size[1], 1)


class TestTextos:
    def test_el_texto_ya_no_existe_para_ningun_lector(self, tmp_path):
        origen = _pdf(tmp_path)
        # Antes: los tres lectores lo encuentran, así que la prueba mide algo.
        assert RUT in _texto_pypdf(origen) and NOMBRE in _texto_pypdf(origen)
        assert RUT.encode() in _bytes_de_todos_los_flujos(origen)

        destino = tmp_path / "redactado.pdf"
        hecho = redactar.redactar(origen, destino, terminos=[RUT, NOMBRE])

        assert hecho.paginas_redactadas == (1,)
        assert hecho.coincidencias == (1, 1)
        texto = _texto_pypdf(destino)
        assert RUT not in texto and "Juan" not in texto and "Soto" not in texto
        crudo = _bytes_de_todos_los_flujos(destino)
        assert RUT.encode() not in crudo and b"Juan" not in crudo and b"Soto" not in crudo
        # Ni siquiera en UTF-16, que es como un PDF guarda un nombre con tilde en un marcador.
        assert NOMBRE.encode("utf-16-be") not in crudo

    def test_donde_estaba_el_texto_ahora_hay_negro(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        redactar.redactar(_pdf(tmp_path), destino, terminos=[RUT])
        # El RUT está en y=670 con cuerpo 14: la caja de la línea, en puntos.
        assert _oscuros_en(destino, (72, 668, 72 + 100, 684)) > 0.6

    def test_la_imagen_que_habia_debajo_se_reemplaza_por_la_de_la_pagina(self, tmp_path):
        origen = _pdf(tmp_path)
        destino = tmp_path / "redactado.pdf"
        redactar.redactar(origen, destino, terminos=[RUT])
        with pikepdf.open(destino) as pdf:
            imagenes = list(pdf.pages[0].images.values())
            assert len(imagenes) == 1
            # La única imagen es la página dibujada: del tamaño de la hoja a 200 ppp.
            assert imagenes[0].Width > 1500

    def test_se_encuentra_sin_importar_las_mayusculas(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        hecho = redactar.redactar(_pdf(tmp_path), destino, terminos=["JUAN PÉREZ"])
        assert hecho.coincidencias == (1,)
        assert "Juan" not in _texto_pypdf(destino)

    def test_lo_que_no_se_pidio_sigue_estando_en_la_misma_pagina_como_imagen(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        redactar.redactar(_pdf(tmp_path), destino, terminos=[RUT])
        # Se avisa en la pantalla: la página redactada ya no tiene texto, ni el que no se tachó.
        assert "Observaciones" not in _texto_pypdf(destino).split("Esta página")[0]


class TestPaginasSinNada:
    def test_las_demas_pasan_tal_cual_con_su_texto(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        hecho = redactar.redactar(_pdf(tmp_path), destino, terminos=[RUT])
        assert hecho.paginas == 2
        assert "Esta página no tiene nada reservado" in _texto_pypdf(destino)
        assert len(PdfReader(str(destino)).pages) == 2

    def test_nada_que_tachar_se_dice_y_no_escribe(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        with pytest.raises(redactar.NadaQueRedactar):
            redactar.redactar(_pdf(tmp_path), destino, terminos=["no aparece en ningún lado"])
        assert not destino.exists()


class TestAreas:
    def test_un_area_tacha_lo_que_hay_debajo(self, tmp_path):
        destino = tmp_path / "redactado.pdf"
        # La imagen: x 72–192, y 500–560 en puntos → desde arriba, y 281.9–341.9 pt.
        mm = 25.4 / 72
        area = redactar.Area(
            pagina=1,
            x0=60 * mm,
            y0=(A4[1] - 570) * mm,
            x1=200 * mm,
            y1=(A4[1] - 490) * mm,
        )
        hecho = redactar.redactar(_pdf(tmp_path), destino, areas=[area])
        assert hecho.areas == 1 and hecho.paginas_redactadas == (1,)
        assert _oscuros_en(destino, (80, 505, 180, 555)) > 0.9

    def test_una_pagina_que_no_existe_se_rechaza(self, tmp_path):
        with pytest.raises(redactar.ComposicionInvalida, match="no existe la 9"):
            redactar.redactar(
                _pdf(tmp_path), tmp_path / "x.pdf", areas=[redactar.Area(9, 1, 1, 10, 10)]
            )

    def test_un_area_sin_tamano_se_rechaza(self, tmp_path):
        with pytest.raises(redactar.ComposicionInvalida, match="no tiene tamaño"):
            redactar.redactar(
                _pdf(tmp_path), tmp_path / "x.pdf", areas=[redactar.Area(1, 10, 10, 10, 20)]
            )


class TestRechazos:
    def test_un_termino_de_una_letra(self):
        with pytest.raises(redactar.ComposicionInvalida, match="una sola letra"):
            redactar.limpiar_terminos(["a"])

    def test_se_quitan_vacios_y_repetidos(self):
        assert redactar.limpiar_terminos(["  Juan  ", "juan", "", "Soto"]) == ["Juan", "Soto"]

    def test_una_resolucion_que_no_se_ofrece(self, tmp_path):
        with pytest.raises(redactar.ComposicionInvalida):
            redactar.redactar(_pdf(tmp_path), tmp_path / "x.pdf", terminos=[RUT], ppp=999)

    def test_el_original_no_se_toca(self, tmp_path):
        origen = _pdf(tmp_path)
        antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        redactar.redactar(origen, tmp_path / "x.pdf", terminos=[RUT])
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes

    def test_no_pasa_nada_del_info_original(self, tmp_path):
        origen = _pdf(tmp_path)
        with pikepdf.open(origen, allow_overwriting_input=True) as pdf:
            pdf.docinfo["/Author"] = "Ana Perez Reservada"
            pdf.save(origen)
        destino = tmp_path / "redactado.pdf"
        redactar.redactar(origen, destino, terminos=[RUT])
        assert b"Reservada" not in _bytes_de_todos_los_flujos(destino)


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_toma_los_terminos_del_entorno_y_no_de_las_opciones(
        self, tmp_path, monkeypatch
    ):
        import json

        monkeypatch.setenv(tarea.VARIABLE_CONTRASENA, json.dumps([RUT]))
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "redactar",
            {"entradas": [{"ruta": str(_pdf(tmp_path))}], "opciones": {"ppp": 200}},
            parcial,
        )
        assert "codigo" not in informe
        assert informe["detalles"]["coincidencias"] == [1]
        # Lo que vuelve al corredor no lleva el término.
        assert RUT not in json.dumps(informe)
        assert RUT not in _texto_pypdf(parcial)

    def test_sin_terminos_ni_areas_falla_con_su_codigo(self, tmp_path, monkeypatch):
        monkeypatch.delenv(tarea.VARIABLE_CONTRASENA, raising=False)
        informe = tarea.ejecutar(
            "redactar",
            {"entradas": [{"ruta": str(_pdf(tmp_path))}], "opciones": {}},
            tmp_path / "salida.parcial",
        )
        assert informe["codigo"] == "documento-invalido"

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:redactar")).status_code == 302

    def test_la_pantalla_avisa_del_precio(self, sesion):
        cuerpo = sesion.get(reverse("documents:redactar")).content.decode()
        assert "ya no tienen texto" in cuerpo

    def test_sin_nada_que_tachar_avisa(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:redactar"),
            {"ruta": str(_pdf(tmp_path)), "accion": "redactar", "terminos": ""},
        )
        assert respuesta.status_code == 200
        assert "Escriba qué tachar" in respuesta.content.decode()

    def test_redactar_encola_y_el_termino_no_queda_en_la_base(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(
            reverse("documents:redactar"),
            {"ruta": str(_pdf(tmp_path)), "accion": "redactar", "terminos": RUT, "ppp": "200"},
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        trabajo = ConversionJob.objects.latest("created_at")
        # Ni en las opciones, ni en la bitácora: el término es justo lo que se tapa.
        assert RUT not in str(trabajo.options)
        assert despachador.procesar_una_vez() == 1
        trabajo.refresh_from_db()
        assert trabajo.status == "done", trabajo.reason_detail
        assert RUT not in str(trabajo.options) and RUT not in str(trabajo.verification)
        assert RUT not in _texto_pypdf(Path(trabajo.output_path))
