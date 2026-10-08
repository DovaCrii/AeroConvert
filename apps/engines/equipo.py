"""Cómo dejar listo el equipo: el paso exacto para cada cosa que sale apagada (F17.3).

La pantalla de compatibilidad dice **qué** falta y por qué. Esto dice **qué hacer**, por cada código
de motivo de «falta algo en esta máquina», en el servidor (Linux, `p340`) y en la estación
(Windows), y **quién** lo hace: un guion, la persona (cuando pide licencia, registro o una clave), o
nadie (cuando no hay arreglo y solo sirve la alternativa).

Es un catálogo cerrado, como `apps/jobs/motivos.py`: una prueba exige que **cada código de «sin-…»
del catálogo de motivos tenga aquí su paso**, para que un motivo nuevo no salga apagado sin decir
cómo encenderlo.
"""

from __future__ import annotations

from dataclasses import dataclass

GUION = "guion"
PERSONA = "persona"
NADIE = "nadie"

INSTALAR_FALTANTES = "sudo despliegue/instalar_faltantes.sh"


@dataclass(frozen=True)
class Paso:
    quien: str  # GUION, PERSONA o NADIE
    servidor: str  # en p340 (Linux)
    estacion: str  # en la estación (Windows)
    comprobar: str = "Abra esta pantalla otra vez: la sonda vuelve a mirar."


PASOS: dict[str, Paso] = {
    "motor-no-disponible": Paso(
        PERSONA,
        "sudo apt install gdal-bin. PDAL no está en los repositorios de Ubuntu 26.04: conda-forge "
        "y AEROCONVERT_PDAL_BIN en el .env.",
        "Instale QGIS (trae GDAL y PDAL) y ponga AEROCONVERT_GDAL_BIN y AEROCONVERT_PDAL_BIN en "
        "el .env, apuntando a su carpeta bin.",
    ),
    "proj-descolocado": Paso(
        PERSONA,
        "Que PROJ_DATA apunte a la carpeta con proj.db del mismo GDAL (no de otra instalación).",
        "Use el GDAL y el PROJ de la misma instalación de QGIS; no mezcle con otro proj.db.",
    ),
    "sin-driver-ecw": Paso(
        PERSONA,
        "Hace falta un GDAL compilado con la SDK de ECW de Hexagon; el de Ubuntu no la trae.",
        "winget install GISInternals.GDAL.ECW (la compilación de QGIS no trae ECW).",
        "gdalinfo --formats debe listar ECW.",
    ),
    "sin-driver-mrsid": Paso(
        PERSONA,
        "Hace falta un GDAL compilado con la SDK de LizardTech; ni el de Ubuntu ni el de QGIS la "
        "traen. Solo si de verdad usan MrSID.",
        "Lo mismo: un GDAL con la SDK de LizardTech.",
        "Mientras tanto, el archivo se abre en el programa que lo lee y se guarda en COG o JP2.",
    ),
    "sin-clave-ecw": Paso(
        PERSONA,
        "AEROCONVERT_ECW_ENCODE_KEY y AEROCONVERT_ECW_ENCODE_COMPANY en el .env (la clave OEM "
        "de Hexagon; nunca en el repositorio).",
        "Las mismas dos variables en el .env de la estación.",
        "Mientras tanto sirven COG y JPEG 2000.",
    ),
    "sin-binario-ecw": Paso(
        PERSONA,
        "Corrija AEROCONVERT_ECW_BIN en el .env o déjela vacía.",
        "Corrija AEROCONVERT_ECW_BIN en el .env o déjela vacía.",
    ),
    "sin-conversor": Paso(
        PERSONA,
        "Descargue ODA File Converter (gratuito, pide registro en la Open Design Alliance), "
        "instálelo y ponga AEROCONVERT_ODA_CONVERTER en el .env. Necesita xvfb: "
        f"{INSTALAR_FALTANTES}.",
        "Instale ODA File Converter y ponga AEROCONVERT_ODA_CONVERTER en el .env.",
    ),
    "sin-driver-pdal": Paso(
        PERSONA,
        "Los controladores de PDAL se fijan al compilar: una compilación de conda-forge trae E57.",
        "La compilación de QGIS no trae E57: use la de conda-forge para ese formato.",
    ),
    "formato-propietario": Paso(
        NADIE,
        "No hay lector abierto. Ábralo en el programa que lo escribió y expórtelo a un formato de "
        "intercambio (E57 o LAS para ReCap).",
        "Lo mismo: ReCap Pro exporta a E57 o LAS.",
        "No se enciende: la pantalla ya dice la alternativa.",
    ),
    "sin-conversor-trimble": Paso(
        PERSONA,
        "Convert To RINEX es de Trimble (licencia propia). Extraiga el MSI con msiextract y ponga "
        "AEROCONVERT_TRIMBLE_RINEX en el .env; corre bajo Wine (F10.5).",
        "Lo trae Trimble Business Center: ponga AEROCONVERT_TRIMBLE_RINEX apuntando a "
        "convertToRinex.exe.",
    ),
    "sin-rtklib": Paso(
        GUION,
        f"{INSTALAR_FALTANTES} (instala rtklib; convbin y rnx2rtkp quedan en el PATH).",
        "Descargue RTKLIB (BSD-2) y ponga AEROCONVERT_RTKLIB_CONVBIN y "
        "AEROCONVERT_RTKLIB_RNX2RTKP en el .env.",
    ),
    "sin-wine": Paso(
        PERSONA,
        "sudo apt install wine, y un prefijo propio en AEROCONVERT_WINEPREFIX (F10.5).",
        "No hace falta: en Windows el convertidor corre directo.",
    ),
    "sin-office": Paso(
        PERSONA,
        "Office no existe en Linux. Con LibreOffice (F17.1, rotulado «puede variar»): "
        f"{INSTALAR_FALTANTES}.",
        "Microsoft Office instalado en la estación que ejecuta.",
    ),
    "sin-access": Paso(
        PERSONA,
        "El motor de Access no existe en Linux. Para leer: mdbtools (F17.2), con "
        f"{INSTALAR_FALTANTES}. Escribir .accdb sigue pidiendo Windows.",
        "Instale el Microsoft Access Database Engine de la misma arquitectura que Python.",
    ),
    "sin-plantillas": Paso(
        PERSONA,
        "Copie las dos plantillas Word de la empresa a una carpeta del servidor y ponga su ruta "
        "en AEROCONVERT_PLANTILLAS_JEJ.",
        "Lo mismo, con una carpeta de la estación.",
    ),
    "sin-ffmpeg": Paso(
        GUION,
        f"{INSTALAR_FALTANTES} (instala ffmpeg, que trae ffprobe).",
        "Descargue FFmpeg (los binarios de gyan.dev) y ponga AEROCONVERT_FFMPEG en el .env; "
        "ffprobe tiene que estar en la misma carpeta.",
    ),
    "sin-tesseract": Paso(
        GUION,
        f"{INSTALAR_FALTANTES} (instala tesseract-ocr con español e inglés).",
        "Instale Tesseract (UB Mannheim) con el idioma español; queda en el PATH.",
    ),
}

