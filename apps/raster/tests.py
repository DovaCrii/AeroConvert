"""El motor GDAL: que el comando salga entero y en orden.

Casi todo esto corre **sin GDAL instalado**, porque lo que se comprueba es el plan, no la
ejecucion. Es el motivo de que un motor describa en vez de ejecutar.

Al final hay unas pocas pruebas marcadas `@pytest.mark.oraculo` que si convierten de verdad
y le preguntan a `gdalinfo` si el resultado sirve. Esas quedan fuera del gate.
"""

import shutil
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.engines.base import ParDeFormatos, ruta_parcial
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs.models import ConversionJob
from apps.raster.motores import MotorEcw, MotorGdalRaster, analizar_progreso

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _trabajo(usuario, tmp_path, **extra):
    origen = tmp_path / "orto.tif"
    if not origen.exists():
        origen.write_bytes(geotiff_minimo(bandas=4))
    campos = {
        "owner": usuario,
        "source_path": str(origen),
        "source_name": "orto.tif",
        "source_size_bytes": 500_000_000,
        "source_format_code": "geotiff",
        "source_crs_authority": "EPSG",
        "source_crs_code": "32719",
        "target_format_code": "cog",
        "output_path": str(tmp_path / "salida.tif"),
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


def _co(argv) -> dict[str, str]:
    """Las opciones de creacion del argv, como diccionario."""
    salida = {}
    for i, token in enumerate(argv):
        if token == "-co" and i + 1 < len(argv):
            clave, _, valor = argv[i + 1].partition("=")
            salida[clave] = valor
    return salida


class TestLectorEstricto:
    """B-04: un `.asc` se lee solo con el controlador de ASCII Grid, no con el que dicte el
    contenido; si no, un VRT disfrazado leería otros archivos del disco."""

    def test_un_asc_pide_el_lector_de_ascii_grid(self, usuario, tmp_path):
        origen = tmp_path / "terreno.asc"
        origen.write_text("ncols 1\n", encoding="utf-8")
        trabajo = _trabajo(usuario, tmp_path, source_path=str(origen), source_format_code="asc")
        argv = MotorGdalRaster().plan(trabajo).argv
        assert argv[argv.index("-if") + 1] == "AAIGrid"
        assert argv.index("-if") < argv.index(str(origen))

    def test_un_geotiff_no_lleva_if(self, usuario, tmp_path):
        assert "-if" not in MotorGdalRaster().plan(_trabajo(usuario, tmp_path)).argv


class TestEleccionDeHerramienta:
    def test_sin_reproyectar_usa_gdal_translate(self, usuario, tmp_path):
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert "gdal_translate" in plan.argv[0]

    def test_reproyectar_usa_gdalwarp(self, usuario, tmp_path):
        """`gdal_translate -a_srs` **no reproyecta**: reetiqueta. Usarlo esperando
        reproyeccion deja la ortofoto en el sitio equivocado con un CRS que dice lo
        contrario, y en silencio."""
        job = _trabajo(usuario, tmp_path, target_crs_authority="EPSG", target_crs_code="32718")
        plan = MotorGdalRaster().plan(job)
        assert "gdalwarp" in plan.argv[0]
        assert "-t_srs" in plan.argv
        assert plan.argv[plan.argv.index("-t_srs") + 1] == "EPSG:32718"

    def test_el_origen_y_el_destino_van_al_final_y_en_ese_orden(self, usuario, tmp_path):
        """GDAL los toma posicionales. Invertirlos sobrescribe el original."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.argv[-2] == str(tmp_path / "orto.tif")
        assert plan.argv[-1] == str(ruta_parcial(tmp_path / "salida.tif"))

    def test_nunca_se_escribe_directamente_en_el_destino(self, usuario, tmp_path):
        """Escritura atomica: primero el parcial, y solo tras verificar se renombra."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.argv[-1] != str(plan.ruta_de_salida)
        assert ".parcial." in plan.argv[-1]

    def test_el_parcial_conserva_la_extension(self, usuario, tmp_path):
        """GDAL infiere cosas de la extensión, así que el temporal tiene que conservarla.
        Con `salida.tif.parcial` la conversión funcionaba y la verificación no."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.argv[-1].endswith(".tif")


class TestElMotorTieneQueHablar:
    """Silenciar a GDAL rompe dos cosas a la vez, y la segunda es grave.

    Sin salida no hay barra de progreso -- molesto -- y **no hay senales para el detector
    de atasco** -- peligroso: en un raster que tarda mas que el umbral de silencio, un motor
    perfectamente sano se daria por atascado y se mataria a si mismo.
    """

    def test_nunca_se_silencia_la_conversion(self, usuario, tmp_path):
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert "-q" not in plan.argv

    def test_gdalwarp_no_lleva_argumentos_que_gdal_rechaza(self, usuario, tmp_path):
        """`-progress` no existe: los dos programas emiten el avance solos. Esto se afirmaba al
        reves, y una prueba que afirma la presencia de un argumento no prueba que GDAL lo acepte;
        lo prueba la que convierte de verdad (`test_reproyectar_...`, con `gdalwarp` real)."""
        job = _trabajo(usuario, tmp_path, target_crs_authority="EPSG", target_crs_code="32718")
        argv = MotorGdalRaster().plan(job).argv
        assert "-progress" not in argv and "-q" not in argv

    def test_el_plan_trae_analizador_de_progreso(self, usuario, tmp_path):
        """Emitir avance no sirve de nada si nadie lo lee."""
        assert (
            MotorGdalRaster().plan(_trabajo(usuario, tmp_path)).analizador_de_progreso is not None
        )


class TestBigtiff:
    """La opcion que resuelve el caso que origino la aplicacion."""

    def test_geotiff_fuerza_tiff_clasico(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="geotiff")
        assert _co(MotorGdalRaster().plan(job).argv)["BIGTIFF"] == "NO"

    def test_bigtiff_como_destino_lo_pide_explicito(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="bigtiff")
        assert _co(MotorGdalRaster().plan(job).argv)["BIGTIFF"] == "YES"

    def test_cog_usa_if_safer_y_no_if_needed(self, usuario, tmp_path):
        """`IF_NEEDED` estima sobre el tamano **sin comprimir** y se equivoca con salidas
        comprimidas que luego crecen. `IF_SAFER` deja margen."""
        job = _trabajo(usuario, tmp_path, target_format_code="cog")
        assert _co(MotorGdalRaster().plan(job).argv)["BIGTIFF"] == "IF_SAFER"


class TestCompresion:
    def test_deflate_por_omision(self, usuario, tmp_path):
        """Medido: 33 MB menos que LZW siendo igual de exacto."""
        job = _trabajo(usuario, tmp_path, target_format_code="geotiff")
        assert _co(MotorGdalRaster().plan(job).argv)["COMPRESS"] == "DEFLATE"

    def test_deflate_y_lzw_llevan_predictor(self, usuario, tmp_path):
        """Sin el predictor horizontal, sobre datos de imagen comprimen la mitad."""
        for compresion in ("DEFLATE", "LZW"):
            job = _trabajo(
                usuario, tmp_path, target_format_code="geotiff", options={"compresion": compresion}
            )
            assert _co(MotorGdalRaster().plan(job).argv)["PREDICTOR"] == "2"

    def test_jpeg_no_lleva_predictor(self, usuario, tmp_path):
        """El predictor es para compresores sin perdida; con JPEG no significa nada."""
        job = _trabajo(
            usuario, tmp_path, target_format_code="geotiff", options={"compresion": "JPEG"}
        )
        assert "PREDICTOR" not in _co(MotorGdalRaster().plan(job).argv)


class TestBandas:
    def test_por_omision_se_copian_todas(self, usuario, tmp_path):
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert "-b" not in plan.argv

    def test_solo_rgb_descarta_la_cuarta(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, options={"solo_rgb": True})
        argv = MotorGdalRaster().plan(job).argv
        bandas = [argv[i + 1] for i, t in enumerate(argv) if t == "-b"]
        assert bandas == ["1", "2", "3"]


class TestPiramides:
    def test_se_piden_con_un_gdaladdo_aparte(self, usuario, tmp_path):
        """No hay forma de pedirselas a `gdal_translate`."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path, target_format_code="geotiff"))
        assert len(plan.posteriores) == 1
        assert "gdaladdo" in plan.posteriores[0][0]
        assert plan.posteriores[0][-5:] == ("2", "4", "8", "16", "32")

    def test_se_construyen_sobre_el_parcial_no_sobre_el_destino(self, usuario, tmp_path):
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path, target_format_code="geotiff"))
        assert ".parcial." in plan.posteriores[0][-6]

    def test_cog_no_las_pide_dos_veces(self, usuario, tmp_path):
        """El controlador COG las construye solo; pedirlas otra vez las duplicaria dentro."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path, target_format_code="cog"))
        assert plan.posteriores == ()

    @pytest.mark.parametrize("destino", ["jp2", "ecw", "asc", "png", "jpeg", "webp", "cog"])
    def test_nunca_se_piden_donde_generarian_un_ovr_al_lado(self, usuario, tmp_path, destino):
        """La lección más cara de esta fase, y salió de medirla.

        `gdaladdo` solo escribe las pirámides **dentro** del archivo cuando el controlador
        admite abrirlo para actualizar. Con cualquier otro deja un `.ovr` al lado: sobre la
        ortofoto de 14.526 × 14.443 eran **360 MB pegados a un JP2 de 63 MB**.

        Rompe las dos promesas a la vez — el entregable deja de ser un solo archivo que se
        basta a sí mismo, y el disco del servidor se llena con seis veces lo pedido.
        """
        job = _trabajo(usuario, tmp_path, target_format_code=destino)
        motor = MotorEcw() if destino == "ecw" else MotorGdalRaster()
        assert motor.plan(job).posteriores == ()

    @pytest.mark.parametrize("destino", ["geotiff", "bigtiff", "img"])
    def test_si_se_piden_donde_van_dentro(self, usuario, tmp_path, destino):
        job = _trabajo(usuario, tmp_path, target_format_code=destino)
        assert len(MotorGdalRaster().plan(job).posteriores) == 1

    def test_el_formulario_no_las_ofrece_donde_no_caben(self, usuario, tmp_path):
        """La regla de siempre: el formulario no puede ofrecer lo que el motor no hará."""
        nombres = {o.nombre for o in MotorGdalRaster().opciones(ParDeFormatos("geotiff", "jp2"))}
        assert "piramides" not in nombres
        nombres = {
            o.nombre for o in MotorGdalRaster().opciones(ParDeFormatos("geotiff", "geotiff"))
        }
        assert "piramides" in nombres

    def test_se_pueden_desactivar(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="geotiff", options={"piramides": ""})
        assert MotorGdalRaster().plan(job).posteriores == ()


class TestJp2SeBastaASiMismo:
    """El entregable tiene que llevar la georreferencia dentro, sin `.j2w` al lado."""

    def test_pide_las_dos_cajas_de_georreferencia(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="jp2")
        creacion = _co(MotorGdalRaster().plan(job).argv)
        assert creacion["GeoJP2"] == "YES"
        assert creacion["GMLJP2"] == "YES"

    def test_la_calidad_por_omision_es_la_medida(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="jp2")
        assert _co(MotorGdalRaster().plan(job).argv)["QUALITY"] == "25"


class TestEntornoDelHijo:
    def test_acota_la_memoria_de_gdal(self, usuario, tmp_path):
        """Sin tope, GDAL se come la memoria y la estacion empieza a paginar."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.env["GDAL_CACHEMAX"] == "512"

    def test_el_path_de_gdal_va_al_hijo_no_al_servidor(self, usuario, tmp_path):
        import os

        with override_settings(GDAL_BIN=r"C:\gdal\bin"):
            plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.env["PATH"].startswith(r"C:\gdal\bin")
        assert os.environ.get("PATH", "").startswith(r"C:\gdal\bin") is False


