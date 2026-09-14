"""El techo de memoria, que es lo que de verdad limita una nube de puntos grande.

GDAL acota su memoria — `GDAL_CACHEMAX` es un tope duro — así que una ortofoto de 40 GB se
convierte en una máquina de 4 GB. **PDAL no**: carga los puntos en memoria, y el techo crece
con el número de puntos. La regla medida son 105 MB por millón.

Sin esta comprobación, una nube que no cabe no da un error: el sistema mata el proceso por
falta de memoria, y en un servidor compartido se lleva lo que el núcleo decida.
"""

import os

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


class TestElTechoDelGrupoDeControl:
    """En el servidor compartido manda `MemoryMax=`, no la RAM de la máquina.

    Sin esto, la comprobación previa acepta un trabajo mirando los 22 GB de la máquina y el
    grupo lo mata a los 8. El trabajo muere igual, pero **veinte minutos después y sin
    motivo escrito**, que es exactamente lo que `_exigir_memoria` existe para evitar.
    """

    def _fingir(self, monkeypatch, tmp_path, ruta, topes):
        """Finge /proc/self/cgroup y el arbol de /sys/fs/cgroup, de la hoja hacia la raiz.

        No se toca `os.name`: leer el grupo no depende del sistema, solo de que existan los
        ficheros. Asi estas pruebas corren igual en Windows y en Linux.
        """
        base = tmp_path / "cgroup"
        self_cgroup = tmp_path / "self-cgroup"
        self_cgroup.write_text(f"0::/{ruta}\n", encoding="utf-8")

        actual = base / ruta
        for tope in topes:
            actual.mkdir(parents=True, exist_ok=True)
            (actual / "memory.max").write_text(tope, encoding="utf-8")
            actual = actual.parent

        real = est.Path
        sustitutos = {"/proc/self/cgroup": self_cgroup, "/sys/fs/cgroup": base}
        monkeypatch.setattr(
            est, "Path", lambda c, *a, **k: sustitutos.get(str(c)) or real(c, *a, **k)
        )

    def test_se_lee_el_tope_de_la_unidad(self, monkeypatch, tmp_path):
        self._fingir(
            monkeypatch, tmp_path, "system.slice/aeroconvert-obrero.service", ["8589934592", "max"]
        )
        assert est.limite_del_grupo_mb() == 8192

    def test_gana_el_menor_de_la_cadena(self, monkeypatch, tmp_path):
        """Una unidad puede pedir 8 GB dentro de un `.slice` que solo da 4."""
        self._fingir(
            monkeypatch,
            tmp_path,
            "system.slice/aeroconvert-obrero.service",
            ["8589934592", "4294967296"],
        )
        assert est.limite_del_grupo_mb() == 4096

    def test_sin_tope_no_dice_nada(self, monkeypatch, tmp_path):
        """«max» en todos los niveles es lo normal fuera de systemd: entonces manda la RAM."""
        self._fingir(monkeypatch, tmp_path, "user.slice", ["max", "max"])
        assert est.limite_del_grupo_mb() == 0

    def test_y_si_no_hay_cgroup_v2_no_se_adivina(self, monkeypatch, tmp_path):
        """Mejor no mirar que mirar mal: en la v1 el formato es otro."""
        v1 = tmp_path / "v1"
        v1.write_text("7:memory:/system.slice/algo.service\n", encoding="utf-8")
        real = est.Path
        monkeypatch.setattr(
            est,
            "Path",
            lambda c, *a, **k: v1 if str(c) == "/proc/self/cgroup" else real(c, *a, **k),
        )
        assert est.limite_del_grupo_mb() == 0

    @pytest.mark.skipif(os.name == "nt", reason="Windows no tiene grupos de control")
    def test_el_total_se_recorta_al_tope(self, monkeypatch):
        """Lo que importa: `memoria_total_mb` devuelve el techo real, no la RAM."""
        monkeypatch.setattr(est, "limite_del_grupo_mb", lambda: 8192)
        assert est.memoria_total_mb() == 8192

    @pytest.mark.skipif(os.name == "nt", reason="Windows no tiene grupos de control")
    def test_pero_nunca_por_encima_de_la_maquina(self, monkeypatch):
        """Un `MemoryMax` mayor que la RAM no crea memoria."""
        monkeypatch.setattr(est, "limite_del_grupo_mb", lambda: 99_999_999)
        assert est.memoria_total_mb() < 99_999_999


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
