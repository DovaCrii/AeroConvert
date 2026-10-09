"""Convierte una altura entre elipsoidal y ortométrica con un modelo de geoide declarado (F15.2).

Sirve, por ejemplo, para la base de un PPK: TBC suele exportar la altura ortométrica y RTKLIB
pide la elipsoidal. **El modelo no tiene valor por omisión**: hay que decirlo con `--modelo`.
Sin la grilla en esta máquina no calcula y dice por qué (`sin-grilla-geoide`); nunca la descarga.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.formats import alturas
from apps.formats.crs import CrsInvalido, PuntoConCrs, validar_declarado


class Command(BaseCommand):
    help = "Convierte una altura elipsoidal u ortométrica con un modelo de geoide declarado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--este", type=float, required=True, help="X o longitud, en m o grados."
        )
        parser.add_argument("--norte", type=float, required=True, help="Y o latitud.")
        parser.add_argument(
            "--crs", default="", help="EPSG de la posición horizontal (sin valor por omisión)."
        )
        parser.add_argument("--altura", type=float, required=True, help="Altura en metros.")
        parser.add_argument(
            "--sentido", choices=alturas.SENTIDOS, required=True, help="Qué tipo es la entrada."
        )
        parser.add_argument(
            "--modelo", default="", help=f"Modelo de geoide: {', '.join(alturas.MODELOS)}."
        )

    def handle(self, *args, **o):
        try:
            crs = validar_declarado(o["crs"])
            punto = PuntoConCrs(o["este"], o["norte"], crs, z_m=o["altura"])
            r = alturas.convertir(punto, modelo=o["modelo"], sentido=o["sentido"])
        except CrsInvalido as fallo:
            raise CommandError(f"{fallo.codigo}: {fallo}") from fallo
        except alturas.AlturaError as fallo:
            raise CommandError(f"{fallo.codigo}: {fallo}") from fallo
        self.stdout.write(f"{r.recibo}")
        self.stdout.write(f"Altura resultante: {r.punto.z_m:.3f} m")
