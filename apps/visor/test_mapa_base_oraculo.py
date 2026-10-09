"""El mapa base propio contra GDAL de verdad (F19.5, regla 2): otro `gdalwarp`, no nuestra cuenta.

Se corren con `uv run pytest -m oraculo apps/visor/test_mapa_base_oraculo.py` y quedan
deseleccionadas en el gate (el CI no tiene GDAL). **Todo sintético**: un mosaico de tablero más
grande que la ortofoto de prueba, como mapa base.

- **La tesela del fondo.** La que sirve la vista con `ruta=fondo:0` es **idéntica**, píxel a píxel,
  a la de otro `gdalwarp` con la caja de la fórmula escrita aparte; y el original no se toca.
- **Una casilla conocida.** El color que **debe** tener un píxel del mosaico según la fórmula del
  tablero que lo creó, no el que diga GDAL.
- **Capas distintas.** El fondo y la ortofoto no comparten caché ni `ETag`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from django.urls import reverse

from apps.visor import cache, capa, mercator, motor, teselas
from apps.visor.test_oraculo import (
    MEDIO_MUNDO_M,
    _caja_de_tesela_aparte,
    _diferencia,
    _png_a_matriz,
    _tesela_independiente,
)
from apps.visor.testing import (
    ESTE_NO_M,
    NORTE_NO_M,
    PASO_M,
    crear_geotiff_sintetico,
)

pytestmark = [
    pytest.mark.oraculo,
    pytest.mark.django_db,
    pytest.mark.skipif(
        motor.ejecutable("gdalwarp") is None,
        reason="Sin GDAL en esta máquina: se corre donde esté instalado.",
    ),
]


@pytest.fixture
def obra(raiz_de_obra):
    return raiz_de_obra


@pytest.fixture
def ortofoto(obra):
    return crear_geotiff_sintetico(obra / "ortofoto.tif")


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestElMapaBaseContraOtroGdalwarp:
    @pytest.fixture
    def mosaico(self, obra):
        return crear_geotiff_sintetico(
            obra / "mosaico.tif",
            ancho=800,
            alto=400,
            caja=(ESTE_NO_M - 4000.0, NORTE_NO_M + 2000.0, ESTE_NO_M + 4000.0, NORTE_NO_M - 2000.0),
        )

    def test_la_tesela_del_fondo_es_identica_a_la_de_otro_gdalwarp(
        self, con_sesion, mosaico, obra, settings
    ):
        settings.VISOR_MAPA_BASE = f"Mosaico={mosaico}"
        antes = _huella(mosaico)
        carpeta_antes = sorted(p.name for p in obra.iterdir())

        ficha = con_sesion.get(reverse("visor:capa"), {"ruta": "fondo:0"}).json()
        assert ficha["dibujable"]
        z = ficha["zoom_maximo"] - 1
        x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)
        respuesta = con_sesion.get(reverse("visor:tesela", args=[z, x, y]), {"ruta": "fondo:0"})
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "image/png"

        propia = _png_a_matriz(respuesta.content)
        externa = _tesela_independiente(
            mosaico, _caja_de_tesela_aparte(z, x, y), obra / "externa_fondo.png", "PNG"
        )
        assert propia.shape == (256, 256, 4)
        assert propia[..., 3].max() == 255, "la tesela del centro tiene imagen"
        assert _diferencia(propia, externa) == (0, 0.0)
        assert _huella(mosaico) == antes, "el original no se toca (regla 5)"
        assert sorted(p.name for p in obra.iterdir() if p.name != "externa_fondo.png") == [
            n for n in carpeta_antes if n != "externa_fondo.png"
        ], "ni un .aux.xml junto al original"

    def test_el_fondo_y_la_ortofoto_son_capas_distintas_con_su_propia_cache(
        self, con_sesion, mosaico, ortofoto, settings
    ):
        settings.VISOR_MAPA_BASE = f"Mosaico={mosaico}"
        z = 16
        x, y = mercator.tesela_de_lonlat(*capa.leer(ortofoto).centro_4326, z)
        del_fondo = con_sesion.get(reverse("visor:tesela", args=[z, x, y]), {"ruta": "fondo:0"})
        de_la_ortofoto = con_sesion.get(
            reverse("visor:tesela", args=[z, x, y]), {"ruta": str(ortofoto)}
        )
        assert del_fondo.status_code == 200 == de_la_ortofoto.status_code
        assert del_fondo["ETag"] != de_la_ortofoto["ETag"]
        assert _diferencia(
            _png_a_matriz(del_fondo.content), _png_a_matriz(de_la_ortofoto.content)
        ) != (
            0,
            0.0,
        )

    def test_una_celda_conocida_del_mosaico_esta_en_su_sitio(self, mosaico, settings):
        """El mismo tablero: el color que **debe** tener un píxel del mosaico, no el de GDAL."""
        from pyproj import Transformer

        ficha = capa.leer(mosaico)
        paso_m = 10.0  # 8000 m / 800 px
        columna, fila = 410.0, 210.0
        este = (ESTE_NO_M - 4000.0) + columna * paso_m
        norte = (NORTE_NO_M + 2000.0) - fila * paso_m
        mx, my = Transformer.from_crs("EPSG:32719", "EPSG:3857", always_xy=True).transform(
            este, norte
        )
        z = ficha.zoom_maximo
        lado = 2 * MEDIO_MUNDO_M / (2**z)
        x, y = int((mx + MEDIO_MUNDO_M) // lado), int((MEDIO_MUNDO_M - my) // lado)
        tesela = _png_a_matriz(teselas.tesela(mosaico, ficha, cache.clave_de(mosaico), z, x, y))
        px = int((mx - (-MEDIO_MUNDO_M + x * lado)) / (lado / 256))
        py = int((MEDIO_MUNDO_M - y * lado - my) / (lado / 256))
        rojo, verde, azul, alfa = (int(v) for v in tesela[py, px])
        casilla = (int(columna) // 20 + int(fila) // 20) % 2
        assert alfa == 255
        assert rojo == (255 if casilla else 0)
        assert verde == pytest.approx(int(columna) * 255 / 799, abs=6)
        assert azul == pytest.approx(int(fila) * 255 / 399, abs=6)
        assert np.asarray(tesela).shape == (256, 256, 4)
        assert PASO_M == 2.0  # el de la ortofoto; el mosaico usa 10 m (arriba)
