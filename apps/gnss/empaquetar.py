"""El segundo paso de la conversión GNSS: meter lo que escribió el convertidor en un zip.

    python -m apps.gnss.empaquetar <carpeta> <zip>

Corre como proceso hijo y **no arranca Django**, igual que `apps/vector/desde_cad.py`: para
juntar archivos en un zip no hace falta una base de datos.

## Por qué un zip

El convertidor de Trimble escribe **varios archivos** —las observaciones y la navegación, a
veces una por constelación— y el trabajo entrega uno. Un zip se renombra de golpe con
`os.replace`, que es el «todo o nada» que el proyecto promete: unos `.23o` y `.23n` sueltos
en una carpeta, con uno de ellos a medias, no se pueden entregar sin que alguien lo note.

## Y por qué mira que haya algo

**El convertidor sale con código 0 y dice «Success» en todos los casos**, también con un
archivo vacío o con basura (medido el 2026-10-05). Aquí se exige que la carpeta tenga archivos
no vacíos, y el verificador del motor exige después que dentro haya épocas de verdad.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


def empaquetar(carpeta: Path, destino: Path) -> int:
    """Devuelve cuántos archivos metió. Levanta `ValueError` si no había ninguno."""
    archivos = sorted(
        p
        for p in carpeta.iterdir()
        # Los que empiezan por `_` son del propio tránsito, no del convertidor.
        if p.is_file() and not p.name.startswith("_") and p.stat().st_size > 0
    )
    if not archivos:
        raise ValueError(
            "El convertidor terminó pero no escribió ningún archivo con contenido. "
            "Suele ser un archivo que no es de un receptor, o uno vacío."
        )

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as paquete:
        for archivo in archivos:
            paquete.write(archivo, arcname=archivo.name)
    return len(archivos)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m apps.gnss.empaquetar <carpeta> <zip>")
        return 2

    carpeta, destino = Path(argv[0]), Path(argv[1])
    try:
        empaquetar(carpeta, destino)
    except (ValueError, OSError) as fallo:
        destino.unlink(missing_ok=True)
        # La última línea con «ERROR» es la que el corredor enseña en la ficha.
        print(f"ERROR: {fallo}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Sea cual sea el final, la carpeta de tránsito no se queda: pesa decenas de veces lo
        # que pesa el crudo, y `_limpiar_restos` del corredor solo borra archivos.
        shutil.rmtree(carpeta, ignore_errors=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - lo ejerce el proceso hijo
    sys.exit(main(sys.argv[1:]))
