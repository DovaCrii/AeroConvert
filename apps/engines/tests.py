"""El registro, la matriz y las sondas.

Todo con motores de mentira: **ninguna prueba de este archivo necesita GDAL instalado.** Es
la mitad del valor del contrato de motor -- que un motor describa en vez de ejecutar hace
que se pueda comprobar lo que va a hacer sin que haga nada.
"""

from pathlib import Path

import pytest
from django.test import override_settings

from apps.engines import registry, sondas
from apps.engines.base import (
    DISPONIBLE,
    INSTALABLE,
    NO_SOPORTADO,
    Disponibilidad,
    Motor,
    ParDeFormatos,
    PlanDeEjecucion,
)


class MotorDeMentira(Motor):
    """Un motor que declara pares y una disponibilidad fija. No ejecuta nada."""

    def __init__(self, identificador, pares_, disponible=True, prioridad=100, motivo=""):
        self.id = identificador
        self.nombre = identificador
        self.familia = "prueba"
        self.prioridad = prioridad
        self._pares = frozenset(ParDeFormatos(o, d) for o, d in pares_)
        self._disponible = disponible
        self._motivo = motivo

    def pares(self):
        return self._pares

    def disponibilidad(self):
        if self._disponible:
            return Disponibilidad.si("v1.0")
        return Disponibilidad.no(
            self._motivo or "motor-no-disponible",
            "No esta.",
            sugerencia="Instalalo.",
            alternativas=("cog", "jp2"),
        )

    def plan(self, trabajo):
        return PlanDeEjecucion(argv=("echo", "hola"), ruta_de_salida=Path("salida.tif"))


@pytest.fixture(autouse=True)
def registro_limpio():
    """Cada prueba arranca con el registro vacio y lo deja como estaba.

    Sin esto, los motores reales que registran las `AppConfig` al arrancar Django se
    mezclarian con los de mentira y las cuentas de la matriz dependerian del orden.
    """
    guardado = registry.todos()
    registry.limpiar()
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


class TestRegistro:
    def test_un_motor_sin_id_no_se_registra(self):
        with pytest.raises(ValueError):
            registry.registrar(MotorDeMentira("", []))

    def test_devuelve_los_motores_ordenados_por_prioridad(self):
        registry.registrar(MotorDeMentira("lento", [], prioridad=50))
        registry.registrar(MotorDeMentira("rapido", [], prioridad=10))
        assert [m.id for m in registry.todos()] == ["rapido", "lento"]

    def test_motores_para_incluye_los_no_disponibles(self):
        """Es el punto: sin ellos la matriz no podria pintar una celda apagada con su
        motivo, y una capacidad ausente se veria igual que una inexistente."""
        registry.registrar(MotorDeMentira("apagado", [("geotiff", "ecw")], disponible=False))
        encontrados = registry.motores_para(ParDeFormatos("geotiff", "ecw"))
        assert [m.id for m in encontrados] == ["apagado"]

    def test_motor_para_solo_devuelve_disponibles(self):
        registry.registrar(MotorDeMentira("apagado", [("geotiff", "ecw")], disponible=False))
        assert registry.motor_para(ParDeFormatos("geotiff", "ecw")) is None

    def test_entre_dos_disponibles_gana_la_prioridad_menor(self):
        par = [("geotiff", "cog")]
        registry.registrar(MotorDeMentira("b", par, prioridad=50))
        registry.registrar(MotorDeMentira("a", par, prioridad=10))
        assert registry.motor_para(ParDeFormatos("geotiff", "cog")).id == "a"

    def test_uno_apagado_no_tapa_a_uno_encendido(self):
        par = [("geotiff", "cog")]
        registry.registrar(MotorDeMentira("apagado", par, disponible=False, prioridad=10))
        registry.registrar(MotorDeMentira("bueno", par, prioridad=50))
        assert registry.motor_para(ParDeFormatos("geotiff", "cog")).id == "bueno"

    def test_una_familia_sin_motores_no_rompe_nada(self):
        """`pointcloud`, `vector` y `mesh` estan vacias desde la fase 0 justo para que esto
        se pruebe desde el primer dia, y no el dia que se llenen, con prisa."""
        assert registry.todos() == ()
        assert registry.matriz_de_capacidades() == {}


