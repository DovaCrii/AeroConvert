"""Los catálogos de tubería, y sobre todo lo que se comprueba antes de escribir.

## Qué se puede probar sin Access, que es casi todo lo que importa

El trabajo con la base lo hace ACE, que solo existe en Windows: en el CI —Ubuntu, sin GDAL y
sin Office— no hay controlador. Eso **no** deja esta capa sin pruebas, porque lo que puede
hacer daño de verdad no es leer una tabla: es **decidir qué se escribe y qué se rechaza**, y esa
decisión es una función de un esquema y una cabecera. Se construyen los dos a mano.

Lo que se salta sin controlador es el viaje completo, que está marcado y se corre en la
estación de trabajo.

## Por qué la validación es lo crítico

Un catálogo al que le falta una columna **Plant 3D lo abre igual**. El fallo no aparece aquí:
aparece más tarde, cuando alguien está usando una pieza que no lleva su espesor. Por eso una
columna desconocida para el trabajo en vez de descartarse en silencio.
"""

from __future__ import annotations

import pytest

from . import catalogos
from .composicion import ComposicionInvalida

#: Sin controlador no hay base que abrir. Es el mismo trato que reciben Office y PDAL.
sin_access = pytest.mark.skipif(not catalogos.sondar(recordar=False), reason="No hay ACE aquí.")


def _tabla(nombre: str, *columnas: str) -> catalogos.Tabla:
    return catalogos.Tabla(
        nombre=nombre,
        columnas=tuple(catalogos.Columna(nombre=c, tipo="VARCHAR", tamano=50) for c in columnas),
    )


class _HojaFalsa:
    def __init__(self, cabecera):
        self._cabecera = cabecera

    def iter_rows(self, values_only=True):
        yield self._cabecera


class _LibroFalso:
    """Lo mínimo de `openpyxl` que usa `_comprobar`: los nombres y la primera fila."""

    def __init__(self, hojas: dict[str, tuple]):
        self._hojas = hojas
        self.sheetnames = list(hojas)

    def __getitem__(self, nombre):
        return _HojaFalsa(self._hojas[nombre])


class TestLaSonda:
    def test_dice_el_motivo_cuando_no_hay_controlador(self, monkeypatch):
        """**Apagada con su motivo, nunca ausente.** Ocultar una capacidad que no está hace
        parecer que nunca existió, y es la regla de la casa desde ECW."""
        monkeypatch.setattr(catalogos, "_mirar", lambda: catalogos.Disponible(motivo="No hay."))
        estado = catalogos.sondar(recordar=False)
        assert not estado
        assert estado.motivo

    def test_no_confunde_el_controlador_de_texto_con_el_de_access(self, monkeypatch):
        """Microsoft registra varios controladores con «Access» en el nombre —el de texto, el
        de dBASE— y ninguno abre una base de Access. Buscar por «Access» a secas daría
        disponible en una máquina donde no se puede hacer nada."""
        falsos = ["Microsoft Access Text Driver (*.txt, *.csv)", "Microsoft Access dBASE Driver"]
        monkeypatch.setattr(catalogos, "_mirar", lambda: _mirar_con(falsos))
        assert not catalogos.sondar(recordar=False)


def _mirar_con(controladores):
    for nombre in controladores:
        if "Access Driver" in nombre and ".mdb" in nombre:
            return catalogos.Disponible(controlador=nombre)
    return catalogos.Disponible(motivo="No hay ningún controlador de Access instalado.")


class TestLoQueSeComprueba:
    """La puerta: qué entra al catálogo y qué se rechaza. **Antes de escribir un byte.**"""

    def setup_method(self):
        self.tablas = {"pipe": _tabla("PIPE", "MATERIAL", "SCHEDULE", "PIPE_OD_M")}

    def test_una_hoja_que_no_es_ninguna_tabla_para_el_trabajo(self):
        libro = _LibroFalso({"Hoja1": ("MATERIAL",)})
        with pytest.raises(ComposicionInvalida) as fallo:
            catalogos._comprobar(libro, self.tablas, [])
        assert "Hoja1" in str(fallo.value)
        assert "PIPE" in str(fallo.value), "Hay que decir cuáles sí valen."

    def test_una_columna_que_la_tabla_no_tiene_para_el_trabajo(self):
        """**Este es el que importa.** Si alguien añadió `DN_NOMINAL` a mano esperando que
        sirva de algo, tirarla en silencio entrega un catálogo que parece correcto y no lleva
        su dato."""
        libro = _LibroFalso({"PIPE": ("MATERIAL", "DN_NOMINAL")})
        with pytest.raises(ComposicionInvalida) as fallo:
            catalogos._comprobar(libro, self.tablas, [])
        assert "DN_NOMINAL" in str(fallo.value)

    def test_una_columna_que_falta_solo_avisa(self):
        """Faltar sí se permite —queda vacía— pero se dice: puede ser deliberado, o una
        columna borrada sin querer al reordenar la hoja."""
        avisos: list[str] = []
        catalogos._comprobar(_LibroFalso({"PIPE": ("MATERIAL",)}), self.tablas, avisos)
        assert avisos and "PIPE" in avisos[0]
        assert "SCHEDULE" in avisos[0]

    def test_el_nombre_de_la_tabla_no_distingue_mayusculas(self):
        """Excel y Access no tratan igual las mayúsculas del nombre, y quien renombra una hoja
        a «Pipe» no está pidiendo otra tabla."""
        catalogos._comprobar(_LibroFalso({"Pipe": ("MATERIAL",)}), self.tablas, [])


