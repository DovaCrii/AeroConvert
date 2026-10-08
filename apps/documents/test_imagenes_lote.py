"""Convertir imágenes por lote (F14.13).

**El oráculo es Pillow reabriendo cada salida**: el formato real (por su cabecera, no por la
extensión) y las dimensiones tienen que ser los que se calculan **a mano aquí** a partir de la
imagen de entrada (400 × 200 a 100 px de lado mayor son 100 × 50). El EXIF y el GPS se escriben a
mano en la entrada y se leen de la salida.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image

from apps.documents import imagenes_lote, motor, tarea

pytestmark = pytest.mark.django_db

#: Latitud y longitud de la prueba, en grados decimales, y como las guarda el EXIF: (grados,
#: minutos, segundos) con su hemisferio.
LAT, LON = -33.45, -70.66


def _gps_exif() -> Image.Exif:
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "S", (33.0, 27.0, 0.0)
    gps[3], gps[4] = "W", (70.0, 39.0, 36.0)
    return exif


def _foto(carpeta: Path, nombre: str, tamano=(400, 200), color=(200, 30, 30), exif=None) -> Path:
    ruta = carpeta / nombre
    imagen = Image.new("RGB", tamano, color)
    formato = {"png": "PNG", "webp": "WEBP", "tif": "TIFF"}.get(
        ruta.suffix.lstrip(".").lower(), "JPEG"
    )
    if exif is not None and formato in ("JPEG", "WEBP", "TIFF"):
        imagen.save(ruta, formato, exif=exif)
    else:
        imagen.save(ruta, formato)
    return ruta


def _leer(ruta: Path) -> tuple[str, tuple[int, int]]:
    with Image.open(ruta) as imagen:
        imagen.load()
        return imagen.format, imagen.size


def _procesar(tmp_path, entradas, **opciones):
    carpeta = tmp_path / "salida"
    carpeta.mkdir(exist_ok=True)
    return carpeta, imagenes_lote.procesar([Path(e) for e in entradas], carpeta, **opciones)


class TestFormatoYTamano:
    @pytest.mark.parametrize(
        ("formato", "esperado"),
        [("jpg", "JPEG"), ("png", "PNG"), ("webp", "WEBP"), ("tiff", "TIFF")],
    )
    def test_el_formato_real_es_el_pedido(self, tmp_path, formato, esperado):
        carpeta, hechas = _procesar(
            tmp_path, [_foto(tmp_path, "a.jpg")], formato=formato, lado_max=0
        )
        assert _leer(carpeta / hechas[0].salida) == (esperado, (400, 200))

    def test_achica_el_lado_mayor_sin_deformar(self, tmp_path):
        carpeta, hechas = _procesar(tmp_path, [_foto(tmp_path, "a.jpg")], lado_max=1024)
        assert _leer(carpeta / hechas[0].salida)[1] == (400, 200)  # no agranda
        grande = _foto(tmp_path, "g.jpg", tamano=(4000, 2000))
        carpeta2, hechas2 = _procesar(
            tmp_path / "x" if False else tmp_path, [grande], lado_max=1024
        )
        assert _leer(carpeta2 / hechas2[0].salida)[1] == (1024, 512)

    def test_nunca_agranda(self, tmp_path):
        carpeta, hechas = _procesar(
            tmp_path, [_foto(tmp_path, "a.jpg", tamano=(300, 100))], lado_max=2048
        )
        assert (hechas[0].ancho, hechas[0].alto) == (300, 100)

    @pytest.mark.parametrize(
        ("recorte", "esperado"),
        [("1:1", (200, 200)), ("16:9", (356, 200)), ("4:3", (267, 200))],
    )
    def test_recorta_al_centro_a_la_proporcion(self, tmp_path, recorte, esperado):
        carpeta, hechas = _procesar(tmp_path, [_foto(tmp_path, "a.jpg")], recorte=recorte)
        ancho, alto = _leer(carpeta / hechas[0].salida)[1]
        assert abs(ancho - esperado[0]) <= 1 and alto == esperado[1]

    def test_el_recorte_conserva_el_centro(self, tmp_path):
        # Izquierda roja, derecha azul: un recorte 1:1 de 400×200 deja 100 de cada lado.
        ruta = tmp_path / "dos.png"
        imagen = Image.new("RGB", (400, 200), (255, 0, 0))
        imagen.paste((0, 0, 255), (200, 0, 400, 200))
        imagen.save(ruta)
        carpeta, hechas = _procesar(tmp_path, [ruta], formato="png", recorte="1:1")
        with Image.open(carpeta / hechas[0].salida) as salida:
            assert salida.getpixel((10, 100)) == (255, 0, 0)
            assert salida.getpixel((190, 100)) == (0, 0, 255)

    def test_gira_noventa_grados(self, tmp_path):
        carpeta, hechas = _procesar(tmp_path, [_foto(tmp_path, "a.jpg")], giro="90")
        assert _leer(carpeta / hechas[0].salida)[1] == (200, 400)

    def test_a_la_derecha_lleva_arriba_lo_que_estaba_a_la_izquierda(self, tmp_path):
        ruta = tmp_path / "dos.png"
        imagen = Image.new("RGB", (40, 20), (0, 0, 255))
        imagen.paste((255, 0, 0), (0, 0, 20, 20))  # izquierda roja
        imagen.save(ruta)
        carpeta, hechas = _procesar(tmp_path, [ruta], formato="png", giro="90", lado_max=0)
        with Image.open(carpeta / hechas[0].salida) as salida:
            assert salida.getpixel((10, 5)) == (255, 0, 0)  # lo de la izquierda quedó arriba


class TestLoQueSeConserva:
    def test_la_orientacion_de_la_foto_se_aplica_y_la_marca_vuelve_a_normal(self, tmp_path):
        exif = Image.Exif()
        exif[0x0112] = 6  # «girar 90° a la derecha para verla bien»
        carpeta, hechas = _procesar(tmp_path, [_foto(tmp_path, "a.jpg", exif=exif)], giro="exif")
        ruta = carpeta / hechas[0].salida
        assert _leer(ruta)[1] == (200, 400)
        with Image.open(ruta) as salida:
            assert salida.getexif().get(0x0112) == 1

    def test_el_gps_sobrevive_a_jpg_webp_y_tiff(self, tmp_path):
        origen = _foto(tmp_path, "a.jpg", exif=_gps_exif())
        for formato in ("jpg", "webp", "tiff"):
            carpeta = tmp_path / f"s_{formato}"
            carpeta.mkdir()
            hechas = imagenes_lote.procesar([origen], carpeta, formato=formato)
            with Image.open(carpeta / hechas[0].salida) as salida:
                gps = salida.getexif().get_ifd(0x8825)
            assert gps.get(1) == "S" and gps.get(3) == "W", formato
            assert tuple(round(float(v)) for v in gps[2]) == (33, 27, 0), formato

    def test_un_png_con_transparencia_a_jpg_queda_sobre_blanco(self, tmp_path):
        ruta = tmp_path / "t.png"
        Image.new("RGBA", (50, 50), (255, 0, 0, 0)).save(ruta)
        carpeta, hechas = _procesar(tmp_path, [ruta], formato="jpg")
        with Image.open(carpeta / hechas[0].salida) as salida:
            assert all(c >= 250 for c in salida.convert("RGB").getpixel((25, 25)))

    def test_el_color_sobrevive_al_cambio_de_formato(self, tmp_path):
        carpeta, hechas = _procesar(
            tmp_path, [_foto(tmp_path, "a.png")], formato="webp", calidad=95
        )
        with Image.open(carpeta / hechas[0].salida) as salida:
            rojo, verde, azul = salida.convert("RGB").getpixel((10, 10))
        assert rojo > 180 and verde < 60 and azul < 60


class TestElLote:
    def test_una_salida_por_entrada_con_su_nombre(self, tmp_path):
        entradas = [
            _foto(tmp_path, "uno.png"),
            _foto(tmp_path, "dos.webp"),
            _foto(tmp_path, "tres.tif"),
        ]
        carpeta, hechas = _procesar(tmp_path, entradas, formato="jpg")
        assert [h.salida for h in hechas] == ["uno.jpg", "dos.jpg", "tres.jpg"]
        assert sorted(p.name for p in carpeta.iterdir()) == ["dos.jpg", "tres.jpg", "uno.jpg"]

    def test_dos_con_el_mismo_nombre_no_se_pisan(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        entradas = [_foto(tmp_path / "a", "foto.png"), _foto(tmp_path / "b", "foto.jpg")]
        carpeta, hechas = _procesar(tmp_path, entradas, formato="jpg")
        assert [h.salida for h in hechas] == ["foto.jpg", "foto_2.jpg"]

    def test_todo_o_nada_si_una_no_se_abre(self, tmp_path):
        rota = tmp_path / "rota.jpg"
        rota.write_bytes(b"esto no es una foto")
        carpeta = tmp_path / "salida"
        carpeta.mkdir()
        with pytest.raises(imagenes_lote.ComposicionInvalida, match="rota.jpg no se pudo abrir"):
            imagenes_lote.procesar([_foto(tmp_path, "ok.jpg"), rota], carpeta)
        assert list(carpeta.iterdir()) == []

    def test_opciones_fuera_de_lo_que_se_ofrece(self, tmp_path):
        foto = _foto(tmp_path, "a.jpg")
        for opciones in (
            {"formato": "bmp"},
            {"lado_max": 999},
            {"giro": "45"},
            {"recorte": "5:4"},
            {"calidad": 10},
        ):
            with pytest.raises(imagenes_lote.ComposicionInvalida):
                imagenes_lote.procesar([foto], tmp_path, **opciones)

    def test_ninguna_imagen_o_demasiadas_se_rechazan(self, tmp_path):
        with pytest.raises(imagenes_lote.ComposicionInvalida, match="ninguna"):
            imagenes_lote.procesar([], tmp_path)
        with pytest.raises(imagenes_lote.ComposicionInvalida, match="máximo"):
            imagenes_lote.procesar([tmp_path / "x.jpg"] * 201, tmp_path)

    def test_los_originales_no_se_tocan(self, tmp_path):
        import hashlib

        origen = _foto(tmp_path, "a.jpg")
        antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        _procesar(tmp_path, [origen], formato="png", lado_max=1024, giro="90")
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes


class TestLosFormatosQueNoSeLeen:
    def test_heic_sin_el_lector_se_dice_y_como_arreglarlo(self, monkeypatch):
        monkeypatch.setattr(imagenes_lote, "_registrar_heic", lambda: False)
        motivo = imagenes_lote.motivo_si_no_se_lee("IMG_0001.HEIC")
        assert "pillow-heif" in motivo and "IMG_0001.HEIC" in motivo

    def test_heic_con_el_lector_se_admite(self, monkeypatch):
        monkeypatch.setattr(imagenes_lote, "_registrar_heic", lambda: True)
        assert imagenes_lote.motivo_si_no_se_lee("IMG_0001.HEIC") == ""

    def test_lo_que_no_es_imagen_se_rechaza(self):
        assert "no es una imagen" in imagenes_lote.motivo_si_no_se_lee("plano.dwg")

    def test_avif_y_webp_se_leen_de_fabrica(self):
        for nombre in ("a.avif", "a.webp", "a.tif"):
            assert imagenes_lote.motivo_si_no_se_lee(nombre) == ""


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_entrega_un_zip_con_las_medidas_dichas(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        entradas = [{"ruta": str(_foto(tmp_path, "a.jpg", tamano=(4000, 2000)))}]
        informe = tarea.ejecutar(
            "imagenes_lote",
            {"entradas": entradas, "opciones": {"formato": "webp", "lado_max": 1024}},
            parcial,
        )
        assert "codigo" not in informe
        assert informe["detalles"]["piezas"] == [
            {"nombre": "a.webp", "ancho": 1024, "alto": 512, "formato": "WEBP"}
        ]
        with zipfile.ZipFile(parcial) as z:
            assert z.namelist() == ["a.webp"]
            with Image.open(io.BytesIO(z.read("a.webp"))) as dentro:
                assert (dentro.format, dentro.size) == ("WEBP", (1024, 512))

    def test_una_sola_imagen_tambien_va_en_zip(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        tarea.ejecutar(
            "imagenes_lote",
            {"entradas": [{"ruta": str(_foto(tmp_path, "a.jpg"))}], "opciones": {}},
            parcial,
        )
        assert zipfile.is_zipfile(parcial)

    def test_la_verificacion_compara_lo_que_se_dijo_con_lo_que_pillow_lee(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        parcial.parent.mkdir(exist_ok=True)
        buffer = io.BytesIO()
        Image.new("RGB", (100, 50)).save(buffer, "JPEG")
        with zipfile.ZipFile(parcial.with_suffix(".zip"), "w") as z:
            z.writestr("a.jpg", buffer.getvalue())
        zip_ = parcial.with_suffix(".zip")
        bien = {"piezas": [{"nombre": "a.jpg", "ancho": 100, "alto": 50, "formato": "JPEG"}]}
        assert motor.verificar(zip_, {"detalles": bien}).correcta
        mal = {"piezas": [{"nombre": "a.jpg", "ancho": 100, "alto": 51, "formato": "JPEG"}]}
        veredicto = motor.verificar(zip_, {"detalles": mal})
        assert not veredicto.correcta and "debía medir 100×51" in veredicto.motivo
        otro = {"piezas": [{"nombre": "a.jpg", "ancho": 100, "alto": 50, "formato": "PNG"}]}
        assert not motor.verificar(zip_, {"detalles": otro}).correcta

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:imagenes_lote")).status_code == 302

    def test_la_pantalla_dice_que_formatos_lee(self, sesion):
        cuerpo = sesion.get(reverse("documents:imagenes_lote")).content.decode()
        assert "webp" in cuerpo and "una imagen por cada una" in cuerpo

    def test_sin_imagenes_avisa(self, sesion):
        respuesta = sesion.post(reverse("documents:imagenes_lote"), {"archivos_texto": ""})
        assert (
            respuesta.status_code == 200
            and "No indicó ninguna imagen" in respuesta.content.decode()
        )

    def test_un_heic_sin_lector_avisa_antes_de_encolar(self, sesion, tmp_path, monkeypatch):
        monkeypatch.setattr(imagenes_lote, "_registrar_heic", lambda: False)
        heic = tmp_path / "IMG_1.heic"
        heic.write_bytes(b"\x00\x00\x00\x18ftypheic")
        respuesta = sesion.post(reverse("documents:imagenes_lote"), {"archivos_texto": str(heic)})
        assert respuesta.status_code == 200 and "pillow-heif" in respuesta.content.decode()

    def test_convertir_encola_y_el_zip_trae_las_medidas(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        a = _foto(tmp_path, "a.jpg", tamano=(4000, 2000))
        b = _foto(tmp_path, "b.png", tamano=(800, 600))
        respuesta = sesion.post(
            reverse("documents:imagenes_lote"),
            {"archivos_texto": f"{a}\n{b}", "formato": "jpg", "lado_max": "1024", "calidad": "85"},
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as z:
            medidas = {}
            for nombre in z.namelist():
                with Image.open(io.BytesIO(z.read(nombre))) as dentro:
                    medidas[nombre] = (dentro.format, dentro.size)
        assert medidas == {"a.jpg": ("JPEG", (1024, 512)), "b.jpg": ("JPEG", (800, 600))}
