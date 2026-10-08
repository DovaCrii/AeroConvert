"""Cada variable que lee la configuración está documentada en `.env.example`.

`AEROCONVERT_LOG_LEVEL` se leía desde `config/settings/base.py` y no figuraba en `.env.example`:
quien despliega no tenía cómo saber que existía. La lista sale del código, no de una lista a mano.

Las variables que el padre le pasa al proceso hijo (la contraseña de «Proteger», la ruta de
Tesseract, el controlador de Access) no son del `.env`: no se leen con `config()`.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

_LEIDA = re.compile(r"""config\(\s*["'](AEROCONVERT_[A-Z0-9_]+)["']""")
_DOCUMENTADA = re.compile(r"^\s*#?\s*(AEROCONVERT_[A-Z0-9_]+)=", re.MULTILINE)


def _leidas() -> set[str]:
    nombres: set[str] = set()
    for ruta in (RAIZ / "config" / "settings").glob("*.py"):
        nombres |= set(_LEIDA.findall(ruta.read_text(encoding="utf-8")))
    return nombres


def test_cada_variable_leida_esta_en_env_example():
    documentadas = set(_DOCUMENTADA.findall((RAIZ / ".env.example").read_text(encoding="utf-8")))
    faltan = sorted(_leidas() - documentadas)
    assert not faltan, f"Leídas en config/settings y ausentes de .env.example: {faltan}"


def test_la_lista_no_esta_vacia():
    """Si el patrón dejara de casar, la prueba de arriba pasaría sin mirar nada."""
    assert {"AEROCONVERT_MODO", "AEROCONVERT_LOG_LEVEL"} <= _leidas()
