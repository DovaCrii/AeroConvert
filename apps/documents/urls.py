from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("unir/", views.unir, name="unir"),
    # Todas las acciones de la pantalla van al mismo sitio y se distinguen por el boton
    # que se pulso. Es un formulario, no una API: separar «subir» de «girar» en dos URL
    # obligaria a repetir el mismo trabajo de leer la receta en las dos.
    path("componer/", views.componer_vista, name="componer"),
]
