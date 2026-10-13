"""Procesar ráster (F21.3): recorte por polígono, mosaico y sombreado.

Casi todo corre **sin GDAL** (el CI no lo tiene): el plan (el `argv` que se lanzaría), las paradas
por CRS y el veredicto sobre lo que `gdalinfo` diría. Al final, las pruebas `@pytest.mark.oraculo`
procesan de verdad datos **sintéticos de resultado conocido**, y comparan con
`gdalinfo -json -stats` contra cifras que se calculan (no se leen del propio resultado):

- un ráster donde cada píxel vale `1000·fila + columna`: el recorte de un rectángulo tiene un
  mínimo, un máximo y una media que son una fórmula;
- un triángulo, donde el porcentaje de píxeles válidos es el de los centros que caen dentro;
- dos mitades de valor constante, cuyo mosaico mide 100 × 100 y de media 1500;
- un plano inclinado, cuyo sombreado es una constante que dan el seno y el coseno de la pendiente.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from apps.engines import registry
from apps.engines.base import ParDeFormatos, PlanNoValido
from apps.engines.testing import MotorDeMentira
from apps.formats import poligono
from apps.formats.crs import Crs, PuntoConCrs
from apps.jobs import runner
from apps.jobs.models import ConversionJob, EntradaDeTrabajo
from apps.raster import motores as raster
from apps.raster import procesar
from apps.raster.procesar import MotorMosaico, MotorRecorteRaster, MotorSombreado

pytestmark = pytest.mark.django_db

UTM19S = 32719


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _trabajo(usuario, tmp_path, operacion, destino="geotiff", origen_code="geotiff", **extra):
    opciones = {"operacion": operacion, **extra.pop("options", {})}
    ruta = Path(extra.pop("source_path", tmp_path / "origen.tif"))
    if not ruta.exists():
        ruta.write_bytes(b"II*\x00")
    campos = {
        "owner": usuario,
        "source_path": str(ruta),
        "source_name": ruta.name,
        "source_size_bytes": 1_000_000,
        "source_format_code": origen_code,
        "source_crs_authority": "EPSG",
        "source_crs_code": str(UTM19S),
        "target_format_code": destino,
        "output_path": str(tmp_path / f"salida.{'tif'}"),
        "options": opciones,
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


def _wkt_de(epsg: int) -> str:
    from pyproj import CRS

    return CRS.from_epsg(epsg).to_wkt()


def _info(
    *,
    bandas=1,
    tipo="Float32",
    sin_dato=True,
    alfa=False,
    epsg: int | None = UTM19S,
    tamano=(100, 100),
    origen=(495000.0, 7318100.0),
    pixel=1.0,
    unidad=None,
):
    """Lo que `gdalinfo -json` diría de un ráster, para probar el plan sin GDAL."""
    lista = []
    for i in range(bandas):
        banda = {"band": i + 1, "type": tipo, "colorInterpretation": "Gray"}
        if sin_dato:
            banda["noDataValue"] = -9999.0
        if unidad:
            banda["unit"] = unidad
        lista.append(banda)
    if alfa:
        lista.append({"band": bandas + 1, "type": "Byte", "colorInterpretation": "Alpha"})
    x0, y0 = origen
    info = {
        "size": list(tamano),
        "geoTransform": [x0, pixel, 0.0, y0, 0.0, -pixel],
        "bands": lista,
        "cornerCoordinates": {
            "lowerLeft": [x0, y0 - tamano[1] * pixel],
            "upperRight": [x0 + tamano[0] * pixel, y0],
        },
        "coordinateSystem": {"wkt": _wkt_de(epsg)} if epsg else {},
    }
    return info


def _valor(argv, bandera):
    return argv[argv.index(bandera) + 1]


def _huella(ruta: Path):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


RECTANGULO = "495020 7318030; 495060 7318030; 495060 7318070; 495020 7318070"
OPCIONES_RECORTE = {"recorte_vertices": RECTANGULO, "recorte_crs": f"EPSG:{UTM19S}"}


# --- Procesos y conversiones no se pisan ----------------------------------------------------------


class TestLosProcesosNoTapanLasConversiones:
    def test_sin_operacion_el_par_lo_atiende_el_motor_de_conversion(self):
        for par in (ParDeFormatos("geotiff", "cog"), ParDeFormatos("geotiff", "geotiff")):
            ids = {m.id for m in registry.motores_para(par)}
            assert "gdal-raster" in ids
            assert not ids & {"gdal-recorte", "gdal-mosaico", "gdal-sombreado"}

    def test_con_operacion_el_par_lo_atiende_el_proceso(self):
        par = ParDeFormatos("geotiff", "cog")
        assert {m.id for m in registry.motores_para(par, "recorte")} == {"gdal-recorte"}
        assert {m.id for m in registry.motores_para(par, "mosaico")} == {"gdal-mosaico"}
        assert {m.id for m in registry.motores_para(par, "sombreado")} == {"gdal-sombreado"}

    def test_la_matriz_de_conversion_no_cambia_de_motor(self):
        celda = registry.matriz_de_capacidades()[("geotiff", "cog")]
        assert celda.motor_id == "gdal-raster"
        assert all(
            not m.operacion for m in registry.todos() if m.id in {"gdal-raster", "gdal-curvas"}
        )

    def test_una_operacion_que_no_existe_no_tiene_motor(self):
        assert registry.motor_para(ParDeFormatos("geotiff", "cog"), "no-existe") is None


# --- El polígono lleva su CRS ---------------------------------------------------------------------


class TestElPoligono:
    def test_los_vertices_salen_como_puntos_con_su_crs(self):
        anillo = poligono.anillo_de_opciones(OPCIONES_RECORTE)
        assert len(anillo) == 4
        assert all(isinstance(p, PuntoConCrs) and str(p.crs) == f"EPSG:{UTM19S}" for p in anillo)

    def test_sin_crs_declarado_se_detiene_y_no_hay_valor_por_omision(self):
        with pytest.raises(PlanNoValido) as fallo:
            poligono.anillo_de_opciones({"recorte_vertices": RECTANGULO})
        assert fallo.value.codigo == "crs-ausente"

    def test_un_crs_que_no_existe_se_detiene(self):
        with pytest.raises(PlanNoValido) as fallo:
            poligono.anillo_de_opciones({**OPCIONES_RECORTE, "recorte_crs": "EPSG:999999"})
        assert fallo.value.codigo == "crs-invalido"

    @pytest.mark.parametrize(
        "vertices",
        ["", "1 2; 3 4", "1 2; 1 2; 1 2", "1 2; 3; 5 6", "1 2; a b; 5 6", [[1, 2], [3, 4]]],
    )
    def test_un_poligono_que_no_es_un_poligono_se_para(self, vertices):
        with pytest.raises(PlanNoValido):
            poligono.anillo_de_opciones({**OPCIONES_RECORTE, "recorte_vertices": vertices})

    def test_un_poligono_sin_superficie_se_para(self):
        anillo = poligono.anillo_de_opciones(
            {**OPCIONES_RECORTE, "recorte_vertices": "0 0; 1 1; 2 2"}
        )
        with pytest.raises(PlanNoValido):
            poligono.a_wkt(anillo)

    def test_el_wkt_cierra_el_anillo_y_guarda_todos_los_decimales(self):
        anillo = poligono.anillo_de_opciones(
            {**OPCIONES_RECORTE, "recorte_vertices": [[0.1, 0.2], [10.25, 0.2], [10.25, 8.125]]}
        )
        wkt = poligono.a_wkt(anillo)
        assert wkt == "POLYGON((0.1 0.2, 10.25 0.2, 10.25 8.125, 0.1 0.2))"

    def test_un_anillo_que_ya_viene_cerrado_no_duplica_el_ultimo(self):
        anillo = poligono.anillo_de_opciones(
            {**OPCIONES_RECORTE, "recorte_vertices": [[0, 0], [4, 0], [4, 4], [0, 0]]}
        )
        assert len(anillo) == 3

    def test_llevar_a_otro_sistema_y_volver_da_los_mismos_vertices(self):
        anillo = poligono.anillo_de_opciones(OPCIONES_RECORTE)
        geograficos = poligono.llevar_a(anillo, Crs("EPSG", "4326"))
        assert all(-72 < p.x_m < -66 for p in geograficos)  # longitudes de Chile, no metros
        de_vuelta = poligono.llevar_a(geograficos, Crs("EPSG", str(UTM19S)))
        for a, b in zip(anillo, de_vuelta, strict=True):
            assert (a.x_m, a.y_m) == pytest.approx((b.x_m, b.y_m), abs=1e-3)

    def test_llevar_a_un_destino_sin_crs_se_detiene(self):
        anillo = poligono.anillo_de_opciones(OPCIONES_RECORTE)
        with pytest.raises(PlanNoValido) as fallo:
            poligono.llevar_a(anillo, Crs("", ""))
        assert fallo.value.codigo == "crs-ausente"

    def test_vertices_con_crs_distintos_no_se_mezclan(self):
        a = PuntoConCrs(x_m=0, y_m=0, crs=Crs("EPSG", "32719"))
        b = PuntoConCrs(x_m=1, y_m=1, crs=Crs("EPSG", "4326"))
        with pytest.raises(PlanNoValido):
            poligono.crs_unico((a, b, a))


# --- El plan del recorte --------------------------------------------------------------------------


class TestElPlanDelRecorte:
    def _plan(self, monkeypatch, usuario, tmp_path, info=None, **extra):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: info or _info())
        opciones = extra.pop("options", OPCIONES_RECORTE)
        trabajo = _trabajo(usuario, tmp_path, "recorte", options=opciones, **extra)
        return MotorRecorteRaster().plan(trabajo)

    def test_el_comando_es_gdalwarp_con_el_poligono_y_su_crs(self, monkeypatch, usuario, tmp_path):
        plan = self._plan(monkeypatch, usuario, tmp_path)
        assert "gdalwarp" in plan.argv[0]
        assert _valor(plan.argv, "-cutline").startswith("POLYGON((495020.0 7318030.0")
        assert _valor(plan.argv, "-cutline_srs") == f"EPSG:{UTM19S}"
        assert ".parcial" in plan.argv[-1]
        assert plan.ruta_de_salida == tmp_path / "salida.tif"

    def test_la_ventana_es_la_del_poligono_sobre_la_reticula_del_original(
        self, monkeypatch, usuario, tmp_path
    ):
        plan = self._plan(monkeypatch, usuario, tmp_path)
        i = plan.argv.index("-te")
        assert [float(v) for v in plan.argv[i + 1 : i + 5]] == [495020, 7318030, 495060, 7318070]
        assert [float(v) for v in plan.argv[plan.argv.index("-tr") + 1 :][:2]] == [1, 1]

    def test_un_polígono_a_medio_pixel_agranda_la_ventana_hacia_afuera(
        self, monkeypatch, usuario, tmp_path
    ):
        opciones = {
            **OPCIONES_RECORTE,
            "recorte_vertices": "495020.4 7318030.4; 495059.6 7318030.4; 495040 7318069.6",
        }
        plan = self._plan(monkeypatch, usuario, tmp_path, options=opciones)
        i = plan.argv.index("-te")
        assert [float(v) for v in plan.argv[i + 1 : i + 5]] == [495020, 7318030, 495060, 7318070]

    def test_la_ventana_no_sale_de_la_imagen(self, monkeypatch, usuario, tmp_path):
        opciones = {
            **OPCIONES_RECORTE,
            "recorte_vertices": "494000 7317000; 496000 7317000; 495500 7319000",
        }
        plan = self._plan(monkeypatch, usuario, tmp_path, options=opciones)
        i = plan.argv.index("-te")
        assert [float(v) for v in plan.argv[i + 1 : i + 5]] == [495000, 7318000, 495100, 7318100]

    def test_sin_dato_declarado_no_se_añade_alfa(self, monkeypatch, usuario, tmp_path):
        plan = self._plan(monkeypatch, usuario, tmp_path)
        assert "-dstalpha" not in plan.argv

    def test_sin_dato_declarado_se_añade_alfa_porque_cero_no_es_sin_dato(
        self, monkeypatch, usuario, tmp_path
    ):
        plan = self._plan(monkeypatch, usuario, tmp_path, info=_info(sin_dato=False))
        assert "-dstalpha" in plan.argv

    def test_con_alfa_propia_no_se_añade_otra(self, monkeypatch, usuario, tmp_path):
        plan = self._plan(
            monkeypatch, usuario, tmp_path, info=_info(sin_dato=False, bandas=3, alfa=True)
        )
        assert "-dstalpha" not in plan.argv

    def test_el_valor_sin_dato_que_se_pide_gana(self, monkeypatch, usuario, tmp_path):
        opciones = {**OPCIONES_RECORTE, "nodata": -32768}
        plan = self._plan(
            monkeypatch, usuario, tmp_path, info=_info(sin_dato=False), options=opciones
        )
        assert _valor(plan.argv, "-dstnodata") == "-32768.0"
        assert "-dstalpha" not in plan.argv

    def test_cog_sale_con_el_controlador_cog_y_geotiff_con_gtiff(
        self, monkeypatch, usuario, tmp_path
    ):
        cog = self._plan(monkeypatch, usuario, tmp_path, destino="cog")
        tif = self._plan(monkeypatch, usuario, tmp_path, destino="geotiff")
        assert _valor(cog.argv, "-of") == "COG"
        assert _valor(tif.argv, "-of") == "GTiff"

    def test_no_remuestrea(self, monkeypatch, usuario, tmp_path):
        assert _valor(self._plan(monkeypatch, usuario, tmp_path).argv, "-r") == "near"

    def test_es_un_proceso_y_el_timeout_sale_del_tamano(self, monkeypatch, usuario, tmp_path):
        plan = self._plan(monkeypatch, usuario, tmp_path)
        assert plan.timeout_s >= 600 and plan.analizador_de_progreso is not None


class TestElRecorteSeDetiene:
    """Las paradas de la regla 3: cada una **con su código**, y **sin tocar el original**."""

    def _original(self, tmp_path):
        ruta = tmp_path / "origen.tif"
        ruta.write_bytes(b"II*\x00" + bytes(range(256)) * 8)
        os.utime(ruta, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        return ruta

    CASOS = [
        pytest.param({"recorte_vertices": RECTANGULO}, {}, "crs-ausente", id="poligono-sin-crs"),
        pytest.param(
            {**OPCIONES_RECORTE, "recorte_crs": "EPSG:999999"}, {}, "crs-invalido", id="crs-falso"
        ),
        pytest.param(OPCIONES_RECORTE, {"source_crs_code": ""}, "crs-ausente", id="imagen-sin-crs"),
        pytest.param({"recorte_crs": f"EPSG:{UTM19S}"}, {}, "error-del-motor", id="sin-poligono"),
        pytest.param(
            {**OPCIONES_RECORTE, "recorte_archivo": "x.geojson"},
            {},
            "error-del-motor",
            id="vertices-y-archivo",
        ),
        pytest.param(
            {
                "recorte_vertices": "0 0; 10 0; 10 10",
                "recorte_crs": f"EPSG:{UTM19S}",
            },
            {},
            "recorte-vacio",
            id="poligono-fuera-de-la-imagen",
        ),
        pytest.param(
            {"recorte_archivo": "poligono.vrt"}, {}, "formato-no-reconocido", id="vrt-no-se-abre"
        ),
    ]

    @pytest.mark.parametrize(("opciones", "extra", "codigo"), CASOS)
    def test_se_para_con_su_codigo_y_el_original_queda_igual(
        self, monkeypatch, usuario, tmp_path, opciones, extra, codigo
    ):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        origen = self._original(tmp_path)
        antes = _huella(origen)
        trabajo = _trabajo(
            usuario, tmp_path, "recorte", source_path=origen, options=opciones, **extra
        )
        with pytest.raises(PlanNoValido) as fallo:
            MotorRecorteRaster().plan(trabajo)
        assert fallo.value.codigo == codigo
        assert _huella(origen) == antes
        assert not list(tmp_path.glob("*.parcial*"))

    def test_una_imagen_girada_no_se_recorta(self, monkeypatch, usuario, tmp_path):
        info = _info()
        info["geoTransform"][2] = 0.3
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: info)
        with pytest.raises(PlanNoValido):
            MotorRecorteRaster().plan(
                _trabajo(usuario, tmp_path, "recorte", options=OPCIONES_RECORTE)
            )

    def test_una_imagen_que_gdal_no_lee_se_para(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: None)
        with pytest.raises(PlanNoValido) as fallo:
            MotorRecorteRaster().plan(
                _trabajo(usuario, tmp_path, "recorte", options=OPCIONES_RECORTE)
            )
        assert fallo.value.codigo == "origen-no-legible"

    def test_un_archivo_de_poligono_sin_crs_con_epsg_se_para(self, monkeypatch, usuario, tmp_path):
        from apps.vector import motores as vector

        poligono_ = tmp_path / "zona.geojson"
        poligono_.write_text('{"type":"FeatureCollection","features":[]}', newline="\n")
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        monkeypatch.setattr(
            vector,
            "_ogrinfo",
            lambda ruta: {
                "layers": [{"name": "zona", "geometryFields": [{"extent": [0, 0, 1, 1]}]}]
            },
        )
        trabajo = _trabajo(
            usuario, tmp_path, "recorte", options={"recorte_archivo": str(poligono_)}
        )
        with pytest.raises(PlanNoValido) as fallo:
            MotorRecorteRaster().plan(trabajo)
        assert fallo.value.codigo == "crs-ausente"

    def test_un_archivo_de_poligono_con_crs_da_su_capa_y_su_caja(
        self, monkeypatch, usuario, tmp_path
    ):
        from apps.vector import motores as vector

        poligono_ = tmp_path / "zona.geojson"
        poligono_.write_text("{}", newline="\n")
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        capa = {
            "name": "zona",
            "geometryFields": [
                {
                    "extent": [495020, 7318030, 495060, 7318070],
                    "coordinateSystem": {"wkt": _wkt_de(UTM19S)},
                }
            ],
        }
        monkeypatch.setattr(vector, "_ogrinfo", lambda ruta: {"layers": [capa]})
        plan = MotorRecorteRaster().plan(
            _trabajo(usuario, tmp_path, "recorte", options={"recorte_archivo": str(poligono_)})
        )
        assert _valor(plan.argv, "-cutline") == str(poligono_)
        assert _valor(plan.argv, "-cl") == "zona"
        i = plan.argv.index("-te")
        assert [float(v) for v in plan.argv[i + 1 : i + 5]] == [495020, 7318030, 495060, 7318070]


class TestElVeredictoDelRecorte:
    def _verificar(self, monkeypatch, usuario, tmp_path, info, **extra):
        monkeypatch.setattr(procesar, "_estadisticas", lambda ruta: info)
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        salida = tmp_path / "recorte.tif"
        salida.write_bytes(b"x" * 20)
        trabajo = _trabajo(usuario, tmp_path, "recorte", options=OPCIONES_RECORTE, **extra)
        return MotorRecorteRaster().verificar(trabajo, salida)

    @staticmethod
    def _recorte(maximo_alfa=255.0, epsg=UTM19S, origen=(495020.0, 7318070.0), tamano=(40, 40)):
        info = _info(sin_dato=False, alfa=True, epsg=epsg, tamano=tamano, origen=origen)
        info["bands"][-1]["metadata"] = {"": {"STATISTICS_MAXIMUM": str(maximo_alfa)}}
        return info

    def test_un_recorte_con_datos_pasa(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._recorte())
        assert v.correcta, v.motivo
        assert v.detalles["ancho_px"] == 40 and v.detalles["epsg"] == str(UTM19S)

    def test_sin_un_solo_dato_es_recorte_vacio_aunque_gdal_haya_salido_con_cero(
        self, monkeypatch, usuario, tmp_path
    ):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._recorte(maximo_alfa=0))
        assert not v.correcta and v.codigo_motivo == "recorte-vacio"

    def test_sin_alfa_se_mira_el_porcentaje_valido(self, monkeypatch, usuario, tmp_path):
        info = _info(tamano=(40, 40), origen=(495020.0, 7318070.0))
        info["bands"][0]["metadata"] = {"": {"STATISTICS_VALID_PERCENT": "0"}}
        v = self._verificar(monkeypatch, usuario, tmp_path, info)
        assert not v.correcta and v.codigo_motivo == "recorte-vacio"

    def test_si_la_salida_pierde_el_crs_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._recorte(epsg=None))
        assert not v.correcta and v.codigo_motivo == "salida-invalida"

    def test_si_la_salida_cambia_de_crs_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, self._recorte(epsg=32718))
        assert not v.correcta and "32718" in v.motivo

    def test_un_recorte_que_se_sale_de_la_imagen_no_se_entrega(
        self, monkeypatch, usuario, tmp_path
    ):
        v = self._verificar(
            monkeypatch,
            usuario,
            tmp_path,
            self._recorte(origen=(494000.0, 7319000.0), tamano=(5000, 5000)),
        )
        assert not v.correcta and "se sale" in v.motivo

    def test_una_salida_que_gdal_no_lee_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, None)
        assert not v.correcta and v.codigo_motivo == "salida-invalida"


# --- El plan del mosaico --------------------------------------------------------------------------


def _entradas(trabajo, rutas):
    for orden, ruta in enumerate(rutas):
        EntradaDeTrabajo.objects.create(
            job=trabajo, orden=orden, ruta=str(ruta), nombre=Path(ruta).name
        )


def _teselas(tmp_path, n=2):
    rutas = []
    for i in range(n):
        ruta = tmp_path / f"tesela{i}.tif"
        ruta.write_bytes(b"II*\x00" + bytes([i]) * 64)
        rutas.append(ruta)
    return rutas


class TestElPlanDelMosaico:
    def _trabajo(self, usuario, tmp_path, rutas, **extra):
        trabajo = _trabajo(
            usuario, tmp_path, "mosaico", destino="cog", source_path=rutas[0], **extra
        )
        _entradas(trabajo, rutas)
        return trabajo

    def test_son_dos_pasos_buildvrt_y_translate_y_la_salida_la_escribe_el_segundo(
        self, monkeypatch, usuario, tmp_path
    ):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        rutas = _teselas(tmp_path, 3)
        plan = MotorMosaico().plan(self._trabajo(usuario, tmp_path, rutas))
        assert "gdalbuildvrt" in plan.argv[0]
        assert [str(r) for r in rutas] == list(plan.argv[-3:])
        (paso2,) = plan.posteriores
        assert "gdal_translate" in paso2[0] and _valor(paso2, "-of") == "COG"
        assert ".parcial" in paso2[-1] and paso2[-2].endswith(".mosaico.vrt")
        assert plan.salida_en_posteriores

    def test_el_intermedio_cuelga_del_parcial_para_que_el_corredor_lo_borre(
        self, monkeypatch, usuario, tmp_path
    ):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        plan = MotorMosaico().plan(self._trabajo(usuario, tmp_path, _teselas(tmp_path)))
        vrt = Path(plan.argv[-3])
        assert vrt.name.startswith(Path(plan.posteriores[0][-1]).name + ".")

    def test_una_ortofoto_sin_dato_y_sin_alfa_recibe_alfa_para_los_huecos(
        self, monkeypatch, usuario, tmp_path
    ):
        monkeypatch.setattr(
            procesar, "_gdalinfo", lambda ruta: _info(bandas=3, tipo="Byte", sin_dato=False)
        )
        plan = MotorMosaico().plan(self._trabajo(usuario, tmp_path, _teselas(tmp_path)))
        assert "-addalpha" in plan.argv

    def test_un_modelo_con_sin_dato_no_recibe_alfa(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        plan = MotorMosaico().plan(self._trabajo(usuario, tmp_path, _teselas(tmp_path)))
        assert "-addalpha" not in plan.argv

    def test_el_tamano_de_pixel_es_una_lista_cerrada(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        rutas = _teselas(tmp_path)
        MotorMosaico().plan(
            self._trabajo(usuario, tmp_path, rutas, options={"resolucion": "lowest"})
        )
        with pytest.raises(PlanNoValido):
            MotorMosaico().plan(
                self._trabajo(usuario, tmp_path, rutas, options={"resolucion": "; rm -rf"})
            )


class TestElMosaicoSeDetiene:
    def _caso(self, monkeypatch, usuario, tmp_path, infos, n=2):
        rutas = _teselas(tmp_path, n)
        por_ruta = dict(zip((str(r) for r in rutas), infos, strict=True))
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: por_ruta[str(ruta)])
        antes = [_huella(r) for r in rutas]
        trabajo = _trabajo(usuario, tmp_path, "mosaico", destino="cog", source_path=rutas[0])
        _entradas(trabajo, rutas)
        with pytest.raises(PlanNoValido) as fallo:
            MotorMosaico().plan(trabajo)
        assert [_huella(r) for r in rutas] == antes  # los originales, intactos
        assert not list(tmp_path.glob("*.parcial*"))
        return fallo.value

    def test_crs_distintos(self, monkeypatch, usuario, tmp_path):
        fallo = self._caso(monkeypatch, usuario, tmp_path, [_info(), _info(epsg=32718)])
        assert fallo.codigo == "crs-distintos"

    def test_una_imagen_sin_crs(self, monkeypatch, usuario, tmp_path):
        fallo = self._caso(monkeypatch, usuario, tmp_path, [_info(), _info(epsg=None)])
        assert fallo.codigo == "crs-ausente"

    def test_la_primera_sin_crs(self, monkeypatch, usuario, tmp_path):
        fallo = self._caso(monkeypatch, usuario, tmp_path, [_info(epsg=None), _info()])
        assert fallo.codigo == "crs-ausente"

    def test_distinto_numero_de_bandas(self, monkeypatch, usuario, tmp_path):
        fallo = self._caso(monkeypatch, usuario, tmp_path, [_info(bandas=3, tipo="Byte"), _info()])
        assert "bandas" in str(fallo)

    def test_una_sola_imagen_no_es_un_mosaico(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: _info())
        rutas = _teselas(tmp_path, 1)
        trabajo = _trabajo(usuario, tmp_path, "mosaico", destino="cog", source_path=rutas[0])
        _entradas(trabajo, rutas)
        with pytest.raises(PlanNoValido):
            MotorMosaico().plan(trabajo)

    def test_una_imagen_que_gdal_no_lee(self, monkeypatch, usuario, tmp_path):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: None)
        rutas = _teselas(tmp_path)
        trabajo = _trabajo(usuario, tmp_path, "mosaico", destino="cog", source_path=rutas[0])
        _entradas(trabajo, rutas)
        with pytest.raises(PlanNoValido) as fallo:
            MotorMosaico().plan(trabajo)
        assert fallo.value.codigo == "origen-no-legible"


class TestElVeredictoDelMosaico:
    def _trabajo_y_salida(self, usuario, tmp_path):
        rutas = _teselas(tmp_path)
        trabajo = _trabajo(usuario, tmp_path, "mosaico", destino="cog", source_path=rutas[0])
        _entradas(trabajo, rutas)
        salida = tmp_path / "mosaico.tif"
        salida.write_bytes(b"x" * 10)
        return trabajo, rutas, salida

    def _infos(self, monkeypatch, salida_info):
        izquierda = _info(tamano=(50, 100), origen=(495000.0, 7318100.0))
        derecha = _info(tamano=(50, 100), origen=(495050.0, 7318100.0))
        por_ruta = {"tesela0.tif": izquierda, "tesela1.tif": derecha, "mosaico.tif": salida_info}
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: por_ruta.get(Path(ruta).name))

    def test_la_union_de_las_extensiones_pasa(self, monkeypatch, usuario, tmp_path):
        trabajo, _, salida = self._trabajo_y_salida(usuario, tmp_path)
        self._infos(monkeypatch, _info(tamano=(100, 100)))
        v = MotorMosaico().verificar(trabajo, salida)
        assert v.correcta, v.motivo
        assert v.detalles["imagenes"] == 2

    def test_si_falta_una_mitad_no_es_la_union(self, monkeypatch, usuario, tmp_path):
        trabajo, _, salida = self._trabajo_y_salida(usuario, tmp_path)
        self._infos(monkeypatch, _info(tamano=(50, 100)))
        v = MotorMosaico().verificar(trabajo, salida)
        assert not v.correcta and "unión" in v.motivo

    def test_si_pierde_el_crs_no_se_entrega(self, monkeypatch, usuario, tmp_path):
        trabajo, _, salida = self._trabajo_y_salida(usuario, tmp_path)
        self._infos(monkeypatch, _info(tamano=(100, 100), epsg=None))
        v = MotorMosaico().verificar(trabajo, salida)
        assert not v.correcta and v.codigo_motivo == "salida-invalida"

    def test_un_original_que_cambia_durante_el_proceso_no_se_entrega(
        self, monkeypatch, usuario, tmp_path
    ):
        trabajo, rutas, salida = self._trabajo_y_salida(usuario, tmp_path)
        self._infos(monkeypatch, _info(tamano=(100, 100)))
        procesar._huellar_entradas(trabajo)
        assert MotorMosaico().verificar(trabajo, salida).correcta
        rutas[1].write_bytes(b"II*\x00" + b"cambio" * 8)
        v = MotorMosaico().verificar(trabajo, salida)
        assert not v.correcta and v.codigo_motivo == "original-modificado"

    def test_huellar_deja_la_huella_de_cada_entrada(self, usuario, tmp_path):
        trabajo, rutas, _ = self._trabajo_y_salida(usuario, tmp_path)
        procesar._huellar_entradas(trabajo)
        for fila, ruta in zip(trabajo.entradas.all(), rutas, strict=True):
            assert fila.sha256 == hashlib.sha256(ruta.read_bytes()).hexdigest()
            assert fila.mtime_ns == ruta.stat().st_mtime_ns


# --- El plan del sombreado ------------------------------------------------------------------------


class TestElPlanDelSombreado:
    def _plan(self, monkeypatch, usuario, tmp_path, info=None, **opciones):
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: info or _info())
        trabajo = _trabajo(usuario, tmp_path, "sombreado", options=opciones)
        return MotorSombreado().plan(trabajo)

    def test_es_gdaldem_hillshade_y_despues_translate(self, monkeypatch, usuario, tmp_path):
        plan = self._plan(monkeypatch, usuario, tmp_path)
        assert "gdaldem" in plan.argv[0] and plan.argv[1] == "hillshade"
        assert _valor(plan.argv, "-az") == "315.0" and _valor(plan.argv, "-alt") == "45.0"
        assert _valor(plan.argv, "-s") == "1.0" and _valor(plan.argv, "-z") == "1.0"
        assert "-q" not in plan.argv  # el avance que imprime GDAL es el de la barra
        (paso2,) = plan.posteriores
        assert "gdal_translate" in paso2[0] and plan.salida_en_posteriores

    def test_comparte_los_argumentos_con_el_visor(self, monkeypatch, usuario, tmp_path):
        from apps.visor import dem

        plan = self._plan(monkeypatch, usuario, tmp_path, azimut_deg=270, altura_deg=30)
        esperado = dem.argumentos_de_sombreado(
            str(tmp_path / "origen.tif"),
            plan.argv[3],
            azimut_deg=270.0,
            altura_deg=30.0,
            exageracion_z=1.0,
            escala=1.0,
            silencioso=False,
        )
        assert list(plan.argv[1:]) == esperado

    def test_en_grados_la_escala_es_la_de_gdal(self, monkeypatch, usuario, tmp_path):
        info = _info(epsg=4326, origen=(-70.0, -33.0), pixel=0.0001)
        plan = self._plan(monkeypatch, usuario, tmp_path, info=info, source_crs_code="4326")
        assert float(_valor(plan.argv, "-s")) == pytest.approx(111120.0)

    def test_con_pies_verticales_la_escala_lo_tiene_en_cuenta(self, monkeypatch, usuario, tmp_path):
        info = _info(unidad="ft")
        plan = self._plan(monkeypatch, usuario, tmp_path, info=info)
        assert float(_valor(plan.argv, "-s")) == pytest.approx(1 / 0.3048)

    def test_los_limites_del_sol_se_comprueban(self, monkeypatch, usuario, tmp_path):
        for opciones in (
            {"azimut_deg": 360},
            {"azimut_deg": -1},
            {"altura_deg": 0},
            {"altura_deg": 91},
            {"exageracion_z": 0},
            {"exageracion_z": 21},
        ):
            with pytest.raises(PlanNoValido):
                self._plan(monkeypatch, usuario, tmp_path, **opciones)
        with pytest.raises(ValueError):
            self._plan(monkeypatch, usuario, tmp_path, azimut_deg="mañana")

    @pytest.mark.parametrize(
        ("info", "codigo"),
        [
            pytest.param(_info(epsg=None), "crs-ausente", id="sin-crs"),
            pytest.param(
                _info(bandas=3, tipo="Byte", sin_dato=False), "error-del-motor", id="imagen"
            ),
            pytest.param(_info(tipo="Byte"), "error-del-motor", id="un-byte-no-es-altura"),
        ],
    )
    def test_se_para_si_no_es_un_modelo_o_no_tiene_crs(
        self, monkeypatch, usuario, tmp_path, info, codigo
    ):
        origen = tmp_path / "origen.tif"
        origen.write_bytes(b"II*\x00" + b"z" * 32)
        antes = _huella(origen)
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: info)
        trabajo = _trabajo(usuario, tmp_path, "sombreado", source_path=origen)
        with pytest.raises(PlanNoValido) as fallo:
            MotorSombreado().plan(trabajo)
        assert fallo.value.codigo == codigo
        assert _huella(origen) == antes


class TestElVeredictoDelSombreado:
    def _verificar(self, monkeypatch, usuario, tmp_path, salida_info):
        origen = _info()
        monkeypatch.setattr(procesar, "_gdalinfo", lambda ruta: origen)
        monkeypatch.setattr(procesar, "_estadisticas", lambda ruta: salida_info)
        salida = tmp_path / "sombra.tif"
        salida.write_bytes(b"x" * 10)
        return MotorSombreado().verificar(_trabajo(usuario, tmp_path, "sombreado"), salida)

    def test_mismo_tamano_ubicacion_y_un_byte_pasa(self, monkeypatch, usuario, tmp_path):
        v = self._verificar(monkeypatch, usuario, tmp_path, _info(tipo="Byte", sin_dato=False))
        assert v.correcta, v.motivo

    def test_otro_tamano_no_pasa(self, monkeypatch, usuario, tmp_path):
        info = _info(tipo="Byte", sin_dato=False, tamano=(99, 100))
        assert not self._verificar(monkeypatch, usuario, tmp_path, info).correcta

    def test_otra_ubicacion_no_pasa(self, monkeypatch, usuario, tmp_path):
        info = _info(tipo="Byte", sin_dato=False, origen=(495001.0, 7318100.0))
        assert not self._verificar(monkeypatch, usuario, tmp_path, info).correcta

    def test_float_no_es_un_sombreado(self, monkeypatch, usuario, tmp_path):
        assert not self._verificar(monkeypatch, usuario, tmp_path, _info()).correcta

    def test_si_pierde_el_crs_no_pasa(self, monkeypatch, usuario, tmp_path):
        info = _info(tipo="Byte", sin_dato=False, epsg=None)
        v = self._verificar(monkeypatch, usuario, tmp_path, info)
        assert not v.correcta and "ningún sistema" in v.motivo


# --- Apagado y encendido (regla 4) ----------------------------------------------------------------


class TestLaDisponibilidad:
    @staticmethod
    def _gdal(monkeypatch, *, hay=True, proj=True, herramientas=()):
        from types import SimpleNamespace

        from apps.engines import sondas

        monkeypatch.setattr(
            sondas,
            "sondar_gdal",
            lambda: SimpleNamespace(disponible=hay, version="GDAL 3.12", motivo="no está"),
        )
        monkeypatch.setattr(
            sondas,
            "sondar_proj",
            lambda: SimpleNamespace(
                disponible=proj, codigo_motivo="proj-descolocado", mensaje="m", sugerencia="s"
            ),
        )
        monkeypatch.setattr(
            procesar, "_bin", lambda n: __file__ if n in herramientas else str(Path("no") / n)
        )

    @pytest.mark.parametrize("motor", [MotorRecorteRaster, MotorMosaico, MotorSombreado])
    def test_sin_gdal_se_apagan_con_motivo(self, monkeypatch, motor):
        self._gdal(monkeypatch, hay=False)
        estado = motor().disponibilidad()
        assert not estado.disponible and estado.codigo_motivo == "motor-no-disponible"

    @pytest.mark.parametrize("motor", [MotorRecorteRaster, MotorMosaico, MotorSombreado])
    def test_con_proj_descolocado_dice_proj_descolocado(self, monkeypatch, motor):
        self._gdal(monkeypatch, proj=False)
        assert motor().disponibilidad().codigo_motivo == "proj-descolocado"

    def test_sin_gdaldem_el_sombreado_sale_apagado_con_el_motivo_de_siempre(self, monkeypatch):
        self._gdal(monkeypatch, herramientas=("gdal_translate",))
        estado = MotorSombreado().disponibilidad()
        assert not estado.disponible and estado.codigo_motivo == "sin-gdaldem"
        celda = registry.celda(ParDeFormatos("geotiff", "cog"), "sombreado")
        assert celda.codigo_motivo == "sin-gdaldem" and celda.estado != "disponible"

    def test_sin_gdalbuildvrt_el_mosaico_dice_cual_falta(self, monkeypatch):
        self._gdal(monkeypatch, herramientas=("gdal_translate",))
        estado = MotorMosaico().disponibilidad()
        assert not estado.disponible and "gdalbuildvrt" in estado.mensaje

    def test_sin_gdalwarp_el_recorte_dice_cual_falta(self, monkeypatch):
        self._gdal(monkeypatch, herramientas=("ogr2ogr",))
        assert "gdalwarp" in MotorRecorteRaster().disponibilidad().mensaje

    @pytest.mark.parametrize(
        ("motor", "herramientas"),
        [
            (MotorRecorteRaster, ("gdalwarp", "ogr2ogr")),
            (MotorMosaico, ("gdalbuildvrt", "gdal_translate")),
            (MotorSombreado, ("gdaldem", "gdal_translate")),
        ],
    )
    def test_con_todo_instalado_se_enciende(self, monkeypatch, motor, herramientas):
        self._gdal(monkeypatch, herramientas=herramientas)
        estado = motor().disponibilidad()
        assert estado.disponible and estado.version == "GDAL 3.12"

    def test_todo_motivo_que_usan_existe_en_el_catalogo_y_los_sin_tienen_paso(self):
        from apps.engines import equipo
        from apps.jobs import motivos

        for codigo in ("sin-gdaldem", "crs-distintos", "recorte-vacio", "crs-ausente"):
            assert codigo in motivos.MOTIVOS
        assert "sin-gdaldem" in equipo.PASOS


# --- El corredor traduce la parada y elige el proceso -------------------------------------------


class _ProcesoDeMentira(MotorDeMentira):
    id = "proceso-de-mentira"
    operacion = "recorte"

    def __init__(self, fallo=None, **kw):
        super().__init__("proceso-de-mentira", **kw)
        self._fallo = fallo

    def plan(self, trabajo):
        if self._fallo:
            raise self._fallo
        return super().plan(trabajo)


class TestElCorredor:
    @pytest.fixture
    def registro_limpio(self):
        guardado = registry.todos()
        registry.limpiar()
        yield
        registry.limpiar()
        for motor in guardado:
            registry.registrar(motor)

    def _origen(self, tmp_path):
        from apps.formats.tests.constructor import geotiff_minimo

        ruta = tmp_path / "orto.tif"
        ruta.write_bytes(geotiff_minimo(bandas=3))
        return ruta

    def _job(self, usuario, origen, tmp_path, operacion):
        return ConversionJob.objects.create(
            owner=usuario,
            source_path=str(origen),
            source_name=origen.name,
            target_format_code="cog",
            output_path=str(tmp_path / "salida.tif"),
            options={"operacion": operacion} if operacion else {},
        )

    def test_una_parada_del_plan_llega_con_su_codigo_y_el_original_queda_igual(
        self, usuario, tmp_path, registro_limpio
    ):
        registry.registrar(
            _ProcesoDeMentira(fallo=PlanNoValido("El polígono no declara CRS.", "crs-ausente"))
        )
        origen = self._origen(tmp_path)
        antes = _huella(origen)
        job = self._job(usuario, origen, tmp_path, "recorte")
        resultado = runner.ejecutar(job)
        job.refresh_from_db()
        assert resultado.estado == "error"
        assert job.reason_code == "crs-ausente" and "polígono" in job.reason_detail
        assert _huella(origen) == antes
        assert not (tmp_path / "salida.tif").exists()

    def test_la_operacion_del_trabajo_elige_el_proceso_y_no_la_conversion(
        self, usuario, tmp_path, registro_limpio
    ):
        registry.registrar(MotorDeMentira(escribe="conversion"))
        registry.registrar(_ProcesoDeMentira(escribe="proceso"))
        origen = self._origen(tmp_path)
        proceso = self._job(usuario, origen, tmp_path, "recorte")
        assert runner.ejecutar(proceso).estado == "done"
        proceso.refresh_from_db()
        assert proceso.engine_id == "proceso-de-mentira"
        assert (tmp_path / "salida.tif").read_text() == "proceso"
        (tmp_path / "salida.tif").unlink()
        conversion = self._job(usuario, origen, tmp_path, "")
        assert runner.ejecutar(conversion).estado == "done"
        conversion.refresh_from_db()
        assert conversion.engine_id == "mentira"

    def test_sin_el_proceso_instalado_dice_por_que(self, usuario, tmp_path, registro_limpio):
        registry.registrar(MotorDeMentira())
        origen = self._origen(tmp_path)
        job = self._job(usuario, origen, tmp_path, "recorte")
        resultado = runner.ejecutar(job)
        assert resultado.estado == "error" and resultado.codigo_motivo == "sin-motor"

    def test_un_plan_con_un_error_cualquiera_sigue_siendo_error_del_motor(
        self, usuario, tmp_path, registro_limpio
    ):
        registry.registrar(_ProcesoDeMentira(fallo=ValueError("roto")))
        job = self._job(usuario, self._origen(tmp_path), tmp_path, "recorte")
        assert runner.ejecutar(job).codigo_motivo == "error-del-motor"


# --- Contra GDAL de verdad ------------------------------------------------------------------------

sin_gdal = pytest.mark.skipif(
    shutil.which("gdalinfo") is None
    and not Path(r"C:\Program Files\QGIS 4.0.2\bin").exists()
    and not os.environ.get("AEROCONVERT_GDAL_BIN"),
    reason="GDAL no esta en esta maquina",
)

LADO_PX = 100
ESTE0, NORTE0 = 495000.0, 7318000.0


def _gdal(programa, *argumentos, salida=False):
    resultado = subprocess.run(  # noqa: S603 - argumentos fijos; el programa es de GDAL
        [raster._bin(programa), *argumentos],
        check=True, capture_output=True, text=True, timeout=300,
        env=os.environ | raster.entorno_de_gdal(GDAL_PAM_ENABLED="NO"),
    )  # fmt: skip
    return resultado.stdout if salida else None


def _gdalinfo_stats(ruta: Path) -> dict:
    """El oráculo: `gdalinfo -json -stats`, otro programa que el que escribió el archivo."""
    return json.loads(_gdal("gdalinfo", "-json", "-stats", str(ruta), salida=True))


def _estad(info: dict, banda: int = 0) -> dict[str, float]:
    meta = info["bands"][banda]["metadata"][""]
    return {
        k.removeprefix("STATISTICS_"): float(v)
        for k, v in meta.items()
        if k.startswith("STATISTICS_")
    }


def _raster(tmp_path, nombre, valores, *, este0=ESTE0, norte0=NORTE0, epsg=UTM19S, sin_dato=True):
    """Un GeoTIFF Float32 de 1 m de píxel con los `valores` dados (fila 0 = norte)."""
    filas, columnas = len(valores), len(valores[0])
    asc = tmp_path / f"{nombre}.asc"
    with asc.open("w", newline="\n") as f:
        f.write(
            f"ncols {columnas}\nnrows {filas}\nxllcorner {este0}\nyllcorner {norte0}\ncellsize 1\n"
        )
        if sin_dato:
            f.write("NODATA_value -9999\n")
        for fila in valores:
            f.write(" ".join(f"{v:.5f}" for v in fila) + "\n")
    tif = tmp_path / f"{nombre}.tif"
    crs = ["-a_srs", f"EPSG:{epsg}"] if epsg else []
    _gdal("gdal_translate", "-q", *crs, "-ot", "Float32", str(asc), str(tif))
    asc.unlink()
    return tif


def _filas_y_columnas():
    return [[1000.0 * r + c for c in range(LADO_PX)] for r in range(LADO_PX)]


@pytest.mark.oraculo
@sin_gdal
class TestRecorteContraGdal:
    """Cada píxel vale `1000·fila + columna` (fila 0 = norte): lo que sale es una fórmula."""

    def _recortar(self, usuario, tmp_path, origen, destino="geotiff", **opciones):
        registry.limpiar()
        raster.registrar_todos()
        trabajo = _trabajo(
            usuario,
            tmp_path,
            "recorte",
            destino=destino,
            source_path=origen,
            source_size_bytes=origen.stat().st_size,
            options={"recorte_crs": f"EPSG:{UTM19S}", **opciones},
        )
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        return resultado, trabajo

    def test_un_rectangulo_deja_exactamente_los_pixeles_de_dentro(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        antes = _huella(origen)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_vertices=RECTANGULO)
        assert resultado.estado == "done", trabajo.reason_detail

        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [40, 40]
        assert info["cornerCoordinates"]["upperLeft"] == [495020.0, 7318070.0]
        assert "32719" in info["coordinateSystem"]["wkt"].split("ID[")[-1]
        # Columnas 20..59 y filas 30..69 (de arriba): la fórmula, no una segunda lectura.
        e = _estad(info)
        assert e["MINIMUM"] == 1000 * 30 + 20
        assert e["MAXIMUM"] == 1000 * 69 + 59
        assert e["MEAN"] == pytest.approx(1000 * 49.5 + 39.5)
        assert len(info["bands"]) == 1  # el original declara «sin dato»: no hace falta alfa
        assert _huella(origen) == antes

    def test_sin_dato_declarado_lo_de_fuera_lleva_alfa_y_no_un_cero(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas(), sin_dato=False)
        # Triángulo corrido un cuarto de píxel: un píxel entra si su **centro** cae dentro,
        # es decir, si columna <= fila. Hay 100·101/2 de 100·100 posibles, y la ventana entera
        # es 100 × 100 (el oráculo vio que `-crop_to_cutline` dejaba 99 filas).
        triangulo = "495000 7318000.25; 495100.25 7318000.25; 495000 7318100.25"
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_vertices=triangulo)
        assert resultado.estado == "done", trabajo.reason_detail

        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [100, 100]
        assert [b["colorInterpretation"] for b in info["bands"]] == ["Gray", "Alpha"]
        validos = sum(1 for r in range(LADO_PX) for c in range(LADO_PX) if c <= r)
        assert validos == 5050
        # La media del alfa (0 ó 255) es 255 por la fracción de píxeles válidos.
        assert _estad(info, 1)["MEAN"] == pytest.approx(255 * validos / LADO_PX**2, abs=0.01)
        # Y en la banda de datos, los de dentro son los suyos: el mínimo es el de la esquina
        # (fila 0, columna 0) y el máximo el de la esquina de abajo (fila 99, columna 99).
        e = _estad(info)
        assert e["MAXIMUM"] == 1000 * 99 + 99
        assert e["MINIMUM"] == 0

    def test_un_triangulo_con_sin_dato_declarado_cuenta_los_validos(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        triangulo = "495000 7318000.25; 495100.25 7318000.25; 495000 7318100.25"
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_vertices=triangulo)
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        esperados = [1000.0 * r + c for r in range(LADO_PX) for c in range(LADO_PX) if c <= r]
        e = _estad(info)
        assert e["VALID_PERCENT"] == pytest.approx(100 * len(esperados) / LADO_PX**2, abs=0.01)
        assert e["MEAN"] == pytest.approx(sum(esperados) / len(esperados), rel=1e-6)
        assert e["MINIMUM"] == min(esperados) and e["MAXIMUM"] == max(esperados)

    def test_el_mismo_poligono_dado_en_grados_recorta_lo_mismo(self, usuario, tmp_path):
        from pyproj import Transformer

        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        a_grados = Transformer.from_crs(UTM19S, 4326, always_xy=True)
        vertices = [
            a_grados.transform(*par)
            for par in ((495020, 7318030), (495060, 7318030), (495060, 7318070), (495020, 7318070))
        ]
        texto = "; ".join(f"{lon!r} {lat!r}" for lon, lat in vertices)
        resultado, trabajo = self._recortar(
            usuario, tmp_path, origen, recorte_vertices=texto, recorte_crs="EPSG:4326"
        )
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [40, 40]
        assert _estad(info)["MEAN"] == pytest.approx(1000 * 49.5 + 39.5, abs=1e-3)

    def test_un_poligono_que_cae_en_otro_sitio_se_para_sin_dejar_salida(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        antes = _huella(origen)
        resultado, trabajo = self._recortar(
            usuario, tmp_path, origen, recorte_vertices="0 0; 10 0; 10 10"
        )
        assert resultado.estado == "error" and trabajo.reason_code == "recorte-vacio"
        assert _huella(origen) == antes
        assert not list(tmp_path.glob("salida*"))

    def test_sin_crs_declarado_se_para_y_no_se_adivina(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        antes = _huella(origen)
        registry.limpiar()
        raster.registrar_todos()
        trabajo = _trabajo(
            usuario,
            tmp_path,
            "recorte",
            source_path=origen,
            options={"recorte_vertices": RECTANGULO},  # sin `recorte_crs`
        )
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        assert resultado.estado == "error" and trabajo.reason_code == "crs-ausente"
        assert _huella(origen) == antes
        assert not list(tmp_path.glob("salida*"))

    def test_un_archivo_de_poligono_geojson_con_su_crs_recorta_igual(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        zona = tmp_path / "zona.geojson"
        zona.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32719"}},
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [495020, 7318030],
                                        [495060, 7318030],
                                        [495060, 7318070],
                                        [495020, 7318070],
                                        [495020, 7318030],
                                    ]
                                ],
                            },
                        }
                    ],
                }
            ),
            newline="\n",
        )
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_archivo=str(zona))
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [40, 40]
        assert _estad(info)["MEAN"] == pytest.approx(1000 * 49.5 + 39.5)

    def _shapefile(self, tmp_path, con_prj: bool) -> Path:
        """El polígono del rectángulo en un Shapefile, hecho por `ogr2ogr` desde un GeoJSON."""
        geojson = tmp_path / "zona_origen.geojson"
        geojson.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [495020, 7318030],
                                        [495060, 7318030],
                                        [495060, 7318070],
                                        [495020, 7318070],
                                        [495020, 7318030],
                                    ]
                                ],
                            },
                        }
                    ],
                }
            ),
            newline="\n",
        )
        zona = tmp_path / "zona.shp"
        _gdal(
            "ogr2ogr", "-f", "ESRI Shapefile", "-a_srs", f"EPSG:{UTM19S}", str(zona), str(geojson)
        )  # fmt: skip
        if not con_prj:
            zona.with_suffix(".prj").unlink()
        return zona

    def test_un_shapefile_con_su_prj_recorta_igual(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        zona = self._shapefile(tmp_path, con_prj=True)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_archivo=str(zona))
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [40, 40]
        assert _estad(info)["MEAN"] == pytest.approx(1000 * 49.5 + 39.5)

    def test_un_shapefile_sin_prj_se_para_y_no_se_adivina(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        antes = _huella(origen)
        zona = self._shapefile(tmp_path, con_prj=False)
        resultado, trabajo = self._recortar(usuario, tmp_path, origen, recorte_archivo=str(zona))
        assert resultado.estado == "error" and trabajo.reason_code == "crs-ausente"
        assert _huella(origen) == antes
        assert not list(tmp_path.glob("salida*"))

    def test_el_destino_cog_sale_cog(self, usuario, tmp_path):
        origen = _raster(tmp_path, "modelo", _filas_y_columnas())
        resultado, trabajo = self._recortar(
            usuario, tmp_path, origen, destino="cog", recorte_vertices=RECTANGULO
        )
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"
        assert not list(tmp_path.glob("*.parcial*")) and not list(tmp_path.glob("*.aux.xml"))


@pytest.mark.oraculo
@sin_gdal
class TestMosaicoContraGdal:
    """Dos mitades de 50 × 100 y de valor constante: el mosaico mide 100 × 100 y de media 1500."""

    def _mosaico(self, usuario, tmp_path, rutas, **extra):
        registry.limpiar()
        raster.registrar_todos()
        trabajo = _trabajo(
            usuario,
            tmp_path,
            "mosaico",
            destino=extra.pop("destino", "cog"),
            source_path=rutas[0],
            source_size_bytes=sum(r.stat().st_size for r in rutas),
            **extra,
        )
        _entradas(trabajo, rutas)
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        return resultado, trabajo

    def _mitades(self, tmp_path, **extra):
        a = _raster(tmp_path, "oeste", [[1000.0] * 50 for _ in range(100)], **extra)
        b = _raster(
            tmp_path, "este", [[2000.0] * 50 for _ in range(100)], este0=ESTE0 + 50, **extra
        )
        return [a, b]

    def test_une_dos_mitades_en_un_cog_de_la_union_de_sus_extensiones(self, usuario, tmp_path):
        rutas = self._mitades(tmp_path)
        antes = [_huella(r) for r in rutas]
        resultado, trabajo = self._mosaico(usuario, tmp_path, rutas)
        assert resultado.estado == "done", trabajo.reason_detail

        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [100, 100]
        assert info["cornerCoordinates"]["upperLeft"] == [ESTE0, NORTE0 + 100]
        assert info["cornerCoordinates"]["lowerRight"] == [ESTE0 + 100, NORTE0]
        e = _estad(info)
        assert (e["MINIMUM"], e["MAXIMUM"], e["MEAN"]) == (1000, 2000, 1500)
        assert info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"
        assert "32719" in info["coordinateSystem"]["wkt"].split("ID[")[-1]
        assert [_huella(r) for r in rutas] == antes  # ningún original se tocó
        assert not list(tmp_path.glob("*.parcial*")) and not list(tmp_path.glob("*.vrt"))

    def test_donde_se_solapan_gana_la_ultima_entrada(self, usuario, tmp_path):
        a = _raster(tmp_path, "debajo", [[1000.0] * 100 for _ in range(100)])
        b = _raster(tmp_path, "encima", [[2000.0] * 50 for _ in range(100)], este0=ESTE0 + 50)
        resultado, trabajo = self._mosaico(usuario, tmp_path, [a, b], destino="geotiff")
        assert resultado.estado == "done", trabajo.reason_detail
        e = _estad(_gdalinfo_stats(Path(trabajo.output_path)))
        assert e["MEAN"] == pytest.approx(1500)  # mitad 1000 (debajo) y mitad 2000 (encima)

    def test_con_un_hueco_entre_imagenes_el_hueco_es_sin_dato_y_no_cero(self, usuario, tmp_path):
        a = _raster(tmp_path, "oeste", [[1000.0] * 40 for _ in range(100)])
        b = _raster(tmp_path, "este", [[2000.0] * 40 for _ in range(100)], este0=ESTE0 + 60)
        resultado, trabajo = self._mosaico(usuario, tmp_path, [a, b], destino="geotiff")
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [100, 100]
        e = _estad(info)
        assert e["VALID_PERCENT"] == pytest.approx(80)
        assert e["MINIMUM"] == 1000  # un cero del hueco habría bajado el mínimo

    def test_crs_distintos_se_para_con_su_codigo_sin_tocar_nada(self, usuario, tmp_path):
        a = _raster(tmp_path, "oeste", [[1000.0] * 50 for _ in range(100)])
        b = _raster(tmp_path, "este", [[2000.0] * 50 for _ in range(100)], epsg=32718)
        antes = [_huella(r) for r in (a, b)]
        resultado, trabajo = self._mosaico(usuario, tmp_path, [a, b])
        assert resultado.estado == "error" and trabajo.reason_code == "crs-distintos"
        assert [_huella(r) for r in (a, b)] == antes
        assert not list(tmp_path.glob("salida*"))


@pytest.mark.oraculo
@sin_gdal
class TestSombreadoContraGdal:
    """Un plano `z = 0,5·este`: pendiente constante (26,565°), mira al oeste (aspecto 270°).

    La iluminación es entonces una constante, `255·(cos Z·cos S + sen Z·sen S·cos(Az − A))`, con
    `Z = 90° − altura`: se calcula, no se lee de `gdaldem`. Es lo que el visor muestra.
    """

    @staticmethod
    def _esperado(altura_deg, azimut_deg, dz_dx, aspecto_deg=270.0):
        s = math.atan(dz_dx)
        z = math.radians(90 - altura_deg)
        luz = math.cos(z) * math.cos(s) + math.sin(z) * math.sin(s) * math.cos(
            math.radians(azimut_deg - aspecto_deg)
        )
        return 255 * luz

    def _sombrear(self, usuario, tmp_path, origen, destino="geotiff", **opciones):
        registry.limpiar()
        raster.registrar_todos()
        trabajo = _trabajo(
            usuario,
            tmp_path,
            "sombreado",
            destino=destino,
            source_path=origen,
            source_size_bytes=origen.stat().st_size,
            options=opciones,
        )
        resultado = runner.ejecutar(trabajo)
        trabajo.refresh_from_db()
        return resultado, trabajo

    @staticmethod
    def _plano(tmp_path, pendiente=0.5):
        return _raster(
            tmp_path, "plano", [[pendiente * c for c in range(LADO_PX)] for _ in range(LADO_PX)]
        )

    @pytest.mark.parametrize(
        ("altura", "azimut", "exageracion", "dz_dx"),
        [(45, 315, 1.0, 0.5), (30, 270, 1.0, 0.5), (30, 270, 2.0, 1.0), (60, 90, 1.0, 0.5)],
    )
    def test_la_iluminacion_de_un_plano_es_la_de_la_formula(
        self, usuario, tmp_path, altura, azimut, exageracion, dz_dx
    ):
        origen = self._plano(tmp_path)
        antes = _huella(origen)
        resultado, trabajo = self._sombrear(
            usuario,
            tmp_path,
            origen,
            altura_deg=altura,
            azimut_deg=azimut,
            exageracion_z=exageracion,
        )
        assert resultado.estado == "done", trabajo.reason_detail
        info = _gdalinfo_stats(Path(trabajo.output_path))
        assert info["size"] == [LADO_PX, LADO_PX] and info["bands"][0]["type"] == "Byte"
        esperado = self._esperado(altura, azimut, dz_dx)
        # Los bordes de la malla se calculan con vecinos que no existen: el oráculo mira el
        # interior (2 px adentro), donde la iluminación de un plano es una sola constante.
        interior = tmp_path / "interior.tif"
        _gdal(
            "gdal_translate", "-q", "-srcwin", "2", "2", "96", "96",
            trabajo.output_path, str(interior),
        )  # fmt: skip
        e = _estad(_gdalinfo_stats(interior))
        assert e["MINIMUM"] == e["MAXIMUM"] == pytest.approx(esperado, abs=1.0)
        assert info["geoTransform"] == [ESTE0, 1.0, 0.0, NORTE0 + LADO_PX, 0.0, -1.0]
        assert _huella(origen) == antes

    def test_sale_cog_y_sin_restos(self, usuario, tmp_path):
        resultado, trabajo = self._sombrear(usuario, tmp_path, self._plano(tmp_path), destino="cog")
        assert resultado.estado == "done", trabajo.reason_detail
        assert (
            _gdalinfo_stats(Path(trabajo.output_path))["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"]
            == "COG"
        )
        assert sorted(p.name for p in tmp_path.iterdir()) == ["plano.tif", "salida.tif"]

    def test_una_imagen_no_se_sombrea_y_el_original_queda_igual(self, usuario, tmp_path):
        rgb = tmp_path / "orto.tif"
        _gdal(
            "gdal_create", "-q", "-of", "GTiff", "-outsize", "20", "20", "-bands", "3",
            "-ot", "Byte", "-a_srs", f"EPSG:{UTM19S}", "-a_ullr", "0", "20", "20", "0", str(rgb),
        )  # fmt: skip
        antes = _huella(rgb)
        resultado, trabajo = self._sombrear(usuario, tmp_path, rgb)
        assert resultado.estado == "error" and trabajo.reason_code == "error-del-motor"
        assert _huella(rgb) == antes

    def test_un_modelo_sin_crs_se_para_y_no_se_adivina(self, usuario, tmp_path):
        sin_crs = _raster(
            tmp_path, "sin_crs", [[0.5 * c for c in range(LADO_PX)] for _ in range(20)], epsg=None
        )
        antes = _huella(sin_crs)
        resultado, trabajo = self._sombrear(usuario, tmp_path, sin_crs)
        assert resultado.estado == "error" and trabajo.reason_code == "crs-ausente"
        assert _huella(sin_crs) == antes