class TestMatriz:
    def test_una_conversion_que_nadie_sabe_es_no_soportada(self):
        celda = registry.celda(ParDeFormatos("ifc", "ecw"))
        assert celda.estado == NO_SOPORTADO
        assert celda.codigo_motivo == "sin-motor"

    def test_una_conversion_con_motor_disponible_esta_viva(self):
        registry.registrar(MotorDeMentira("bueno", [("geotiff", "cog")]))
        celda = registry.celda(ParDeFormatos("geotiff", "cog"))
        assert celda.estado == DISPONIBLE
        assert celda.se_puede is True
        assert celda.motor_id == "bueno"

    def test_una_conversion_con_motor_apagado_es_instalable_no_inexistente(self):
        """Tres estados y no dos: para quien mira, «no lo tengo instalado» y «nadie sabe
        hacerlo» son cosas distintas y llevan a acciones distintas."""
        registry.registrar(
            MotorDeMentira("ecw", [("geotiff", "ecw")], disponible=False, motivo="sin-clave-ecw")
        )
        celda = registry.celda(ParDeFormatos("geotiff", "ecw"))
        assert celda.estado == INSTALABLE
        assert celda.codigo_motivo == "sin-clave-ecw"
        assert celda.sugerencia
        assert celda.alternativas == ("cog", "jp2")

    def test_la_matriz_junta_los_pares_de_todos_los_motores(self):
        registry.registrar(MotorDeMentira("a", [("geotiff", "cog")]))
        registry.registrar(MotorDeMentira("b", [("geotiff", "jp2"), ("las", "copc")]))
        assert set(registry.matriz_de_capacidades()) == {
            ("geotiff", "cog"),
            ("geotiff", "jp2"),
            ("las", "copc"),
        }


class TestVerificacionPorOmision:
    """La regla numero uno del proyecto: el codigo de salida no prueba nada."""

    def test_sin_archivo_es_sin_salida(self, tmp_path):
        motor = MotorDeMentira("x", [])
        resultado = motor.verificar(None, tmp_path / "no-existe.tif")
        assert resultado.correcta is False
        assert resultado.codigo_motivo == "sin-salida"

    def test_un_archivo_vacio_no_pasa(self, tmp_path):
        """GDAL devuelve 0 tras dejar un archivo vacio si el controlador fallo al cerrar."""
        vacio = tmp_path / "vacio.tif"
        vacio.write_bytes(b"")
        resultado = MotorDeMentira("x", []).verificar(None, vacio)
        assert resultado.correcta is False
        assert resultado.codigo_motivo == "salida-invalida"

    def test_un_archivo_con_contenido_pasa(self, tmp_path):
        bueno = tmp_path / "bueno.tif"
        bueno.write_bytes(b"II*\x00" + bytes(100))
        resultado = MotorDeMentira("x", []).verificar(None, bueno)
        assert resultado.correcta is True
        assert resultado.detalles["bytes"] == 104


