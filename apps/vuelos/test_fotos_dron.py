"""Fotos de dron (F14.14): quitar la posición, sacarla a un KMZ o GeoJSON y renombrar.

Las fotos de partida se **escriben con coordenadas, fecha y XMP conocidos** (Pillow las crea). Lo
que sale se lee con **`exifread`**, otro lector que el que escribió los bytes, y con `ogrinfo`
cuando GDAL está. La prueba de que no se recodifica es que los datos de imagen quedan
**idénticos byte por byte**, no que «se ve igual».
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import exifread
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image

from apps.documents import motor, tarea
from apps.documents.composicion import ComposicionInvalida
from apps.vuelos import fotos_dron

XMP = (
    b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF>"
    b"<rdf:Description drone-dji:GpsLatitude='-33.4500' drone-dji:GpsLongitude='-70.6500'/>"
    b"</rdf:RDF></x:xmpmeta>"
)


def _foto(
    ruta: Path,
    *,
    lat: float | None = -33.45,
    lon: float | None = -70.65,
    alt: float = 520.5,
    fecha: str | None = "2026:09:30 10:15:02",
    color: tuple[int, int, int] = (200, 30, 30),
) -> Path:
    imagen = Image.new("RGB", (64, 48), color)
    exif = Image.Exif()
    exif[0x010F] = "DJI"
    exif[0x0110] = "FC6310"
    if fecha:
        exif.get_ifd(0x8769)[0x9003] = fecha
    if lat is not None and lon is not None:
        gps = exif.get_ifd(0x8825)
        gps[1] = "S" if lat < 0 else "N"
        gps[2] = (abs(lat) // 1, (abs(lat) % 1) * 60 // 1, ((abs(lat) % 1) * 60 % 1) * 60)
        gps[3] = "W" if lon < 0 else "E"
        gps[4] = (abs(lon) // 1, (abs(lon) % 1) * 60 // 1, ((abs(lon) % 1) * 60 % 1) * 60)
        gps[5] = 0
        gps[6] = alt
    imagen.save(ruta, "JPEG", exif=exif, xmp=XMP, quality=90)
    return ruta


def _leer_exifread(datos: bytes) -> dict:
    return exifread.process_file(io.BytesIO(datos), details=False)


def _datos_de_imagen(datos: bytes) -> bytes:
    """Todo lo que va desde SOS: los píxeles comprimidos, que no deben cambiar."""
    return datos[datos.index(b"\xff\xda") :]


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class TestLeer:
    def test_la_posicion_leida_es_la_que_se_escribio(self, tmp_path):
        foto = fotos_dron.leer(_foto(tmp_path / "a.jpg"))
        assert foto.lat == pytest.approx(-33.45, abs=1e-6)
        assert foto.lon == pytest.approx(-70.65, abs=1e-6)
        assert foto.alt_m == pytest.approx(520.5)
        assert foto.fecha.isoformat() == "2026-09-30T10:15:02"

    def test_el_oraculo_exifread_coincide_con_lo_escrito(self, tmp_path):
        etiquetas = _leer_exifread(_foto(tmp_path / "a.jpg").read_bytes())
        assert str(etiquetas["GPS GPSLatitudeRef"]) == "S"
        assert str(etiquetas["GPS GPSLongitudeRef"]) == "W"
        grados, minutos, segundos = (
            float(x.num) / float(x.den) for x in etiquetas["GPS GPSLatitude"].values
        )
        assert -(grados + minutos / 60 + segundos / 3600) == pytest.approx(-33.45, abs=1e-6)

    def test_sin_posicion_no_inventa_nada(self, tmp_path):
        foto = fotos_dron.leer(_foto(tmp_path / "a.jpg", lat=None, lon=None))
        assert not foto.tiene_posicion and foto.lat is None

    def test_una_posicion_fuera_de_rango_se_descarta(self, tmp_path):
        foto = fotos_dron.leer(_foto(tmp_path / "a.jpg", lat=-133.0))
        assert not foto.tiene_posicion


class TestQuitarGps:
    def test_exifread_ya_no_ve_posicion_y_si_ve_lo_demas(self, tmp_path):
        original = _foto(tmp_path / "a.jpg").read_bytes()
        limpia = fotos_dron.quitar_gps(original)
        etiquetas = _leer_exifread(limpia)
        assert not [k for k in etiquetas if k.startswith("GPS")]
        assert str(etiquetas["Image Make"]) == "DJI"
        assert str(etiquetas["EXIF DateTimeOriginal"]) == "2026:09:30 10:15:02"

    def test_el_xmp_con_la_posicion_desaparece(self, tmp_path):
        original = _foto(tmp_path / "a.jpg").read_bytes()
        assert b"GpsLatitude" in original
        assert b"GpsLatitude" not in fotos_dron.quitar_gps(original)

    def test_los_pixeles_no_se_recodifican(self, tmp_path):
        original = _foto(tmp_path / "a.jpg").read_bytes()
        limpia = fotos_dron.quitar_gps(original)
        assert _datos_de_imagen(limpia) == _datos_de_imagen(original)
        con_pillow = Image.open(io.BytesIO(limpia))
        assert con_pillow.size == (64, 48)
        assert Image.open(io.BytesIO(original)).tobytes() == con_pillow.tobytes()

    def test_la_altura_tampoco_queda_en_los_bytes(self, tmp_path):
        # 520.5 m se escribe como el racional 1041/2; ni ese par ni la latitud pueden seguir ahí.
        import struct

        original = _foto(tmp_path / "a.jpg", alt=520.5).read_bytes()
        pares = [struct.pack(">II", 1041, 2), struct.pack("<II", 1041, 2)]
        assert any(p in original for p in pares)
        assert not any(p in fotos_dron.quitar_gps(original) for p in pares)

    def test_pillow_tambien_lee_un_bloque_gps_vacio(self, tmp_path):
        limpia = fotos_dron.quitar_gps(_foto(tmp_path / "a.jpg").read_bytes())
        assert Image.open(io.BytesIO(limpia)).getexif().get_ifd(0x8825) == {}

    def test_una_foto_sin_gps_pasa_sin_dano(self, tmp_path):
        original = _foto(tmp_path / "a.jpg", lat=None, lon=None).read_bytes()
        limpia = fotos_dron.quitar_gps(original)
        assert _datos_de_imagen(limpia) == _datos_de_imagen(original)
        assert str(_leer_exifread(limpia)["Image Make"]) == "DJI"

    def test_lo_que_no_es_jpeg_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="No es un JPEG"):
            fotos_dron.quitar_gps(b"GIF89a....")

    def test_un_jpeg_cortado_se_rechaza(self, tmp_path):
        datos = _foto(tmp_path / "a.jpg").read_bytes()
        with pytest.raises(ComposicionInvalida):
            fotos_dron.quitar_gps(datos[:30])


class TestProcesar:
    def _vuelo(self, tmp_path):
        a = _foto(tmp_path / "IMG_0002.jpg", lat=-33.45, lon=-70.65, fecha="2026:09:30 10:15:09")
        b = _foto(tmp_path / "IMG_0001.jpg", lat=-33.46, lon=-70.66, fecha="2026:09:30 10:15:02")
        c = _foto(tmp_path / "IMG_0003.jpg", lat=None, lon=None, fecha="2026:09:30 10:15:20")
        return [a, b, c]

    def test_conservar_copia_byte_por_byte(self, tmp_path):
        origenes = self._vuelo(tmp_path)
        salida = tmp_path / "s"
        salida.mkdir()
        hecho = fotos_dron.procesar(origenes, salida)
        assert [f.salida for f in hecho.fotos] == ["IMG_0002.jpg", "IMG_0001.jpg", "IMG_0003.jpg"]
        for origen in origenes:
            assert _sha(salida / origen.name) == _sha(origen)

    def test_quitar_deja_a_exifread_sin_posicion_en_todas(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        fotos_dron.procesar(self._vuelo(tmp_path), salida, gps="quitar")
        for foto in salida.glob("*.jpg"):
            assert not [k for k in _leer_exifread(foto.read_bytes()) if k.startswith("GPS")]

    def test_renombrar_por_fecha(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        hecho = fotos_dron.procesar(self._vuelo(tmp_path), salida, nombres="fecha")
        assert [f.salida for f in hecho.fotos] == [
            "20260930_101509.jpg",
            "20260930_101502.jpg",
            "20260930_101520.jpg",
        ]

    def test_dos_fotos_de_la_misma_hora_no_se_pisan(self, tmp_path):
        a = _foto(tmp_path / "a.jpg")
        b = _foto(tmp_path / "b.jpg")
        salida = tmp_path / "s"
        salida.mkdir()
        hecho = fotos_dron.procesar([a, b], salida, nombres="fecha")
        assert sorted(f.salida for f in hecho.fotos) == [
            "20260930_101502.jpg",
            "20260930_101502_2.jpg",
        ]

    def test_renombrar_por_vuelo_ordena_por_hora_de_toma(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        hecho = fotos_dron.procesar(self._vuelo(tmp_path), salida, nombres="vuelo")
        por_origen = {f.entrada: f.salida for f in hecho.fotos}
        assert por_origen == {
            "IMG_0001.jpg": "vuelo_0001.jpg",
            "IMG_0002.jpg": "vuelo_0002.jpg",
            "IMG_0003.jpg": "vuelo_0003.jpg",
        }

    def test_una_foto_sin_fecha_impide_renombrar_por_fecha_y_no_deja_nada(self, tmp_path):
        a = _foto(tmp_path / "a.jpg")
        b = _foto(tmp_path / "b.jpg", fecha=None)
        salida = tmp_path / "s"
        salida.mkdir()
        with pytest.raises(ComposicionInvalida, match="b.jpg no trae fecha"):
            fotos_dron.procesar([a, b], salida, nombres="fecha")
        assert list(salida.iterdir()) == []

    def test_geojson_tiene_una_posicion_por_foto_con_gps(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        hecho = fotos_dron.procesar(self._vuelo(tmp_path), salida, posiciones="geojson")
        assert hecho.posiciones == "posiciones.geojson" and hecho.sin_posicion == 1
        datos = json.loads((salida / "posiciones.geojson").read_text(encoding="utf-8"))
        puntos = {r["properties"]["foto"]: r["geometry"]["coordinates"] for r in datos["features"]}
        assert set(puntos) == {"IMG_0002.jpg", "IMG_0001.jpg"}
        assert puntos["IMG_0001.jpg"][:2] == pytest.approx([-70.66, -33.46], abs=1e-6)
        assert puntos["IMG_0001.jpg"][2] == pytest.approx(520.5)

    def test_las_posiciones_salen_aunque_se_quite_el_gps_de_las_fotos(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        fotos_dron.procesar(self._vuelo(tmp_path), salida, gps="quitar", posiciones="geojson")
        assert len(json.loads((salida / "posiciones.geojson").read_text("utf-8"))["features"]) == 2

    def test_kmz_es_un_zip_con_un_kml_de_tantas_marcas_como_fotos_con_gps(self, tmp_path):
        from xml.etree import ElementTree as ET

        salida = tmp_path / "s"
        salida.mkdir()
        fotos_dron.procesar(self._vuelo(tmp_path), salida, posiciones="kmz", nombres="vuelo")
        with zipfile.ZipFile(salida / "posiciones.kmz") as paquete:
            assert paquete.namelist() == ["doc.kml"]
            raiz = ET.fromstring(paquete.read("doc.kml"))
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        nombres = sorted(n.text for n in raiz.findall(".//k:Placemark/k:name", ns))
        assert nombres == ["vuelo_0001.jpg", "vuelo_0002.jpg"]

    def test_el_nombre_en_el_kml_se_escapa(self, tmp_path):
        foto = fotos_dron.Foto("a<b>&.jpg", -33.0, -70.0, None, None)
        kml = fotos_dron.a_kml([(foto.nombre, foto)])
        assert "a&lt;b&gt;&amp;.jpg" in kml

    @pytest.mark.oraculo
    @pytest.mark.skipif(not shutil.which("ogrinfo"), reason="sin ogrinfo")
    def test_ogrinfo_abre_el_kmz_y_cuenta_las_fotos(self, tmp_path):
        salida = tmp_path / "s"
        salida.mkdir()
        fotos_dron.procesar(self._vuelo(tmp_path), salida, posiciones="kmz")
        r = subprocess.run(  # noqa: S603
            ["ogrinfo", "-so", "-al", str(salida / "posiciones.kmz")],  # noqa: S607
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
        assert "Feature Count: 2" in r.stdout

    def test_sin_ninguna_posicion_y_con_archivo_pedido_es_un_error(self, tmp_path):
        a = _foto(tmp_path / "a.jpg", lat=None, lon=None)
        salida = tmp_path / "s"
        salida.mkdir()
        with pytest.raises(ComposicionInvalida, match="Ninguna de las fotos trae posición"):
            fotos_dron.procesar([a], salida, posiciones="kmz")

    def test_el_original_no_se_toca_ni_al_quitar_ni_al_fallar(self, tmp_path):
        a = _foto(tmp_path / "a.jpg")
        b = _foto(tmp_path / "b.jpg", fecha=None)
        antes = {p: (_sha(p), p.stat().st_mtime_ns) for p in (a, b)}
        salida = tmp_path / "s"
        salida.mkdir()
        fotos_dron.procesar([a, b], salida, gps="quitar")
        with pytest.raises(ComposicionInvalida):
            fotos_dron.procesar([a, b], salida, nombres="fecha")
        assert {p: (_sha(p), p.stat().st_mtime_ns) for p in (a, b)} == antes

    @pytest.mark.parametrize(
        "campo,valor",
        [("gps", "x"), ("nombres", "x"), ("posiciones", "x")],
    )
    def test_opciones_desconocidas_se_rechazan(self, tmp_path, campo, valor):
        with pytest.raises(ComposicionInvalida):
            fotos_dron.procesar([_foto(tmp_path / "a.jpg")], tmp_path, **{campo: valor})

    def test_sin_fotos_y_demasiadas(self, tmp_path):
        with pytest.raises(ComposicionInvalida, match="No indicó"):
            fotos_dron.procesar([], tmp_path)
        with pytest.raises(ComposicionInvalida, match="máximo"):
            fotos_dron.procesar([tmp_path / "a.jpg"] * 501, tmp_path)

    def test_un_png_no_se_lee(self):
        assert "no es un JPG" in fotos_dron.motivo_si_no_se_lee("a.png")
        assert fotos_dron.motivo_si_no_se_lee("A.JPG") == ""


class TestVerificador:
    """El motor comprueba la salida con Pillow, que no escribió esos bytes (regla 1)."""

    def test_detecta_la_posicion_que_quedo(self, tmp_path):
        original = _foto(tmp_path / "a.jpg").read_bytes()
        assert motor._conserva_gps(original)
        assert not motor._conserva_gps(fotos_dron.quitar_gps(original))

    def test_un_zip_que_dice_sin_posicion_y_la_trae_se_rechaza(self, tmp_path):
        parcial = tmp_path / "s.zip"
        with zipfile.ZipFile(parcial, "w") as paquete:
            paquete.write(_foto(tmp_path / "a.jpg"), "a.jpg")
        veredicto = motor._verificar_zip(
            parcial, {"piezas": [{"nombre": "a.jpg", "sin_gps": True}]}
        )
        assert not veredicto.correcta and "todavía la trae" in veredicto.motivo

    def test_las_posiciones_se_cuentan(self):
        pieza = {"puntos": 3}
        cuerpo = json.dumps({"features": [{}, {}]}).encode()
        assert "debía traer 3" in motor._problema_en_posiciones("p.geojson", cuerpo, pieza)
        assert motor._problema_en_posiciones("p.geojson", cuerpo, {"puntos": 2}) == ""


class TestTarea:
    def test_registrada_en_el_motor_y_en_la_tarea(self):
        assert "fotos_dron" in motor.ESPECIFICACIONES and "fotos_dron" in tarea.TAREAS


@pytest.mark.django_db
class TestPantalla:
    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("documents:fotos_dron")).status_code == 302

    def test_se_abre(self, sesion):
        respuesta = sesion.get(reverse("documents:fotos_dron"))
        assert (
            respuesta.status_code == 200 and "Limpiar fotos de dron" in respuesta.content.decode()
        )

    def test_sin_fotos_avisa(self, sesion):
        respuesta = sesion.post(reverse("documents:fotos_dron"), {"archivos_texto": ""})
        assert "No indicó ninguna foto" in respuesta.content.decode()

    def test_un_png_se_rechaza_antes_de_encolar(self, sesion, tmp_path):
        png = tmp_path / "a.png"
        Image.new("RGB", (4, 4)).save(png)
        respuesta = sesion.post(reverse("documents:fotos_dron"), {"archivos_texto": str(png)})
        assert respuesta.status_code == 200 and "no es un JPG" in respuesta.content.decode()

    def test_una_opcion_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path):
        foto = _foto(tmp_path / "a.jpg")
        respuesta = sesion.post(
            reverse("documents:fotos_dron"), {"archivos_texto": str(foto), "gps": "todo"}
        )
        assert (
            respuesta.status_code == 200
            and "no es de las que se ofrecen" in respuesta.content.decode()
        )

    def test_de_extremo_a_extremo_el_zip_trae_las_fotos_sin_posicion_y_el_kmz(
        self, sesion, tmp_path
    ):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        a = _foto(tmp_path / "a.jpg")
        b = _foto(tmp_path / "b.jpg", lat=-33.5, lon=-70.7, fecha="2026:09:30 10:20:00")
        respuesta = sesion.post(
            reverse("documents:fotos_dron"),
            {
                "archivos_texto": f"{a}\n{b}",
                "gps": "quitar",
                "nombres": "vuelo",
                "posiciones": "kmz",
            },
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as paquete:
            assert sorted(paquete.namelist()) == [
                "posiciones.kmz",
                "vuelo_0001.jpg",
                "vuelo_0002.jpg",
            ]
            for nombre in ("vuelo_0001.jpg", "vuelo_0002.jpg"):
                assert not [k for k in _leer_exifread(paquete.read(nombre)) if k.startswith("GPS")]
        assert _sha(a) == hashlib.sha256(a.read_bytes()).hexdigest()
