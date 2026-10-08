"""Trato de usted en toda la interfaz (F13.3).

`AGENTS.md` y `.claude/rules/interfaz-y-textos.md` piden **español neutral, de usted y sin voseo**.
Lo que hay en pantalla tuteaba («tu equipo», «eliges», «suelta»…) y ninguna prueba lo vigilaba, así
que cada texto nuevo volvía a empezar desde cero.

## Qué se mira, y qué no

Solo **lo que una persona puede leer**: el texto visible de las plantillas (sin sus comentarios),
las cadenas de los módulos de Python (sin docstrings ni comentarios), las cadenas de los guiones
de `static/js/` y los `msgstr` de `locale/es/`. Los comentarios y docstrings son del equipo y se
escriben como a cada quien le salga: lo que se mide es lo que llega a quien usa la aplicación.

## Cómo se evitan los falsos positivos

El español de «hojas sueltas», «una página sale suelta» o «lo que abre en cualquier puesto» es
correcto, y una lista por raíz los marcaría. Aquí hay **dos clases de patrón**:

- **palabras que solo existen en trato de tú** («tu», «eliges», «quieres», «puedes», «te»…);
- **imperativos de tú al principio de una frase** («Elige», «Pincha», «Suelta»…), que se reconocen
  por la posición, no por la raíz. Una tercera persona en medio de la frase («lo mira y escribe»)
  no se toca.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

#: Palabras que no tienen otra lectura que el trato de tú.
SOLO_DE_TU = (
    "tu tus tuyo tuya tuyos tuyas te tú eres estás vas "
    "eliges quieres puedes sabes tienes crees necesitas estabas querías "
    "equivocaste indicaste olvidaste dejaste elegiste pegaste subiste hiciste "
    "verás harás podrás tendrás "
    "díselo elígelo ábrelo guárdalo quítasela súbelo ponle dímelo "
    # Se colaron en Preajustes y en la pantalla de convertir (2026-10-08): enclíticos de tú y la
    # segunda persona de «haber».
    "cámbialo cámbiala cópialo cópialos instálalo compruébalo bórralo marcaste escribiste "
    "pártelo fiarte tengas"
).split()

#: Imperativos de tú, **solo si abren una frase** o un título. «Pega» y «Mira» en medio de una
#: frase pueden ser tercera persona («lo mira y escribe»).
IMPERATIVOS = (
    "Elige Mira Pincha Suelta Arrastra Prueba Vuelve Pulsa Haz Dime Revisa Indica Pega "
    "Ponle Abre Sube Escribe Usa Elígelo Ábrelo Pásalo "
    "Copia Corre Deja Cambia Instala Comprueba Borra Has Repasa"
).split()

#: Módulos cuyas cadenas **no son para una persona**. `apps/tino/fuera.py` es la instrucción que se
#: le da a un modelo de lenguaje («Eres Tino…»): el tuteo ahí es la forma de hablarle a la máquina y
#: no llega a ninguna pantalla.
EXENTOS = {"apps/tino/fuera.py"}

_PALABRAS = re.compile(r"(?<![\w-])(" + "|".join(SOLO_DE_TU) + r")(?![\w-])", re.IGNORECASE)
_INICIO = re.compile(
    r"(?:^|[.:;!?»›>\n]\s*|<[^>]*>\s*)(" + "|".join(IMPERATIVOS) + r")(?![\wáéíóú])"
)

# Imperativos de tú que se confunden con la tercera persona de los `que_hace` («Abre en cualquier
# puesto»): ahí el sujeto es la herramienta, no la persona. Solo se marcan los que NO son de ese
# estilo; los que sí lo son se vigilan con la lista de palabras de arriba.
_AMBIGUOS_DE_TERCERA = {
    "Abre", "Sube", "Escribe", "Usa", "Pega", "Revisa", "Indica",
    # «Copia la base de datos», «Borra salidas caducadas», «Corre en segundo plano»: el `help` de
    # una orden habla de la orden. Sus enclíticos («cópialo», «bórralo») sí se vigilan.
    "Copia", "Borra", "Corre",
}  # fmt: skip


def _hallazgos(texto: str) -> list[str]:
    encontrados = [m.group(1) for m in _PALABRAS.finditer(texto)]
    for m in _INICIO.finditer(texto):
        palabra = m.group(1)
        if palabra in _AMBIGUOS_DE_TERCERA:
            continue
        encontrados.append(palabra)
    return encontrados


# --- Plantillas -----------------------------------------------------------------------

_COMENTARIO_DJANGO = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.DOTALL)
_COMENTARIO_LINEA = re.compile(r"\{#.*?#\}", re.DOTALL)
_COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)
_ETIQUETA_DJANGO = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_GUION_O_ESTILO = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


def _conservando_lineas(patron: re.Pattern[str], texto: str) -> str:
    """Quita lo que casa pero deja los saltos de línea, para que el número de línea sirva."""
    return patron.sub(lambda m: "\n" * m.group(0).count("\n"), texto)


#: Un texto literal que se le pasa a un `{% include … with titulo="…" %}` **se pinta**: quitar la
#: etiqueta entera lo escondía, y así se coló «Tuyos» como título de una tarjeta.
_LITERAL_EN_INCLUDE = re.compile(r'\b\w+="([^"{}%]+)"')


def _literales_de_include(etiqueta: str) -> str:
    if not etiqueta.lstrip("{% ").startswith("include"):
        return "\n" * etiqueta.count("\n")
    textos = ". ".join(_LITERAL_EN_INCLUDE.findall(etiqueta))
    return textos + "\n" * etiqueta.count("\n")


def _visible(plantilla: str) -> str:
    texto = plantilla
    for patron in (_COMENTARIO_DJANGO, _COMENTARIO_LINEA, _COMENTARIO_HTML, _GUION_O_ESTILO):
        texto = _conservando_lineas(patron, texto)
    return _ETIQUETA_DJANGO.sub(lambda m: _literales_de_include(m.group(0)), texto)


def _plantillas() -> list[Path]:
    return sorted((RAIZ / "templates").rglob("*.html"))


def _lineas_de(texto: str):
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if linea.strip():
            yield numero, linea


def test_las_plantillas_hablan_de_usted():
    mal = []
    for ruta in _plantillas():
        visible = _visible(ruta.read_text(encoding="utf-8"))
        for numero, linea in _lineas_de(visible):
            for encontrado in _hallazgos(linea):
                mal.append(
                    f"{ruta.relative_to(RAIZ)}:{numero}: «{encontrado}» → {linea.strip()[:90]}"
                )
    assert not mal, "Texto de tú en plantillas:\n" + "\n".join(mal)


# --- Python ---------------------------------------------------------------------------


def _cadenas_de(ruta: Path):
    """Las cadenas de un módulo que no son docstring, con su línea."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            cuerpo = nodo.body
            if (
                cuerpo
                and isinstance(cuerpo[0], ast.Expr)
                and isinstance(cuerpo[0].value, ast.Constant)
                and isinstance(cuerpo[0].value.value, str)
            ):
                docstrings.add(id(cuerpo[0].value))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            if id(nodo) not in docstrings:
                yield nodo.lineno, nodo.value


