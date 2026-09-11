"""Modo nube: el mismo codigo en un servidor propio, con los archivos **subidos**.

> ## Esto todavia no sirve. No lo uses para desplegar.
>
> El modo nube es el de las subidas, y **la subida de archivos no esta escrita**: no hay ni
> un `request.FILES` en el repositorio, `ConversionJob.source_upload` esta huerfano, y el
> runner solo lee `source_path`. Con estos ajustes la aplicacion arranca, sirve paginas y
> autentica, y no convierte **nada**, porque `comprobar_ruta` cierra la unica via de
> entrada que si existe.
>
> `manage.py check` se niega, a proposito.
>
> **Para una VM compartida el modulo correcto es `config.settings.prod` con
> `AEROCONVERT_MODO=taller`**, y las raices apuntando a la carpeta compartida. Eso ya
> funciona hoy: la salida va junto al original -- que es lo que se quiere cuando el equipo
> tiene la carpeta montada --, la retencion es permanente, y la chapa detecta que la maquina
> es compartida y lo dice. Ver `docs/DEPLOY.md`.

Cuando la subida se escriba, la diferencia con `taller` sera la politica de entrada y
salida, no la logica: el archivo se sube y tiene tope, y la salida caduca. El tope tendra
que comprobarse en tres sitios -- nginx, el manejador de subida y `clean()` -- porque solo
el ultimo es inevadible y solo los dos primeros dan un mensaje que se entiende. Hoy no esta
ninguno.
"""

from .base import MODO_NUBE
from .prod import *  # noqa: F403

MODO = MODO_NUBE
CONVERSION_DISPATCHER_ENABLED = True
