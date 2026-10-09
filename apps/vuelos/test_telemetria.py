"""La traza de un video de dron (F14.18).

Los SRT de partida son **texto escrito a mano con las coordenadas conocidas**; lo que sale se lee
con un analizador de XML —y, con GDAL delante, con `ogrinfo`, que es el oráculo de verdad—, y se
comparan el número de puntos y cada coordenada con las que se escribieron en el SRT.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import motor, tarea
from apps.vuelos import telemetria

pytestmark = pytest.mark.django_db

#: (lat, lon, alt) de cada fotograma con posición del SRT nuevo de abajo.
PUNTOS = [
    (-33.4500000, -70.6600000, 569.3),
    (-33.4501000, -70.6601000, 570.0),
    (-33.4502000, -70.6602000, 571.5),
]


def _bloque(n: int, t: str, cuerpo: str, fecha: str = "2026-10-01 12:00:00.000") -> str:
    return f"{n}\n{t}\nSrtCnt : {n}, DiffTime : 500ms\n{fecha}\n{cuerpo}\n"


def _con_posicion(lat: str, lon: str, rel: str, absoluta: str) -> str:
    return f"[iso : 100] [latitude: {lat}] [longitude: {lon}] [rel_alt: {rel} abs_alt: {absoluta}]"


def _srt_nuevo(carpeta: Path, nombre: str = "DJI_0001.SRT") -> Path:
    t = ("00:00:00,000 --> 00:00:00,500", "00:00:00,500 --> 00:00:01,000",
         "00:00:01,000 --> 00:00:01,500", "00:00:01,500 --> 00:00:02,000",
         "00:00:02,000 --> 00:00:02,500")  # fmt: skip
    bloques = [
        _bloque(1, t[0], _con_posicion("-33.4500000", "-70.6600000", "50.0", "569.300")),
        _bloque(2, t[1], _con_posicion("-33.4501000", "-70.6601000", "51.0", "570.000"),
                "2026-10-01 12:00:00.500"),
        # Sin satélites: el dron escribe 0, 0.
        _bloque(3, t[2], _con_posicion("0.000000", "0.000000", "0.0", "0.0"),
                "2026-10-01 12:00:01.000"),
        # Ni siquiera trae la posición.
        _bloque(4, t[3], "[iso : 100] [shutter : 1/1000.0]", "2026-10-01 12:00:01.500"),
        _bloque(5, t[4], _con_posicion("-33.4502000", "-70.6602000", "52.0", "571.500"),
                "2026-10-01 12:00:02.000"),
    ]  # fmt: skip
    ruta = carpeta / nombre
    ruta.write_text("\n".join(bloques), encoding="utf-8")
    return ruta


def _srt_antiguo(carpeta: Path) -> Path:
    ruta = carpeta / "DJI_0002.SRT"
    primero = _bloque(1, "00:00:00,000 --> 00:00:00,033", "GPS(-70.66,-33.45,36) BAROMETER:50.5")
    segundo = _bloque(
        2, "00:00:00,033 --> 00:00:00,066", "GPS (-70.6601, -33.4501, 37) BAROMETER:51"
    )
    ruta.write_text(primero + "\n" + segundo, encoding="utf-8")
    return ruta


def _gpx(ruta: Path) -> list[tuple[float, float, float | None, str | None]]:
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    filas = []
    for p in ET.parse(ruta).getroot().iterfind(".//g:trkpt", ns):
        ele = p.find("g:ele", ns)
        hora = p.find("g:time", ns)
        filas.append(
            (
                float(p.get("lat")),
                float(p.get("lon")),
                float(ele.text) if ele is not None else None,
                hora.text if hora is not None else None,
            )
        )
    return filas


class TestLeer:
    def test_el_formato_nuevo_da_las_posiciones_que_estaban_escritas(self, tmp_path):
        lectura = telemetria.leer(_srt_nuevo(tmp_path))
        assert [(p.lat, p.lon, p.alt) for p in lectura.puntos] == PUNTOS

    def test_se_cuentan_los_fotogramas_sin_posicion(self, tmp_path):
        lectura = telemetria.leer(_srt_nuevo(tmp_path))
        assert (lectura.entradas, len(lectura.puntos), lectura.sin_posicion) == (5, 3, 2)

    def test_el_formato_antiguo_trae_la_longitud_primero(self, tmp_path):
        lectura = telemetria.leer(_srt_antiguo(tmp_path))
        assert [(p.lat, p.lon, p.alt) for p in lectura.puntos] == [
            (-33.45, -70.66, 36.0),
            (-33.4501, -70.6601, 37.0),
        ]

    def test_los_tiempos_son_los_del_codigo_de_tiempo(self, tmp_path):
        lectura = telemetria.leer(_srt_nuevo(tmp_path))
        assert [p.t_s for p in lectura.puntos] == [0.0, 0.5, 2.0]

    def test_lo_que_no_es_un_srt_se_rechaza(self, tmp_path):
        otro = tmp_path / "x.srt"
        otro.write_text("hola, esto no tiene tiempos")
        with pytest.raises(telemetria.ComposicionInvalida, match="no parece un SRT"):
            telemetria.leer(otro)

    def test_un_srt_sin_posiciones_se_dice(self, tmp_path):
        sin = tmp_path / "sin.srt"
        sin.write_text(_bloque(1, "00:00:00,000 --> 00:00:01,000", "[iso : 100]"))
        with pytest.raises(telemetria.ComposicionInvalida, match="no trae ninguna posición"):
            telemetria.leer(sin)


class TestGpx:
    def test_un_punto_por_posicion_con_sus_coordenadas_y_su_altura(self, tmp_path):
        destino = tmp_path / "traza.gpx"
        _, cuantos = telemetria.convertir(_srt_nuevo(tmp_path), destino, "gpx")
        filas = _gpx(destino)
        assert cuantos == len(filas) == 3
        for (lat, lon, ele, _), (lat_e, lon_e, alt_e) in zip(filas, PUNTOS, strict=True):
            assert (round(lat, 7), round(lon, 7), ele) == (lat_e, lon_e, alt_e)

    def test_sin_desfase_no_escribe_hora(self, tmp_path):
        destino = tmp_path / "traza.gpx"
        telemetria.convertir(_srt_nuevo(tmp_path), destino, "gpx")
        assert all(hora is None for *_, hora in _gpx(destino))

    def test_con_desfase_la_hora_se_pasa_a_utc(self, tmp_path):
        destino = tmp_path / "traza.gpx"
        # La cámara marca 12:00 y está a UTC−4: son las 16:00 UTC.
        telemetria.convertir(_srt_nuevo(tmp_path), destino, "gpx", desfase_h=-4)
        assert _gpx(destino)[0][3] == "2026-10-01T16:00:00.000Z"
        assert _gpx(destino)[1][3] == "2026-10-01T16:00:00.500Z"

    def test_uno_por_segundo_adelgaza_y_conserva_el_ultimo(self, tmp_path):
        destino = tmp_path / "traza.gpx"
        lectura, cuantos = telemetria.convertir(_srt_nuevo(tmp_path), destino, "gpx", cada_s=1)
        filas = _gpx(destino)
        assert cuantos == len(filas) == 2  # t=0 y t=2 (el de t=0,5 cae dentro del primer segundo)
        assert (round(filas[-1][0], 7), round(filas[-1][1], 7)) == PUNTOS[-1][:2]
        assert len(lectura.puntos) == 3

    def test_el_nombre_se_escapa(self, tmp_path):
        origen = _srt_nuevo(tmp_path, "A&B 1.SRT")
        destino = tmp_path / "traza.gpx"
        telemetria.convertir(origen, destino, "gpx")
        assert "A&amp;B 1" in destino.read_text(encoding="utf-8")


class TestKml:
    def test_la_linea_lleva_longitud_latitud_altura_en_ese_orden(self, tmp_path):
        destino = tmp_path / "traza.kml"
        _, cuantos = telemetria.convertir(_srt_nuevo(tmp_path), destino, "kml")
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        raiz = ET.parse(destino).getroot()
        linea = raiz.find(".//k:LineString/k:coordinates", ns).text.split()
        assert cuantos == len(linea) == 3
        lon, lat, alt = (float(v) for v in linea[0].split(","))
        assert (lat, lon, alt) == PUNTOS[0]
        nombres = [n.text for n in raiz.iterfind(".//k:Placemark/k:name", ns)]
        assert "Inicio" in nombres and "Final" in nombres


class TestRechazos:
    def test_formato_intervalo_y_desfase_fuera_de_lo_que_se_ofrece(self, tmp_path):
        origen = _srt_nuevo(tmp_path)
        with pytest.raises(telemetria.ComposicionInvalida):
            telemetria.convertir(origen, tmp_path / "x.shp", "shp")
        with pytest.raises(telemetria.ComposicionInvalida):
            telemetria.convertir(origen, tmp_path / "x.gpx", "gpx", cada_s=3)
        with pytest.raises(telemetria.ComposicionInvalida, match="−14 a \\+14"):
            telemetria.convertir(origen, tmp_path / "x.gpx", "gpx", desfase_h=20)

    def test_el_original_no_se_toca(self, tmp_path):
        import hashlib

        origen = _srt_nuevo(tmp_path)
        antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        telemetria.convertir(origen, tmp_path / "x.gpx", "gpx")
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes


def _ogrinfo() -> str | None:
    encontrado = shutil.which("ogrinfo")
    if encontrado:
        return encontrado
    candidato = Path(r"C:\Program Files\QGIS 4.0.2\bin\ogrinfo.exe")
    return str(candidato) if candidato.exists() else None


@pytest.mark.oraculo
@pytest.mark.skipif(_ogrinfo() is None, reason="GDAL no está en esta máquina")
@pytest.mark.parametrize(("formato", "capa"), [("gpx", "track_points"), ("kml", None)])
def test_ogrinfo_abre_la_traza_y_cuenta_los_mismos_puntos(tmp_path, formato, capa):
    """GDAL —que no escribió el archivo— cuenta los puntos: coinciden con las posiciones del SRT."""
    destino = tmp_path / f"traza.{formato}"
    _, cuantos = telemetria.convertir(_srt_nuevo(tmp_path), destino, formato)
    salida = subprocess.run(  # noqa: S603 - argumentos fijos y rutas de la prueba
        [_ogrinfo(), "-ro", "-al", "-geom=SUMMARY", str(destino)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # La línea de la traza lleva todos los puntos, en los dos formatos.
    assert f"LINESTRING : {cuantos} points" in salida
    if capa:
        trozo = salida.split(f"Layer name: {capa}")[1]
        assert f"Feature Count: {cuantos}" in trozo.split("Layer name:")[0]


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_convierte_y_cuenta(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "telemetria",
            {"entradas": [{"ruta": str(_srt_nuevo(tmp_path))}], "opciones": {"formato": "gpx"}},
            parcial,
        )
        assert "codigo" not in informe
        assert informe["detalles"] == {
            "puntos": 3,
            "entradas": 5,
            "sin_posicion": 2,
            "formato": "gpx",
        }

    def test_la_verificacion_cuenta_los_puntos_con_otro_lector(self, tmp_path):
        destino = tmp_path / "traza.gpx"
        telemetria.convertir(_srt_nuevo(tmp_path), destino, "gpx")
        assert motor.verificar(destino, {"detalles": {"puntos": 3}}).correcta
        veredicto = motor.verificar(destino, {"detalles": {"puntos": 9}})
        assert not veredicto.correcta and "3 puntos" in veredicto.motivo

    def test_un_xml_roto_no_se_da_por_bueno(self, tmp_path):
        roto = tmp_path / "traza.gpx"
        roto.write_text("<gpx><trk>")
        assert not motor.verificar(roto, {"detalles": {}}).correcta

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:telemetria")).status_code == 302

    def test_la_pantalla_dice_que_la_hora_no_se_inventa(self, sesion):
        cuerpo = sesion.get(reverse("documents:telemetria")).content.decode()
        assert "sin zona" in cuerpo

    def test_rechaza_lo_que_no_es_srt(self, sesion, tmp_path):
        otro = tmp_path / "datos.csv"
        otro.write_text("a,b")
        respuesta = sesion.post(reverse("documents:telemetria"), {"ruta": str(otro)})
        assert respuesta.status_code == 200 and "no es un .SRT" in respuesta.content.decode()

    def test_un_desfase_que_no_es_numero_avisa(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:telemetria"),
            {"ruta": str(_srt_nuevo(tmp_path)), "desfase": "cuatro"},
        )
        assert respuesta.status_code == 200 and "número de horas" in respuesta.content.decode()

    def test_hacer_la_traza_encola_y_el_gpx_tiene_los_puntos(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(
            reverse("documents:telemetria"),
            {"ruta": str(_srt_nuevo(tmp_path)), "formato": "gpx", "cada_s": "0"},
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert len(_gpx(Path(trabajo.output_path))) == 3
