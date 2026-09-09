"""El formulario generado desde lo que el motor declara.

La razón de que exista este módulo es que hubo **dos** listas de lo que el motor acepta —la
declarada y la del formulario— y se desincronizaron sin que nada fallara. Estas pruebas
cierran esa puerta.
"""

import pytest

from apps.engines import formulario as fmr
from apps.engines.base import Motor, OpcionDeMotor, ParDeFormatos, PlanDeEjecucion


class MotorConOpciones(Motor):
    id = "conopciones"
    familia = "prueba"

    def __init__(self, opciones_=()):
        self._opciones = tuple(opciones_)

    def pares(self):
        return frozenset({ParDeFormatos("geotiff", "cog")})

    def disponibilidad(self):
        from apps.engines.base import Disponibilidad

        return Disponibilidad.si("1.0")

    def opciones(self, par):
        return self._opciones

    def plan(self, trabajo):
        return PlanDeEjecucion(argv=("x",), ruta_de_salida="x")


PAR = ParDeFormatos("geotiff", "cog")


class TestConstruir:
    def test_un_motor_sin_opciones_da_un_formulario_vacio(self):
        formulario = fmr.construir(MotorConOpciones(), PAR)
        assert formulario.hay_campos is False

    def test_cada_campo_arranca_con_el_valor_por_omision_del_motor(self):
        motor = MotorConOpciones([OpcionDeMotor("calidad", "Calidad", "entero", por_defecto=25)])
        formulario = fmr.construir(motor, PAR)
        assert formulario.valores == {"calidad": 25}

    def test_los_valores_dados_ganan_al_por_omision(self):
        motor = MotorConOpciones([OpcionDeMotor("calidad", "Calidad", "entero", por_defecto=25)])
        formulario = fmr.construir(motor, PAR, {"calidad": 40})
        assert formulario.valores == {"calidad": 40}

    def test_el_campo_expone_lo_que_la_plantilla_necesita_sin_decidir(self):
        """La plantilla solo dibuja. Si tuviera que decidir el tipo, habría un `if` por
        formato dentro del HTML y volveríamos a tener dos listas."""
        motor = MotorConOpciones(
            [
                OpcionDeMotor("a", "A", "eleccion", por_defecto="x", elecciones=(("x", "X"),)),
                OpcionDeMotor("b", "B", "booleano", por_defecto=True),
                OpcionDeMotor("c", "C", "entero", por_defecto=1, minimo=0, maximo=9),
            ]
        )
        campos = {c.nombre: c for c in fmr.construir(motor, PAR).campos}
        assert campos["a"].es_eleccion and not campos["a"].es_numero
        assert campos["b"].es_booleano and campos["b"].marcado
        assert campos["c"].es_numero and campos["c"].paso == "1"

    def test_un_decimal_deja_teclear_decimales(self):
        """Con `step=1` el navegador rechaza `2,5` antes de enviarlo, y la persona no
        entiende por qué."""
        motor = MotorConOpciones([OpcionDeMotor("g", "GSD", "decimal", por_defecto=2.5)])
        assert fmr.construir(motor, PAR).campos[0].paso == "any"


