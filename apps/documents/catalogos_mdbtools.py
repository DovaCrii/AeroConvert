"""Leer un catálogo de Access **sin Access**, con `mdbtools` (F17.2).

En el servidor (Linux) no existe el motor de Access de Microsoft, así que «Catálogo Plant 3D a
Excel» salía apagada. `mdbtools` (programa externo, sondeado y ejecutado aparte: D1) **lee** bases
Jet y ACE. **Escribir** un `.mdb` sigue pidiendo Windows: «Excel a catálogo» no cambia.

Tres órdenes, todas de solo lectura y con lista de argumentos:

- `mdb-tables -1 <base>`: los nombres de las tablas de usuario, uno por línea.
- `mdb-export <base> <tabla>`: la tabla en CSV, con la fila de encabezados. Da los **nombres de las
  columnas en su orden**.
- `mdb-json <base> <tabla>`: una fila por línea en JSON, con **los tipos** (números como números).
  Si esta versión de `mdbtools` no la trae, se usa el CSV y los valores van como texto, y se dice.

Lo que no cambia respecto de ACE: las tablas `MSys…` no se exportan, los nombres pasan por
`catalogos._seguro` y el tope de filas es el mismo.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess  # nosec B404 - mdbtools se lanza con lista de argumentos
from pathlib import Path

from .composicion import ComposicionInvalida

TIEMPO_MAXIMO_S = 120


def encontrar(carpeta: str = "") -> str:
    """La carpeta de `mdbtools` (donde están `mdb-tables`, `mdb-export`), o cadena vacía."""
    if carpeta and (Path(carpeta) / "mdb-tables").is_file():
        return carpeta
    tablas = shutil.which("mdb-tables")
    if tablas and shutil.which("mdb-export"):
        return str(Path(tablas).parent)
    return ""


def _orden(carpeta: str, programa: str) -> str:
    candidato = Path(carpeta) / programa
    if candidato.is_file():
        return str(candidato)
    for extension in (".cmd", ".exe", ".bat"):
        if candidato.with_suffix(extension).is_file():
            return str(candidato.with_suffix(extension))
    return str(candidato)


def _correr(carpeta: str, programa: str, *argumentos: str) -> str:
    try:
        resultado = subprocess.run(  # nosec B603
            [_orden(carpeta, programa), *argumentos],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIEMPO_MAXIMO_S,
            check=False,
        )
    except FileNotFoundError as fallo:
        raise ComposicionInvalida(f"No está {programa} de mdbtools.") from fallo
    except subprocess.TimeoutExpired as fallo:
        raise ComposicionInvalida(f"{programa} lleva {TIEMPO_MAXIMO_S} s sin terminar.") from fallo
    if resultado.returncode != 0:
        queja = (resultado.stderr or "").strip().splitlines()
        raise ComposicionInvalida(
            f"mdbtools no pudo leer la base: {queja[-1][:200] if queja else programa}"
        )
    return resultado.stdout


def tablas(carpeta: str, base: Path) -> list[str]:
    nombres = [n.strip() for n in _correr(carpeta, "mdb-tables", "-1", str(base)).splitlines()]
    return [n for n in nombres if n and not n.startswith("MSys")]


def columnas_y_filas(carpeta: str, base: Path, tabla: str) -> tuple[list[str], list[list[str]]]:
    lector = csv.reader(io.StringIO(_correr(carpeta, "mdb-export", str(base), tabla)))
    cabecera = next(lector, None)
    if cabecera is None:
        raise ComposicionInvalida(f"mdbtools no devolvió ni los encabezados de {tabla}.")
    return cabecera, [fila for fila in lector]


def filas_con_tipos(carpeta: str, base: Path, tabla: str, columnas: list[str]):
    """Las filas con sus tipos (`mdb-json`), o `None` si esta versión no tiene `mdb-json`."""
    if not Path(_orden(carpeta, "mdb-json")).is_file() and not shutil.which("mdb-json"):
        return None
    filas = []
    for linea in _correr(carpeta, "mdb-json", str(base), tabla).splitlines():
        if not linea.strip():
            continue
        try:
            objeto = json.loads(linea)
        except json.JSONDecodeError as fallo:
            raise ComposicionInvalida(
                f"mdb-json devolvió algo que no es JSON en {tabla}."
            ) from fallo
        filas.append([objeto.get(c) for c in columnas])
    return filas