def _modulos() -> list[Path]:
    sitios = [RAIZ / "apps", RAIZ / "config"]
    salida = []
    for sitio in sitios:
        for ruta in sorted(sitio.rglob("*.py")):
            nombre = ruta.name
            if nombre.startswith("test") or nombre == "tests.py" or "migrations" in ruta.parts:
                continue
            if "tests" in ruta.parts:
                continue
            salida.append(ruta)
    return salida


def test_las_cadenas_de_python_hablan_de_usted():
    mal = []
    for ruta in _modulos():
        if ruta.relative_to(RAIZ).as_posix() in EXENTOS:
            continue
        for linea, cadena in _cadenas_de(ruta):
            # Una cadena de identificadores o de código no es texto para una persona.
            if "\n" not in cadena and " " not in cadena.strip():
                continue
            for encontrado in _hallazgos(cadena):
                mal.append(
                    f"{ruta.relative_to(RAIZ)}:{linea}: «{encontrado}» → {cadena.strip()[:90]}"
                )
    assert not mal, "Texto de tú en Python:\n" + "\n".join(mal)


# --- JavaScript y traducciones ---------------------------------------------------------

_CADENA_JS = re.compile(r"""(["'])((?:\\.|(?!\1).)*)\1""")


def test_los_guiones_hablan_de_usted():
    mal = []
    for ruta in sorted((RAIZ / "static" / "js").glob("*.js")):
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
            if linea.lstrip().startswith(("//", "*", "/*")):
                continue
            for m in _CADENA_JS.finditer(linea):
                cadena = m.group(2)
                if " " not in cadena:
                    continue
                for encontrado in _hallazgos(cadena):
                    mal.append(f"{ruta.name}:{numero}: «{encontrado}» → {cadena[:90]}")
    assert not mal, "Texto de tú en JavaScript:\n" + "\n".join(mal)


