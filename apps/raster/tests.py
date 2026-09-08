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

from apps.engines.base import ParDeFormatos
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
        assert plan.argv[-1].endswith("salida.tif.parcial")

    def test_nunca_se_escribe_directamente_en_el_destino(self, usuario, tmp_path):
        """Escritura atomica: primero el parcial, y solo tras verificar se renombra."""
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert plan.argv[-1] != str(plan.ruta_de_salida)
        assert plan.argv[-1].endswith(".parcial")


class TestElMotorTieneQueHablar:
    """Silenciar a GDAL rompe dos cosas a la vez, y la segunda es grave.

    Sin salida no hay barra de progreso -- molesto -- y **no hay senales para el detector
    de atasco** -- peligroso: en un raster que tarda mas que el umbral de silencio, un motor
    perfectamente sano se daria por atascado y se mataria a si mismo.
    """

    def test_nunca_se_silencia_la_conversion(self, usuario, tmp_path):
        plan = MotorGdalRaster().plan(_trabajo(usuario, tmp_path))
        assert "-q" not in plan.argv

    def test_gdalwarp_pide_el_avance_explicitamente(self, usuario, tmp_path):
        """`gdal_translate` lo emite solo; `gdalwarp` hay que pedirselo."""
        job = _trabajo(usuario, tmp_path, target_crs_authority="EPSG", target_crs_code="32718")
        assert "-progress" in MotorGdalRaster().plan(job).argv

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
        assert plan.posteriores[0][-6].endswith(".parcial")

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

        origen = tmp_path / "orto.tif"
        origen.write_bytes(geotiff_minimo(ancho=256, alto=256, bandas=1, epsg=32719))
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
        assert job.verification["ancho_px"] == 256
