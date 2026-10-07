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
        _m(
            "crs-en-grados",
            "El destino necesita metros y el origen está en grados. Hay que reproyectar.",
        ),
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
        # --- GNSS ------------------------------------------------------------
        #
        # El convertidor de Trimble sale con código 0 y dice «Success» con un archivo cortado,
        # con basura y hasta vacío. Lo que decide si sirvió es lo que hay en los archivos.
        _m(
            "sin-conversor-trimble",
            "No hay convertidor de Trimble en esta máquina.",
            "Es «Convert To RINEX», de licencia propia. Lo trae Trimble Business Center.",
        ),
        _m(
            "sin-rtklib",
            "No hay RTKLIB (convbin) en esta máquina.",
            "Es de código abierto. En Ubuntu: sudo apt install rtklib, "
            "o AEROCONVERT_RTKLIB_CONVBIN.",
        ),
        _m(
            "sin-wine",
            "El convertidor de Trimble es de Windows y aquí no hay Wine para correrlo.",
            "sudo apt install wine, y un prefijo propio en AEROCONVERT_WINEPREFIX.",
        ),
        _m(
            "crudo-incompleto",
            "El archivo del receptor está cortado: termina a mitad de un bloque.",
            "Cópialo otra vez desde el receptor. Convertirlo así daría un RINEX más corto "
            "sin avisar de nada.",
        ),
        _m(
            "rinex-invalido",
            "El convertidor escribió algo que no es un RINEX que se pueda leer.",
        ),
        _m(
            "rinex-sin-epocas",
            "El RINEX salió sin una sola época de observación.",
            "Suele ser un archivo que no es de un receptor, o uno vacío por dentro.",
        ),
        # --- Documentos ------------------------------------------------------
        #
        # Las herramientas de PDF pasan por la cola desde la fase 9 y traen sus propios
        # motivos. Los tres de «sin-» son **la herramienta de fuera que falta**, con el mismo
        # trato que el resto de la casa: se dice cuál y no se esconde el botón.
        _m("documento-invalido", "El documento no se pudo abrir o no es lo que dice ser."),
        _m("contrasena-incorrecta", "La contraseña no abre el documento."),
        _m(
            "falta-la-contrasena",
            "La contraseña ya no está: por seguridad no se guarda, y hay que volver a escribirla.",
        ),
        _m(
            "demasiadas-paginas",
            "El documento pasa del tope de páginas de esta herramienta.",
            "Pártelo antes con «Dividir PDF».",
        ),
        _m("sin-office", "Esta máquina no tiene Office, que es lo que hace esta conversión."),
        _m("sin-access", "Esta máquina no tiene el motor de Access que abre los catálogos."),
        _m(
            "sin-tesseract",
            "Esta máquina no tiene Tesseract, que es lo que reconoce el texto.",
            "sudo apt install tesseract-ocr tesseract-ocr-spa",
        ),
    ]
)


#: **Terminó bien, pero sin archivo, o con algo que decir.** No son fallos y no van en
#: `MOTIVOS`: el trabajo queda `HECHO`, y esto dice por qué no hay descarga o qué hay que
#: leer antes de usarla.
#:
#: Existen porque la cola suponía que «hecho» es «hay un archivo», y tres herramientas de
#: documentos contestan con otra cosa legítima. Comprimir un PDF que ya venía comprimido lo
#: engordaría, y entregar eso sería la peor respuesta; un escaneo no tiene texto que sacar;
#: y un catálogo puede escribirse con filas que no cuadraban.
DESENLACES: dict[str, Motivo] = dict(
    [
        _m(
            "no-valio-la-pena",
            "Ya estaba comprimido: comprimirlo otra vez lo habría hecho más grande, así que "
            "no se ha tocado.",
        ),
        _m(
            "sin-texto-que-sacar",
            "El PDF no tiene texto: es un escaneo, una imagen de un texto.",
            "Pásele antes por «Reconocer texto (OCR)».",
        ),
        _m(
            "sin-imagenes",
            "El PDF no lleva ninguna imagen incrustada que valga la pena sacar.",
            "Si lo que quiere es cada página como imagen, use «PDF a imágenes».",
        ),
        _m(
            "sin-diferencias",
            "Los dos PDF se ven iguales: no hay ninguna página que difiera.",
            "Si esperaba cambios, compruebe que son las dos versiones que quería comparar.",
        ),
        _m("con-avisos", "Hecho, con avisos que conviene leer antes de usarlo."),
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
