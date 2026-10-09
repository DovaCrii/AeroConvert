"""La caché de teselas: se escribe de golpe, se acota, se barre lo menos mirado y se vacía a mano.

Nada de GDAL aquí: es disco y reloj. El reloj se **fija con `os.utime`** en vez de dormir, así que
la prueba del orden de barrido no depende de lo rápido que sea la máquina.
"""

from __future__ import annotations

import hashlib
import os
import time
from io import StringIO

import pytest
from django.core.management import call_command

from apps.visor import cache


@pytest.fixture
def carpeta(tmp_path, settings):
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 1
    cache._escrito_desde_el_barrido = 0
    return tmp_path / "cache-visor"


#: Una clave con la forma que escribe la caché: 32 caracteres hexadecimales.
CLAVE = "a" * 32


def _con_fecha(ruta, hace_s: float) -> None:
    ahora = time.time()
    os.utime(ruta, (ahora - hace_s, ahora - hace_s))


def _llenar(carpeta, n: int, tamano: int = 100_000):
    """`n` archivos de `tamano` bytes, el 0 el más viejo y el último el más nuevo."""
    rutas = []
    for i in range(n):
        ruta = carpeta / "ab" / CLAVE / f"{i}-0-0.png"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"x" * tamano)
        _con_fecha(ruta, hace_s=(n - i) * 100)
        rutas.append(ruta)
    return rutas


class TestLaClave:
    def test_cambia_si_cambia_el_archivo(self, tmp_path):
        original = tmp_path / "ortofoto.tif"
        original.write_bytes(b"uno")
        antes = cache.clave_de(original)
        original.write_bytes(b"dos y mas")
        assert cache.clave_de(original) != antes

    def test_es_estable_si_no_cambia(self, tmp_path):
        original = tmp_path / "ortofoto.tif"
        original.write_bytes(b"uno")
        assert cache.clave_de(original) == cache.clave_de(original)

    def test_un_archivo_que_no_esta_levanta(self, tmp_path):
        with pytest.raises(OSError):
            cache.clave_de(tmp_path / "no-esta.tif")

    def test_se_reparte_en_subcarpetas(self, carpeta):
        clave = "ab" + "c" * 30
        assert cache.carpeta_de(clave) == carpeta / "ab" / clave


class TestLaEscrituraEsDeGolpe:
    def test_no_queda_ningun_parcial(self, carpeta):
        destino = carpeta / "ab" / CLAVE / "3-1-2.png"
        cache.escribir(destino, b"png")
        assert destino.read_bytes() == b"png"
        assert [p.name for p in destino.parent.iterdir()] == ["3-1-2.png"]

    def test_dos_escrituras_de_lo_mismo_no_se_pisan(self, carpeta):
        destino = carpeta / "ab" / CLAVE / "3-1-2.png"
        cache.escribir(destino, b"uno")
        cache.escribir(destino, b"uno")
        assert destino.read_bytes() == b"uno"

    def test_un_acierto_anota_que_se_miro(self, carpeta):
        destino = carpeta / "ab" / CLAVE / "3-1-2.png"
        cache.escribir(destino, b"png")
        _con_fecha(destino, hace_s=5000)
        antes = destino.stat().st_mtime
        assert cache.leer(destino) == b"png"
        assert destino.stat().st_mtime > antes + 1000

    def test_leer_lo_que_no_esta_da_none(self, carpeta):
        assert cache.leer(carpeta / "ab" / "no" / "esta.png") is None

    def test_reemplazar_tolera_un_destino_que_otro_dejo(self, carpeta, monkeypatch):
        """En Windows `os.replace` falla si otro hilo lee el destino: si ya está, sirve."""
        destino = carpeta / "ab" / CLAVE / "t.png"
        destino.parent.mkdir(parents=True)
        destino.write_bytes(b"ya")
        parcial = cache.nombre_de_parcial(destino)
        parcial.write_bytes(b"ya")

        def falla(*_):
            raise PermissionError("abierto")

        monkeypatch.setattr(cache.os, "replace", falla)
        cache.reemplazar(parcial, destino)  # no levanta

        destino.unlink()
        with pytest.raises(PermissionError):
            cache.reemplazar(parcial, destino)