class TestPresupuestoDeTiempo:
    def test_escala_con_el_tamano(self, usuario, tmp_path):
        pequeno = _trabajo(usuario, tmp_path, source_size_bytes=1_000_000)
        grande = _trabajo(usuario, tmp_path, source_size_bytes=40_000_000_000)
        assert MotorGdalRaster().plan(grande).timeout_s > MotorGdalRaster().plan(pequeno).timeout_s

    def test_nunca_baja_de_diez_minutos(self, usuario, tmp_path):
        """Un presupuesto corto convierte un arranque lento en un fallo."""
        job = _trabajo(usuario, tmp_path, source_size_bytes=1)
        assert MotorGdalRaster().plan(job).timeout_s >= 600


class TestEcw:
    def test_la_clave_va_en_el_entorno_y_nunca_en_el_argv(self, usuario, tmp_path):
        """El argv se guarda **entero** en la bitacora. Una clave ahi seria una clave
        filtrada a cualquiera que pueda leer el historial."""
        centinela = "CLAVE-SECRETA-QUE-NO-DEBE-APARECER"
        job = _trabajo(usuario, tmp_path, target_format_code="ecw")

        with override_settings(ECW_ENCODE_KEY=centinela, ECW_ENCODE_COMPANY="JEJ"):
            plan = MotorEcw().plan(job)

        assert centinela not in " ".join(plan.argv)
        assert plan.env["ECW_ENCODE_KEY"] == centinela

    def test_sin_clave_no_se_pone_nada_en_el_entorno(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="ecw")
        with override_settings(ECW_ENCODE_KEY="", ECW_ENCODE_COMPANY=""):
            plan = MotorEcw().plan(job)
        assert "ECW_ENCODE_KEY" not in plan.env

    def test_el_controlador_es_ecw(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="ecw")
        plan = MotorEcw().plan(job)
        assert plan.argv[plan.argv.index("-of") + 1] == "ECW"

    def test_no_pide_piramides_aparte(self, usuario, tmp_path):
        """ECW es wavelet: lleva su propia piramide por construccion."""
        job = _trabajo(usuario, tmp_path, target_format_code="ecw")
        assert MotorEcw().plan(job).posteriores == ()

    def test_declara_los_pares_hacia_ecw_esté_o_no_disponible(self):
        pares = MotorEcw().pares()
        assert ParDeFormatos("geotiff", "ecw") in pares
        assert all(p.destino == "ecw" for p in pares)


