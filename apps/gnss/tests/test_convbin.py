"""El motor abierto, RTKLIB `convbin`: el plan, la sonda y el veredicto, sin el programa.

El `argv` se compara entero y en orden, como en el motor de Trimble. Lo que no se prueba aquí es
una conversión de verdad de un flujo UBX, SBF o RT17: **no hay uno en esta máquina**. Sí se midió,
a mano y con el `convbin` que trae Trimble Business Center, la ruta RINEX a RINEX 2.11 (3.600
épocas, leídas con `rinex.py`); está en `docs/PRUEBAS_CON_ORACULO.md`.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.engines import sondas
from apps.engines.base import ParDeFormatos
from apps.formats.tests.constructor import rinex_minimo
from apps.gnss import motores

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def entorno(tmp_path, settings):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.RTKLIB_CONVBIN = "/usr/bin/convbin"


def _trabajo(tmp_path, formato="ubx", nombre="medida.ubx", **opciones):
    origen = tmp_path / nombre
    origen.write_bytes(b"\xb5\x62" + bytes(100))
    return SimpleNamespace(
        pk="0f5a",
        source_format=formato,
        source_path=str(origen),
        source_size_bytes=origen.stat().st_size,
        output_path=str(tmp_path / "medida_rinex.zip"),
        options=opciones,
    )


def _carpeta(tmp_path) -> str:
    return str(tmp_path / "trabajo" / "0f5a.parcial.rinex")


class TestElPar:
    def test_declara_los_siete_flujos_y_el_rinex_hacia_rinex(self):
        pares = motores.MotorRtklibConvbin().pares()
        assert pares == {
            ParDeFormatos(origen, "rinex")
            for origen in ("rtcm3", "ubx", "novatel", "sbf", "rt17", "binex", "javad", "rinex_obs")
        }

    def test_un_rinex_se_reescribe_en_otra_version_y_nunca_en_si_mismo(self):
        """El destino es `rinex` (un zip) y el origen `rinex_obs`: ninguna celda repite formato."""
        assert all(p.origen != p.destino for p in motores.MotorRtklibConvbin().pares())

    def test_no_declara_el_archivo_de_campo_de_trimble(self):
        """RTKLIB no lee T02 ni T04, y decirlo mal sería prometer lo que no hace."""
        assert ParDeFormatos("trimble_t0x", "rinex") not in motores.MotorRtklibConvbin().pares()

    def test_cada_formato_del_catalogo_tiene_su_letra_de_convbin(self):
        from apps.formats import catalogo

        for codigo in motores.FORMATO_DE_CONVBIN:
            assert catalogo.formato(codigo).familia == catalogo.GNSS


class TestLaSonda:
    def test_sin_convbin_lo_dice_con_su_motivo(self, monkeypatch):
        monkeypatch.setattr(sondas, "ruta_de_rtklib", lambda: "")
        estado = sondas.sondar_rtklib()
        assert not estado.disponible
        assert estado.codigo_motivo == "sin-rtklib"
        assert "apt install rtklib" in estado.sugerencia

    def test_una_ruta_que_no_existe(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sondas, "ruta_de_rtklib", lambda: str(tmp_path / "no"))
        assert sondas.sondar_rtklib().codigo_motivo == "sin-rtklib"

    def test_una_ruta_que_existe(self, monkeypatch, tmp_path):
        exe = tmp_path / "convbin"
        exe.write_bytes(b"")
        monkeypatch.setattr(sondas, "ruta_de_rtklib", lambda: str(exe))
        assert sondas.sondar_rtklib().disponible

    def test_lo_configurado_gana_al_path(self, settings):
        settings.RTKLIB_CONVBIN = '"D:\\rtklib\\convbin.exe"'
        assert sondas.ruta_de_rtklib() == "D:\\rtklib\\convbin.exe"


class TestElPlan:
    def test_argv_completo_y_en_orden(self, tmp_path):
        plan = motores.MotorRtklibConvbin().plan(_trabajo(tmp_path))
        assert plan.argv == (
            "/usr/bin/convbin",
            "-r",
            "ubx",
            "-v",
            "3.04",
            "-d",
            _carpeta(tmp_path),
            str(tmp_path / "medida.ubx"),
        )

    def test_con_todas_las_opciones(self, tmp_path):
        trabajo = _trabajo(tmp_path, version="2.11", doppler=True, snr=True, marcador="BASE-1")
        assert motores.MotorRtklibConvbin().plan(trabajo).argv == (
            "/usr/bin/convbin",
            "-r",
            "ubx",
            "-v",
            "2.11",
            "-d",
            _carpeta(tmp_path),
            "-od",
            "-os",
            "-hm",
            "BASE-1",
            str(tmp_path / "medida.ubx"),
        )

    def test_un_rinex_de_entrada_va_con_menos_r_rinex_y_la_version_pedida(self, tmp_path):
        trabajo = _trabajo(tmp_path, formato="rinex_obs", nombre="a.23o", version="2.11")
        assert motores.MotorRtklibConvbin().plan(trabajo).argv == (
            "/usr/bin/convbin",
            "-r",
            "rinex",
            "-v",
            "2.11",
            "-d",
            _carpeta(tmp_path),
            str(tmp_path / "a.23o"),
        )

    def test_novatel_se_llama_nov_para_convbin(self, tmp_path):
        trabajo = _trabajo(tmp_path, formato="novatel", nombre="a.gps")
        assert motores.MotorRtklibConvbin().plan(trabajo).argv[2] == "nov"

    def test_la_fecha_aproximada_solo_va_con_rtcm3(self, tmp_path):
        fecha = "2026/10/05 12:00:00"
        rtcm = _trabajo(tmp_path, formato="rtcm3", nombre="a.rtcm3", fecha_aproximada=fecha)
        assert "-tr" in motores.MotorRtklibConvbin().plan(rtcm).argv
        ubx = _trabajo(tmp_path, fecha_aproximada=fecha)
        assert "-tr" not in motores.MotorRtklibConvbin().plan(ubx).argv

    @pytest.mark.parametrize("fecha", ["ayer", "2026-10-05", "2026/10/05 12:00:00; rm -rf /"])
    def test_una_fecha_mal_escrita_no_llega_al_argv(self, tmp_path, fecha):
        trabajo = _trabajo(tmp_path, formato="rtcm3", nombre="a.rtcm3", fecha_aproximada=fecha)
        with pytest.raises(ValueError, match="AAAA/MM/DD"):
            motores.MotorRtklibConvbin().plan(trabajo)

    @pytest.mark.parametrize("marcador", ["-ts", "a b", "x;y"])
    def test_un_marcador_que_se_leeria_como_opcion_se_rechaza(self, tmp_path, marcador):
        with pytest.raises(ValueError, match="nombre del punto"):
            motores.MotorRtklibConvbin().plan(_trabajo(tmp_path, marcador=marcador))

    def test_una_version_que_no_se_ofrece(self, tmp_path):
        with pytest.raises(ValueError, match="no es una versión"):
            motores.MotorRtklibConvbin().plan(_trabajo(tmp_path, version="9.99"))

    def test_un_formato_que_rtklib_no_lee(self, tmp_path):
        with pytest.raises(ValueError, match="no sabe leer"):
            motores.MotorRtklibConvbin().plan(_trabajo(tmp_path, formato="trimble_t0x"))

    def test_el_segundo_paso_empaqueta_la_carpeta(self, tmp_path):
        plan = motores.MotorRtklibConvbin().plan(_trabajo(tmp_path))
        assert plan.salida_en_posteriores is True
        assert plan.posteriores[0][:3] == (sys.executable, "-m", "apps.gnss.empaquetar")
        assert plan.emite_progreso is False


class TestElVeredicto:
    """Lo escribe `convbin` y lo lee `rinex.py`: dos analizadores distintos."""

    def _zip(self, tmp_path: Path, archivos: dict[str, str]) -> Path:
        ruta = tmp_path / "medida_rinex.parcial.zip"
        with zipfile.ZipFile(ruta, "w") as paquete:
            for nombre, contenido in archivos.items():
                paquete.writestr(nombre, contenido)
        return ruta

    def test_un_rinex_bueno_pasa_y_dice_con_que_se_verifico(self, tmp_path):
        salida = self._zip(tmp_path, {"medida.obs": rinex_minimo(version="3.04", epocas=10)})
        veredicto = motores.MotorRtklibConvbin().verificar(_trabajo(tmp_path), salida)
        assert veredicto.correcta
        assert "RTKLIB convbin" in veredicto.detalles["verificado_con"]
        assert veredicto.detalles["epocas"] == 10

    def test_el_veredicto_trae_la_calidad_y_cabe_en_json(self, tmp_path):
        import json

        salida = self._zip(tmp_path, {"medida.obs": rinex_minimo(version="3.04", epocas=10)})
        veredicto = motores.MotorRtklibConvbin().verificar(_trabajo(tmp_path), salida)
        calidad = veredicto.detalles["calidad"]
        assert calidad["satelites_maximo"] == 3
        assert calidad["porcentaje_completo"] == 100.0
        assert calidad["satelites_con_poca_presencia"] == []
        json.dumps(veredicto.detalles)  # el recibo se guarda como JSON

    def test_un_satelite_que_aparece_poco_se_nombra(self, tmp_path):
        """R05 sale en la mitad de las épocas: el recibo lo dice por su nombre."""
        resultado: list[str] = []
        epoca = -1
        for linea in rinex_minimo(version="3.04", epocas=10).split("\n"):
            if linea.startswith(">"):
                epoca += 1
                if epoca % 2:  # la cabecera de la época dice cuántos satélites hay: 3 a 2
                    linea = linea[:-1] + "2"
            elif linea.startswith("R05") and epoca % 2:
                continue
            resultado.append(linea)
        salida = self._zip(tmp_path, {"medida.obs": "\n".join(resultado)})
        veredicto = motores.MotorRtklibConvbin().verificar(_trabajo(tmp_path), salida)
        assert veredicto.correcta, veredicto.motivo
        bajos = veredicto.detalles["calidad"]["satelites_con_poca_presencia"]
        assert [s["id"] for s in bajos] == ["R05"]
        assert bajos[0]["porcentaje"] == 50.0

    def test_una_conversion_sin_epocas_no_pasa_aunque_convbin_saliera_con_cero(self, tmp_path):
        """La regla 1: un flujo que no era lo que decía deja una cabecera sola."""
        salida = self._zip(tmp_path, {"medida.obs": rinex_minimo(version="3.04", epocas=0)})
        veredicto = motores.MotorRtklibConvbin().verificar(_trabajo(tmp_path), salida)
        assert not veredicto.correcta
        assert veredicto.codigo_motivo == "rinex-sin-epocas"

    def test_otra_version_de_la_pedida_no_pasa(self, tmp_path):
        salida = self._zip(tmp_path, {"medida.obs": rinex_minimo(version="2.11", epocas=10)})
        veredicto = motores.MotorRtklibConvbin().verificar(_trabajo(tmp_path), salida)
        assert veredicto.codigo_motivo == "rinex-invalido"


class TestElRegistro:
    def test_el_registro_trae_los_dos_motores_gnss(self):
        from apps.engines import registry

        ids = {motor.id for motor in registry.todos() if motor.familia == "gnss"}
        assert ids == {"trimble-rinex", "rtklib-convbin"}

    def test_el_motivo_esta_en_el_catalogo(self):
        from apps.jobs import motivos

        assert "sin-rtklib" in motivos.MOTIVOS
