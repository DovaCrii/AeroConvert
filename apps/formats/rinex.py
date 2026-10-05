"""Lector de RINEX: la cabecera, y un escáner de épocas que no carga el archivo en memoria.

Es la mitad del verificador de la conversión de datos GNSS. Lo escribe un programa cerrado
(el convertidor de Trimble) y lo lee código nuestro: son dos analizadores escritos por gente
distinta, que es lo que la regla 2 de `AGENTS.md` pide cuando no hay un oráculo externo
instalable.

## Qué comprueba y qué no

Comprueba que el archivo **es un RINEX** (cabecera completa, versión conocida), cuántas épocas
trae, de cuándo a cuándo, cada cuánto y dónde faltan. **No comprueba que las observaciones
sean ciertas**: eso solo se sabría contra el crudo, y el crudo es un formato cerrado. Se dice
en `docs/PRUEBAS_CON_ORACULO.md` en vez de fingir lo contrario.

## Dos formas de época

- **RINEX 2.xx**: una línea de época con la lista de satélites (hasta 12 por línea, con
  continuación) y después, por satélite, tantas líneas como pidan los tipos de observación
  (cinco por línea). Hay que conocer cuántos tipos hay para saber cuántas líneas saltar.
- **RINEX 3.xx y 4.xx**: una línea que empieza por `>` y después **una línea por satélite**.
  Más sencilla de recorrer.

En ambas, un indicador de época mayor que 1 no es una observación sino un evento (cambio de
antena, salto de reloj, inicio de sesión) con tantas líneas de registro como satélites declare.

## Lo que no hace

No descomprime Hatanaka (CRINEX): se dice y se pide el RINEX normal.
"""

from __future__ import annotations

import io
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

#: Cuánto se lee buscando el final de la cabecera. Una cabecera real mide unas decenas de
#: líneas; la de una red con muchos comentarios, unos cientos. Pasar de esto es un archivo roto.
LINEAS_MAXIMAS_DE_CABECERA = 4_000
#: Una línea de RINEX mide cientos de caracteres; con un tipo de observación por campo de 16,
#: ni la de una constelación con docenas llega a la mitad de esto.
LARGO_MAXIMO_DE_LINEA = 16_384

#: Las versiones que se conocen: la 2.xx, la 3.xx y la 4.xx. Una distinta no se rechaza —el
#: formato evoluciona—, pero se avisa.
VERSION_MINIMA, VERSION_MAXIMA = 2.0, 5.0

TIPOS = {"O": "observación", "N": "navegación", "M": "meteorológico"}

#: La letra con la que RINEX nombra a cada constelación, y su nombre. Para el recibo: «E G R»
#: no le dice nada a quien no se lo sepa, y «Galileo, GPS, GLONASS» sí.
CONSTELACIONES = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "I": "NavIC",
    "S": "SBAS",
}


def nombre_de_constelaciones(letras) -> str:
    """`("E", "G", "R")` a «Galileo, GPS, GLONASS»: en el orden en que se suelen decir."""
    orden = list(CONSTELACIONES)
    ordenadas = sorted(letras, key=lambda c: orden.index(c) if c in orden else len(orden))
    return ", ".join(CONSTELACIONES.get(c, c) for c in ordenadas)


def duracion_legible(segundos: float | None) -> str:
    """`3599.0` a «59 min 59 s»; `8726` a «2 h 25 min 26 s»."""
    if segundos is None:
        return ""
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    partes = []
    if horas:
        partes.append(f"{horas} h")
    if minutos or horas:
        partes.append(f"{minutos} min")
    if segs or not partes:
        partes.append(f"{segs} s")
    return " ".join(partes)


#: Un hueco es un salto de más de esta vez el intervalo habitual.
FACTOR_DE_HUECO = 1.5

#: Para no devolver una lista de miles de huecos de un archivo roto: se cuentan todos, se
#: guardan los primeros.
HUECOS_GUARDADOS = 50

#: Saltos distintos que se recuerdan. Un archivo bien formado tiene uno o dos (el intervalo y
#: algún hueco); uno corrupto puede inventarse uno por época, y eso no puede crecer sin tope.
SALTOS_DISTINTOS_MAXIMOS = 2_000


class NoEsRinex(Exception):
    """El archivo no es un RINEX que se pueda leer."""


