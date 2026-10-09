"""El proceso PPK con RTKLIB (F18.3).

**No hay RTKLIB en esta estación ni un vuelo real** (pedidos P15 y P16), así que aquí se prueba todo
lo que rodea a la corrida y se dice que la corrida real queda ⚠:

- la orden se compara con una lista escrita a mano desde el uso de `rnx2rtkp`;
- los RINEX son cabeceras escritas a mano, y la distancia a la base se comprueba contra una
  conversión geodésica **escrita aparte en la prueba** (no la de pyproj);
- el pegamento con el programa se prueba con un `rnx2rtkp` de mentira que **registra los argumentos
  que recibe**, y que puede salir con 0 sin escribir nada (regla 1), escribir basura o colgarse.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest import mock

import pytest
from django.test import override_settings

from apps.documents import vuelo_pos, vuelo_ppk
from apps.documents.composicion import ComposicionInvalida

# --- La geodesia, escrita aparte para no repetir al implementado ---------------------------------

A = 6_378_137.0
F = 1 / 298.257223563
E2 = F * (2 - F)


def _ecef(lat_deg: float, lon_deg: float, h: float) -> tuple[float, float, float]:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    n = A / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    return (
        (n + h) * math.cos(lat) * math.cos(lon),
        (n + h) * math.cos(lat) * math.sin(lon),
        (n * (1 - E2) + h) * math.sin(lat),
    )


BASE = vuelo_ppk.Base(-33.456789012, -70.654321098, 520.123, "SIRGAS-Chile")


# --- Los RINEX -----------------------------------------------------------------------------------


def _cabecera(tipo: str, version="3.04", xyz=None, extra="") -> str:
    nombre = "OBSERVATION DATA" if tipo == "O" else "NAVIGATION DATA"
    lineas = [f"{version:>9}           {nombre:<20}{'M: MIXED':<20}RINEX VERSION / TYPE"]
    lineas.append(f"{'REC-1':<20}{'TRIMBLE R12i':<20}{'5.50':<20}REC # / TYPE / VERS")
    if xyz is not None:
        lineas.append(f"{xyz[0]:14.4f}{xyz[1]:14.4f}{xyz[2]:14.4f}{'':18}APPROX POSITION XYZ")
    if extra:
        lineas.append(extra)
    lineas.append(f"{'':60}END OF HEADER")
    return "\n".join(lineas) + "\n"


def _rinex(carpeta: Path, nombre: str, tipo: str, **kw) -> Path:
    ruta = carpeta / nombre
    ruta.write_text(_cabecera(tipo, **kw), encoding="latin-1")
    return ruta


@pytest.fixture
def archivos(tmp_path):
    return {
        "rover": _rinex(tmp_path, "dron.obs", "O", xyz=(0.0, 0.0, 0.0)),
        "base": _rinex(tmp_path, "base.obs", "O", xyz=_ecef(-33.456789, -70.654321, 520.0)),
        "nav": _rinex(tmp_path, "efemerides.nav", "N"),
    }


class TestCabecera:
    def test_lee_version_tipo_posicion_y_receptor(self, tmp_path):
        xyz = _ecef(-33.45, -70.65, 500.0)
        c = vuelo_ppk.leer_cabecera(_rinex(tmp_path, "b.obs", "O", xyz=xyz))
        assert (c.version, c.tipo, c.receptor) == ("3.04", "O", "TRIMBLE R12i")
        assert c.posicion_aproximada == pytest.approx(xyz, abs=1e-3)

    def test_un_nav_es_de_navegacion(self, tmp_path):
        assert vuelo_ppk.leer_cabecera(_rinex(tmp_path, "n.nav", "N")).tipo == "N"

    def test_rinex_2_se_lee(self, tmp_path):
        c = vuelo_ppk.leer_cabecera(_rinex(tmp_path, "v2.obs", "O", version="2.11"))
        assert c.version == "2.11" and c.tipo == "O"

    @pytest.mark.parametrize(
        "contenido,motivo",
        [
            (b"", "está vacío"),
            (b"\x00\x01\x02binario" * 100, "binario"),
            (b"esto no es un rinex\nnada\n", "no empieza con una cabecera RINEX"),
        ],
    )
    def test_lo_que_no_es_rinex_se_rechaza_con_motivo(self, tmp_path, contenido, motivo):
        ruta = tmp_path / "x.obs"
        ruta.write_bytes(contenido)
        with pytest.raises(ComposicionInvalida, match=motivo):
            vuelo_ppk.leer_cabecera(ruta)

    def test_una_version_que_rtklib_no_lee_se_dice(self, tmp_path):
        ruta = _rinex(tmp_path, "viejo.obs", "O", version="1.00")
        with pytest.raises(ComposicionInvalida, match="RINEX 1.00"):
            vuelo_ppk.leer_cabecera(ruta)

    def test_un_archivo_que_no_existe_se_dice(self, tmp_path):
        with pytest.raises(ComposicionInvalida, match="no se pudo abrir"):
            vuelo_ppk.leer_cabecera(tmp_path / "nada.obs")


class TestLaBaseSeDeclara:
    def test_sin_sistema_no_hay_base(self):
        with pytest.raises(ComposicionInvalida, match="Falta el sistema"):
            vuelo_ppk.Base(-33.0, -70.0, 500.0, "  ")

    @pytest.mark.parametrize(
        "lat,lon,alt", [(-91, -70, 500), (-33, -181, 500), (-33, -70, 50_000), (-33, -70, -900)]
    )
    def test_coordenadas_imposibles_se_rechazan(self, lat, lon, alt):
        with pytest.raises(ComposicionInvalida):
            vuelo_ppk.Base(lat, lon, alt, "WGS84")

    def test_la_distancia_al_rinex_coincide_con_la_conversion_aparte(self, tmp_path):
        # El RINEX dice una posición a 1 m al norte de la declarada.
        declarada = vuelo_ppk.Base(-33.45, -70.65, 500.0, "SIRGAS-Chile")
        una_arriba = _ecef(-33.45, -70.65, 501.0)  # a 1 m de altura exacta
        c = vuelo_ppk.leer_cabecera(_rinex(tmp_path, "b.obs", "O", xyz=una_arriba))
        assert vuelo_ppk.distancia_a_la_base_m(c, declarada) == pytest.approx(1.0, abs=0.01)

    def test_sin_posicion_en_el_rinex_no_hay_distancia(self, tmp_path):
        c = vuelo_ppk.leer_cabecera(_rinex(tmp_path, "b.obs", "O"))
        assert vuelo_ppk.distancia_a_la_base_m(c, BASE) is None


class TestRevisar:
    def test_todo_en_orden_pasa_y_dice_la_distancia(self, archivos):
        r = vuelo_ppk.revisar(archivos["rover"], archivos["base"], [archivos["nav"]], BASE)
        assert r.distancia_base_m is not None and r.distancia_base_m < 100
        assert r.avisos == []

    def test_una_base_a_kilometros_se_rechaza_antes_de_correr(self, archivos):
        lejos = vuelo_ppk.Base(-33.40, -70.654321, 520.0, "SIRGAS-Chile")  # ~6 km al norte
        with pytest.raises(ComposicionInvalida, match=r"está a \d+\.\d km de donde dice estar"):
            vuelo_ppk.revisar(archivos["rover"], archivos["base"], [archivos["nav"]], lejos)

    def test_un_signo_cambiado_se_nota(self, archivos):
        signo = vuelo_ppk.Base(33.456789, -70.654321, 520.0, "WGS84")
        with pytest.raises(ComposicionInvalida, match="km"):
            vuelo_ppk.revisar(archivos["rover"], archivos["base"], [archivos["nav"]], signo)

    def test_una_base_sin_posicion_en_su_rinex_avisa_y_no_comprueba(self, tmp_path, archivos):
        sin = _rinex(tmp_path, "base2.obs", "O")
        r = vuelo_ppk.revisar(archivos["rover"], sin, [archivos["nav"]], BASE)
        assert r.distancia_base_m is None and "no se pudo comprobar" in r.avisos[0]

    def test_los_tipos_se_comprueban(self, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="del dron lo es"):
            vuelo_ppk.revisar(archivos["nav"], archivos["base"], [archivos["nav"]], BASE)
        with pytest.raises(ComposicionInvalida, match="de la base lo es"):
            vuelo_ppk.revisar(archivos["rover"], archivos["nav"], [archivos["nav"]], BASE)
        with pytest.raises(ComposicionInvalida, match="no es de navegación"):
            vuelo_ppk.revisar(archivos["rover"], archivos["base"], [archivos["rover"]], BASE)
        with pytest.raises(ComposicionInvalida, match="Falta el archivo de efemérides"):
            vuelo_ppk.revisar(archivos["rover"], archivos["base"], [], BASE)


class TestOrden:
    def test_la_orden_completa_escrita_a_mano(self, archivos, tmp_path):
        salida = tmp_path / "s.pos"
        orden = vuelo_ppk.construir_orden(
            "/usr/bin/rnx2rtkp",
            rover=archivos["rover"],
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            salida=salida,
            base=BASE,
        )
        assert orden == [
            "/usr/bin/rnx2rtkp",
            "-p", "2", "-m", "15", "-sys", "G,R,E,C", "-f", "2", "-v", "3", "-t", "-d", "3",
            "-l", "-33.456789012", "-70.654321098", "520.1230",
            "-o", str(salida.resolve()),
            str(archivos["rover"].resolve()),
            str(archivos["base"].resolve()),
            str(archivos["nav"].resolve()),
        ]  # fmt: skip

    def test_las_opciones_llegan_a_la_orden(self, archivos, tmp_path):
        orden = vuelo_ppk.construir_orden(
            "rnx2rtkp",
            rover=archivos["rover"],
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            salida=tmp_path / "s.pos",
            base=BASE,
            opciones=vuelo_ppk.Opciones(
                modo="estatico",
                mascara_elevacion_deg=10,
                sistemas="g, e",
                frecuencias=1,
                umbral_ambiguedad=2.5,
                intervalo_s=1,
                combinada=True,
            ),
        )
        assert orden[orden.index("-p") + 1] == "3"
        assert orden[orden.index("-m") + 1] == "10"
        assert orden[orden.index("-sys") + 1] == "G,E"
        assert orden[orden.index("-f") + 1] == "1"
        assert orden[orden.index("-v") + 1] == "2.5"
        assert orden[orden.index("-ti") + 1] == "1" and "-c" in orden

    def test_una_ruta_que_empieza_por_guion_sale_absoluta(self, tmp_path, archivos):
        raro = tmp_path / "-rover.obs"
        raro.write_text(archivos["rover"].read_text(encoding="latin-1"), encoding="latin-1")
        orden = vuelo_ppk.construir_orden(
            "rnx2rtkp",
            rover=raro,
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            salida=tmp_path / "s.pos",
            base=BASE,
        )
        assert str(raro.resolve()) in orden
        assert not any(a == "-rover.obs" for a in orden)

    @pytest.mark.parametrize(
        "malo",
        [
            {"modo": "volando"},
            {"mascara_elevacion_deg": 90},
            {"frecuencias": 4},
            {"umbral_ambiguedad": -1},
            {"intervalo_s": 0.001},
            {"sistemas": "G,X"},
            {"sistemas": ""},
        ],
    )
    def test_las_opciones_invalidas_se_rechazan(self, archivos, tmp_path, malo):
        with pytest.raises(ComposicionInvalida):
            vuelo_ppk.construir_orden(
                "rnx2rtkp",
                rover=archivos["rover"],
                base_obs=archivos["base"],
                navegacion=[archivos["nav"]],
                salida=tmp_path / "s.pos",
                base=BASE,
                opciones=vuelo_ppk.Opciones(**malo),
            )


# --- El pegamento, con un rnx2rtkp de mentira ----------------------------------------------------

FALSO = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path

    config = json.loads(Path(__file__).with_name("falso.json").read_text())
    args = sys.argv[1:]
    Path(__file__).with_name("recibido.json").write_text(json.dumps(args))
    salida = args[args.index("-o") + 1]
    if config.get("pid_en"):
        import os
        Path(config["pid_en"]).write_text(str(os.getpid()), encoding="utf-8")
    if config.get("duerme"):
        time.sleep(config["duerme"])
    for linea in config.get("progreso", []):
        # Como RTKLIB: una línea por época, separadas por retorno de carro y sin salto de línea.
        sys.stderr.write(linea + chr(13))
        sys.stderr.flush()
    if config.get("mensaje"):
        print(config["mensaje"], file=sys.stderr)
    if config.get("escribe") is not None:
        Path(salida).write_text(config["escribe"], encoding="utf-8")
    sys.exit(config.get("codigo", 0))
    """
)