class TestOpcionesDeclaradas:
    """De aqui se genera el formulario, asi que no puede ofrecer lo que el motor no sabe."""

    def test_cada_opcion_tiene_etiqueta_y_tipo(self, usuario, tmp_path):
        for par in (ParDeFormatos("geotiff", "cog"), ParDeFormatos("geotiff", "jp2")):
            for opcion in MotorGdalRaster().opciones(par):
                assert opcion.etiqueta
                assert opcion.tipo in ("texto", "entero", "decimal", "eleccion", "booleano")

    def test_las_elecciones_traen_valor_y_texto(self, usuario, tmp_path):
        for opcion in MotorGdalRaster().opciones(ParDeFormatos("geotiff", "cog")):
            if opcion.tipo == "eleccion":
                assert all(len(e) == 2 for e in opcion.elecciones)

    def test_el_valor_por_omision_esta_entre_las_elecciones(self, usuario, tmp_path):
        for opcion in MotorGdalRaster().opciones(ParDeFormatos("geotiff", "cog")):
            if opcion.tipo == "eleccion":
                valores = [v for v, _ in opcion.elecciones]
                assert opcion.por_defecto in valores, opcion.nombre


class TestRemuestreoYNodata:
    """F16.6: lo que `plan()` ya leía y nadie podía poner, y el valor «sin dato»."""

    def _plan(self, usuario, tmp_path, **extra):
        return MotorGdalRaster().plan(_trabajo(usuario, tmp_path, **extra))

    def test_el_remuestreo_se_declara_para_que_el_formulario_lo_pueda_poner(self):
        nombres = [o.nombre for o in MotorGdalRaster().opciones(ParDeFormatos("geotiff", "cog"))]
        assert "remuestreo" in nombres

    def test_el_remuestreo_llega_al_argumento_solo_si_se_reproyecta(self, usuario, tmp_path):
        con = self._plan(
            usuario,
            tmp_path,
            target_crs_authority="EPSG",
            target_crs_code="32718",
            options={"remuestreo": "near"},
        )
        i = con.argv.index("-r")
        assert con.argv[i + 1] == "near" and "gdalwarp" in con.argv[0]
        sin = self._plan(usuario, tmp_path, options={"remuestreo": "near"})
        assert "-r" not in sin.argv, "sin reproyectar no hay nada que remuestrear"

    def test_por_omision_sigue_siendo_cubica(self, usuario, tmp_path):
        plan = self._plan(usuario, tmp_path, target_crs_authority="EPSG", target_crs_code="32718")
        assert plan.argv[plan.argv.index("-r") + 1] == "cubic"

    def test_un_remuestreo_que_no_se_ofrece_no_llega_al_comando(self, usuario, tmp_path):
        with pytest.raises(ValueError, match="no es un remuestreo"):
            self._plan(
                usuario,
                tmp_path,
                target_crs_authority="EPSG",
                target_crs_code="32718",
                options={"remuestreo": "cubic -co EVIL=1"},
            )

    def test_nodata_solo_se_ofrece_donde_el_archivo_lo_guarda(self):
        motor = MotorGdalRaster()
        con = {"geotiff", "bigtiff", "cog", "img", "asc"}
        for destino in ("geotiff", "bigtiff", "cog", "img", "asc", "png", "webp", "jp2"):
            nombres = [o.nombre for o in motor.opciones(ParDeFormatos("geotiff", destino))]
            assert ("nodata" in nombres) == (destino in con), destino

    def test_nodata_sin_reproyectar_es_a_nodata(self, usuario, tmp_path):
        plan = self._plan(usuario, tmp_path, options={"nodata": -9999})
        assert plan.argv[plan.argv.index("-a_nodata") + 1] == "-9999.0"
        assert "-dstnodata" not in plan.argv

    def test_nodata_al_reproyectar_es_dstnodata(self, usuario, tmp_path):
        plan = self._plan(
            usuario,
            tmp_path,
            target_crs_authority="EPSG",
            target_crs_code="32718",
            options={"nodata": 0},
        )
        assert plan.argv[plan.argv.index("-dstnodata") + 1] == "0.0"
        assert "-a_nodata" not in plan.argv

    def test_el_cero_es_un_valor_y_el_vacio_no_hace_nada(self, usuario, tmp_path):
        assert "-a_nodata" in self._plan(usuario, tmp_path, options={"nodata": 0}).argv
        for vacio in (None, ""):
            assert "-a_nodata" not in self._plan(usuario, tmp_path, options={"nodata": vacio}).argv

    def test_el_formulario_valida_ambas(self):
        from apps.engines import formulario

        par = ParDeFormatos("geotiff", "cog")
        motor = MotorGdalRaster()
        assert formulario.leer(motor, par, {"remuestreo": "near", "nodata": "-9999,5"}) == {
            "solo_rgb": False,
            "remuestreo": "near",
            "nodata": -9999.5,
        }
        with pytest.raises(formulario.OpcionInvalida):
            formulario.leer(motor, par, {"remuestreo": "magico"})
        with pytest.raises(formulario.OpcionInvalida):
            formulario.leer(motor, par, {"nodata": "mucho"})
        with pytest.raises(formulario.OpcionInvalida):
            formulario.leer(motor, par, {"nodata": "1e300"})


