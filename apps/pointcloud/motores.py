"""Motores de nubes de puntos. **Vacio a proposito hasta la fase F2.**

La app existe desde la fase 0, sin un solo motor dentro, por dos razones concretas:

1. La fase que la llene no tendra que tocar `INSTALLED_APPS` ni el registro.
2. Hay una prueba, desde el primer dia, de que el registro **tolera una familia sin
   motores**. Un registro que revienta con una lista vacia se descubre el dia que se anade
   la familia, con prisa.

Lo que llegara: LAS/LAZ -> COPC portando `AeroBim/apps/web/scripts/a-copc.py`, que ya esta
escrito y medido, y PDAL para E57 y el diezmado.
"""


def registrar_todos() -> None:
    return None