CABECERA_POS = (
    "% program   : RTKPOST ver.2.4.3\n"
    "%  GPST                  latitude(deg) longitude(deg)  height(m)   Q  ns   sdn(m)   sde(m)  "
    "sdu(m)  sdne(m)  sdeu(m)  sdun(m) age(s)  ratio\n"
)


def _pos(calidades) -> str:
    return CABECERA_POS + "".join(
        f"2026/10/08 12:00:{i * 0.2:06.3f} -33.450000000 -70.650000000 520.0000 {q:3d}  12 "
        "0.0020 0.0020 0.0040 0.0000 0.0000 0.0000 0.00 99.9\n"
        for i, q in enumerate(calidades)
    )


@pytest.fixture
def falso(tmp_path):
    carpeta = tmp_path / "rtklib"
    carpeta.mkdir()
    (carpeta / "falso.py").write_text(FALSO, encoding="utf-8")

    def configurar(**config):
        (carpeta / "falso.json").write_text(json.dumps(config), encoding="utf-8")
        return [sys.executable, str(carpeta / "falso.py")]

    configurar.carpeta = carpeta
    return configurar


class TestCorrer:
    def _correr(self, programa, archivos, tmp_path, **kw):
        return vuelo_ppk.correr(
            programa,
            rover=archivos["rover"],
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            destino=tmp_path / "salida.pos",
            base=BASE,
            **kw,
        )

    def test_lo_que_devuelve_es_lo_que_se_leyo_del_pos(self, falso, archivos, tmp_path):
        programa = falso(escribe=_pos([1, 1, 1, 2, 5]), mensaje="processing...")
        r = self._correr(programa, archivos, tmp_path)
        assert r.trayectoria.n == 5 and r.porcentaje_fijo == pytest.approx(60.0)
        assert (tmp_path / "salida.pos").read_text(encoding="utf-8") == _pos([1, 1, 1, 2, 5])
        assert r.mensajes == ["processing..."]

    def test_rtklib_recibe_exactamente_la_orden_armada(self, falso, archivos, tmp_path):
        programa = falso(escribe=_pos([1]))
        self._correr(programa, archivos, tmp_path)
        recibido = json.loads((falso.carpeta / "recibido.json").read_text())
        assert recibido[:4] == ["-p", "2", "-m", "15"]
        assert recibido[recibido.index("-l") + 1 : recibido.index("-l") + 4] == [
            "-33.456789012", "-70.654321098", "520.1230",
        ]  # fmt: skip
        assert recibido[-3:] == [
            str(archivos["rover"].resolve()),
            str(archivos["base"].resolve()),
            str(archivos["nav"].resolve()),
        ]

    def test_salir_con_cero_sin_escribir_nada_es_un_fallo_y_dice_lo_que_dijo_rtklib(
        self, falso, archivos, tmp_path
    ):
        programa = falso(codigo=0, mensaje="error: no common satellites")
        with pytest.raises(ComposicionInvalida, match="no escribió ninguna posición") as e:
            self._correr(programa, archivos, tmp_path)
        assert "no common satellites" in str(e.value)
        assert not (tmp_path / "salida.pos").exists()

    def test_un_pos_vacio_tampoco_vale(self, falso, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="no escribió ninguna posición"):
            self._correr(falso(escribe=""), archivos, tmp_path)

    def test_basura_en_lugar_de_un_pos_se_rechaza(self, falso, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="no parece un .pos"):
            self._correr(falso(escribe="hola\nmundo\n"), archivos, tmp_path)
        assert not (tmp_path / "salida.pos").exists()

    def test_un_pos_sin_posiciones_se_rechaza(self, falso, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="ninguna posición legible"):
            self._correr(falso(escribe=CABECERA_POS), archivos, tmp_path)

    def test_un_pos_en_ecef_se_rechaza(self, falso, archivos, tmp_path):
        ecef = CABECERA_POS.replace("latitude(deg) longitude(deg)", "x-ecef(m) y-ecef(m)")
        with pytest.raises(ComposicionInvalida, match="ECEF"):
            self._correr(falso(escribe=ecef + _pos([1])[len(CABECERA_POS) :]), archivos, tmp_path)

    def test_si_se_cuelga_se_detiene_y_lo_dice(self, falso, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="tardó más de"):
            self._correr(falso(duerme=30), archivos, tmp_path, plazo_s=1)

    def test_un_programa_que_no_existe_se_dice(self, archivos, tmp_path):
        with pytest.raises(ComposicionInvalida, match="No se pudo lanzar RTKLIB"):
            self._correr(str(tmp_path / "no_existe"), archivos, tmp_path)

    def test_los_rinex_se_revisan_antes_de_lanzar(self, falso, archivos, tmp_path):
        lejos = vuelo_ppk.Base(-33.40, -70.654321, 520.0, "SIRGAS-Chile")
        with pytest.raises(ComposicionInvalida, match="km"):
            vuelo_ppk.correr(
                falso(escribe=_pos([1])),
                rover=archivos["rover"],
                base_obs=archivos["base"],
                navegacion=[archivos["nav"]],
                destino=tmp_path / "s.pos",
                base=lejos,
            )
        assert not (falso.carpeta / "recibido.json").exists(), "ni se lanzó RTKLIB"

    def test_los_originales_no_se_tocan(self, falso, archivos, tmp_path):
        import hashlib

        def huella():
            return {
                k: (hashlib.sha256(v.read_bytes()).hexdigest(), v.stat().st_mtime_ns)
                for k, v in archivos.items()
            }

        antes = huella()
        self._correr(falso(escribe=_pos([1, 1])), archivos, tmp_path)
        with pytest.raises(ComposicionInvalida):
            self._correr(falso(escribe="basura\n"), archivos, tmp_path)
        assert huella() == antes