def test_las_traducciones_al_espanol_hablan_de_usted():
    """El español vive en `locale/es/`, y los `msgid` van en inglés: corregir una plantilla sin
    mirar el `.po` deja el tuteo donde nadie lo busca."""
    ruta = RAIZ / "locale" / "es" / "LC_MESSAGES" / "django.po"
    mal = []
    actual: list[str] = []
    inicio = 0
    en_msgstr = False
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        if linea.startswith("msgstr"):
            en_msgstr, actual, inicio = True, [linea.partition(" ")[2].strip().strip('"')], numero
        elif en_msgstr and linea.startswith('"'):
            actual.append(linea.strip().strip('"'))
        else:
            if en_msgstr:
                cadena = "".join(actual)
                for encontrado in _hallazgos(cadena):
                    mal.append(f"django.po:{inicio}: «{encontrado}» → {cadena[:90]}")
            en_msgstr = False
    assert not mal, "Texto de tú en las traducciones:\n" + "\n".join(mal)


# --- La propia prueba ------------------------------------------------------------------


class TestElDetector:
    """Que el detector marque lo que debe y deje en paz el español correcto."""

    def test_marca_el_tuteo(self):
        for frase in (
            "Desde tu equipo",
            "Elige el archivo",
            "Suelta cualquier archivo",
            "Vas a convertir",
            "si no quieres",
            "Pincha para entrar",
            "te la da",
            "Copia uno de fábrica y cámbialo.",
            "Has marcado coordenadas locales",
        ):
            assert _hallazgos(frase), frase

    def test_no_marca_el_usted_ni_las_terceras_personas(self):
        for frase in (
            "Desde su equipo",
            "Elija el archivo",
            "Una página sale suelta; varias, juntas en un zip.",
            "Saca una parte, o parte uno grande en hojas sueltas.",
            "Esto lo mira y escribe debajo de la imagen",
            "Lo que abre en cualquier puesto",
            "Abre el PDF y reconstruye párrafos",
            "Pone «3 / 56» en cada hoja.",
        ):
            assert not _hallazgos(frase), frase

    def test_un_imperativo_solo_cuenta_al_abrir_la_frase(self):
        assert _hallazgos("Mire dentro del archivo") == []
        assert _hallazgos("Mira dentro del archivo") == ["Mira"]
        assert _hallazgos("El motor lo mira dos veces") == []

    def test_mira_el_texto_que_se_le_pasa_a_un_include(self):
        plantilla = '{% include "x.html" with titulo="Tuyos" ayuda="Elige el archivo" %}'
        hallados = [h for _, linea in _lineas_de(_visible(plantilla)) for h in _hallazgos(linea)]
        assert "Tuyos" in hallados and "Elige" in hallados

    def test_no_mira_los_comentarios_de_las_plantillas(self):
        plantilla = "{% comment %}Elige tu equipo{% endcomment %}\n<p>Elija su equipo</p>"
        assert not [h for _, linea in _lineas_de(_visible(plantilla)) for h in _hallazgos(linea)]
