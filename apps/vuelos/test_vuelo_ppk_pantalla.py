"""«Corregir un vuelo de dron», la segunda entrada: la trayectoria se calcula con RTKLIB (F18.7).

**No hay RTKLIB en el CI ni una corrida real** (la base de un vuelo real falta, pedido P18), así que
aquí se prueba todo lo que rodea a la corrida, con un `rnx2rtkp` de mentira: un programa de verdad
(`.cmd` en Windows, guion de `sh` en Linux) que lanza un Python, escribe un `.pos` de resultado
conocido e imprime líneas de avance como las de RTKLIB. El vuelo es el sintético y de fórmula
conocida de `test_vuelo_proceso.py`: la trayectoria del `.pos` sale de **la misma fórmula** que
las posiciones «de Trimble» con que se contrasta, y la calidad de cada época es conocida.

Lo que se comprueba, y contra qué:

- que el sistema de la base sin elegir se rechaza, y que una base a kilómetros también;
- que sin RTKLIB la opción sale apagada con el motivo `sin-rnx2rtkp`, y no oculta;
- que el zip trae el `.pos` y su resumen, y que la calidad por foto coincide con la que se calcula
  **aparte** en la prueba, mirando las épocas vecinas de cada disparo;
- que el avance llega con fracciones crecientes;
- que los originales no cambian (`sha256` y `mtime`) ni en el camino feliz ni en el que falla.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import motor, tarea
from apps.vuelos import vuelo_ppk
from apps.vuelos.test_vuelo_ppk import _ecef, _rinex
from apps.vuelos.test_vuelo_proceso import (
    A_LL,
    GPS_INICIO_S,
    N_FOTOS,
    _antena,
    _fotos_de_trimble,
    _instante,
    _mrk,
)

pytestmark = pytest.mark.django_db

#: La base declarada: cerca del vuelo sintético (zona 19 sur, a unos 7 420 km del ecuador).
BASE_LAT, BASE_LON, BASE_ALT = -23.0, -69.0, 1100.0

PASO_S = 0.2
EPOCAS = 2000
#: Las primeras 200 épocas son fijas (Q=1) y el resto flotantes (Q=2).
FIJAS_HASTA = 200


# --- El vuelo y sus archivos ---------------------------------------------------------------


def _fecha(t_s: float) -> datetime:
    return datetime(1980, 1, 6) + timedelta(seconds=GPS_INICIO_S + t_s)


def _pos_del_vuelo(suma_alt_m: float = 0.0) -> str:
    """El `.pos` que escribiría RTKLIB: la antena de la fórmula, con calidad conocida por época."""
    lineas = [
        "% program   : RTKPOST ver.2.4.3\n",
        "%  GPST                  latitude(deg) longitude(deg)  height(m)   Q  ns   sdn(m)   "
        "sde(m)   sdu(m)  sdne(m)  sdeu(m)  sdun(m) age(s)  ratio\n",
    ]
    for i in range(EPOCAS):
        t = -10.0 + i * PASO_S
        este, norte, alt = _antena(t)
        lon, lat = A_LL.transform(este, norte)
        q = 1 if i < FIJAS_HASTA else 2
        fecha = _fecha(t)
        lineas.append(
            f"{fecha:%Y/%m/%d %H:%M:%S}.{round(fecha.microsecond / 1000):03d} {lat:14.9f} "
            f"{lon:14.9f} {alt + suma_alt_m:10.4f} {q:3d} 12 0.0020 0.0020 0.0040 0.0000 0.0000 "
            "0.0000 0.00 99.9\n"
        )
    return "".join(lineas)


def _hora_de_rinex(t_s: float, etiqueta: str) -> str:
    f = _fecha(t_s)
    campos = f"{f.year:6d}{f.month:6d}{f.day:6d}{f.hour:6d}{f.minute:6d}{f.second:13.7f}"
    return (campos + "     GPS").ljust(60) + etiqueta


def _rinex_del_vuelo(carpeta: Path, *, con_fin: bool = True, base=(BASE_LAT, BASE_LON)) -> dict:
    extra = _hora_de_rinex(-10.0, "TIME OF FIRST OBS")
    if con_fin:
        extra += "\n" + _hora_de_rinex(-10.0 + EPOCAS * PASO_S, "TIME OF LAST OBS")
    return {
        "rover_obs": _rinex(carpeta, "DJI_0001_PPKOBS.obs", "O", xyz=(0.0, 0.0, 0.0), extra=extra),
        "navegacion": _rinex(carpeta, "DJI_0001_PPKNAV.nav", "N"),
        "navegacion_extra": _rinex(carpeta, "efemerides.25g", "N"),
        "base_obs": _rinex(carpeta, "13933630.25o", "O", xyz=_ecef(*base, BASE_ALT)),
    }


# --- Un rnx2rtkp de mentira ----------------------------------------------------------------

GUION_FALSO = """
import json
import sys
import time
from pathlib import Path

