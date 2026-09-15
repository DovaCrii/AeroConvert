"""Todo lo que sabe hacer esta aplicación, en una sola lista y buscable.

## Por qué hacía falta

Las capacidades estaban repartidas en tres pantallas que no se hablan: «Convertir» para lo
geoespacial, «PDF» para los once de documentos, y «Compatibilidad» para la matriz de 189
celdas. Quien llega con un archivo en la mano y una intención —«necesito juntar estos planos
y numerarlos»— tiene que saber de antemano en cuál de las tres mirar.

Esto le da la vuelta: **una lista de lo que se puede hacer, agrupada por el tipo de trabajo,
y con un buscador**. No sustituye a las tres pantallas; es la puerta que lleva a ellas.

## Lo que NO es

No es la matriz de capacidades. La matriz contesta «¿puedo llevar este formato exacto a este
otro?» y tiene que enseñar las 189 celdas, apagadas incluidas. Esto contesta «¿qué quiero
hacer?», que es una pregunta con veinte respuestas, no con ciento ochenta y nueve.

De ahí que lo geoespacial entre aquí **por perfil de destino** —«llevarlo a Civil 3D»— y no
por par de formatos: el perfil es la forma en que alguien piensa el problema, y la elección
del formato concreto ya la hace la aplicación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.urls import reverse


@dataclass(frozen=True)
class Accion:
    """Una cosa que se puede hacer, dicha como la diría quien la necesita."""

    id: str
    nombre: str
    que_hace: str
    #: Qué entrega. Es la pregunta de antes de pulsar, y casi ninguna interfaz la contesta.
    sale: str
    categoria: str
    #: El nombre de la URL, para `reverse()`. Vacío si hoy no lleva a ninguna parte.
    url: str
    icono: str
    #: La familia de color. Ver `--av-fam-*` en `app.css`.
    familia: str
    disponible: bool = True
    motivo: str = ""
    #: Palabras por las que alguien la buscaría y que **no** están en el nombre. Es lo que
    #: hace que «excel» encuentre «Hoja de cálculo a Markdown», o «achurar» encuentre la
    #: marca de agua. Sin esto, un buscador solo sirve a quien ya sabe cómo se llama.
    palabras: tuple[str, ...] = field(default_factory=tuple)
    #: Lo que hay que llevarse en la cadena de consulta para que el enlace no pierda la
    #: elección. Ver `enlace`.
    consulta: dict[str, str] = field(default_factory=dict)

    @property
    def texto_de_busqueda(self) -> str:
        return " ".join((self.nombre, self.que_hace, self.sale, *self.palabras)).lower()

    @property
    def enlace(self) -> str:
        """A dónde lleva la tarjeta, **con la elección dentro**.

        Se resuelve aquí y no con `{% url %}` en la plantilla porque seis de estas acciones
        van al mismo sitio y lo único que las distingue es la consulta. Con `{% url %}` la
        plantilla tendría que saber cuáles llevan parámetros y cuáles no; aquí lo sabe cada
        acción, que es quien lo sabe de verdad.
        """
        if not self.url:
            return ""
        destino = reverse(self.url)
        return f"{destino}?{urlencode(self.consulta)}" if self.consulta else destino


#: Las categorías, en el orden en que se piensan: primero el trabajo de terreno, luego el de
#: gabinete, y al final lo que sale hacia fuera.
CATEGORIAS = (
    (
        "planos",
        "Planos, mapas y nubes de puntos",
        "Lo que viene del vuelo o del levantamiento, y hay que dejar en un formato que abra.",
    ),
    (
        "documentos",
        "Documentos y PDF",
        "Lo que acaba dentro de un informe o de una entrega.",
    ),
    (
        "texto",
        "Texto y tablas",
        "Cuando el contenido tiene que salir del archivo y entrar en otro sitio.",
    ),
)


#: El nombre corto de cada formato de salida, para la línea de «Sale:».
#:
#: No sale de `catalogo.FORMATOS[x].nombre` a propósito: allí viven los nombres completos
#: —«Cloud Optimized GeoTIFF», «LAZ compressed point cloud»— que son los correctos en la
#: matriz de compatibilidad y demasiado largos para una tarjeta. Esto es presentación, y
#: vive en la capa de presentación.
SIGLAS = {
    "cog": "COG",
    "geotiff": "GeoTIFF",
    "gpkg": "GeoPackage",
    "copc": "COPC",
    "laz": "LAZ",
    "shp": "Shapefile",
    "geojson": "GeoJSON",
    "kmz": "KMZ",
    "landxml": "LandXML",
    "dxf": "DXF",
}

#: Un símbolo por perfil, y **distinguible**, no solo distinto.
#:
#: Los seis llevaban la misma diana y el mismo azul. Seis tarjetas idénticas salvo por su
#: título obligan a leer los seis títulos para encontrar uno: el icono dejaba de informar y
#: solo ocupaba sitio.
ICONOS_DE_PERFIL = {
    "civil3d": "icon-destino-plano",
    "qgis": "icon-destino-capas",
    "arcgis": "icon-destino-globo",
    "google-earth": "icon-destino-chincheta",
    "web": "icon-destino-ventana",
    "aerobim": "icon-destino-cubo",
}


def _salidas_de(perfil) -> str:
    """Los formatos a los que lleva un perfil, sin repetir y en orden de probabilidad.

    Antes las seis tarjetas decían «el formato que ese programa abre», las seis, ocupando dos
    líneas cada una. Una línea que no distingue una tarjeta de otra no está informando.

    El dato ya estaba: `formato_destino` más `destinos_por_familia`. Lo que faltaba era
    decirlo.
    """
    codigos = [perfil.formato_destino, *perfil.destinos_por_familia.values()]
    vistos: list[str] = []
    for codigo in codigos:
        if codigo and codigo not in vistos:
            vistos.append(codigo)
    return " · ".join(SIGLAS.get(c, c.upper()) for c in vistos)


def _de_los_perfiles() -> list[Accion]:
    """Lo geoespacial, **por dónde tiene que abrir** y no por formato.

    Es como está planteada la pantalla de convertir desde el principio: se elige el programa
    de destino y los ajustes se ponen solos. Aquí se repite esa forma de preguntar, porque es
    la que coincide con la de quien tiene el archivo.

    **Y la elección viaja en el enlace.** Las seis iban a `dashboard:convertir` a secas, así
    que pulsar «Llevarlo a QGIS» tiraba justo lo único que la tarjeta había preguntado y
    dejaba a quien la pulsó en la pantalla genérica, eligiendo otra vez.
    """
    from apps.targets import perfiles as perfiles_mod

    return [
        Accion(
            id=f"perfil-{perfil.id}",
            nombre=f"Llevarlo a {perfil.nombre}",
            que_hace=perfil.descripcion,
            sale=_salidas_de(perfil),
            categoria="planos",
            url="dashboard:convertir",
            consulta={"destino": perfil.id},
            icono=ICONOS_DE_PERFIL.get(perfil.id, "icon-destino"),
            familia="destino",
            palabras=("ortofoto", "nube de puntos", "raster", "vectorial", perfil.id),
        )
        for perfil in perfiles_mod.PERFILES.values()
    ]


def _de_los_documentos() -> list[Accion]:
    """Las once de PDF, con su disponibilidad de verdad."""
    from apps.documents.views import estado_de_herramientas

    #: Por qué alguien las buscaría sin usar su nombre.
    SINONIMOS = {
        "unir": ("juntar", "combinar", "fusionar", "merge", "un solo archivo"),
        "dividir": ("separar", "partir", "extraer", "split", "sacar paginas"),
        "imagenes": ("fotos", "escaneo", "jpg", "png", "monografia"),
        "a_imagenes": ("exportar", "lamina", "captura", "jpg", "png"),
        "numerar": ("foliar", "paginacion", "numeros de pagina"),
        "marca": ("borrador", "confidencial", "sello", "estampar", "watermark"),
        "proteger": ("contrasena", "clave", "cifrar", "desbloquear", "aes"),
        "office": ("word", "excel", "powerpoint", "docx", "xlsx", "pptx"),
        "a_word": ("editar", "docx", "reflow"),
    }

    return [
        Accion(
            id=f"pdf-{h['id']}",
            nombre=h["nombre"],
            que_hace=h["que_hace"],
            sale=h["sale"],
            categoria="documentos",
            url=h["url"] if h["disponible"] else "",
            icono=h["icono"],
            familia=h["familia"],
            disponible=h["disponible"],
            motivo=h.get("motivo", ""),
            palabras=SINONIMOS.get(h["id"], ()),
        )
        for h in estado_de_herramientas()
    ]


def todas() -> list[Accion]:
    return [*_de_los_perfiles(), *_de_los_documentos()]


def por_categoria(busqueda: str = "") -> list[dict]:
    """Las acciones agrupadas, filtradas por lo que se haya escrito.

    **Todas las palabras tienen que aparecer, en cualquier orden y en cualquier campo.** Es
    lo que hace que «juntar pdf» encuentre «Unir PDF» aunque ninguna de las dos palabras esté
    en su nombre — «juntar» está en los sinónimos y «pdf» en la descripción.

    Una categoría sin resultados no se pinta: un encabezado sobre un hueco hace pensar que
    algo se rompió.
    """
    terminos = [t for t in busqueda.lower().split() if t]
    encontradas = [a for a in todas() if all(t in a.texto_de_busqueda for t in terminos)]

    grupos = []
    for clave, titulo, cuando in CATEGORIAS:
        dentro = [a for a in encontradas if a.categoria == clave]
        if dentro:
            grupos.append({"clave": clave, "titulo": titulo, "cuando": cuando, "acciones": dentro})
    return grupos
