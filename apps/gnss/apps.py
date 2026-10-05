from django.apps import AppConfig


class GnssConfig(AppConfig):
    name = "apps.gnss"
    verbose_name = "Motores de datos GNSS"

    def ready(self):
        from .motores import registrar_todos

        registrar_todos()
