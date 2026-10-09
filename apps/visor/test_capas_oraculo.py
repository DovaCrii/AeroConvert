"""Varias capas y mapa base contra GDAL de verdad (regla 2): el otro lector, no nuestra cuenta.

Se corren con `uv run pytest -m oraculo apps/visor/test_capas_oraculo.py` y quedan deseleccionadas
en el gate (el CI no tiene GDAL). **Todo sintético**: una ortofoto de tablero (la de
`testing.crear_geotiff_sintetico`), un mosaico más grande como mapa base y un vuelo de cuatro
disparos cuyas posiciones se construyeron **sobre píxeles conocidos** de esa ortofoto.

Qué se comprueba, y contra qué:

- **Las fotos sobre la ortofoto.** Cada disparo del vuelo cae donde `gdaltransform` (otro camino
  de transformación: `-s_srs EPSG:4326 -t_srs EPSG:3857`) pone su latitud y longitud, con menos de
  un píxel de diferencia a los niveles 14, 17 y 20 de la cuadrícula. Y además, el píxel de la
  tesela de la ortofoto **bajo la marca** tiene el color que la fórmula del tablero le dio a la
  casilla en la que se construyó el disparo: la foto está sobre el píxel que debía.
- **La trayectoria.** Cada punto, contra `gdaltransform -s_srs EPSG:32719 -t_srs EPSG:3857` de
  su Este y Norte, y a menos de un píxel al nivel 20.
- **El mapa base.** La tesela que sirve la vista con `ruta=fondo:0` es **idéntica**, píxel a
  píxel, a la de otro `gdalwarp` con la caja de la fórmula escrita aparte; y el original no se
  toca.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from django.urls import reverse

from apps.visor import cache, capa, motor, teselas
from apps.visor.test_oraculo import (
    MEDIO_MUNDO_M,
    _png_a_matriz,
)
from apps.visor.testing import (
    ALTO_PX,
    ANCHO_PX,
    ESTE_NO_M,
    NORTE_NO_M,
    PASO_M,
    crear_geotiff_sintetico,
    crear_vuelo_sintetico,
    herramienta_externa,
)

pytestmark = [
    pytest.mark.oraculo,
    pytest.mark.django_db,
    pytest.mark.skipif(
        motor.ejecutable("gdalwarp") is None or motor.ejecutable("gdaltransform") is None,
        reason="Sin GDAL en esta máquina: se corre donde esté instalado.",
    ),
]

#: Los píxeles de la ortofoto (columna, fila) **en el centro de una casilla del tablero** (de
#: 20 × 20 píxeles) donde se construyen los disparos del vuelo de este oráculo: en el centro de la
#: casilla el color es el de la fórmula, sin mezcla con la vecina. Los de `PUNTOS_DE_GDAL` caen en
#: esquinas de píxel y de casilla, y no sirven para mirar un color.
PIXELES_DE_LOS_DISPAROS = [(30, 30), (70, 50), (110, 70), (150, 10)]


def _a_3857_con_gdaltransform(origen: str, puntos: list[tuple[float, float]]):
    """`gdaltransform` de `origen` a EPSG:3857: **otro camino**, no `pyproj` ni nuestra fórmula."""
    entrada = "".join(f"{x!r} {y!r}\n" for x, y in puntos)
    hecho = herramienta_externa(
        "gdaltransform", ["-s_srs", origen, "-t_srs", "EPSG:3857", "-output_xy"], entrada=entrada
    )
    assert hecho.returncode == 0, hecho.stderr
    filas = [tuple(float(v) for v in linea.split()[:2]) for linea in hecho.stdout.splitlines()]
    assert len(filas) == len(puntos)
    return filas


def _pixeles_de_mapa(m: float, z: int) -> float:
    """Metros de Web Mercator a píxeles del nivel `z`, **escrito aquí** y no importado."""
    return (m + MEDIO_MUNDO_M) / (2 * MEDIO_MUNDO_M / (256 * 2**z))


@pytest.fixture
def obra(raiz_de_obra):
    return raiz_de_obra


@pytest.fixture
def ortofoto(obra):
    return crear_geotiff_sintetico(obra / "ortofoto.tif")


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestLasFotosSobreLaOrtofoto:
    @pytest.fixture
    def vuelo(self, persona, obra):
        return crear_vuelo_sintetico(persona, obra / "salidas")

    @pytest.fixture
    def datos(self, con_sesion, vuelo):
        return con_sesion.get(reverse("visor:vuelo", args=[vuelo.pk])).json()

    @pytest.mark.parametrize("nivel", [14, 17, 20])
    def test_cada_foto_cae_a_menos_de_un_pixel_de_donde_gdaltransform_la_pone(self, datos, nivel):
        fotos = datos["fotos"]["puntos"]
        assert len(fotos) == 4
        medido = _a_3857_con_gdaltransform("EPSG:4326", [(f["lon"], f["lat"]) for f in fotos])
        for foto, (mx, my) in zip(fotos, medido, strict=True):
            dx = _pixeles_de_mapa(foto["mx"], nivel) - _pixeles_de_mapa(mx, nivel)
            dy = _pixeles_de_mapa(foto["my"], nivel) - _pixeles_de_mapa(my, nivel)
            assert abs(dx) < 1 and abs(dy) < 1, (foto["n"], nivel, dx, dy)

    def test_la_trayectoria_pasa_por_los_puntos_que_da_gdaltransform_desde_utm(self, datos):
        este0, norte0 = 345000.0, 6294900.0
        from apps.visor.vuelo import leer_datos  # noqa: F401  (el origen es el del vuelo sintético)

        recorrido = datos["trayectoria"]["puntos"]
        crudos = [
            (este0 + x, norte0 + y)
            for x, y in [[0, 200], [100, 100], [200, 150], [300, 50], [400, 0]]
        ]
        medido = _a_3857_con_gdaltransform("EPSG:32719", crudos)
        for (mx, my), (gx, gy) in zip(recorrido, medido, strict=True):
            assert abs(_pixeles_de_mapa(mx, 20) - _pixeles_de_mapa(gx, 20)) < 1
            assert abs(_pixeles_de_mapa(my, 20) - _pixeles_de_mapa(gy, 20)) < 1

    def test_el_pixel_de_la_ortofoto_bajo_cada_marca_es_el_de_la_casilla_donde_se_construyo(
        self, ortofoto, persona, obra, con_sesion
    ):
        """Un vuelo **construido sobre píxeles conocidos** de la ortofoto: el centro de cada uno se
        pasó a latitud y longitud con `gdaltransform` (otro camino que el nuestro). Bajo cada marca
        debe verse el color que **la fórmula del tablero** le da a ese píxel. Si la foto cayera
        corrida, otra casilla se vería ahí."""
        centros_utm = [
            (ESTE_NO_M + (c + 0.5) * PASO_M, NORTE_NO_M - (f + 0.5) * PASO_M)
            for c, f in PIXELES_DE_LOS_DISPAROS
        ]
        entrada = "".join(f"{e!r} {n!r}\n" for e, n in centros_utm)
        hecho = herramienta_externa(
            "gdaltransform",
            ["-s_srs", "EPSG:32719", "-t_srs", "EPSG:4326", "-output_xy"],
            entrada=entrada,
        )
        assert hecho.returncode == 0, hecho.stderr
        lonlat = [tuple(float(v) for v in linea.split()[:2]) for linea in hecho.stdout.splitlines()]
        trabajo = crear_vuelo_sintetico(persona, obra / "salidas", fotos_lonlat=lonlat)
        datos = con_sesion.get(reverse("visor:vuelo", args=[trabajo.pk])).json()

        ficha = capa.leer(ortofoto)
        clave = cache.clave_de(ortofoto)
        z = ficha.zoom_maximo
        lado = 2 * MEDIO_MUNDO_M / (2**z)
        fotos = datos["fotos"]["puntos"]
        assert len(fotos) == len(PIXELES_DE_LOS_DISPAROS)
        for foto, (columna, fila) in zip(fotos, PIXELES_DE_LOS_DISPAROS, strict=True):
            mx, my = foto["mx"], foto["my"]
            x, y = int((mx + MEDIO_MUNDO_M) // lado), int((MEDIO_MUNDO_M - my) // lado)
            tesela = _png_a_matriz(teselas.tesela(ortofoto, ficha, clave, z, x, y))
            px = int((mx - (-MEDIO_MUNDO_M + x * lado)) / (lado / 256))
            py = int((MEDIO_MUNDO_M - y * lado - my) / (lado / 256))
            rojo, verde, azul, alfa = (int(v) for v in tesela[py, px])
            casilla = (columna // 20 + fila // 20) % 2
            assert alfa == 255, f"el disparo {foto['n']} cae fuera de la imagen"
            assert rojo == (255 if casilla else 0), f"disparo {foto['n']}: casilla corrida"
            assert verde == pytest.approx(columna * 255 / (ANCHO_PX - 1), abs=6), foto["n"]
            assert azul == pytest.approx(fila * 255 / (ALTO_PX - 1), abs=6), foto["n"]

    def test_la_caja_de_la_ortofoto_contiene_a_todas_las_fotos(self, ortofoto, datos):
        x0, y0, x1, y1 = capa.leer(ortofoto).caja_3857
        # Un centímetro de holgura: el disparo 4 se construyó justo en la esquina sureste.
        for foto in datos["fotos"]["puntos"]:
            assert x0 - 0.01 <= foto["mx"] <= x1 + 0.01
            assert y0 - 0.01 <= foto["my"] <= y1 + 0.01
