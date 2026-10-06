"""El despachador por dentro: el bucle de un carril, el arranque y la parada.

`procesar_una_vez` ya la cubren las pruebas de la cola; lo que quedaba sin probar era lo que
rodea al hilo: que un trabajo malo no lo mate, que solo el carril pesado haga la limpieza, que
`arrancar` respete sus tres guardas y que `detener` espere a los hilos. Ninguna prueba arranca
un hilo de verdad: el bucle se corre en el hilo de la prueba y se para solo.
"""

from __future__ import annotations

import gc
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from apps.jobs import despachador, retencion


@pytest.fixture(autouse=True)
def estado_limpio(monkeypatch):
    """El despachador guarda su estado en el módulo: se deja como estaba."""
    monkeypatch.setattr(despachador, "_hilos", [])
    monkeypatch.setattr(despachador, "_parar", threading.Event())
    monkeypatch.setattr(despachador, "_ciclos", 0)
    monkeypatch.setattr(despachador.time, "sleep", lambda _s: None)
    monkeypatch.setattr(despachador, "close_old_connections", lambda: None)


def _parar_tras(veces: int, resultado=1, fallar_en: int | None = None):
    """Un `procesar_una_vez` falso que para el bucle tras `veces` llamadas."""
    llamadas = []

    def falso(carril=None):
        llamadas.append(carril)
        if len(llamadas) >= veces:
            despachador._parar.set()
        if fallar_en == len(llamadas):
            raise RuntimeError("un trabajo malo")
        return resultado

    return falso, llamadas


class TestVive:
    def test_el_proceso_propio_vive(self):
        assert despachador._vive(os.getpid()) is True

    def test_un_proceso_terminado_no_vive(self):
        proceso = subprocess.Popen([sys.executable, "-c", "pass"])  # nosec B603
        proceso.wait()
        pid = proceso.pid
        # En Windows el proceso sigue «existiendo» mientras alguien conserve su manejador, y
        # quien lo conserva aquí es el propio `Popen`. El obrero real no es hijo de nadie.
        del proceso
        gc.collect()
        assert despachador._vive(pid) is False


class TestElBucle:
    def test_sin_carril_late_y_procesa_hasta_que_se_le_para(self, monkeypatch):
        falso, llamadas = _parar_tras(3)
        latidos = []
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        monkeypatch.setattr(despachador, "latir", lambda: latidos.append(1))

        despachador._bucle()

        assert llamadas == [None, None, None]
        assert despachador._ciclos == 3
        assert latidos == [1], "late en el primer ciclo y no en cada uno"

    def test_solo_el_carril_pesado_late_y_barre(self, monkeypatch):
        latidos, barridos = [], []
        monkeypatch.setattr(despachador, "latir", lambda: latidos.append(1))
        monkeypatch.setattr(despachador, "CICLOS_ENTRE_BARRIDOS", 1)
        monkeypatch.setattr(
            retencion, "barrer", lambda: barridos.append(1) or SimpleNamespace(bytes_liberados=0)
        )

        falso, _ = _parar_tras(2)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        despachador._bucle(despachador.LIGERO)
        assert not latidos and not barridos, "dos hilos barriendo la misma carpeta es una carrera"

        despachador._parar.clear()
        falso, _ = _parar_tras(2)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        despachador._bucle(despachador.PESADO)
        assert latidos and barridos

    def test_cuenta_lo_liberado_cuando_el_barrido_libera(self, monkeypatch, caplog):
        monkeypatch.setattr(despachador, "latir", lambda: None)
        monkeypatch.setattr(despachador, "CICLOS_ENTRE_BARRIDOS", 1)
        monkeypatch.setattr(retencion, "barrer", lambda: SimpleNamespace(bytes_liberados=2048))
        falso, _ = _parar_tras(1)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        with caplog.at_level("INFO", logger=despachador.registro.name):
            despachador._bucle()
        assert "Barrido" in caplog.text

    def test_un_trabajo_malo_no_mata_al_hilo(self, monkeypatch, caplog):
        falso, llamadas = _parar_tras(3, fallar_en=1)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        monkeypatch.setattr(despachador, "latir", lambda: None)

        despachador._bucle()

        assert len(llamadas) == 3, "tras el fallo siguió con el ciclo siguiente"
        assert "Fallo del despachador" in caplog.text

    def test_duerme_solo_cuando_no_hubo_nada_que_hacer(self, monkeypatch):
        dormidas = []
        monkeypatch.setattr(despachador.time, "sleep", dormidas.append)
        monkeypatch.setattr(despachador, "latir", lambda: None)

        falso, _ = _parar_tras(2, resultado=0)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        despachador._bucle(despachador.LIGERO)
        assert dormidas == [despachador.INTERVALO_S] * 2

        dormidas.clear()
        despachador._parar.clear()
        falso, _ = _parar_tras(2, resultado=1)
        monkeypatch.setattr(despachador, "procesar_una_vez", falso)
        despachador._bucle(despachador.LIGERO)
        assert dormidas == [], "con trabajo en cola no hay espera"


