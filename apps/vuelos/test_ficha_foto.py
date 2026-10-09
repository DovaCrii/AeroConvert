"""La ficha de una foto de dron (F18.8 a F18.10), leída con **otros lectores**.

Las fotos son **sintéticas**: un JPEG mínimo que la prueba crea, con un EXIF y un XMP de DJI
escritos a mano con valores conocidos (nunca datos reales en el repositorio). Los oráculos son dos
lectores que no son el de `ficha_foto.py`:

- **`exifread`** lee el EXIF (modelo, focal, apertura, exposición, ISO, dimensiones, GPS);
- el **XMP** se lee con un analizador de XML (`xml.etree`), no con la expresión regular que usa el
  código.
"""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET  # nosec B405 - solo se lee el XMP que escribe la propia prueba

import exifread
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from apps.documents.composicion import ComposicionInvalida
from apps.vuelos import ficha_foto

#: Lo que escribe un Matrice 3E en el XMP de una foto con RTK fijo: valores **conocidos**.
XMP_BASE = {
    "Version": "1.6",
    "ImageSource": "WideCamera",
    "GpsStatus": "RTK",
    "AltitudeType": "RtkAlt",
    "GpsLatitude": "-23.338633813",
    "GpsLongitude": "-69.832545843",
    "AbsoluteAltitude": "+1158.513",
    "RelativeAltitude": "+79.724",
    "GimbalRollDegree": "+0.00",
    "GimbalYawDegree": "-11.30",
    "GimbalPitchDegree": "-80.00",
    "FlightRollDegree": "-11.40",
    "FlightYawDegree": "-9.80",
    "FlightPitchDegree": "-16.00",
    "FlightXSpeed": "11.2",
    "FlightYSpeed": "-1.9",
    "FlightZSpeed": "-0.1",
    "RtkFlag": "50",
    "RtkStdLon": "0.01621",
    "RtkStdLat": "0.01573",
    "RtkStdHgt": "0.03532",
    "RtkDiffAge": "1.00000",
    "UTCAtExposure": "2025-12-29T15:39:10.934085",
}


def xmp_de_dji(**cambios) -> bytes:
    """Un XMP con la forma del de DJI: atributos `drone-dji:…` de un solo `rdf:Description`."""
    valores = {**XMP_BASE, **cambios}
    atributos = "\n".join(f'   drone-dji:{k}="{v}"' for k, v in valores.items() if v is not None)
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="DJI Meta Data"\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"\n'
        '   xmp:CreateDate="2025-12-29T12:38:52-03:00"\n'
        f"{atributos}>\n"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>"
    ).encode()


def _dms(grados: float) -> tuple[float, float, float]:
    grados = abs(grados)
    g = int(grados)
    m = int((grados - g) * 60)
    s = round(((grados - g) * 60 - m) * 60, 4)
    return float(g), float(m), s


def jpeg_de_dji(*, xmp: bytes | None = None, con_exif_gps: bool = True, **cambios) -> bytes:
    """Un JPEG de 160 × 120 con el EXIF de una cámara DJI y, si se pide, su XMP.

    `xmp=None` pone el XMP base con `cambios`; `xmp=b""` no pone ninguno.
    """
    exif = Image.Exif()
    exif[0x010F] = "DJI"
    exif[0x0110] = "M3E"
    exif[0x0132] = "2025:12:29 12:38:52"
    interno = exif.get_ifd(0x8769)
    interno[0x9003] = "2025:12:29 12:38:52"
    interno[0x829A] = IFDRational(1, 2000)
    interno[0x829D] = IFDRational(9, 2)
    interno[0x8827] = 100
    interno[0x920A] = IFDRational(1229, 100)
    interno[0xA002] = 5280
    interno[0xA003] = 3956
    interno[0xA405] = 24
    if con_exif_gps:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = "S", _dms(23.338633813)
        gps[3], gps[4] = "W", _dms(69.832545843)
        gps[5], gps[6] = 0, IFDRational(1158513, 1000)
        gps[18] = "WGS-84"
    memoria = io.BytesIO()
    cuerpo = xmp_de_dji(**cambios) if xmp is None else xmp
    opciones = {"exif": exif}
    if cuerpo:
        opciones["xmp"] = cuerpo
    Image.effect_noise((160, 120), 60).convert("RGB").save(memoria, "JPEG", quality=80, **opciones)
    return memoria.getvalue()


def _xmp_con_xml(datos: bytes) -> dict[str, str]:
    """El XMP de la foto leído con un analizador de XML: el oráculo del XMP."""
    inicio = datos.index(b"<x:xmpmeta")
    fin = datos.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")
    raiz = ET.fromstring(datos[inicio:fin])  # noqa: S314 - lo escribió la propia prueba
    descripcion = next(e for e in raiz.iter() if e.tag.endswith("}Description"))
    return {k.split("}")[1]: v for k, v in descripcion.attrib.items() if "dji.com" in k}


def _racional(etiqueta) -> float:
    v = etiqueta.values[0]
    return float(v.num) / float(v.den)


