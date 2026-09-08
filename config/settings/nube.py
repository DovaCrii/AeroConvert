"""Modo nube: el mismo codigo en un servidor propio, para conversiones livianas y para
compartir resultados.

La diferencia con `taller` es la politica de entrada y salida, no la logica: aca el archivo
se sube y tiene tope, y la salida caduca. El tope se comprueba en **tres** sitios --nginx,
el manejador de subida y `clean()`-- porque solo el ultimo es inevadible y solo los dos
primeros dan un mensaje que se entiende.
"""

from .base import MODO_NUBE
from .prod import *  # noqa: F403

MODO = MODO_NUBE
CONVERSION_DISPATCHER_ENABLED = True
