"""Sacar los puntos de un LandXML para que OGR pueda con ellos.

**OGR no lee LandXML**, así que la conversión va en dos pasos: este módulo saca los
`CgPoint` a un CSV con un encabezado que nosotros ponemos, y después `ogr2ogr` lleva ese CSV
al formato que se haya pedido.

## Por qué un CSV y no un GeoJSON

Porque el comando de la segunda mitad ya existe y está probado: es el mismo que usa
`MotorPuntosTopograficos` para una libreta de puntos, con `X_POSSIBLE_NAMES` y compañía. La
diferencia es que aquí **el encabezado lo escribimos nosotros**, así que no hay orden de
columnas que deducir ni riesgo de equivocarlo: es el único caso de todo el proyecto donde
esa pregunta no se plantea.

Se escribe con el módulo `csv` y no concatenando comas: una descripción de topógrafo trae
comas y comillas más a menudo de lo que parece —`cerco, esquina NE`— y partir esa línea por
las comas rompería la fila entera.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Se ejecuta como proceso hijo (`python -m apps.vector.desde_landxml`), asi que no puede dar
# por hecho que la raiz del repositorio este en `sys.path`.
if __package__ in (None, ""):  # pragma: no cover - solo en el arranque del hijo
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.formats import landxml as lectura  # noqa: E402

#: El encabezado del CSV intermedio. Lo lee `ogr2ogr` por estos nombres exactos, así que
#: cambiarlos aquí obliga a cambiarlos en `motores.py`. Hay una prueba que lo comprueba.
CAMPO_PUNTO = "punto"
CAMPO_NORTE = "norte"
CAMPO_ESTE = "este"
CAMPO_COTA = "cota"
CAMPO_DESCRIPCION = "descrip"

ENCABEZADO = (CAMPO_PUNTO, CAMPO_NORTE, CAMPO_ESTE, CAMPO_COTA, CAMPO_DESCRIPCION)


def extraer(origen: str | Path, destino: str | Path) -> int:
    """Escribe el CSV intermedio y devuelve cuántos puntos puso."""
    puestos = 0
    with open(destino, "w", encoding="utf-8", newline="") as salida:
        escritor = csv.writer(salida)
        escritor.writerow(ENCABEZADO)
        for punto in lectura.iterar_puntos(origen):
            escritor.writerow(
                [
                    punto.identificador,
                    f"{punto.norte_m:.6f}",
                    f"{punto.este_m:.6f}",
                    f"{punto.cota_m:.6f}",
                    punto.descripcion,
                ]
            )
            puestos += 1
    return puestos


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(
        description="Saca los puntos de un LandXML a un CSV intermedio."
    )
    analizador.add_argument("origen")
    analizador.add_argument("destino")
    opciones = analizador.parse_args(argumentos)

    try:
        puestos = extraer(opciones.origen, opciones.destino)
    except lectura.NoEsLandXml as fallo:
        print(f"No se pudo leer el LandXML: {fallo}", file=sys.stderr)
        return 2

    if not puestos:
        # **No se cree el codigo de salida ni siquiera el nuestro.** Un CSV con solo el
        # encabezado produce una capa vacia perfectamente valida.
        print(
            "El LandXML no trae ningún punto. Las superficies y los alineamientos todavía "
            "no se convierten.",
            file=sys.stderr,
        )
        return 3

    print(f"{puestos} puntos extraídos.")
    return 0


if __name__ == "__main__":  # pragma: no cover - lo ejerce el proceso hijo
    raise SystemExit(main())
