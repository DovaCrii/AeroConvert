from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core import forms as core_forms
from apps.core import views as core_views

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path("trabajos/", include("apps.jobs.urls")),
    path("motores/", include("apps.engines.urls")),
    path("preajustes/", include("apps.presets.urls")),
    path("documentos/", include("apps.documents.urls")),
    path("tino/", include("apps.tino.urls")),
    path("api/v1/", include("apps.engines.api_urls")),
    path("salud/", core_views.salud, name="salud"),
    path(
        "entrar/",
        auth_views.LoginView.as_view(
            template_name="core/entrar.html",
            authentication_form=core_forms.FormularioDeEntrada,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
