"""Cortar una subida que pasa del tope **mientras llega**, no después.

`DATA_UPLOAD_MAX_MEMORY_SIZE` no sirve para esto: limita los datos del formulario que **no**
son archivos. Un cuerpo de veinte gigabytes con un archivo dentro lo acepta tan tranquilo, lo
escribe entero en el temporal del sistema, y solo entonces llega a la vista — que para
entonces ya puede rechazarlo, pero el disco ya se llenó.

Así que se cuenta byte a byte y se para en cuanto se pasa. De los tres sitios donde tiene que
mirarse el tope, este es el que protege la máquina:

- **nginx** (`client_max_body_size`) corta antes de que llegue a Python, pero su mensaje es
  una página de error del servidor que no explica nada.
- **este manejador** da un mensaje que se entiende y no escribe de más.
- **`ArchivoSubido.clean()`** es el inevadible, el que cubre la API y el panel de
  administración.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.uploadhandler import StopUpload, TemporaryFileUploadHandler


class SubidaConTope(TemporaryFileUploadHandler):
    """Como el de siempre, pero contando.

    Hereda del **temporal** y no del de memoria: un PDF de doscientos megabytes no tiene por
    qué pasar por la memoria del proceso, y `TemporaryFileUploadHandler` además deja un
    archivo con `.temporary_file_path()`, que es lo que necesita cualquier herramienta que
    lea del disco.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recibidos = 0

    @property
    def tope_bytes(self) -> int:
        return int(getattr(settings, "TOPE_MB", 0)) * 1_048_576

    def receive_data_chunk(self, raw_data, start):
        tope = self.tope_bytes
        if tope:
            self._recibidos += len(raw_data)
            if self._recibidos > tope:
                # `connection_reset=True` corta la conexion en vez de seguir leyendo un
                # cuerpo que ya se rechazo. Sin eso, el cliente termina de subir sus veinte
                # gigabytes para que le digan que no al final.
                raise StopUpload(connection_reset=True)
        return super().receive_data_chunk(raw_data, start)
