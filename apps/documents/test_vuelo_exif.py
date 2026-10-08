"""Escribir la posición corregida en la foto (F18.5), con **otro lector** que el que la escribe.

El oráculo de la posición es `exifread` (otro código que lee los bytes del EXIF); el de los píxeles
es la comparación **byte por byte** de todo lo que va desde SOS, y la decodificación con Pillow.
"""

from __future__ import annotations

import io

import exifread
import pytest
from PIL import Image

from apps.documents import fotos_dron, vuelo_exif
from apps.documents.composicion import ComposicionInvalida

NOTA = bytes(range(200, 240)) * 3  # un MakerNote con forma de dato opaco

#: Posiciones para probar: hemisferio sur y oeste (los signos), y una al norte y al este.
SUR_OESTE = (-23.123456789, -69.987654321, 1123.319)
NORTE_ESTE = (45.5, 9.25, -12.5)


def _jpeg(*, gps_viejo=False, con_exif=True, xmp: bytes | None = None, nota=True) -> bytes:
    imagen = Image.effect_noise((160, 120), 60).convert("RGB")
    exif = Image.Exif()
    if con_exif:
        exif[0x010F] = "DJI"
        exif[0x0110] = "FC6310S"
        interno = exif.get_ifd(0x8769)
        interno[0x9003] = "2026:10:08 10:15:02"
        if nota:
            interno[0x927C] = NOTA
        if gps_viejo:
            gps = exif.get_ifd(0x8825)
            gps[1], gps[2] = "N", (10.0, 20.0, 30.0)
            gps[3], gps[4] = "E", (11.0, 22.0, 33.0)
    memoria = io.BytesIO()
    opciones = {"exif": exif} if con_exif else {}
    if xmp is not None:
        opciones["xmp"] = xmp
    imagen.save(memoria, "JPEG", quality=80, **opciones)
    return memoria.getvalue()


def _leer(datos: bytes) -> dict:
    return exifread.process_file(io.BytesIO(datos), details=False)


def _grados(etiquetas, nombre: str, ref: str) -> float:
    g, m, s = (float(v.num) / float(v.den) for v in etiquetas[nombre].values)
    valor = g + m / 60 + s / 3600
    return -valor if str(etiquetas[ref]) in ("S", "W") else valor


def _posicion(datos: bytes) -> tuple[float, float, float | None]:
    e = _leer(datos)
    lat = _grados(e, "GPS GPSLatitude", "GPS GPSLatitudeRef")
    lon = _grados(e, "GPS GPSLongitude", "GPS GPSLongitudeRef")
    alt = None
    if "GPS GPSAltitude" in e:
        v = e["GPS GPSAltitude"].values[0]
        alt = float(v.num) / float(v.den)
        if e["GPS GPSAltitudeRef"].values == [1]:
            alt = -alt
    return lat, lon, alt


def _desde_sos(datos: bytes) -> bytes:
    return fotos_dron._segmentos(datos)[1]


@pytest.mark.parametrize("posicion", [SUR_OESTE, NORTE_ESTE])
@pytest.mark.parametrize("gps_viejo", [False, True])
@pytest.mark.parametrize("con_exif", [True, False])
def test_la_posicion_escrita_la_lee_otro_lector(posicion, gps_viejo, con_exif):
    original = _jpeg(gps_viejo=gps_viejo and con_exif, con_exif=con_exif)
    nuevo = vuelo_exif.poner_posicion(original, *posicion)
    lat, lon, alt = _posicion(nuevo)
    assert lat == pytest.approx(posicion[0], abs=1e-9)  # 1e-9° ≈ 0,1 mm
    assert lon == pytest.approx(posicion[1], abs=1e-9)
    assert alt == pytest.approx(posicion[2], abs=5e-4)


def test_el_datum_declarado_es_wgs84():
    e = _leer(vuelo_exif.poner_posicion(_jpeg(), *SUR_OESTE))
    assert str(e["GPS GPSMapDatum"]) == "WGS-84"


def test_los_pixeles_pasan_byte_por_byte():
    original = _jpeg(gps_viejo=True)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    assert _desde_sos(nuevo) == _desde_sos(original)
    a, b = Image.open(io.BytesIO(original)), Image.open(io.BytesIO(nuevo))
    assert a.tobytes() == b.tobytes() and a.size == b.size


