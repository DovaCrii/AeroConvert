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


@dataclass(frozen=True)
class Accion:
    """Una cosa que se puede hacer, dicha como la diría quien la necesita."""

    id: str
    nombre: str
    que_hace: str
    #: Qué entrega. Es la pregunta de antes de pulsar, y casi ninguna interfaz la contesta.
    sale: str
    categoria: str
    #: El nombre de la URL, para `{% url %}`. Vacío si hoy no lleva a ninguna parte.
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

    @property
    def texto_de_busqueda(self) -> str:
        return " ".join((self.nombre, self.que_hace, self.sale, *self.palabras)).lower()


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


def _de_los_perfiles() -> list[Accion]:
    """Lo geoespacial, **por dónde tiene que abrir** y no por formato.

    Es como está planteada la pantalla de convertir desde el principio: se elige el programa
    de destino y los ajustes se ponen solos. Aquí se repite esa forma de preguntar, porque es
    la que coincide con la de quien tiene el archivo.
    """
    from apps.targets import perfiles as perfiles_mod

    return [
        Accion(
            id=f"perfil-{perfil.id}",
            nombre=f"Llevarlo a {perfil.nombre}",
            que_hace=perfil.descripcion,
            sale="el formato que ese programa abre",
            categoria="planos",
            url="dashboard:convertir",
            icono="icon-destino",
            familia="transformar",
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
