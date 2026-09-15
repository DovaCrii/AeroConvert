"""Cortar una subida que pasa del tope **mientras llega**, no después.

`DATA_UPLOAD_MAX_MEMORY_SIZE` no sirve para esto: limita los datos del formulario que **no**
son archivos. Un cuerpo de veinte gigabytes con un archivo dentro lo acepta tan tranquilo, lo
escribe entero en el temporal del sistema, y solo entonces llega a la vista — que para
entonces ya puede rechazarlo, pero el disco ya se llenó.

Así que se cuenta byte a byte y se para en cuanto se pasa. De los tres sitios donde tiene que
mirarse el tope, este es el que protege la máquina:

- **nginx** (`client_max_body_size`) corta antes de que llegue a Python, pero su mensaje es
  una página de error del servidor que no explica nada.
- **este manejador** corta sin escribir de más, y **deja dicho por qué**.
- **`ArchivoSubido.clean()`** es el inevadible, el que cubre la API y el panel de
  administración.

## Por qué hace falta la marca en el pedido

`StopUpload` aborta el análisis del cuerpo y **descarta todo lo que había**: la vista recibe un
`request.FILES` vacío, exactamente igual que si nadie hubiera elegido archivo. Así que durante
meses alguien que subía 600 MB con el tope en 200 leía **«No llegó ningún archivo»** y un código
`ruta-no-permitida` — dos afirmaciones falsas sobre un archivo que sí eligió y que sí empezó a
subir. Pasó de verdad, en el servidor, el 2026-09-15.

`StopUpload` no lleva mensaje y no hay forma de que lo lleve. Lo que sí se puede es dejar la
razón anotada en el propio pedido antes de levantarla, que es lo que hace `MARCA_DE_CORTE`.
"""

from __future__ import annotations

from django.conf import settings
from django.core.files.uploadhandler import StopUpload, TemporaryFileUploadHandler

#: Dónde queda anotado que la subida se cortó por tamaño. Lo lee la vista.
MARCA_DE_CORTE = "_subida_cortada_por_el_tope"


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
                # **La razon se anota antes de levantar.** `StopUpload` tira el cuerpo entero
                # y la vista ve lo mismo que si nadie hubiera elegido archivo; sin esta marca
                # no hay forma de distinguir «no elegiste nada» de «no cabia».
                #
                # El `if` no sobra: `FileUploadHandler` admite construirse sin pedido, y hay
                # pruebas que lo hacen para medir solo el conteo. Reventar aqui convertiria
                # una mejora del mensaje en un fallo del corte, que es lo que de verdad
                # protege la maquina.
                if self.request is not None:
                    setattr(self.request, MARCA_DE_CORTE, True)
                # `connection_reset=True` corta la conexion en vez de seguir leyendo un
                # cuerpo que ya se rechazo. Sin eso, el cliente termina de subir sus veinte
                # gigabytes para que le digan que no al final.
                raise StopUpload(connection_reset=True)
        return super().receive_data_chunk(raw_data, start)
