"""El lector de RINEX y su escáner de épocas.

Los archivos son sintéticos (`constructor.rinex_minimo()`). Lo que se vigila es lo que el
verificador de la conversión va a necesitar: que la cabecera se lea entera, que las épocas
se cuenten igual en RINEX 2 que en RINEX 3 y 4, que un hueco se vea como hueco, y que un
archivo cortado a mitad de una época se diga cortado en vez de contarlo bueno.
"""

from datetime import datetime

import pytest

from apps.formats import rinex
from apps.formats.tests.constructor import rinex_minimo


def _escribir(tmp_path, texto: str, nombre="x.rnx"):
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="latin-1", newline="")
    return ruta


def _resumen(tmp_path, **opciones):
    ruta = _escribir(tmp_path, rinex_minimo(**opciones))
    return rinex.resumir_epocas(ruta, rinex.leer_cabecera(ruta))


class TestLaCabecera:
    def test_rinex_3(self, tmp_path):
        cabecera = rinex.leer_cabecera(_escribir(tmp_path, rinex_minimo(version="3.04")))
        assert cabecera.version == 3.04
        assert cabecera.es_observacion
        assert not cabecera.es_v2
        assert cabecera.marcador == "GMLA"
        assert cabecera.receptor == "TRIMBLE NETR9"
        assert cabecera.antena == "TRM57971.00 NONE"  # el tipo y, detrás, el radomo
        assert cabecera.intervalo_s == 30.0
        assert cabecera.primera_epoca == datetime(2023, 1, 31, 17, 0, 0)
        assert cabecera.posicion_aproximada_m == (1948450.2, -5475860.9, -2656160.3)

    def test_los_tipos_de_observacion_van_por_sistema(self, tmp_path):
        cabecera = rinex.leer_cabecera(_escribir(tmp_path, rinex_minimo(version="3.04")))
        assert cabecera.tipos_de_observacion["G"] == ("C1C", "L1C", "D1C", "S1C")
        assert cabecera.constelaciones == ("G", "R")

    def test_rinex_2(self, tmp_path):
        cabecera = rinex.leer_cabecera(_escribir(tmp_path, rinex_minimo(version="2.11")))
        assert cabecera.version == 2.11
        assert cabecera.es_v2
        assert cabecera.tipos_de_observacion["*"] == ("C1", "L1", "D1", "S1")
        assert cabecera.numero_de_tipos == 4

    def test_rinex_4(self, tmp_path):
        cabecera = rinex.leer_cabecera(_escribir(tmp_path, rinex_minimo(version="4.00")))
        assert cabecera.version == 4.0
        assert rinex.version_conocida(cabecera.version)

    def test_una_posicion_a_cero_es_no_saberla(self, tmp_path):
        texto = rinex_minimo().replace("  1948450.2000 -5475860.9000 -2656160.3000", " " * 42)
        texto = texto.replace(
            " " * 42 + " " * 18 + "APPROX POSITION XYZ",
            "         0.0000          0.0000          0.0000".ljust(60) + "APPROX POSITION XYZ",
        )
        cabecera = rinex.leer_cabecera(_escribir(tmp_path, texto))
        assert cabecera.posicion_aproximada_m is None

    def test_con_saltos_de_linea_de_windows(self, tmp_path):
        ruta = _escribir(tmp_path, rinex_minimo(fin_de_linea="\r\n"))
        assert rinex.leer_cabecera(ruta).marcador == "GMLA"
        assert rinex.resumir_epocas(ruta, rinex.leer_cabecera(ruta)).epocas == 5

    def test_las_versiones_futuras_no_se_dan_por_conocidas(self):
        assert not rinex.version_conocida(5.0)
        assert not rinex.version_conocida(1.0)


class TestLoQueNoEsUnRinex:
    def test_texto_cualquiera(self, tmp_path):
        with pytest.raises(rinex.NoEsRinex):
            rinex.leer_cabecera(_escribir(tmp_path, "esto no es un rinex\n" * 5))

    def test_un_archivo_vacio(self, tmp_path):
        with pytest.raises(rinex.NoEsRinex):
            rinex.leer_cabecera(_escribir(tmp_path, ""))

    def test_sin_fin_de_cabecera(self, tmp_path):
        """El convertidor que murió escribiendo la cabecera."""
        texto = rinex_minimo(con_fin_de_cabecera=False)
        with pytest.raises(rinex.NoEsRinex, match="END OF HEADER"):
            rinex.leer_cabecera(_escribir(tmp_path, texto))

    def test_comprimido_en_hatanaka_se_dice(self, tmp_path):
        # Tal como la escribe `rnx2crx`: la versión y «COMPACT RINEX FORMAT», y la etiqueta.
        texto = "3.0                 COMPACT RINEX FORMAT".ljust(60) + "CRINEX VERS   / TYPE\n"
        with pytest.raises(rinex.NoEsRinex, match="Hatanaka"):
            rinex.leer_cabecera(_escribir(tmp_path, texto))

    def test_una_navegacion_no_se_cuenta_en_epocas(self, tmp_path):
        texto = rinex_minimo().replace("OBSERVATION DATA    M", "NAVIGATION DATA     M")
        ruta = _escribir(tmp_path, texto)
        with pytest.raises(rinex.NoEsRinex, match="observación"):
            rinex.resumir_epocas(ruta, rinex.leer_cabecera(ruta))