@dataclass(frozen=True)
class CabeceraRinex:
    version: float
    #: `O` observación, `N` navegación, `M` meteorológico.
    tipo: str
    #: `G` GPS, `R` GLONASS, `E` Galileo, `C` BeiDou, `J` QZSS, `I` NavIC, `S` SBAS, `M` mixto.
    sistema: str
    programa: str
    marcador: str
    receptor: str
    antena: str
    #: ECEF en metros, o `None` si no la trae (o viene a cero, que es lo mismo que no saberla).
    posicion_aproximada_m: tuple[float, float, float] | None
    intervalo_s: float | None
    primera_epoca: datetime | None
    ultima_epoca: datetime | None
    #: Por sistema en RINEX 3/4 (`{"G": ("C1C", "L1C", …)}`); bajo `"*"` en RINEX 2.
    tipos_de_observacion: dict[str, tuple[str, ...]]
    lineas: int

    @property
    def es_observacion(self) -> bool:
        return self.tipo == "O"

    @property
    def es_v2(self) -> bool:
        return self.version < 3.0

    @property
    def constelaciones(self) -> tuple[str, ...]:
        """Las que la cabecera dice que trae. En RINEX 2 solo se sabe «mixto» o una."""
        if not self.es_v2:
            return tuple(sorted(self.tipos_de_observacion))
        return () if self.sistema in ("", "M") else (self.sistema,)

    @property
    def numero_de_tipos(self) -> int:
        """Cuántos tipos de observación por satélite, que en RINEX 2 decide cuántas líneas hay."""
        return len(self.tipos_de_observacion.get("*", ()))


@dataclass(frozen=True)
class ResumenDeEpocas:
    epocas: int
    primera: datetime | None
    ultima: datetime | None
    #: El intervalo más repetido entre épocas, en segundos.
    intervalo_s: float | None
    huecos: tuple[tuple[datetime, datetime], ...]
    total_de_huecos: int
    #: Épocas con indicador de evento (>1): no son observaciones.
    eventos: int
    #: El archivo acaba a mitad de una época.
    truncado: bool
    satelites_maximos: int

    @property
    def duracion_s(self) -> float | None:
        if self.primera is None or self.ultima is None:
            return None
        return (self.ultima - self.primera).total_seconds()

    @property
    def esperadas(self) -> int | None:
        """Cuántas épocas debería haber si no faltara ninguna."""
        if not self.intervalo_s or self.duracion_s is None:
            return None
        return round(self.duracion_s / self.intervalo_s) + 1


#: De dónde se lee: una ruta, o una función que abre el archivo en binario cada vez que se
#: la llama. La segunda existe para leer **dentro de un zip sin extraerlo**: un día de datos a
#: 1 Hz son cientos de megabytes, y extraerlos solo para mirarlos duplicaría el disco.
Fuente = Path | Callable[[], BinaryIO]


def _lineas(fuente: Fuente) -> Iterator[str]:
    # `latin-1` no falla nunca: un RINEX es ASCII y un byte raro no debe tumbar la lectura.
    if isinstance(fuente, Path):
        with open(fuente, encoding="latin-1", newline="") as archivo:
            yield from _lineas_acotadas(archivo)
        return
    with fuente() as binario:
        yield from _lineas_acotadas(io.TextIOWrapper(binario, encoding="latin-1", newline=""))


def _lineas_acotadas(archivo) -> Iterator[str]:
    """Línea a línea, sin dejar que una sola línea sea el archivo entero.

    `for linea in archivo` lee hasta el salto: un archivo de gigabytes sin ninguno era una
    única línea que se copiaba dos veces en memoria (hallazgo D-02 de la auditoría). Una línea
    de RINEX mide cientos de caracteres como mucho.
    """
    while True:
        linea = archivo.readline(LARGO_MAXIMO_DE_LINEA + 1)
        if not linea:
            return
        if len(linea) > LARGO_MAXIMO_DE_LINEA and not linea.endswith(("\n", "\r")):
            raise NoEsRinex(
                f"Una línea pasa de {LARGO_MAXIMO_DE_LINEA} caracteres: esto no es un RINEX."
            )
        yield linea.rstrip("\r\n")


def _momento(partes: list[str]) -> datetime | None:
    """Año, mes, día, hora, minuto, segundo (con fracción) a un instante."""
    try:
        anio, mes, dia, hora, minuto = (int(p) for p in partes[:5])
        segundos = float(partes[5])
        base = datetime(anio, mes, dia, hora, minuto)
    except (ValueError, IndexError):
        return None
    return base + timedelta(seconds=segundos)


