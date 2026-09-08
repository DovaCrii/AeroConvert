from django.urls import path

from . import views

app_name = "engines"

urlpatterns = [
    path("", views.matriz, name="matriz"),
]
