"""Trabajar un video de dron (F14.17).

En el CI no hay FFmpeg: el pegamento se prueba con un `ffmpeg` y un `ffprobe` **de mentira** que se
comportan como los de verdad en lo que importa (escriben un JPG por fotograma; dejan una ficha que
ffprobe devuelve en JSON). Lo que se comprueba de la salida lo miran otros lectores: `exifread` la
posición del fotograma, Pillow la imagen, y una **fórmula de haversine escrita aquí** la distancia
entre fotogramas (el código usa `pyproj.Geod`). Con FFmpeg de verdad, la prueba `oraculo` de abajo.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import sys
import zipfile
from pathlib import Path

import exifread
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import motor, telemetria, video
from apps.documents.composicion import ComposicionInvalida

# Un vuelo hacia el norte: 1e-4° de latitud por segundo (≈ 11,1 m/s), treinta segundos.
LAT0, LON0 = -33.40, -70.60
PASO_LAT = 1e-4
DURACION_S = 30


def _srt(ruta: Path, segundos: int = DURACION_S) -> Path:
    bloques = []
    for i in range(segundos + 1):
        t0, t1 = i, i + 0.5
        lat = LAT0 + PASO_LAT * i
        bloques.append(
            f"{i + 1}\n00:00:{int(t0):02d},000 --> 00:00:{int(t1):02d},500\n"
            f"[latitude: {lat:.7f}] [longitude: {LON0:.7f}] [rel_alt: 50.0 abs_alt: 650.0]\n"
        )
    ruta.write_text("\n".join(bloques), encoding="utf-8")
    return ruta


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = f2 - f1, math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


FFMPEG_FALSO = r"""
import json, sys
from pathlib import Path
args = sys.argv[1:]
salida = Path(args[-1])
entrada = Path(args[args.index("-i") + 1])
ficha = json.loads(Path(str(entrada) + ".ficha.json").read_text())
if "-frames:v" in args:
    from PIL import Image
    Image.new("RGB", (64, 48), (10, 120, 200)).save(salida, "JPEG")
    sys.exit(0)
if "-t" in args:
    ficha["duracion"] = float(args[args.index("-t") + 1])
if "-an" in args:
    ficha["audio"] = False
if "libx264" in args:
    ficha["codec"] = "h264"
salida.write_bytes(b"\x00\x00\x00\x18ftypmp42 video de mentira")
Path(str(salida) + ".ficha.json").write_text(json.dumps(ficha))
"""

FFPROBE_FALSO = r"""
import json, sys
from pathlib import Path
ficha = json.loads(Path(sys.argv[-1] + ".ficha.json").read_text())
flujos = [{"codec_type": "video", "codec_name": ficha["codec"], "width": 1920, "height": 1080}]
if ficha["audio"]:
    flujos.append({"codec_type": "audio", "codec_name": "aac"})
