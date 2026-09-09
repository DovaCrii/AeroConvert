"""El entorno del proceso hijo: dónde están los binarios y **dónde están sus datos**.

Vive aparte porque lo necesitan los dos motores que llaman a GDAL -- el ráster y el
vectorial -- y porque la parte que importa no es evidente.

## GDAL no se basta con su carpeta `bin`

Además de los ejecutables, GDAL lleva una carpeta de datos con archivos que algunos
controladores **necesitan para funcionar**, no para ir más rápido. Sin ella:

- El controlador DXF no escribe nada. Busca la plantilla `header.dxf` y, al no encontrarla,
  responde `DXF driver failed to create ...` y termina con código 1. Se descubrió
  convirtiendo la libreta de control del cruce minero a DXF.
- Cada invocación escupe `Cannot find tms_NZTM2000.json (GDAL_DATA is not defined)` por
  stderr. Es inofensivo, pero ese stderr se guarda en la bitácora del trabajo, y un aviso
  inocuo repetido mil veces esconde el que sí importa.

## Y la ruta **no se puede deducir de una regla**

Lo natural es `<bin>/../share/gdal`, y en esta máquina no es así. En QGIS 4.0.2 conviven dos
diseños distintos a la vez:

    C:\\Program Files\\QGIS 4.0.2\\bin                        los ejecutables
    C:\\Program Files\\QGIS 4.0.2\\apps\\gdal\\share\\gdal       los datos de GDAL
    C:\\Program Files\\QGIS 4.0.2\\share\\proj                 los datos de PROJ

Así que se buscan varios sitios y **se comprueba con un archivo testigo**, no con la
existencia de la carpeta: una carpeta `share/gdal` vacía existe y no sirve de nada. Si no se
encuentra, no se pone la variable — dejarla apuntando a un sitio equivocado es peor que no
ponerla, porque GDAL deja de buscar por su cuenta.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings

#: Un archivo que solo está en la carpeta de datos de GDAL. Es además **el que hacía falta**:
#: sin él el controlador DXF no arranca.
TESTIGO_GDAL = "header.dxf"

#: El que de verdad usa PROJ. `sondar_proj()` comprueba lo mismo por su lado.
TESTIGO_PROJ = "proj.db"

#: Sitios donde mirar, **relativos a la carpeta de binarios**, en orden.
#:
#: Ojo con el `..`: casi todos empiezan por ahí porque los datos son hermanos de `bin`, no
#: hijos. Anclarlos por error dentro de `bin` es justo lo que hizo que DXF siguiera fallando
#: después de escribir este módulo.
CANDIDATOS_GDAL = (
    ("..", "share", "gdal"),
    ("..", "apps", "gdal", "share", "gdal"),
    ("..", "..", "share", "gdal"),
    ("share", "gdal"),
)

CANDIDATOS_PROJ = (
    ("..", "share", "proj"),
    ("..", "apps", "proj", "share", "proj"),
    ("..", "proj", "share", "proj"),
    ("..", "..", "share", "proj"),
    ("share", "proj"),
)


def carpeta_de_binarios() -> Path | None:
    """La que dice la configuración, o `None` si no hay ninguna configurada."""
    crudo = (getattr(settings, "GDAL_BIN", "") or "").strip().strip('"')
    return Path(crudo) if crudo else None


def _buscar(base: Path, candidatos: tuple[tuple[str, ...], ...], testigo: str) -> Path | None:
    for partes in candidatos:
        candidata = base.joinpath(*partes)
        try:
            if (candidata / testigo).is_file():
                return candidata.resolve()
        except OSError:  # pragma: no cover - ruta imposible o permiso denegado
            continue
    return None


def entorno_de_gdal(**extra: str) -> dict[str, str]:
    """Las variables que se le pasan al hijo. **Nunca se tocan las del servidor.**

    `extra` es para lo que cada motor añade por su cuenta: `GDAL_CACHEMAX` en ráster, la
    clave de ECW cuando la hay. Se aplica al final, así que un motor puede sobrescribir
    cualquiera de las de aquí.
    """
    entorno: dict[str, str] = {}
    base = carpeta_de_binarios()

    if base is not None:
        entorno["PATH"] = str(base) + os.pathsep + os.environ.get("PATH", "")

        datos = _buscar(base, CANDIDATOS_GDAL, TESTIGO_GDAL)
        if datos is not None:
            entorno["GDAL_DATA"] = str(datos)

        proyecciones = _buscar(base, CANDIDATOS_PROJ, TESTIGO_PROJ)
        if proyecciones is not None:
            # Las dos: `PROJ_DATA` es la de PROJ 9 y `PROJ_LIB` la que aún leen versiones
            # anteriores. Poner solo una deja fuera a la mitad de las instalaciones.
            entorno["PROJ_DATA"] = str(proyecciones)
            entorno["PROJ_LIB"] = str(proyecciones)

    entorno.update(extra)
    return entorno