class TestLosCarriles:
    def test_se_lanza_un_hilo_por_carril(self, monkeypatch):
        arrancados = []
        monkeypatch.setattr(despachador, "_bucle", lambda carril=None: arrancados.append(carril))

        despachador._lanzar_carriles()
        for hilo in despachador._hilos:
            hilo.join(timeout=2)

        assert sorted(arrancados) == sorted(despachador.CARRILES)
        assert {h.name for h in despachador._hilos} == {
            f"aeroconvert-{c}" for c in despachador.CARRILES
        }
        assert all(h.daemon for h in despachador._hilos)

    def test_vivo_mira_a_los_hilos(self):
        assert despachador.vivo() is False
        parado = threading.Event()
        hilo = threading.Thread(target=parado.wait, daemon=True)
        hilo.start()
        despachador._hilos.append(hilo)
        try:
            assert despachador.vivo() is True
        finally:
            parado.set()
            hilo.join(timeout=2)
        assert despachador.vivo() is False

    def test_detener_avisa_y_espera_a_los_hilos(self):
        unidos = []
        falso = SimpleNamespace(join=lambda timeout: unidos.append(timeout))
        despachador._hilos.append(falso)

        despachador.detener(timeout=1.5)

        assert despachador._parar.is_set()
        assert unidos == [1.5]

    def test_servir_lanza_y_siempre_detiene(self, monkeypatch):
        eventos = []
        monkeypatch.setattr(despachador, "_lanzar_carriles", lambda: eventos.append("lanzar"))
        monkeypatch.setattr(despachador, "detener", lambda: eventos.append("detener"))

        despachador.servir()  # sin hilos vivos, sale enseguida

        assert eventos == ["lanzar", "detener"]


class TestArrancar:
    @pytest.fixture
    def habilitado(self, settings, monkeypatch):
        settings.CONVERSION_DISPATCHER_ENABLED = True
        monkeypatch.delenv("RUN_MAIN", raising=False)
        lanzados = []
        monkeypatch.setattr(despachador, "_lanzar_carriles", lambda: lanzados.append(1))
        monkeypatch.setattr(retencion, "barrer", lambda: SimpleNamespace(bytes_liberados=0))
        return lanzados

    def test_apagado_en_la_configuracion_no_arranca(self, settings, habilitado):
        settings.CONVERSION_DISPATCHER_ENABLED = False
        assert despachador.arrancar() is False
        assert not habilitado

    def test_el_vigilante_del_recargador_no_arranca(self, habilitado, monkeypatch):
        monkeypatch.setenv("RUN_MAIN", "false")
        assert despachador.arrancar() is False
        assert not habilitado

    def test_con_hilos_vivos_no_arranca_otros(self, habilitado, monkeypatch):
        monkeypatch.setattr(despachador, "vivo", lambda: True)
        assert despachador.arrancar() is False
        assert not habilitado

    def test_arranca_y_barre_antes(self, habilitado, monkeypatch):
        barridos = []
        monkeypatch.setattr(retencion, "barrer", lambda: barridos.append(1))
        assert despachador.arrancar() is True
        assert habilitado == [1] and barridos == [1]

    def test_un_barrido_fallido_no_impide_arrancar(self, habilitado, monkeypatch, caplog):
        def roto():
            raise OSError("disco")

        monkeypatch.setattr(retencion, "barrer", roto)
        assert despachador.arrancar() is True
        assert habilitado == [1]
        assert "barrido de arranque fallo" in caplog.text
