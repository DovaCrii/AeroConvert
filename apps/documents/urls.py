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
    path("miniatura/", views.miniatura, name="miniatura"),
]