class TestElXmpYElExifSeLeenComoLosLeeOtro:
    def test_la_ficha_coincide_con_exifread_y_con_el_analizador_de_xml(self):
        datos = jpeg_de_dji()
        ficha = ficha_foto.leer_ficha_de_bytes("DJI_0001_V.JPG", datos)
        e = exifread.process_file(io.BytesIO(datos), details=False)
        x = _xmp_con_xml(datos)

        # La cámara, con exifread.
        assert ficha.marca == str(e["Image Make"]) == "DJI"
        assert ficha.modelo == str(e["Image Model"]) == "M3E"
        assert ficha.focal_mm == pytest.approx(_racional(e["EXIF FocalLength"]))
        assert ficha.focal_35mm_mm == pytest.approx(int(str(e["EXIF FocalLengthIn35mmFilm"])))
        assert ficha.apertura_f == pytest.approx(_racional(e["EXIF FNumber"]))
        assert ficha.exposicion_s == pytest.approx(_racional(e["EXIF ExposureTime"]))
        assert ficha.iso == int(str(e["EXIF ISOSpeedRatings"])) == 100
        assert (ficha.ancho_px, ficha.alto_px) == (
            int(str(e["EXIF ExifImageWidth"])),
            int(str(e["EXIF ExifImageLength"])),
        )
        assert ficha.datum == str(e["GPS GPSMapDatum"]) == "WGS-84"

        # El XMP, con el analizador de XML.
        assert ficha.rtk_bandera == int(x["RtkFlag"])
        assert ficha.gps_estado == x["GpsStatus"] and ficha.tipo_de_altura == x["AltitudeType"]
        assert ficha.lat == pytest.approx(float(x["GpsLatitude"]), abs=1e-12)
        assert ficha.lon == pytest.approx(float(x["GpsLongitude"]), abs=1e-12)
        assert ficha.alt_m == pytest.approx(float(x["AbsoluteAltitude"]), abs=1e-9)
        assert ficha.posicion_de == "XMP"
        assert ficha.rtk_desv_lat_m == pytest.approx(float(x["RtkStdLat"]))
        assert ficha.rtk_desv_lon_m == pytest.approx(float(x["RtkStdLon"]))
        assert ficha.rtk_desv_alt_m == pytest.approx(float(x["RtkStdHgt"]))
        assert ficha.rtk_edad_dif_s == pytest.approx(float(x["RtkDiffAge"]))
        assert ficha.fecha == "2025-12-29T12:38:52-03:00"

    def test_la_orientacion_del_gimbal_y_del_dron_y_las_velocidades(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji())
        x = _xmp_con_xml(jpeg_de_dji())
        # Con las unidades que dice cada nombre: grados y metros por segundo.
        assert ficha.gimbal_guinada_deg == float(x["GimbalYawDegree"]) == -11.3
        assert ficha.gimbal_cabeceo_deg == float(x["GimbalPitchDegree"]) == -80.0
        assert ficha.gimbal_alabeo_deg == float(x["GimbalRollDegree"]) == 0.0
        assert ficha.dron_guinada_deg == float(x["FlightYawDegree"])
        assert ficha.dron_cabeceo_deg == float(x["FlightPitchDegree"])
        assert ficha.dron_alabeo_deg == float(x["FlightRollDegree"])
        assert (ficha.velocidad_x_ms, ficha.velocidad_y_ms, ficha.velocidad_z_ms) == (
            11.2,
            -1.9,
            -0.1,
        )
        assert ficha.altura_relativa_m == 79.724
        assert ficha.con_orientacion

    def test_la_longitud_mal_escrita_por_dji_tambien_se_lee(self):
        """DJI escribe `GpsLongtitude` en algunos archivos: se acepta la forma torcida."""
        xmp = xmp_de_dji(GpsLongitude=None).replace(
            b"drone-dji:GpsLatitude", b'drone-dji:GpsLongtitude="-69.5"\n   drone-dji:GpsLatitude'
        )
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(xmp=xmp))
        assert ficha.lon == -69.5

    def test_el_xmp_en_forma_de_elementos_tambien_se_lee(self):
        """Algunos modelos escriben `<drone-dji:Tag>valor</drone-dji:Tag>` y no atributos."""
        xmp = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/'
            b'02/22-rdf-syntax-ns#"><rdf:Description xmlns:drone-dji="http://www.dji.com/'
            b'drone-dji/1.0/"><drone-dji:RtkFlag>34</drone-dji:RtkFlag>'
            b"<drone-dji:GimbalPitchDegree>-90.00</drone-dji:GimbalPitchDegree>"
            b"</rdf:Description></rdf:RDF></x:xmpmeta>"
        )
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(xmp=xmp))
        assert ficha.rtk_bandera == 34 and ficha.gimbal_cabeceo_deg == -90.0


