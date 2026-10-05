"""Motores GNSS: del archivo crudo de un receptor a RINEX.

## Dos motores: el de Trimble para sus archivos de campo, y RTKLIB para el resto

`MotorRtklibConvbin` (más abajo) lee los flujos RT17, UBX, SBF, NovAtel, RTCM 3, BINEX y
Javad con `convbin`, de código abierto. **No** lee los archivos de campo de Trimble, y por eso
sigue existiendo el motor de Trimble. Se buscó qué existe antes de escribir nada.

**RTKLIB `convbin` no lee los archivos de campo de Trimble** (T01, T02, T04): lee los flujos RT17 y RT27, más Septentrio, u-blox, NovAtel, Javad,
RTCM y BINEX. `runpkr00` más TEQC tampoco convierte un T04, y TEQC está muerto desde 2019 y solo
escribe RINEX 2. Lo único que convierte un T02 o un T04 es la utilidad oficial de Trimble,
`convertToRinex.exe`: un programa de Windows, de licencia propia, **que no se puede
redistribuir**. Por eso se sondea y no se declara, igual que ODA, y en Linux corre bajo Wine.

## Lo que mide el convertidor, y por qué esto verifica tanto

Medido el 2026-10-05 sobre un T02 de un NetR9 y un T04 de un R12i, en Windows:

- sale con código 0 y escribe «Success» **siempre**: con un archivo vacío, con 200 bytes de
  basura (y deja un RINEX de 1.476 bytes, solo cabecera), y con un T02 cortado por la mitad
  (que entrega un RINEX más corto, sin avisar de nada);
- escribe varios archivos: las observaciones (`.23o`) y la navegación (`.23n` GPS, `.23g`
  GLONASS, `.23l` Galileo, o `.23mix` con `-mx`), con nombres cortos de RINEX 2 aunque el
  contenido es 3.04;
- tarda unos 10 s por megabyte de crudo.

Es la regla número uno de `AGENTS.md` en estado puro: **el código de salida no prueba nada**.
La integridad del crudo se comprueba antes (`trimble.comprobar_integridad`), y lo que salió se
comprueba después abriendo cada archivo y contando épocas (`rinex.py`).
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

from django.conf import settings

from apps.engines.base import (
    Disponibilidad,
    Motor,
    OpcionDeMotor,
    ParDeFormatos,
    PlanDeEjecucion,
    Verificacion,
    ruta_parcial,
)
from apps.formats import rinex, trimble

#: Qué versión de RINEX se puede pedir. 3.04 es la que usa el convertidor si no se le dice
#: nada; 2.11 es la que lee hasta el software más viejo.
VERSIONES = (
    ("3.04", "RINEX 3.04"),
    ("3.05", "RINEX 3.05"),
    ("2.11", "RINEX 2.11 (la que lee todo)"),
)
VERSION_POR_OMISION = "3.04"

#: Segundos de plazo por megabyte de crudo. Medido: 10 s/MB en Windows. Se da el triple, y
#: otro tanto bajo Wine, que en la receta publicada tarda unas tres veces más.
SEGUNDOS_POR_MB_EN_WINDOWS = 30
SEGUNDOS_POR_MB_BAJO_WINE = 90
SEGUNDOS_BASE = 300


def _bajo_wine() -> bool:
    from apps.engines import sondas

    return sondas.necesita_wine()


def a_ruta_de_wine(ruta: Path) -> str:
    """`/var/lib/x` a `Z:\\var\\lib\\x`.

    Wine monta la raíz del sistema como la unidad `Z:`. Los argumentos de un programa de
    Windows tienen que ser rutas de Windows, y convertirlas aquí es determinista: no hace
    falta lanzar `winepath` para cada trabajo.
    """
    return "Z:" + str(ruta).replace("/", "\\")


def _carpeta_de_transito(trabajo) -> Path:
    """Donde el convertidor deja lo suyo antes de empaquetarlo.

    Va en la **carpeta de trabajo** y no junto al destino: pesa decenas de veces lo que pesa el
    crudo, y dejarlo al lado del original ensuciaría la carpeta compartida de alguien. Lleva
    `.parcial.` en el nombre, que es la marca que busca el barrido de huérfanos.
    """
    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{trabajo.pk}.parcial.rinex"


def _marcador(texto: object) -> str:
    """El nombre del punto, comprobado. Va al argv, y un `-` delante se leería como opción."""
    limpio = str(texto or "").strip()
    if not limpio:
        return ""
    permitido = limpio[0].isalnum() and all(c.isalnum() or c in "_.-" for c in limpio)
    if not permitido or len(limpio) > 60:
        raise ValueError(
            "El nombre del punto solo admite letras, números, guion, guion bajo y punto, "
            "empieza por letra o número y no pasa de 60 caracteres."
        )
    return limpio


class MotorTrimbleARinex(Motor):
    """T01, T02 y T04 de Trimble a RINEX, con el convertidor oficial."""

    id = "trimble-rinex"
    nombre = "Convert To RINEX de Trimble"
    familia = "gnss"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset({ParDeFormatos("trimble_t0x", "rinex")})

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_trimble_rinex()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                nombre="version",
                etiqueta="Versión de RINEX",
                tipo="eleccion",
                por_defecto=VERSION_POR_OMISION,
                elecciones=VERSIONES,
                ayuda="La 3.04 es la que escribe el convertidor por omisión.",
            ),
            OpcionDeMotor(
                nombre="navegacion_unica",
                etiqueta="Navegación en un solo archivo",
                tipo="booleano",
                por_defecto=True,
                ayuda="Junta GPS, GLONASS y Galileo. Si no, sale un archivo por constelación.",
            ),
            OpcionDeMotor(
                nombre="doppler",
                etiqueta="Incluir Doppler",
                tipo="booleano",
                por_defecto=False,
            ),
            OpcionDeMotor(
                nombre="snr",
                etiqueta="Incluir intensidad de señal (SNR)",
                tipo="booleano",
                por_defecto=False,
            ),
            OpcionDeMotor(
                nombre="marcador",
                etiqueta="Nombre del punto",
                tipo="texto",
                por_defecto="",
                ayuda="Si lo dejas vacío se usa el que trae el receptor.",
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        from apps.engines import sondas

        opciones = dict(trabajo.options or {})
        version = str(opciones.get("version") or VERSION_POR_OMISION)
        if version not in dict(VERSIONES):
            raise ValueError(f"«{version}» no es una versión de RINEX que se ofrezca.")
        marcador = _marcador(opciones.get("marcador"))

        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        carpeta = _carpeta_de_transito(trabajo)

        # Un intento anterior pudo dejar cosas, y mezclar su salida con la de este sería
        # entregar archivos de otra conversión dentro del zip.
        shutil.rmtree(carpeta, ignore_errors=True)
        carpeta.mkdir(parents=True, exist_ok=True)

        ejecutable = sondas.ruta_de_trimble_rinex()
        wine = _bajo_wine()
        argumento = a_ruta_de_wine if wine else str
        argv: list[str] = []
        if wine:
            xvfb = shutil.which("xvfb-run")
            if xvfb and not os.environ.get("DISPLAY"):
                argv += [xvfb, "-a"]
            argv.append(shutil.which("wine") or "wine")
        argv += [ejecutable, argumento(origen), "-p", argumento(carpeta), "-v", version]

        if opciones.get("navegacion_unica", True):
            argv.append("-mx")
        if opciones.get("doppler"):
            argv.append("-d")
        if opciones.get("snr"):
            argv.append("-s")
        if marcador:
            argv += ["-mo", marcador]

        env: dict[str, str] = {}
        if wine:
            # `-all`: Wine habla por la salida de error y ensucia el diagnóstico real.
            env["WINEDEBUG"] = "-all"
            if getattr(settings, "WINEPREFIX", ""):
                env["WINEPREFIX"] = settings.WINEPREFIX

        megas = max(1, math.ceil(trabajo.source_size_bytes / 1_048_576))
        por_mega = SEGUNDOS_POR_MB_BAJO_WINE if wine else SEGUNDOS_POR_MB_EN_WINDOWS

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            # El segundo paso mete lo escrito en el zip. El principal no escribe el parcial.
            posteriores=(
                (sys.executable, "-m", "apps.gnss.empaquetar", str(carpeta), str(parcial)),
            ),
            salida_en_posteriores=True,
            env=env,
            cwd=Path(settings.BASE_DIR),
            timeout_s=SEGUNDOS_BASE + por_mega * megas,
            # El convertidor imprime «Scanning… Complete!» y «Converting… Success», y nada
            # de avance: sin esto el detector de atasco mataría un trabajo sano.
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        return verificar_rinex(salida, version=_version_pedida(trabajo), crudo=trabajo.source_path)


#: Qué le dice `-r` a `convbin` por cada formato del catálogo. Es una lista cerrada: lo que
#: llega del usuario nunca se interpola en el argv, se elige de aquí.
FORMATO_DE_CONVBIN = {
    "rtcm3": "rtcm3",
    "ubx": "ubx",
    "novatel": "nov",
    "sbf": "sbf",
    "rt17": "rt17",
    "binex": "binex",
    "javad": "javad",
}

VERSIONES_DE_CONVBIN = (
    ("3.04", "RINEX 3.04"),
    ("3.05", "RINEX 3.05"),
    ("3.03", "RINEX 3.03"),
    ("2.11", "RINEX 2.11 (la que lee todo)"),
)

#: `convbin` es rápido (16 MB de RINEX en un segundo), pero se deja holgura por si el disco es
#: lento. No es una medida de la conversión de un flujo, que no se ha hecho: no hay uno aquí.
SEGUNDOS_POR_MB_DE_CONVBIN = 20

_FECHA_APROXIMADA = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")


class MotorRtklibConvbin(Motor):
    """Los flujos y registros de receptores a RINEX, con RTKLIB `convbin` (BSD-2).

    **Es el motor abierto**: corre nativo en Linux y en Windows, sin Wine ni licencia. No lee
    los T01/T02/T04 de Trimble, que son otro formato (ver el docstring del módulo).
    """

    id = "rtklib-convbin"
    nombre = "RTKLIB convbin"
    familia = "gnss"
    prioridad = 20

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos(origen, "rinex") for origen in FORMATO_DE_CONVBIN)

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_rtklib()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        opciones = [
            OpcionDeMotor(
                nombre="version",
                etiqueta="Versión de RINEX",
                tipo="eleccion",
                por_defecto=VERSION_POR_OMISION,
                elecciones=VERSIONES_DE_CONVBIN,
            ),
            OpcionDeMotor(
                nombre="doppler", etiqueta="Incluir Doppler", tipo="booleano", por_defecto=False
            ),
            OpcionDeMotor(
                nombre="snr",
                etiqueta="Incluir intensidad de señal (SNR)",
                tipo="booleano",
                por_defecto=False,
            ),
            OpcionDeMotor(
                nombre="marcador",
                etiqueta="Nombre del punto",
                tipo="texto",
                por_defecto="",
                ayuda="Si lo dejas vacío, el RINEX sale sin nombre de punto.",
            ),
        ]
        if par.origen == "rtcm3":
            opciones.append(
                OpcionDeMotor(
                    nombre="fecha_aproximada",
                    etiqueta="Fecha aproximada de la grabación (AAAA/MM/DD hh:mm:ss)",
                    tipo="texto",
                    por_defecto="",
                    ayuda=(
                        "El RTCM 3 no trae la semana GPS. Vacío, se usa la fecha del archivo "
                        "en disco, que al copiarlo puede ser la de la copia y no la de la medida."
                    ),
                )
            )
        return tuple(opciones)

    def plan(self, trabajo) -> PlanDeEjecucion:
        from apps.engines import sondas

        opciones = dict(trabajo.options or {})
        version = str(opciones.get("version") or VERSION_POR_OMISION)
        if version not in dict(VERSIONES_DE_CONVBIN):
            raise ValueError(f"«{version}» no es una versión de RINEX que se ofrezca.")
        formato = FORMATO_DE_CONVBIN.get(str(trabajo.source_format))
        if formato is None:
            raise ValueError(f"RTKLIB no sabe leer «{trabajo.source_format}».")
        marcador = _marcador(opciones.get("marcador"))
        fecha = str(opciones.get("fecha_aproximada") or "").strip()
        if fecha and not _FECHA_APROXIMADA.match(fecha):
            raise ValueError("La fecha aproximada va como AAAA/MM/DD hh:mm:ss.")

        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        carpeta = _carpeta_de_transito(trabajo)
        shutil.rmtree(carpeta, ignore_errors=True)
        carpeta.mkdir(parents=True, exist_ok=True)

        argv = [sondas.ruta_de_rtklib(), "-r", formato, "-v", version, "-d", str(carpeta)]
        if opciones.get("doppler"):
            argv.append("-od")
        if opciones.get("snr"):
            argv.append("-os")
        if marcador:
            argv += ["-hm", marcador]
        if fecha and formato == "rtcm3":
            argv += ["-tr", fecha]
        argv.append(str(origen))

        megas = max(1, math.ceil(trabajo.source_size_bytes / 1_048_576))
        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=(
                (sys.executable, "-m", "apps.gnss.empaquetar", str(carpeta), str(parcial)),
            ),
            salida_en_posteriores=True,
            cwd=Path(settings.BASE_DIR),
            timeout_s=SEGUNDOS_BASE + SEGUNDOS_POR_MB_DE_CONVBIN * megas,
            # `convbin` pinta una línea de avance por época en la salida de error, pero no un
            # porcentaje: el detector de atasco no tiene de dónde medir.
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        # Sin `crudo`: el cruce con el receptor del crudo es del T0x de Trimble.
        resultado = verificar_rinex(salida, version=_version_pedida(trabajo))
        if resultado.correcta:
            resultado.detalles["verificado_con"] = (
                "rinex.py (lector propio, sobre la salida de RTKLIB convbin)"
            )
        return resultado


def _version_pedida(trabajo) -> str:
    return str((trabajo.options or {}).get("version") or VERSION_POR_OMISION)


def _fallo(codigo: str, mensaje: str) -> Verificacion:
    return Verificacion(correcta=False, motivo=mensaje, codigo_motivo=codigo)


def verificar_rinex(salida: Path, *, version: str, crudo: str = "") -> Verificacion:
    """Abre el zip y cada archivo de dentro. **Lo escribe un programa y lo lee otro.**

    El que escribe es el convertidor cerrado de Trimble; el que lee es `rinex.py`. Son dos
    analizadores escritos por gente distinta, que es lo que la regla 2 de `AGENTS.md` pide
    cuando no hay un oráculo instalable. Lo que no hay es oráculo para la integridad frente al
    crudo, y se dice en `docs/PRUEBAS_CON_ORACULO.md`.
    """
    try:
        paquete = zipfile.ZipFile(salida)
    except zipfile.BadZipFile as fallo:
        return _fallo("rinex-invalido", f"El zip escrito no se deja abrir: {fallo}")

    avisos: list[str] = []
    archivos: list[dict] = []
    observaciones = []
    navegacion = 0

    with paquete:
        rota = paquete.testzip()
        if rota is not None:
            return _fallo("rinex-invalido", f"{rota} está dañado dentro del zip.")

        for nombre in sorted(n for n in paquete.namelist() if not n.endswith("/")):
            abrir = lambda n=nombre: paquete.open(n)  # noqa: E731 - se reabre en cada pasada
            try:
                cabecera = rinex.leer_cabecera(abrir)
            except rinex.NoEsRinex as fallo:
                return _fallo("rinex-invalido", f"{nombre}: {fallo}")

            if f"{cabecera.version:.2f}" != f"{float(version):.2f}":
                return _fallo(
                    "rinex-invalido",
                    f"Se pidió RINEX {version} y {nombre} salió en {cabecera.version:.2f}.",
                )
            tamano = paquete.getinfo(nombre).file_size
            archivos.append({"nombre": nombre, "bytes": tamano, "tipo": cabecera.tipo})

            if cabecera.es_observacion:
                resumen = rinex.resumir_epocas(abrir, cabecera)
                if resumen.epocas == 0:
                    return _fallo(
                        "rinex-sin-epocas",
                        f"{nombre} tiene cabecera pero ninguna época de observación.",
                    )
                if resumen.truncado:
                    return _fallo(
                        "rinex-invalido",
                        f"{nombre} termina a mitad de una época: el archivo quedó cortado.",
                    )
                observaciones.append((nombre, cabecera, resumen))
            else:
                navegacion += 1

    if not observaciones:
        return _fallo("rinex-invalido", "El zip no trae ningún archivo de observación.")
    if not navegacion:
        avisos.append(
            "No trae archivo de navegación: sin las efemérides de a bordo no se puede "
            "posprocesar con ellas."
        )

    nombre, cabecera, resumen = observaciones[0]
    if len(observaciones) > 1:
        avisos.append(
            f"Trae {len(observaciones)} archivos de observación; el recibo cuenta {nombre}."
        )

    intervalo = resumen.intervalo_s or cabecera.intervalo_s
    if resumen.total_de_huecos:
        faltan = (resumen.esperadas or resumen.epocas) - resumen.epocas
        avisos.append(
            f"Faltan {faltan} épocas en {resumen.total_de_huecos} hueco(s). "
            "Puede ser del receptor y no de la conversión."
        )
    if cabecera.primera_epoca and resumen.primera and intervalo:
        desfase = abs((cabecera.primera_epoca - resumen.primera).total_seconds())
        if desfase > intervalo:
            avisos.append("La primera época del archivo no coincide con la que dice su cabecera.")
    if cabecera.ultima_epoca and resumen.ultima and intervalo:
        desfase = abs((cabecera.ultima_epoca - resumen.ultima).total_seconds())
        if desfase > intervalo:
            avisos.append("La última época del archivo no coincide con la que dice su cabecera.")

    bloques = 0
    if crudo:
        try:
            del_crudo = trimble.leer_cabecera(Path(crudo))
        except (trimble.NoEsTrimble, OSError):
            del_crudo = None
        if del_crudo and del_crudo.identificado and cabecera.receptor:
            # Dos lectores distintos opinando sobre lo mismo: el nuestro sobre el crudo y el
            # de Trimble sobre su propia salida. Si no coinciden, algo no es lo que parece.
            if del_crudo.modelo.casefold() != cabecera.receptor.casefold():
                avisos.append(
                    f"El crudo es de un {del_crudo.modelo} y el RINEX dice {cabecera.receptor}."
                )
        try:
            bloques = trimble.comprobar_integridad(Path(crudo)).bloques
        except (trimble.NoEsTrimble, OSError):
            bloques = 0

    detalles = {
        "version": f"{cabecera.version:.2f}",
        "marcador": cabecera.marcador,
        "receptor": cabecera.receptor,
        "antena": cabecera.antena,
        "intervalo_s": intervalo,
        "epocas": resumen.epocas,
        "esperadas": resumen.esperadas,
        "primera": resumen.primera.strftime("%Y-%m-%d %H:%M:%S") if resumen.primera else "",
        "ultima": resumen.ultima.strftime("%Y-%m-%d %H:%M:%S") if resumen.ultima else "",
        "duracion_s": resumen.duracion_s,
        "duracion": rinex.duracion_legible(resumen.duracion_s),
        "constelaciones": " ".join(cabecera.constelaciones),
        "constelaciones_nombres": rinex.nombre_de_constelaciones(cabecera.constelaciones),
        "satelites_maximos": resumen.satelites_maximos,
        "huecos": resumen.total_de_huecos,
        "archivos": archivos,
        "bloques_del_crudo": bloques,
        "verificado_con": "rinex.py (lector propio, sobre la salida del convertidor)",
        "avisos": avisos,
    }
    return Verificacion(correcta=True, detalles=detalles)


def registrar_todos() -> None:
    from apps.engines import registry

    registry.registrar(MotorTrimbleARinex())
    registry.registrar(MotorRtklibConvbin())
