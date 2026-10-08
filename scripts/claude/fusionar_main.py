"""Fusiona `origin/main` en la rama actual y resuelve solo los conflictos «los dos añadieron».

Cada herramienta nueva toca las mismas ocho piezas (el registro, la taxonomía, los sinónimos, la
cola, las rutas, el sprite…), así que dos PR seguidos chocan siempre en los mismos sitios, y siempre
del mismo modo: **cada uno añadió su entrada junto a la del otro**. Eso se resuelve quedándose con
las dos, y lo único difícil es el separador que las junta (un `),` que cierra una tupla, un `},
{` que abre otra entrada…).

En vez de adivinarlo, se **prueba** y se valida el resultado:

- en `.py`, que el archivo se lea (`ast`) y que **ningún diccionario tenga una clave repetida**
  (es el fallo que un separador equivocado deja: dos entradas fundidas en una, que Python acepta);
- en `.svg`, que sea un XML bien formado;
- en `CHANGELOG.md`, nada: las dos entradas se apilan.

Y en todos, **que la fusión no funda ni invente piezas** (ver `_suma`): ninguna llamada con más
argumentos que en alguno de los dos lados, ninguna tupla de un elemento salida de la nada, ningún
encabezado de versión repetido en un `.md`. Cuando el hueco cae **dentro** de algo que comparten
los dos lados (`_m(` … `),`), el primer separador que se prueba es cerrarlo y volver a abrirlo.
El 2026-10-08 un separador vacío fundió dos
`_m(...)` del catálogo de motivos en una sola llamada de seis argumentos, otro convirtió un
`return {...}` en `return ({...},)`, y el `CHANGELOG.md` acabó entero dos veces: los tres archivos
se leían bien y ninguno sumaba.

Lo que no se sabe resolver **se deja con sus marcas y se dice**: las tablas de `MASTER_PLAN.md` y de
`SEGUIMIENTO.md` llevan el estado de cada fila y ahí decide una persona (o el cierre de la fila).
Nunca se hace `push`, nunca `--force`.

Uso::

    uv run python scripts/claude/fusionar_main.py            # fusiona y resuelve
    uv run python scripts/claude/fusionar_main.py --solo-texto ARCHIVO   # para probarlo
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

RAIZ = Path(__file__).resolve().parents[2]

#: Lo que puede haber que poner entre los dos lados, del más simple al más específico.
SEPARADORES = (
    "",
    "\n",
    "\n\n",
    "        ),\n",
    ")\n",
    "    },\n",
    "    },\n    {\n",
    "        ),\n    },\n    {\n",
    "  </symbol>\n\n",
)

#: `git` escribe las marcas con el nombre de la rama de cada lado.
HUECO = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)

#: Los archivos donde se apilan los dos lados sin más (no hay nada que validar).
APILAR = {"CHANGELOG.md"}

#: Donde decide una persona: el estado de cada fila no se «junta».
NUNCA_AUTOMATICO = {"MASTER_PLAN.md", "docs/planes/SEGUIMIENTO.md", "HANDOFF.md"}


def _claves_repetidas(arbol: ast.AST) -> bool:
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Dict):
            claves = [k.value for k in nodo.keys if isinstance(k, ast.Constant)]
            if len(claves) != len(set(claves)):
                return True
    return False


def valido(nombre: str, texto: str) -> bool:
    """Si `texto` es un archivo de ese tipo que se lee y no esconde un diccionario fundido."""
    try:
        if nombre.endswith(".py"):
            arbol = ast.parse(texto)
            return not _claves_repetidas(arbol)
        if nombre.endswith(".svg"):
            ET.fromstring(texto)
            return True
    except (SyntaxError, ET.ParseError):
        return False
    return True


_TIPOS_QUE_SUMAN = (
    ast.Call,
    ast.Dict,
    ast.Tuple,
    ast.List,
    ast.FunctionDef,
    ast.ClassDef,
    ast.Return,
)


def estructura(nombre: str, texto: str) -> dict[str, int] | None:
    """Cuántas piezas de cada clase tiene el texto, o `None` si no se puede contar."""
    if not nombre.endswith(".py"):
        return None
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return None
    cuentas = dict.fromkeys((t.__name__ for t in _TIPOS_QUE_SUMAN), 0)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, _TIPOS_QUE_SUMAN):
            cuentas[type(nodo).__name__] += 1
    return cuentas


def _tuplas_de_uno(texto: str) -> int:
    return sum(
        1 for n in ast.walk(ast.parse(texto)) if isinstance(n, ast.Tuple) and len(n.elts) == 1
    )


def _argumentos_por_funcion(texto: str) -> dict[str, int]:
    """El mayor número de argumentos con que se llama a cada función por su nombre."""
    maximos: dict[str, int] = {}
    for nodo in ast.walk(ast.parse(texto)):
        if isinstance(nodo, ast.Call):
            nombre = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
            if nombre:
                n = len(nodo.args) + len(nodo.keywords)
                maximos[nombre] = max(maximos.get(nombre, 0), n)
    return maximos


def _suma(nombre: str, resultado: str, mio: str, suyo: str, comun: str) -> bool:
    """Que la fusión no **invente** piezas ni **funda** dos en una.

    - No pueden aparecer tuplas de un solo elemento que no estaban en ningún lado: es una coma
      suelta de un separador mal puesto (`return ({...},)`).
    - Ninguna llamada puede llevar más argumentos que los que lleva en alguno de los dos lados: dos
      `_m(...)` fundidas en una llaman a `_m` con seis.
    - En un `.md`, ningún encabezado de versión (`## [x]`) puede quedar repetido.
    """
    if nombre.endswith(".md"):
        versiones = re.findall(r"^## \[[^\]]+\]", resultado, re.M)
        return len(versiones) == len(set(versiones))
    if estructura(nombre, resultado) is None or estructura(nombre, mio) is None:
        return True  # sin poder contar, decide `valido`
    # Una tupla de un solo elemento casi nunca se escribe a propósito; aparece cuando un separador
    # deja una coma suelta (`return ({...},)`). Más de las que ya había en los dos lados, no.
    if _tuplas_de_uno(resultado) > _tuplas_de_uno(mio) + _tuplas_de_uno(suyo):
        return False
    tope = _argumentos_por_funcion(mio)
    for funcion, n in _argumentos_por_funcion(suyo).items():
        tope[funcion] = max(tope.get(funcion, 0), n)
    return all(n <= tope.get(f, n) for f, n in _argumentos_por_funcion(resultado).items())


def _separador_del_contexto(antes: str, resto: str) -> str | None:
    """Si el hueco está **dentro** de algo que los dos comparten (`_m(` … `),`), el separador es
    cerrar eso y volver a abrirlo: la última línea de antes que abre y la primera de después que
    cierra."""
    lineas_antes = antes.splitlines(keepends=True)
    lineas_despues = resto.splitlines(keepends=True)
    if not lineas_antes or not lineas_despues:
        return None
    apertura, cierre = lineas_antes[-1], lineas_despues[0]
    if apertura.rstrip().endswith(("(", "{", "[")) and cierre.lstrip().startswith((")", "}", "]")):
        return cierre + apertura
    return None


def resolver_texto(nombre: str, texto: str, *, valida: Callable[[str, str], bool] = valido) -> str:
    """El texto sin marcas de conflicto, o `ValueError` si algún hueco no se puede resolver."""
    huecos = list(HUECO.finditer(texto))
    if not huecos:
        return texto
    partes: list[str] = []
    ultimo = 0
    for k, m in enumerate(huecos):
        partes.append(texto[ultimo : m.start()])
        ultimo = m.end()
        mia, suya = m.group(1), m.group(2)
        resto = HUECO.sub(lambda r: r.group(1), texto[m.end() :])  # lo que falta: solo «el nuestro»
        antes = "".join(partes)
        candidatos = ("\n",) if Path(nombre).name in APILAR else SEPARADORES
        contexto = _separador_del_contexto(antes, resto)
        if contexto is not None and Path(nombre).name not in APILAR:
            candidatos = (contexto, *candidatos)
        for sep in candidatos:
            junto = antes + mia + sep + suya + resto
            if (Path(nombre).name in APILAR or valida(nombre, junto)) and _suma(
                nombre, junto, antes + mia + resto, antes + suya + resto, antes + resto
            ):
                partes.append(mia + sep + suya)
                break
        else:
            raise ValueError(f"{nombre}: ningún separador deja el hueco {k + 1} válido y sumando")
    partes.append(texto[ultimo:])
    return "".join(partes)


def _git(*args: str, comprobar: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - `git` con argumentos fijos y rutas del propio repositorio
        ["git", *args],  # noqa: S607
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=comprobar,
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["--solo-texto"]:
        ruta = Path(argv[1])
        ruta.write_text(
            resolver_texto(ruta.name, ruta.read_text(encoding="utf-8")), encoding="utf-8"
        )
        return 0

    rama = _git("branch", "--show-current").stdout.strip()
    if rama in ("", "main"):
        print("Estás en `main` (o sin rama): crea `codex/<área>` antes de fusionar.")
        return 2
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        print("Hay cambios sin confirmar: confírmalos antes de fusionar `main`.")
        return 2

    _git("fetch", "-q")
    fusion = _git("merge", "--no-edit", "origin/main", comprobar=False)
    if fusion.returncode == 0:
        print("Fusión limpia: nada que resolver.")
        return 0

    conflictos = _git("diff", "--name-only", "--diff-filter=U").stdout.split()
    if not conflictos:
        print(fusion.stdout + fusion.stderr)
        return 1

    resueltos, pendientes = [], []
    for archivo in conflictos:
        ruta = RAIZ / archivo
        if archivo in NUNCA_AUTOMATICO or ruta.suffix not in {".py", ".svg", ".md"}:
            pendientes.append(archivo)
            continue
        try:
            ruta.write_text(
                resolver_texto(archivo, ruta.read_text(encoding="utf-8")),
                encoding="utf-8",
                newline="",
            )
        except ValueError as fallo:
            print(fallo)
            pendientes.append(archivo)
            continue
        _git("add", archivo)
        resueltos.append(archivo)

    for archivo in resueltos:
        print(f"resuelto   {archivo}")
    for archivo in pendientes:
        print(f"PENDIENTE  {archivo}  (a mano: sus marcas siguen puestas)")
    if pendientes:
        return 1

    _git("commit", "-q", "-m", f"Merge origin/main en {rama}")
    print("Fusión confirmada. Pasa ruff y la suite antes de subir.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
