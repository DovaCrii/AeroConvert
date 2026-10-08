"""Una sola forma de agrupar las herramientas (F13.1).

## Por qué existe

Había **dos clasificaciones que no coincidían**. La portada y el lateral agrupaban con
`acciones.CATEGORIAS` (planos · gnss · documentos · texto) y el índice de `/documentos/` con
`views.GRUPOS` (componer · transformar · marcar · proteger · texto), así que la misma herramienta
vivía en dos grupos distintos según la pantalla; los catálogos de Plant 3D estaban en «Sacar texto»;
y GNSS era un grupo de una sola herramienta con casi su mismo nombre. Con las más de 60 herramientas
que traen las fases 14 y 15, cada una habría reinventado el menú.

Aquí vive **el único árbol**: nueve grupos, cada uno con un **identificador estable**, y la
asignación de cada herramienta a uno. La portada, el lateral y los índices de `/documentos/` lo
leen de aquí, y `test_taxonomia.py` impide que una herramienta nueva quede sin grupo.

## El identificador es estable; el título no

`data-recuerda` guarda en el navegador qué grupos dejó abiertos cada persona. Si la clave saliera
del título, **renombrar un grupo borraría lo que cada quien había dejado abierto**. Por eso se
guarda con el `id`, que no cambia aunque el título sí.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Grupo:
    id: str
    titulo: str
    #: Una frase de «para qué sirve»: lo que la persona tiene entre manos cuando lo busca.
    cuando: str
    #: La pantalla a la que lleva el encabezado del grupo, por nombre de URL. Vacío si no tiene.
    seccion: str
    #: Un grupo de una sola herramienta es una anomalía que `test_taxonomia.py` señala, salvo que
    #: se declare aquí: GNSS lo es porque hoy hay un solo tipo de dato de receptor que convertir.
    admite_uno: bool = False
    #: El símbolo del grupo (`static/img/icons.svg`): el que se ve con el lateral reducido.
    icono: str = "icon-todas"


#: Los nueve grupos, **en el orden en que se piensan**: primero lo que se entrega a otro programa,
#: luego los datos de campo (GNSS y vuelos de dron), luego el trabajo sobre documentos y, al
#: final, lo que sale del archivo.
GRUPOS: tuple[Grupo, ...] = (
    Grupo(
        "entregar",
        "Entregar a un programa",
        "Cuando el archivo tiene que abrir en un programa concreto.",
        "dashboard:convertir",
        icono="icon-destino",
    ),
    Grupo(
        "gnss",
        "Coordenadas y datos GNSS",
        "Lo que graba el receptor en campo, para posprocesarlo.",
        "dashboard:convertir",
        admite_uno=True,
        icono="icon-destino-satelite",
    ),
    Grupo(
        "vuelos",
        "Vuelos de dron",
        "Lo que graba un vuelo: la traza, las fotos y su posición corregida.",
        "documents:vuelos",
        icono="icon-dron",
    ),
    Grupo(
        "organizar",
        "Organizar PDF",
        "Cuando sobran, faltan o están desordenadas las hojas.",
        "documents:inicio",
        icono="icon-pdf-organizar",
    ),
    Grupo(
        "convertir",
        "Convertir documentos",
        "Cuando el documento hace falta en otro formato.",
        "documents:inicio",
        icono="icon-pdf-office",
    ),
    Grupo(
        "optimizar",
        "Optimizar y reconocer",
        "Cuando el PDF pesa mucho o no se puede buscar.",
        "documents:inicio",
        icono="icon-pdf-comprimir",
    ),
    Grupo(
        "revisar",
        "Revisar, firmar y proteger",
        "Cuando el documento va a salir de la oficina.",
        "documents:inicio",
        icono="icon-pdf-proteger",
    ),
    Grupo(
        "texto",
        "Texto, tablas y Markdown",
        "Cuando el contenido tiene que salir del archivo.",
        "documents:texto",
        icono="icon-texto-tabla",
    ),
    Grupo(
        "planta",
        "Imagen, video y planta",
        "Catálogos de planta y, más adelante, imágenes y video.",
        "documents:texto",
        icono="icon-catalogo",
    ),
)

POR_ID: dict[str, Grupo] = {g.id: g for g in GRUPOS}

#: A qué grupo pertenece cada herramienta de documentos, por su `id` en `herramientas.py`.
DE_DOCUMENTOS: dict[str, str] = {
    "unir": "organizar",
    "organizar": "organizar",
    "dividir": "organizar",
    "tamano": "organizar",
    "comparar": "revisar",
    "imagenes": "convertir",
    "imagenes_lote": "convertir",
    "dxf_lamina": "convertir",
    "a_imagenes": "convertir",
    "extraer_imagenes": "convertir",
    "office": "convertir",
    "a_word": "convertir",
    "comprimir": "optimizar",
    "ocr": "optimizar",
    "reparar": "optimizar",
    "html_a_pdf": "texto",
    "numerar": "revisar",
    "marca": "revisar",
    "proteger": "revisar",
    "redactar": "revisar",
    "formularios": "revisar",
    "firma_visible": "revisar",
    "firmar": "revisar",
    "verificar_firmas": "revisar",
    "metadatos": "revisar",
    "md_excel": "texto",
    "md_csv": "texto",
    "md_word": "texto",
    "md_pdf": "texto",
    "md_epub": "texto",
    "md_html": "texto",
    "md_a_pdf": "texto",
    "telemetria": "vuelos",
    "fotos_dron": "vuelos",
    "vuelo_dron": "vuelos",
    "video": "vuelos",
    "portada": "texto",
    "catalogo_excel": "planta",
    "excel_catalogo": "planta",
}

#: Los índices de `/documentos/`: cada uno enseña **un trozo del mismo árbol**, en el mismo orden.
INDICES: dict[str, tuple[str, ...]] = {
    "documentos": ("organizar", "convertir", "optimizar", "revisar"),
    "texto": ("texto", "planta"),
    "vuelos": ("vuelos",),
}


def grupo_de_documento(herramienta_id: str) -> str:
    """El grupo de una herramienta de documentos. Una que no esté asignada **levanta**: es mejor
    que la prueba falle a que la herramienta aparezca en un grupo por defecto que nadie eligió."""
    try:
        return DE_DOCUMENTOS[herramienta_id]
    except KeyError as fallo:
        raise KeyError(
            f"La herramienta «{herramienta_id}» no tiene grupo: añádala a `DE_DOCUMENTOS` en "
            "`apps/dashboard/taxonomia.py`."
        ) from fallo


def grupo_de_perfil(perfil) -> str:
    """El grupo de un perfil de destino: GNSS para los de posproceso, entregar para los demás."""
    from apps.formats import catalogo as catalogo_mod

    return "gnss" if catalogo_mod.GNSS in perfil.familias else "entregar"
