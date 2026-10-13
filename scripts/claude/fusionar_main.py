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

Las tablas de `MASTER_PLAN.md` y de `SEGUIMIENTO.md` llevan el estado de cada fila. Solo se
resuelven dos choques, que son solo filas de tabla: **la misma fila editada en los dos lados**
(se toma la de `main` y se le aplican las marcas `✅`/`⚠` de la rama) y **filas distintas en el
mismo hueco** (se conservan las dos, en orden natural por código). Lo demás queda con sus marcas.
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
NUNCA_AUTOMATICO = {"HANDOFF.md"}

#: Las tablas de estado: solo se resuelven los choques que son **filas de tabla**.
TABLAS = {"MASTER_PLAN.md", "docs/planes/SEGUIMIENTO.md"}

#: La clave de una fila: `F20.11` en `| F20.11 |`, `B15` en `| **B15 · Topografía** |`.
_CLAVE_FILA = re.compile(r"^\|\s*(?:\*\*)?([A-Z]+)(\d+)(?:\.(\d+))?(?!\d)")
_MARCA = re.compile(r"(F\d+\.\d+)(?!\d)\s*(✅|⚠)")


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


def _clave_fila(linea: str) -> tuple[str, int, int]:
    """`(letra, n, m)` de una fila de tabla, para ordenarla natural (`F20.2` < `F20.11`)."""
    m = _CLAVE_FILA.match(linea)
    if not m:
        raise ValueError(f"no es una fila de tabla con código: {linea.strip()[:60]!r}")
    return m.group(1), int(m.group(2)), int(m.group(3) or 0)


def _filas(bloque: str) -> dict[tuple[str, int, int], str]:
    filas: dict[tuple[str, int, int], str] = {}
    for linea in bloque.splitlines(keepends=True):
        if not linea.startswith("|"):
            raise ValueError("el choque no es solo de filas de tabla")
        clave = _clave_fila(linea)
        if clave in filas:
            raise ValueError(f"código repetido dentro de un lado: {linea.strip()[:60]!r}")
        filas[clave] = linea if linea.endswith("\n") else linea + "\n"
    return filas


def _ultima_celda(fila: str) -> tuple[str, str]:
    cuerpo = fila.rstrip().removesuffix("|").rstrip()
    cabeza, _, celda = cuerpo.rpartition("|")
    return cabeza + "|", celda.strip()


def _con_marcas_de_la_rama(suya: str, mia: str, *, texto_de_cierre: bool) -> str:
    """La fila de `main` con las marcas `✅`/`⚠` que la rama puso en sus códigos `F\\d+\\.\\d+`.

    La marca de un código de la rama gana solo si `main` no marca ya ese código. Y, si se pide, el
    texto de cierre de la última celda de la rama gana cuando `main` la dejó en `⬜`.
    """
    resultado = suya
    for codigo, marca in _MARCA.findall(mia):
        if re.search(rf"{re.escape(codigo)}(?!\d)\s*(✅|⚠)", resultado):
            continue
        resultado = re.sub(rf"{re.escape(codigo)}(?!\d)", f"{codigo} {marca}", resultado, count=1)
    if texto_de_cierre:
        cabeza, celda_main = _ultima_celda(resultado)
        _, celda_rama = _ultima_celda(mia)
        if celda_main == "⬜" and celda_rama and celda_rama != "⬜":
            fin = "\n" if resultado.endswith("\n") else ""
            resultado = f"{cabeza} {celda_rama} |{fin}"
    return resultado


def _fusionar_tabla(mia: str, suya: str, *, texto_de_cierre: bool) -> str:
    """Resuelve un hueco que es solo de filas de tabla, o `ValueError`.

    La misma fila en los dos lados: la de `main` con las marcas de la rama. Filas distintas: las
    dos, en orden natural por código.
    """
    de_rama, de_main = _filas(mia), _filas(suya)
    junto = {}
    for clave in sorted(de_rama.keys() | de_main.keys()):
        if clave in de_rama and clave in de_main:
            junto[clave] = _con_marcas_de_la_rama(
                de_main[clave], de_rama[clave], texto_de_cierre=texto_de_cierre
            )
        else:
            junto[clave] = de_rama.get(clave) or de_main[clave]
    return "".join(junto.values())


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
        if nombre.replace("\\", "/") in TABLAS:
            junto = _fusionar_tabla(mia, suya, texto_de_cierre=nombre.endswith("MASTER_PLAN.md"))
            if not _suma(nombre, antes + junto + resto, "", "", ""):
                raise ValueError(f"{nombre}: el hueco {k + 1} deja la tabla inválida")
            partes.append(junto)
            continue
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
