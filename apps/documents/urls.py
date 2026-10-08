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
    path("organizar/", views.organizar, name="organizar"),
    path("organizar/componer/", views.componer_organizar_vista, name="componer_organizar"),
    path("dividir/", views.dividir_vista, name="dividir"),
    path("telemetria/", views.telemetria_vista, name="telemetria"),
    path("reparar/", views.reparar_vista, name="reparar"),
    path("html-a-pdf/", views.html_a_pdf_vista, name="html_a_pdf"),
    path("tamano/", views.tamano_vista, name="tamano"),
    path("comparar/", views.comparar_vista, name="comparar"),
    path("extraer-imagenes/", views.extraer_imagenes_vista, name="extraer_imagenes"),
    path("imagenes/", views.imagenes_vista, name="imagenes"),
    path("imagenes-lote/", views.imagenes_lote_vista, name="imagenes_lote"),
    path("fotos-dron/", views.fotos_dron_vista, name="fotos_dron"),
    path("vuelo-dron/", views.vuelo_dron_vista, name="vuelo_dron"),
    path("vuelo/<uuid:pk>/", views.vuelo_ver, name="vuelo_ver"),
    path("vuelo/<uuid:pk>/datos/", views.vuelo_datos, name="vuelo_datos"),
    path("vuelo/<uuid:pk>/foto/<int:n>/", views.vuelo_miniatura, name="vuelo_miniatura"),
    path("plano-dxf/", views.dxf_lamina_vista, name="dxf_lamina"),
    path("a-imagenes/", views.a_imagenes_vista, name="a_imagenes"),
    path("numerar/", views.numerar_vista, name="numerar"),
    path("marca/", views.marca_vista, name="marca"),
    path("formularios/", views.formularios_vista, name="formularios"),
    path("firma-visible/", views.firma_visible_vista, name="firma_visible"),
    path("firmar/", views.firmar_vista, name="firmar"),
    path("verificar-firmas/", views.verificar_firmas_vista, name="verificar_firmas"),
    path("metadatos/", views.metadatos_vista, name="metadatos"),
    path("proteger/", views.proteger_vista, name="proteger"),
    path("portada/", views.portada_vista, name="portada"),
    path("redactar/", views.redactar_vista, name="redactar"),
    path("office/", views.office_vista, name="office"),
    path("a-word/", views.a_word_vista, name="a_word"),
    path("comprimir/", views.comprimir, name="comprimir"),
    # Reconocer el texto de un escaneo. Necesita Tesseract, que se sondea: donde no esta, la
    # pantalla existe igual y dice como ponerlo, como las de Office.
    path("ocr/", views.ocr_vista, name="ocr"),
    path("pdf-a/", views.pdf_a_vista, name="pdf_a"),
    # «Texto y tablas» tiene su propio índice. Compartía el de PDF, y entonces el desplegable
    # ofrecía dos columnas distintas que llevaban al mismo sitio.
    path("texto/", views.texto, name="texto"),
    path("vuelos/", views.vuelos, name="vuelos"),
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
]
