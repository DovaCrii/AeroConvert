from django.apps import AppConfig


class VectorConfig(AppConfig):
    name = "apps.vector"
    verbose_name = "Motores vectoriales y CAD"

    def ready(self):
        from .motores import registrar_todos

        registrar_todos()
