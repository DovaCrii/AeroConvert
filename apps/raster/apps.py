from django.apps import AppConfig


class RasterConfig(AppConfig):
    name = "apps.raster"
    verbose_name = "Motores raster"

    def ready(self):
        from .motores import registrar_todos

        registrar_todos()