def leer_cabecera(ruta: Fuente) -> CabeceraRinex:
    """La cabecera, hasta `END OF HEADER`. No toca las observaciones."""
    version = tipo = sistema = ""
    programa = marcador = receptor = antena = ""
    posicion = intervalo = primera = ultima = None
    tipos: dict[str, tuple[str, ...]] = {}
    sistema_en_curso = ""
    faltan = 0
    acumulado: list[str] = []
    total = 0
    cerrada = False

    for total, linea in enumerate(_lineas(ruta), start=1):
        if total == 1:
            # La primera línea de un CRINEX es `3.0   COMPACT RINEX FORMAT   CRINEX VERS / TYPE`:
            # la palabra va en la etiqueta de la derecha, como en cualquier cabecera RINEX.
            if "CRINEX VERS" in linea[60:80]:
                raise NoEsRinex(
                    "Está comprimido en Hatanaka (CRINEX). Descomprímelo a RINEX normal primero."
                )
            if "RINEX VERSION / TYPE" not in linea:
                raise NoEsRinex("La primera línea no es «RINEX VERSION / TYPE».")
        if total > LINEAS_MAXIMAS_DE_CABECERA:
            break

        etiqueta = linea[60:80].strip()
        contenido = linea[:60]

        if etiqueta == "RINEX VERSION / TYPE":
            try:
                version = float(contenido[:9])
            except ValueError as fallo:
                raise NoEsRinex("La versión de la cabecera no es un número.") from fallo
            tipo = contenido[20:21].strip()
            sistema = contenido[40:41].strip()
        elif etiqueta == "PGM / RUN BY / DATE":
            programa = contenido[:20].strip()
        elif etiqueta == "MARKER NAME":
            marcador = contenido.strip()
        elif etiqueta == "REC # / TYPE / VERS":
            receptor = " ".join(contenido[20:40].split())
        elif etiqueta == "ANT # / TYPE":
            # El campo lleva el tipo de antena y, detrás, el radomo («TRM57971.00     NONE»).
            antena = " ".join(contenido[20:40].split())
        elif etiqueta == "APPROX POSITION XYZ":
            try:
                xyz = tuple(float(p) for p in contenido.split()[:3])
            except ValueError:
                xyz = ()
            if len(xyz) == 3 and any(xyz):
                posicion = xyz
        elif etiqueta == "INTERVAL":
            try:
                intervalo = float(contenido[:10])
            except ValueError:
                pass
        elif etiqueta == "TIME OF FIRST OBS":
            primera = _momento(contenido.split())
        elif etiqueta == "TIME OF LAST OBS":
            ultima = _momento(contenido.split())
        elif etiqueta == "# / TYPES OF OBSERV":  # RINEX 2
            partes = contenido.split()
            if partes and partes[0].isdigit() and not acumulado:
                faltan = int(partes[0])
                partes = partes[1:]
            acumulado.extend(partes)
            if faltan and len(acumulado) >= faltan:
                tipos["*"] = tuple(acumulado[:faltan])
                faltan, acumulado = 0, []
        elif etiqueta == "SYS / # / OBS TYPES":  # RINEX 3 y 4
            if contenido[:1].strip():  # línea nueva de un sistema
                sistema_en_curso = contenido[0]
                try:
                    faltan = int(contenido[3:6])
                except ValueError:
                    faltan = 0
                acumulado = contenido[7:].split()
            else:  # continuación
                acumulado.extend(contenido[7:].split())
            if sistema_en_curso and faltan and len(acumulado) >= faltan:
                tipos[sistema_en_curso] = tuple(acumulado[:faltan])
                sistema_en_curso, faltan, acumulado = "", 0, []
        elif etiqueta == "END OF HEADER":
            cerrada = True
            break

    if not version:
        raise NoEsRinex("No trae «RINEX VERSION / TYPE».")
    if not cerrada:
        raise NoEsRinex("La cabecera no termina: falta «END OF HEADER».")
    if not tipo:
        raise NoEsRinex("La cabecera no dice qué tipo de RINEX es.")

    return CabeceraRinex(
        version=version,
        tipo=tipo,
        sistema=sistema,
        programa=programa,
        marcador=marcador,
        receptor=receptor,
        antena=antena,
        posicion_aproximada_m=posicion,
        intervalo_s=intervalo,
        primera_epoca=primera,
        ultima_epoca=ultima,
        tipos_de_observacion=tipos,
        lineas=total,
    )


def version_conocida(version: float) -> bool:
    return VERSION_MINIMA <= version < VERSION_MAXIMA


