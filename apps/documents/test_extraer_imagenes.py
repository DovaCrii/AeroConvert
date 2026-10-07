"""Extraer las imágenes incrustadas de un PDF (F14.1).

**El oráculo son las imágenes de entrada**: se arma un PDF con imágenes de tamaño y color
conocidos y lo que sale tiene que ser eso, abierto con Pillow —que no escribió el PDF— y
contado con un lector distinto del que las extrajo.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from apps.documents import dividir, extraer_imagenes, tarea

pytestmark = pytest.mark.django_db


def _imagen(carpeta: Path, nombre: str, tamano, color) -> Path:
    ruta = carpeta / nombre
    Image.new("RGB", tamano, color).save(ruta)
    return ruta


def _pdf_con(carpeta: Path, imagenes: list[Path], nombre: str = "informe.pdf") -> Path:
    destino = carpeta / nombre
    dividir.desde_imagenes(imagenes, destino, tamano="imagen")
    return destino


def _tamanos(rutas) -> list[tuple[int, int]]:
    medidas = []
    for ruta in rutas:
        with Image.open(ruta) as imagen:
            imagen.load()
            medidas.append(imagen.size)
    return medidas


class TestExtraer:
    def test_salen_las_imagenes_con_su_tamano_original(self, tmp_path):
        a = _imagen(tmp_path, "a.png", (120, 80), (200, 30, 30))
        b = _imagen(tmp_path, "b.png", (200, 100), (30, 200, 30))
        pdf = _pdf_con(tmp_path, [a, b])
        salida = tmp_path / "salida"
        salida.mkdir()

        escritas = extraer_imagenes.extraer(pdf, salida)

        assert sorted(_tamanos(escritas)) == [(120, 80), (200, 100)]
        # Y el color sobrevive: no se volvió a dibujar ni a muestrear.
        with Image.open(escritas[0]) as primera:
            pixel = primera.convert("RGB").getpixel((5, 5))
            # JPEG al incrustar: el color llega con unas décimas de diferencia, no cambiado.
            assert all(abs(a - b) <= 8 for a, b in zip(pixel, (200, 30, 30), strict=True))

    def test_las_diminutas_no_cuentan(self, tmp_path):
        grande = _imagen(tmp_path, "g.png", (150, 90), (10, 10, 200))
        chica = _imagen(tmp_path, "c.png", (16, 16), (0, 0, 0))
        pdf = _pdf_con(tmp_path, [grande, chica])
        salida = tmp_path / "salida"
        salida.mkdir()

        assert _tamanos(extraer_imagenes.extraer(pdf, salida)) == [(150, 90)]

    def test_una_imagen_repetida_sale_una_vez(self, tmp_path):
        origen = _imagen(tmp_path, "logo.png", (140, 70), (90, 90, 90))
        base = _pdf_con(tmp_path, [origen], "base.pdf")
        lector = PdfReader(str(base))
        escritor = PdfWriter()
        for _ in range(3):
            escritor.add_page(lector.pages[0])
        repetido = tmp_path / "repetido.pdf"
        with open(repetido, "wb") as f:
            escritor.write(f)
        # El oráculo del supuesto: tres páginas que comparten el mismo objeto de imagen.
        ids = {
            p.images[0].indirect_reference.idnum for p in PdfReader(str(repetido)).pages if p.images
        }
        salida = tmp_path / "salida"
        salida.mkdir()

        escritas = extraer_imagenes.extraer(repetido, salida)

        assert len(escritas) == len(ids)

    def test_un_pdf_sin_imagenes_dice_que_no_hay(self, tmp_path):
        escritor = PdfWriter()
        escritor.add_blank_page(width=200, height=200)
        pdf = tmp_path / "vacio.pdf"
        with open(pdf, "wb") as f:
            escritor.write(f)
        with pytest.raises(extraer_imagenes.SinImagenes):
            extraer_imagenes.extraer(pdf, tmp_path)

    def test_el_original_no_se_toca(self, tmp_path):
        import hashlib

        pdf = _pdf_con(tmp_path, [_imagen(tmp_path, "a.png", (100, 60), (1, 2, 3))])
        antes = (hashlib.sha256(pdf.read_bytes()).hexdigest(), pdf.stat().st_mtime_ns)
        salida = tmp_path / "salida"
        salida.mkdir()
        extraer_imagenes.extraer(pdf, salida)
        assert (hashlib.sha256(pdf.read_bytes()).hexdigest(), pdf.stat().st_mtime_ns) == antes

    def test_un_pdf_cifrado_se_rechaza_con_su_motivo(self, tmp_path):
        escritor = PdfWriter()
        escritor.add_blank_page(width=100, height=100)
        escritor.encrypt("clave")
        pdf = tmp_path / "cifrado.pdf"
        with open(pdf, "wb") as f:
            escritor.write(f)
        with pytest.raises(extraer_imagenes.ComposicionInvalida, match="contraseña"):
            extraer_imagenes.extraer(pdf, tmp_path)

    def test_un_archivo_que_no_es_pdf_se_rechaza(self, tmp_path):
        basura = tmp_path / "x.pdf"
        basura.write_bytes(b"esto no es un pdf")
        with pytest.raises(extraer_imagenes.ComposicionInvalida):
            extraer_imagenes.extraer(basura, tmp_path)


class TestEnLaTarea:
    def test_siempre_entrega_un_zip_aunque_haya_una_sola(self, tmp_path):
        pdf = _pdf_con(tmp_path, [_imagen(tmp_path, "a.png", (100, 60), (5, 5, 5))])
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "extraer_imagenes", {"entradas": [{"ruta": str(pdf)}], "opciones": {}}, parcial
        )
        assert "codigo" not in informe
        with zipfile.ZipFile(parcial) as paquete:
            assert len(paquete.namelist()) == 1
            with Image.open(BytesIO(paquete.read(paquete.namelist()[0]))) as imagen:
                assert imagen.size == (100, 60)

    def test_sin_imagenes_no_hay_archivo_y_se_explica(self, tmp_path):
        escritor = PdfWriter()
        escritor.add_blank_page(width=200, height=200)
        pdf = tmp_path / "vacio.pdf"
        with open(pdf, "wb") as f:
            escritor.write(f)
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "extraer_imagenes", {"entradas": [{"ruta": str(pdf)}], "opciones": {}}, parcial
        )
        assert informe["desenlace"] == "sin-imagenes"
        assert not parcial.exists()
        assert not parcial.with_name(parcial.name + ".piezas").exists()


class TestLaPantalla:
    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:extraer_imagenes")).status_code == 302

    def test_carga_y_ofrece_extraer_despues_de_mirar(self, sesion, tmp_path):
        pdf = _pdf_con(tmp_path, [_imagen(tmp_path, "a.png", (100, 60), (5, 5, 5))])
        url = reverse("documents:extraer_imagenes")
        assert "Extraer imágenes" in sesion.get(url).content.decode()
        cuerpo = sesion.post(url, {"ruta": str(pdf), "accion": "mirar"}).content.decode()
        assert 'value="extraer"' in cuerpo

    def test_extraer_encola_y_el_zip_trae_la_imagen(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        pdf = _pdf_con(tmp_path, [_imagen(tmp_path, "a.png", (130, 70), (9, 99, 199))])
        respuesta = sesion.post(
            reverse("documents:extraer_imagenes"), {"ruta": str(pdf), "accion": "extraer"}
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as paquete:
            nombres = paquete.namelist()
            assert len(nombres) == 1
            with Image.open(BytesIO(paquete.read(nombres[0]))) as imagen:
                assert imagen.size == (130, 70)
