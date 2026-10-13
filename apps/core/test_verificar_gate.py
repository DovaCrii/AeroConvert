"""`scripts/claude/verificar.py todo` comprueba lo mismo que `verify.ps1` y el CI (tres gates).

El auditor externo vio dos diferencias: `check` sin `--fail-level WARNING` y sin `shellcheck`. Esta
prueba lee el gate real (`verify.ps1`) y compara, no repite una lista copiada.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _verificar():
    spec = importlib.util.spec_from_file_location(
        "verificar_claude", RAIZ / "scripts" / "claude" / "verificar.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _comando(paso: dict) -> str:
    return " ".join(paso["cmd"])


def test_los_dos_check_llevan_fail_level_warning_como_el_gate():
    gate = (RAIZ / "scripts" / "verify.ps1").read_bytes().decode("utf-8")
    assert len(re.findall(r'"--fail-level", "WARNING"', gate)) >= 2
    por_id = {p["id"]: p for p in _verificar().pasos("todo", [], sin_red=True)}
    for clave in ("check", "deploy"):
        assert "--fail-level WARNING" in _comando(por_id[clave]), clave


def test_shellcheck_entra_si_esta_instalado_y_si_no_se_dice(monkeypatch, capsys):
    modulo = _verificar()
    monkeypatch.setattr(modulo.shutil, "which", lambda _n: "/usr/bin/shellcheck")
    assert "shellcheck" in {p["id"] for p in modulo.pasos("todo", [], sin_red=True)}
    monkeypatch.setattr(modulo.shutil, "which", lambda _n: None)
    assert "shellcheck" not in {p["id"] for p in modulo.pasos("todo", [], sin_red=True)}
    assert "shellcheck" in capsys.readouterr().out
