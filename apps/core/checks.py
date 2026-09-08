"""Comprobaciones que corre `manage.py check`, y por tanto `verify.ps1`.

Un taller sin raices permitidas tiene que notarse al arrancar, no al primer intento de
conversion -- que es media hora despues, con alguien esperando.
"""

from django.core.checks import Error, register

from . import modo


@register()
def revisar_modo(app_configs, **kwargs):
    return [Error(problema, id="aeroconvert.E001") for problema in modo.revisar_configuracion()]
