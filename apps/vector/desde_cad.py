"""DWG y DGN v8 a DXF, con el ODA File Converter.

## Por qué este paso existe

DWG es un formato cerrado de Autodesk y **no hay forma abierta de leerlo sin contagiar la
licencia**: LibreDWG es GPL-3 y se llevaría por delante la de AeroConvert entero. El ODA File
Converter es gratuito, lo publica la Open Design Alliance —que es quien mantiene la
especificación de DWG— y se instala aparte con su propia EULA. Por eso **se sondea y no se
declara**, igual que GDAL, que Office y que Tesseract.

DGN se parte en dos: la v7 la lee GDAL con controlador abierto y no pasa por aquí; **la v8
necesita ODA**, y v8 es lo que entrega cualquiera desde hace quince años.

## Las tres cosas que hacen esto más raro de lo que parece

**1. ODA convierte carpetas, no archivos.** No hay forma de decirle «este archivo». Así que se
le arma una carpeta de entrada con una sola copia dentro y se recoge lo que deje en la de
salida. Las dos son temporales y se borran solas.

**2. Su código de salida no sirve para saber si funcionó.** Devuelve cero habiendo escrito un
registro de errores y ningún DXF. Así que **no se mira el código: se mira si hay archivo**, y
si no lo hay se cuenta lo que el propio ODA dejó escrito.

**3. En Linux es un programa de ventanas aunque no enseñe ninguna.** Está hecho con Qt y
necesita un servidor gráfico para arrancar, así que en el servidor hay que envolverlo en
`xvfb-run`. Eso no se adivina leyendo un error: lo que sale es un fallo de Qt sobre un
«display» que nadie pidió. Aquí se detecta y se dice con el paquete que falta.

## Por qué se baja a ACAD2000 y no se mantiene la versión

Parece una pérdida y es lo contrario. Al bajar de versión, ODA **descompone** las entidades
modernas que el lector DXF de GDAL no entendería —y que dejaría fuera en silencio— en
primitivas que sí lee. Lo que se quiere de un plano aquí son sus líneas, sus puntos y sus
textos, no su árbol de objetos.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - lanzar herramientas externas es lo que hace esta aplicación
import sys
import tempfile
from pathlib import Path

# Se ejecuta como proceso hijo (`python -m apps.vector.desde_cad`), asi que no puede dar por
# hecho que la raiz del repositorio este en `sys.path`. Igual que `desde_landxml`.
if __package__ in (None, ""):  # pragma: no cover - solo en el arranque del hijo
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

#: La versión de salida. Ver el docstring del módulo: bajar descompone, y descomponer es lo
#: que hace que GDAL vea las entidades en vez de saltárselas.
VERSION_DE_SALIDA = "ACAD2000"

#: Lo que ODA sabe recibir de los formatos que aquí interesan, con su filtro de entrada.
FILTROS = {".dwg": "*.DWG", ".dgn": "*.DGN"}

#: Un plano de obra grande tarda, pero no diez minutos. Pasado esto es que se colgó esperando
#: algo —una ventana, una licencia— y seguir esperando no lo arregla.
TOPE_SEGUNDOS = 600


class SinConversorDeCad(RuntimeError):
    """No se puede convertir, y el mensaje dice qué falta y cómo ponerlo."""


def donde_esta() -> str:
    """La ruta del conversor, o cadena vacía. **Configuración primero, PATH después.**

    Lee la variable de entorno directamente cuando Django no está levantado, que es el caso
    del proceso hijo. Arrancar Django entero —con su base de datos y sus aplicaciones— para
    leer una cadena costaría más que la conversión.
    """
    configurada = ""
    try:
        from django.conf import settings

        configurada = (settings.ODA_CONVERTER or "").strip().strip('"')
    except Exception:  # nosec B110 - sin Django se sigue por la variable de entorno
        # No es tragarse un error: es que **este módulo corre en los dos lados**. En el padre
        # Django está y manda su ajuste; en el hijo no está, y entonces la variable de
        # entorno es la fuente correcta, no un remiendo.
        pass
    if not configurada:
        configurada = (os.environ.get("AEROCONVERT_ODA_CONVERTER") or "").strip().strip('"')

    if configurada and Path(configurada).is_file():
        return configurada
    return shutil.which("ODAFileConverter") or ""


def _envoltura() -> list[str]:
    """`xvfb-run` delante, en Linux, si está.

    ODA está hecho con Qt y **necesita un servidor gráfico para arrancar aunque no dibuje
    nada**. En el servidor no hay ninguno, así que sin esto el fallo que sale habla de un
    «display» y no de CAD, y nadie relaciona una cosa con la otra.
    """
    if os.name == "nt" or os.environ.get("DISPLAY"):
        return []
    xvfb = shutil.which("xvfb-run")
    return [xvfb, "-a"] if xvfb else []


def a_dxf(origen: str | Path, destino: str | Path) -> Path:
    """Escribe el DXF equivalente y devuelve su ruta.

    Levanta `SinConversorDeCad` con el motivo cuando no se puede, que es lo que el runner
    convierte en el mensaje de la ficha.
    """
    origen = Path(origen)
    destino = Path(destino)

    conversor = donde_esta()
    if not conversor:
        raise SinConversorDeCad(
            "No hay conversor de CAD en este equipo. DWG es un formato cerrado de Autodesk y "
            "hace falta el ODA File Converter, que es gratuito: instálalo y apunta "
            "AEROCONVERT_ODA_CONVERTER a su ejecutable. Mientras tanto, «Guardar como DXF» "
            "desde cualquier CAD hace el mismo primer paso."
        )

    filtro = FILTROS.get(origen.suffix.lower())
    if filtro is None:
        raise SinConversorDeCad(
            f"{origen.name} no es un DWG ni un DGN, que es lo único que pasa por aquí."
        )
    if not origen.is_file():
        raise SinConversorDeCad(f"No está {origen.name}.")

    envoltura = _envoltura()
    if os.name != "nt" and not os.environ.get("DISPLAY") and not envoltura:
        raise SinConversorDeCad(
            "El conversor de ODA necesita un servidor gráfico para arrancar, aunque no "
            "dibuje nada, y en este equipo no hay ninguno ni está «xvfb-run» para fingirlo. "
            "Se resuelve con «sudo apt install xvfb»."
        )

    with tempfile.TemporaryDirectory(prefix="aeroconvert-cad-") as carpeta:
        raiz = Path(carpeta)
        entrada, salida = raiz / "entra", raiz / "sale"
        entrada.mkdir()
        salida.mkdir()

        # El nombre se normaliza: ODA filtra por extensión y la compara en mayúsculas, y hay
        # nombres que le sientan mal. El de verdad no importa aquí -- el resultado se mueve a
        # `destino`, que es quien conserva el nombre que verá la persona.
        copia = entrada / f"plano{origen.suffix.lower()}"
        shutil.copy2(origen, copia)

        orden = [
            *envoltura,
            conversor,
            str(entrada),
            str(salida),
            VERSION_DE_SALIDA,
            "DXF",
            "0",  # sin recorrer subcarpetas: solo hay un archivo
            "1",  # con auditoría: un DWG dañado se arregla o se dice, no se convierte a medias
            filtro,
        ]

        try:
            proceso = subprocess.run(  # nosec B603 - ejecutable sondeado, sin shell
                orden,
                capture_output=True,
                text=True,
                timeout=TOPE_SEGUNDOS,
                check=False,
            )
        except subprocess.TimeoutExpired as fallo:
            raise SinConversorDeCad(
                f"El conversor de CAD lleva {TOPE_SEGUNDOS // 60} minutos sin terminar con "
                f"{origen.name} y se ha parado. Suele ser que se quedó esperando algo que "
                "nadie va a contestar."
            ) from fallo
        except OSError as fallo:
            raise SinConversorDeCad(f"No se pudo lanzar el conversor de CAD: {fallo}") from fallo

        # **El código de salida no se mira**: devuelve cero habiendo escrito un registro de
        # errores y ningún DXF. Lo que decide es si hay archivo.
        producidos = sorted(salida.glob("*.dxf")) + sorted(salida.glob("*.DXF"))
        if not producidos:
            raise SinConversorDeCad(_por_que_no_salio(origen, salida, proceso))

        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(producidos[0]), destino)

    return destino


def _por_que_no_salio(origen: Path, salida: Path, proceso) -> str:
    """El motivo, buscándolo donde ODA lo deja y no donde sería cómodo.

    Escribe los errores en archivos dentro de la carpeta de salida y **no en la salida de
    error del proceso**, así que quedarse con `stderr` da un mensaje vacío en el caso que más
    importa: el archivo que no se pudo convertir.
    """
    for registro in sorted(salida.glob("*.txt")):
        try:
            texto = registro.read_text("utf-8", errors="replace").strip()
        except OSError:
            continue
        if texto:
            return f"El conversor de CAD no pudo con {origen.name}: {texto[:300]}"

    detalle = (proceso.stderr or proceso.stdout or "").strip()
    if "display" in detalle.lower() or "xcb" in detalle.lower():
        return (
            "El conversor de CAD no arrancó porque no encontró servidor gráfico. Necesita "
            "uno aunque no dibuje nada: «sudo apt install xvfb» lo resuelve."
        )
    return f"El conversor de CAD terminó sin escribir nada para {origen.name}" + (
        f": {detalle[:300]}" if detalle else ". No dejó dicho por qué."
    )


def main(argv: list[str]) -> int:
    """Para poder lanzarlo como paso de un plan, igual que `desde_landxml`."""
    if len(argv) != 2:
        print("uso: python -m apps.vector.desde_cad <origen.dwg|dgn> <destino.dxf>")
        return 2
    try:
        a_dxf(argv[0], argv[1])
    except SinConversorDeCad as fallo:
        print(str(fallo), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - lo ejerce el proceso hijo
    raise SystemExit(main(sys.argv[1:]))