#: Las herramientas de documentos dicen qué les falta con una marca, no con un código.
_EXIGE_A_CODIGO = {
    "exige_office": "sin-office",
    "exige_access": "sin-access",
    "exige_plantillas": "sin-plantillas",
    "exige_tesseract": "sin-tesseract",
    "exige_ffmpeg": "sin-ffmpeg",
}


def codigo_de_herramienta(herramienta: dict) -> str:
    """El código de motivo de una herramienta de documentos apagada."""
    for marca, codigo in _EXIGE_A_CODIGO.items():
        if herramienta.get(marca):
            return codigo
    return ""


def apagados_ahora() -> list[dict]:
    """Lo que en esta máquina sale apagado **ahora**, agrupado por código y con su paso.

    Es la sonda en vivo: los motores del registro y las herramientas de documentos, preguntados
    al pintar la página.
    """
    from apps.documents.views import estado_de_herramientas

    from . import registry

    grupos: dict[str, dict] = {}

    def anotar(codigo: str, nombre: str, mensaje: str) -> None:
        grupo = grupos.setdefault(
            codigo or "sin-codigo",
            {"codigo": codigo, "mensaje": mensaje, "afectados": [], "paso": PASOS.get(codigo)},
        )
        if nombre not in grupo["afectados"]:
            grupo["afectados"].append(nombre)

    for motor in registry.todos():
        estado = motor.disponibilidad()
        if not estado.disponible:
            anotar(estado.codigo_motivo, motor.nombre, estado.mensaje)
    for herramienta in estado_de_herramientas():
        if not herramienta["disponible"]:
            anotar(
                codigo_de_herramienta(herramienta),
                herramienta.get("nombre", herramienta.get("id", "")),
                herramienta.get("motivo", ""),
            )
    return sorted(grupos.values(), key=lambda g: (-len(g["afectados"]), g["codigo"]))
