from django.apps import AppConfig


class MeshConfig(AppConfig):
    name = "apps.mesh"
    verbose_name = "Motores BIM y malla"

    def ready(self):
        from .motores import registrar_todos

        registrar_todos()
