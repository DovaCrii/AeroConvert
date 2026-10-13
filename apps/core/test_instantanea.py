"""`scripts/claude/instantanea.py`: pinta pantallas con sesión sintética y deja el HTML en disco.

Se corre como proceso aparte (como lo usa quien lo invoca) para no tocar la base ni los ajustes del
proceso de pruebas. La carpeta de salida se redirige a una temporal con `INSTANTANEA_CARPETA`.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

RUTA = Path(settings.BASE_DIR) / "scripts" / "claude" / "instantanea.py"
_especificacion = importlib.util.spec_from_file_location("instantanea", RUTA)
instantanea = importlib.util.module_from_spec(_especificacion)
_especificacion.loader.exec_module(instantanea)


def _correr(carpeta: Path, *args: str) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "INSTANTANEA_CARPETA": str(carpeta)}
    return subprocess.run(  # noqa: S603 - el propio intérprete y un script del repositorio
        [sys.executable, str(RUTA), *args],
        cwd=settings.BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=300,
    )


def test_escribe_el_html_y_limpiar_lo_quita(tmp_path):
    carpeta = tmp_path / "vista"
    resultado = _correr(carpeta, "--sin-sesion", "entrar=/entrar/")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    html = (carpeta / "entrar.html").read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert '="/static/' not in html  # los estáticos quedaron relativos
    assert "../" in html
    assert _correr(carpeta, "--limpiar").returncode == 0
    assert not carpeta.exists()


def test_con_sesion_no_pide_la_contrasena(tmp_path):
    carpeta = tmp_path / "vista"
    resultado = _correr(carpeta, "inicio=/")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    # `follow=True`: si la sesión no valiera, la respuesta final sería la pantalla de entrar.
    assert 'name="password"' not in (carpeta / "inicio.html").read_text(encoding="utf-8")


def test_una_respuesta_que_no_es_200_sale_con_codigo_distinto_de_cero(tmp_path):
    resultado = _correr(tmp_path / "vista", "nada=/no-existe-esta-ruta/")
    assert resultado.returncode == 1
    assert (tmp_path / "vista" / "nada.html").exists()


def test_reescribe_los_estaticos_a_relativos():
    html = "<link href=\"/static/css/a.css\"><script src='/static/js/b.js'></script>"
    html += '<style>x{background:url(/static/i/c.png)}</style><a href="/mapa/">'
    fuera = instantanea.reescribir_estaticos(html)
    assert 'href="../css/a.css"' in fuera
    assert "src='../js/b.js'" in fuera
    assert "url(../i/c.png)" in fuera
    assert 'href="/mapa/"' in fuera


def test_el_gitignore_excluye_las_pantallas():
    lineas = (Path(settings.BASE_DIR) / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/static/_vista_previa/" in [linea.strip() for linea in lineas]
