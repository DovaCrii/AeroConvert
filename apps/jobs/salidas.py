"""Dónde y cómo se escribe la salida: destino libre, reserva, espacio, borrado y renombrado.

Salió de `runner.py` en F11.8 sin cambiar una línea. Es donde viven la regla cinco (el original
no se toca: la salida va a `<destino>.parcial` y solo se renombra con `os.replace()` tras
verificarla) y el arreglo de confidencialidad de `_destino_libre`.
"""

from __future__ import annotations

import glob
import os
import shutil
import time
from pathlib import Path

from .fallos import TrabajoFallido
from .models import ConversionJob, JobEvent

#: Reintentos del renombrado final. El antivirus abre el archivo recien escrito durante un
#: instante, y ese caso si es transitorio -- a diferencia de QGIS teniendolo abierto.
REINTENTOS_DE_RENOMBRADO = 3

#: Cuantos nombres se prueban antes de rendirse. Cincuenta versiones del mismo entregable en
#: la misma carpeta ya no es un caso legitimo: es un bucle o un malentendido.
MAXIMO_VERSIONES = 50


def _con_version(destino: Path, version: int) -> Path:
    """`salida.tif` → `salida_2.tif`, y `nube.copc.laz` → `nube_2.copc.laz`.

    Se corta en el **primer** punto por la misma razon que `ruta_parcial()`: las extensiones
    compuestas son parte del formato, y media herramienta geoespacial deduce el formato de la
    extension.
    """
    raiz, punto, extensiones = destino.name.partition(".")
    if not punto:
        return destino.with_name(f"{raiz}_{version}")
    return destino.with_name(f"{raiz}_{version}.{extensiones}")


def _destino_libre(job, destino: Path) -> Path:
    """El primer nombre que no le pise la salida a **otra persona**.

    Este es el arreglo de un fallo de confidencialidad, no una comodidad. La ruta de salida
    se construye de forma determinista -- `ortofoto_civil3d.tif` -- y en una carpeta
    compartida dos personas que conviertan cada una su `ortofoto.tif` con el mismo perfil
    producian **exactamente la misma ruta**. La segunda sobrescribia a la primera, y la
    descarga sirve lo que haya en `output_path`: alguien se bajaba el archivo de otro.

    Lo que **no** hace es evitar que sobrescribas lo tuyo. Volver a convertir el mismo
    archivo y encontrarse el resultado donde estaba es lo que uno espera; obligar a
    `_2`, `_3`, `_4` cada vez seria cambiar un fallo por una molestia diaria. Por eso la
    pregunta no es «¿existe el archivo?» sino «¿lo reclama el trabajo de otro?».
    """
    from .models import ConversionJob

    # **Nunca el propio original.** Una herramienta cuya salida lleva la misma extensión que
    # su entrada (un `.pdf` pasado a «Markdown a PDF») apuntaba el destino al archivo de
    # partida, y el `os.replace` final lo sustituía con el trabajo dando «verificado».
    originales = {_clave_de_ruta(job.source_path)}
    originales.update(_clave_de_ruta(ruta) for ruta in job.entradas.values_list("ruta", flat=True))

    for version in range(1, MAXIMO_VERSIONES + 1):
        candidata = destino if version == 1 else _con_version(destino, version)
        if _clave_de_ruta(candidata) in originales:
            continue
        de_otro = (
            ConversionJob.objects.filter(output_path=str(candidata))
            .exclude(pk=job.pk)
            .exclude(owner=job.owner)
            .exists()
        )
        if not de_otro:
            return candidata

    raise TrabajoFallido(
        "salida-bloqueada",
        f"Hay {MAXIMO_VERSIONES} versiones de {destino.name} en esa carpeta. Revisa antes de "
        "seguir generando.",
    )


def _clave_de_ruta(ruta) -> str:
    """Una ruta comparable: sin mayúsculas en Windows y sin `..` ni enlaces."""
    texto = str(ruta or "")
    if not texto:
        return ""
    try:
        texto = str(Path(texto).resolve())
    except OSError:
        pass
    return os.path.normcase(texto)


