from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Nucleo"

    def ready(self):
        # Los dos imports tienen efecto secundario **a proposito**: es como Django espera
        # que se registren tanto las comprobaciones de `manage.py check` como los receptores
        # de senales.
        from . import checks, senales  # noqa: F401
