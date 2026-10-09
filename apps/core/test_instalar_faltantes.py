"""`despliegue/instalar_faltantes.sh` no depende del idioma del servidor.

En p340, con el sistema en español, `apt-cache policy` contesta «Candidato:» y el guion buscaba
«Candidate:»: dio los doce paquetes por ausentes (2026-10-09). Lo que lo impide es fijar `LC_ALL=C`
antes de la primera orden de apt.
"""

from __future__ import annotations

from pathlib import Path

GUION = Path(__file__).resolve().parents[2] / "despliegue" / "instalar_faltantes.sh"


def test_fija_el_idioma_antes_de_preguntarle_a_apt():
    texto = GUION.read_text(encoding="utf-8")
    assert "export LC_ALL=C" in texto
    assert texto.index("export LC_ALL=C") < texto.index("$(apt-cache policy")


def test_el_guion_tiene_finales_de_linea_de_unix():
    assert b"\r\n" not in GUION.read_bytes(), "bash en Linux no lee CRLF"