class TestSondaEcw:
    """Tres motivos distintos porque son tres arreglos distintos."""

    @pytest.fixture(autouse=True)
    def sin_cache(self):
        sondas.olvidar()
        yield
        sondas.olvidar()

    def test_un_binario_externo_que_no_existe_da_su_motivo(self):
        with override_settings(ECW_BIN=r"C:\no\existe\comprimir.exe"):
            estado = sondas.sondar_ecw()
        assert estado.codigo_motivo == "sin-binario-ecw"
        assert estado.alternativas == ("cog", "jp2")

    def test_un_binario_externo_que_existe_sirve(self, tmp_path):
        falso = tmp_path / "comprimir.exe"
        falso.write_text("")
        with override_settings(ECW_BIN=str(falso)):
            assert sondas.sondar_ecw().disponible is True

    def test_sin_controlador_ecw_lo_dice_y_ofrece_alternativas(self, monkeypatch):
        monkeypatch.setattr(
            sondas,
            "sondar_gdal",
            lambda: sondas.EstadoGdal(
                disponible=True, version="GDAL 3.12.4", controladores=frozenset({"GTIFF"})
            ),
        )
        with override_settings(ECW_BIN="", ECW_ENCODE_KEY="", ECW_ENCODE_COMPANY=""):
            estado = sondas.sondar_ecw()
        assert estado.codigo_motivo == "sin-driver-ecw"
        assert "cog" in estado.alternativas

    def test_con_controlador_pero_sin_clave_el_motivo_es_otro(self, monkeypatch):
        """Es el caso caro: el controlador **lee** siempre, asi que verlo y dar la
        escritura por buena produce un trabajo que corre veinte minutos y muere al final."""
        monkeypatch.setattr(
            sondas,
            "sondar_gdal",
            lambda: sondas.EstadoGdal(
                disponible=True,
                version="GDAL 3.12.4",
                controladores=frozenset({"GTIFF", "ECW"}),
                escribibles=frozenset({"GTIFF"}),
            ),
        )
        with override_settings(ECW_BIN="", ECW_ENCODE_KEY="", ECW_ENCODE_COMPANY=""):
            estado = sondas.sondar_ecw()
        assert estado.codigo_motivo == "sin-clave-ecw"

    def test_con_clave_pero_controlador_de_solo_lectura_tampoco_sirve(self, monkeypatch):
        monkeypatch.setattr(
            sondas,
            "sondar_gdal",
            lambda: sondas.EstadoGdal(
                disponible=True,
                version="GDAL 3.12.4",
                controladores=frozenset({"ECW"}),
                escribibles=frozenset(),
            ),
        )
        with override_settings(ECW_BIN="", ECW_ENCODE_KEY="k", ECW_ENCODE_COMPANY="e"):
            assert sondas.sondar_ecw().codigo_motivo == "sin-driver-ecw"

    def test_con_todo_en_su_sitio_esta_disponible(self, monkeypatch):
        monkeypatch.setattr(
            sondas,
            "sondar_gdal",
            lambda: sondas.EstadoGdal(
                disponible=True,
                version="GDAL 3.12.4",
                controladores=frozenset({"ECW"}),
                escribibles=frozenset({"ECW"}),
            ),
        )
        with override_settings(ECW_BIN="", ECW_ENCODE_KEY="k", ECW_ENCODE_COMPANY="e"):
            assert sondas.sondar_ecw().disponible is True

    def test_sin_gdal_no_se_culpa_a_la_clave(self, monkeypatch):
        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: sondas.EstadoGdal(disponible=False, motivo="no hay")
        )
        with override_settings(ECW_BIN=""):
            assert sondas.sondar_ecw().codigo_motivo == "motor-no-disponible"


class TestSondaOda:
    def test_sin_configurar_ni_en_el_path_da_sin_conversor(self, monkeypatch):
        monkeypatch.setattr(sondas.shutil, "which", lambda _: None)
        with override_settings(ODA_CONVERTER=""):
            estado = sondas.sondar_oda()
        assert estado.codigo_motivo == "sin-conversor"
        assert estado.alternativas == ("dxf",)

    def test_una_ruta_configurada_que_no_existe_lo_dice(self):
        with override_settings(ODA_CONVERTER=r"C:\no\existe\ODAFileConverter.exe"):
            estado = sondas.sondar_oda()
        assert estado.codigo_motivo == "sin-conversor"
        assert "no hay ningún archivo" in estado.mensaje

    def test_si_esta_en_el_path_no_hay_que_configurar_nada(self, monkeypatch, tmp_path):
        falso = tmp_path / "ODAFileConverter.exe"
        falso.write_text("")
        monkeypatch.setattr(sondas.shutil, "which", lambda _: str(falso))
        with override_settings(ODA_CONVERTER=""):
            assert sondas.sondar_oda().disponible is True

    def test_una_ruta_valida_sirve(self, tmp_path):
        falso = tmp_path / "ODAFileConverter.exe"
        falso.write_text("")
        with override_settings(ODA_CONVERTER=str(falso)):
            assert sondas.sondar_oda().disponible is True


class TestLecturaDeFormatosDeGdal:
    def test_el_patron_separa_lo_que_lee_de_lo_que_escribe(self):
        """`gdalinfo --formats` marca las capacidades entre parentesis. Confundirlas es lo
        que hace creer que se puede escribir MrSID."""
        linea = "  GTiff -raster- (rw+uvs): GeoTIFF (*.tif, *.tiff)"
        coincidencia = sondas.PATRON_FORMATO.match(linea)
        assert coincidencia.group(1) == "GTiff"
        assert "w" in coincidencia.group(2)

    def test_un_controlador_de_solo_lectura_no_declara_escritura(self):
        linea = "  MrSID -raster- (ro): Multi-resolution Seamless Image Database"
        coincidencia = sondas.PATRON_FORMATO.match(linea)
        assert coincidencia.group(1) == "MrSID"
        assert "w" not in coincidencia.group(2)

    def test_una_linea_de_cabecera_no_es_un_controlador(self):
        assert sondas.PATRON_FORMATO.match("Supported Formats:") is None
