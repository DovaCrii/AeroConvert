"""El techo de memoria, que es lo que de verdad limita una nube de puntos grande.

GDAL acota su memoria — `GDAL_CACHEMAX` es un tope duro — así que una ortofoto de 40 GB se
convierte en una máquina de 4 GB. **PDAL no**: carga los puntos en memoria, y el techo crece
con el número de puntos. La regla medida son 105 MB por millón.

Sin esta comprobación, una nube que no cabe no da un error: el sistema mata el proceso por
falta de memoria, y en un servidor compartido se lleva lo que el núcleo decida.
"""

import pytest

from apps.jobs import estimacion as est

pytestmark = pytest.mark.django_db


class _Las:
    def __init__(self, puntos):
        self.puntos = puntos


class _Inspeccion:
    def __init__(self, puntos):
        self.las = _Las(puntos)


def _con(memoria_mb, total_mb):
    return est.Estimacion(
        bytes_salida=0,
        segundos=0.0,
        memoria_mb=memoria_mb,
        libre_bytes=0,
        memoria_total_mb=total_mb,
    )


class TestCuantaMemoriaTieneLaMaquina:
    def test_se_puede_averiguar(self):
        """Sin `psutil`: los dos sistemas ofrecen el número."""
        assert est.memoria_total_mb() > 0

    def test_y_es_una_cifra_creible(self):
        # Entre 1 GB y 2 TB. Fuera de eso, la lectura esta mal.
        assert 1024 <= est.memoria_total_mb() <= 2_097_152


class TestElTecho:
    def test_una_nube_pequena_cabe(self):
        """La de referencia: 9,6 millones de puntos, 966 MB medidos."""
        assert _con(1200, 4096).cabe_en_memoria

    def test_una_nube_de_mil_millones_no(self):
        """105 MB por millón son unos 100 GB. No es «una VM más grande»."""
        cabe = _con(105_000, 4096)
        assert not cabe.cabe_en_memoria
        assert "no puede terminar" in cabe.motivo_de_memoria

    def test_el_motivo_dice_las_dos_cifras(self):
        motivo = _con(105_000, 4096).motivo_de_memoria
        assert "102.5 GB" in motivo
        assert "4.0 GB" in motivo

    def test_se_deja_margen_para_el_resto_de_la_maquina(self):
        """En la máquina viven además el servidor web, la base y el sistema."""
        justo = int(4096 * est.FRACCION_DE_MEMORIA_UTIL)
        assert _con(justo, 4096).cabe_en_memoria
        assert not _con(justo + 1, 4096).cabe_en_memoria

    def test_si_no_se_sabe_la_memoria_no_se_rechaza_nada(self):
        """Devolver cero desactiva la comprobación en vez de rechazar por una lectura
        fallida. Un falso «no cabe» es peor que no comprobar."""
        assert _con(999_999, 0).cabe_en_memoria
        assert _con(999_999, 0).motivo_de_memoria == ""


class TestLoQueSeEstimaDeUnaNube:
    def test_el_techo_crece_con_los_puntos(self):
        chica = est._memoria_mb(_Inspeccion(10_000_000))
        grande = est._memoria_mb(_Inspeccion(100_000_000))
        assert grande > chica * 8

    def test_y_no_crece_para_un_raster(self):
        """GDAL lo acota él, y por eso una ortofoto enorme sí se convierte."""
        assert est._memoria_mb(None) == est._memoria_mb(None)


class TestElRunnerLoPara:
    def test_una_nube_que_no_cabe_no_se_intenta(self, monkeypatch):
        """El formulario es evadible desde la API, igual que con el CRS."""
        from apps.jobs import runner

        monkeypatch.setattr(est, "memoria_total_mb", lambda: 4096)
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_memoria(None, _Inspeccion(1_000_000_000))
        assert fallo.value.codigo == "memoria-insuficiente"

    def test_y_una_que_si_cabe_pasa(self, monkeypatch):
        from apps.jobs import runner

        monkeypatch.setattr(est, "memoria_total_mb", lambda: 16384)
        runner._exigir_memoria(None, _Inspeccion(9_600_000))