config = json.loads(Path(__file__).with_name("falso.json").read_text(encoding="utf-8"))
argumentos = sys.argv[1:]
Path(__file__).with_name("recibido.json").write_text(json.dumps(argumentos), encoding="utf-8")
salida = argumentos[argumentos.index("-o") + 1]
if config.get("pid_en"):
    import os

    Path(config["pid_en"]).write_text(str(os.getpid()), encoding="utf-8")
if config.get("duerme"):
    time.sleep(config["duerme"])
for linea in config.get("progreso", []):
    sys.stderr.write(linea + chr(13))
    sys.stderr.flush()
    time.sleep(0.002)
if config.get("mensaje"):
    sys.stderr.write(config["mensaje"] + chr(10))
if config.get("escribe") is not None:
    Path(salida).write_text(config["escribe"], encoding="utf-8")
# La regla 1: este programa sale con 0 haya escrito algo o no.
sys.exit(0)
"""


@pytest.fixture
def rtklib_falso(tmp_path, settings):
    """Un `rnx2rtkp` ejecutable, configurado como el de verdad (`RTKLIB_RNX2RTKP`)."""
    carpeta = tmp_path / "rtklib"
    carpeta.mkdir()
    (carpeta / "falso.py").write_text(GUION_FALSO, encoding="utf-8")
    if os.name == "nt":
        programa = carpeta / "rnx2rtkp.cmd"
        programa.write_text(
            f'@echo off\r\n"{sys.executable}" "{carpeta / "falso.py"}" %*\r\n', encoding="utf-8"
        )
    else:
        programa = carpeta / "rnx2rtkp"
        programa.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{carpeta / "falso.py"}" "$@"\n', encoding="utf-8"
        )
        programa.chmod(programa.stat().st_mode | stat.S_IXUSR)
    settings.RTKLIB_RNX2RTKP = str(programa)

    def configurar(**config) -> Path:
        (carpeta / "falso.json").write_text(json.dumps(config), encoding="utf-8")
        return programa

    configurar.programa = programa
    configurar.carpeta = carpeta
    configurar.recibido = lambda: json.loads((carpeta / "recibido.json").read_text("utf-8"))
    return configurar


def _avance_de_mentira() -> list[str]:
    """Las líneas de avance de un RTKLIB que recorre los 400 s del vuelo, de 20 en 20 s."""
    horas = [_fecha(-10.0 + s) for s in range(0, 401, 20)]
    return [f"processing : {h:%Y/%m/%d %H:%M:%S}.0 Q=1 ns=14" for h in horas]


# --- La pantalla ------------------------------------------------------------------------------


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    )
    return client


def _enviar(sesion, tmp_path, rinex, **extra):
    disparos = tmp_path / "vuelo_Timestamp.MRK"
    disparos.write_bytes(_mrk())
    referencia = tmp_path / "export_extended.csv"
    referencia.write_bytes(_fotos_de_trimble())
    datos = {
        "origen": "rinex",
        "disparos": str(disparos),
        "referencia": str(referencia),
        "rover_obs": str(rinex["rover_obs"]),
        "navegacion": str(rinex["navegacion"]),
        "navegacion_extra": str(rinex["navegacion_extra"]),
        "base_obs": str(rinex["base_obs"]),
        "base_lat": str(BASE_LAT).replace(
            ".", ","
        ),  # con coma: es lo que teclea quien escribe en es
        "base_lon": str(BASE_LON),
        "base_alt": str(BASE_ALT),
        "base_sistema": "SIRGAS-Chile 2002",
        "sistema": "medir",
        "aplicar_desfase": "on",
        "ppk_modo": "cinematico",
        "ppk_mascara_elevacion_deg": "15",
        "ppk_umbral_ambiguedad": "3",
        "ppk_sistemas": ["G", "R", "E", "C"],
        **extra,
    }
    return sesion.post(reverse("documents:vuelo_dron"), datos)


def _etiqueta(cuerpo: str, identificador: str) -> str:
    """La etiqueta `<input>` o `<select>` con ese `id`, para mirar sus atributos sin depender de
    los espacios de la plantilla."""
    return re.search(rf'<(?:input|select)[^>]*id="{identificador}"[^>]*>', cuerpo, re.S).group(0)


def _huella(rutas) -> dict:
    return {
        str(r): (hashlib.sha256(Path(r).read_bytes()).hexdigest(), Path(r).stat().st_mtime_ns)
        for r in rutas
    }


class TestLaEleccionDeOrigen:
    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("documents:vuelo_dron")).status_code == 302
        assert client.post(reverse("documents:vuelo_dron"), {"origen": "rinex"}).status_code == 302

    def test_la_pregunta_y_sus_tres_respuestas_estan_a_la_vista(self, sesion, rtklib_falso):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert "¿De dónde sale la posición precisa?" in cuerpo
        assert "La exportó Trimble Business Center" in cuerpo
        assert "Calcularla aquí con RTKLIB (PPK)" in cuerpo
        assert "Las fotos ya traen la posición RTK" in cuerpo
        for valor in ("trimble", "rinex", "fotos"):
            assert f'value="{valor}"' in cuerpo
        # Por omisión, lo de hoy.
        assert "checked" in _etiqueta(cuerpo, "id_origen_trimble")
        assert "checked" not in _etiqueta(cuerpo, "id_origen_rinex")
        assert "checked" not in _etiqueta(cuerpo, "id_origen_fotos")
        assert "disabled" not in _etiqueta(cuerpo, "id_origen_rinex")
        # Las fotos RTK no necesitan ninguna herramienta externa: nunca salen apagadas.
        assert "disabled" not in _etiqueta(cuerpo, "id_origen_fotos")

    def test_los_pasos_de_rinex_piden_lo_que_hace_falta(self, sesion, rtklib_falso):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        for texto in (
            "El RINEX del dron",
            "Las efemérides de navegación",
            "El RINEX de la base",
            "La coordenada de la base",
            "Altura elipsoidal (metros)",
            "Latitud (grados decimales)",
        ):
            assert texto in cuerpo
        # Cada campo de archivo declara su tope y la plantilla tiene dónde pintar el avance.
        assert cuerpo.count("data-tope-mb") == cuerpo.count('type="file"')
        assert "data-avance-subida" in cuerpo

    def test_el_sistema_de_la_base_no_trae_ninguno_elegido(self, sesion, rtklib_falso):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        bloque = cuerpo.split('id="id_base_sistema"')[1].split("</select>")[0]
        opciones = re.findall(r"<option[^>]*>", bloque)
        # Solo la vacía («Elija el sistema…») viene marcada: ninguno por omisión.
        assert [("selected" in o, 'value=""' in o) for o in opciones].count((True, True)) == 1
        assert bloque.count("selected") == 1
        assert "SIRGAS-Chile 2002" in bloque and "WGS84" in bloque and "ITRF2014" in bloque

    def test_las_opciones_de_rtklib_traen_su_valor_a_la_vista(self, sesion, rtklib_falso):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert 'value="15"' in _etiqueta(cuerpo, "id_ppk_mascara_elevacion_deg")
        assert 'value="3"' in _etiqueta(cuerpo, "id_ppk_umbral_ambiguedad")
        for letra in "GREC":
            assert "checked" in _etiqueta(cuerpo, f"id_ppk_sistemas_{letra}")
        for letra in "JI":
            assert "checked" not in _etiqueta(cuerpo, f"id_ppk_sistemas_{letra}")
        assert "<details" in cuerpo and "Opciones de RTKLIB" in cuerpo


class TestSinRtklibLaOpcionSaleApagadaConSuMotivo:
    @pytest.fixture(autouse=True)
    def _sin_rtklib(self, settings, monkeypatch):
        settings.RTKLIB_RNX2RTKP = ""
        settings.RTKLIB_CONVBIN = ""
        monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)

    def test_la_opcion_esta_pero_apagada_y_dice_por_que_y_que_hacer(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        # No se oculta (regla 4): sigue estando la opción, con su motivo estable y su sugerencia.
        assert "Calcularla aquí con RTKLIB (PPK)" in cuerpo
        assert "disabled" in _etiqueta(cuerpo, "id_origen_rinex")
        assert 'data-motivo="sin-rnx2rtkp"' in cuerpo and "No disponible en esta máquina" in cuerpo
        assert "sudo apt install rtklib" in cuerpo and "AEROCONVERT_RTKLIB_RNX2RTKP" in cuerpo
        # Y la otra sigue siendo la elegida.
        assert "checked" in _etiqueta(cuerpo, "id_origen_trimble")

    def test_el_motor_dice_lo_mismo(self):
        pedida = motor.disponibilidad("vuelo_dron", {"origen": "rinex"})
        assert not pedida.disponible and pedida.codigo_motivo == "sin-rnx2rtkp"
        assert "sudo apt install rtklib" in pedida.sugerencia
        # La trayectoria de Trimble no necesita RTKLIB: sigue encendida.
        assert motor.disponibilidad("vuelo_dron").disponible
        assert motor.disponibilidad("vuelo_dron", {"origen": "trimble"}).disponible

    def test_pedirla_igual_se_rechaza_con_el_motivo_y_no_encola(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        rinex = _rinex_del_vuelo(tmp_path)
        respuesta = _enviar(sesion, tmp_path, rinex)
        assert respuesta.status_code == 200
        cuerpo = respuesta.content.decode()
        assert "no tiene RTKLIB" in cuerpo and "Mientras tanto sirve la trayectoria" in cuerpo
        assert not ConversionJob.objects.exists()

    def test_el_motivo_esta_en_el_catalogo_y_tiene_su_paso(self):
        from apps.engines.equipo import PASOS
        from apps.jobs.motivos import MOTIVOS

        assert "sin-rnx2rtkp" in MOTIVOS and "sin-rnx2rtkp" in PASOS


class TestLoQueSeRechazaAntesDeEncolar:
    def _rechazada(self, sesion, tmp_path, texto, rinex=None, **extra):
        from apps.jobs.models import ConversionJob

        respuesta = _enviar(sesion, tmp_path, rinex or _rinex_del_vuelo(tmp_path), **extra)
        assert respuesta.status_code == 200, "se vuelve al formulario, no a la ficha del trabajo"
        assert texto in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_el_sistema_de_la_base_sin_elegir_no_se_supone(self, sesion, tmp_path, rtklib_falso):
        rtklib_falso(escribe=_pos_del_vuelo())
        self._rechazada(
            sesion, tmp_path, "Elija el sistema de las coordenadas de la base", base_sistema=""
        )
        assert not (rtklib_falso.carpeta / "recibido.json").exists(), "ni se lanzó RTKLIB"

    def test_un_sistema_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        self._rechazada(sesion, tmp_path, "no es de los que se ofrecen", base_sistema="PSAD56")

    @pytest.mark.parametrize(
        "campo,texto",
        [
            ("base_lat", "Falta la latitud de la base"),
            ("base_lon", "Falta la longitud de la base"),
            ("base_alt", "Falta la altura elipsoidal de la base"),
        ],
    )
    def test_falta_una_coordenada_de_la_base(self, sesion, tmp_path, rtklib_falso, campo, texto):
        self._rechazada(sesion, tmp_path, texto, **{campo: ""})

    def test_una_coordenada_que_no_es_un_numero(self, sesion, tmp_path, rtklib_falso):
        self._rechazada(sesion, tmp_path, "no es un número", base_lat="veinte")

    def test_una_altura_que_no_es_creible_dice_que_se_espera_la_elipsoidal(
        self, sesion, tmp_path, rtklib_falso
    ):
        self._rechazada(sesion, tmp_path, "altura **elipsoidal**", base_alt="45000")

    def test_la_base_a_kilometros_del_rinex_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        # El RINEX de la base dice estar medio grado al sur: ~55 km.
        rinex = _rinex_del_vuelo(tmp_path, base=(BASE_LAT - 0.5, BASE_LON))
        self._rechazada(sesion, tmp_path, "km de donde dice estar", rinex=rinex)
        assert not (rtklib_falso.carpeta / "recibido.json").exists()

    def test_un_rinex_que_no_es_lo_que_dice_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        rinex = _rinex_del_vuelo(tmp_path)
        # Una observación con nombre de efemérides: el nombre no la delata, la cabecera sí.
        rinex["navegacion"] = _rinex(tmp_path, "falsa.nav", "O")
        self._rechazada(sesion, tmp_path, "no es de navegación", rinex=rinex)

    @pytest.mark.parametrize(
        "campo,texto",
        [
            ("rover_obs", "Falta el RINEX de observación del dron"),
            ("navegacion", "Falta el RINEX de navegación"),
            ("base_obs", "Falta el RINEX de observación de la base"),
        ],
    )
    def test_falta_un_rinex(self, sesion, tmp_path, rtklib_falso, campo, texto):
        self._rechazada(sesion, tmp_path, texto, **{campo: ""})

    def test_una_extension_que_no_es_de_rinex_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        rinex = _rinex_del_vuelo(tmp_path)
        pdf = tmp_path / "base.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        rinex["base_obs"] = pdf
        self._rechazada(sesion, tmp_path, "no parece un RINEX de observación", rinex=rinex)

    def test_una_opcion_de_rtklib_fuera_de_rango_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        self._rechazada(sesion, tmp_path, "máscara de elevación", ppk_mascara_elevacion_deg="80")

    def test_una_mascara_no_entera_no_se_trunca(self, sesion, tmp_path, rtklib_falso):
        self._rechazada(sesion, tmp_path, "grados enteros", ppk_mascara_elevacion_deg="10.9")

    def test_un_sistema_satelital_que_no_se_ofrece_no_se_descarta_en_silencio(
        self, sesion, tmp_path, rtklib_falso
    ):
        self._rechazada(
            sesion, tmp_path, "no es un sistema satelital de los que se ofrecen",
            ppk_sistemas=["G", "X"],
        )  # fmt: skip

    def test_sin_ningun_sistema_satelital_se_rechaza(self, sesion, tmp_path, rtklib_falso):
        self._rechazada(sesion, tmp_path, "sistemas satelitales", ppk_sistemas=[])


# --- De punta a punta ----------------------------------------------------------------------


def _correr(sesion, tmp_path, rtklib_falso, config=None, **extra):
    from apps.jobs import despachador
    from apps.jobs.models import ConversionJob

    rtklib_falso(**(config if config is not None else {"escribe": _pos_del_vuelo()}))
    rinex = _rinex_del_vuelo(tmp_path)
    antes = _huella(rinex.values())
    respuesta = _enviar(sesion, tmp_path, rinex, **extra)
    assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"], (
        respuesta.content.decode()[:2000] if respuesta.status_code == 200 else ""
    )
    assert despachador.procesar_una_vez() == 1
    return ConversionJob.objects.latest("created_at"), rinex, antes


def _avisos(trabajo) -> list[str]:
    """Lo que el trabajo anotó en su bitácora como aviso."""
    return [e.message for e in trabajo.eventos.filter(level="warn")]


def _calidad_esperada(i: int) -> str:
    """La calidad de la foto `i`, calculada **aparte**: la peor de sus dos épocas vecinas."""
    indice = int((_instante(i) + 10.0) / PASO_S + 1e-9)  # la época anterior al disparo
    q = [1 if k < FIJAS_HASTA else 2 for k in (indice, indice + 1)]
    return "fija" if max(q) == 1 else "flotante"


class TestDePuntaAPunta:
    def test_el_zip_trae_el_pos_su_resumen_y_los_entregables(self, sesion, tmp_path, rtklib_falso):
        pos = _pos_del_vuelo()
        trabajo, rinex, antes = _correr(sesion, tmp_path, rtklib_falso, {"escribe": pos})
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.progress_percent == 100
        with zipfile.ZipFile(trabajo.output_path) as z:
            assert sorted(z.namelist()) == sorted(
                [
                    "fotos.csv",
                    "fotos.geojson",
                    "fotos.kml",
                    "calidad.md",
                    "vuelo.json",
                    "trayectoria.pos",
                    "trayectoria.md",
                ]
            )
            # El .pos del zip es **el que escribió RTKLIB**, tal cual.
            assert z.read("trayectoria.pos").decode("utf-8") == pos
            resumen = z.read("trayectoria.md").decode("utf-8")
            calidad = z.read("calidad.md").decode("utf-8")
        assert "Calidad de las posiciones" in resumen and "Fija: 10.0 %" in resumen
        assert "Calculada con **RTKLIB**" in calidad
        # Lo declarado queda escrito: sin la base y su sistema el .pos no se puede repetir.
        assert "**SIRGAS-Chile 2002** (declarado por quien procesó" in resumen
        assert (
            f"altura elipsoidal {BASE_ALT:.4f} m" in resumen
            and "umbral de ambigüedades 3" in resumen
        )
        assert (
            trabajo.verification["verificado_con"]
            and "lectura del .pos" in (trabajo.verification["verificado_con"])
        )
        assert trabajo.verification["piezas_verificadas"] == 7
        # Los originales, intactos.
        assert _huella(rinex.values()) == antes

    def test_la_calidad_de_cada_foto_sale_de_las_epocas_vecinas(
        self, sesion, tmp_path, rtklib_falso
    ):
        trabajo, _rinex, _antes = _correr(sesion, tmp_path, rtklib_falso)
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as z:
            filas = list(csv.DictReader(io.StringIO(z.read("fotos.csv").decode("utf-8"))))
            visor = json.loads(z.read("vuelo.json"))
        assert len(filas) == N_FOTOS
        esperadas = [_calidad_esperada(i) for i in range(N_FOTOS)]
        assert "fija" in esperadas and "flotante" in esperadas, "la prueba mide las dos"
        assert [f["calidad"] for f in filas] == esperadas
        assert [f["calidad"] for f in visor["fotos"]] == esperadas
        assert trabajo.verification["fotos_con_posicion_fija"] == esperadas.count("fija")
        assert trabajo.verification["porcentaje_fijo"] == 10.0
        # Lo que no es fijo se avisa, con la cuenta.
        assert any(
            f"{esperadas.count('flotante')} foto(s) no tienen posición fija" in a
            for a in _avisos(trabajo)
        )

    def test_la_posicion_de_las_fotos_coincide_con_la_de_trimble_en_el_plano(
        self, sesion, tmp_path, rtklib_falso
    ):
        trabajo, _r, _a = _correr(sesion, tmp_path, rtklib_falso)
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.verification["contraste_maximo_mm"] < 1.5
        assert trabajo.verification["sistema_epsg"] == 32719
        assert trabajo.verification["trayectoria_de"] == "RTKLIB (PPK)"
        assert trabajo.verification["epocas_de_rtklib"] == EPOCAS

    def test_la_altura_distinta_de_la_de_trimble_no_es_un_aviso_de_desajuste(
        self, sesion, tmp_path, rtklib_falso
    ):
        # RTKLIB da altura elipsoidal; la de Trimble es otra (35 m en el vuelo real).
        alto = _pos_del_vuelo(suma_alt_m=35.0)
        trabajo, _r, _a = _correr(sesion, tmp_path, rtklib_falso, {"escribe": alto})
        assert trabajo.status == "done", trabajo.reason_detail
        assert not any("no coinciden con las de Trimble" in a for a in _avisos(trabajo))
        with zipfile.ZipFile(trabajo.output_path) as z:
            assert "elipsoidal" in z.read("calidad.md").decode("utf-8")

    def test_las_entradas_quedan_con_su_papel_y_dos_son_de_navegacion(
        self, sesion, tmp_path, rtklib_falso
    ):
        trabajo, _r, _a = _correr(sesion, tmp_path, rtklib_falso)
        papeles = sorted(e.papel for e in trabajo.entradas.all())
        assert papeles == sorted(
            ["disparos", "rover", "base", "navegacion", "navegacion", "referencia"]
        )
        assert trabajo.options["origen"] == "rinex"
        assert trabajo.options["base_sistema"] == "SIRGAS-Chile 2002"
        assert trabajo.options["base_lat"] == pytest.approx(BASE_LAT)  # la coma se entendió

    def test_rtklib_recibe_la_base_declarada_y_las_opciones(self, sesion, tmp_path, rtklib_falso):
        trabajo, rinex, _a = _correr(
            sesion,
            tmp_path,
            rtklib_falso,
            ppk_mascara_elevacion_deg="10",
            ppk_umbral_ambiguedad="2.5",
            ppk_sistemas=["G", "E"],
            ppk_modo="estatico",
        )
        assert trabajo.status == "done", trabajo.reason_detail
        orden = rtklib_falso.recibido()
        assert orden[orden.index("-m") + 1] == "10" and orden[orden.index("-v") + 1] == "2.5"
        assert orden[orden.index("-sys") + 1] == "G,E" and orden[orden.index("-p") + 1] == "3"
        i = orden.index("-l")
        assert orden[i + 1 : i + 4] == [f"{BASE_LAT:.9f}", f"{BASE_LON:.9f}", f"{BASE_ALT:.4f}"]
        # Rover primero, base después y las efemérides al final, con rutas absolutas.
        assert orden[-4:] == [
            str(rinex["rover_obs"].resolve()),
            str(rinex["base_obs"].resolve()),
            str(rinex["navegacion"].resolve()),
            str(rinex["navegacion_extra"].resolve()),
        ]

    def test_el_corredor_le_pasa_al_hijo_la_ruta_de_rnx2rtkp(self, sesion, tmp_path, rtklib_falso):
        from apps.jobs.models import ConversionJob

        rtklib_falso(escribe=_pos_del_vuelo())
        _enviar(sesion, tmp_path, _rinex_del_vuelo(tmp_path))
        job = ConversionJob.objects.latest("created_at")
        plan = motor.plan(job)
        assert plan.env[tarea.VARIABLE_RNX2RTKP] == str(rtklib_falso.programa)

    def test_la_de_trimble_no_lleva_la_variable(self, sesion, tmp_path, rtklib_falso):
        from apps.jobs.models import ConversionJob
        from apps.vuelos.test_vuelo_pantalla import _archivos

        rutas = _archivos(tmp_path)
        respuesta = sesion.post(
            reverse("documents:vuelo_dron"),
            {
                "trayectoria": str(rutas["trayectoria"]),
                "disparos": str(rutas["disparos"]),
                "referencia": str(rutas["referencia"]),
                "sistema": "medir",
                "escala_de_tiempo": "GPST",
                "aplicar_desfase": "on",
            },
        )
        assert respuesta.status_code == 302
        job = ConversionJob.objects.latest("created_at")
        assert tarea.VARIABLE_RNX2RTKP not in motor.plan(job).env

    def test_sin_hora_de_fin_en_el_rinex_el_trabajo_igual_termina(
        self, sesion, tmp_path, rtklib_falso
    ):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        rtklib_falso(escribe=_pos_del_vuelo(), progreso=_avance_de_mentira())
        rinex = _rinex_del_vuelo(tmp_path, con_fin=False)
        assert _enviar(sesion, tmp_path, rinex).status_code == 302
        assert despachador.procesar_una_vez() == 1
        assert ConversionJob.objects.latest("created_at").status == "done"


class TestLosCaminosQueFallan:
    def test_rtklib_sale_con_cero_sin_escribir_y_el_trabajo_falla_sin_tocar_nada(
        self, sesion, tmp_path, rtklib_falso
    ):
        trabajo, rinex, antes = _correr(
            sesion, tmp_path, rtklib_falso, {"mensaje": "error: no common satellites"}
        )
        assert trabajo.status == "error"
        assert "RTKLIB no escribió ninguna posición" in trabajo.reason_detail
        assert "no common satellites" in trabajo.reason_detail
        assert not Path(trabajo.output_path).exists()
        assert _huella(rinex.values()) == antes

    def test_un_pos_que_no_lo_es_falla_y_los_originales_siguen_igual(
        self, sesion, tmp_path, rtklib_falso
    ):
        trabajo, rinex, antes = _correr(sesion, tmp_path, rtklib_falso, {"escribe": "hola\n"})
        assert trabajo.status == "error" and "no parece un .pos" in trabajo.reason_detail
        assert _huella(rinex.values()) == antes

    def test_un_pos_en_utc_falla_con_su_escala_dicha(self, sesion, tmp_path, rtklib_falso):
        utc = _pos_del_vuelo().replace("%  GPST ", "%  UTC  ", 1)
        trabajo, rinex, antes = _correr(sesion, tmp_path, rtklib_falso, {"escribe": utc})
        assert trabajo.status == "error" and "UTC" in trabajo.reason_detail
        assert _huella(rinex.values()) == antes

    def test_si_rtklib_desaparece_entre_la_pantalla_y_la_cola_el_trabajo_lo_dice(
        self, sesion, tmp_path, rtklib_falso, settings, monkeypatch
    ):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        rtklib_falso(escribe=_pos_del_vuelo())
        rinex = _rinex_del_vuelo(tmp_path)
        antes = _huella(rinex.values())
        assert _enviar(sesion, tmp_path, rinex).status_code == 302
        settings.RTKLIB_RNX2RTKP = ""
        settings.RTKLIB_CONVBIN = ""
        monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status != "done"
        assert trabajo.reason_code == "sin-rnx2rtkp"
        assert _huella(rinex.values()) == antes


class TestElAvanceLlegaALaCola:
    """La tarea escribe `PROGRESO` con la hora de RTKLIB entre la primera y la última obs."""

    def test_las_fracciones_crecen_dentro_del_tramo_de_rtklib(
        self, tmp_path, rtklib_falso, monkeypatch, capsys
    ):
        rtklib_falso(escribe=_pos_del_vuelo(), progreso=_avance_de_mentira())
        rinex = _rinex_del_vuelo(tmp_path)
        monkeypatch.setenv(tarea.VARIABLE_RNX2RTKP, str(rtklib_falso.programa))
        entradas = [
            {"ruta": str(rinex["rover_obs"]), "papel": "rover"},
            {"ruta": str(rinex["base_obs"]), "papel": "base"},
            {"ruta": str(rinex["navegacion"]), "papel": "navegacion"},
        ]
        opciones = {
            "base_lat": BASE_LAT,
            "base_lon": BASE_LON,
            "base_alt_elipsoidal_m": BASE_ALT,
            "base_sistema": "SIRGAS-Chile 2002",
        }
        resultado, texto, base = tarea._calcular_con_rtklib(entradas, opciones)
        assert resultado.trayectoria.n == EPOCAS and base.sistema == "SIRGAS-Chile 2002"
        assert texto == _pos_del_vuelo()

        salida = capsys.readouterr().out.splitlines()
        lineas = [x for x in salida if x.startswith("PROGRESO")]
        fracciones = [float(x.split()[1]) for x in lineas]
        assert len(fracciones) >= 5
        assert fracciones == sorted(fracciones), "nunca baja"
        desde, hasta = tarea.FRACCION_DE_RTKLIB
        assert fracciones[0] == pytest.approx(desde) and fracciones[-1] == pytest.approx(hasta)
        assert any("RTKLIB va en" in x for x in lineas)

    def test_sin_la_variable_del_corredor_no_se_lanza_nada(
        self, tmp_path, rtklib_falso, monkeypatch
    ):
        monkeypatch.delenv(tarea.VARIABLE_RNX2RTKP, raising=False)
        with pytest.raises(tarea.FalloDeTarea) as fallo:
            tarea._calcular_con_rtklib([], {})
        assert fallo.value.codigo == "sin-rnx2rtkp"
        assert not (rtklib_falso.carpeta / "recibido.json").exists()

    def test_una_base_sin_sistema_no_corre(self, tmp_path, rtklib_falso, monkeypatch):
        rtklib_falso(escribe=_pos_del_vuelo())
        rinex = _rinex_del_vuelo(tmp_path)
        monkeypatch.setenv(tarea.VARIABLE_RNX2RTKP, str(rtklib_falso.programa))
        entradas = [
            {"ruta": str(rinex["rover_obs"]), "papel": "rover"},
            {"ruta": str(rinex["base_obs"]), "papel": "base"},
            {"ruta": str(rinex["navegacion"]), "papel": "navegacion"},
        ]
        opciones = {
            "base_lat": BASE_LAT,
            "base_lon": BASE_LON,
            "base_alt_elipsoidal_m": BASE_ALT,
            "base_sistema": "",
        }
        from apps.documents.composicion import ComposicionInvalida

        with pytest.raises(ComposicionInvalida, match="Falta el sistema"):
            tarea._calcular_con_rtklib(entradas, opciones)
        assert not (rtklib_falso.carpeta / "recibido.json").exists()


def test_con_un_envoltorio_el_plazo_alcanza_tambien_al_nieto(tmp_path, rtklib_falso):
    """`rnx2rtkp.cmd` o el guion de `sh` lanzan a Python: matar solo al envoltorio dejaría vivo
    al que de verdad calcula. El falso escribe el PID del Python, el nieto."""
    from apps.documents.composicion import ComposicionInvalida
    from apps.vuelos.test_vuelo_ppk import _esperar_a_que_muera

    pid_en = tmp_path / "pid.txt"
    rinex = _rinex_del_vuelo(tmp_path)
    programa = rtklib_falso(duerme=60, pid_en=str(pid_en))
    with pytest.raises(ComposicionInvalida, match="tardó más de"):
        vuelo_ppk.correr(
            str(programa),
            rover=rinex["rover_obs"],
            base_obs=rinex["base_obs"],
            navegacion=[rinex["navegacion"]],
            destino=tmp_path / "s.pos",
            base=vuelo_ppk.Base(BASE_LAT, BASE_LON, BASE_ALT, "SIRGAS-Chile 2002"),
            plazo_s=3,
        )
    assert _esperar_a_que_muera(int(pid_en.read_text()))


def test_la_trayectoria_de_dos_origenes_a_la_vez_no_se_admite():
    from apps.documents.composicion import ComposicionInvalida
    from apps.vuelos import vuelo_pos, vuelo_proceso

    with pytest.raises(ComposicionInvalida, match="una trayectoria, y solo una"):
        vuelo_proceso.procesar(disparos=_mrk(), nombre_de_disparos="a.MRK")
    with pytest.raises(ComposicionInvalida, match="una trayectoria, y solo una"):
        vuelo_proceso.procesar(
            trayectoria=b"x",
            trayectoria_ppk=vuelo_pos.leer(_pos_del_vuelo()),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            escala_de_tiempo="GPST",
        )


def test_el_motor_rechaza_un_pos_con_otras_epocas_que_las_dichas(tmp_path):
    parcial = tmp_path / "v.zip"
    pos = _pos_del_vuelo()
    with zipfile.ZipFile(parcial, "w") as z:
        z.writestr("trayectoria.pos", pos)
    veredicto = motor._verificar_zip(
        parcial, {"piezas": [{"nombre": "trayectoria.pos", "epocas": EPOCAS + 1}]}
    )
    assert not veredicto.correcta and "debía traer 2001 época(s)" in veredicto.motivo
    bien = motor._verificar_zip(
        parcial, {"piezas": [{"nombre": "trayectoria.pos", "epocas": EPOCAS}]}
    )
    assert bien.correcta
    with zipfile.ZipFile(parcial, "w") as z:
        z.writestr("trayectoria.pos", "basura\n")
    assert not motor._verificar_zip(
        parcial, {"piezas": [{"nombre": "trayectoria.pos", "epocas": 1}]}
    ).correcta
