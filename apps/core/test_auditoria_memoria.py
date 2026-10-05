"""Los hallazgos de memoria y disco de la auditoría de seguridad del 2026-10-05 (F11.10).

Cada prueba pone un archivo hostil o enorme de tamaño acotado donde antes la memoria o el
disco crecían con él. Los identificadores (D-01, B-01...) son los del informe.
"""

from __future__ import annotations

import tracemalloc
from types import SimpleNamespace

import pytest

from apps.formats import deteccion, puntos, rinex
from apps.jobs import estimacion, runner

pytestmark = pytest.mark.django_db


def _libreta(ruta, lineas: int):
    with open(ruta, "w", encoding="utf-8", newline="\n") as salida:
        salida.write("punto,norte,este,cota,descripcion\n")
        for n in range(lineas):
            norte, este, cota = 7_300_000 + n * 0.01, 495_000 + n * 0.01, 100 + n % 50
            salida.write(f"P{n},{norte:.3f},{este:.3f},{cota},T\n")


class TestD01LibretaEnFlujo:
    def test_la_memoria_no_crece_con_el_archivo(self, tmp_path):
        """300.000 líneas (~14 MB). Leídas enteras pasan de 150 MB; en flujo, no."""
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 300_000)
        tracemalloc.start()
        try:
            cabecera = puntos.leer(archivo)
            _actual, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert cabecera.puntos_leidos == 300_000
        assert pico < 40 * 1024 * 1024, f"pico de {pico / 1e6:.0f} MB"

    def test_el_resumen_es_el_mismo_de_siempre(self, tmp_path):
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 1_000)
        cabecera = puntos.leer(archivo)
        assert cabecera.puntos_leidos == 1_000
        assert cabecera.lineas_ignoradas == 0
        assert cabecera.minimo[0] == pytest.approx(7_300_000.0)
        assert cabecera.maximo[0] == pytest.approx(7_300_000 + 999 * 0.01)
        assert cabecera.minimo[2] == 100 and cabecera.maximo[2] == 149
        assert cabecera.tiene_encabezado
        assert cabecera.leido_completo

    def test_la_muestra_se_reparte_por_todo_el_archivo_y_no_pasa_del_tope(self, tmp_path):
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 50_000)
        muestra = puntos.leer(archivo).muestra
        assert 0 < len(muestra) <= puntos.MUESTRA_MAXIMA
        assert muestra[0].identificador == "P0"
        assert int(muestra[-1].identificador[1:]) > 40_000, "no es solo la cabeza"

    def test_pasado_el_tope_de_lineas_se_dice(self, tmp_path, monkeypatch):
        monkeypatch.setattr(puntos, "LINEAS_MAXIMAS_AL_INSPECCIONAR", 100)
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 500)
        cabecera = puntos.leer(archivo)
        assert not cabecera.leido_completo
        assert cabecera.puntos_leidos < 500

    def test_la_inspeccion_avisa_de_que_el_conteo_es_parcial(self, tmp_path, monkeypatch):
        monkeypatch.setattr(puntos, "LINEAS_MAXIMAS_AL_INSPECCIONAR", 100)
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 500)
        avisos = deteccion.inspeccionar(archivo).avisos
        assert any("libreta muy grande" in aviso for aviso in avisos)

    def test_campos_ogr_lee_solo_las_primeras_lineas(self, tmp_path):
        archivo = tmp_path / "libreta.csv"
        _libreta(archivo, 300_000)
        tracemalloc.start()
        try:
            puntos.campos_ogr(archivo)
            _actual, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert pico < 5 * 1024 * 1024, f"pico de {pico / 1e6:.0f} MB"


class TestD02LineaSinSalto:
    def test_una_linea_gigante_no_es_un_rinex_y_no_se_lee_entera(self, tmp_path):
        archivo = tmp_path / "x.obs"
        with open(archivo, "wb") as salida:
            salida.write(b"A" * (rinex.LARGO_MAXIMO_DE_LINEA * 40))  # sin un solo salto
        tracemalloc.start()
        try:
            with pytest.raises(rinex.NoEsRinex, match="no es un RINEX"):
                rinex.leer_cabecera(archivo)
            _actual, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert pico < 2 * 1024 * 1024

    def test_la_inspeccion_la_declara_desconocida(self, tmp_path):
        archivo = tmp_path / "x.obs"
        archivo.write_bytes(b"A" * (rinex.LARGO_MAXIMO_DE_LINEA * 4))
        assert deteccion.inspeccionar(archivo).codigo_formato == ""


class TestB01SalidaMayorQueElOrigen:
    """Un TIFF de pocos KB que declara miles de millones de píxeles."""

    def _inspeccion(self):
        cabecera = SimpleNamespace(ancho_px=200_000, alto_px=200_000, bandas=3, bits_por_muestra=8)
        return SimpleNamespace(tiff=cabecera, bytes_totales=10_000, ruta="/x/bomba.tif", las=None)

    def _trabajo(self):
        return SimpleNamespace(target_format_code="geotiff", options={"compresion": "NONE"})

    def test_la_salida_estimada_no_cabe_y_el_trabajo_se_niega_antes_de_empezar(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(estimacion.shutil, "disk_usage", lambda _c: SimpleNamespace(free=50e9))
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_espacio_de_la_salida(
                self._trabajo(), self._inspeccion(), tmp_path / "bomba_geotiff.tif"
            )
        assert fallo.value.codigo == "sin-espacio"
        assert "comprimido" in str(fallo.value)

    def test_una_salida_razonable_pasa(self, tmp_path):
        inspeccion = self._inspeccion()
        inspeccion.tiff.ancho_px = inspeccion.tiff.alto_px = 100
        runner._exigir_espacio_de_la_salida(
            self._trabajo(), inspeccion, tmp_path / "pequena_geotiff.tif"
        )

    def test_sin_cabecera_de_tiff_no_se_juzga(self, tmp_path):
        inspeccion = SimpleNamespace(tiff=None, bytes_totales=1, ruta="x", las=None)
        runner._exigir_espacio_de_la_salida(self._trabajo(), inspeccion, tmp_path / "x")