class TestElBarrido:
    def test_bajo_el_tope_no_toca_nada(self, carpeta):
        rutas = _llenar(carpeta, 5)  # 500 kB de 1 MiB
        resultado = cache.barrer()
        assert resultado.archivos_borrados == 0
        assert all(r.exists() for r in rutas)

    def test_pasado_el_tope_borra_lo_menos_mirado_primero(self, carpeta):
        rutas = _llenar(carpeta, 15)  # 1,5 MB contra 1 MiB
        resultado = cache.barrer()
        vivos = [r for r in rutas if r.exists()]
        assert resultado.archivos_borrados == 15 - len(vivos) > 0
        # Se borró un tramo contiguo desde la más vieja: las que quedan son las más nuevas.
        assert vivos == rutas[-len(vivos) :]
        # Y se baja hasta el 80 %, no solo hasta el tope.
        assert resultado.bytes_despues <= cache.tope_bytes() * cache.FRACCION_AL_BARRER

    def test_lo_que_se_acaba_de_mirar_sobrevive(self, carpeta):
        """LRU y no FIFO: la primera que se escribió, si se miró ahora, no es la que se va."""
        rutas = _llenar(carpeta, 15)
        assert cache.leer(rutas[0]) is not None  # la más vieja, vista ahora mismo
        cache.barrer()
        assert rutas[0].exists()
        assert not rutas[1].exists()

    def test_simular_cuenta_y_no_borra(self, carpeta):
        rutas = _llenar(carpeta, 15)
        resultado = cache.barrer(simular=True)
        assert resultado.archivos_borrados > 0
        assert all(r.exists() for r in rutas)

    def test_un_tope_dado_manda_sobre_el_de_ajustes(self, carpeta):
        rutas = _llenar(carpeta, 5)
        resultado = cache.barrer(tope=0)
        assert resultado.archivos_borrados == 5
        assert not any(r.exists() for r in rutas)
        assert not (carpeta / "ab").exists(), "las carpetas vacías también se van"

    def test_un_parcial_viejo_huerfano_se_borra_y_uno_reciente_no(self, carpeta):
        viejo = carpeta / "ab" / CLAVE / f"1-0-0.png{cache.MARCA_PARCIAL}aaaa1111"
        reciente = carpeta / "ab" / CLAVE / f"1-0-1.png{cache.MARCA_PARCIAL}bbbb2222"
        viejo.parent.mkdir(parents=True)
        viejo.write_bytes(b"a medias")
        reciente.write_bytes(b"escribiendose")
        _con_fecha(viejo, hace_s=cache.EDAD_DE_UN_PARCIAL_S + 60)
        resultado = cache.barrer()
        assert not viejo.exists()
        assert reciente.exists(), "podría estar escribiéndolo otro hilo ahora mismo"
        assert resultado.parciales_borrados == 1

    def test_barre_solo_cuando_lo_escrito_pasa_de_un_veinteavo_del_tope(self, carpeta):
        rutas = _llenar(carpeta, 15)  # ya pasa del tope
        cache.escribir(carpeta / "ab" / CLAVE / "1-1-1.png", b"x" * 100)  # < 1/20 del tope
        assert all(r.exists() for r in rutas), "una escritura chica no dispara el barrido"
        cache.escribir(carpeta / "ab" / CLAVE / "2-2-2.png", b"x" * 60_000)  # > 52 kB
        assert not rutas[0].exists(), "una grande sí: la caché no pasa del tope por mucho"

    def test_un_disco_que_falla_no_tumba_la_escritura(self, carpeta, monkeypatch):
        def falla(*_a, **_k):
            raise OSError("disco")

        monkeypatch.setattr(cache, "barrer", falla)
        cache.escribir(carpeta / "ab" / CLAVE / "2-2-2.png", b"x" * 100_000)  # no levanta

    def test_el_barrido_de_la_aplicacion_tambien_barre_las_teselas(self, carpeta, db):
        from apps.jobs import retencion

        _llenar(carpeta, 15)
        resultado = retencion.barrer()
        assert resultado.teselas_borradas > 0
        assert "de la caché del mapa" in str(resultado)

    def test_usado_bytes_suma_lo_que_hay(self, carpeta):
        _llenar(carpeta, 3, tamano=1000)
        assert cache.usado_bytes() == 3000


class TestElComando:
    def test_simular_no_borra(self, carpeta):
        rutas = _llenar(carpeta, 15)
        salida = StringIO()
        call_command("barrer_teselas", "--simular", stdout=salida)
        assert "Simulación" in salida.getvalue()
        assert all(r.exists() for r in rutas)

    def test_barre_hasta_el_tope(self, carpeta):
        rutas = _llenar(carpeta, 15)
        salida = StringIO()
        call_command("barrer_teselas", stdout=salida)
        assert "archivos de la caché de teselas" in salida.getvalue()
        assert sum(r.exists() for r in rutas) < 15

    def test_otro_tope_para_esta_vez(self, carpeta):
        rutas = _llenar(carpeta, 5)  # 500 kB: bajo el tope de ajustes
        call_command("barrer_teselas", "--tope-mb", "0", stdout=StringIO())
        assert not any(r.exists() for r in rutas)

    def test_vaciar_borra_todo(self, carpeta):
        rutas = _llenar(carpeta, 5)
        call_command("barrer_teselas", "--vaciar", stdout=StringIO())
        assert not any(r.exists() for r in rutas)


def test_la_carpeta_por_omision_esta_junto_al_codigo_y_no_en_la_de_trabajo(settings, tmp_path):
    """No gasta el `PRESUPUESTO_GB` de los trabajos: las teselas se rehacen."""
    settings.VISOR_CACHE = ""
    settings.BASE_DIR = tmp_path
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    assert cache.carpeta() == tmp_path / "cache-visor"
    assert not str(cache.carpeta()).startswith(settings.CARPETA_DE_TRABAJO)


def test_la_huella_no_depende_de_nada_que_no_este_en_el_nombre(tmp_path):
    """Guarda: la clave es sha256 de ruta|tamaño|mtime|versión, truncada a 32 caracteres."""
    original = tmp_path / "o.tif"
    original.write_bytes(b"abc")
    datos = original.stat()
    esperado = hashlib.sha256(
        f"{original}|{datos.st_size}|{datos.st_mtime_ns}|{cache.VERSION}".encode()
    ).hexdigest()[:32]
    assert cache.clave_de(original) == esperado


def test_el_barrido_no_toca_lo_que_no_es_de_la_cache(carpeta):
    """Si la variable apuntara por error a una carpeta con otras cosas, no se les borra nada."""
    ajeno = carpeta / "entrega_cliente.pdf"
    otro = carpeta / "ab" / CLAVE / "notas.txt"
    otro.parent.mkdir(parents=True)
    ajeno.write_bytes(b"x" * 200_000)
    otro.write_bytes(b"x" * 200_000)
    _con_fecha(ajeno, 10_000)
    _con_fecha(otro, 10_000)
    _llenar(carpeta, 15)

    cache.barrer()
    cache.barrer(tope=0)

    assert ajeno.exists() and otro.exists()
