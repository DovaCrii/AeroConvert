"""El proceso hijo de «Office a PDF» **con LibreOffice** (F17.1). Sin Django.

    python -m apps.documents.libreoffice_hijo <soffice> <origen> <parcial> <tiempo_maximo_s>

## Por qué un hijo propio y no `soffice` directo

1. **El original no se toca, ni su carpeta.** LibreOffice deja un archivo de bloqueo
   (`.~lock.<nombre>#`) junto al documento que abre. Abrirlo en la carpeta compartida sería
   escribir en ella, y en una carpeta de solo lectura, fallar. Así que se **copia** a una carpeta
   de trabajo propia y se convierte la copia.
2. **`soffice` no deja elegir el nombre de salida**: escribe `<carpeta>/<nombre>.pdf`. El hijo lo
   mueve al parcial que espera el corredor.
3. **Un perfil propio por trabajo** (`-env:UserInstallation`): dos conversiones a la vez con el
   perfil compartido se pisan, y la segunda sale con código 0 sin escribir nada.

El código de salida de `soffice` no decide nada (regla 1): decide que el PDF exista. Y la carpeta de
trabajo se borra siempre, también si falla.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - se lanza soffice con una lista de argumentos
import sys
from pathlib import Path


def convertir(soffice: str, origen: Path, parcial: Path, tiempo_maximo_s: int) -> None:
    trabajo = parcial.with_name(parcial.name + ".lo")
    shutil.rmtree(trabajo, ignore_errors=True)
    entrada = trabajo / "entrada"
    salida = trabajo / "salida"
    perfil = trabajo / "perfil"
    for carpeta in (entrada, salida, perfil):
        carpeta.mkdir(parents=True)
    try:
        # El nombre de la copia es fijo y sin rarezas: un nombre con espacios o tildes es el que
        # se le pasa a soffice, y así no hay sorpresas de codificación en la línea de órdenes.
        copia = entrada / f"documento{origen.suffix.lower()}"
        shutil.copyfile(origen, copia)
        orden = [
            soffice,
            f"-env:UserInstallation={perfil.resolve().as_uri()}",
            "--headless",
            "--norestore",
            "--nologo",
            "--nodefault",
            "--convert-to",
            "pdf",
            "--outdir",
            str(salida),
            str(copia),
        ]
        try:
            resultado = subprocess.run(  # nosec B603
                orden, capture_output=True, text=True, timeout=tiempo_maximo_s, check=False
            )
        except subprocess.TimeoutExpired:
            print(f"LibreOffice lleva {tiempo_maximo_s} s sin terminar.", file=sys.stderr)
            raise SystemExit(3) from None
        escrito = salida / "documento.pdf"
        if not escrito.is_file() or escrito.stat().st_size == 0:
            queja = (resultado.stderr or resultado.stdout or "").strip().splitlines()
            print(
                "LibreOffice no escribió el PDF. " + (queja[-1][:300] if queja else ""),
                file=sys.stderr,
            )
            raise SystemExit(2)
        shutil.move(str(escrito), str(parcial))
        print(f"LibreOffice: {escrito.name} -> {parcial.name}")
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "Uso: libreoffice_hijo <soffice> <origen> <parcial> <tiempo_maximo_s>", file=sys.stderr
        )
        return 64
    soffice, origen, parcial, tiempo = argv
    convertir(soffice, Path(origen), Path(parcial), int(tiempo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
