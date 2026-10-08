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
        candidatos = ("\n",) if Path(nombre).name in APILAR else SEPARADORES
        for sep in candidatos:
            if Path(nombre).name in APILAR or valida(
                nombre, "".join(partes) + mia + sep + suya + resto
            ):
                partes.append(mia + sep + suya)
                break
        else:
            raise ValueError(f"{nombre}: ningún separador deja válido el hueco {k + 1}")
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
