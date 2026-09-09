"""Escribir LandXML: la forma en que Civil 3D importa puntos **de verdad**.

## Por qué existe, teniendo ya DXF

Un DXF con puntos entra en Civil 3D como dibujo: entidades `AcDbPoint` sueltas en el
espacio. Se ven, y se acabó. **LandXML entra como grupo de puntos COGO**, con su número y su
descripción, que es lo que hace que el punto sirva para replantear, para listarlo en una
tabla y para que el código `pr` mueva el estilo que le toca. Es la diferencia entre entregar
un plano y entregar datos de topografía.

Y no hay atajo: **OGR no trae controlador de LandXML**, ni de lectura ni de escritura.
Comprobado con `ogrinfo --formats` en la instalación de esta máquina.

## Se escribe a mano y en flujo, sin construir un árbol

Con `xml.etree` habría que tener el documento entero en memoria antes de escribir nada, y
una libreta de una obra grande trae cientos de miles de puntos. Se escribe línea a línea,
escapando cada valor con `xml.sax.saxutils.escape`, que es lo mismo que haría el árbol y
cuesta un objeto en vez de un millón.

## El orden de las coordenadas, otra vez

El contenido de un `<CgPoint>` es **norte, este, cota**, en ese orden y separado por
espacios. Coincide con PNEZD, que es una simetría cómoda y una trampa: es el mismo error de
siempre esperando en otro sitio. Hay una prueba que lo fija contra un ejemplo escrito a mano.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

# `escape` y `quoteattr` **serializan**, no analizan: convierten `&` en `&amp;` y ponen las
# comillas de un atributo. Bandit marca todo `xml.sax` por el nombre del paquete (B406), y
# aquí no se analiza ningún XML — este módulo solo escribe. La alternativa sería escribir a
# mano las cinco sustituciones, y `quoteattr` además convierte saltos de línea y tabuladores
# en referencias de carácter: reimplementarlo sería asumir un riesgo real para callar un
# aviso que no lo es.
from xml.sax.saxutils import escape, quoteattr  # nosec B406

# Este modulo se ejecuta **como proceso hijo** (`python -m apps.vector.landxml`), asi que no
# puede dar por hecho que la raiz del repositorio este en `sys.path`.
if __package__ in (None, ""):  # pragma: no cover - solo en el arranque del hijo
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.formats import puntos as puntos_mod  # noqa: E402

#: La version del esquema que lee Civil 3D sin rechistar. La 2.0 existe y casi nadie la usa.
VERSION = "1.2"
ESPACIO = "http://www.landxml.org/schema/LandXML-1.2"
ESQUEMA = f"{ESPACIO} {ESPACIO}/LandXML-1.2.xsd"


def _cabecera(*, epsg: str, nombre_crs: str, cuando: datetime, aplicacion: str) -> str:
    """El preámbulo. `Units` no es decoración: sin él, Civil 3D pregunta."""
    coordenadas = ""
    if epsg:
        # `epsgCode` es lo que de verdad mira Civil 3D. El `name` va porque un humano
        # abriendo el XML en un editor merece leer algo más que un número.
        coordenadas = (
            f"  <CoordinateSystem epsgCode={quoteattr(epsg)} "
            f"name={quoteattr(nombre_crs or f'EPSG:{epsg}')} />\n"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<LandXML xmlns="{ESPACIO}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f"xsi:schemaLocation={quoteattr(ESQUEMA)} "
        f'version="{VERSION}" date="{cuando:%Y-%m-%d}" time="{cuando:%H:%M:%S}" '
        'language="Spanish" readOnly="false">\n'
        "  <Units>\n"
        '    <Metric areaUnit="squareMeter" linearUnit="meter" volumeUnit="cubicMeter"\n'
        '            temperatureUnit="celsius" pressureUnit="milliBars"\n'
        '            angularUnit="decimal degrees" directionUnit="decimal degrees" />\n'
        "  </Units>\n"
        f"{coordenadas}"
        f"  <Application name={quoteattr(aplicacion)} />\n"
    )


def _cgpoint(punto: puntos_mod.Punto, indice: int) -> str:
    """Un punto.

    El `name` es obligatorio y tiene que ser único: si la libreta no traía número de punto
    se pone el correlativo. Dejarlo vacío hace que Civil 3D importe **un solo punto**,
    machacando los anteriores, y sin decir nada.
    """
    nombre = punto.identificador.strip() or str(indice)
    atributos = f" name={quoteattr(nombre)}"
    if punto.descripcion.strip():
        # `code` es la descripción bruta del topógrafo, que es la que engancha con los
        # estilos de punto de Civil 3D. `desc` sería la descripción ya traducida.
        atributos += f" code={quoteattr(punto.descripcion.strip())}"

    # Norte, este, cota. En ese orden.
    return (
        f"    <CgPoint{atributos}>"
        f"{escape(f'{punto.norte_m:.6f} {punto.este_m:.6f} {punto.cota_m:.6f}')}"
        "</CgPoint>\n"
    )


def escribir(
    puntos: Iterable[puntos_mod.Punto],
    destino: str | Path,
    *,
    epsg: str = "",
    nombre_crs: str = "",
    nombre_grupo: str = "",
    aplicacion: str = "AeroConvert",
    cuando: datetime | None = None,
) -> int:
    """Escribe el LandXML y devuelve cuántos puntos puso.

    Toma un **iterable** y no una `CabeceraPuntos` a propósito: `cabecera.muestra` está
    recortada a `MUESTRA_MAXIMA` para poder dibujarla, y entregar un archivo con tres mil
    puntos de los cien mil que traía el original —con la misma cara— sería el peor fallo
    posible aquí. Pidiendo el iterable, ese error no se puede cometer por descuido: hay que
    pasarle algo, y lo que se le pasa es `puntos.iterar()`.
    """
    destino = Path(destino)
    cuando = cuando or datetime.now(UTC)
    grupo = nombre_grupo or destino.stem

    puestos = 0
    with open(destino, "w", encoding="utf-8", newline="\n") as salida:
        salida.write(
            _cabecera(epsg=epsg, nombre_crs=nombre_crs, cuando=cuando, aplicacion=aplicacion)
        )
        salida.write(f"  <CgPoints name={quoteattr(grupo)}>\n")
        for indice, punto in enumerate(puntos, start=1):
            salida.write(_cgpoint(punto, indice))
            puestos += 1
        salida.write("  </CgPoints>\n")
        salida.write("</LandXML>\n")

    return puestos


def main(argumentos: list[str] | None = None) -> int:
    """Punto de entrada del proceso hijo.

    Es un proceso aparte y no una llamada de función porque el runner necesita poder
    **cancelarlo** y ponerle un presupuesto de tiempo, y porque un fallo de memoria con un
    archivo enorme no puede llevarse por delante el servidor. Es la misma decisión que hace
    que GDAL y PDAL corran fuera.
    """
    analizador = argparse.ArgumentParser(description="Escribe una libreta de puntos como LandXML.")
    analizador.add_argument("origen")
    analizador.add_argument("destino")
    analizador.add_argument("--orden", default="")
    analizador.add_argument("--epsg", default="")
    analizador.add_argument("--nombre-crs", default="")
    analizador.add_argument("--grupo", default="")
    opciones = analizador.parse_args(argumentos)

    try:
        puestos = escribir(
            puntos_mod.iterar(opciones.origen, orden=opciones.orden),
            opciones.destino,
            epsg=opciones.epsg,
            nombre_crs=opciones.nombre_crs,
            nombre_grupo=opciones.grupo,
        )
    except puntos_mod.NoEsArchivoDePuntos as fallo:
        print(f"No se pudo leer la libreta: {fallo}", file=sys.stderr)
        return 2

    if not puestos:
        # **No se cree el código de salida ni siquiera el nuestro.** Un LandXML con cero
        # puntos es un archivo válido y bien formado que Civil 3D abre sin protestar y sin
        # enseñar nada. Que falle aquí, ruidosamente.
        print("No se pudo interpretar ninguna línea de la libreta.", file=sys.stderr)
        return 3

    print(f"{puestos} puntos escritos.")
    return 0


if __name__ == "__main__":  # pragma: no cover - lo ejerce el proceso hijo
    raise SystemExit(main())