print(json.dumps({"streams": flujos, "format": {"duration": str(ficha["duracion"])}}))
"""


def _lanzador(carpeta: Path, nombre: str, codigo: str) -> str:
    guion = carpeta / f"{nombre}.py"
    guion.write_text(codigo, encoding="utf-8")
    if os.name == "nt":
        lanzador = carpeta / f"{nombre}.cmd"
        lanzador.write_text(f'@"{sys.executable}" "{guion}" %*\n', encoding="utf-8")
    else:
        lanzador = carpeta / nombre
        lanzador.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{guion}" "$@"\n', encoding="utf-8"
        )
        lanzador.chmod(0o755)
    return str(lanzador)


@pytest.fixture
def herramientas(tmp_path):
    carpeta = tmp_path / "bin"
    carpeta.mkdir()
    return (
        _lanzador(carpeta, "ffmpeg", FFMPEG_FALSO),
        _lanzador(carpeta, "ffprobe", FFPROBE_FALSO),
    )


def _video(ruta: Path, *, duracion=DURACION_S, codec="hevc", audio=True) -> Path:
    ruta.write_bytes(b"\x00\x00\x00\x18ftypqt  un video de mentira")
    Path(str(ruta) + ".ficha.json").write_text(
        json.dumps({"duracion": duracion, "codec": codec, "audio": audio})
    )
    return ruta


class TestLosInstantes:
    def test_por_tiempo(self):
        assert video.instantes_por_tiempo(10, 2) == [0, 2, 4, 6, 8]
        with pytest.raises(ComposicionInvalida):
            video.instantes_por_tiempo(10, 0)

    def test_por_distancia_cae_cada_n_metros_medido_con_otra_formula(self, tmp_path):
        puntos = telemetria.leer(_srt(tmp_path / "v.SRT")).puntos
        instantes = video.instantes_por_distancia(puntos, 20)
        assert instantes[0] == 0 and len(instantes) > 10
        posiciones = [video.posicion_en(puntos, t) for t in instantes]
        for n, (anterior, actual) in enumerate(zip(posiciones, posiciones[1:], strict=False), 1):
            separacion = _haversine_m(anterior[0], anterior[1], actual[0], actual[1])
            assert separacion == pytest.approx(20, abs=0.15), n  # haversine vs elipsoide

    def test_la_posicion_se_interpola_en_el_tiempo(self, tmp_path):
        puntos = telemetria.leer(_srt(tmp_path / "v.SRT")).puntos
        lat, lon, alt = video.posicion_en(puntos, 2.5)
        assert lat == pytest.approx(LAT0 + 2.5 * PASO_LAT) and lon == pytest.approx(LON0)
        assert video.posicion_en(puntos, 500) is None


class TestLasOrdenes:
    def test_recortar_recodifica_y_no_copia(self, tmp_path):
        argv = video.plan_operacion("ffmpeg", "recortar", tmp_path / "a.mp4", tmp_path / "b.mp4",
                                    inicio_s=2, fin_s=7)  # fmt: skip
        assert argv[argv.index("-ss") + 1] == "2.000" and argv[argv.index("-t") + 1] == "5.000"
        assert "-to" not in argv and argv.index("-ss") < argv.index("-i") < argv.index("-t")
        assert "libx264" in argv and "copy" not in argv

    def test_sin_audio_copia_la_imagen_y_quita_el_sonido(self, tmp_path):
        argv = video.plan_operacion("ffmpeg", "sin_audio", tmp_path / "a.mp4", tmp_path / "b.mp4")
        assert "-an" in argv and argv[argv.index("-c:v") + 1] == "copy"

    @pytest.mark.parametrize(
        "rango", [{}, {"inicio_s": 5, "fin_s": 2}, {"inicio_s": -1, "fin_s": 2}]
    )
    def test_un_recorte_imposible_se_rechaza(self, tmp_path, rango):
        with pytest.raises(ComposicionInvalida):
            video.plan_operacion("ffmpeg", "recortar", tmp_path / "a", tmp_path / "b", **rango)

    def test_una_operacion_que_no_existe_se_rechaza(self, tmp_path):
        with pytest.raises(ComposicionInvalida):
            video.plan_operacion("ffmpeg", "borrar_disco", tmp_path / "a", tmp_path / "b")


class TestLosFotogramas:
    def test_cada_fotograma_lleva_su_posicion_y_no_la_altura(self, tmp_path, herramientas):
        ffmpeg, _ = herramientas
        origen = _video(tmp_path / "v.mp4")
        puntos = telemetria.leer(_srt(tmp_path / "v.SRT")).puntos
        instantes = [0.0, 5.0, 10.5]
        archivos, tabla = video.extraer_fotogramas(
            ffmpeg, origen, tmp_path / "f", instantes, puntos=puntos
        )
        assert len(archivos) == 3 and len(tabla.splitlines()) == 4
        for archivo, t in zip(archivos, instantes, strict=True):
            e = exifread.process_file(io.BytesIO(archivo.read_bytes()), details=False)
            g, m, s = (float(v.num) / float(v.den) for v in e["GPS GPSLatitude"].values)
            assert -(g + m / 60 + s / 3600) == pytest.approx(LAT0 + PASO_LAT * t, abs=1e-8)
            assert "GPS GPSAltitude" not in e, "la altura del SRT no declara su referencia"

    def test_mas_del_tope_se_rechaza_antes_de_empezar(self, tmp_path, herramientas, monkeypatch):
        monkeypatch.setattr(video, "MAXIMO_FOTOGRAMAS", 2)
        with pytest.raises(ComposicionInvalida, match="tope"):
            video.extraer_fotogramas(herramientas[0], tmp_path / "v.mp4", tmp_path / "f", [0, 1, 2])

    def test_ffprobe_lee_la_ficha(self, tmp_path, herramientas):
        ficha = video.probar(herramientas[1], _video(tmp_path / "v.mp4", duracion=12.5))
        assert ficha.duracion_s == 12.5 and ficha.con_audio and ficha.codec == "hevc"


@pytest.fixture
def entrado(client, db, settings, tmp_path, herramientas, monkeypatch):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    ffmpeg, ffprobe = herramientas
    monkeypatch.setattr(
        video, "sondar", lambda **k: video.Disponible(ffmpeg=ffmpeg, ffprobe=ffprobe)
    )
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def _huellas(carpeta: Path):
    return {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in carpeta.iterdir()
        if p.is_file()
    }


class TestLaPantalla:
    def test_sin_sesion_redirige(self, client, db):
        assert client.get(reverse("documents:video")).status_code == 302

    def test_sin_ffmpeg_dice_el_motivo(self, client, db, monkeypatch):
        client.force_login(get_user_model().objects.create_user("b", password="x" * 20))  # nosec B106
        monkeypatch.setattr(video, "sondar", lambda **k: video.Disponible(motivo="No hay FFmpeg."))
        assert "No hay FFmpeg." in client.get(reverse("documents:video")).content.decode()

    def test_lo_que_no_es_video_se_rechaza(self, entrado, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        cuerpo = entrado.post(reverse("documents:video"), {"ruta": str(tmp_path / "a.txt")})
        assert "no es un video" in cuerpo.content.decode()

    def test_cada_metros_sin_srt_se_dice_antes(self, entrado, tmp_path):
        from apps.jobs.models import ConversionJob

        origen = _video(tmp_path / "solo.mp4")
        cuerpo = entrado.post(
            reverse("documents:video"),
            {"ruta": str(origen), "operacion": "fotogramas", "criterio": "metros", "cada_m": "20"},
        ).content.decode()
        assert "hace falta el .SRT" in cuerpo and not ConversionJob.objects.exists()

    def test_de_extremo_a_extremo_fotogramas_cada_20_metros(self, entrado, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        carpeta = tmp_path / "vuelo"
        carpeta.mkdir()
        origen = _video(carpeta / "DJI_0001.MP4")
        _srt(carpeta / "DJI_0001.SRT")
        antes = _huellas(carpeta)
        entrado.post(
            reverse("documents:video"),
            {"ruta": str(origen), "operacion": "fotogramas", "criterio": "metros", "cada_m": "20"},
        )
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.get()
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as z:
            jpgs = [n for n in z.namelist() if n.endswith(".jpg")]
            assert len(jpgs) == trabajo.verification["fotogramas"] > 10
            assert "fotogramas.csv" in z.namelist()
        assert trabajo.verification["con_posicion"] == len(jpgs)
        despues = _huellas(carpeta)
        assert {k: despues[k] for k in antes} == antes, "el video y su SRT, intactos"

    def test_de_extremo_a_extremo_quitar_el_audio(self, entrado, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        origen = _video(tmp_path / "con_audio.mp4", codec="h264")
        entrado.post(reverse("documents:video"), {"ruta": str(origen), "operacion": "sin_audio"})
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.get()
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.verification["con_audio"] is False
        assert trabajo.verification["verificado_con"] == "ffprobe"

    def test_un_recorte_mas_largo_que_el_video_falla_con_su_motivo(self, entrado, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        origen = _video(tmp_path / "corto.mp4", duracion=10)
        entrado.post(
            reverse("documents:video"),
            {"ruta": str(origen), "operacion": "recortar", "inicio_s": "2", "fin_s": "40"},
        )
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.get()
        assert trabajo.status == "error" and "dura 10.0 s" in trabajo.reason_detail


class TestLosCaminosDeFallo:
    """Regla 5 en los fallos: el video y su SRT intactos, y sin restos junto a la salida."""

    def _sin_restos(self, carpeta: Path):
        return [
            p.name for p in carpeta.iterdir() if ".parcial" in p.name or p.name.endswith(".piezas")
        ]

    def test_un_recorte_imposible(self, entrado, tmp_path):
        from apps.jobs import despachador

        carpeta = tmp_path / "v"
        carpeta.mkdir()
        origen = _video(carpeta / "corto.mp4", duracion=10)
        antes = _huellas(carpeta)
        entrado.post(
            reverse("documents:video"),
            {"ruta": str(origen), "operacion": "recortar", "inicio_s": "2", "fin_s": "40"},
        )
        despachador.procesar_una_vez()
        assert _huellas(carpeta) == antes and self._sin_restos(carpeta) == []

    def test_ffmpeg_que_falla_a_mitad_de_los_fotogramas(self, entrado, tmp_path, monkeypatch):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        carpeta = tmp_path / "v"
        carpeta.mkdir()
        origen = _video(carpeta / "DJI_0002.MP4")
        _srt(carpeta / "DJI_0002.SRT")
        roto = _lanzador(tmp_path / "bin", "ffmpeg_roto", "import sys; sys.exit(1)")
        ffprobe = video.sondar().ffprobe
        monkeypatch.setattr(
            video, "sondar", lambda **k: video.Disponible(ffmpeg=roto, ffprobe=ffprobe)
        )
        antes = _huellas(carpeta)
        entrado.post(
            reverse("documents:video"),
            {"ruta": str(origen), "operacion": "fotogramas", "criterio": "segundos", "cada_s": "5"},
        )
        despachador.procesar_una_vez()
        assert ConversionJob.objects.get().status == "error"
        assert _huellas(carpeta) == antes and self._sin_restos(carpeta) == []

    def test_el_zip_con_un_fotograma_sin_la_posicion_prometida_se_rechaza(self, tmp_path):
        from PIL import Image

        parcial = tmp_path / "f.zip"
        memoria = io.BytesIO()
        Image.new("RGB", (8, 8)).save(memoria, "JPEG")
        with zipfile.ZipFile(parcial, "w") as z:
            z.writestr("fotograma_00001.jpg", memoria.getvalue())
        veredicto = motor._verificar_zip(
            parcial, {"piezas": [{"nombre": "fotograma_00001.jpg", "lat": -33.4, "lon": -70.6}]}
        )
        assert not veredicto.correcta and "posición" in veredicto.motivo


class TestLaVerificacion:
    def test_si_se_pidio_h264_y_salio_otra_cosa_se_rechaza(
        self, tmp_path, herramientas, monkeypatch
    ):
        ffmpeg, ffprobe = herramientas
        monkeypatch.setattr(
            video, "sondar", lambda **k: video.Disponible(ffmpeg=ffmpeg, ffprobe=ffprobe)
        )
        salida = _video(tmp_path / "s.mp4", codec="hevc")
        veredicto = motor._verificar_video(salida, {"operacion": "comprimir"})
        assert not veredicto.correcta and "H.264" in veredicto.motivo

    def test_un_recorte_que_no_dura_lo_pedido_se_rechaza(self, tmp_path, herramientas, monkeypatch):
        ffmpeg, ffprobe = herramientas
        monkeypatch.setattr(
            video, "sondar", lambda **k: video.Disponible(ffmpeg=ffmpeg, ffprobe=ffprobe)
        )
        salida = _video(tmp_path / "s.mp4", codec="h264", duracion=9)
        veredicto = motor._verificar_video(
            salida, {"operacion": "recortar", "duracion_esperada_s": 5}
        )
        assert not veredicto.correcta and "debía durar" in veredicto.motivo


@pytest.mark.oraculo
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="sin FFmpeg")
def test_ffmpeg_de_verdad_saca_un_fotograma_por_segundo(tmp_path):
    """Con FFmpeg instalado: un video de prueba de 5 s da 5 fotogramas, y ffprobe lee lo escrito."""
    import subprocess

    from PIL import Image

    origen = tmp_path / "prueba.mp4"
    subprocess.run(  # noqa: S603 - argumentos fijos
        [shutil.which("ffmpeg"), "-y", "-f", "lavfi",
         "-i", "testsrc=duration=5:size=320x240:rate=25", "-c:v", "libx264", str(origen)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    ficha = video.probar(shutil.which("ffprobe"), origen)
    assert ficha.duracion_s == pytest.approx(5, abs=0.1)
    archivos, _ = video.extraer_fotogramas(
        shutil.which("ffmpeg"), origen, tmp_path / "f", video.instantes_por_tiempo(5, 1)
    )
    assert len(archivos) == 5 and all(Image.open(a).size == (320, 240) for a in archivos)
