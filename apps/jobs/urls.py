from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<uuid:pk>/", views.ficha, name="ficha"),
    path("<uuid:pk>/progreso/", views.progreso, name="progreso"),
    path("<uuid:pk>/cancelar/", views.cancelar, name="cancelar"),
    path("<uuid:pk>/reencolar/", views.reencolar, name="reencolar"),
    path("<uuid:pk>/descargar/", views.descargar, name="descargar"),
]
