"""Los motivos por los que un trabajo no sale, con codigo estable.

## Por que un codigo ademas del mensaje

El mensaje es para la persona y cambia: se reescribe, se traduce, se afina. El codigo es
para el sistema y no cambia nunca -- lo consultan las pruebas, la interfaz para elegir que
ofrecer, y quien lea la bitacora dentro de un ano. Es el mismo criterio que ya usa
`AeroBim/services/api/apps/documents/conversion.py`, y su vocabulario se hereda entero en
vez de inventar otro paralelo.

## Y por que reintentar es `False` por omision

Porque casi nada de lo que falla aqui mejora repitiendolo. Reintentar `sin-clave-ecw` tres
veces es gastar el tiempo de alguien confirmando lo mismo. Solo es reintentable lo que
depende de algo que puede cambiar solo: un archivo que otro programa tenia abierto, un
antivirus que estaba mirando, un obrero que murio.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Motivo:
    codigo: str
    mensaje: str
    sugerencia: str = ""


def _m(codigo: str, mensaje: str, sugerencia: str = "") -> tuple[str, Motivo]:
    return codigo, Motivo(codigo, mensaje, sugerencia)


MOTIVOS: dict[str, Motivo] = dict(
    [
        # --- Falta una herramienta -----------------------------------------
        _m("sin-motor", "Ningún motor sabe hacer esta conversión."),
        _m(
            "motor-no-disponible",
            "El motor existe pero no esta instalado en esta máquina.",
            "Revisa INSTALL.md.",
        ),
        _m(
            "sin-driver-ecw",
            "Esta instalacion de GDAL no trae el controlador ECW.",
            "Se necesita una compilacion de GDAL con la SDK de Hexagon.",
        ),
        _m(
            "sin-clave-ecw",
            "El controlador ECW esta, pero escribir exige una clave OEM de Hexagon.",
            "Configura AEROCONVERT_ECW_ENCODE_KEY, o usa COG o JP2.",
        ),
        _m(
            "sin-binario-ecw",
            "AEROCONVERT_ECW_BIN apunta a un archivo que no existe.",
            "Corrige la ruta o deja la variable vacia.",
        ),
        _m("sin-conversor", "No hay conversor configurado para este formato."),
        _m(
            "sin-driver-pdal",
            "Esta compilación de PDAL no trae ese controlador.",
            "Los controladores se fijan al compilar. El de QGIS no incluye E57.",
        ),
        _m(
            "formato-propietario",
            "Es un formato cerrado y no hay ningún lector abierto.",
            "Expórtalo desde el programa que lo escribió a un formato de intercambio.",
        ),
        _m(
            "proj-descolocado",
            "GDAL no encuentra su base de datos PROJ.",
            "PROJ_DATA tiene que apuntar a una carpeta con proj.db.",
        ),
        # --- El par no se puede --------------------------------------------
        _m("par-no-soportado", "Ese formato de destino no se puede escribir."),
        _m("extension-no-convertible", "No se convierte esa extensión."),
        _m("formato-no-reconocido", "No se pudo reconocer el formato del archivo."),
        # --- Sistema de referencia -----------------------------------------
        _m(
            "crs-ausente",
            "El archivo no declara sistema de referencia y esta conversión lo necesita.",
            "Declara el EPSG. Adivinarlo es peor que no tenerlo.",
        ),
        _m("crs-invalido", "El código EPSG declarado no existe."),
        # --- Entrada y salida ----------------------------------------------
        _m("origen-no-legible", "No se pudo leer el archivo de origen."),
        _m("origen-bloqueado", "El archivo de origen esta abierto en otro programa."),
        _m("salida-bloqueada", "El archivo de destino esta abierto en otro programa."),
        _m(
            "solo-marcador-en-la-nube",
            "El archivo figura en la carpeta pero su contenido no esta descargado.",
            "Abrelo en el Explorador o marca «Conservar siempre en este dispositivo».",
        ),
        _m("ruta-demasiado-larga", "La ruta pasa del limite practico de Windows."),
        _m("ruta-no-permitida", "La ruta esta fuera de las carpetas permitidas."),
        _m("sin-espacio", "No hay espacio suficiente en el disco de destino."),
        _m("memoria-insuficiente", "El proceso se quedo sin memoria."),
        _m("excede-tope", "El archivo pasa del tope de tamaño de este servidor."),
        # --- Resultado -------------------------------------------------------
        _m("sin-salida", "El motor termino sin escribir ningún archivo."),
        _m("salida-invalida", "El archivo salio, pero no paso la verificacion."),
        _m("error-del-motor", "El motor termino con error."),
        # --- Tiempo y ciclo de vida ------------------------------------------
        _m("sin-avance", "El motor lleva demasiado tiempo sin dar senales."),
        _m("tardo-demasiado", "La conversión agoto su presupuesto de tiempo."),
        _m("cancelado-por-el-usuario", "Se cancelo."),
        _m("interrumpido", "El proceso que lo ejecutaba desaparecio."),
    ]
)

#: Lo unico que mejora repitiendolo. Es una lista explicita, no una regla: que un motivo
#: nuevo NO sea reintentable por omision es la decision correcta.
REINTENTABLES: frozenset[str] = frozenset(
    {"origen-bloqueado", "salida-bloqueada", "sin-avance", "tardo-demasiado", "interrumpido"}
)


def es_reintentable(codigo: str) -> bool:
    return codigo in REINTENTABLES


def mensaje(codigo: str) -> str:
    motivo = MOTIVOS.get(codigo)
    return motivo.mensaje if motivo else codigo
