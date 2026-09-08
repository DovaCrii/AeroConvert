from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = "apps.jobs"
    verbose_name = "Trabajos"

    def ready(self):
        # El despachador solo arranca si los ajustes lo permiten, y nunca en las pruebas.
        # La logica de las guardas vive en `arrancar()`, no aqui.
        from . import despachador

        despachador.arrancar()
