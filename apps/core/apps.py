from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Nucleo"

    def ready(self):
        # Registra las comprobaciones de `manage.py check`. El import tiene el efecto
        # secundario a proposito: es como Django espera que se registren.
        from . import checks  # noqa: F401