def _con_horas(carpeta: Path, nombre: str, primera: str, ultima: str | None) -> Path:
    """Un RINEX del dron con `TIME OF FIRST OBS` y, si se pide, `TIME OF LAST OBS`."""

    def linea(hora: str, etiqueta: str) -> str:
        y, mo, d, h, mi, s = hora.split()
        campos = f"{int(y):6d}{int(mo):6d}{int(d):6d}{int(h):6d}{int(mi):6d}{float(s):13.7f}"
        return (campos + "     GPS").ljust(60) + etiqueta

    extra = linea(primera, "TIME OF FIRST OBS")
    if ultima:
        extra += "\n" + linea(ultima, "TIME OF LAST OBS")
    return _rinex(carpeta, nombre, "O", xyz=(0.0, 0.0, 0.0), extra=extra)


def _avance(minuto_s: list[tuple[int, int]]) -> list[str]:
    return [f"processing : 2025/12/29 15:{m:02d}:{s:02d}.0 Q=1 ns=14" for m, s in minuto_s]


class TestElAvanceLeidoDeRtklib:
    """`rnx2rtkp` dice dónde va en stderr; con la primera y la última observación sale la barra."""

    def test_la_cabecera_trae_la_primera_y_la_ultima_observacion(self, tmp_path):
        ruta = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", "2025 12 29 15 50 30")
        c = vuelo_ppk.leer_cabecera(ruta)
        assert c.desde.isoformat() == "2025-12-29T15:40:00"
        assert c.hasta.isoformat() == "2025-12-29T15:50:30"

    def test_sin_hora_de_fin_la_cabecera_no_la_inventa(self, tmp_path):
        c = vuelo_ppk.leer_cabecera(_con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", None))
        assert c.hasta is None and c.ultima_observacion == ""

    def test_las_fracciones_crecen_y_van_de_cero_a_uno(self, falso, archivos, tmp_path):
        rover = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", "2025 12 29 15 50 0")
        # Los minutos 40 a 50 son diez minutos: cada 30 s es el 5 %. Una época repetida no suma.
        horas = [(40 + s // 60, s % 60) for s in range(0, 601, 30)]
        programa = falso(escribe=_pos([1, 1]), progreso=_avance(horas + [horas[-1]]))
        avances: list[tuple[float | None, str]] = []
        vuelo_ppk.correr(
            programa,
            rover=rover,
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            destino=tmp_path / "s.pos",
            base=BASE,
            progreso=lambda f, e: avances.append((f, e)),
        )
        fracciones = [f for f, _ in avances]
        assert fracciones and None not in fracciones
        assert fracciones == sorted(fracciones) and len(set(fracciones)) == len(fracciones)
        assert fracciones[0] == pytest.approx(0.0, abs=1e-9) and fracciones[-1] == pytest.approx(
            1.0
        )
        assert 0.49 < fracciones[len(fracciones) // 2] < 0.56  # hacia la mitad, a las 15:45
        assert all("RTKLIB va en 2025-12-29 15:" in e and "GPST" in e for _, e in avances)
        assert "fija" in avances[0][1]

    def test_sin_hora_de_fin_solo_va_la_etiqueta(self, falso, archivos, tmp_path):
        rover = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", None)
        programa = falso(escribe=_pos([1]), progreso=_avance([(41, 0), (42, 0)]))
        avances = []
        vuelo_ppk.correr(
            programa,
            rover=rover,
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            destino=tmp_path / "s.pos",
            base=BASE,
            progreso=lambda f, e: avances.append((f, e)),
        )
        assert [f for f, _ in avances] == [None, None]
        assert avances[-1][1].startswith("RTKLIB va en 2025-12-29 15:42:00")

    def test_la_barra_no_ensucia_los_mensajes_de_error(self, falso, archivos, tmp_path):
        rover = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", "2025 12 29 15 50 0")
        programa = falso(
            codigo=0, progreso=_avance([(41, 0), (42, 0)]), mensaje="error: no common satellites"
        )
        with pytest.raises(ComposicionInvalida, match="no escribió ninguna posición") as e:
            vuelo_ppk.correr(
                programa,
                rover=rover,
                base_obs=archivos["base"],
                navegacion=[archivos["nav"]],
                destino=tmp_path / "s.pos",
                base=BASE,
            )
        assert "no common satellites" in str(e.value) and "processing" not in str(e.value)


def _proceso_vivo(pid: int) -> bool:
    if sys.platform == "win32":
        salida = subprocess.run(  # nosec B603 B607 - prueba, orden fija
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        ).stdout
        return str(pid) in salida
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _esperar_a_que_muera(pid: int, hasta_s: float = 10.0) -> bool:
    limite = time.monotonic() + hasta_s
    while time.monotonic() < limite:
        if not _proceso_vivo(pid):
            return True
        time.sleep(0.1)
    return not _proceso_vivo(pid)


class TestElAvanceNoTumbaAlCalculo:
    """El hilo lector solo vacía el pipe: un avance mal formado o un `progreso` roto no bloquean a
    RTKLIB hasta el plazo."""

    def _correr(self, programa, archivos, tmp_path, **kw):
        rover = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", "2025 12 29 15 50 0")
        inicio = time.monotonic()
        resultado = vuelo_ppk.correr(
            programa,
            rover=rover,
            base_obs=archivos["base"],
            navegacion=[archivos["nav"]],
            destino=tmp_path / "s.pos",
            base=BASE,
            plazo_s=30,
            **kw,
        )
        return resultado, time.monotonic() - inicio

    def test_un_segundo_intercalar_en_la_hora_se_descarta_sin_matar_al_lector(
        self, falso, archivos, tmp_path
    ):
        # `15:59:60` no es una hora para `datetime`; las líneas buenas de después siguen llegando,
        # y se llenan más de los 64 KiB del pipe para que un lector muerto bloquearía a RTKLIB.
        malas = ["processing : 2025/12/29 15:59:60.0 Q=1 ns=14"]
        buenas = _avance([(41, 0), (45, 0), (49, 0)])
        relleno = ["x" * 200] * 600
        programa = falso(escribe=_pos([1]), progreso=malas + relleno + buenas)
        avances = []
        resultado, duracion = self._correr(
            programa, archivos, tmp_path, progreso=lambda f, e: avances.append(f)
        )
        assert resultado.trayectoria.n == 1 and duracion < 20
        assert len(avances) == 3 and avances == sorted(avances)

    def test_un_progreso_que_lanza_no_detiene_el_calculo(self, falso, archivos, tmp_path):
        programa = falso(escribe=_pos([1, 1]), progreso=_avance([(41, 0), (45, 0)]) * 50)
        llamadas = []

        def roto(fraccion, etiqueta):
            llamadas.append(fraccion)
            raise RuntimeError("la barra se rompió")

        resultado, duracion = self._correr(programa, archivos, tmp_path, progreso=roto)
        assert resultado.trayectoria.n == 2 and duracion < 20
        assert len(llamadas) == 1, "tras fallar una vez, no se vuelve a llamar"

    def test_una_linea_sin_fin_no_crece_sin_tope(self, falso, archivos, tmp_path):
        programa = falso(escribe=_pos([1]), progreso=["y" * 300_000])
        resultado, _d = self._correr(programa, archivos, tmp_path)
        assert resultado.trayectoria.n == 1


class TestLoQueSeCuelgaSeMataConSuDescendencia:
    def test_pasado_el_plazo_el_proceso_ya_no_existe(self, falso, archivos, tmp_path):
        pid_en = tmp_path / "pid.txt"
        programa = falso(duerme=60, pid_en=str(pid_en))
        with pytest.raises(ComposicionInvalida, match="tardó más de"):
            vuelo_ppk.correr(
                programa,
                rover=archivos["rover"],
                base_obs=archivos["base"],
                navegacion=[archivos["nav"]],
                destino=tmp_path / "s.pos",
                base=BASE,
                plazo_s=2,
            )
        assert _esperar_a_que_muera(int(pid_en.read_text()))

    def test_si_quien_llama_se_interrumpe_no_queda_huerfano(self, falso, archivos, tmp_path):
        pid_en = tmp_path / "pid.txt"
        programa = falso(duerme=60, pid_en=str(pid_en))

        def interrumpe(fraccion, etiqueta):
            raise KeyboardInterrupt

        rover = _con_horas(tmp_path, "d.obs", "2025 12 29 15 40 0", "2025 12 29 15 50 0")
        # La interrupción llega con el programa vivo: el `finally` de `correr` lo mata.
        original = vuelo_ppk._Avisador.entregar

        def entregar_y_cortar(self, avances):
            if pid_en.exists():
                raise KeyboardInterrupt
            original(self, avances)

        with mock.patch.object(vuelo_ppk._Avisador, "entregar", entregar_y_cortar):
            with pytest.raises(KeyboardInterrupt):
                vuelo_ppk.correr(
                    programa,
                    rover=rover,
                    base_obs=archivos["base"],
                    navegacion=[archivos["nav"]],
                    destino=tmp_path / "s.pos",
                    base=BASE,
                    plazo_s=30,
                    progreso=interrumpe,
                )
        assert _esperar_a_que_muera(int(pid_en.read_text()))


class TestSonda:
    def test_sin_rnx2rtkp_dice_que_falta_y_como_ponerlo(self):
        with override_settings(RTKLIB_RNX2RTKP="", RTKLIB_CONVBIN=""):
            from unittest import mock

            with mock.patch("shutil.which", return_value=None):
                estado = vuelo_ppk.sondar()
        assert not estado and "sudo apt install rtklib" in estado.sugerencia

    def test_una_ruta_configurada_que_no_existe_se_dice(self, tmp_path):
        with override_settings(RTKLIB_RNX2RTKP=str(tmp_path / "nada")):
            estado = vuelo_ppk.sondar()
        assert not estado and "ahí no hay ningún archivo" in estado.motivo

    def test_una_ruta_configurada_que_existe_se_acepta_sin_ejecutarla(self, tmp_path):
        programa = tmp_path / "rnx2rtkp"
        programa.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        with override_settings(RTKLIB_RNX2RTKP=str(programa)):
            assert vuelo_ppk.sondar().programa == str(programa)

    def test_se_busca_junto_a_convbin(self, tmp_path):
        (tmp_path / "convbin").write_text("x", encoding="utf-8")
        (tmp_path / "rnx2rtkp").write_text("x", encoding="utf-8")
        with override_settings(RTKLIB_RNX2RTKP="", RTKLIB_CONVBIN=str(tmp_path / "convbin")):
            assert vuelo_ppk.ruta_de_rnx2rtkp() == str(tmp_path / "rnx2rtkp")


def test_el_pos_del_resultado_lo_lee_vuelo_pos():
    assert vuelo_pos.leer(_pos([1, 2])).n == 2
