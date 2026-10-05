"""Un `convertToRinex.exe` de mentira, para probar el motor sin el programa de Trimble.

Se comporta como el de verdad **en lo que se midió el 2026-10-05**, que es justo lo que importa
probar: sale con código 0 y escribe «Success» en todos los casos, también cuando no ha hecho
nada o ha hecho mal el trabajo. El caso que se simula lo dice la variable `CONVERTIDOR_FALSO`.

No es una copia del programa —no se conoce su formato de entrada ni hace falta—: es el guion de
sus modales, y las pruebas comprueban que el motor mira los archivos y no el código de salida.

    python convertidor_falso.py <entrada> -p <carpeta> [-v X.XX] [-mx] [-d] [-s] [-mo NOMBRE]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Se ejecuta como script suelto: la raíz del repositorio no está en `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from apps.formats.tests.constructor import rinex_minimo  # noqa: E402


def _navegacion(version: str) -> str:
    primera = f"{version:>9}           NAVIGATION DATA     M".ljust(60) + "RINEX VERSION / TYPE"
    return primera + "\n" + "".ljust(60) + "END OF HEADER\n"


def main(argv: list[str]) -> int:
    entrada = Path(argv[0])
    carpeta = Path(argv[argv.index("-p") + 1])
    version = argv[argv.index("-v") + 1] if "-v" in argv else "3.04"
    marcador = argv[argv.index("-mo") + 1] if "-mo" in argv else "GMLA"
    modo = os.environ.get("CONVERTIDOR_FALSO", "ok")

    # Lo único que dice el de verdad en cualquier caso.
    print(f"Scanning {entrada}...Complete!")
    print(f"Converting {entrada.name}...Success")

    # Quien lo llama tiene que haber creado la carpeta: el de verdad no la crea.
    obs = carpeta / f"{entrada.stem}.23o"
    nav = carpeta / f"{entrada.stem}.23mix"

    if modo == "nada":
        return 0  # «Success» sin escribir ni un archivo
    if modo == "no_rinex":
        obs.write_text("esto no es un RINEX\n", encoding="latin-1")
        return 0
    if modo == "sin_epocas":
        obs.write_text(
            rinex_minimo(version=version, epocas=0, marcador=marcador), encoding="latin-1"
        )
        nav.write_text(_navegacion(version), encoding="latin-1")
        return 0

    texto = rinex_minimo(
        version="2.11" if modo == "version_mala" else version,
        epocas=10,
        marcador=marcador,
        truncar_la_ultima=modo == "truncado",
        huecos_en=(4, 5) if modo == "hueco" else (),
    )
    obs.write_text(texto, encoding="latin-1", newline="")
    if modo != "sin_navegacion":
        nav.write_text(_navegacion(version), encoding="latin-1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
