"""La ficha EXIF de cada foto en el visor del vuelo (F18.9): cámara, GNSS y dron.

Qué se comprueba, y contra qué otro lector:

- los valores de la ficha son los del archivo de la foto: la cámara contra **`exifread`**, el XMP
  contra un **analizador de XML** (no la expresión regular del código);
- cuando la foto no está en la carpeta, la ficha sale del `export_extended` de Trimble, y sus
  valores contra el **CSV** leído con `csv` en la propia prueba;
- que **nada se esconde**: la ficha es un panel a la vista (grupos plegables con el teclado) y no un
  cuadro que aparece al pasar el ratón;
- que es **solo de quien pidió el trabajo**, y que un nombre hostil no sale de la carpeta.

Las fotos son sintéticas (`test_ficha_foto.py`); el contraste con el vuelo real, solo en local, está
en `test_vuelo_real.py`.
"""

from __future__ import annotations

import csv
import io
import json as json_mod
import re
from pathlib import Path

import exifread
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.vuelos import ficha_foto, vuelo_proceso, vuelo_trimble
from apps.vuelos.test_ficha_foto import _racional, _xmp_con_xml, jpeg_de_dji
from apps.vuelos.test_vuelo_pantalla import _archivos, _enviar
from apps.vuelos.test_vuelo_proceso import (
    EPSG,
    N_FOTOS,
    _antena,
    _desfase,
    _instante,
    _mrk,
    _trayectoria,
)
from apps.vuelos.test_vuelo_rtk import _correr as _correr_rtk

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    )
    return client


def _fila_de(grupos, titulo: str, rotulo: str) -> dict:
    grupo = next(g for g in grupos if g["titulo"] == titulo)
    return next(f for f in grupo["filas"] if f["rotulo"] == rotulo)