class TestLaCalidadSaleDeLaBanderaYNoSeCompleta:
    @pytest.mark.parametrize(
        ("bandera", "calidad", "codigo"),
        [
            ("50", "fija", 1),
            ("34", "flotante", 2),
            ("16", "simple", 5),
            ("0", "sin solución", None),
            ("64", "no reconocida (código 64)", None),
        ],
    )
    def test_cada_codigo_dice_su_calidad(self, bandera, calidad, codigo):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(RtkFlag=bandera))
        assert ficha.calidad == calidad
        assert ficha_foto.CODIGO_DE_CALIDAD.get(ficha.rtk_bandera) == codigo

    def test_sin_bandera_se_dice_no_informada_y_no_se_supone(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(RtkFlag=None))
        assert ficha.rtk_bandera is None and ficha.calidad == "no informada"

    def test_el_estado_del_gps_no_es_la_calidad(self):
        """`GpsStatus` dice «RTK» aunque la bandera sea 16 (posición simple): se midió en un
        vuelo real."""
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(RtkFlag="16"))
        assert ficha.gps_estado == "RTK" and ficha.calidad == "simple"

    def test_una_bandera_que_no_es_un_numero_no_se_inventa(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(RtkFlag="dos"))
        assert ficha.rtk_bandera is None and ficha.calidad == "no informada"


class TestLoQueFaltaQuedaSinDato:
    def test_sin_xmp_la_posicion_sale_del_exif_y_la_calidad_no_se_informa(self):
        datos = jpeg_de_dji(xmp=b"")
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", datos)
        e = exifread.process_file(io.BytesIO(datos), details=False)
        g, m, s = (float(v.num) / float(v.den) for v in e["GPS GPSLatitude"].values)
        assert ficha.posicion_de == "EXIF"
        assert ficha.lat == pytest.approx(-(g + m / 60 + s / 3600), abs=1e-9)
        assert ficha.rtk_bandera is None and ficha.calidad == "no informada"
        assert not ficha.con_orientacion and ficha.gimbal_guinada_deg is None
        assert ficha.alt_m == pytest.approx(1158.513)

    def test_sin_exif_ni_xmp_no_hay_posicion_y_no_revienta(self):
        memoria = io.BytesIO()
        Image.new("RGB", (8, 8)).save(memoria, "JPEG")
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", memoria.getvalue())
        assert not ficha.con_posicion and ficha.modelo is None and ficha.calidad == "no informada"

    def test_una_posicion_imposible_se_descarta(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(GpsLatitude="123.4"))
        assert ficha.posicion_de == "EXIF"  # la del XMP no vale; cae a la del EXIF

    def test_un_archivo_que_no_es_jpeg_se_rechaza_con_su_nombre(self, tmp_path):
        ruta = tmp_path / "x.jpg"
        ruta.write_bytes(b"esto no es un jpeg")
        with pytest.raises(ComposicionInvalida):
            ficha_foto.leer_ficha(ruta)

    def test_un_exif_dañado_no_tumba_la_ficha(self):
        datos = bytearray(jpeg_de_dji())
        i = datos.index(b"Exif\x00\x00") + 6
        datos[i : i + 8] = b"XXXXXXXX"  # sin cabecera TIFF
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", bytes(datos))
        assert ficha.modelo is None and ficha.rtk_bandera == 50  # el XMP sigue valiendo


class TestSoloLeeLaCabeceraYNoTocaElOriginal:
    def test_lee_de_disco_y_el_original_queda_intacto(self, tmp_path):
        ruta = tmp_path / "DJI_0001_V.JPG"
        ruta.write_bytes(jpeg_de_dji())
        antes = (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns)
        ficha = ficha_foto.leer_ficha(ruta)
        assert ficha.nombre == "DJI_0001_V.JPG" and ficha.rtk_bandera == 50
        assert (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns) == antes

    def test_si_la_cabecera_no_cabe_en_lo_primero_que_se_lee_se_amplia(self, tmp_path, monkeypatch):
        """Un EXIF grande (un MakerNote de 40 kB) no se pierde por leer poco."""
        monkeypatch.setattr(ficha_foto, "CABECERA_INICIAL", 512)
        ruta = tmp_path / "a.jpg"
        ruta.write_bytes(jpeg_de_dji())
        assert ficha_foto.leer_ficha(ruta).rtk_bandera == 50

    def test_no_lee_el_archivo_entero(self, tmp_path, monkeypatch):
        """Se pide una cabecera de ~192 kB, no los megabytes de la foto."""
        pedidos: list[int] = []
        original = ficha_foto._segmentos

        def espiar(datos):
            pedidos.append(len(datos))
            return original(datos)

        monkeypatch.setattr(ficha_foto, "_segmentos", espiar)
        ruta = tmp_path / "grande.jpg"
        relleno = Image.effect_noise((2400, 1800), 90).convert("RGB")
        relleno.save(ruta, "JPEG", quality=95, exif=Image.Exif(), xmp=xmp_de_dji())
        assert ruta.stat().st_size > 2 * ficha_foto.CABECERA_INICIAL
        ficha_foto.leer_ficha(ruta)
        assert pedidos == [ficha_foto.CABECERA_INICIAL]
