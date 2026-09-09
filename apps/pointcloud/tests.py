"""Los motores de nubes: que el comando de PDAL salga bien, y que lo que no se puede lo diga."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.engines import registry
from apps.engines.base import NO_SOPORTADO, ParDeFormatos, ruta_parcial
from apps.formats.tests.constructor import copc_minimo, las_minimo
from apps.jobs.models import ConversionJob
from apps.pointcloud.motores import MotorPdalE57, MotorPdalNubes, MotorReCap

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _trabajo(usuario, tmp_path, **extra):
    origen = tmp_path / "nube.las"
    if not origen.exists():
        origen.write_bytes(las_minimo(puntos=9_618_692))
    campos = {
        "owner": usuario,
        "source_path": str(origen),
        "source_name": "nube.las",
        "source_size_bytes": 278_900_000,
        "source_format_code": "las",
        "source_crs_authority": "EPSG",
        "source_crs_code": "32719",
        "target_format_code": "copc",
        "output_path": str(tmp_path / "salida.copc.laz"),
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


class TestElComando:
    def test_usa_pdal_translate(self, usuario, tmp_path):
        assert MotorPdalNubes().plan(_trabajo(usuario, tmp_path)).argv[1] == "translate"

    def test_el_escritor_va_explicito(self, usuario, tmp_path):
        """`.laz` no dice si se quiere un LAZ corriente o un COPC, y esa es justo la
        distinción que importa para AeroBim."""
        argv = MotorPdalNubes().plan(_trabajo(usuario, tmp_path)).argv
        assert argv[argv.index("-w") + 1] == "writers.copc"

    def test_el_parcial_conserva_la_extension_compuesta(self, usuario, tmp_path):
        """`nube.copc.laz` tiene que quedar como `nube.parcial.copc.laz`, no como
        `nube.copc.laz.parcial`: PDAL no escribe ni lee lo segundo."""
        plan = MotorPdalNubes().plan(_trabajo(usuario, tmp_path))
        assert plan.argv[3] == str(ruta_parcial(tmp_path / "salida.copc.laz"))
        assert plan.argv[3].endswith(".copc.laz")

    def test_laz_pide_compresion_y_las_no(self, usuario, tmp_path):
        laz = MotorPdalNubes().plan(_trabajo(usuario, tmp_path, target_format_code="laz")).argv
        crudo = MotorPdalNubes().plan(_trabajo(usuario, tmp_path, target_format_code="las")).argv
        assert "--writers.las.compression=laszip" in laz
        assert "--writers.las.compression=none" in crudo

    def test_el_forward_lleva_el_nombre_del_escritor_que_se_paso(self, usuario, tmp_path):
        """Pedir `--writers.las.forward` cuando el escritor es `writers.copc` no se ignora:
        PDAL responde «Argument references invalid/unused stage» y **no escribe nada**."""
        job = _trabajo(usuario, tmp_path, options={"conservar_metadatos": True})
        argv = MotorPdalNubes().plan(job).argv
        assert "--writers.copc.forward=all" in argv
        assert "--writers.las.forward=all" not in argv


class TestDiezmado:
    def test_por_omision_no_diezma(self, usuario, tmp_path):
        argv = MotorPdalNubes().plan(_trabajo(usuario, tmp_path)).argv
        assert "sample" not in argv

    def test_con_separacion_se_anade_la_etapa(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, options={"separacion_minima_m": 0.25})
        argv = MotorPdalNubes().plan(job).argv
        assert "sample" in argv
        assert "--filters.sample.radius=0.25" in argv


class TestReproyeccion:
    def test_reproyectar_declara_los_dos_sistemas(self, usuario, tmp_path):
        """PDAL necesita el de origen explícito: si lo deduce mal, mueve la nube sin
        avisar."""
        job = _trabajo(usuario, tmp_path, target_crs_authority="EPSG", target_crs_code="32718")
        argv = MotorPdalNubes().plan(job).argv
        assert "reprojection" in argv
        assert "--filters.reprojection.out_srs=EPSG:32718" in argv
        assert "--filters.reprojection.in_srs=EPSG:32719" in argv

    def test_reproyectar_va_antes_de_diezmar(self, usuario, tmp_path):
        """Diezmar por radio en grados no significa nada."""
        job = _trabajo(
            usuario,
            tmp_path,
            target_crs_code="32718",
            options={"separacion_minima_m": 0.5},
        )
        argv = list(MotorPdalNubes().plan(job).argv)
        assert argv.index("reprojection") < argv.index("sample")


class TestElSilencioDePdal:
    """PDAL no dice nada mientras trabaja, y eso hay que declararlo.

    Sin `emite_progreso=False`, el detector de atasco del runner mataría un trabajo
    perfectamente sano en cuanto pasara del umbral de silencio — y una nube de diez millones
    de puntos lo pasa.
    """

    def test_el_plan_lo_declara(self, usuario, tmp_path):
        plan = MotorPdalNubes().plan(_trabajo(usuario, tmp_path))
        assert plan.emite_progreso is False
        assert plan.analizador_de_progreso is None

    def test_el_presupuesto_crece_con_los_puntos(self, usuario, tmp_path):
        """Es el único detector que queda cuando la herramienta calla, así que tiene que
        dar de sí."""
        plan = MotorPdalNubes().plan(_trabajo(usuario, tmp_path))
        assert plan.timeout_s >= 600


class TestE57:
    """Separado del motor general por la misma razón que ECW lo está del de ráster."""

    def test_declara_sus_pares_este_o_no_disponible(self):
        pares = MotorPdalE57().pares()
        assert ParDeFormatos("e57", "copc") in pares
        assert ParDeFormatos("las", "e57") in pares

    def test_su_motivo_distingue_falta_el_controlador_de_falta_pdal(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(sondas, "_controladores_pdal", lambda _: frozenset({"readers.las"}))
        monkeypatch.setattr(sondas, "_ejecutable", lambda *_: "pdal")
        estado = MotorPdalE57().disponibilidad()
        assert estado.codigo_motivo == "sin-driver-pdal"
        assert "copc" in estado.alternativas


class TestReCap:
    """RCS y RCP están en el catálogo **para poder decir que no se pueden**."""

    def test_nunca_esta_disponible(self):
        assert MotorReCap().disponibilidad().disponible is False

    def test_su_indisponibilidad_es_irremediable(self):
        """No es «falta instalar algo»: no hay lector abierto ni lo va a haber. Marcarlo
        como instalable mandaría a alguien a buscar un paquete que no existe."""
        assert MotorReCap().disponibilidad().irremediable is True

    def test_trae_el_remedio_escrito(self):
        estado = MotorReCap().disponibilidad()
        assert "ReCap" in estado.sugerencia
        assert "E57" in estado.sugerencia
        assert "e57" in estado.alternativas

    def test_su_celda_queda_no_soportada_y_no_instalable(self):
        guardado = registry.todos()
        registry.limpiar()
        try:
            registry.registrar(MotorReCap())
            celda = registry.celda(ParDeFormatos("rcs", "las"))
            assert celda.estado == NO_SOPORTADO
            # Y aun así trae motivo y remedio, que es lo que la separa de un hueco vacío.
            assert celda.mensaje
            assert celda.sugerencia
        finally:
            registry.limpiar()
            for motor in guardado:
                registry.registrar(motor)


class TestVerificacion:
    def test_una_perdida_de_puntos_no_pedida_invalida_la_salida(
        self, usuario, tmp_path, monkeypatch
    ):
        """El fallo silencioso propio de esta familia: una conversión que se come la mitad
        de la nube deja un archivo que abre, se ve bien, y le falta media obra."""
        from apps.pointcloud import motores

        salida = tmp_path / "salida.copc.laz"
        salida.write_bytes(copc_minimo(puntos=5_000_000))
        monkeypatch.setattr(motores, "_pdal_info", lambda _: {"num_points": 5_000_000})

        veredicto = MotorPdalNubes().verificar(_trabajo(usuario, tmp_path), salida)

        assert veredicto.correcta is False
        assert veredicto.codigo_motivo == "salida-invalida"

    def test_si_se_pidio_diezmar_perder_puntos_es_lo_esperado(self, usuario, tmp_path, monkeypatch):
        from apps.pointcloud import motores

        salida = tmp_path / "salida.copc.laz"
        salida.write_bytes(copc_minimo(puntos=1_000_000))
        monkeypatch.setattr(motores, "_pdal_info", lambda _: {"num_points": 1_000_000})
        job = _trabajo(usuario, tmp_path, options={"separacion_minima_m": 0.5})

        assert MotorPdalNubes().verificar(job, salida).correcta is True

    def test_conservar_todos_los_puntos_pasa(self, usuario, tmp_path, monkeypatch):
        from apps.pointcloud import motores

        salida = tmp_path / "salida.copc.laz"
        salida.write_bytes(copc_minimo(puntos=9_618_692))
        monkeypatch.setattr(
            motores,
            "_pdal_info",
            lambda _: {
                "num_points": 9_618_692,
                "bounds": {"minx": 0, "maxx": 370, "miny": 0, "maxy": 369, "minz": 0, "maxz": 25},
            },
        )

        veredicto = MotorPdalNubes().verificar(_trabajo(usuario, tmp_path), salida)

        assert veredicto.correcta is True
        assert veredicto.detalles["puntos"] == 9_618_692
        assert veredicto.detalles["extension_m"][0] == 370.0

    def test_si_pdal_no_puede_leer_lo_que_escribio_es_invalida(
        self, usuario, tmp_path, monkeypatch
    ):
        from apps.pointcloud import motores

        salida = tmp_path / "salida.copc.laz"
        salida.write_bytes(copc_minimo())
        monkeypatch.setattr(motores, "_pdal_info", lambda _: None)

        assert MotorPdalNubes().verificar(_trabajo(usuario, tmp_path), salida).correcta is False


class TestLosPares:
    def test_no_se_ofrece_convertir_algo_a_si_mismo(self):
        for par in MotorPdalNubes().pares():
            assert par.origen != par.destino

    def test_las_a_copc_esta(self):
        assert ParDeFormatos("las", "copc") in MotorPdalNubes().pares()


class TestBinario:
    def test_se_usa_el_pdal_configurado(self, usuario, tmp_path):
        import os

        falso = tmp_path / ("pdal.exe" if os.name == "nt" else "pdal")
        falso.write_text("")
        with override_settings(PDAL_BIN=str(tmp_path)):
            assert MotorPdalNubes().plan(_trabajo(usuario, tmp_path)).argv[0] == str(falso)
