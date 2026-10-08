"""`scripts/claude/antes_de_push.py`: el hook que detiene un `push` con la puerta rápida en rojo."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from django.conf import settings

RUTA = Path(settings.BASE_DIR) / "scripts" / "claude" / "antes_de_push.py"
_especificacion = importlib.util.spec_from_file_location("antes_de_push", RUTA)
hook = importlib.util.module_from_spec(_especificacion)
_especificacion.loader.exec_module(hook)


def _llamada(comando: str) -> str:
    return json.dumps({"tool_name": "PowerShell", "tool_input": {"command": comando}})


class TestQueEsUnPush:
    @pytest.mark.parametrize(
        "comando",
        [
            "git push -u origin codex/f14-18",
            "git push",
            "git add -A; git commit -m x; git push -q origin rama",
            "git -C D:\\repo push origin rama",
            "cd x && git push",
        ],
    )
    def test_se_vigila(self, comando):
        assert hook.es_un_push_que_hay_que_vigilar(comando)

    @pytest.mark.parametrize(
        "comando",
        [
            "git status",
            "git pull",
            "git log --oneline",
            "echo git pushed",
            "git push origin --delete codex/vieja",
            "git push origin :codex/vieja",
            "git push --dry-run",
            "",
        ],
    )
    def test_no_se_vigila(self, comando):
        assert not hook.es_un_push_que_hay_que_vigilar(comando)


class TestElHook:
    def test_un_comando_que_no_es_push_pasa_sin_correr_nada(self):
        def no_debe_correr():
            raise AssertionError("no tenía que correr la puerta")

        assert hook.main(_llamada("git status"), correr=no_debe_correr) == 0

    def test_con_la_puerta_en_verde_el_push_pasa(self):
        assert hook.main(_llamada("git push"), correr=lambda: (0, "todo bien")) == 0

    def test_con_la_puerta_en_rojo_se_bloquea_con_el_motivo(self, capsys):
        salida = "ruff check\nB110 try_except_pass en reparar.py"
        assert hook.main(_llamada("git push -u origin x"), correr=lambda: (1, salida)) == 2
        assert "B110" in capsys.readouterr().err

    def test_una_entrada_que_no_se_entiende_no_bloquea(self):
        assert hook.main("esto no es json", correr=lambda: (1, "")) == 0
        assert hook.main("", correr=lambda: (1, "")) == 0

    def test_el_mensaje_no_pasa_de_las_ultimas_lineas(self, capsys):
        salida = "\n".join(f"linea {i}" for i in range(200))
        hook.main(_llamada("git push"), correr=lambda: (1, salida))
        error = capsys.readouterr().err
        assert "linea 199" in error and "linea 10\n" not in error