def test_lo_demas_del_exif_queda_igual_incluida_la_nota_del_fabricante():
    original = _jpeg(gps_viejo=True)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    antes, despues = (
        Image.open(io.BytesIO(original)).getexif(),
        Image.open(io.BytesIO(nuevo)).getexif(),
    )
    assert despues[0x010F] == antes[0x010F] == "DJI" and despues[0x0110] == antes[0x0110]
    interno_antes, interno_despues = antes.get_ifd(0x8769), despues.get_ifd(0x8769)
    assert interno_despues[0x9003] == interno_antes[0x9003]
    assert interno_despues[0x927C] == interno_antes[0x927C] == NOTA


def test_el_exif_viejo_no_se_toca_fuera_de_su_bloque_gps():
    """Ningún desplazamiento se mueve: lo que ya estaba queda en su byte (lo exige la nota)."""
    original = _jpeg(gps_viejo=True)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    viejo_exif = next(c for m, c in fotos_dron._segmentos(original)[0] if m == 0xE1)
    nuevo_exif = next(c for m, c in fotos_dron._segmentos(nuevo)[0] if m == 0xE1)
    assert len(nuevo_exif) > len(viejo_exif)
    iguales = sum(1 for a, b in zip(viejo_exif, nuevo_exif, strict=False) if a == b)
    # Lo único que cambia dentro de lo viejo es el bloque GPS (a cero) y su puntero.
    assert iguales >= len(viejo_exif) - 12 - 2 - 12 * 6 - 64
    assert NOTA in nuevo_exif


def test_sin_puntero_a_gps_el_exif_se_copia_y_la_nota_sigue_donde_estaba():
    original = _jpeg(gps_viejo=False)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    viejo_exif = next(c for m, c in fotos_dron._segmentos(original)[0] if m == 0xE1)
    nuevo_exif = next(c for m, c in fotos_dron._segmentos(nuevo)[0] if m == 0xE1)
    assert viejo_exif.find(NOTA) == nuevo_exif.find(NOTA) != -1
    assert _posicion(nuevo)[0] == pytest.approx(SUR_OESTE[0], abs=1e-9)


def test_la_posicion_vieja_no_queda_escondida():
    original = _jpeg(gps_viejo=True)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    assert _posicion(original)[0] == pytest.approx(10 + 20 / 60 + 30 / 3600)
    assert _posicion(nuevo)[0] != pytest.approx(_posicion(original)[0])
    # Y los racionales viejos (11, 22, 33) ya no están en el bloque.
    exif = next(c for m, c in fotos_dron._segmentos(nuevo)[0] if m == 0xE1)
    assert b"\x00\x00\x00\x21\x00\x00\x00\x01" not in exif  # 33/1 en big endian
    assert b"\x21\x00\x00\x00\x01\x00\x00\x00" not in exif  # 33/1 en little endian


def test_el_xmp_de_dji_se_actualiza_y_conserva_la_orientacion():
    xmp = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
        b'drone-dji:GpsLatitude="-23.0" drone-dji:GpsLongtitude="-69.0" '
        b'drone-dji:AbsoluteAltitude="+1000.100" drone-dji:RelativeAltitude="+80.0" '
        b'drone-dji:GimbalYawDegree="+12.3"/></rdf:RDF></x:xmpmeta>'
    )
    original = _jpeg(xmp=xmp)
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    carga = next(
        c
        for m, c in fotos_dron._segmentos(nuevo)[0]
        if m == 0xE1 and c.startswith(fotos_dron._FIRMA_XMP)
    )
    assert b'GpsLatitude="-23.12345679"' in carga
    assert b'GpsLongtitude="-69.98765432"' in carga
    assert b'AbsoluteAltitude="1123.319"' in carga
    assert b'GimbalYawDegree="+12.3"' in carga and b'RelativeAltitude="+80.0"' in carga
    assert _desde_sos(nuevo) == _desde_sos(original)


def test_una_foto_sin_altura_no_inventa_una():
    e = _leer(vuelo_exif.poner_posicion(_jpeg(), -10.0, -20.0, None))
    assert "GPS GPSAltitude" not in e and "GPS GPSLatitude" in e


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (-95, 10)])
def test_una_posicion_imposible_se_rechaza(lat, lon):
    with pytest.raises(ComposicionInvalida):
        vuelo_exif.poner_posicion(_jpeg(), lat, lon, 0)


