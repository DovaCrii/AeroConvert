"""Fixtures compartidas por todas las pruebas.

## Por qué existe `con_gdal`

La puerta de calidad **tiene que ser verde en una máquina sin GDAL** (`AGENTS.md`), y el CI es
justo eso. Varias pruebas de pantalla preguntan «¿se puede pasar un tif a jp2?», y la respuesta
depende de que haya un GDAL instalado: pasaban en la estación de trabajo, que tiene QGIS, y
fallaban en CI. `main` estuvo en rojo desde el 24 de septiembre por esto, y nadie lo vio
porque la puerta local daba verde.

Lo que esas pruebas miden es el buscador y el formulario, no si GDAL está instalado — de eso
se ocupa la sonda con sus propias pruebas. Así que se finge, igual que `con_ogr` en
`test_libretas.py` y `con_pdal` en `test_crs_local.py`, y ahora en un solo sitio.

Y para **reproducir CI en la estación**: `AEROCONVERT_GDAL_BIN= AEROCONVERT_PDAL_BIN= pytest`.
"""

from __future__ import annotations

import pytest

#: Los controladores que hacen falta para que las conversiones raster habituales estén vivas.
CONTROLADORES_DE_MENTIRA = frozenset(
    {"GTIFF", "COG", "JP2OPENJPEG", "PNG", "JPEG", "AAIGRID", "HFA", "GPKG"}
)


@pytest.fixture
def con_gdal(monkeypatch):
    """Finge que GDAL y PROJ están en esta máquina, sea cual sea la que corra las pruebas."""
    from django.core.cache import cache

    from apps.engines import sondas

    # La sonda se guarda diez minutos: sin vaciarla, leería lo que dejó otra prueba.
    cache.clear()
    estado = sondas.EstadoGdal(
        disponible=True,
        version="GDAL 3.12.4 (de mentira)",
        ejecutable="gdalinfo",
        controladores=CONTROLADORES_DE_MENTIRA,
        escribibles=CONTROLADORES_DE_MENTIRA,
    )
    monkeypatch.setattr(sondas, "sondar_gdal", lambda: estado)
    monkeypatch.setattr(sondas, "sondar_proj", lambda: sondas.Disponibilidad.si("PROJ 9.8"))
    yield
    cache.clear()
