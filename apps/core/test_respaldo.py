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


class TestLaCopiaDeFuera:
    """**El único riesgo del servidor sin arreglo posible después.**

    Los demás se corrigen el día que se descubren. Que se muera el NVMe llevándose la base,
    los entregables y los respaldos a la vez, no: ese día ya no hay nada que hacer.
    """

    def test_se_deja_una_segunda_copia_donde_se_diga(self, con_trabajos, tmp_path):
        aqui, alla = tmp_path / "aqui", tmp_path / "alla"
        call_command("respaldar", carpeta=str(aqui), copiar_a=str(alla))

        copias = list(alla.glob("aeroconvert-*.sqlite3.gz"))
        assert len(copias) == 1
        assert copias[0].name == next(aqui.glob("aeroconvert-*.sqlite3.gz")).name

    def test_y_es_la_verificada_no_una_a_medias(self, con_trabajos, tmp_path):
        """Se lleva fuera el archivo **después** de comprobar su integridad y comprimirlo.
        Copiar primero y verificar después dejaría fuera una copia que no se miró."""
        aqui, alla = tmp_path / "aqui", tmp_path / "alla"
        call_command("respaldar", carpeta=str(aqui), copiar_a=str(alla))

        conexion = _abrir(next(alla.glob("*.gz")), tmp_path)
        try:
            assert conexion.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conexion.execute("SELECT COUNT(*) FROM jobs_conversionjob").fetchone()[0] == 3
        finally:
            conexion.close()

    def test_si_no_se_puede_llevar_fuera_el_comando_falla(self, con_trabajos, tmp_path):
        """**Aunque la copia local esté bien**, y con su coste: una unidad de red caída deja
        el servicio marcado como fallido. Se prefiere eso a un respaldo de fuera que lleva
        tres meses sin escribirse y nadie lo sabe."""
        from apps.core.management.commands import respaldar as mandato

        def no_se_puede(origen, destino, **kwargs):
            raise OSError("la unidad de red no responde")

        aqui = tmp_path / "aqui"
        with pytest.MonkeyPatch.context() as parche:
            parche.setattr(mandato.shutil, "copy2", no_se_puede)
            with pytest.raises(CommandError, match="fuera"):
                call_command("respaldar", carpeta=str(aqui), copiar_a=str(tmp_path / "alla"))

        # Y la local sí quedó: el fallo es de la segunda, y se dice cuál.
        assert list(aqui.glob("aeroconvert-*.sqlite3.gz"))

    def test_una_copia_truncada_no_pasa_por_buena(self, con_trabajos, tmp_path):
        """**El fallo clásico de los respaldos de red**: la unidad se desmonta, el sistema
        crea el directorio dentro del punto de montaje vacío, y durante meses se escriben
        copias en el disco local creyendo que están fuera."""
        from apps.core.management.commands import respaldar as mandato

        def copiar_a_medias(origen, destino, **kwargs):
            from pathlib import Path

            Path(destino).write_bytes(b"solo un trozo")

        with pytest.MonkeyPatch.context() as parche:
            parche.setattr(mandato.shutil, "copy2", copiar_a_medias)
            with pytest.raises(CommandError, match="bytes"):
                call_command(
                    "respaldar", carpeta=str(tmp_path / "aqui"), copiar_a=str(tmp_path / "alla")
                )

    def test_sin_destino_se_avisa_en_cada_ejecucion(self, con_trabajos, tmp_path, capsys):
        """No es un detalle de configuración: es el riesgo que no se puede arreglar
        después. Se dice cada vez, para que aparezca en el diario del servicio."""
        call_command("respaldar", carpeta=str(tmp_path))
        assert "Sin copia fuera" in capsys.readouterr().out

    def test_y_alla_tambien_se_poda(self, con_trabajos, tmp_path):
        """Si no, la unidad de red se llena y deja de aceptar la copia — en silencio y
        justo cuando lleva meses de historia dentro."""
        import os
        import time

        alla = tmp_path / "alla"
        alla.mkdir()
        antiguo = alla / "aeroconvert-20200101-000000.sqlite3.gz"
        antiguo.write_bytes(b"finge que soy viejo")
        hace_mucho = time.time() - 30 * 86400
        os.utime(antiguo, (hace_mucho, hace_mucho))

        call_command("respaldar", carpeta=str(tmp_path / "aqui"), copiar_a=str(alla), dias=14)
        assert not antiguo.exists()


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
