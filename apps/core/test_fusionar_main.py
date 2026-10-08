"""`scripts/claude/fusionar_main.py`: resolver «los dos añadieron» sin fundir dos entradas en una.

Los textos de prueba reproducen los **tres choques que se repitieron** al añadir herramientas:
una entrada de diccionario junto a otra, una palabra en una tupla de sinónimos, y un símbolo del
sprite. El fallo que se vigila es el silencioso: un separador equivocado deja un diccionario con
claves repetidas, que Python acepta y que pierde una de las dos herramientas.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from django.conf import settings

RUTA = Path(settings.BASE_DIR) / "scripts" / "claude" / "fusionar_main.py"
_especificacion = importlib.util.spec_from_file_location("fusionar_main", RUTA)
fusionar = importlib.util.module_from_spec(_especificacion)
_especificacion.loader.exec_module(fusionar)

#: Dos herramientas que se añadieron a la vez: la de HEAD termina cerrando su `que_hace`, la de la
#: otra rama, también, y el cierre de la entrada es común.
DICCIONARIOS = """HERRAMIENTAS = (
    {
        "id": "a",
        "que_hace": (
            "hace a"
        ),
<<<<<<< HEAD
    },
    {
        "id": "b",
        "que_hace": (
            "hace b"
        ),
=======
    },
    {
        "id": "c",
        "que_hace": (
            "hace c"
        ),
>>>>>>> origin/main
    },
)
"""

TUPLAS = """SINONIMOS = {
    "a": (
        "uno",
        "dos",
<<<<<<< HEAD
    ),
    "b": (
        "tres",
=======
    ),
    "c": (
        "cuatro",
>>>>>>> origin/main
    ),
}
"""

SIMBOLOS = """<svg xmlns="http://www.w3.org/2000/svg">
  <symbol id="a"><path d="M0 0"/></symbol>

<<<<<<< HEAD
  <symbol id="b">
    <path d="M1 1"/>
=======
  <symbol id="c">
    <path d="M2 2"/>
>>>>>>> origin/main
  </symbol>
