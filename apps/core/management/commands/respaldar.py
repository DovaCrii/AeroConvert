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

## La copia de fuera, que es el único riesgo sin arreglo posible después

Todo lo de arriba escribe en `/var/backups/aeroconvert`, que está **en el mismo disco que la
base**. Un fallo de ese NVMe se lleva la base, los entregables y los respaldos a la vez, y
ese día no hay nada que hacer: los demás riesgos del servidor se arreglan cuando se
descubren, y este no.

`--copiar-a` deja una segunda copia donde se le diga —una unidad de red, un disco externo,
lo que sea que no esté dentro de esta máquina—. **Sin decírselo no hace nada**, porque
elegir dónde vive la segunda copia de la bitácora de la oficina no es una decisión de este
archivo.

Y si la copia de fuera falla, **el comando termina con error aunque la local haya salido
bien**. Es deliberado y tiene su coste: una unidad de red caída deja el servicio marcado
como fallido en `systemctl --failed`. Se prefiere eso a lo contrario, porque un respaldo de
fuera que lleva tres meses sin escribirse y nadie lo sabe es exactamente el mismo desastre
que no tenerlo.
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
            "--copiar-a",
            default=None,
            help=(
                "Una segunda copia FUERA de esta maquina. Por omision, "
                "AEROCONVERT_RESPALDOS_FUERA; vacio, no se hace."
            ),
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
        fuera = str(
            opciones["copiar_a"] or getattr(settings, "CARPETA_DE_RESPALDOS_FUERA", "") or ""
        ).strip()

        self.stdout.write(f"Base:    {origen}")
        self.stdout.write(f"Destino: {carpeta}")
        if fuera:
            self.stdout.write(f"Y fuera: {fuera}")
        else:
            # **No es un detalle de configuracion: es el unico riesgo sin arreglo posible
            # despues.** Se dice en cada ejecucion, para que aparezca en el diario del
            # servicio y alguien lo vea alguna vez.
            self.stdout.write(
                self.style.WARNING(
                    "Sin copia fuera de esta maquina: los respaldos viven en el mismo disco "
                    "que la base. Ver --copiar-a."
                )
            )

        if opciones["simular"]:
            self.stdout.write(f"Se conservarian {dias} dias. No se escribio nada.")
            return

        # **El error que costó semanas de respaldos vacíos.** Bajo `ProtectSystem=strict`,
        # `/opt` es de solo lectura para el propio servicio, así que el destino por omisión
        # —`<repo>/respaldos`— no se puede crear. Sin este mensaje, lo que quedaba en el
        # diario era un rastro de pila con «Read-only file system» y **ninguna mención a
        # dónde estaba intentando escribir ni a por qué no podía**.
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as fallo:
            raise CommandError(
                f"No se puede escribir en {carpeta}: {fallo}. Si esto corre como servicio, "
                "`ProtectSystem=strict` deja todo en solo lectura salvo lo que el propio "
                "servicio declare en `ReadWritePaths` — y el destino tiene que ser uno de "
                "esos. Pásalo con --carpeta, como hace aeroconvert-respaldo.service."
            ) from fallo

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

        # Al final y no antes: lo que se lleva fuera es el archivo ya verificado y
        # comprimido, no uno a medias.
        if fuera:
            self._llevar_fuera(comprimido, Path(fuera), dias)

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

    def _llevar_fuera(self, comprimido: Path, destino: Path, dias: int) -> None:
        """La segunda copia, y **se comprueba que llegó entera**.

        Copiar y no mirar es el fallo clásico de los respaldos de red: la unidad se
        desmonta, el sistema crea alegremente el directorio dentro del punto de montaje
        vacío, y durante meses se escriben copias en el disco local creyendo que están
        fuera. Se compara el tamaño, que es lo barato y basta para cazar eso.

        Un fallo aquí **hace fallar el comando** aunque la copia local esté bien. Ver el
        docstring del módulo: se prefiere un servicio marcado como fallido a un respaldo de
        fuera que lleva tres meses sin escribirse y nadie lo sabe.
        """
        try:
            destino.mkdir(parents=True, exist_ok=True)
            alla = destino / comprimido.name
            shutil.copy2(comprimido, alla)
            aqui_bytes = comprimido.stat().st_size
            alla_bytes = alla.stat().st_size
        except OSError as fallo:
            raise CommandError(
                f"La copia local esta bien, pero no se pudo dejar una fuera en {destino}: {fallo}"
            ) from fallo

        if alla_bytes != aqui_bytes:
            raise CommandError(
                f"La copia de fuera quedo con {alla_bytes} bytes y la de aqui tiene "
                f"{aqui_bytes}. Suele ser la unidad de red desmontada."
            )

        self.stdout.write(self.style.SUCCESS(f"Y una copia fuera, en {alla}."))
        self._podar(destino, dias)

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
