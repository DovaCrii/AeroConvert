#!/usr/bin/env python3
"""Lee `MASTER_PLAN.md` por filas, sin cargarlo entero.

Uso:
    python scripts/claude/plan_fila.py F9.4              filas de tabla y encabezados
    python scripts/claude/plan_fila.py F9.4 --seccion    además, 40 líneas de su sección
    python scripts/claude/plan_fila.py --abiertas        filas con estado abierto (⬜ 🔶 ◐ ❓)

Solo lee. Para editar, usa el número de línea (`Lnnn`) que imprime y edita ESA fila.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

RAIZ = Path(os.environ.get("VERIFICAR_RAIZ") or Path(__file__).resolve().parents[2])
ARCHIVO = RAIZ / "MASTER_PLAN.md"
ABIERTO = re.compile("[⬜🔶◐❓]")
CODIGO = re.compile(r"F\d+\.\d+[a-z]?")


def corto(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= n else s[: n - 1] + "…"


def nivel(linea: str) -> int:
    m = re.match(r"^(#{1,6})\s", linea)
    return len(m.group(1)) if m else 0


def main(argv: list[str]) -> int:
    if not ARCHIVO.exists():
        print(f"No existe {ARCHIVO}", file=sys.stderr)
        return 2
    con_seccion = "--seccion" in argv
    abiertas = "--abiertas" in argv
    codigo = next((a for a in argv if not a.startswith("--")), None)
    if not abiertas and not codigo:
        print("Uso: plan_fila.py <código, p. ej. F9.4> [--seccion] | --abiertas", file=sys.stderr)
        return 2
    lineas = ARCHIVO.read_text(encoding="utf-8").splitlines()

    if abiertas:
        n = 0
        for i, linea in enumerate(lineas):
            if linea.startswith("|") and ABIERTO.search(linea) and CODIGO.search(linea):
                print(f"L{i + 1}  {corto(linea, 200)}")
                n += 1
        print(f"\n{n} filas abiertas. Detalle de una: plan_fila.py <código> --seccion")
        return 0

    patron = re.compile(r"(?<![\w.])" + re.escape(codigo) + r"(?![\w])")
    filas, encabezados, otras = [], [], []
    for i, linea in enumerate(lineas):
        if not patron.search(linea):
            continue
        if linea.startswith("|"):
            filas.append(i)
        elif nivel(linea) > 0:
            encabezados.append(i)
        else:
            otras.append(i)
    if not (filas or encabezados or otras):
        print(f"Sin menciones de {codigo} en MASTER_PLAN.md")
        return 1
    print(f"## {codigo}")
    for i in filas[:8]:
        print(f"L{i + 1}  {corto(lineas[i], 260)}")
    if len(filas) > 8:
        print(f"… {len(filas) - 8} filas más")
    for i in encabezados[:4]:
        print(f"L{i + 1}  {lineas[i]}")
        if con_seccion:
            n = nivel(lineas[i])
            fin = i + 1
            while fin < len(lineas) and fin < i + 41 and not (0 < nivel(lineas[fin]) <= n):
                fin += 1
            for j in range(i + 1, fin):
                print(f"      {corto(lineas[j], 300)}")
            if fin == i + 41:
                print("      … (sección más larga; léela por rangos con el número de línea)")
    if otras:
        lista = " ".join(f"L{i + 1}" for i in otras[:6])
        print(
            f"Otras menciones en el texto: {len(otras)} ({lista}{' …' if len(otras) > 6 else ''})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
