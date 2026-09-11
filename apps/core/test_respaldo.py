"""El respaldo de la base.

La prueba que importa no es que el comando escriba un archivo: es que **el archivo que
escribe se pueda abrir y tenga lo que tenía que tener**. Un respaldo que nadie ha abierto es
una suposición, y el día que se necesita ya es tarde para comprobarlo.
"""

import gzip
import sqlite3

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.jobs.models import ConversionJob

# **`transaction=True` y no el `django_db` de siempre.** La API de respaldo de SQLite copia
# desde una base viva y espera a que no haya una escritura a medias; envuelta en la
# transacción que pytest abre alrededor de cada prueba, esperaría para siempre contra su
# propio hilo. Y probar un respaldo contra una base que no se comporta como la de verdad no
# probaría gran cosa.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def con_trabajos():
    duena = get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    for numero in range(3):
        ConversionJob.objects.create(
            owner=duena,
            source_path=f"/mnt/entregas/orto{numero}.tif",
            source_name=f"orto{numero}.tif",
            target_format_code="cog",
        )
    return duena


def _abrir(comprimido, carpeta):
    """Descomprime y abre la copia, que es la única prueba que vale."""
    suelto = carpeta / "abierto.sqlite3"
    with gzip.open(comprimido, "rb") as entrada:
        suelto.write_bytes(entrada.read())
    return sqlite3.connect(suelto)


class TestElRespaldo:
    def test_se_escribe_y_se_puede_abrir(self, con_trabajos, tmp_path):
        call_command("respaldar", carpeta=str(tmp_path))
        copias = list(tmp_path.glob("aeroconvert-*.sqlite3.gz"))
        assert len(copias) == 1

        conexion = _abrir(copias[0], tmp_path)
        try:
            assert conexion.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conexion.close()

    def test_y_trae_las_mismas_filas(self, con_trabajos, tmp_path):
        """Lo que de verdad se está respaldando son los recibos."""
        call_command("respaldar", carpeta=str(tmp_path))
        copia = next(tmp_path.glob("aeroconvert-*.sqlite3.gz"))

        conexion = _abrir(copia, tmp_path)
        try:
            cuantos = conexion.execute("SELECT COUNT(*) FROM jobs_conversionjob").fetchone()[0]
        finally:
            conexion.close()
        assert cuantos == ConversionJob.objects.count() == 3

    def test_no_pisa_uno_anterior(self, con_trabajos, tmp_path):
        """`VACUUM INTO` falla si el destino existe, y eso es una virtud: nunca se pierde un
        respaldo bueno por lanzar el comando dos veces."""
        import time

        call_command("respaldar", carpeta=str(tmp_path))
        time.sleep(1.1)  # el nombre lleva los segundos
        call_command("respaldar", carpeta=str(tmp_path))
        assert len(list(tmp_path.glob("aeroconvert-*.sqlite3.gz"))) == 2

    def test_no_lo_puede_leer_cualquiera(self, con_trabajos, tmp_path):
        """Contiene la bitácora entera de la oficina."""
        import os
        import stat

        if os.name == "nt":
            pytest.skip("los modos POSIX no significan lo mismo en Windows")

        call_command("respaldar", carpeta=str(tmp_path))
        copia = next(tmp_path.glob("aeroconvert-*.sqlite3.gz"))
        assert stat.S_IMODE(copia.stat().st_mode) == 0o600

    def test_simular_no_escribe_nada(self, con_trabajos, tmp_path):
        call_command("respaldar", carpeta=str(tmp_path), simular=True)
        assert list(tmp_path.glob("*.gz")) == []


class TestLaVerificacion:
    def test_una_copia_rota_se_detecta(self, con_trabajos, tmp_path, monkeypatch):
        """El paso que convierte «se escribió un archivo» en «hay un respaldo»."""
        from apps.core.management.commands import respaldar as mandato

        def mentir(self, base):
            return 99

        monkeypatch.setattr(mandato.Command, "_contar", mentir)
        with pytest.raises(CommandError, match="trabajos"):
            call_command("respaldar", carpeta=str(tmp_path))


class TestLaPoda:
    def test_se_borran_los_viejos(self, con_trabajos, tmp_path):
        import os
        import time

        antiguo = tmp_path / "aeroconvert-20200101-000000.sqlite3.gz"
        antiguo.write_bytes(b"finge que soy viejo")
        hace_mucho = time.time() - 30 * 86400
        os.utime(antiguo, (hace_mucho, hace_mucho))

        call_command("respaldar", carpeta=str(tmp_path), dias=14)
        assert not antiguo.exists()
        assert len(list(tmp_path.glob("aeroconvert-*.sqlite3.gz"))) == 1

    def test_y_no_los_recientes(self, con_trabajos, tmp_path):
        reciente = tmp_path / "aeroconvert-20990101-000000.sqlite3.gz"
        reciente.write_bytes(b"de ayer")
        call_command("respaldar", carpeta=str(tmp_path), dias=14)
        assert reciente.exists()
