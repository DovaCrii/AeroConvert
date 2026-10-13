"""Pinta pantallas de AeroConvert **con sesión** sin crear cuentas reales ni teclear contraseñas.

Levanta una base de pruebas (en memoria), crea un usuario **sintético** con todos los permisos,
entra
con `Client.force_login` (no hay contraseña de por medio), pide cada ruta y escribe el HTML en
`static/_vista_previa/<nombre>.html`. Al terminar destruye la base. Los medios (`MEDIA_ROOT`) y la
base de datos van a una carpeta temporal: **nada** de lo que se suba toca `entradas/` ni
`db.sqlite3`.

Las URL de los estáticos del HTML se reescriben a relativas (`/static/x.css` pasa a `../x.css`), de
modo que la página se ve igual servida por el servidor de desarrollo
(`/static/_vista_previa/<nombre>.html`) que abierta como archivo.

`static/_vista_previa/` **no se confirma nunca**: está en `.gitignore`; bórrela con `--limpiar`.

Uso::

    uv run python scripts/claude/instantanea.py inicio=/ mapa=/mapa/
    uv run python scripts/claude/instantanea.py subida=/pdf/ --post subida=/pdf/ muestra.pdf
    uv run python scripts/claude/instantanea.py --limpiar

Sale con 0 si todas las respuestas fueron 200 y con 1 si alguna no (el HTML se escribe igual, para
ver qué pasó). `--post NOMBRE=RUTA ARCHIVO` envía el archivo (campo `archivo`, o `--campo`)
por POST.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
#: Se puede cambiar con `INSTANTANEA_CARPETA` (las pruebas no pisan las pantallas de nadie).
CARPETA = Path(os.environ.get("INSTANTANEA_CARPETA") or RAIZ / "static" / "_vista_previa")
NOMBRE_SEGURO = re.compile(r"^[\w.-]+$")
#: Una URL absoluta de estáticos tras una comilla o `(`: `src="/static/x.js"`, `url(/static/x.png)`.
_ESTATICO = re.compile(r"""(["'(])/static/""")


def reescribir_estaticos(html: str) -> str:
    """Las URL `/static/…` pasan a relativas a `static/_vista_previa/` (`../…`)."""
    return _ESTATICO.sub(r"\1../", html)


def _par(texto: str) -> tuple[str, str]:
    nombre, separador, ruta = texto.partition("=")
    if not separador or not NOMBRE_SEGURO.match(nombre) or not ruta.startswith("/"):
        raise argparse.ArgumentTypeError(f"se esperaba NOMBRE=/ruta/, no {texto!r}")
    return nombre, ruta


def limpiar() -> int:
    if CARPETA.exists():
        shutil.rmtree(CARPETA)
        print(f"borrada {CARPETA}")
    else:
        print("no había nada que borrar")
    return 0


def _comprobar_ignorada() -> None:
    gitignore = RAIZ / ".gitignore"
    lineas = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if not any(linea.strip().rstrip("/").lstrip("/") == "static/_vista_previa" for linea in lineas):
        with gitignore.open("a", encoding="utf-8", newline="\n") as salida:
            salida.write(
                "\n# Pantallas de `scripts/claude/instantanea.py`: no se confirman nunca\n"
            )
            salida.write("/static/_vista_previa/\n")
        print("añadido `/static/_vista_previa/` a .gitignore")


def pintar(
    paginas: list[tuple[str, str]],
    envios: list[tuple[str, str, Path]],
    *,
    campo: str = "archivo",
    con_sesion: bool = True,
) -> int:
    """Escribe una página por cada `(nombre, ruta)` y devuelve el código de salida."""
    sys.path.insert(0, str(RAIZ))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"
    temporal = Path(tempfile.mkdtemp(prefix="instantanea-"))
    # Antes de `django.setup()`: lo que se suba y la base van a una carpeta que se borra al final.
    os.environ["AEROCONVERT_MEDIA"] = str(temporal / "entradas")
    os.environ["DB_PATH"] = str(temporal / "db.sqlite3")

    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.test import Client
    from django.test.utils import setup_test_environment, teardown_test_environment

    setup_test_environment()
    antigua = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    fallos = 0
    try:
        cliente = Client()
        if con_sesion:
            modelo = get_user_model()
            usuario = modelo.objects.create_superuser(
                username="instantanea", email="instantanea@example.invalid", password=None
            )
            cliente.force_login(usuario)
        CARPETA.mkdir(parents=True, exist_ok=True)
        for nombre, ruta in paginas:
            respuesta = cliente.get(ruta, follow=True)
            fallos += _guardar(nombre, ruta, respuesta)
        for nombre, ruta, archivo in envios:
            with archivo.open("rb") as flujo:
                respuesta = cliente.post(ruta, {campo: flujo}, follow=True)
            fallos += _guardar(nombre, f"POST {ruta}", respuesta)
    finally:
        connection.creation.destroy_test_db(antigua, verbosity=0)
        teardown_test_environment()
        shutil.rmtree(temporal, ignore_errors=True)
    print("Recuerde: `static/_vista_previa/` no se confirma (.gitignore); `--limpiar` la borra.")
    return 1 if fallos else 0


def _guardar(nombre: str, ruta: str, respuesta) -> int:
    html = respuesta.content.decode("utf-8", errors="replace")
    destino = CARPETA / f"{nombre}.html"
    destino.write_text(reescribir_estaticos(html), encoding="utf-8", newline="\n")
    ok = respuesta.status_code == 200
    print(f"{'ok ' if ok else 'ERR'} {respuesta.status_code}  {ruta}  ->  {destino}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    analizador.add_argument("paginas", nargs="*", type=_par, metavar="NOMBRE=/ruta/")
    analizador.add_argument(
        "--post", nargs=2, action="append", default=[], metavar=("NOMBRE=/ruta/", "ARCHIVO")
    )
    analizador.add_argument("--campo", default="archivo", help="nombre del campo del archivo")
    analizador.add_argument("--sin-sesion", action="store_true", help="no entrar con el usuario")
    analizador.add_argument("--limpiar", action="store_true", help="borra static/_vista_previa/")
    args = analizador.parse_args(argv)
    if args.limpiar:
        return limpiar()
    envios = []
    for texto, archivo in args.post:
        nombre, ruta = _par(texto)
        envios.append((nombre, ruta, Path(archivo).resolve()))
    if not args.paginas and not envios:
        analizador.error("indique al menos una página NOMBRE=/ruta/")
    if "INSTANTANEA_CARPETA" not in os.environ:
        _comprobar_ignorada()
    return pintar(args.paginas, envios, campo=args.campo, con_sesion=not args.sin_sesion)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