@dataclass
class _Cuenta:
    """Lo que se acumula mientras se recorre. Memoria constante salvo los huecos guardados."""

    epocas: int = 0
    primera: datetime | None = None
    ultima: datetime | None = None
    saltos: Counter = field(default_factory=Counter)
    eventos: int = 0
    truncado: bool = False
    satelites_maximos: int = 0
    _anterior: datetime | None = None
    #: Ejemplos de cada salto, acotados. Cuál es el intervalo habitual solo se sabe al final,
    #: así que no se puede decidir antes qué salto es un hueco: se guardan unos cuantos de cada.
    _ejemplos: dict = field(default_factory=dict)

    def epoca(self, momento: datetime | None, satelites: int, evento: bool) -> None:
        if evento:
            self.eventos += 1
            return
        if momento is None:
            return
        self.epocas += 1
        self.satelites_maximos = max(self.satelites_maximos, satelites)
        if self.primera is None:
            self.primera = momento
        if self._anterior is not None:
            salto = round((momento - self._anterior).total_seconds(), 3)
            if salto in self.saltos or len(self.saltos) < SALTOS_DISTINTOS_MAXIMOS:
                self.saltos[salto] += 1
                guardados = self._ejemplos.setdefault(salto, [])
                if len(guardados) < HUECOS_GUARDADOS:
                    guardados.append((self._anterior, momento))
        self._anterior = momento
        self.ultima = momento


def resumir_epocas(ruta: Fuente, cabecera: CabeceraRinex) -> ResumenDeEpocas:
    """Recorre las épocas de un RINEX de observación sin cargarlo entero."""
    if not cabecera.es_observacion:
        raise NoEsRinex("Solo se cuentan épocas en un RINEX de observación.")

    cuenta = _Cuenta()
    lineas = _lineas(ruta)
    for _ in range(cabecera.lineas):  # saltar la cabecera
        next(lineas, None)

    if cabecera.es_v2:
        _recorrer_v2(lineas, cabecera, cuenta)
    else:
        _recorrer_v3(lineas, cuenta)

    habitual = cuenta.saltos.most_common(1)[0][0] if cuenta.saltos else None
    huecos: list[tuple[datetime, datetime]] = []
    total = 0
    if habitual:
        for salto, veces in cuenta.saltos.items():
            if salto > habitual * FACTOR_DE_HUECO:
                total += veces
                huecos.extend(cuenta._ejemplos.get(salto, ()))
        huecos = sorted(huecos)[:HUECOS_GUARDADOS]

    return ResumenDeEpocas(
        epocas=cuenta.epocas,
        primera=cuenta.primera,
        ultima=cuenta.ultima,
        intervalo_s=habitual,
        huecos=tuple(huecos),
        total_de_huecos=total,
        eventos=cuenta.eventos,
        truncado=cuenta.truncado,
        satelites_maximos=cuenta.satelites_maximos,
    )


def _recorrer_v3(lineas: Iterator[str], cuenta: _Cuenta) -> None:
    for linea in lineas:
        if not linea.startswith(">"):
            continue
        partes = linea[1:].split()
        momento = _momento(partes[:6])
        try:
            indicador, cuantos = int(partes[6]), int(partes[7])
        except (ValueError, IndexError):
            cuenta.truncado = True
            return
        for _ in range(cuantos):
            if next(lineas, None) is None:
                cuenta.truncado = True
                return  # la época a medias no se cuenta como buena
        cuenta.epoca(momento, cuantos, evento=indicador > 1)


def _recorrer_v2(lineas: Iterator[str], cabecera: CabeceraRinex, cuenta: _Cuenta) -> None:
    por_satelite = max(1, -(-cabecera.numero_de_tipos // 5))  # techo de n / 5
    for linea in lineas:
        if len(linea) < 32 or not linea[:1].isspace():
            continue
        try:
            anio = int(linea[1:3])
            partes = [
                str(anio + (2000 if anio < 80 else 1900)),
                linea[4:6],
                linea[7:9],
                linea[10:12],
                linea[13:15],
                linea[15:26],
            ]
            indicador, cuantos = int(linea[28:29]), int(linea[29:32])
        except ValueError:
            continue  # no es una época: una línea suelta que no se sabe leer
        momento = _momento([p.strip() for p in partes])

        # Los satélites caben 12 por línea; la primera va en la propia línea de época.
        a_saltar = max(0, -(-cuantos // 12) - 1)
        a_saltar += cuantos if indicador > 1 else cuantos * por_satelite
        for _ in range(a_saltar):
            if next(lineas, None) is None:
                cuenta.truncado = True
                return  # la época a medias no se cuenta como buena
        cuenta.epoca(momento, cuantos, evento=indicador > 1)