class TestElNombreQueEntraEnLaConsulta:
    """**El `.mdb` viene de fuera, y sus nombres acaban dentro de una consulta.**

    Se interpolan entre corchetes —`SELECT * FROM [PIPE]`— porque ODBC no admite parámetros
    para identificadores: los valores sí van parametrizados, los nombres no pueden. Así que la
    única defensa es no dejar pasar el nombre, y un corchete de cierre dentro se sale del
    delimitador.
    """

    @pytest.mark.parametrize("bueno", ["PIPE", "MISC_FIT", "Tabla 1", "EC_CLASS_NAME", "A#1"])
    def test_los_normales_pasan(self, bueno):
        assert catalogos._seguro(bueno, "tabla") == bueno

    @pytest.mark.parametrize(
        "malo",
        [
            "PIPE]; DELETE FROM [BOLT",  # el que rompe el delimitador
            "PIPE] WHERE 1=1--",
            "1TABLA",  # empezar por cifra no es un identificador válido
            "",
            "T" * 100,
            "tabla;otra",
        ],
    )
    def test_los_raros_paran_aqui(self, malo):
        with pytest.raises(ComposicionInvalida):
            catalogos._seguro(malo, "tabla")

    def test_el_mensaje_no_vuelca_el_nombre_entero(self):
        """Un nombre de mil caracteres en un mensaje de error es otra forma de ensuciar la
        pantalla con lo que venía en el archivo."""
        with pytest.raises(ComposicionInvalida) as fallo:
            catalogos._seguro("]" + "x" * 500, "tabla")
        assert len(str(fallo.value)) < 200


class TestElNombreDeLaHoja:
    """Excel corta en 31 caracteres y prohíbe cinco; Access no. Sin adaptarlo, dos tablas de
    nombre largo acaban en la misma hoja — o `openpyxl` levanta a mitad de la exportación, con
    el archivo ya medio escrito."""

    def test_corta_a_treinta_y_uno(self):
        assert len(catalogos._nombre_de_hoja("T" * 60, set())) == 31

    def test_cambia_los_prohibidos_de_excel(self):
        assert catalogos._nombre_de_hoja("PIPE/OD[1]", set()) == "PIPE_OD_1_"

    def test_dos_nombres_largos_no_acaban_en_la_misma_hoja(self):
        usados: set[str] = set()
        uno = catalogos._nombre_de_hoja("CATALOGO_DE_TUBERIA_PE100_PN16_A", usados)
        otro = catalogos._nombre_de_hoja("CATALOGO_DE_TUBERIA_PE100_PN16_B", usados)
        assert uno != otro
        assert len(otro) <= 31


class TestElMensajeDeOdbc:
    def test_se_queda_con_la_parte_util(self):
        """Vienen envueltos en corchetes con el nombre del controlador y un código al final.
        Enseñar eso entero es pedirle a alguien que busque su frase dentro."""
        crudo = Exception(
            "('HY000', \"[HY000] [Microsoft][Controlador ODBC Microsoft Access] "
            'El campo es demasiado pequeño para aceptar la cantidad de datos (-1811)")'
        )
        assert catalogos._limpiar(crudo) == (
            "El campo es demasiado pequeño para aceptar la cantidad de datos"
        )

    def test_uno_que_no_tiene_esa_forma_se_devuelve_entero(self):
        assert catalogos._limpiar(Exception("algo raro")) == "algo raro"


class TestLaCelda:
    def test_un_campo_binario_no_tumba_la_exportacion(self):
        """`openpyxl` no escribe `bytes`. Un catálogo no los lleva, así que se dice cuántos son
        en vez de perder la exportación entera por una columna que nadie mira."""
        assert catalogos._a_celda(b"\x00\x01\x02") == "<3 bytes>"

    def test_lo_demas_pasa_tal_cual(self):
        assert catalogos._a_celda("PE100") == "PE100"
        assert catalogos._a_celda(None) is None
        assert catalogos._a_celda(6.6) == 6.6


@sin_access
class TestElViajeCompleto:
    """Solo donde hay Access. Se corre en la estación de trabajo, no en el CI.

    Comprobado a mano el 2026-09-15 contra `HDPE_PE100_PN16.mdb`, un catálogo de verdad de
    AutoCAD Plant 3D: nueve tablas, 481 filas, exportado a Excel, editado y reconstruido con
    las mismas filas y el cambio dentro.
    """

    def test_la_sonda_encuentra_el_controlador_de_mdb(self):
        estado = catalogos.sondar(recordar=False)
        assert ".mdb" in estado.controlador

    def test_un_archivo_que_no_esta(self, tmp_path):
        with pytest.raises(ComposicionInvalida):
            catalogos.esquema(tmp_path / "no_existe.mdb")

    def test_algo_que_no_es_una_base(self, tmp_path):
        falso = tmp_path / "falso.mdb"
        falso.write_bytes(b"esto no es una base de Access")
        with pytest.raises(ComposicionInvalida):
            catalogos.esquema(falso)
