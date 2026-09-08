"""El modo de operacion, y la unica puerta por la que entra una ruta del disco.

En modo taller la persona escribe o pega una ruta. Eso es, literalmente, un primitivo de
lectura del sistema de archivos expuesto en un formulario web -- da igual que escuche solo
en 127.0.0.1: un enlace en un correo puede hacer que el navegador de la persona envie el
formulario. Por eso `AEROCONVERT_RAICES_PERMITIDAS` es obligatoria en este modo, y por eso
la comprobacion vive aca y no en el formulario: el formulario es evadible desde la API y
desde el admin, esta funcion no.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


class RutaNoPermitida(Exception):
    """La ruta esta fuera de las raices configuradas, o no se puede resolver."""

    def __init__(self, mensaje: str, codigo: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def es_taller() -> bool:
    return settings.MODO == settings.MODO_TALLER


def es_nube() -> bool:
    return settings.MODO == settings.MODO_NUBE


def raices_permitidas() -> tuple[Path, ...]:
    """Las raices bajo las que se puede leer, ya resueltas.

    Se separan con `;` porque en Windows `:` aparece dentro de cada ruta (`D:\\`).
    """
    crudo = (settings.RAICES_PERMITIDAS or "").strip()
    if not crudo:
        return ()
    raices = []
    for trozo in crudo.split(";"):
        trozo = trozo.strip()
        if not trozo:
            continue
        try:
            raices.append(Path(trozo).resolve(strict=False))
        except (OSError, ValueError):
            # Una raiz mal escrita se ignora en vez de tumbar el arranque, pero
            # `revisar_configuracion()` la reporta.
            continue
    return tuple(raices)


def revisar_configuracion() -> tuple[str, ...]:
    """Problemas de configuracion, en texto para la persona. Vacio = todo bien.

    Lo llama `manage.py check` a traves de `apps.core.checks`, para que un taller sin
    raices configuradas se note al arrancar y no al primer intento de conversion.
    """
    problemas: list[str] = []
    if es_taller():
        raices = raices_permitidas()
        if not raices:
            problemas.append(
                "AEROCONVERT_RAICES_PERMITIDAS esta vacia y el modo es taller. Sin ella "
                "cualquier ruta del disco seria legible desde el formulario. Ponla en .env, "
                "por ejemplo AEROCONVERT_RAICES_PERMITIDAS=D:\\"
            )
        for raiz in raices:
            if not raiz.exists():
                problemas.append(f"La raiz permitida {raiz} no existe.")
    return tuple(problemas)


def comprobar_ruta(ruta: str | Path) -> Path:
    """Devuelve la ruta resuelta si esta dentro de una raiz permitida. Si no, levanta.

    **No comprueba que el archivo exista**: eso lo dice la inspeccion, con su propio motivo.
    Aca solo se decide si tenemos derecho a mirar ahi.
    """
    if not es_taller():
        raise RutaNoPermitida(
            "En modo nube los archivos se suben, no se leen del disco del servidor.",
            "ruta-no-permitida",
        )

    texto = str(ruta).strip().strip('"')
    if not texto:
        raise RutaNoPermitida("No se indico ninguna ruta.", "ruta-no-permitida")

    # El limite clasico de Windows. Mas alla, GDAL y las herramientas externas fallan de
    # formas raras, asi que se para antes y se dice por que.
    if len(texto) > 255:
        raise RutaNoPermitida(
            f"La ruta tiene {len(texto)} caracteres y el limite practico son 255. "
            "Mueve el archivo a una carpeta con nombre mas corto.",
            "ruta-demasiado-larga",
        )

    try:
        candidata = Path(texto).resolve(strict=False)
    except (OSError, ValueError) as fallo:
        raise RutaNoPermitida(
            f"No se pudo interpretar la ruta: {fallo}", "origen-no-legible"
        ) from fallo

    raices = raices_permitidas()
    if not raices:
        raise RutaNoPermitida(
            "No hay raices permitidas configuradas. Revisa AEROCONVERT_RAICES_PERMITIDAS.",
            "ruta-no-permitida",
        )

    for raiz in raices:
        if candidata == raiz or raiz in candidata.parents:
            return candidata

    listado = ", ".join(str(r) for r in raices)
    raise RutaNoPermitida(
        f"{candidata} esta fuera de las carpetas permitidas ({listado}).",
        "ruta-no-permitida",
    )


@dataclass(frozen=True)
class Chapa:
    """Lo que la interfaz pinta arriba, en todas las pantallas."""

    modo: str
    etiqueta: str
    explicacion: str


def chapa() -> Chapa:
    if es_taller():
        return Chapa(
            modo=settings.MODO_TALLER,
            etiqueta="Taller",
            explicacion="Los archivos se leen de tu disco y no salen de esta máquina.",
        )
    return Chapa(
        modo=settings.MODO_NUBE,
        etiqueta="Nube",
        explicacion=f"Los archivos se suben al servidor. Tope {settings.TOPE_MB} MB.",
    )
