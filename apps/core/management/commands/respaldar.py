"""Respalda la base, en caliente y de forma correcta.

## Por qué no es un `cp`

Con WAL —y la base corre con WAL, porque el despachador escribe progreso mientras el
navegador sondea— el estado real es `db.sqlite3` **más** `db.sqlite3-wal`. Entonces:

- `cp db.sqlite3 copia` entrega la foto del último punto de control. La copia abre, es
  válida, y le faltan las últimas horas **sin decirlo**.
- `cp db.sqlite3*` toma los tres archivos en instantes distintos mientras alguien escribe, y
  puede producir un conjunto incoherente.

Las dos formas producen un respaldo que solo falla el día que hace falta.

Se usa **la API de respaldo en línea de SQLite** (`Connection.backup`), que está hecha
exactamente para esto: copia página a página desde una base viva, es consistente con el WAL, y
no exige parar a nadie. La otra opción correcta sería `VACUUM INTO`, y se descartó porque no
puede correr dentro de una transacción — lo que la deja sin poder probarse.

## Y por qué se verifica

Un respaldo que nadie ha abierto no es un respaldo. Este se reabre, se le pasa
`PRAGMA integrity_check` y se cuentan los trabajos para contrastarlos con el origen. Si no
cuadra, el comando falla **ruidosamente**, que es el único momento útil para enterarse.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

#: Cuantos dias se guardan. Catorce: suficiente para notar que algo se rompio hace una
#: semana, y poco para que no crezca sin fin.
DIAS_POR_OMISION = 14


class Command(BaseCommand):
    help = "Copia la base de datos, la verifica y poda las copias viejas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--carpeta",
            default=None,
            help="Donde dejarlo. Por omision, AEROCONVERT_RESPALDOS o <repo>/respaldos.",
        )
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help=f"Cuantos dias se conservan. Por omision {DIAS_POR_OMISION}.",
        )
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Decir que haria, sin escribir nada.",
        )

    def handle(self, *args, **opciones):
        carpeta = Path(
            opciones["carpeta"]
            or getattr(settings, "CARPETA_DE_RESPALDOS", "")
            or Path(settings.BASE_DIR) / "respaldos"
        )
        dias = opciones["dias"] or getattr(settings, "RESPALDOS_DIAS", DIAS_POR_OMISION)
        origen = Path(connection.settings_dict["NAME"])

        self.stdout.write(f"Base:    {origen}")
        self.stdout.write(f"Destino: {carpeta}")

        if opciones["simular"]:
            self.stdout.write(f"Se conservarian {dias} dias. No se escribio nada.")
            return

        carpeta.mkdir(parents=True, exist_ok=True)
        sello = timezone.localtime().strftime("%Y%m%d-%H%M%S")
        crudo = carpeta / f"aeroconvert-{sello}.sqlite3"
        # El nombre lleva la marca de tiempo, y ademas se comprueba: **nunca se pisa un
        # respaldo bueno** por lanzar el comando dos veces.
        if crudo.exists() or crudo.with_suffix(".sqlite3.gz").exists():
            raise CommandError(f"Ya hay un respaldo de este segundo: {crudo.name}")

        connection.ensure_connection()
        destino = sqlite3.connect(crudo)
        try:
            connection.connection.backup(destino)
        finally:
            destino.close()

        trabajos_origen = self._contar(origen)
        self._verificar(crudo, trabajos_origen)

        comprimido = crudo.with_suffix(".sqlite3.gz")
        with open(crudo, "rb") as entrada, gzip.open(comprimido, "wb") as salida:
            shutil.copyfileobj(entrada, salida)
        crudo.unlink()
        # Contiene la bitacora entera de la oficina: nadie mas que su dueno.
        comprimido.chmod(0o600)

        megas = comprimido.stat().st_size / 1_048_576
        self.stdout.write(
            self.style.SUCCESS(
                f"{comprimido.name}: {megas:.1f} MB, {trabajos_origen} trabajos, integridad ok."
            )
        )
        self._podar(carpeta, dias)

    def _contar(self, base: Path) -> int:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM jobs_conversionjob")
            return cursor.fetchone()[0]

    def _verificar(self, copia: Path, trabajos_esperados: int) -> None:
        """Abrirlo y mirarlo. Un respaldo sin verificar es una suposición."""
        try:
            conexion = sqlite3.connect(f"file:{copia}?mode=ro", uri=True)
        except sqlite3.Error as fallo:
            raise CommandError(f"El respaldo no se deja abrir: {fallo}") from fallo

        try:
            veredicto = conexion.execute("PRAGMA integrity_check").fetchone()[0]
            if veredicto != "ok":
                raise CommandError(
                    f"El respaldo no pasa la comprobacion de integridad: {veredicto}"
                )

            copiados = conexion.execute("SELECT COUNT(*) FROM jobs_conversionjob").fetchone()[0]
            if copiados != trabajos_esperados:
                raise CommandError(
                    f"El respaldo tiene {copiados} trabajos y la base {trabajos_esperados}."
                )
        finally:
            conexion.close()

    def _podar(self, carpeta: Path, dias: int) -> None:
        limite = timezone.now().timestamp() - dias * 86400
        borrados = 0
        for viejo in carpeta.glob("aeroconvert-*.sqlite3.gz"):
            try:
                if viejo.stat().st_mtime < limite:
                    viejo.unlink()
                    borrados += 1
            except OSError:  # pragma: no cover
                continue
        if borrados:
            self.stdout.write(f"Podados {borrados} respaldos de mas de {dias} dias.")