class TestLosTresGrupos:
    def test_cada_grupo_trae_lo_que_dice_el_archivo(self):
        datos = jpeg_de_dji()
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", datos)
        grupos = ficha_foto.grupos(ficha)
        assert [g["titulo"] for g in grupos] == ["Cámara", "GNSS", "Dron"]

        e = exifread.process_file(io.BytesIO(datos), details=False)
        x = _xmp_con_xml(datos)
        # Cámara: contra exifread.
        assert _fila_de(grupos, "Cámara", "Modelo")["valor"] == str(e["Image Model"])
        focal = _fila_de(grupos, "Cámara", "Distancia focal")
        assert focal["numero"] == pytest.approx(_racional(e["EXIF FocalLength"]))
        assert focal["valor"] == "12,29 mm"
        assert _fila_de(grupos, "Cámara", "Apertura")["valor"] == "f/4,5"
        assert _fila_de(grupos, "Cámara", "Tiempo de exposición")["valor"] == "1/2000 s"
        assert _fila_de(grupos, "Cámara", "ISO")["valor"] == "100"
        assert _fila_de(grupos, "Cámara", "Dimensiones")["valor"] == "5280 × 3956 px"
        # GNSS y dron: contra el XMP.
        assert _fila_de(grupos, "GNSS", "Calidad de la posición")["valor"] == "fija"
        assert _fila_de(grupos, "GNSS", "Bandera RTK")["numero"] == int(x["RtkFlag"])
        assert _fila_de(grupos, "GNSS", "Desviación RTK, latitud")["numero"] == float(
            x["RtkStdLat"]
        )
        assert _fila_de(grupos, "GNSS", "Altura de la foto")["numero"] == float(
            x["AbsoluteAltitude"]
        )
        assert _fila_de(grupos, "GNSS", "Estado que declara el GPS")["valor"] == "RTK"
        guinada = _fila_de(grupos, "Dron", "Gimbal, guiñada")
        assert guinada["numero"] == float(x["GimbalYawDegree"]) and guinada["valor"] == "-11,30 °"
        assert _fila_de(grupos, "Dron", "Gimbal, cabeceo (−90° = nadir)")["numero"] == -80.0
        assert _fila_de(grupos, "Dron", "Velocidad X")["valor"] == "11,2 m/s"

    def test_lo_que_falta_no_se_pone_como_guion(self):
        """Una foto sin XMP no inventa un gimbal en cero: el grupo del dron ni aparece."""
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji(xmp=b""))
        grupos = ficha_foto.grupos(ficha)
        assert "Dron" not in [g["titulo"] for g in grupos]
        assert _fila_de(grupos, "GNSS", "Calidad de la posición")["valor"] == "no informada"
        titulos = {f["rotulo"] for g in grupos for f in g["filas"]}
        assert "Bandera RTK" not in titulos and "Gimbal, guiñada" not in titulos

    def test_el_desfase_del_mrk_va_en_gnss_con_su_signo_y_si_se_aplico(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji())
        grupos = ficha_foto.grupos(
            ficha, {"n_mm": 27.0, "e_mm": 3.0, "v_mm": 92.0, "aplicado": True}
        )
        vertical = _fila_de(
            grupos, "GNSS", "Desfase antena a cámara, vertical (positivo hacia abajo)"
        )
        assert vertical["numero"] == 92.0
        assert _fila_de(grupos, "GNSS", "Desfase antena a cámara, norte")["numero"] == 27.0
        assert _fila_de(grupos, "GNSS", "Desfase en la posición entregada")["valor"] == "aplicado"
        sin = ficha_foto.grupos(ficha, {"n_mm": 1.0, "e_mm": 1.0, "v_mm": 1.0, "aplicado": False})
        assert _fila_de(sin, "GNSS", "Desfase en la posición entregada")["valor"] == "no aplicado"

    def test_una_exposicion_larga_se_dice_en_segundos(self):
        ficha = ficha_foto.FichaFoto(nombre="a", exposicion_s=2.5)
        assert _fila_de(ficha_foto.grupos(ficha), "Cámara", "Tiempo de exposición")["valor"] == (
            "2,5 s"
        )

    def test_la_ficha_sobrevive_a_su_ida_y_vuelta_por_el_vuelo_json(self):
        ficha = ficha_foto.leer_ficha_de_bytes("a.jpg", jpeg_de_dji())
        assert ficha_foto.FichaFoto.de_dict(ficha.a_dict()) == ficha
        assert "marca" in ficha.a_dict()
        assert ficha_foto.FichaFoto.de_dict({"nombre": "x", "campo_ajeno": 1}).nombre == "x"


# --- La ficha desde el archivo de Trimble ------------------------------------------------------

CABECERA_EXTENDIDA = (
    "ID,Este,Norte,Elevación,Fecha,Modelo,Apertura,Tiempo exp.,F Number,Focal,Focal 35 mm,"
    "ISO Speed,Dimensiones,Shutter,SW,Calidad,Latitud,Longitud,Altura,Alt. abs. vuelo,"
    "Alt.rel.vuelo,Gimbal Roll,Gimbal Yaw,Gimbal Pitch,UAV Roll,UAV Yaw,UAV Pitch,"
    "V. UAV X,V. UAV Y,V. UAV Z"
)


def _export_extendido() -> bytes:
    """Lo que entregaría Trimble: las posiciones de las fotos y los datos de la toma."""
    from pyproj import Transformer

    a_ll = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    filas = [CABECERA_EXTENDIDA]
    for i in range(N_FOTOS):
        n, e, v = _desfase(i)
        ea, na, ha = _antena(_instante(i))
        este, norte, alto = ea + e / 1000, na + n / 1000, ha - v / 1000
        lon, lat = a_ll.transform(este, norte)
        filas.append(
            f"DJI_{i + 1:04d}_V.JPG,{este:.3f},{norte:.3f},{alto:.3f},2025:12:29 12:38:52,DJI M3E,"
            f"4.34,0.0005,4.5,12.29,24,100,5280 x 3956,10.9658,11.09.08.24,PPK,{lat:.9f},{lon:.9f},"
            f"{alto:.3f},{alto + 58.0:+.3f},+79.724,+0.00,{-11.3 - i / 10:+.2f},-80.00,"
            f"-11.40,-9.80,{-16.0 + i / 100:+.2f},11.2,-1.9,-0.1"
        )
    return ("\n".join(filas) + "\n").encode("cp1252")