@pytest.mark.parametrize("version", ["2.11", "3.04", "4.00"])
class TestLasEpocas:
    def test_las_cuenta_todas(self, tmp_path, version):
        resumen = _resumen(tmp_path, version=version, epocas=5)
        assert resumen.epocas == 5
        assert resumen.primera == datetime(2023, 1, 31, 17, 0, 0)
        assert resumen.ultima == datetime(2023, 1, 31, 17, 2, 0)
        assert resumen.intervalo_s == 30.0
        assert resumen.satelites_maximos == 3
        assert resumen.total_de_huecos == 0
        assert not resumen.truncado

    def test_dice_cuantas_esperaba(self, tmp_path, version):
        assert _resumen(tmp_path, version=version, epocas=5).esperadas == 5

    def test_un_hueco_se_ve_como_hueco(self, tmp_path, version):
        resumen = _resumen(tmp_path, version=version, epocas=6, huecos_en=(2,))
        assert resumen.epocas == 5
        assert resumen.total_de_huecos == 1
        assert resumen.huecos == (
            (datetime(2023, 1, 31, 17, 0, 30), datetime(2023, 1, 31, 17, 1, 30)),
        )
        # Cinco leídas y seis esperadas: la diferencia es exactamente lo que falta.
        assert resumen.esperadas == 6

    def test_el_intervalo_es_el_mas_repetido_y_no_el_primero(self, tmp_path, version):
        """Con un hueco al principio, el primer salto no es el intervalo."""
        resumen = _resumen(tmp_path, version=version, epocas=8, huecos_en=(1, 2))
        assert resumen.intervalo_s == 30.0

    def test_un_archivo_cortado_a_mitad_de_una_epoca_se_dice(self, tmp_path, version):
        resumen = _resumen(tmp_path, version=version, epocas=5, truncar_la_ultima=True)
        assert resumen.truncado
        assert resumen.epocas == 4, "la época incompleta no se cuenta como buena"

    def test_con_saltos_de_linea_de_windows(self, tmp_path, version):
        assert _resumen(tmp_path, version=version, fin_de_linea="\r\n").epocas == 5


class TestLosEventos:
    def test_un_evento_no_es_una_observacion(self, tmp_path):
        """El indicador mayor que 1 abre registros que no son satélites."""
        base = rinex_minimo(version="3.04", epocas=3).split("\n")
        fin = next(n for n, linea in enumerate(base) if "END OF HEADER" in linea)
        evento = [
            "> 2023 01 31 17 00 45.0000000  4  1",
            "*** cambio de antena ***".ljust(60) + "COMMENT",
        ]
        texto = "\n".join(base[: fin + 1] + evento + base[fin + 1 :])
        ruta = _escribir(tmp_path, texto)
        resumen = rinex.resumir_epocas(ruta, rinex.leer_cabecera(ruta))
        assert resumen.eventos == 1
        assert resumen.epocas == 3


class TestLaMemoriaNoCreceConElArchivo:
    def test_los_saltos_distintos_tienen_tope(self, tmp_path, monkeypatch):
        """Un archivo corrupto puede inventarse un salto distinto por época."""
        monkeypatch.setattr(rinex, "SALTOS_DISTINTOS_MAXIMOS", 2)
        cabecera = rinex_minimo(version="3.04", epocas=0)
        cuerpo = ""
        for segundos in (0, 7, 19, 40, 91, 200):
            cuerpo += f"> 2023 01 31 17 {segundos // 60:02d} {segundos % 60:02d}.0000000  0  1\n"
            cuerpo += "G01" + "  20000000.000  " * 4 + "\n"
        ruta = _escribir(tmp_path, cabecera + cuerpo)
        resumen = rinex.resumir_epocas(ruta, rinex.leer_cabecera(ruta))
        assert resumen.epocas == 6

    def test_los_huecos_guardados_tienen_tope(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rinex, "HUECOS_GUARDADOS", 3)
        # Faltan dos épocas de cada diez: el intervalo habitual sigue siendo 30 s y hay seis
        # huecos de 90 s. (Si faltaran dos de cada tres, el hueco pasaría a ser lo normal.)
        faltan = tuple(n for n in range(60) if n % 10 in (4, 5))
        resumen = _resumen(tmp_path, version="3.04", epocas=60, huecos_en=faltan)
        assert resumen.intervalo_s == 30.0
        assert resumen.total_de_huecos == 6
        assert len(resumen.huecos) == 3
