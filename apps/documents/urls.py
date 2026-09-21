from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("unir/", views.unir, name="unir"),
    # Todas las acciones de la pantalla de unir van al mismo sitio y se distinguen por el
    # boton que se pulso. Es un formulario, no una API: separarlas obligaria a repetir en
    # cada vista el mismo trabajo de leer la receta.
    path("unir/componer/", views.componer_vista, name="componer"),
    path("dividir/", views.dividir_vista, name="dividir"),
    path("imagenes/", views.imagenes_vista, name="imagenes"),
    path("a-imagenes/", views.a_imagenes_vista, name="a_imagenes"),
    path("numerar/", views.numerar_vista, name="numerar"),
    path("marca/", views.marca_vista, name="marca"),
    path("proteger/", views.proteger_vista, name="proteger"),
    path("office/", views.office_vista, name="office"),
    path("a-word/", views.a_word_vista, name="a_word"),
    path("comprimir/", views.comprimir, name="comprimir"),
    # Reconocer el texto de un escaneo. Necesita Tesseract, que se sondea: donde no esta, la
    # pantalla existe igual y dice como ponerlo, como las de Office.
    path("ocr/", views.ocr_vista, name="ocr"),
    # «Texto y tablas» tiene su propio índice. Compartía el de PDF, y entonces el desplegable
    # ofrecía dos columnas distintas que llevaban al mismo sitio.
    path("texto/", views.texto, name="texto"),
    # Una pantalla para los seis orígenes: lo que cambia por dentro lo decide la extensión, y
    # seis pantallas idénticas salvo por el título serían seis sitios donde arreglar el mismo
    # fallo. El catálogo sí las lista por separado, con `?de=`.
    path("a-markdown/", views.a_markdown, name="a_markdown"),
    path("de-markdown/", views.de_markdown, name="de_markdown"),
    # Catálogos de tubería de Plant 3D, que son bases de Access. Solo en Windows: en el
    # servidor salen apagadas con su motivo, igual que las de Office.
    path("catalogo-a-excel/", views.catalogo_a_excel, name="catalogo_a_excel"),
    path("excel-a-catalogo/", views.excel_a_catalogo, name="excel_a_catalogo"),
    path("miniatura/", views.miniatura, name="miniatura"),
    # Por identificador y **nunca por ruta**: ver el docstring de la vista.
    path("descargar/<uuid:pk>/", views.descargar, name="descargar"),
]