class TestAnalizadorDeProgreso:
    def test_lee_el_formato_de_gdal(self):
        assert analizar_progreso("0...10...20...30") == pytest.approx(0.30)
        assert analizar_progreso("0...10...100 - done.") == pytest.approx(1.0)

    def test_ignora_lo_que_no_es_progreso(self):
        assert analizar_progreso("ERROR 4: no such file") is None


# --- Con GDAL de verdad -----------------------------------------------------

sin_gdal = pytest.mark.skipif(
    shutil.which("gdalinfo") is None and not Path(r"C:\Program Files\QGIS 4.0.2\bin").exists(),
    reason="GDAL no esta en esta maquina",
)


@pytest.mark.oraculo
@sin_gdal
class TestContraGdalDeVerdad:
    """Convierte de verdad y le pregunta a `gdalinfo` si el resultado sirve.

    Fuera del gate a proposito: el gate tiene que ser verde en una maquina limpia.
    """

    def test_un_geotiff_se_convierte_a_cog_y_conserva_el_crs(self, usuario, tmp_path):
        from apps.engines import registry
        from apps.jobs import runner

        registry.limpiar()
        registry.registrar(MotorGdalRaster())

        # `geotiff_minimo` declara las teselas pero no las escribe: GDAL 3.12 lo rechaza con
        # «Cannot read 8192 bytes». Esta prueba llevaba tiempo sin correr (está fuera del gate).
        origen = self._tablero(tmp_path)
        job = _trabajo(
            usuario,
            tmp_path,
            source_path=str(origen),
            source_size_bytes=origen.stat().st_size,
            target_format_code="cog",
        )

        resultado = runner.ejecutar(job)
        job.refresh_from_db()

        assert resultado.estado == "done", job.reason_detail
        assert job.verification["epsg"] == "32719"
        assert job.verification["ancho_px"] == 64

    # --- F16.6: remuestreo y nodata, leídos por `gdalinfo`, que no escribió el archivo ----------

    def _tablero(self, tmp_path) -> Path:
        """Un GeoTIFF de 64 × 64 en cuadros de 2 px, solo 0 y 255, georreferenciado."""
        import subprocess

        from PIL import Image

        from apps.raster.motores import _bin

        imagen = Image.new("L", (64, 64))
        imagen.putdata(
            [255 if ((x // 2) + (y // 2)) % 2 else 0 for y in range(64) for x in range(64)]
        )
        png = tmp_path / "tablero.png"
        imagen.save(png)
        destino = tmp_path / "tablero.tif"
        subprocess.run(  # noqa: S603 - argumentos fijos; los programas son los de GDAL
            [
                _bin("gdal_translate"), "-q", "-a_srs", "EPSG:32719",
                "-a_ullr", "495000", "7318900", "495064", "7318836", str(png), str(destino),
            ],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip
        return destino

    def _convertir(self, usuario, tmp_path, origen, **extra):
        from apps.engines import registry
        from apps.jobs import runner

        registry.limpiar()
        registry.registrar(MotorGdalRaster())
        job = _trabajo(
            usuario,
            tmp_path,
            source_path=str(origen),
            source_size_bytes=origen.stat().st_size,
            target_format_code="geotiff",
            output_path=str(tmp_path / "salida.tif"),
            **extra,
        )
        resultado = runner.ejecutar(job)
        job.refresh_from_db()
        assert resultado.estado == "done", job.reason_detail
        return Path(job.output_path)

    def _gdalinfo(self, ruta: Path, *extra: str) -> dict:
        import json
        import subprocess

        from apps.raster.motores import _bin

        salida = subprocess.run(  # noqa: S603 - argumentos fijos
            [_bin("gdalinfo"), "-json", *extra, str(ruta)],
            check=True, capture_output=True, text=True, timeout=120,
        )  # fmt: skip
        return json.loads(salida.stdout)

    def test_nodata_queda_declarado_en_el_archivo(self, usuario, tmp_path):
        salida = self._convertir(
            usuario,
            tmp_path,
            self._tablero(tmp_path),
            options={"nodata": 0, "piramides": ""},
        )
        banda = self._gdalinfo(salida)["bands"][0]
        assert banda["noDataValue"] == 0

    def test_sin_nodata_el_archivo_no_declara_ninguno(self, usuario, tmp_path):
        salida = self._convertir(
            usuario, tmp_path, self._tablero(tmp_path), options={"piramides": ""}
        )
        assert "noDataValue" not in self._gdalinfo(salida)["bands"][0]

    def _valores_distintos(self, ruta: Path) -> int:
        banda = self._gdalinfo(ruta, "-hist")["bands"][0]
        return sum(1 for cuenta in banda["histogram"]["buckets"] if cuenta)

    def test_vecino_mas_cercano_no_inventa_valores_y_bilineal_si(self, usuario, tmp_path):
        tablero = self._tablero(tmp_path)
        valores = {}
        for remuestreo in ("near", "bilinear"):
            carpeta = tmp_path / remuestreo
            carpeta.mkdir()
            salida = self._convertir(
                usuario,
                carpeta,
                tablero,
                target_crs_authority="EPSG",
                target_crs_code="32718",
                options={"remuestreo": remuestreo, "piramides": ""},
            )
            valores[remuestreo] = self._valores_distintos(salida)
        assert valores["near"] == 2, "solo 0 y 255: el vecino más cercano conserva los valores"
        assert valores["bilinear"] > 2, "el bilineal mezcla y crea grises que no existían"
