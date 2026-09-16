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

import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.urls import reverse


def sin_tildes(texto: str) -> str:
    """En minúsculas y sin acentos ni eñes, para comparar.

    **No es un detalle de idioma: es un fallo que se veía.** «quitar contraseña» —escrito como
    lo escribe cualquiera, con eñe— no encontraba nada, porque los sinónimos están escritos sin
    acentos y la comparación era literal. Cero resultados se lee como «no se puede», que era
    falso.

    Se normaliza a NFD y se tiran las marcas diacríticas: así «contraseña» y «contrasena»,
    «numeración» y «numeracion», son la misma cosa a efectos de buscar.
    """
    plano = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn")


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
        return sin_tildes(" ".join((self.nombre, self.que_hace, self.sale, *self.palabras)))

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
#:
#: El cuarto campo es **la pantalla de la sección**, para que el encabezado del desplegable
#: sea un enlace y no un rótulo muerto. Vacío cuando la sección no tiene pantalla propia.
CATEGORIAS = (
    (
        "planos",
        "Planos, mapas y nubes de puntos",
        "Lo que viene del vuelo o del levantamiento, y hay que dejar en un formato que abra.",
        "dashboard:convertir",
    ),
    (
        "documentos",
        "Documentos y PDF",
        "Lo que acaba dentro de un informe o de una entrega.",
        "documents:inicio",
    ),
    (
        "texto",
        "Texto y tablas",
        "Cuando el contenido tiene que salir del archivo y entrar en otro sitio.",
        "documents:texto",
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
        "numerar": ("foliar", "paginacion", "numeracion", "numeros de pagina"),
        "marca": ("borrador", "confidencial", "sello", "estampar", "watermark"),
        "proteger": ("contrasena", "clave", "cifrar", "desbloquear", "aes"),
        "office": ("word", "excel", "powerpoint", "docx", "xlsx", "pptx"),
        "a_word": ("editar", "docx", "reflow"),
        # Texto y tablas. «md» y «markdown» en todas, porque quien busca escribe una u otra.
        "md_excel": ("md", "markdown", "xlsx", "hoja de calculo", "tabla", "pegar en un correo"),
        "md_csv": ("md", "markdown", "tabla", "separado por comas", "punto y coma"),
        "md_word": ("md", "markdown", "docx", "texto plano"),
        "md_pdf": ("md", "markdown", "sacar el texto", "copiar el texto"),
        "md_epub": ("md", "markdown", "libro", "ebook", "capitulos"),
        "md_html": ("md", "markdown", "pagina web", "htm", "limpiar"),
        "md_a_pdf": ("md", "markdown", "imprimir", "entregar", "maquetar"),
    }

    return [
        Accion(
            id=f"pdf-{h['id']}",
            nombre=h["nombre"],
            que_hace=h["que_hace"],
            sale=h["sale"],
            # `documentos` salvo que la herramienta diga otra cosa. Las de Markdown viven en
            # el mismo sitio que las de PDF —comparten pantalla, origen y descarga— pero no
            # contestan la misma pregunta: una entrega un PDF y la otra saca lo de dentro.
            categoria=h.get("categoria", "documentos"),
            url=h["url"] if h["disponible"] else "",
            consulta=h.get("consulta", {}),
            icono=h["icono"],
            familia=h["familia"],
            disponible=h["disponible"],
            motivo=h.get("motivo", ""),
            palabras=SINONIMOS.get(h["id"], ()),
        )
        for h in estado_de_herramientas()
    ]


#: Búsquedas de ejemplo para la portada, y **cada una demuestra un truco distinto**.
#:
#: No son decoración: un buscador con truco que nadie descubre es un buscador que no sirve.
#: Los tres que tiene este —la palabra de quien busca, el par de formatos, y el contenido del
#: archivo— no se adivinan escribiendo en una caja vacía.
#:
#: Las cubre `test_los_ejemplos_de_la_portada_devuelven_algo`: un ejemplo que no encuentra nada
#: es peor que ninguno, porque enseña que el buscador no funciona.
EJEMPLOS = (
    ("juntar planos", "Encuentra «Unir PDF» sin que ninguna de las dos palabras esté en su nombre"),
    ("tif a jp2", "Escribe los dos formatos y contesta si se puede"),
    ("quitar contraseña", "Encuentra la herramienta por lo que hace, no por cómo se llama"),
    ("excel", "Todo lo que sale de una hoja de cálculo o entra en ella"),
)


def todas() -> list[Accion]:
    return [*_de_los_perfiles(), *_de_los_documentos()]


# --- Buscar por par de formatos --------------------------------------------
#
# El catálogo está ordenado por intención —«Llevarlo a QGIS»— y eso cubre a quien llega con un
# archivo y una necesidad. Pero **no cubre a quien ya sabe exactamente lo que quiere**: escribir
# «tif a jp2» no encontraba nada, aunque la aplicación sepa hacerlo desde la primera fase.
#
# La respuesta no es meter las 189 combinaciones en el catálogo: eso es la matriz, y existe.
# Es que el **buscador** entienda la pregunta y lleve al sitio, que es lo que Nielsen Norman
# llama convertir la búsqueda en navegación — cuando lo escrito señala a una sola cosa, se va
# a esa cosa en vez de devolver una lista.

#: Cómo nombra la gente a un formato cuando no usa su código. La clave es el código.
APODOS = {
    "geotiff": ("tif", "tiff", "geotif", "raster"),
    "bigtiff": ("tif grande", "tiff grande"),
    "cog": ("tif en la nube", "cloud optimized"),
    "jp2": ("jpeg2000", "jpeg 2000", "j2k", "jp2000"),
    "jpeg": ("jpg", "foto"),
    "png": ("imagen sin perdida",),
    "ecw": ("hexagon", "erdas"),
    "mrsid": ("sid", "lizardtech"),
    "img": ("erdas imagine",),
    "asc": ("ascii grid", "grid"),
    "shp": ("shapefile", "shape"),
    "gpkg": ("geopackage", "paquete"),
    "geojson": ("json geografico",),
    "kml": ("google earth",),
    "kmz": ("google earth comprimido",),
    "dxf": ("autocad", "cad", "dibujo"),
    "landxml": ("puntos cogo", "topografia"),
    "las": ("nube de puntos",),
    "laz": ("nube comprimida",),
    "copc": ("nube en la nube", "cloud optimized point cloud"),
    "puntos": ("libreta", "libreta de puntos", "csv de puntos"),
}


#: Por qué vía se reconoció un formato. **Solo desempata entre textos igual de largos.**
#:
#: `.tif` es extensión de `geotiff`, de `cog` y de `bigtiff` a la vez, así que «tif» a secas
#: tiene tres dueños posibles y hay que elegir: quien escribe «un tif» quiere decir el clásico,
#: que es el apodo declarado arriba. Sin esto salía `cog`, que es lo que devolvía el orden del
#: diccionario — o sea, el azar.
_POR_CODIGO, _POR_APODO, _POR_NOMBRE, _POR_EXTENSION_ = 0, 1, 2, 3


def _indice_de_formatos() -> list[tuple[str, str]]:
    """Pares `(texto buscable, código)`, en el orden en que hay que probarlos.

    **Primero por longitud y solo después por vía**, y ese orden no es intercambiable: «jpeg
    2000» tiene que ganar a «jpeg» aunque «jpeg» sea un código exacto y «jpeg 2000» solo un
    apodo. Al revés, «jpeg» se comería las cuatro primeras letras y dejaría un «2000» suelto
    que no es nada.
    """
    from apps.formats import catalogo

    entradas: list[tuple[str, str, int]] = []
    for codigo, formato in catalogo.FORMATOS.items():
        entradas.append((sin_tildes(codigo), codigo, _POR_CODIGO))
        entradas.append((sin_tildes(str(formato.nombre)), codigo, _POR_NOMBRE))
        for extension in formato.extensiones:
            entradas.append((sin_tildes(extension.lstrip(".")), codigo, _POR_EXTENSION_))
        for apodo in APODOS.get(codigo, ()):
            entradas.append((sin_tildes(apodo), codigo, _POR_APODO))

    ordenadas = sorted(set(entradas), key=lambda e: (-len(e[0]), e[2]))
    return [(texto, codigo) for texto, codigo, _ in ordenadas]


def formatos_nombrados(busqueda: str) -> list[str]:
    """Los códigos de formato que se reconocen en lo escrito, en el orden en que aparecen.

    **Se busca por palabras completas**, no por trozos: sin eso «asc» aparecería dentro de
    cualquier frase que lo lleve pegado a otra letra, y «las» —que es un formato de nube de
    puntos— saldría en «las páginas», o sea en media aplicación.

    Lo que se marca como gastado es **la palabra, no sus espacios**. Con los espacios dentro,
    dos formatos pegados compartían el de en medio: en «geotiff jpeg2000», el primero se
    quedaba con el espacio y el segundo dejaba de encontrarse. La búsqueda devolvía uno solo y
    por tanto ninguna respuesta.
    """
    texto = " " + sin_tildes(busqueda).replace("→", " ").replace("-", " ") + " "
    hallados: list[tuple[int, str]] = []
    gastado = [False] * len(texto)

    for aguja, codigo in _indice_de_formatos():
        desde = 0
        while (pos := texto.find(f" {aguja} ", desde)) != -1:
            inicio, fin = pos + 1, pos + 1 + len(aguja)
            if not any(gastado[inicio:fin]):
                for i in range(inicio, fin):
                    gastado[i] = True
                hallados.append((inicio, codigo))
            desde = pos + 1

    vistos: list[str] = []
    for _, codigo in sorted(hallados):
        if codigo not in vistos:
            vistos.append(codigo)
    return vistos


@dataclass(frozen=True)
class Conversion:
    """La respuesta directa a «¿puedo pasar de esto a esto otro?»."""

    origen: str
    destino: str
    nombre_origen: str
    nombre_destino: str
    se_puede: bool
    motivo: str = ""
    sugerencia: str = ""


def conversion_pedida(busqueda: str) -> Conversion | None:
    """`None` si lo escrito no nombra dos formatos.

    Dos y no uno: con uno solo no hay pregunta que contestar —«jp2» a secas puede ser origen o
    destino— y adivinar cuál de los dos es sería contestar otra cosa.
    """
    from apps.engines import registry
    from apps.engines.base import ParDeFormatos
    from apps.formats import catalogo

    codigos = formatos_nombrados(busqueda)
    if len(codigos) < 2:
        return None

    origen, destino = codigos[0], codigos[1]
    celda = registry.celda(ParDeFormatos(origen, destino))
    return Conversion(
        origen=origen,
        destino=destino,
        nombre_origen=str(catalogo.FORMATOS[origen].nombre),
        nombre_destino=str(catalogo.FORMATOS[destino].nombre),
        se_puede=celda.se_puede,
        motivo=celda.mensaje,
        sugerencia=celda.sugerencia,
    )


def por_categoria(busqueda: str = "") -> list[dict]:
    """Las acciones agrupadas, filtradas por lo que se haya escrito.

    **Todas las palabras tienen que aparecer, en cualquier orden y en cualquier campo.** Es
    lo que hace que «juntar pdf» encuentre «Unir PDF» aunque ninguna de las dos palabras esté
    en su nombre — «juntar» está en los sinónimos y «pdf» en la descripción.

    Una categoría sin resultados no se pinta: un encabezado sobre un hueco hace pensar que
    algo se rompió.
    """
    terminos = [t for t in sin_tildes(busqueda).split() if t]
    catalogo = todas()
    encontradas = [a for a in catalogo if all(t in a.texto_de_busqueda for t in terminos)]

    # **Si exigir todas no deja nada, se devuelve lo que más se acerca.**
    #
    # «juntar planos» daba cero: «juntar» está en «Unir PDF» y «planos» en la descripción de
    # otra herramienta, así que ninguna las tenía las dos. Y cero resultados se lee como «no se
    # puede» —que era falso— en la búsqueda más natural del mundo.
    #
    # Se puntúa cada acción por **cuántos términos acierta** y se devuelven las del máximo. No
    # es «cualquiera de las palabras», que soltaría media aplicación: si algo acierta dos, las
    # que aciertan una no salen. Y si el máximo es cero, no sale nada — «xilofono» sigue sin
    # devolver resultados, que es la respuesta correcta.
    if terminos and not encontradas:
        aciertos = {a.id: sum(t in a.texto_de_busqueda for t in terminos) for a in catalogo}
        techo = max(aciertos.values(), default=0)
        if techo:
            encontradas = [a for a in catalogo if aciertos[a.id] == techo]

    grupos = []
    for clave, titulo, cuando, seccion in CATEGORIAS:
        dentro = [a for a in encontradas if a.categoria == clave]
        if dentro:
            grupos.append(
                {
                    "clave": clave,
                    "titulo": titulo,
                    "cuando": cuando,
                    "seccion": reverse(seccion) if seccion else "",
                    "acciones": dentro,
                }
            )
    return grupos
