"""El modo de operacion, y la unica puerta por la que entra una ruta del disco.

En modo taller la persona escribe o pega una ruta. Eso es, literalmente, un primitivo de
lectura del sistema de archivos expuesto en un formulario web -- da igual que escuche solo
en 127.0.0.1: un enlace en un correo puede hacer que el navegador de la persona envie el
formulario. Por eso `AEROCONVERT_RAICES_PERMITIDAS` es obligatoria en este modo, y por eso
la comprobacion vive aca y no en el formulario: el formulario es evadible desde la API y
desde el admin, esta funcion no.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

#: Hasta donde se admite una ruta, **y depende del sistema**.
#:
#: En Windows es el limite clasico: mas alla, GDAL y las herramientas externas fallan de
#: formas raras, asi que se para antes y se dice por que.
#:
#: En Linux el limite del sistema son 4096, y poner 255 ahi **es un bloqueante silencioso**:
#: una carpeta compartida con la estructura de una obra de verdad
#: -- `/mnt/entregas/CC 716 - BHP/CC 716 NEHVTI BHP/Entrega/Vuelo cruce minero/...` --
#: pasa de 255 sin esfuerzo, y el mensaje diria «mueve el archivo», que es el consejo
#: equivocado sobre una carpeta que no se puede mover.
LARGO_MAXIMO_DE_RUTA = 255 if os.name == "nt" else 4096


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

    if es_nube():
        # **El modo nube no tiene por donde entrar un archivo, y eso no es una variable que
        # falte: es una funcionalidad que no esta escrita.** `comprobar_ruta` lo cierra a
        # proposito, y la via que lo sustituiria -- la subida -- no existe: no hay ni un
        # `request.FILES` en todo el repositorio, `ConversionJob.source_upload` esta
        # huerfano, y el runner solo lee `source_path`.
        #
        # Arranca, sirve paginas, autentica, y no convierte nada. Descubrirlo al primer
        # intento de conversion, con alguien esperando, es la peor forma de enterarse.
        problemas.append(
            "AEROCONVERT_MODO=nube todavia no sirve para nada: es el modo de las subidas, y "
            "la subida de archivos no esta escrita. Para una VM compartida usa "
            "AEROCONVERT_MODO=taller con DJANGO_SETTINGS_MODULE=config.settings.prod, y "
            "apunta AEROCONVERT_RAICES_PERMITIDAS a la carpeta compartida. Ver docs/DEPLOY.md."
        )

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

        # **Estas dos solo cuando llega gente de otras maquinas**, y la distincion importa:
        # en una estacion de trabajo, dar `D:\` entero es exactamente lo que se quiere --
        # es tu disco y eres la unica que entra. En una VM compartida, la misma linea
        # convierte la sesion de cualquiera en lectura de todo el servidor.
        if _es_compartida():
            for raiz in raices:
                if _es_demasiado_ancha(raiz):
                    problemas.append(
                        f"La raiz permitida {raiz} es un volumen entero o una carpeta de "
                        "montaje, y a esta maquina entra gente desde otras. Apunta a la "
                        "carpeta de trabajo concreta y no a la unidad: /mnt/entregas, no "
                        "/mnt."
                    )
                if settings.BASE_DIR == raiz or raiz in Path(settings.BASE_DIR).parents:
                    problemas.append(
                        f"La raiz permitida {raiz} contiene el arbol de codigo de la propia "
                        "aplicacion, asi que la configuracion y la base quedan legibles "
                        "desde el formulario."
                    )
    return tuple(problemas)


def _es_demasiado_ancha(raiz: Path) -> bool:
    """¿Es una unidad entera o una carpeta de montaje?

    `C:\\` y `/` son la raiz de su arbol -- se reconocen porque su padre son ellas mismas --.
    Y en Linux hace falta ademas atrapar `/mnt`, `/home`, `/srv`: tienen padre, pero dar una
    de esas es dar todo lo que cuelgue de ahi, incluido lo que se monte manana.
    """
    if raiz.parent == raiz:
        return True
    return os.name != "nt" and len(raiz.parts) <= 2


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

    if len(texto) > LARGO_MAXIMO_DE_RUTA:
        raise RutaNoPermitida(
            f"La ruta tiene {len(texto)} caracteres y el limite practico son "
            f"{LARGO_MAXIMO_DE_RUTA}. Mueve el archivo a una carpeta con nombre mas corto.",
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


#: Los nombres por los que se llega a una maquina que es de una sola persona. Cualquier otra
#: cosa en `ALLOWED_HOSTS` -- un dominio, una IP de la red -- significa que hay mas gente.
NOMBRES_LOCALES = frozenset({"localhost", "127.0.0.1", "[::1]", "testserver"})


def _es_compartida() -> bool:
    """¿Llega gente desde otras máquinas?"""
    return any(
        str(nombre).strip().lower() not in NOMBRES_LOCALES
        for nombre in (settings.ALLOWED_HOSTS or ())
    )


@dataclass(frozen=True)
class Chapa:
    """Lo que la interfaz pinta arriba, en todas las pantallas."""

    modo: str
    etiqueta: str
    explicacion: str


def chapa() -> Chapa:
    if es_taller():
        # **El texto depende de si la maquina es de uno o del equipo**, y eso lo dice el
        # servidor: en la estacion de trabajo se escucha en `127.0.0.1`, y en la VM
        # compartida hay un nombre de dominio en `ALLOWED_HOSTS`. Prometer «no salen de
        # esta máquina» a cinco personas que comparten una carpeta seria mentir en todas
        # las pantallas.
        if _es_compartida():
            return Chapa(
                modo=settings.MODO_TALLER,
                etiqueta="Equipo",
                explicacion=(
                    "Los archivos salen de la carpeta compartida, y lo que conviertas lo "
                    "ve todo el equipo."
                ),
            )
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
