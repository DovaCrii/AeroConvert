"""Las veinte herramientas de documentos, como datos y nada más.

Vive aparte de `views.py` desde la fase 9 porque ahora la necesitan sitios que no son
pantallas: el modelo de trabajo, para decir «Numerar páginas» en el historial en vez de un
código; el proceso hijo que las ejecuta en la cola; y `recientes.py`, para enlazar de vuelta
a su pantalla. Ninguno de esos puede importar las vistas sin arrastrar Django entero, y el
hijo ni siquiera arranca Django.

Por eso aquí **no hay nada que haga nada**: ni sondas, ni plantillas, ni rutas resueltas.
Lo que depende de esta máquina —si hay Office, si hay Tesseract— lo añade
`views.estado_de_herramientas()`.
"""

from __future__ import annotations

#: Las herramientas, para el indice y para el titulo de cada pantalla. Una lista y no seis
#: entradas en la barra: la barra es de secciones, y esto es una seccion con varias cosas
#: dentro. Ademas asi entra la siguiente sin rediscutir donde ponerla.
#:
#: El `icono` es el identificador dentro de `static/img/icons.svg`. Va aqui y no en la
#: plantilla porque la plantilla recorre la lista: con un `if` por herramienta, anadir la
#: decima obligaria a tocar dos sitios y el segundo se olvida.
HERRAMIENTAS = (
    {
        "id": "unir",
        "url": "documents:unir",
        "icono": "icon-pdf-unir",
        "sale": "un PDF",
        "familia": "componer",
        "nombre": "Unir PDF",
        "que_hace": (
            "Junta varios en uno. Eliges qué páginas entran, en qué orden, y giras las "
            "láminas que lo necesiten."
        ),
    },
    {
        "id": "dividir",
        "icono": "icon-pdf-dividir",
        "sale": "uno o varios PDF",
        "familia": "componer",
        "url": "documents:dividir",
        "nombre": "Dividir PDF",
        "que_hace": "Saca una parte, o parte uno grande en hojas sueltas.",
    },
    {
        "id": "imagenes",
        "icono": "icon-pdf-a-pdf",
        "sale": "un PDF",
        "familia": "transformar",
        "url": "documents:imagenes",
        "nombre": "Imágenes a PDF",
        "que_hace": "Fotos o escaneos en un solo documento, en A4 o al tamaño del original.",
    },
    {
        "id": "a_imagenes",
        "icono": "icon-pdf-a-imagen",
        "sale": "JPG o PNG",
        "familia": "transformar",
        "url": "documents:a_imagenes",
        "nombre": "PDF a imágenes",
        "que_hace": "Una lámina como JPG o PNG, para meterla en un informe o en una diapositiva.",
    },
    {
        "id": "comprimir",
        "icono": "icon-pdf-comprimir",
        "sale": "el mismo PDF, más ligero",
        "familia": "transformar",
        "url": "documents:comprimir",
        "nombre": "Comprimir PDF",
        "que_hace": "Para que un juego de planos entre en un correo. Dice cuánto baja antes.",
    },
    {
        "id": "ocr",
        "icono": "icon-pdf-ocr",
        "sale": "el mismo PDF, con el texto dentro",
        "familia": "transformar",
        "url": "documents:ocr",
        "nombre": "Reconocer el texto de un escaneo",
        "que_hace": "Un PDF escaneado pasa a poder buscarse y copiarse. Se ve igual.",
        # La tercera que depende de algo de fuera, y con el mismo trato que Office y Access:
        # cuando Tesseract no esta, la tarjeta **sigue saliendo**, apagada y con el motivo.
        "exige_tesseract": True,
        # Lo que se lee en la ficha al terminar. Estaba en el recibo de la pantalla y se vino
        # con la herramienta a la cola: sin él, «listo» invita a fiarse de una búsqueda.
        "tras_hacerlo": (
            "Repasa el texto antes de fiarte de una búsqueda: lo que no se reconoció bien no "
            "aparece."
        ),
    },
    {
        "id": "numerar",
        "icono": "icon-pdf-numerar",
        "sale": "el mismo PDF, numerado",
        "familia": "marcar",
        "url": "documents:numerar",
        "nombre": "Numerar páginas",
        "que_hace": ("Pone «3 / 56» en cada hoja. Sin numerar la portada, si no quieres."),
    },
    {
        "id": "marca",
        "icono": "icon-pdf-marca",
        "sale": "el mismo PDF, con la marca",
        "familia": "marcar",
        "url": "documents:marca",
        "nombre": "Marca de agua",
        "que_hace": "Estampa «BORRADOR» o «CONFIDENCIAL» cruzando cada página.",
    },
    {
        "id": "proteger",
        "icono": "icon-pdf-proteger",
        "sale": "el mismo PDF, con contraseña",
        "familia": "proteger",
        "url": "documents:proteger",
        "nombre": "Proteger PDF",
        "que_hace": "Le pone contraseña, con AES-256. O se la quita, si la sabes.",
    },
    {
        "id": "office",
        "icono": "icon-pdf-office",
        "sale": "un PDF",
        "familia": "transformar",
        "url": "documents:office",
        "nombre": "Word, Excel o PowerPoint a PDF",
        "que_hace": "Con el Office de tu equipo, así que sale idéntico al original.",
        # La unica que depende de algo de fuera. Cuando no esta, la tarjeta **sigue
        # saliendo**, apagada y con el motivo: ocultarla haria parecer que nunca existio.
        "exige_office": True,
    },
    {
        "id": "a_word",
        "icono": "icon-pdf-a-word",
        "sale": "un DOCX",
        "familia": "transformar",
        "url": "documents:a_word",
        "nombre": "PDF a Word",
        "que_hace": "El camino de vuelta, para poder editarlo. Con lo que eso significa.",
        "exige_office": True,
        "tras_hacerlo": "Repásalo antes de mandarlo: Word rehace la maqueta a su manera.",
    },
    # --- Texto y tablas ---------------------------------------------------
    #
    # **Seis entradas y una sola pantalla.** La pantalla mira la extensión y hace lo que toca;
    # las seis entradas existen porque quien busca escribe «excel a markdown» o «epub», no
    # «a markdown». Es el mismo patrón que los seis destinos geoespaciales, que también van a
    # una sola pantalla con la elección en la consulta.
    {
        "id": "md_excel",
        "categoria": "texto",
        "icono": "icon-texto-tabla",
        "sale": "un .md con una tabla por hoja",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "xlsx"},
        "nombre": "Excel a Markdown",
        "que_hace": "Cada hoja, una tabla que se pega en un correo o en una ficha.",
    },
    {
        "id": "md_csv",
        "categoria": "texto",
        "icono": "icon-texto-tabla",
        "sale": "un .md con la tabla",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "csv"},
        "nombre": "CSV a Markdown",
        "que_hace": "Detecta si separa por punto y coma o por coma, que aquí cambia.",
    },
    {
        "id": "md_word",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "docx"},
        "nombre": "Word a Markdown",
        "que_hace": "Títulos, listas, tablas y negritas. Lo que no sobrevive se avisa.",
    },
    {
        "id": "md_pdf",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "pdf"},
        "nombre": "PDF a Markdown",
        "que_hace": "El texto que el PDF ya tiene. Si es un escaneo, se dice.",
    },
    {
        "id": "md_epub",
        "categoria": "texto",
        "icono": "icon-texto-libro",
        "sale": "un .md con los capítulos en orden",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "epub"},
        "nombre": "EPUB a Markdown",
        "que_hace": "En el orden en que se lee, no en el que vienen dentro del archivo.",
    },
    {
        "id": "md_html",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "html"},
        "nombre": "Página web a Markdown",
        "que_hace": "Una página guardada, sin el armazón ni los menús.",
    },
    {
        "id": "md_a_pdf",
        "categoria": "texto",
        "icono": "icon-texto-imprimir",
        "sale": "un PDF",
        "familia": "texto",
        "url": "documents:de_markdown",
        "nombre": "Markdown a PDF",
        "que_hace": "El camino de vuelta, para entregar lo que se redactó en Markdown.",
    },
    # --- Catálogos de tubería ---------------------------------------------
    #
    # Son bases de Access de AutoCAD Plant 3D. Van en este grupo porque es lo mismo que hacen
    # las de arriba: sacar el contenido de un archivo para poder trabajarlo en otro sitio.
    {
        "id": "catalogo_excel",
        "categoria": "texto",
        "icono": "icon-catalogo",
        "sale": "un Excel con una hoja por tabla",
        "familia": "texto",
        "url": "documents:catalogo_a_excel",
        "nombre": "Catálogo de tubería a Excel",
        "que_hace": "Saca las nueve tablas del catálogo para poder editarlas cómodo.",
        "exige_access": True,
        "tras_hacerlo": (
            "Una hoja por tabla, con la fila de encabezados fija. Cuando lo tengas editado, "
            "vuelve con «Excel a catálogo de tubería»."
        ),
    },
    {
        "id": "excel_catalogo",
        "categoria": "texto",
        "icono": "icon-catalogo-volver",
        "sale": "un catálogo listo para Plant 3D",
        "familia": "texto",
        "url": "documents:excel_a_catalogo",
        "nombre": "Excel a catálogo de tubería",
        "que_hace": "El camino de vuelta. Se parte del catálogo original, que pone el esquema.",
        "exige_access": True,
    },
)

#: Por identificador, para quien tiene el código y necesita el resto.
POR_ID = {h["id"]: h for h in HERRAMIENTAS}


def nombre_de(identificador: str) -> str:
    """«Numerar páginas» para `numerar`. El propio identificador si ya no existe."""
    herramienta = POR_ID.get(identificador)
    return herramienta["nombre"] if herramienta else identificador
