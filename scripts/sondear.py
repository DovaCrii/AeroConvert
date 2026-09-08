"""Imprime que motores ve esta maquina y por que faltan los que faltan.

Se ejecuta con `pwsh scripts/sondear.ps1`, que es solo un envoltorio. La logica vive aqui,
en Python, y no incrustada en el `.ps1`: escapar comillas anidadas dentro de una cadena de
PowerShell es una fuente de errores que no aporta nada.

Es lo primero que hay que mirar cuando una conversion no aparece disponible, y lo que se
pega en un correo a soporte.
"""

import os
import sys
from pathlib import Path

# Python pone en `sys.path` la carpeta del script, no el directorio de trabajo, asi que
# `config` no se encuentra por mucho que `sondear.ps1` haga `Set-Location` a la raiz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django  # noqa: E402


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    django.setup()

    from apps.engines import registry, sondas

    print()
    print("HERRAMIENTAS")
    print("-" * 78)

    gdal = sondas.sondar_gdal()
    if gdal.disponible:
        print(f"  GDAL   OK      {gdal.version}")
        print(f"                 {gdal.ejecutable}")
        print(
            f"                 lee {len(gdal.controladores)} controladores, "
            f"escribe {len(gdal.escribibles)}"
        )
        for clave in ("GTIFF", "COG", "JP2OPENJPEG", "ECW", "MRSID", "HFA", "AAIGRID"):
            if clave in gdal.escribibles:
                estado = "lee y escribe"
            elif clave in gdal.controladores:
                estado = "solo lee"
            else:
                estado = "NO ESTA"
            print(f"                   {clave:<13} {estado}")
    else:
        print(f"  GDAL   FALTA   {gdal.motivo}")

    for etiqueta, sonda in (
        ("PROJ", sondas.sondar_proj),
        ("PDAL", sondas.sondar_pdal),
        ("ECW", sondas.sondar_ecw),
        ("ODA", sondas.sondar_oda),
    ):
        estado = sonda()
        if estado.disponible:
            print(f"  {etiqueta:<6} OK      {estado.version}")
        else:
            print(f"  {etiqueta:<6} FALTA   [{estado.codigo_motivo}] {estado.mensaje}")
            if estado.sugerencia:
                print(f"                 {estado.sugerencia}")
            if estado.alternativas:
                alternativas = ", ".join(estado.alternativas)
                print(f"                 en su lugar sirven: {alternativas}")

    print()
    print("MOTORES")
    print("-" * 78)
    for motor in registry.todos():
        estado = motor.disponibilidad()
        marca = "OK     " if estado.disponible else "apagado"
        detalle = estado.version or estado.codigo_motivo
        print(f"  {marca} {motor.id:<14} {len(motor.pares()):>3} pares   {detalle}")

    print()
    print("MATRIZ DE CAPACIDADES")
    print("-" * 78)
    celdas = registry.matriz_de_capacidades()
    por_estado: dict[str, list] = {}
    for celda in celdas.values():
        por_estado.setdefault(celda.estado, []).append(celda)

    for estado in ("disponible", "instalable", "no-soportado"):
        lista = por_estado.get(estado, [])
        print(f"  {estado:<14} {len(lista):>3} conversiones")
        if estado != "disponible":
            for motivo in sorted({c.codigo_motivo for c in lista}):
                cuantas = sum(1 for c in lista if c.codigo_motivo == motivo)
                print(f"                     {cuantas:>3} por {motivo}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
