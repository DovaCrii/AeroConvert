"""Hook `PreToolUse`: no deja hacer `git push` si la puerta rápida no pasa.

Dos veces en una misma jornada el CI de GitHub cazó lo que el gate local habría cazado en segundos
(`bandit` B110 y B406), y cada vez costó un ciclo de diez minutos. Esto lo mueve a antes del
`push`: se corre `verificar.py rapido` (check, migraciones, ruff, formato y bandit; sin pytest, que
tarda) y, si falla, el `push` se **bloquea** con el motivo.

El hook recibe por la entrada estándar el JSON de la llamada. Sale con **2** para bloquear (el
mensaje de `stderr` se le enseña a quien lo pidió) y con 0 para dejar pasar. Lo que no es un
`git push` pasa sin mirarlo, y un `push` que **borra** una rama o es un ensayo (`--dry-run`)
también.

No sustituye a la suite completa: esa se corre antes de subir, en segundo plano, como dice
`/avanzar`. Aquí solo está lo que cabe en unos segundos.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

_PUSH = re.compile(r"(^|[;&|]\s*|\s)git\s+(?:-C\s+\S+\s+)?push\b")
_NO_APLICA = re.compile(r"--delete\b|\s-d\s|--dry-run\b|\s:\S+")


def es_un_push_que_hay_que_vigilar(comando: str) -> bool:
    """Un `git push` de verdad: ni un borrado de rama ni un ensayo."""
    if not _PUSH.search(comando or ""):
        return False
    return not _NO_APLICA.search(comando)


def correr_la_puerta_rapida() -> tuple[int, str]:
    resultado = subprocess.run(  # noqa: S603 - `uv` con argumentos fijos
        ["uv", "run", "python", "scripts/claude/verificar.py", "rapido", "--sin-red"],  # noqa: S607
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return resultado.returncode, (resultado.stdout + resultado.stderr).strip()


def main(entrada: str, correr=correr_la_puerta_rapida) -> int:
    try:
        llamada = json.loads(entrada or "{}")
    except ValueError:
        return 0  # sin entender la llamada no se bloquea nada
    comando = (llamada.get("tool_input") or {}).get("command", "")
    if not es_un_push_que_hay_que_vigilar(comando):
        return 0

    codigo, salida = correr()
    if codigo == 0:
        return 0
    cola = "\n".join(salida.splitlines()[-25:])
    sys.stderr.write(
        "El push se detuvo: la puerta rápida (check, migraciones, ruff, formato y bandit) "
        f"no pasa.\n{cola}\nArréglelo y vuelva a empujar.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
