#!/usr/bin/env python3
"""Verificación con salida corta, para agentes (Claude Code / Codex) y para personas.

Corre los mismos pasos que el CI (`.github/workflows/ci.yml`) y escribe el registro completo en
`.claude/tmp/verificar/<paso>.log`; por pantalla solo sale una línea por paso y, si algo falla,
las líneas que dicen qué falló y el final de la salida. La puerta real sigue siendo
`scripts/verify.ps1` / `scripts/verificar.sh` y el CI: esto no la sustituye, la resume.

Uso:
    uv run python scripts/claude/verificar.py [rapido|pruebas|todo] [RUTA ...] [--seguir]

    rapido   check, makemigrations, ruff check y ruff format (segundos; sin pytest)
    pruebas  solo pytest, sin cobertura, sobre las RUTA dadas (o todo si no hay ninguna)
    todo     los mismos pasos que el CI, en su orden (por omisión)

    --seguir       no se detiene en el primer fallo
    --sin-red      salta pip-audit (necesita red)

Solo biblioteca estándar. Variables para probar el propio script: VERIFICAR_RAIZ.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(os.environ.get("VERIFICAR_RAIZ") or Path(__file__).resolve().parents[2])
LOGS = RAIZ / ".claude" / "tmp" / "verificar"

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
PISTAS = [
    re.compile(r"\d+ passed"),
    re.compile(r"^TOTAL\s+\d+"),
    re.compile(r"Required test coverage"),
    re.compile(r"All checks passed"),
    re.compile(r"\d+ files? already formatted"),
    re.compile(r"No issues identified"),
    re.compile(r"No known vulnerabilities"),
    re.compile(r"System check identified no issues"),
    re.compile(r"No changes detected"),
]
CLAVES = re.compile(
    r"^(FAILED |ERROR |E\s{3}|Error: |Would reformat)|^[A-Z]{1,4}\d{3,4} |-->\s+\S+:\d+|Issue: \["
)


def entorno_prod(raiz_permitida: Path) -> dict[str, str]:
    """Ajustes mínimos de producción para que `check --deploy` mire el módulo de verdad."""
    return {
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "ALLOWED_HOSTS": "verificacion.example.org",
        "CSRF_TRUSTED_ORIGINS": "https://verificacion.example.org",
        "AEROCONVERT_MODO": "taller",
        "AEROCONVERT_RAICES_PERMITIDAS": str(raiz_permitida),
    }


def entorno_gate() -> dict[str, str]:
    """Lo que el CI fija para que el gate corra sin `.env`."""
    return {
        "SECRET_KEY": os.environ.get(
            "SECRET_KEY", "clave-solo-para-verificar-no-se-usa-en-ningun-despliegue"
        ),
        "DEBUG": os.environ.get("DEBUG", "True"),
        "AEROCONVERT_MODO": os.environ.get("AEROCONVERT_MODO", "taller"),
        "AEROCONVERT_RAICES_PERMITIDAS": os.environ.get(
            "AEROCONVERT_RAICES_PERMITIDAS", tempfile.gettempdir()
        ),
    }


def pasos(modo: str, rutas: list[str], sin_red: bool) -> list[dict]:
    entregas = Path(tempfile.gettempdir()) / "aeroconvert-verificacion"
    entregas.mkdir(parents=True, exist_ok=True)
    uv = ["uv", "run"]
    check = {
        "id": "check",
        "nombre": "manage.py check",
        "cmd": [*uv, "python", "manage.py", "check"],
    }
    deploy = {
        "id": "deploy",
        "nombre": "check --deploy (producción)",
        "cmd": [*uv, "python", "manage.py", "check", "--deploy"],
        "env": entorno_prod(entregas),
    }
    estaticos = {
        "id": "static",
        "nombre": "collectstatic (manifiesto)",
        "cmd": [*uv, "python", "manage.py", "collectstatic", "--noinput", "--clear"],
        "env": {**entorno_prod(entregas), "STATIC_ROOT": str(entregas / "static")},
        "opcional": True,
    }
    migr = {
        "id": "migr",
        "nombre": "makemigrations --check",
        "cmd": [*uv, "python", "manage.py", "makemigrations", "--check", "--dry-run"],
    }
    ruff = {"id": "ruff", "nombre": "ruff check", "cmd": [*uv, "ruff", "check", "."]}
    fmt = {
        "id": "fmt",
        "nombre": "ruff format --check",
        "cmd": [*uv, "ruff", "format", "--check", "."],
    }
    bandit = {
        "id": "bandit",
        "nombre": "bandit",
        "cmd": [*uv, "bandit", "-q", "-c", "pyproject.toml", "-r", "apps", "config"],
    }
    audit = {"id": "audit", "nombre": "pip-audit", "cmd": [*uv, "pip-audit"]}

    if modo == "rapido":
        return [check, migr, ruff, fmt]
    if modo == "pruebas":
        return [
            {
                "id": "pytest",
                "nombre": "pytest (sin cobertura)",
                "cmd": [*uv, "pytest", "-q", "-p", "no:cacheprovider", *rutas],
            }
        ]
    pytest = {
        "id": "pytest",
        "nombre": "pytest --cov",
        "cmd": [*uv, "pytest", "--cov=apps", "--cov-report=term-missing"],
    }
    lista = [check, deploy, estaticos, migr, pytest, ruff, fmt, bandit]
    if not sin_red:
        lista.append(audit)
    return lista


def limpiar(texto: str) -> str:
    return ANSI.sub("", texto).replace("\r", "").replace("\x00", "")


def correr(paso: dict) -> tuple[int, str, float]:
    env = {
        **os.environ,
        **entorno_gate(),
        "NO_COLOR": "1",
        "PYTHONUNBUFFERED": "1",
        **paso.get("env", {}),
    }
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            paso["cmd"],
            cwd=RAIZ,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )  # noqa: S603  (lista fija, sin shell)
        salida = limpiar((r.stdout or "") + (r.stderr or ""))
        return r.returncode, salida, time.monotonic() - t0
    except FileNotFoundError as e:
        return (
            127,
            f"No se encontró el programa: {e}. ¿Está `uv` en el PATH?",
            time.monotonic() - t0,
        )


def pistas(salida: str) -> list[str]:
    vistas: list[str] = []
    for linea in salida.splitlines():
        if any(p.search(linea) for p in PISTAS):
            t = re.sub(r"^=+\s*|\s*=+$", "", linea.strip())
            if t and t not in vistas:
                vistas.append(t)
    return vistas[-4:]


def claves(salida: str) -> list[str]:
    vistas: list[str] = []
    for linea in salida.splitlines():
        if CLAVES.search(linea) and linea.strip() not in vistas:
            vistas.append(linea.strip())
    return vistas[:12]


def cola(salida: str) -> list[str]:
    lineas: list[str] = []
    for linea in salida.splitlines():
        if linea.strip() == "" and lineas and lineas[-1].strip() == "":
            continue
        lineas.append(linea)
    sel = lineas[-30:]
    return (["... (el registro completo está en el log)"] if len(lineas) > 30 else []) + sel


def main(argv: list[str]) -> int:
    seguir = "--seguir" in argv
    sin_red = "--sin-red" in argv
    resto = [a for a in argv if not a.startswith("--")]
    modo = resto[0] if resto and resto[0] in {"rapido", "pruebas", "todo"} else "todo"
    rutas = resto[1:] if resto and resto[0] in {"rapido", "pruebas", "todo"} else resto
    lista = pasos(modo, rutas, sin_red)
    LOGS.mkdir(parents=True, exist_ok=True)
    ancho = max(len(p["nombre"]) for p in lista)
    verdes = fallos = corridos = 0
    for paso in lista:
        corridos += 1
        codigo, salida, seg = correr(paso)
        log = LOGS / f"{paso['id']}.log"
        log.write_text(
            f"$ {' '.join(paso['cmd'])}\n(código {codigo})\n\n{salida}", encoding="utf-8"
        )
        etiqueta = paso["nombre"].ljust(ancho)
        if codigo == 0:
            verdes += 1
            extra = pistas(salida)
            print(f"OK     {etiqueta}  {seg:.1f} s" + (f"  · {' · '.join(extra)}" if extra else ""))
        else:
            fallos += 1
            print(f"FALLO  {etiqueta}  {seg:.1f} s  (código {codigo})")
            ks = claves(salida)
            if ks:
                print("   Lo que falló:")
                for k in ks:
                    print(f"   * {k}")
            print("   Final de la salida:")
            for fila in cola(salida):
                print(f"   | {fila}")
            print(f"   log completo: {log.relative_to(RAIZ).as_posix()}")
            if not seguir:
                break
    omitidos = len(lista) - corridos
    print(
        f"\n{verdes} de {len(lista)} pasos en verde"
        + (f", {fallos} con fallo" if fallos else "")
        + (f", {omitidos} sin correr (usa --seguir para no parar)" if omitidos else "")
        + "."
    )
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