class TestLaFichaDeTrimble:
    def test_los_valores_son_los_columnas_del_csv_leido_con_csv(self):
        posiciones = vuelo_trimble.leer_posiciones_por_foto(_export_extendido())
        crudo = list(csv.DictReader(io.StringIO(_export_extendido().decode("cp1252"))))
        for r, fila in zip(posiciones[:5], crudo[:5], strict=True):
            f = ficha_foto.ficha_de_trimble(r.nombre, r.extras)
            assert f.fuente == "trimble" and f.modelo == "DJI M3E"
            assert f.focal_mm == float(fila["Focal"]) and f.apertura_f == float(fila["F Number"])
            assert f.exposicion_s == float(fila["Tiempo exp."]) and f.iso == 100
            assert (f.ancho_px, f.alto_px) == (5280, 3956)
            assert f.gimbal_guinada_deg == float(fila["Gimbal Yaw"])
            assert f.gimbal_cabeceo_deg == float(fila["Gimbal Pitch"])
            assert f.gimbal_alabeo_deg == float(fila["Gimbal Roll"])
            assert f.dron_guinada_deg == float(fila["UAV Yaw"])
            assert f.velocidad_z_ms == float(fila["V. UAV Z"])
            assert f.alt_m == float(fila["Alt. abs. vuelo"])

    def test_trimble_no_exporta_la_bandera_y_no_se_inventa(self):
        r = vuelo_trimble.leer_posiciones_por_foto(_export_extendido())[0]
        f = ficha_foto.ficha_de_trimble(r.nombre, r.extras)
        assert f.rtk_bandera is None and f.rtk_desv_lat_m is None and f.tipo_de_altura is None
        grupos = ficha_foto.grupos(f, calidad=r.calidad)
        assert _fila_de(grupos, "GNSS", "Calidad según Trimble")["valor"] == "PPK"
        assert "Bandera RTK" not in {fl["rotulo"] for g in grupos for fl in g["filas"]}

    def test_el_vuelo_json_la_guarda_solo_de_las_fotos_que_no_estan_en_la_carpeta(self):
        r = vuelo_proceso.procesar(
            trayectoria=_trayectoria(),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            referencia=_export_extendido(),
            nombres_en_carpeta=["DJI_0002_V.JPG"],
            escala_de_tiempo="GPST",
        )
        fotos = json_mod.loads(r.archivos["vuelo.json"])["fotos"]
        assert (
            "ficha" not in fotos[1] and fotos[1]["miniatura"]
        )  # está en la carpeta: se lee de ahí
        assert fotos[0]["ficha"]["modelo"] == "DJI M3E" and fotos[0]["ficha"]["fuente"] == "trimble"
        assert fotos[0]["desfase"]["aplicado"] is True


