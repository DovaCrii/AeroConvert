"""Recorte de una nube por un polígono (F21.3).

Sin PDAL corre el plan, las paradas por CRS y el veredicto. Con PDAL (`@pytest.mark.oraculo`), una
nube **sintética de resultado conocido**: una rejilla de 20 × 20 puntos en enteros
(`x = 495000 + i`, `y = 7318000 + j`, `z = i + j`). Cuántos puntos caen dentro de un polígono de
bordes en medios enteros es una cuenta, y `pdal info --summary` (otro lector que el que escribió la
salida) la confirma.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry
from apps.engines.base import ParDeFormatos, PlanNoValido
from apps.jobs import runner
from apps.jobs.models import ConversionJob
from apps.pointcloud import motores as nube
from apps.pointcloud import recorte
from apps.pointcloud.recorte import MotorRecorteNube

pytestmark = pytest.mark.django_db

UTM19S = 32719
# Bordes en medios enteros: dentro quedan x = 495005…495010 (6) e y = 7318003…7318006 (4).
RECTANGULO = "495004.5 7318002.5; 495010.5 7318002.5; 495010.5 7318006.5; 495004.5 7318006.5"
OPCIONES = {"operacion": "recorte", "recorte_vertices": RECTANGULO, "recorte_crs": f"EPSG:{UTM19S}"}


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _huella(ruta: Path):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _trabajo(usuario, tmp_path, destino="laz", origen="laz", crs=str(UTM19S), **opciones):
    ruta = tmp_path / "nube.laz"
    if not ruta.exists():
        ruta.write_bytes(b"LASF" + bytes(300))
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(ruta),
        source_name=ruta.name,
        source_size_bytes=ruta.stat().st_size,
        source_format_code=origen,
        source_crs_authority="EPSG" if crs else "",
        source_crs_code=crs,
        target_format_code=destino,
        output_path=str(tmp_path / f"recorte.{destino}"),
        options={**OPCIONES, **opciones},
    )


class TestElPlan:
    def test_es_pdal_translate_con_filters_crop_y_el_poligono_en_wkt(self, usuario, tmp_path):
        plan = MotorRecorteNube().plan(_trabajo(usuario, tmp_path))
        argv = plan.argv
        assert "pdal" in argv[0] and argv[1] == "translate"
        assert argv[argv.index("crop") - 0] == "crop"
        poligono = next(a for a in argv if a.startswith("--filters.crop.polygon="))
        assert poligono == (
            "--filters.crop.polygon=POLYGON((495004.5 7318002.5, 495010.5 7318002.5, "
            "495010.5 7318006.5, 495004.5 7318006.5, 495004.5 7318002.5))"
        )
        assert argv[argv.index("-w") + 1] == "writers.las"
        assert "--writers.las.compression=laszip" in argv
        assert ".parcial" in argv[3]
        assert plan.emite_progreso is False

    def test_copc_pasa_el_nombre_del_escritor_que_toca(self, usuario, tmp_path):
        argv = MotorRecorteNube().plan(_trabajo(usuario, tmp_path, destino="copc")).argv
        assert argv[argv.index("-w") + 1] == "writers.copc"
        assert "--writers.copc.forward=all" in argv
        assert not any("writers.las" in a for a in argv)

    def test_si_el_poligono_esta_en_otro_sistema_se_lleva_al_de_la_nube(self, usuario, tmp_path):
        from pyproj import Transformer

        a_grados = Transformer.from_crs(UTM19S, 4326, always_xy=True)
        pares = [
            a_grados.transform(*p)
            for p in ((495004.5, 7318002.5), (495010.5, 7318002.5), (495010.5, 7318006.5))
        ]
        texto = "; ".join(f"{x!r} {y!r}" for x, y in pares)
        trabajo = _trabajo(usuario, tmp_path, recorte_vertices=texto, recorte_crs="EPSG:4326")
        wkt = next(
            a
            for a in MotorRecorteNube().plan(trabajo).argv
            if a.startswith("--filters.crop.polygon=")
        )
        numeros = [float(n) for n in wkt.split("((")[1].rstrip(")").replace(",", " ").split()]
        # Vuelven a metros UTM (6 dígitos de este, 7 de norte), no se quedan en grados.
        assert numeros[0] == pytest.approx(495004.5, abs=1e-3)
        assert numeros[1] == pytest.approx(7318002.5, abs=1e-3)

    def test_es_un_proceso_que_la_conversion_no_ve(self):
        par = ParDeFormatos("laz", "laz")
        assert registry.motores_para(par) == ()  # laz → laz no es una conversión
        assert {m.id for m in registry.motores_para(par, "recorte")} == {"pdal-recorte"}
        assert registry.matriz_de_capacidades().get(("laz", "laz")) is None
        assert registry.matriz_de_capacidades()[("laz", "las")].motor_id == "pdal-nubes"


class TestSeDetiene:
    CASOS = [
        pytest.param({"recorte_crs": ""}, {}, "crs-ausente", id="poligono-sin-crs"),
        pytest.param({"recorte_crs": "EPSG:999999"}, {}, "crs-invalido", id="crs-falso"),
        pytest.param({}, {"crs": ""}, "crs-ausente", id="nube-sin-crs"),
        pytest.param({"recorte_vertices": ""}, {}, "error-del-motor", id="sin-poligono"),
        pytest.param({"recorte_vertices": "0 0; 1 1"}, {}, "error-del-motor", id="dos-vertices"),
        pytest.param({"recorte_vertices": "0 0; 1 1; 2 2"}, {}, "error-del-motor", id="sin-area"),
    ]

    @pytest.mark.parametrize(("opciones", "extra", "codigo"), CASOS)
    def test_cada_parada_lleva_su_codigo_y_el_original_no_se_toca(
        self, usuario, tmp_path, opciones, extra, codigo
    ):
        original = tmp_path / "nube.laz"
        original.write_bytes(b"LASF" + bytes(range(200)))
        os.utime(original, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        antes = _huella(original)
        trabajo = _trabajo(usuario, tmp_path, **extra, **opciones)
        with pytest.raises(PlanNoValido) as fallo:
            MotorRecorteNube().plan(trabajo)
        assert fallo.value.codigo == codigo
        assert _huella(original) == antes
        assert not list(tmp_path.glob("*.parcial*"))


class TestElVeredicto:
    def _verificar(self, monkeypatch, usuario, tmp_path, resumen, origen_puntos=400):
        monkeypatch.setattr(recorte, "_pdal_info", lambda ruta: resumen)
        monkeypatch.setattr(recorte, "_puntos_de_origen", lambda trabajo: origen_puntos)
        salida = tmp_path / "recorte.laz"
        salida.write_bytes(b"x" * 20)
        return MotorRecorteNube().verificar(_trabajo(usuario, tmp_path), salida)

    @staticmethod
    def _resumen(puntos=24, **limites):
        base = {"minx": 495005, "maxx": 495010, "miny": 7318003, "maxy": 7318006}
        return {"num_points": puntos, "bounds": {**base, **limites}}

    def test_con_puntos_dentro_pasa(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._resumen())
        assert v.correcta, v.motivo
        assert v.detalles["puntos"] == 24 and v.detalles["puntos_origen"] == 400

    def test_sin_un_punto_es_recorte_vacio_aunque_pdal_haya_salido_con_cero(
        self, monkeypatch, usuario, tmp_path
    ):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._resumen(puntos=0))
        assert not v.correcta and v.codigo_motivo == "recorte-vacio"

    def test_mas_puntos_que_el_original_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._resumen(puntos=500))
        assert not v.correcta and v.codigo_motivo == "salida-invalida"

    def test_un_punto_fuera_de_la_caja_del_poligono_no_se_entrega(
        self, monkeypatch, usuario, tmp_path
    ):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._resumen(maxx=495020))
        assert not v.correcta and "fuera de la caja" in v.motivo

    def test_una_nube_que_pdal_no_lee_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, None)
        assert not v.correcta and v.codigo_motivo == "salida-invalida"


class TestLaDisponibilidad:
    def test_sin_el_filtro_se_apaga_con_motivo_y_alternativa(self, monkeypatch):
        from apps.engines import sondas
        from apps.engines.base import Disponibilidad

        pedidos = []

        def sonda(nombre):
            pedidos.append(nombre)
            return Disponibilidad.no("sin-driver-pdal", f"Este PDAL no trae {nombre}.")

        monkeypatch.setattr(sondas, "sondar_pdal_controlador", sonda)
        estado = MotorRecorteNube().disponibilidad()
        assert not estado.disponible and estado.codigo_motivo == "sin-driver-pdal"
        assert pedidos == ["filters.crop"]
        celda = registry.celda(ParDeFormatos("laz", "laz"), "recorte")
        assert celda.codigo_motivo == "sin-driver-pdal"

    def test_con_el_filtro_se_enciende(self, monkeypatch):
        from apps.engines import sondas
        from apps.engines.base import Disponibilidad

        monkeypatch.setattr(
            sondas, "sondar_pdal_controlador", lambda nombre: Disponibilidad.si("pdal 2.10")
        )
        estado = MotorRecorteNube().disponibilidad()
        assert estado.disponible and estado.version == "pdal 2.10"
        assert registry.motor_para(ParDeFormatos("laz", "laz"), "recorte").id == "pdal-recorte"

    def test_motivos_y_pasos_existen(self):
        from apps.engines import equipo
        from apps.jobs import motivos

        assert "sin-driver-pdal" in motivos.MOTIVOS and "recorte-vacio" in motivos.MOTIVOS
        assert "motor-no-disponible" in equipo.PASOS


# --- Contra PDAL de verdad -----------------------------------------------------------------

sin_pdal = pytest.mark.skipif(
    shutil.which("pdal") is None
    and not Path(r"C:\Program Files\QGIS 4.0.2\bin\pdal.exe").exists()
    and not os.environ.get("AEROCONVERT_PDAL_BIN"),
    reason="PDAL no esta en esta maquina",
)

LADO = 20
ESTE0, NORTE0 = 495000, 7318000


def _pdal(*argumentos) -> str:
    resultado = subprocess.run(  # noqa: S603 - argumentos fijos; el programa es de PDAL
        [nube._bin(), *argumentos], check=True, capture_output=True, text=True, timeout=300
    )
    return resultado.stdout


def _resumen(ruta: Path) -> dict:
    """El oráculo: `pdal info --summary`, otro programa que el que recortó."""
    return json.loads(_pdal("info", "--summary", str(ruta)))["summary"]


def _nube_sintetica(tmp_path: Path, nombre="nube", srs=f"EPSG:{UTM19S}") -> Path:
    texto = tmp_path / f"{nombre}.txt"
    filas = ["X,Y,Z"] + [
        f"{ESTE0 + i},{NORTE0 + j},{i + j}" for i in range(LADO) for j in range(LADO)
    ]
    texto.write_text("\n".join(filas) + "\n", newline="\n")
    laz = tmp_path / f"{nombre}.laz"
    argumentos = ["translate", str(texto), str(laz), "--writers.las.compression=laszip"]
    if srs:
        argumentos += [f"--writers.las.a_srs={srs}"]
    _pdal(*argumentos)
    texto.unlink()
    return laz


@pytest.mark.oraculo
@sin_pdal
class TestContraPdalDeVerdad:
    def _recortar(self, usuario, tmp_path, origen, destino="laz", crs=str(UTM19S), **opciones):
        registry.limpiar()
        nube.registrar_todos()
        trabajo = _trabajo(usuario, tmp_path, destino=destino, crs=crs, **opciones)
        trabajo.source_path = str(origen)
        trabajo.source_name = origen.name
        trabajo.save()
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        return resultado, trabajo

    def test_el_oraculo_ve_la_nube_sintetica_entera(self, tmp_path):
        assert _resumen(_nube_sintetica(tmp_path))["num_points"] == LADO * LADO

    def test_un_rectangulo_deja_los_puntos_de_dentro_y_solo_esos(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path)
        antes = _huella(origen)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen)
        assert resultado.estado == "done", trabajo.reason_detail

        resumen = _resumen(Path(trabajo.output_path))
        assert resumen["num_points"] == 6 * 4  # x = 495005…495010, y = 7318003…7318006
        caja = resumen["bounds"]
        assert (caja["minx"], caja["maxx"]) == (495005, 495010)
        assert (caja["miny"], caja["maxy"]) == (7318003, 7318006)
        assert (caja["minz"], caja["maxz"]) == (5 + 3, 10 + 6)
        assert "32719" in json.dumps(resumen["srs"])  # la nube recortada conserva su sistema
        assert _huella(origen) == antes
        assert not list(tmp_path.glob("*.parcial*"))

    def test_un_triangulo_cuenta_los_puntos_que_la_cuenta_dice(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path)
        # Triángulo con la hipotenusa en i + j = 9,5 y los catetos en -0,5: entra el punto (i, j)
        # si i + j <= 9, y con i, j >= 0 son 55. Ninguno cae sobre un borde.
        norte, este = NORTE0, ESTE0
        triangulo = f"{este - 0.5} {norte - 0.5}; {este + 10.0} {norte - 0.5}; "
        triangulo += f"{este - 0.5} {norte + 10.0}"
        esperados = sum(1 for i in range(LADO) for j in range(LADO) if i + j <= 9)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_vertices=triangulo)
        assert resultado.estado == "done", trabajo.reason_detail
        assert _resumen(Path(trabajo.output_path))["num_points"] == esperados

    def test_el_mismo_poligono_dado_en_grados_recorta_lo_mismo(self, usuario, tmp_path):
        from pyproj import Transformer

        origen = _nube_sintetica(tmp_path)
        a_grados = Transformer.from_crs(UTM19S, 4326, always_xy=True)
        esquinas = ((495004.5, 7318002.5), (495010.5, 7318002.5), (495010.5, 7318006.5))
        texto = "; ".join("{!r} {!r}".format(*a_grados.transform(*p)) for p in esquinas)
        resultado, trabajo = self._recortar(
            usuario,
            tmp_path,
            origen,
            recorte_vertices=texto
            + "; "
            + "{!r} {!r}".format(*a_grados.transform(495004.5, 7318006.5)),
            recorte_crs="EPSG:4326",
        )
        assert resultado.estado == "done", trabajo.reason_detail
        assert _resumen(Path(trabajo.output_path))["num_points"] == 24

    def test_a_copc_tambien(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, destino="copc")
        assert resultado.estado == "done", trabajo.reason_detail
        assert _resumen(Path(trabajo.output_path))["num_points"] == 24

    def test_un_poligono_que_cae_en_otro_sitio_se_para_sin_dejar_salida(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path)
        antes = _huella(origen)
        resultado, trabajo = self._recortar(
            usuario, tmp_path, origen, recorte_vertices="0 0; 10 0; 10 10"
        )
        assert resultado.estado == "error" and trabajo.reason_code == "recorte-vacio"
        assert _huella(origen) == antes
        assert not (tmp_path / "recorte.laz").exists() and not list(tmp_path.glob("*.parcial*"))

    def test_una_nube_sin_crs_se_para_y_no_se_adivina(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path, nombre="sin_crs", srs="")
        antes = _huella(origen)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, crs="")
        assert resultado.estado == "error" and trabajo.reason_code == "crs-ausente"
        assert _huella(origen) == antes
        assert not (tmp_path / "recorte.laz").exists()

    def test_sin_crs_del_poligono_se_para(self, usuario, tmp_path):
        origen = _nube_sintetica(tmp_path)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_crs="")
        assert resultado.estado == "error" and trabajo.reason_code == "crs-ausente"


def test_el_modulo_declara_lo_que_dice():
    assert recorte.RECORTE == "recorte"
    assert MotorRecorteNube().operacion == "recorte"
    assert SimpleNamespace  # evita que el linter quite la importación usada en pruebas futuras
