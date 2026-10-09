"""Alturas elipsoidal ↔ ortométrica con geoide declarado (F15.2).

Sin grillas (el CI) se prueba el sondeo, el apagado con motivo, que no hay modelo por omisión y
que el recibo dice modelo, grilla y método. **El oráculo es `cs2cs` de PROJ**, con la grilla por la
ruta de códigos EPSG (`EPSG:4979` → `EPSG:4326+5773`), que no comparte código con la ruta
`vgridshift` explícita de `apps/formats/alturas.py`. Tolerancia: 1 mm.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.formats import alturas
from apps.formats.crs import SIN_CRS, PuntoConCrs, epsg
from apps.jobs import motivos

UTM19S = epsg(32719)
BASE = PuntoConCrs(414790.476, 7418959.900, UTM19S, z_m=1037.918)


@pytest.fixture
def carpeta_con_grilla(tmp_path, settings, monkeypatch):
    """Una carpeta con un «us_nga_egm96_15.tif» de mentira: sirve para el sondeo y la huella."""
    (tmp_path / "us_nga_egm96_15.tif").write_bytes(b"no es una grilla, es una prueba de sondeo")
    settings.PROJ_GRILLAS = str(tmp_path)
    monkeypatch.setattr(alturas, "carpetas_de_grillas", lambda: [tmp_path])
    return tmp_path


@pytest.fixture
def sin_grillas(tmp_path, monkeypatch):
    monkeypatch.setattr(alturas, "carpetas_de_grillas", lambda: [tmp_path])
    return tmp_path


class TestElModeloSeDeclara:
    def test_sin_modelo_no_hay_valor_por_omision(self):
        for vacio in (None, "", "  "):
            with pytest.raises(alturas.AlturaError) as fallo:
                alturas.convertir(BASE, modelo=vacio, sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
            assert fallo.value.codigo == "geoide-no-declarado"

    def test_un_modelo_que_no_existe_se_dice(self):
        with pytest.raises(alturas.AlturaError) as fallo:
            alturas.ondulacion_m(BASE, modelo="GEOIDE-DE-CHILE")
        assert fallo.value.codigo == "geoide-desconocido"

    def test_el_sondeo_de_un_modelo_sin_declarar_no_inventa_uno(self):
        s = alturas.sondear("")
        assert not s.disponible
        assert s.motivo == "geoide-no-declarado"
        assert s.grilla is None

    def test_no_hay_un_modelo_por_omision_en_las_firmas(self):
        for funcion in (alturas.convertir, alturas.ondulacion_m):
            parametro = inspect.signature(funcion).parameters["modelo"]
            assert parametro.default is inspect.Parameter.empty, funcion.__name__

    def test_el_catalogo_dice_el_epsg_vertical_de_cada_modelo(self):
        assert alturas.MODELOS["EGM2008"].epsg_vertical == 3855
        assert alturas.MODELOS["EGM96"].epsg_vertical == 5773


class TestSondeo:
    def test_sin_la_grilla_queda_apagado_con_motivo_y_alternativa(self, sin_grillas):
        s = alturas.sondear("EGM2008")
        assert s.disponible is False
        assert s.motivo == "sin-grilla-geoide"
        assert "us_nga_egm08_25.tif" in s.mensaje
        assert motivos.MOTIVOS["sin-grilla-geoide"].sugerencia  # la alternativa, dicha
        assert str(sin_grillas) in s.buscado_en

    def test_sin_la_grilla_convertir_no_sustituye_en_silencio(self, sin_grillas):
        with pytest.raises(alturas.AlturaError) as fallo:
            alturas.convertir(BASE, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        assert fallo.value.codigo == "sin-grilla-geoide"

    def test_una_grilla_vacia_no_cuenta(self, sin_grillas):
        (sin_grillas / "us_nga_egm96_15.tif").write_bytes(b"")
        assert alturas.sondear("EGM96").motivo == "sin-grilla-geoide"

    def test_encuentra_la_grilla_y_da_nombre_y_huella(self, carpeta_con_grilla):
        s = alturas.sondear("egm96")  # el código no distingue mayúsculas
        assert s.disponible and s.modelo == "EGM96"
        ruta = carpeta_con_grilla / "us_nga_egm96_15.tif"
        assert s.grilla.nombre == "us_nga_egm96_15.tif"
        assert s.grilla.sha256 == hashlib.sha256(ruta.read_bytes()).hexdigest()
        assert s.grilla.bytes_totales == ruta.stat().st_size

    def test_cada_modelo_busca_su_grilla_y_no_la_de_otro(self, carpeta_con_grilla):
        assert alturas.sondear("EGM96").disponible
        assert not alturas.sondear("EGM2008").disponible

    def test_las_carpetas_salen_de_la_variable_y_solo_si_existen(self, tmp_path, settings):
        settings.PROJ_GRILLAS = os.pathsep.join([str(tmp_path), str(tmp_path / "no-existe")])
        carpetas = alturas.carpetas_de_grillas()
        assert carpetas[0] == tmp_path
        assert tmp_path / "no-existe" not in carpetas

    def test_sondear_no_activa_la_red_de_proj(self, sin_grillas):
        from pyproj.network import is_network_enabled

        antes = is_network_enabled()
        alturas.sondear("EGM2008")
        assert is_network_enabled() == antes

    def test_sondear_todos_cubre_el_catalogo(self, sin_grillas):
        assert [s.modelo for s in alturas.sondear_todos()] == list(alturas.MODELOS)


class TestLaPosicionLlevaSuCrs:
    def test_sin_crs_se_detiene_y_no_se_adivina_el_huso(self, carpeta_con_grilla):
        sin = PuntoConCrs(414790.476, 7418959.900, SIN_CRS, z_m=1037.9)
        with pytest.raises(alturas.AlturaError) as fallo:
            alturas.convertir(sin, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        assert fallo.value.codigo == "crs-ausente"

    def test_sin_altura_no_hay_que_convertir(self, carpeta_con_grilla):
        plano = PuntoConCrs(414790.476, 7418959.900, UTM19S)
        with pytest.raises(alturas.AlturaError) as fallo:
            alturas.convertir(plano, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        assert fallo.value.codigo == "altura-ausente"

    def test_un_sentido_inventado_es_un_error_de_programa(self):
        with pytest.raises(ValueError):
            alturas.convertir(BASE, modelo="EGM96", sentido="arriba")


class TestElRecibo:
    """El número de `N` lo pone un doble: aquí se prueba lo que el recibo **dice**."""

    @pytest.fixture
    def con_n_de_30(self, monkeypatch):
        grilla = alturas.Grilla("us_nga_egm96_15.tif", "/x/us_nga_egm96_15.tif", "ab" * 32, 10)
        monkeypatch.setattr(alturas, "ondulacion_m", lambda punto, *, modelo: (30.0, grilla))
        return grilla

    def test_ortometrica_a_elipsoidal_suma_n(self, con_n_de_30):
        r = alturas.convertir(BASE, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        assert r.punto.z_m == pytest.approx(1037.918 + 30.0)

    def test_elipsoidal_a_ortometrica_resta_n(self, con_n_de_30):
        r = alturas.convertir(BASE, modelo="EGM96", sentido=alturas.ELIPSOIDAL_A_ORTOMETRICA)
        assert r.punto.z_m == pytest.approx(1037.918 - 30.0)

    def test_ida_y_vuelta_devuelve_la_altura(self, con_n_de_30):
        ida = alturas.convertir(BASE, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        vuelta = alturas.convertir(
            ida.punto, modelo="EGM96", sentido=alturas.ELIPSOIDAL_A_ORTOMETRICA
        )
        assert vuelta.punto.z_m == pytest.approx(BASE.z_m, abs=1e-9)

    def test_el_punto_conserva_xy_y_crs(self, con_n_de_30):
        r = alturas.convertir(BASE, modelo="EGM96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        assert (r.punto.x_m, r.punto.y_m, r.punto.crs) == (BASE.x_m, BASE.y_m, BASE.crs)

    def test_el_recibo_dice_modelo_grilla_huella_y_metodo(self, con_n_de_30):
        r = alturas.convertir(BASE, modelo="egm96", sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
        d = r.recibo.como_dict()
        assert d["modelo"] == "EGM96"
        assert d["grilla"] == "us_nga_egm96_15.tif"
        assert d["grilla_sha256"] == "ab" * 32
        assert "vgridshift" in d["metodo"]
        assert d["sentido"] == alturas.ORTOMETRICA_A_ELIPSOIDAL
        assert d["crs"] == "EPSG:32719"
        texto = str(r.recibo)
        assert "EGM96" in texto and "us_nga_egm96_15.tif" in texto and "vgridshift" in texto


class TestElComando:
    def _correr(self, **extra):
        argumentos = {
            "este": 414790.476,
            "norte": 7418959.9,
            "crs": "32719",
            "altura": 1037.918,
            "sentido": alturas.ORTOMETRICA_A_ELIPSOIDAL,
            "modelo": "EGM96",
        }
        argumentos.update(extra)
        salida = io.StringIO()
        call_command("convertir_altura", stdout=salida, **argumentos)
        return salida.getvalue()

    def test_sin_modelo_se_niega_con_el_codigo_estable(self, sin_grillas):
        with pytest.raises(CommandError, match="geoide-no-declarado"):
            self._correr(modelo="")

    def test_sin_crs_se_niega(self, sin_grillas):
        with pytest.raises(CommandError, match="crs-ausente"):
            self._correr(crs="")

    def test_sin_grilla_dice_el_motivo(self, sin_grillas):
        with pytest.raises(CommandError, match="sin-grilla-geoide"):
            self._correr()

    def test_con_grilla_imprime_el_recibo(self, carpeta_con_grilla, monkeypatch):
        grilla = alturas.sondear("EGM96").grilla
        monkeypatch.setattr(alturas, "ondulacion_m", lambda punto, *, modelo: (31.0, grilla))
        salida = self._correr()
        assert "EGM96" in salida and "us_nga_egm96_15.tif" in salida
        assert "1068.918" in salida


class TestElCatalogoDeMotivos:
    def test_los_codigos_nuevos_estan(self):
        for codigo in (
            "geoide-no-declarado",
            "geoide-desconocido",
            "sin-grilla-geoide",
            "fuera-de-la-grilla",
            "altura-ausente",
        ):
            assert codigo in motivos.MOTIVOS, codigo


# --- Oráculo: cs2cs de PROJ ---------------------------------------------------------------


def _cs2cs() -> str | None:
    hallado = shutil.which("cs2cs")
    if hallado:
        return hallado
    for candidato in sorted(Path("C:/Program Files").glob("QGIS*/bin/cs2cs.exe"), reverse=True):
        return str(candidato)
    return None


def _hay_grilla(modelo: str) -> bool:
    return alturas.sondear(modelo).disponible


#: Valores repartidos por el planeta (lon, lat en EPSG:4326): norte de Chile, Santiago, el origen,
#: París y Tokio.
PUNTOS_GRADOS = [(-68.9, -23.0), (-70.65, -33.45), (0.0, 0.0), (2.35, 48.85), (139.7, 35.7)]


def _con_cs2cs(modelo: str, lon: float, lat: float, h_elipsoidal: float) -> float:
    """H que da `cs2cs` por códigos EPSG, con las mismas carpetas de grillas y sin red."""
    carpetas = os.pathsep.join(str(c) for c in alturas.carpetas_de_grillas())
    entorno = dict(os.environ, PROJ_DATA=carpetas, PROJ_NETWORK="OFF")
    vertical = alturas.MODELOS[modelo].epsg_vertical
    r = subprocess.run(  # noqa: S603 - argumentos fijos y datos de la prueba
        [_cs2cs(), "-d", "6", "EPSG:4979", f"EPSG:4326+{vertical}"],
        input=f"{lat} {lon} {h_elipsoidal}\n",
        capture_output=True,
        text=True,
        env=entorno,
        timeout=60,
        check=True,
    )
    return float(r.stdout.split()[-1])


@pytest.mark.oraculo
@pytest.mark.skipif(_cs2cs() is None, reason="cs2cs (PROJ) no está en esta máquina")
@pytest.mark.parametrize("modelo", sorted(alturas.MODELOS))
@pytest.mark.parametrize("lon, lat", PUNTOS_GRADOS)
def test_la_ortometrica_coincide_con_cs2cs_a_menos_de_1_mm(modelo, lon, lat):
    if not _hay_grilla(modelo):
        pytest.skip(f"no hay grilla de {modelo} en esta máquina")
    punto = PuntoConCrs(lon, lat, epsg(4326), z_m=1000.0)
    r = alturas.convertir(punto, modelo=modelo, sentido=alturas.ELIPSOIDAL_A_ORTOMETRICA)
    esperado = _con_cs2cs(modelo, lon, lat, 1000.0)
    assert abs(r.punto.z_m - esperado) < 0.001


@pytest.mark.oraculo
@pytest.mark.skipif(_cs2cs() is None, reason="cs2cs (PROJ) no está en esta máquina")
@pytest.mark.parametrize("modelo", sorted(alturas.MODELOS))
def test_la_base_de_baquedano_en_utm_coincide_con_cs2cs(modelo):
    """La posición va en UTM 19S, como en el CSV de TBC: el camino incluye la reproyección."""
    if not _hay_grilla(modelo):
        pytest.skip(f"no hay grilla de {modelo} en esta máquina")
    from pyproj import Transformer

    r = alturas.convertir(BASE, modelo=modelo, sentido=alturas.ORTOMETRICA_A_ELIPSOIDAL)
    lon, lat = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True).transform(
        BASE.x_m, BASE.y_m
    )
    # `cs2cs` convierte elipsoidal → ortométrica; la inversa se comprueba por ida y vuelta: la
    # salida convertida de vuelta por el oráculo tiene que ser la altura de entrada.
    vuelta = _con_cs2cs(modelo, lon, lat, r.punto.z_m)
    assert abs(vuelta - BASE.z_m) < 0.001