# --- La vista ------------------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaVistaDeLaFicha:
    def test_lee_la_cabecera_del_archivo_en_la_carpeta_y_coincide_con_exifread_y_el_xml(
        self,
        sesion,
        tmp_path,
    ):
        trabajo = _correr_rtk(sesion, tmp_path)
        assert trabajo.status == "done", trabajo.reason_detail
        carpeta = tmp_path / "fotos"
        archivo = sorted(carpeta.iterdir())[2].read_bytes()

        respuesta = sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 3]))
        assert respuesta.status_code == 200 and "no-store" in respuesta["Cache-Control"]
        json = respuesta.json()
        assert json["fuente"] == "foto" and "archivo de la foto" in json["fuente_texto"]
        grupos = json["grupos"]
        assert [g["titulo"] for g in grupos] == ["Cámara", "GNSS", "Dron"]

        e = exifread.process_file(io.BytesIO(archivo), details=False)
        x = _xmp_con_xml(archivo)
        assert _fila_de(grupos, "Cámara", "Modelo")["valor"] == str(e["Image Model"])
        assert _fila_de(grupos, "Cámara", "Distancia focal")["numero"] == pytest.approx(
            _racional(e["EXIF FocalLength"])
        )
        # La foto 3 es la de la bandera 16 (simple): el índice 2 del reparto 50, 34, 16.
        assert _fila_de(grupos, "GNSS", "Calidad de la posición")["valor"] == "simple"
        assert _fila_de(grupos, "GNSS", "Bandera RTK")["numero"] == int(x["RtkFlag"]) == 16
        assert _fila_de(grupos, "Dron", "Gimbal, cabeceo (−90° = nadir)")["numero"] == float(
            x["GimbalPitchDegree"]
        )
        # El desfase del .MRK, de ese disparo.
        assert _fila_de(grupos, "GNSS", "Desfase antena a cámara, vertical (positivo hacia abajo)")[
            "numero"
        ] == float(_desfase(2)[2])
        assert _fila_de(grupos, "GNSS", "Desfase en la posición entregada")["valor"] == "aplicado"

    def test_el_original_no_se_toca(self, sesion, tmp_path):
        import hashlib

        trabajo = _correr_rtk(sesion, tmp_path)
        fotos = sorted((tmp_path / "fotos").iterdir())
        antes = {
            str(f): (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns)
            for f in fotos
        }
        for n in (1, 2, 3):
            assert (
                sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, n])).status_code
                == 200
            )
        despues = {
            str(f): (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns)
            for f in fotos
        }
        assert despues == antes

    def test_una_foto_fuera_de_rango_es_404(self, sesion, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        for n in (0, N_FOTOS + 1, 9999):
            assert (
                sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, n])).status_code
                == 404
            )

    def test_una_foto_borrada_sin_trimble_que_la_describa_dice_por_que_con_404(
        self,
        sesion,
        tmp_path,
    ):
        trabajo = _correr_rtk(sesion, tmp_path)
        sorted((tmp_path / "fotos").iterdir())[1].unlink()
        respuesta = sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 2]))
        assert respuesta.status_code == 404

    def test_una_foto_que_dejo_de_ser_imagen_no_revienta(self, sesion, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        sorted((tmp_path / "fotos").iterdir())[1].write_bytes(b"no soy una foto")
        assert sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 2])).status_code == 404

    def test_si_la_carpeta_deja_de_estar_permitida_no_se_lee(self, sesion, tmp_path, settings):
        trabajo = _correr_rtk(sesion, tmp_path)
        settings.RAICES_PERMITIDAS = str(tmp_path / "trabajo")
        assert sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 1])).status_code == 404

    def test_un_enlace_simbolico_que_sale_de_la_carpeta_no_se_lee(self, sesion, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        fuera = tmp_path.parent / f"{tmp_path.name}_fuera.jpg"
        fuera.write_bytes(jpeg_de_dji())
        destino = sorted((tmp_path / "fotos").iterdir())[0]
        destino.unlink()
        try:
            destino.symlink_to(fuera)
        except OSError:
            pytest.skip("esta máquina no deja crear enlaces simbólicos")
        assert sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 1])).status_code == 404

    def test_es_solo_de_quien_pidio_el_trabajo(self, sesion, client, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        url = reverse("documents:vuelo_ficha", args=[trabajo.pk, 1])
        client.logout()
        assert type(client)().get(url).status_code == 302  # sin sesión
        client.force_login(
            get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        )
        assert client.get(url).status_code == 404  # otra persona: ni confirma que exista

    def test_solo_se_lee_con_get(self, sesion, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        url = reverse("documents:vuelo_ficha", args=[trabajo.pk, 1])
        assert sesion.post(url).status_code == 405

    def test_la_ficha_de_trimble_sale_cuando_la_foto_no_esta_en_la_carpeta(self, sesion, tmp_path):
        """Un vuelo de Trimble sin carpeta de fotos: la ficha sale del export_extended."""
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        rutas = _archivos(tmp_path)
        rutas["referencia"].write_bytes(_export_extendido())
        assert _enviar(sesion, rutas).status_code == 302
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail

        json = sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 4])).json()
        assert json["fuente"] == "trimble" and "Trimble" in json["fuente_texto"]
        crudo = list(csv.DictReader(io.StringIO(_export_extendido().decode("cp1252"))))[3]
        grupos = json["grupos"]
        assert _fila_de(grupos, "Cámara", "Modelo")["valor"] == crudo["Modelo"]
        assert _fila_de(grupos, "Dron", "Gimbal, guiñada")["numero"] == float(crudo["Gimbal Yaw"])
        assert _fila_de(grupos, "Dron", "Velocidad X")["numero"] == float(crudo["V. UAV X"])
        assert _fila_de(grupos, "GNSS", "Calidad según Trimble")["valor"] == "PPK"
        assert _fila_de(grupos, "GNSS", "Desfase en la posición entregada")["valor"] == "aplicado"

    def test_sin_carpeta_ni_trimble_que_la_describa_es_404(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        # Sin las posiciones de Trimble (y sin carpeta) no hay quién describa la foto.
        respuesta = _enviar(sesion, _archivos(tmp_path), referencia="", sistema="32719")
        assert respuesta.status_code == 302
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert sesion.get(reverse("documents:vuelo_ficha", args=[trabajo.pk, 1])).status_code == 404


# --- La página: un panel a la vista, accesible y sin esconderse en hover --------------------------


@pytest.mark.django_db
class TestElPanelEsAccesibleYNoSeEscondeEnHover:
    def test_la_pagina_trae_el_panel_y_dice_de_donde_pedirlo(self, sesion, tmp_path):
        trabajo = _correr_rtk(sesion, tmp_path)
        cuerpo = sesion.get(reverse("documents:vuelo_ver", args=[trabajo.pk])).content.decode()
        assert reverse("documents:vuelo_ficha", args=[trabajo.pk, 1]) in cuerpo
        assert 'id="visor-exif"' in cuerpo and "Ficha de la foto" in cuerpo
        # Una región con nombre (para el lector de pantalla) y que se anuncia al cambiar.
        assert 'aria-labelledby="visor-exif-titulo"' in cuerpo
        assert 'id="visor-exif-fuente"' in cuerpo and 'role="status"' in cuerpo

    def test_nada_de_la_ficha_se_esconde_en_hover(self):
        plantilla = (RAIZ / "templates/vuelos/vuelo_visor.html").read_text(encoding="utf-8")
        js = (RAIZ / "static/js/vuelo.js").read_text(encoding="utf-8")
        css = (RAIZ / "static/css/app.css").read_text(encoding="utf-8")
        assert "group-hover" not in plantilla and "opacity-0" not in plantilla
        bloque = js[js.index("function mostrarFicha") : js.index("function mostrarFoto")]
        for prohibido in ("mouseover", "mouseenter", "mouseleave", "pointerenter", "onmouse"):
            assert prohibido not in bloque
        # Los grupos son `<details>` con `<summary>`: se despliegan con el teclado.
        assert 'createElement("details")' in bloque and 'createElement("summary")' in bloque
        assert "grupo.open = true" in bloque, "los grupos nacen abiertos: nada que descubrir"
        reglas = re.findall(r"\.visor-exif[^{]*\{[^}]*\}", css)
        assert reglas and not any(":hover" in r and "opacity" in r for r in reglas)

    def test_los_textos_de_la_ficha_entran_con_text_content_y_nunca_como_html(self):
        js = (RAIZ / "static/js/vuelo.js").read_text(encoding="utf-8")
        bloque = js[js.index("function mostrarFicha") : js.index("function mostrarFoto")]
        assert "innerHTML" not in bloque and "insertAdjacentHTML" not in bloque
        assert "textContent" in bloque

    def test_el_pedido_de_una_foto_vieja_se_descarta(self):
        js = (RAIZ / "static/js/vuelo.js").read_text(encoding="utf-8")
        bloque = js[js.index("function mostrarFicha") : js.index("function mostrarFoto")]
        assert "marca !== fichaPedida" in bloque