def _reservar_destino(destino: Path) -> None:
    """Comprueba **antes de empezar** que se podra escribir ahi.

    Lo caro no es que falle: es que falle al final. Un destino abierto en QGIS hace fallar
    el renombrado tras horas de conversion.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    testigo = destino.with_name(destino.name + ".prueba")
    try:
        with open(testigo, "xb"):
            pass
    except FileExistsError:
        _borrar(testigo)
    except PermissionError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada",
            f"No se puede escribir en {destino.parent}: sin permiso o carpeta bloqueada.",
        ) from fallo
    except OSError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada", f"No se puede escribir en {destino.parent}: {fallo}"
        ) from fallo
    else:
        _borrar(testigo)

    if not destino.exists():
        return

    # **Abrir el archivo no sirve para saber si esta bloqueado.** En Windows, Python abre
    # con FILE_SHARE_READ|FILE_SHARE_WRITE, asi que `open(destino, "ab")` funciona aunque
    # QGIS lo tenga abierto -- y la comprobacion daba siempre verde mientras el fallo real
    # aparecia al final, en `os.replace()`, tras horas de conversion. Que es exactamente lo
    # que esta funcion existe para evitar.
    #
    # Lo que si lo detecta es intentar **la misma operacion** que se hara al final:
    # renombrar. Un archivo con un manejador abierto no se puede renombrar, asi que se
    # renombra y se deja como estaba. Cuesta dos llamadas al sistema.
    testigo = destino.with_name(destino.name + ".enuso")
    _borrar(testigo)
    try:
        os.replace(destino, testigo)
    except OSError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada",
            f"{destino.name} esta abierto en otro programa. Cierralo y reintenta.",
        ) from fallo

    try:
        os.replace(testigo, destino)
    except OSError as fallo:  # pragma: no cover - solo si algo se lo lleva entremedias
        raise TrabajoFallido(
            "salida-bloqueada",
            f"No se pudo devolver {destino.name} a su sitio: {fallo}. Quedo como {testigo.name}.",
        ) from fallo


def _exigir_espacio(destino: Path, bytes_origen: int) -> None:
    """Que quepa la salida. Llenar el disco de la estacion de trabajo la tumba entera."""
    try:
        libre = shutil.disk_usage(destino.parent).free
    except OSError:
        return
    # Se pide el tamano del origen como estimacion. Es conservador para una conversion con
    # perdida y ajustado para una sin perdida, que es cuando de verdad importa.
    if libre < bytes_origen:
        raise TrabajoFallido(
            "sin-espacio",
            f"Quedan {libre / 1e9:.1f} GB libres y la salida puede necesitar "
            f"{bytes_origen / 1e9:.1f} GB.",
        )


def _exigir_espacio_de_la_salida(job: ConversionJob, inspeccion, destino: Path) -> None:
    """Que quepa la salida **tal como la estima la cabecera**, no como pesa el archivo.

    `_exigir_espacio` compara contra el tamaño del archivo de partida, que es el comprimido:
    un GeoTIFF de 10 KB que declara 200.000 × 200.000 píxeles de ceros se convertía a un
    destino sin compresión y llenaba el disco compartido (hallazgo B-01 de la auditoría).
    La estimación ya existía y solo se enseñaba; aquí se hace cumplir. Solo con cabecera de
    TIFF: sin ella la estimación no tiene de dónde sacar el tamaño real.
    """
    if getattr(inspeccion, "tiff", None) is None:
        return

    from . import estimacion

    estimada = estimacion.estimar(
        inspeccion=inspeccion,
        formato_destino=job.target_format_code,
        opciones=dict(job.options or {}),
        destino=destino,
    )
    # `libre_bytes == 0` es «no se pudo medir»: no se rechaza por una lectura fallida.
    if estimada.libre_bytes and estimada.libre_bytes < estimada.bytes_salida:
        raise TrabajoFallido(
            "sin-espacio",
            f"Esta conversión escribiría unos {estimada.bytes_salida / 1e9:.1f} GB y quedan "
            f"{estimada.libre_bytes / 1e9:.1f} GB libres. Lo que pesa el archivo comprimido "
            "no es lo que pesará la salida.",
        )


def _limpiar_restos(parcial: Path) -> None:
    """Borra los acompanantes que GDAL colgo del nombre del parcial.

    GDAL escribe un `.aux.xml` junto a lo que crea, y como lo crea con el nombre del
    parcial, ese acompanante se queda huerfano en cuanto el archivo se renombra: nadie lo
    reclama y nadie lo borra. Son unos pocos kilobytes cada uno, pero se acumulan uno por
    conversion y **contradicen lo que se promete** -- que el entregable es un solo archivo
    que se basta a si mismo.

    Se borra por prefijo. El destino nunca coincide: `entrega.jp2` no empieza por
    `entrega.jp2.parcial`.
    """
    try:
        for resto in parcial.parent.glob(glob.escape(parcial.name) + ".*"):
            _borrar(resto)
    except OSError:
        pass


def _borrar(ruta: Path) -> None:
    try:
        ruta.unlink(missing_ok=True)
    except OSError:
        # Que no se pueda borrar el parcial es feo, no grave: el trabajo ya fallo y el
        # motivo real es el que se esta reportando.
        pass
    if ".parcial" in ruta.name:
        # Los intermedios que un motor deja **colgados del nombre del parcial** (el GeoPackage 3D
        # de las curvas en DXF, un `.aux.xml`) se van con él, también cuando el trabajo falla: antes
        # solo el camino feliz los limpiaba.
        try:
            restos = list(ruta.parent.glob(glob.escape(ruta.name) + ".*"))
        except OSError:
            restos = []
        for resto in restos:  # uno por uno: que uno esté abierto no salva a los demás
            try:
                if resto.is_dir():
                    # **Solo** la carpeta de trabajo de LibreOffice (`<parcial>.lo`), si el hijo
                    # murió antes de borrarla él mismo; nunca otra carpeta, ni un enlace.
                    if resto.name == ruta.name + ".lo" and not resto.is_symlink():
                        shutil.rmtree(resto, ignore_errors=True)
                else:
                    resto.unlink(missing_ok=True)
            except OSError:
                pass


def _renombrar_con_acompanantes(job: ConversionJob, parcial: Path, destino: Path) -> None:
    """Renombra la salida **y los archivos que la acompañan**.

    Un Shapefile no es un archivo: son cinco. `salida.shp` sin su `.shx` y su `.dbf` al lado
    **no abre en ninguna parte** -- `ogrinfo` responde «Unable to open salida.shx». Y no
    fallaba de forma visible: la verificacion corre sobre el parcial, cuando los hermanos
    todavia se llaman `salida.parcial.shx`, asi que pasaba; el renombrado movia solo el
    `.shp` y los dejaba huerfanos. El recibo decia «verificado» sobre un entregable
    inservible, que es el peor fallo que puede tener esto.

    Cuales acompañan lo dice el catalogo, no una lista escrita aqui: es el mismo dato que ya
    usa la ficha para avisar de que falta un `.prj`.
    """
    from apps.formats import catalogo

    _renombrar(parcial, destino)

    formato = catalogo.FORMATOS.get(job.target_format_code)
    if formato is None or not formato.acompanantes:
        return

    for extension in sorted(formato.acompanantes):
        hermano = parcial.with_suffix(extension)
        if not hermano.exists():
            continue
        try:
            _renombrar(hermano, destino.with_suffix(extension))
        except TrabajoFallido:
            # Un acompañante que no se puede mover deja el entregable incompleto, y eso hay
            # que decirlo: el archivo principal ya esta en su sitio y parece correcto.
            job.registrar(
                f"No se pudo colocar {destino.with_suffix(extension).name} junto a la "
                "salida. El archivo puede no abrir sin el.",
                nivel=JobEvent.ERROR,
            )


def _renombrar(parcial: Path, destino: Path) -> None:
    """`os.replace()` con reintentos, por el antivirus.

    Se reintenta tres veces con espera creciente. No es esconder un fallo: el caso del
    antivirus mirando el archivo recien escrito dura decimas de segundo, mientras que un
    destino abierto en QGIS falla las tres veces y acaba dando su motivo.
    """
    ultimo = None
    for intento in range(REINTENTOS_DE_RENOMBRADO):
        try:
            os.replace(parcial, destino)
            return
        except PermissionError as fallo:
            ultimo = fallo
            time.sleep(0.5 * (intento + 1))
        except OSError as fallo:
            ultimo = fallo
            break
    _borrar(parcial)
    raise TrabajoFallido(
        "salida-bloqueada",
        f"No se pudo escribir {destino.name}: {ultimo}. "
        "Suele ser que este abierto en otro programa.",
    )
