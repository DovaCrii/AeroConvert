from django.apps import AppConfig


class PointcloudConfig(AppConfig):
    name = "apps.pointcloud"
    verbose_name = "Motores de nubes de puntos"

    def ready(self):
        from .motores import registrar_todos

        registrar_todos()
