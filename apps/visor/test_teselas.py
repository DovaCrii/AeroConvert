"""Cortar teselas: el pegamento alrededor de `gdalwarp`, con un GDAL de mentira.

Lo que se vigila es lo que `AGENTS.md` pone como regla, camino por camino:

- **Regla 1.** El código de salida no es la prueba: un `gdalwarp` que sale bien y no escribe nada, o
  escribe un PNG de otra medida, o escribe basura, **no se sirve**.
- **Regla 5.** El original no se toca (`sha256` y `mtime` iguales antes y después, en **cada**
  camino de fallo) y la salida solo se renombra tras verificarla: nunca queda un parcial.

Con GDAL de verdad, `test_oraculo.py` compara la tesela con un `gdalwarp` independiente.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from apps.visor import cache, capa, mercator, motor, teselas
from apps.visor.testing import GdalDeMentira, info_de_gdal, png_de


@pytest.fixture
def entorno(monkeypatch, tmp_path, settings):
    """Un original, su caché y un GDAL de mentira. Devuelve lo que las pruebas necesitan."""
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 64
    falso = GdalDeMentira()
    monkeypatch.setattr(motor, "correr", falso)
    (tmp_path / "obra").mkdir()
    original = tmp_path / "obra" / "ortofoto.tif"
    original.write_bytes(b"II*\x00" + b"contenido del original" * 100)
    clave = cache.clave_de(original)
    ficha = capa.leer(original)
    falso.llamadas.clear()
    return original, ficha, clave, falso


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _tesela_que_toca(ficha: capa.Capa) -> tuple[int, int, int]:
    z = ficha.zoom_maximo
    return (z, *mercator.tesela_de_lonlat(*ficha.centro_4326, z))


class TestElCamino:
    def test_una_tesela_dentro_de_la_capa_se_corta_con_gdalwarp(self, entorno):
        original, ficha, clave, falso = entorno
        z, x, y = _tesela_que_toca(ficha)

        contenido = teselas.tesela(original, ficha, clave, z, x, y)

        assert contenido.startswith(b"\x89PNG")
        assert falso.contar("gdalwarp") == 1

    def test_los_argumentos_son_los_de_una_tesela_en_3857(self, entorno):
        original, ficha, clave, falso = entorno
        z, x, y = _tesela_que_toca(ficha)
        teselas.tesela(original, ficha, clave, z, x, y)

        _, argumentos = falso.llamadas[-1]
        caja = mercator.caja_de_tesela(z, x, y)
        assert argumentos[argumentos.index("-t_srs") + 1] == "EPSG:3857"
        assert argumentos[argumentos.index("-ts") + 1 : argumentos.index("-ts") + 3] == [
            "256",
            "256",
        ]
        asignados = argumentos[argumentos.index("-te") + 1 : argumentos.index("-te") + 5]
        assert [float(v) for v in asignados] == pytest.approx(list(caja))
        assert argumentos[argumentos.index("-of") + 1] == "PNG"
        assert "-dstalpha" in argumentos, "lo que cae fuera de la imagen tiene que ser transparente"
        assert argumentos[-2] == str(original), "se corta del original, no de una copia"
        assert "shell" not in " ".join(argumentos).lower()

    def test_la_segunda_vez_sale_de_la_cache_sin_lanzar_nada(self, entorno):
        original, ficha, clave, falso = entorno
        z, x, y = _tesela_que_toca(ficha)
        primera = teselas.tesela(original, ficha, clave, z, x, y)
        segunda = teselas.tesela(original, ficha, clave, z, x, y)
        assert primera == segunda
        assert falso.contar("gdalwarp") == 1

    def test_una_tesela_fuera_de_la_capa_es_transparente_y_no_lanza_nada(self, entorno):
        original, ficha, clave, falso = entorno
        z = ficha.zoom_maximo
        lejos = mercator.tesela_de_lonlat(ficha.centro_4326[0] + 5, ficha.centro_4326[1], z)

        contenido = teselas.tesela(original, ficha, clave, z, *lejos)

        assert falso.contar("gdalwarp") == 0
        imagen = Image.open(__import__("io").BytesIO(contenido))
        assert imagen.size == (256, 256)
        assert imagen.convert("RGBA").getextrema()[3] == (0, 0), "todo transparente"

    def test_la_tesela_vacia_es_un_png_de_256(self):
        imagen = Image.open(__import__("io").BytesIO(teselas.tesela_vacia()))
        assert (imagen.format, imagen.size) == ("PNG", (256, 256))

    def test_se_escribe_en_la_carpeta_de_la_cache_y_sin_parciales(self, entorno):
        original, ficha, clave, _falso = entorno
        z, x, y = _tesela_que_toca(ficha)
        teselas.tesela(original, ficha, clave, z, x, y)

        nombres = sorted(p.name for p in cache.carpeta_de(clave).iterdir())
        assert f"{z}-{x}-{y}.png" in nombres
        assert not [n for n in nombres if cache.MARCA_PARCIAL in n]


class TestLaSalidaSeVerificaNoSeSupone:
    """**Regla 1.** GDAL sale con 0 y puede no haber hecho nada."""

    def _sirve(self, entorno) -> None:
        original, ficha, clave, falso = entorno
        z, x, y = _tesela_que_toca(ficha)
        antes = _huella(original)
        with pytest.raises(motor.ErrorDeGdal) as dentro:
            teselas.tesela(original, ficha, clave, z, x, y)
        self.codigo = dentro.value.codigo
        # El original, intacto en el camino de fallo; y nada servible quedó en la caché.
        assert _huella(original) == antes
        carpeta = cache.carpeta_de(clave)
        assert not list(carpeta.glob("*.png")), "una salida que no verificó no se guarda"
        assert not [p for p in carpeta.iterdir() if cache.MARCA_PARCIAL in p.name]

    def test_sale_con_cero_y_no_escribe_nada(self, entorno):
        entorno[3].escribir = False
        self._sirve(entorno)
        assert self.codigo == "sin-salida"

    def test_escribe_un_png_de_otra_medida(self, entorno):
        entorno[3].lado_de_salida = 128
        self._sirve(entorno)
        assert self.codigo == "salida-invalida"

    def test_escribe_basura(self, entorno):
        entorno[3].contenido = b"esto no es un png"
        self._sirve(entorno)
        assert self.codigo == "salida-invalida"

    def test_escribe_un_png_cortado(self, entorno):
        entorno[3].contenido = png_de()[:80]
        self._sirve(entorno)
        assert self.codigo == "salida-invalida"

    def test_escribe_un_archivo_vacio(self, entorno):
        entorno[3].contenido = b""
        self._sirve(entorno)
        assert self.codigo == "sin-salida"

    def test_gdal_que_falla_deja_el_original_intacto(self, entorno):
        entorno[3].fallar_con = motor.ErrorDeGdal("ERROR 1: boom", "error-del-motor")
        self._sirve(entorno)
        assert self.codigo == "error-del-motor"

    def test_gdal_que_tarda_demasiado_se_dice_y_no_cuelga(self, entorno):
        entorno[3].fallar_con = motor.ErrorDeGdal("tardó", "tardo-demasiado")
        self._sirve(entorno)
        assert self.codigo == "tardo-demasiado"

    def test_verificar_png_acepta_uno_bueno(self, tmp_path):
        bueno = tmp_path / "t.png"
        bueno.write_bytes(png_de())
        teselas.verificar_png(bueno)  # no levanta


class TestLaFuenteDe8Bits:
    def test_una_8_bits_se_corta_del_original(self, entorno):
        original, ficha, clave, _ = entorno
        assert teselas.fuente_para(original, ficha, clave) == original

    def test_una_de_16_bits_pasa_por_un_vrt_escalado_en_la_cache(self, monkeypatch, entorno):
        original, _, clave, falso = entorno
        falso.info = info_de_gdal(tipo="UInt16", bandas=1, interpretacion="Gray")
        falso.minimo, falso.maximo = 100.0, 3000.0
        ficha = capa.leer(original)
        falso.llamadas.clear()

        fuente = teselas.fuente_para(original, ficha, clave)

        assert fuente == cache.carpeta_de(clave) / "fuente.vrt"
        _, argumentos = falso.llamadas[0]
        assert argumentos[argumentos.index("-ot") + 1] == "Byte"
        assert argumentos[argumentos.index("-scale") + 1 : argumentos.index("-scale") + 5] == [
            "100.0",
            "3000.0",
            "0",
            "255",
        ]
        assert argumentos[-2] == str(original), "el VRT apunta al original; no lo copia"
        # Una segunda vez no vuelve a prepararlo.
        assert teselas.fuente_para(original, ficha, clave) == fuente
        assert falso.contar("gdal_translate") == 1

    def test_una_con_paleta_se_expande_a_rgba(self, entorno):
        original, _, clave, falso = entorno
        falso.info = info_de_gdal(tipo="Byte", bandas=1, interpretacion="Palette")
        ficha = capa.leer(original)
        falso.llamadas.clear()
        teselas.fuente_para(original, ficha, clave)
        assert "-expand" in falso.llamadas[0][1]
        assert "rgba" in falso.llamadas[0][1]

    def test_una_de_ocho_bandas_elige_tres(self, entorno):
        original, _, clave, falso = entorno
        falso.info = info_de_gdal(tipo="Byte", bandas=8)
        ficha = capa.leer(original)
        falso.llamadas.clear()
        teselas.fuente_para(original, ficha, clave)
        argumentos = falso.llamadas[0][1]
        bandas = [argumentos[i + 1] for i, a in enumerate(argumentos) if a == "-b"]
        assert bandas == ["1", "2", "3"]

    def test_un_vrt_que_gdal_no_escribio_no_se_acepta(self, entorno):
        original, _, clave, falso = entorno
        falso.info = info_de_gdal(tipo="Byte", bandas=1, interpretacion="Palette")
        ficha = capa.leer(original)
        falso.escribir = False
        with pytest.raises(motor.ErrorDeGdal) as dentro:
            teselas.fuente_para(original, ficha, clave)
        assert dentro.value.codigo == "sin-salida"
        assert not (cache.carpeta_de(clave) / "fuente.vrt").exists()


class TestElOriginalNoSeToca:
    def test_tras_cortar_muchas_el_original_y_su_carpeta_siguen_iguales(self, entorno):
        original, ficha, clave, _ = entorno
        antes = _huella(original)
        carpeta_antes = sorted(p.name for p in original.parent.iterdir())
        z = ficha.zoom_maximo
        cx, cy = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                teselas.tesela(original, ficha, clave, z, cx + dx, cy + dy)
        assert _huella(original) == antes
        assert sorted(p.name for p in original.parent.iterdir()) == carpeta_antes, (
            "ni un .aux.xml ni nada al lado"
        )

    def test_el_entorno_del_hijo_apaga_los_aux_xml(self):
        assert motor.entorno()["GDAL_PAM_ENABLED"] == "NO"

    def test_el_entorno_no_toca_el_del_servidor(self):
        import os

        antes = dict(os.environ)
        motor.entorno(GDAL_CACHEMAX="1")
        assert dict(os.environ) == antes


class TestLaDisponibilidad:
    def test_sin_gdal_el_motivo_trae_alternativa(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: sondas.EstadoGdal(disponible=False, motivo="no hay")
        )
        d = motor.disponibilidad()
        assert not d.disponible
        assert d.codigo_motivo == "sin-gdal"
        assert d.sugerencia, "una capacidad apagada dice qué hacer mientras tanto"
        assert "Convertir" in d.sugerencia

    def test_con_gdal_pero_sin_una_de_las_herramientas_tambien_se_dice(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: sondas.EstadoGdal(disponible=True, version="GDAL 3")
        )
        monkeypatch.setattr(
            motor, "ejecutable", lambda nombre: None if nombre == "gdalwarp" else "/x/" + nombre
        )
        d = motor.disponibilidad()
        assert not d.disponible and "gdalwarp" in d.mensaje

    def test_con_todo_esta_disponible(self, monkeypatch):
        from apps.engines import sondas

        monkeypatch.setattr(
            sondas, "sondar_gdal", lambda: sondas.EstadoGdal(disponible=True, version="GDAL 3.12")
        )
        monkeypatch.setattr(motor, "ejecutable", lambda nombre: "/x/" + nombre)
        d = motor.disponibilidad()
        assert d.disponible and d.version == "GDAL 3.12"

    def test_correr_sin_la_herramienta_levanta_sin_gdal(self, monkeypatch):
        monkeypatch.setattr(motor, "ejecutable", lambda nombre: None)
        with pytest.raises(motor.ErrorDeGdal) as dentro:
            motor.correr("gdalwarp", [], plazo_s=1)
        assert dentro.value.codigo == "sin-gdal"