def test_lo_que_no_es_jpeg_o_viene_cortado_se_rechaza():
    with pytest.raises(ComposicionInvalida):
        vuelo_exif.poner_posicion(b"no soy una foto", 0, 0, 0)
    with pytest.raises(ComposicionInvalida):
        vuelo_exif.poner_posicion(_jpeg()[:60], 0, 0, 0)


def test_los_segundos_nunca_dan_sesenta():
    # 0,9999999999° → 59' 59,99999964": el redondeo a 6 decimales no puede dejar 60".
    e = _leer(vuelo_exif.poner_posicion(_jpeg(), 10.9999999999, 20.0, 0))
    g, m, s = (float(v.num) / float(v.den) for v in e["GPS GPSLatitude"].values)
    assert s < 60 and m < 60 and g + m / 60 + s / 3600 == pytest.approx(10.9999999999, abs=1e-8)


def _con_endianidad(datos: bytes, como: str) -> bytes:
    """El mismo JPEG con su EXIF reescrito en `II` (DJI) o `MM`, con Pillow."""
    imagen = Image.open(io.BytesIO(datos))
    exif = imagen.getexif()
    exif.endian = "<" if como == "II" else ">"
    memoria = io.BytesIO()
    imagen.save(memoria, "JPEG", exif=exif)
    return memoria.getvalue()


@pytest.mark.parametrize("como", ["II", "MM"])
@pytest.mark.parametrize("gps_viejo", [False, True])
def test_las_dos_endianidades_del_exif_se_escriben_y_se_leen(como, gps_viejo):
    original = _con_endianidad(_jpeg(gps_viejo=gps_viejo), como)
    cuerpo = next(c for m, c in fotos_dron._segmentos(original)[0] if m == 0xE1)
    assert cuerpo[6:8] == como.encode()
    nuevo = vuelo_exif.poner_posicion(original, *SUR_OESTE)
    assert _posicion(nuevo)[0] == pytest.approx(SUR_OESTE[0], abs=1e-9)
    assert _posicion(nuevo)[1] == pytest.approx(SUR_OESTE[1], abs=1e-9)
    assert _desde_sos(nuevo) == _desde_sos(original)


def test_el_datum_se_escribe_tal_como_lo_dice_quien_llama():
    e = _leer(vuelo_exif.poner_posicion(_jpeg(), -10.0, -20.0, 1.0, "SIRGAS-Chile 2002"))
    assert str(e["GPS GPSMapDatum"]) == "SIRGAS-Chile 2002"


def test_un_exif_cortado_dice_cual_es_el_problema():
    cortado = bytes([0xFF, 0xD8, 0xFF, 0xE1, 0x00, 0x0A]) + b"Exif\x00\x00II" + b"\xff\xda\x00\x02"
    with pytest.raises(ComposicionInvalida, match="cortado"):
        vuelo_exif.poner_posicion(cortado, -10.0, -20.0, None)


def test_un_exif_que_no_cabe_en_un_segmento_se_rechaza_con_motivo():
    gordo = Image.Exif()
    gordo[0x010F] = "DJI"
    gordo.get_ifd(0x8769)[0x927C] = bytes(65400)
    memoria = io.BytesIO()
    Image.new("RGB", (16, 16)).save(memoria, "JPEG")
    imagen = Image.open(io.BytesIO(memoria.getvalue()))
    salida = io.BytesIO()
    imagen.save(salida, "JPEG", exif=gordo)
    with pytest.raises(ComposicionInvalida, match="no cabe"):
        vuelo_exif.poner_posicion(salida.getvalue(), -10.0, -20.0, 1.0)


def test_un_segundo_bloque_exif_tampoco_guarda_la_posicion_vieja():
    original = _jpeg(gps_viejo=True)
    segmentos, resto = fotos_dron._segmentos(original)
    exif = next(c for m, c in segmentos if m == 0xE1)
    doble = bytearray(b"\xff\xd8")
    for marca, carga in segmentos:
        doble += bytes([0xFF, marca]) + (len(carga) + 2).to_bytes(2, "big") + carga
    doble += b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif  # un segundo EXIF
    doble = bytes(doble) + resto
    nuevo = vuelo_exif.poner_posicion(doble, *SUR_OESTE)
    bloques = [c for m, c in fotos_dron._segmentos(nuevo)[0] if m == 0xE1]
    assert len(bloques) == 2
    solo = b"\xff\xd8\xff\xe1" + (len(bloques[1]) + 2).to_bytes(2, "big") + bloques[1]
    assert "GPS GPSLatitude" not in _leer(solo)
