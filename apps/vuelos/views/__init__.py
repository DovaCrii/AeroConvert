"""Las pantallas de los vuelos de dron: la traza de un video, las fotos y el proceso PPK.

Salieron de `apps/documents/views/` (F18.13). Siguen usando de `apps.documents` solo lo que
comparten con el resto de la aplicación: la cola, la entrada de archivos y `ComposicionInvalida`.
"""

from __future__ import annotations

from .pantalla_fotos_dron import (  # noqa: F401
    fotos_dron_vista,
)
from .pantalla_indice import (  # noqa: F401
    vuelos,
)
from .pantalla_telemetria import (  # noqa: F401
    telemetria_vista,
)
from .pantalla_video import (  # noqa: F401
    video_vista,
)
from .pantalla_vuelo import (  # noqa: F401
    vuelo_datos,
    vuelo_dron_vista,
    vuelo_miniatura,
    vuelo_ver,
)