</svg>
"""


class TestResolverTexto:
    def test_dos_entradas_de_diccionario_quedan_como_dos(self):
        # Con un separador vacío esto «funciona» en Python y funde las dos entradas en una.
        resuelto = fusionar.resolver_texto("herramientas.py", DICCIONARIOS)
        arbol = ast.parse(resuelto)
        entradas = next(n for n in ast.walk(arbol) if isinstance(n, ast.Tuple))
        assert [e.keys[0].value for e in entradas.elts] == ["id"] * 3
        assert [e.values[0].value for e in entradas.elts] == ["a", "b", "c"]
        assert "<<<<<<<" not in resuelto and ">>>>>>>" not in resuelto

    def test_dos_tuplas_de_sinonimos_tambien(self):
        resuelto = fusionar.resolver_texto("acciones.py", TUPLAS)
        asignado = ast.literal_eval(resuelto.split("=", 1)[1].strip())
        assert asignado == {"a": ("uno", "dos"), "b": ("tres",), "c": ("cuatro",)}

    def test_dos_simbolos_del_sprite_quedan_bien_formados(self):
        from xml.etree import ElementTree as ET

        resuelto = fusionar.resolver_texto("icons.svg", SIMBOLOS)
        ids = [e.get("id") for e in ET.fromstring(resuelto)]
        assert ids == ["a", "b", "c"]

    def test_el_changelog_apila_los_dos_lados(self):
        texto = (
            "## [Sin publicar]\n<<<<<<< HEAD\n### Uno\n- a\n=======\n### Dos\n- b\n"
            ">>>>>>> origin/main\n"
        )
        resuelto = fusionar.resolver_texto("CHANGELOG.md", texto)
        assert resuelto.index("### Uno") < resuelto.index("### Dos")
        assert "<<<<<<<" not in resuelto

    def test_lo_que_no_se_sabe_resolver_se_rechaza_y_no_se_inventa(self):
        # Dos lados que cambian **la misma línea**: no hay «los dos añadieron».
        texto = "x = (\n<<<<<<< HEAD\n    1 +\n=======\n    2 *\n>>>>>>> origin/main\n    3\n)\n"
        with pytest.raises(ValueError, match="ningún separador"):
            fusionar.resolver_texto("a.py", texto, valida=lambda *_: False)

    def test_sin_conflictos_el_texto_no_cambia(self):
        assert fusionar.resolver_texto("a.py", "x = 1\n") == "x = 1\n"


class TestLaEstructuraSuma:
    """Lo que pasó el 2026-10-08: tres resultados que se leían bien y no sumaban."""

    def test_dos_llamadas_no_se_funden_en_una(self):
        texto = (
            "MOTIVOS = dict([\n"
            "    _m(\n"
            "<<<<<<< HEAD\n"
            '        "sin-ffmpeg",\n'
            '        "No hay FFmpeg.",\n'
            "=======\n"
            '        "sin-ghostscript",\n'
            '        "No hay Ghostscript.",\n'
            ">>>>>>> origin/main\n"
            "    ),\n"
            "])\n"
        )
        resultado = fusionar.resolver_texto("motivos.py", texto)
        arbol = ast.parse(resultado)
        llamadas = [
            n
            for n in ast.walk(arbol)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_m"
        ]
        assert len(llamadas) == 2 and all(len(c.args) == 2 for c in llamadas)

    def test_el_changelog_entero_dos_veces_se_rechaza(self):
        texto = (
            "# Registro\n\n"
            "<<<<<<< HEAD\n"
            "## [Sin publicar]\n\n### Añadido — A\n\n## [0.1.0]\n\n### Añadido — viejo\n"
            "=======\n"
            "## [Sin publicar]\n\n### Añadido — B\n\n## [0.1.0]\n\n### Añadido — viejo\n"
            ">>>>>>> origin/main\n"
        )
        with pytest.raises(ValueError):
            fusionar.resolver_texto("CHANGELOG.md", texto)

    def test_una_tupla_que_no_estaba_en_ningun_lado_no_suma(self):
        mio = "def f():\n    return {1: 2}\n"
        suyo = "def f():\n    return {1: 2}\n\n\ndef g():\n    return {3: 4}\n"
        malo = "def f():\n    return ({1: 2},)\n\n\ndef g():\n    return {3: 4}\n"
        assert not fusionar._suma("t.py", malo, mio, suyo, mio)
        assert fusionar._suma("t.py", suyo, mio, suyo, mio)

    def test_lo_que_suma_bien_pasa(self):
        assert fusionar.estructura("a.py", "x = f(1)\ny = {1: 2}\n") == {
            "Call": 1,
            "Dict": 1,
            "Tuple": 0,
            "List": 0,
            "FunctionDef": 0,
            "ClassDef": 0,
            "Return": 0,
        }


class TestValidar:
    def test_una_clave_repetida_en_un_diccionario_no_es_valida(self):
        assert fusionar.valido("a.py", '{"id": 1, "x": 2}\n')
        assert not fusionar.valido("a.py", '{"id": 1, "id": 2}\n')

    def test_una_sintaxis_rota_no_es_valida(self):
        assert not fusionar.valido("a.py", "def (:\n")

    def test_un_xml_roto_no_es_valido(self):
        assert not fusionar.valido("a.svg", "<svg><symbol></svg>")

    def test_otros_archivos_se_aceptan(self):
        assert fusionar.valido("a.md", "cualquier texto")


def test_las_tablas_de_estado_nunca_se_juntan_solas():
    assert {
        "MASTER_PLAN.md",
        "docs/planes/SEGUIMIENTO.md",
        "HANDOFF.md",
    } <= fusionar.NUNCA_AUTOMATICO
