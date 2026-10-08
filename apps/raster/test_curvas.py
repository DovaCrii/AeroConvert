"""Curvas de nivel desde un modelo de elevación (F15.6).

Casi todo corre **sin GDAL**: lo que se comprueba es el plan (el `argv` que se lanzaría) y el
veredicto sobre lo que OGR diría. Al final, las pruebas `@pytest.mark.oraculo` sí convierten de
verdad, con un **cono de fórmula conocida**: `z = 100 − 0,5·r`. La curva de cota `L` es entonces una
x, y eso es un oráculo que no es GDAL: se calcula, no se lee.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.engines.base import ParDeFormatos, ruta_parcial
from apps.jobs.models import ConversionJob
from apps.raster import motores as raster
from apps.raster.motores import MotorCurvasDeNivel

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _trabajo(usuario, tmp_path, destino="gpkg", origen="geotiff", **extra):
    ruta = tmp_path / ("modelo.asc" if origen == "asc" else "modelo.tif")
    if not ruta.exists():
        ruta.write_bytes(b"ncols 2\nnrows 2\n" if origen == "asc" else b"II*\x00")
    campos = {
        "owner": usuario,
        "source_path": str(ruta),
        "source_name": ruta.name,
        "source_size_bytes": 1_000_000,
        "source_format_code": origen,
        "source_crs_authority": "EPSG",
        "source_crs_code": "32719",
        "target_format_code": destino,
        "output_path": str(tmp_path / f"curvas.{destino}"),
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


def _valor(argv, bandera):
    return argv[argv.index(bandera) + 1]


class TestElPlan:
    def test_el_comando_es_gdal_contour_con_origen_y_parcial_al_final(self, usuario, tmp_path):
        plan = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path))
        assert "gdal_contour" in plan.argv[0]
        assert plan.argv[-2] == str(tmp_path / "modelo.tif")
        assert plan.argv[-1] == str(ruta_parcial(tmp_path / "curvas.gpkg"))
        assert plan.argv[-1].endswith(".gpkg") and ".parcial." in plan.argv[-1]

    @pytest.mark.parametrize(
        "destino,controlador",
        [("shp", "ESRI Shapefile"), ("gpkg", "GPKG")],
    )
    def test_cada_destino_pide_su_controlador(self, usuario, tmp_path, destino, controlador):
        argv = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, destino)).argv
        assert _valor(argv, "-f") == controlador

    def test_solo_el_dxf_sale_en_3d(self, usuario, tmp_path):
        """Un DXF de curvas planas es un dibujo de líneas sin altura; en SHP y GPKG la cota va en
        el campo `ELEV`."""
        for destino in ("shp", "gpkg"):
            argv = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, destino)).argv
            assert "-3d" not in argv and _valor(argv, "-a") == "ELEV"
        assert "-3d" in MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, "dxf")).argv

    def test_el_dxf_pasa_por_un_geopackage_3d_porque_directo_pierde_la_cota(
        self, usuario, tmp_path
    ):
        """Medido: `gdal_contour -f DXF -3d` escribe polilíneas sin elevación."""
        plan = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, "dxf"))
        parcial = ruta_parcial(tmp_path / "curvas.dxf")
        assert _valor(plan.argv, "-f") == "GPKG"
        assert plan.argv[-1] == str(parcial) + ".curvas3d.gpkg"
        (paso,) = plan.posteriores
        assert "ogr2ogr" in paso[0] and _valor(paso, "-f") == "DXF"
        assert paso[-2:] == (str(parcial), plan.argv[-1])
        assert plan.salida_en_posteriores

    def test_los_otros_destinos_escriben_directo(self, usuario, tmp_path):
        plan = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, "gpkg"))
        assert not plan.posteriores and not plan.salida_en_posteriores

    def test_el_intervalo_y_la_cota_de_partida_llegan_al_comando(self, usuario, tmp_path):
        trabajo = _trabajo(usuario, tmp_path, options={"intervalo_m": 2.5, "desde_m": 1})
        argv = MotorCurvasDeNivel().plan(trabajo).argv
        assert float(_valor(argv, "-i")) == 2.5 and float(_valor(argv, "-off")) == 1.0
        assert _valor(argv, "-a") == "ELEV" and _valor(argv, "-nln") == "curvas"

    def test_sin_opciones_el_intervalo_es_el_declarado(self, usuario, tmp_path):
        argv = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path)).argv
        declarada = {o.nombre: o.por_defecto for o in MotorCurvasDeNivel().opciones(None)}
        assert float(_valor(argv, "-i")) == declarada["intervalo_m"]

    @pytest.mark.parametrize("malo", [0, -5, 0.0001, "abc", "nan", "inf", None])
    def test_un_intervalo_que_no_es_una_curva_se_rechaza(self, usuario, tmp_path, malo):
        trabajo = _trabajo(usuario, tmp_path, options={"intervalo_m": malo})
        with pytest.raises(ValueError):
            MotorCurvasDeNivel().plan(trabajo)

    def test_un_destino_que_no_es_de_curvas_se_rechaza(self, usuario, tmp_path):
        with pytest.raises(ValueError, match="no es un destino de curvas"):
            MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, "geojson"))

    def test_nunca_se_silencia_y_hay_analizador_de_progreso(self, usuario, tmp_path):
        plan = MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path))
        assert "-q" not in plan.argv and "--quiet" not in plan.argv
        assert plan.analizador_de_progreso is not None and plan.emite_progreso

    def test_un_asc_que_es_otra_cosa_no_se_abre(self, usuario, tmp_path):
        """`gdal_contour` no tiene `-if`: un VRT disfrazado de `.asc` leería otros archivos."""
        falso = tmp_path / "modelo.asc"
        falso.write_text("<VRTDataset><VRTRasterBand><SourceFilename>/etc/x</SourceFilename>")
        trabajo = _trabajo(usuario, tmp_path, origen="asc")
        with pytest.raises(ValueError, match="no empieza como uno"):
            MotorCurvasDeNivel().plan(trabajo)

    @pytest.mark.parametrize("cabecera", [b"ncols 2\n", b"NCOLS 2\n", b"\n  ncols 2\n"])
    def test_un_asc_de_verdad_si(self, usuario, tmp_path, cabecera):
        (tmp_path / "modelo.asc").write_bytes(cabecera)
        MotorCurvasDeNivel().plan(_trabajo(usuario, tmp_path, origen="asc"))

    def test_el_original_no_se_toca_en_el_plan(self, usuario, tmp_path):
        import hashlib

        trabajo = _trabajo(usuario, tmp_path)
        ruta = Path(trabajo.source_path)
        huella = (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns)
        MotorCurvasDeNivel().plan(trabajo)
        assert (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns) == huella


class TestLosPares:
    def test_cada_origen_de_elevacion_va_a_los_tres_destinos(self):
        pares = MotorCurvasDeNivel().pares()
        assert len(pares) == len(raster.ORIGENES_DE_ELEVACION) * 3
        assert ParDeFormatos("geotiff", "dxf") in pares and ParDeFormatos("asc", "gpkg") in pares

    def test_dwg_no_esta_porque_lo_escribe_oda(self):
        assert not any(p.destino == "dwg" for p in MotorCurvasDeNivel().pares())

    def test_un_jpeg_o_un_png_no_son_modelos_de_elevacion(self):
        origenes = {p.origen for p in MotorCurvasDeNivel().pares()}
        assert origenes.isdisjoint({"jpeg", "png", "webp", "jp2"})

    def test_las_opciones_declaradas_son_las_que_el_plan_lee(self, usuario, tmp_path):
        nombres = {o.nombre for o in MotorCurvasDeNivel().opciones(None)}
        assert nombres == {"intervalo_m", "desde_m"}

    def test_esta_registrado(self):
        from apps.engines import registry

        registry.limpiar()
        raster.registrar_todos()
        assert any(m.id == "gdal-curvas" for m in registry.todos())


class TestLaDisponibilidad:
    def test_sin_gdal_contour_se_apaga_con_motivo(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: SimpleNamespace(disponible=True, version="GDAL 3")
        )
        monkeypatch.setattr(sondas, "sondar_proj", lambda: SimpleNamespace(disponible=True))
        monkeypatch.setattr(raster, "_bin", lambda nombre: str(Path("no") / "existe" / nombre))
        estado = MotorCurvasDeNivel().disponibilidad()
        assert not estado.disponible and estado.codigo_motivo == "motor-no-disponible"
        assert "gdal_contour" in estado.mensaje and estado.version == "GDAL 3"


def _ogr(capas):
    return {"driverShortName": "GPKG", "layers": capas}


def _capa(n, epsg="32719"):
    wkt = f'PROJCRS["x",ID["EPSG",{epsg}]]' if epsg else ""
    return {"featureCount": n, "geometryFields": [{"coordinateSystem": {"wkt": wkt}}]}


class TestElVeredicto:
    def _verificar(self, monkeypatch, usuario, tmp_path, info, destino="gpkg"):
        from apps.vector import motores as vector

        salida = tmp_path / f"curvas.{destino}"
        salida.write_bytes(b"x" * 100)
        monkeypatch.setattr(vector, "_ogrinfo", lambda ruta: info)
        trabajo = _trabajo(usuario, tmp_path, destino)
        return MotorCurvasDeNivel().verificar(trabajo, salida)

    def test_sin_ninguna_curva_se_rechaza_y_dice_por_que(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(0)]))
        assert not v.correcta and v.codigo_motivo == "salida-invalida"
        assert "No salió ninguna curva" in v.motivo and "ortofoto" in v.motivo

    def test_ogr_que_no_lee_lo_que_se_escribio_se_rechaza(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, None)
        assert not v.correcta and "OGR no puede leer" in v.motivo

    def test_con_curvas_y_sistema_pasa_y_cuenta(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(29)]))
        assert v.correcta and v.detalles["curvas"] == 29 and v.detalles["epsg"] == "32719"

    def test_perder_el_sistema_en_un_gpkg_se_rechaza(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(5, epsg="")]))
        assert not v.correcta and "ningún sistema" in v.motivo

    def test_el_dxf_no_guarda_sistema_y_el_recibo_lo_dice(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(5, epsg="")]), "dxf")
        assert v.correcta and "no guarda el sistema" in v.detalles["avisos"][0]
        assert "EPSG:32719" in v.detalles["avisos"][0]

    def test_sin_archivo_no_se_pregunta_a_ogr(self, usuario, tmp_path):
        v = MotorCurvasDeNivel().verificar(_trabajo(usuario, tmp_path), tmp_path / "no_hay.gpkg")
        assert not v.correcta and v.codigo_motivo == "sin-salida"


class TestLaLimpiezaDeLosRestos:
    """`_borrar` arrastra lo que cuelga del nombre del parcial, y nada más (regla 5)."""

    def test_se_van_el_parcial_y_sus_intermedios_y_se_quedan_los_ajenos(self, tmp_path):
        from apps.jobs.runner import _borrar

        parcial = tmp_path / "mapa.parcial.dxf"
        intermedio = tmp_path / "mapa.parcial.dxf.curvas3d.gpkg"
        ajenos = [
            tmp_path / "mapa.dxf",
            tmp_path / "mapa.parcial.shp",
            tmp_path / "otro.parcial.dxf",
        ]
        for ruta in (parcial, intermedio, *ajenos):
            ruta.write_bytes(b"x")
        _borrar(parcial)
        assert not parcial.exists() and not intermedio.exists()
        assert all(a.exists() for a in ajenos)

    def test_un_nombre_con_corchetes_o_comodines_no_deja_restos_ni_toca_ajenos(self, tmp_path):
        from apps.jobs.runner import _borrar

        parcial = tmp_path / "mapa [final].parcial.dxf"
        intermedio = tmp_path / "mapa [final].parcial.dxf.curvas3d.gpkg"
        vecino = (
            tmp_path / "mapa f.parcial.dxf.curvas3d.gpkg"
        )  # lo que casaría `[final]` sin escapar
        for ruta in (parcial, intermedio, vecino):
            ruta.write_bytes(b"x")
        _borrar(parcial)
        assert not intermedio.exists() and vecino.exists()


class TestElOrigenQueNoEsElevacion:
    def test_una_imagen_de_varias_bandas_se_rechaza(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(raster, "_gdalinfo", lambda ruta: {"bands": [{}, {}, {}]})
        v = TestElVeredicto()._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(25)]))
        assert not v.correcta and "3 bandas" in v.motivo and "no un modelo" in v.motivo

    def test_una_banda_sola_pasa(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(raster, "_gdalinfo", lambda ruta: {"bands": [{}]})
        v = TestElVeredicto()._verificar(monkeypatch, usuario, tmp_path, _ogr([_capa(25)]))
        assert v.correcta

    def test_un_modelo_sin_sistema_avisa_aunque_no_declare_ninguno(
        self, monkeypatch, usuario, tmp_path
    ):
        monkeypatch.setattr(raster, "_gdalinfo", lambda ruta: {"bands": [{}]})
        trabajo = _trabajo(usuario, tmp_path, source_crs_code="")
        salida = tmp_path / "curvas.gpkg"
        salida.write_bytes(b"x" * 10)
        from apps.vector import motores as vector

        monkeypatch.setattr(vector, "_ogrinfo", lambda ruta: _ogr([_capa(5, epsg="")]))
        v = MotorCurvasDeNivel().verificar(trabajo, salida)
        assert v.correcta and "no declara su sistema" in v.detalles["avisos"][0]


class TestLaDisponibilidadDeOgr2ogr:
    def test_sin_ogr2ogr_se_apaga_con_motivo(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: SimpleNamespace(disponible=True, version="GDAL 3")
        )
        monkeypatch.setattr(sondas, "sondar_proj", lambda: SimpleNamespace(disponible=True))
        monkeypatch.setattr(
            raster,
            "_bin",
            lambda n: __file__ if n == "gdal_contour" else str(Path("no") / "existe" / n),
        )
        estado = MotorCurvasDeNivel().disponibilidad()
        assert not estado.disponible and "ogr2ogr" in estado.mensaje


# --- Contra GDAL de verdad ------------------------------------------------------------------

sin_gdal = pytest.mark.skipif(
    shutil.which("gdalinfo") is None and not Path(r"C:\Program Files\QGIS 4.0.2\bin").exists(),
    reason="GDAL no esta en esta maquina",
)

PENDIENTE = 0.5  # m de bajada por metro de distancia
ALTURA_DE_LA_CIMA = 100.0
LADO_PX = 400


@pytest.mark.oraculo
@sin_gdal
class TestContraGdalDeVerdad:
    """Un cono `z = 100 − 0,5·r` en un GeoTIFF de 400 × 400 px de 1 m.

    La curva de cota `L` es una circunferencia de radio `(100 − L)/0,5`: el oráculo es la fórmula,
    no una segunda lectura de GDAL. Las cotas 10…90 son anillos completos (uno por cota); las de 0
    hacia abajo solo tocan las cuatro esquinas del cuadrado, porque el radio llega a 283 m y el
    cuadrado solo a 200 m del centro.
    """

    ESTE0, NORTE0 = 495000.0, 7318000.0

    def _modelo(self, tmp_path) -> Path:
        import numpy as np

        y, x = np.mgrid[0:LADO_PX, 0:LADO_PX]
        r = np.hypot(x + 0.5 - LADO_PX / 2, y + 0.5 - LADO_PX / 2)
        z = ALTURA_DE_LA_CIMA - PENDIENTE * r
        asc = tmp_path / "cono.asc"
        with asc.open("w") as f:
            f.write(
                f"ncols {LADO_PX}\nnrows {LADO_PX}\nxllcorner {self.ESTE0}\n"
                f"yllcorner {self.NORTE0}\ncellsize 1\nNODATA_value -9999\n"
            )
            for fila in z:
                f.write(" ".join(f"{v:.5f}" for v in fila) + "\n")
        tif = tmp_path / "cono.tif"
        subprocess.run(  # noqa: S603 - argumentos fijos; el programa es de GDAL
            [
                raster._bin("gdal_translate"), "-q", "-a_srs", "EPSG:32719", str(asc), str(tif),
            ],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip
        return tif

    def _curvas(self, usuario, tmp_path, origen, destino, **opciones):
        from apps.engines import registry
        from apps.jobs import runner

        registry.limpiar()
        registry.registrar(MotorCurvasDeNivel())
        trabajo = _trabajo(
            usuario,
            tmp_path,
            destino,
            options={"intervalo_m": 10, **opciones},
            source_path=str(origen),
            source_name=origen.name,
            source_size_bytes=origen.stat().st_size,
            source_format_code="asc" if origen.suffix == ".asc" else "geotiff",
        )
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        assert resultado.estado == "done", trabajo.reason_detail
        return trabajo

    def _entidades(self, ruta: Path) -> list[dict]:
        """Lo que lee `ogrinfo` (GeoJSON): otro programa que el que escribió el archivo."""
        salida = subprocess.run(  # noqa: S603
            [raster._bin("ogrinfo"), "-json", "-features", "-al", str(ruta)],
            check=True, capture_output=True, text=True, timeout=120,
            env=__import__("os").environ | raster.entorno_de_gdal(),
        )  # fmt: skip
        capas = json.loads(salida.stdout)["layers"]
        return [f for capa in capas for f in capa.get("features", [])]

    def test_cada_cota_es_una_circunferencia_del_radio_que_dice_la_formula(self, usuario, tmp_path):
        trabajo = self._curvas(usuario, tmp_path, self._modelo(tmp_path), "gpkg")
        entidades = self._entidades(Path(trabajo.output_path))
        centro = (self.ESTE0 + LADO_PX / 2, self.NORTE0 + LADO_PX / 2)

        por_cota: dict[float, list[dict]] = {}
        for e in entidades:
            por_cota.setdefault(e["properties"]["ELEV"], []).append(e)

        for cota in range(10, 100, 10):
            anillos = por_cota[float(cota)]
            assert len(anillos) == 1, f"la cota {cota} debía ser un solo anillo"
            esperado = (ALTURA_DE_LA_CIMA - cota) / PENDIENTE
            for x, y, *_ in anillos[0]["geometry"]["coordinates"]:
                radio = math.hypot(x - centro[0], y - centro[1])
                assert radio == pytest.approx(esperado, abs=0.6), (cota, radio, esperado)
            primero, ultimo = (
                anillos[0]["geometry"]["coordinates"][0],
                anillos[0]["geometry"]["coordinates"][-1],
            )
            assert primero[:2] == ultimo[:2], f"el anillo de la cota {cota} no cierra"
        # Las cotas que solo tocan las esquinas: cuatro arcos cada una.
        for cota in (-40, -30, -20, -10, 0):
            assert len(por_cota[float(cota)]) == 4
        assert sorted(por_cota) == [float(c) for c in range(-40, 100, 10)]

    def test_el_recibo_dice_las_curvas_y_el_sistema(self, usuario, tmp_path):
        trabajo = self._curvas(usuario, tmp_path, self._modelo(tmp_path), "gpkg")
        assert trabajo.verification["curvas"] == 29 and trabajo.verification["epsg"] == "32719"

    def _cotas_del_dxf(self, ruta: Path) -> list[float]:
        """La elevación de cada polilínea, leída con `ezdxf`: otro lector que `ogr2ogr`.

        OGR no devuelve la Z de un DXF de polilíneas con elevación (la lee como 2D), así que para
        esto el oráculo es `ezdxf`.
        """
        import ezdxf

        modelo = ezdxf.readfile(ruta)
        return [round(e.dxf.elevation, 6) for e in modelo.modelspace().query("LWPOLYLINE")]

    def test_los_tres_destinos_dan_el_mismo_numero_de_curvas_por_cota(self, usuario, tmp_path):
        modelo = self._modelo(tmp_path)
        cuentas = {}
        for destino in ("gpkg", "shp", "dxf"):
            carpeta = tmp_path / destino
            carpeta.mkdir()
            ruta = Path(self._curvas(usuario, carpeta, modelo, destino).output_path)
            if destino == "dxf":
                cotas = self._cotas_del_dxf(ruta)
            else:
                cotas = [f["properties"]["ELEV"] for f in self._entidades(ruta)]
            cuentas[destino] = {c: cotas.count(c) for c in set(cotas)}
        assert cuentas["gpkg"] == cuentas["shp"] == cuentas["dxf"]
        assert sum(cuentas["dxf"].values()) == 29

    def test_el_dxf_trae_cada_curva_a_su_cota(self, usuario, tmp_path):
        """Sin esto el DXF sale con 29 polilíneas planas: el fallo que obligó al intermedio 3D."""
        trabajo = self._curvas(usuario, tmp_path, self._modelo(tmp_path), "dxf")
        cotas = self._cotas_del_dxf(Path(trabajo.output_path))
        assert sorted(set(cotas)) == [float(c) for c in range(-40, 100, 10)]
        assert not list(tmp_path.glob("*.curvas3d.gpkg")), "el intermedio no se limpió"

    def test_un_asc_se_lee_igual_que_su_geotiff(self, usuario, tmp_path):
        tif = self._modelo(tmp_path)
        a = (
            self._curvas(usuario, tmp_path / "a", tif, "gpkg")
            if (tmp_path / "a").mkdir() is None
            else None
        )
        b = (
            self._curvas(usuario, tmp_path / "b", tmp_path / "cono.asc", "gpkg")
            if (tmp_path / "b").mkdir() is None
            else None
        )
        assert a.verification["curvas"] == b.verification["curvas"] == 29

    def test_la_cota_de_partida_desplaza_las_curvas(self, usuario, tmp_path):
        trabajo = self._curvas(usuario, tmp_path, self._modelo(tmp_path), "gpkg", desde_m=5)
        cotas = {f["properties"]["ELEV"] for f in self._entidades(Path(trabajo.output_path))}
        assert {15.0, 25.0, 95.0} <= cotas and 10.0 not in cotas

    def test_un_intervalo_mayor_que_el_desnivel_no_da_un_archivo_vacio_como_bueno(
        self, usuario, tmp_path
    ):
        from apps.engines import registry
        from apps.jobs import runner

        modelo = self._modelo(tmp_path)
        registry.limpiar()
        registry.registrar(MotorCurvasDeNivel())
        trabajo = _trabajo(
            usuario, tmp_path, "gpkg", options={"intervalo_m": 5000, "desde_m": 2500},
            source_path=str(modelo), source_size_bytes=modelo.stat().st_size,
        )  # fmt: skip
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        assert resultado.estado != "done"
        assert not Path(trabajo.output_path).exists()  # y no queda un archivo vacío como entregable

    def test_un_fallo_deja_el_original_intacto_y_ni_parcial_ni_intermedio(self, usuario, tmp_path):
        import hashlib

        from apps.engines import registry
        from apps.jobs import runner

        modelo = self._modelo(tmp_path)
        huella = (hashlib.sha256(modelo.read_bytes()).hexdigest(), modelo.stat().st_mtime_ns)
        registry.limpiar()
        registry.registrar(MotorCurvasDeNivel())
        for destino in ("gpkg", "dxf"):
            carpeta = tmp_path / destino
            carpeta.mkdir()
            trabajo = _trabajo(
                usuario, carpeta, destino, options={"intervalo_m": 5000, "desde_m": 2500},
                source_path=str(modelo), source_size_bytes=modelo.stat().st_size,
            )  # fmt: skip
            assert runner.ejecutar(trabajo).estado != "done"
            assert sorted(p.name for p in carpeta.iterdir()) == ["modelo.tif"], (
                destino
            )  # solo el de relleno de `_trabajo`
        assert (
            hashlib.sha256(modelo.read_bytes()).hexdigest(),
            modelo.stat().st_mtime_ns,
        ) == huella

    def test_una_ortofoto_de_tres_bandas_no_se_da_por_modelo(self, usuario, tmp_path):
        from apps.engines import registry
        from apps.jobs import runner

        rgb = tmp_path / "orto.tif"
        subprocess.run(  # noqa: S603 - argumentos fijos; el programa es de GDAL
            [raster._bin("gdal_translate"), "-q", "-b", "1", "-b", "1", "-b", "1",
             "-a_srs", "EPSG:32719",
             str(self._modelo(tmp_path)), str(rgb)],
            capture_output=True, timeout=120,
        )  # fmt: skip
        if not rgb.exists():
            pytest.skip("no se pudo fabricar la imagen de tres bandas")
        registry.limpiar()
        registry.registrar(MotorCurvasDeNivel())
        trabajo = _trabajo(usuario, tmp_path, "gpkg", source_path=str(rgb))
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        assert resultado.estado != "done"