class TestLeer:
    def test_solo_devuelve_lo_declarado(self):
        """Lo que sobra se descarta sin avisar: no lo mandó la persona, lo mandó una pestaña
        abierta desde ayer o alguien probando."""
        motor = MotorConOpciones([OpcionDeMotor("calidad", "Calidad", "entero", por_defecto=25)])
        leido = fmr.leer(motor, PAR, {"calidad": "40", "inventado": "sí", "BIGTIFF": "NO"})
        assert leido == {"calidad": 40}

    def test_convierte_al_tipo_declarado(self):
        motor = MotorConOpciones(
            [
                OpcionDeMotor("n", "N", "entero", por_defecto=1),
                OpcionDeMotor("d", "D", "decimal", por_defecto=1.0),
                OpcionDeMotor("b", "B", "booleano", por_defecto=False),
            ]
        )
        leido = fmr.leer(motor, PAR, {"n": "7", "d": "2.5", "b": "on"})
        assert leido == {"n": 7, "d": 2.5, "b": True}

    def test_acepta_la_coma_decimal(self):
        """Es lo que teclea quien tiene el teclado en español. Rechazarla sería pedantear
        con la persona en vez de con el dato."""
        motor = MotorConOpciones([OpcionDeMotor("d", "D", "decimal", por_defecto=1.0)])
        assert fmr.leer(motor, PAR, {"d": "2,5"}) == {"d": 2.5}

    def test_un_booleano_que_no_llega_es_falso(self):
        """Una casilla desmarcada no viaja en el POST. Sin esta rama, desmarcarla no haría
        nada -- que es justo el fallo silencioso que este módulo existe para evitar."""
        motor = MotorConOpciones([OpcionDeMotor("b", "B", "booleano", por_defecto=True)])
        assert fmr.leer(motor, PAR, {}) == {"b": False}

    def test_una_eleccion_fuera_de_la_lista_se_rechaza(self):
        motor = MotorConOpciones(
            [
                OpcionDeMotor(
                    "c",
                    "Compresión",
                    "eleccion",
                    por_defecto="DEFLATE",
                    elecciones=(("DEFLATE", "d"), ("LZW", "l")),
                )
            ]
        )
        with pytest.raises(fmr.OpcionInvalida) as fallo:
            fmr.leer(motor, PAR, {"c": "ZSTD"})
        assert fallo.value.nombre == "c"
        assert "Compresión" in fallo.value.mensaje

    def test_un_numero_que_no_es_numero_se_rechaza_con_un_mensaje_util(self):
        motor = MotorConOpciones([OpcionDeMotor("n", "Calidad", "entero", por_defecto=25)])
        with pytest.raises(fmr.OpcionInvalida) as fallo:
            fmr.leer(motor, PAR, {"n": "mucha"})
        assert "Calidad" in fallo.value.mensaje
        assert "mucha" in fallo.value.mensaje

    @pytest.mark.parametrize("valor", ["0", "101"])
    def test_se_respetan_el_minimo_y_el_maximo(self, valor):
        """Un `QUALITY=999` no puede inyectar nada -- el argv es una lista -- pero llega a
        GDAL, que falla veinte minutos después con un mensaje que no menciona la opción."""
        motor = MotorConOpciones(
            [OpcionDeMotor("q", "Calidad", "entero", por_defecto=25, minimo=1, maximo=100)]
        )
        with pytest.raises(fmr.OpcionInvalida):
            fmr.leer(motor, PAR, {"q": valor})

    def test_un_numero_vacio_cae_al_por_omision(self):
        motor = MotorConOpciones([OpcionDeMotor("q", "Q", "entero", por_defecto=25)])
        assert fmr.leer(motor, PAR, {"q": ""}) == {"q": 25}


class TestContraElMotorDeVerdad:
    """Sobre el motor GDAL real, que es lo que va a estar en producción."""

    def test_todo_lo_que_declara_se_puede_leer_y_convertir(self):
        from apps.raster.motores import MotorGdalRaster

        motor = MotorGdalRaster()
        for destino in ("geotiff", "cog", "jp2", "img", "asc"):
            par = ParDeFormatos("geotiff", destino)
            declaradas = motor.opciones(par)
            # Se envían los valores por omisión de vuelta: tienen que sobrevivir la ida y
            # la vuelta sin que ninguno se rechace a sí mismo.
            datos = {o.nombre: o.por_defecto for o in declaradas}
            datos = {k: ("1" if v is True else v) for k, v in datos.items()}
            leido = fmr.leer(motor, par, datos)
            assert set(leido) == {o.nombre for o in declaradas}, destino

    def test_los_ajustes_cambian_con_el_formato(self):
        """JP2 tiene calidad y GeoTIFF tiene tamaño de tesela. Es la razón de que el
        formulario se pida otra vez al cambiar el destino."""
        from apps.raster.motores import MotorGdalRaster

        motor = MotorGdalRaster()
        geotiff = {o.nombre for o in motor.opciones(ParDeFormatos("geotiff", "geotiff"))}
        jp2 = {o.nombre for o in motor.opciones(ParDeFormatos("geotiff", "jp2"))}
        assert "tamano_tesela" in geotiff
        assert "calidad" in jp2
        assert geotiff != jp2
