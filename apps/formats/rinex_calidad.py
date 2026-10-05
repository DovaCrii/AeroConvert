"""Calidad de un RINEX de observación, en código propio: lo que se pide de TEQC.

TEQC dejó de mantenerse en 2019, escribe solo RINEX 2, y su binario no es de código abierto
(ni se puede portar ni redistribuir). Aquí se calcula lo que más se miraba de su informe, con
el lector de `rinex.py`, en una sola pasada y con memoria acotada:

- **satélites por época** (mínimo, media y máximo);
- **épocas con cada satélite**, y qué porcentaje de las épocas del archivo es;
- **observaciones presentes frente a posibles**, por constelación y por tipo de observación
  (RINEX 3; en RINEX 2 los campos van en líneas aparte y no se cuentan);
- lo que `resumir_epocas` ya sabe: huecos, intervalo, eventos, truncado.

**Lo que NO calcula**, y se dice para que nadie lo busque: multitrayecto (MP1, MP2), saltos de
ciclo, ni elevación o acimut de los satélites (haría falta la efeméride y la posición). Un
informe que los inventara sería peor que no tenerlo. Y como todo lo del archivo, **cuenta lo
que el archivo dice**; no hay oráculo contra lo que grabó el receptor.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import rinex
from .rinex import CabeceraRinex, Fuente

#: Qué tanto de la lista de satélites se guarda. Hay unos 200 en el cielo; el tope solo
#: protege de un archivo hostil con identificadores inventados.
SATELITES_MAXIMOS = 600
ANCHO_DE_CAMPO = 16
ANCHO_DEL_VALOR = 14


@dataclass(frozen=True)
class SatelitePresente:
    id: str
    epocas: int
    #: Porcentaje de las épocas del archivo en que aparece.
    porcentaje: float


@dataclass(frozen=True)
class InformeDeCalidad:
    epocas: int
    satelites_minimo: int
    satelites_medio: float
    satelites_maximo: int
    #: De mayor a menor presencia.
    satelites: tuple[SatelitePresente, ...]
    #: Por constelación: (letra, observaciones presentes, posibles). Solo RINEX 3.
    completitud: tuple[tuple[str, int, int], ...]
    #: Por constelación y tipo (`G`, `C1C`): presentes y posibles. Solo RINEX 3.
    por_tipo: tuple[tuple[str, str, int, int], ...]
    #: Hubo identificadores de más de los que se guardan.
    recortado: bool = False
    notas: tuple[str, ...] = field(default_factory=tuple)

    @property
    def porcentaje_completo(self) -> float | None:
        posibles = sum(p for _, _, p in self.completitud)
        if not posibles:
            return None
        return 100.0 * sum(h for _, h, _ in self.completitud) / posibles


def calcular(fuente: Fuente, cabecera: CabeceraRinex) -> InformeDeCalidad:
    """Una pasada por el archivo. Para el resto del resumen, `rinex.resumir_epocas`."""
    if not cabecera.es_observacion:
        raise rinex.NoEsRinex("Solo se mide la calidad de un RINEX de observación.")

    lineas = rinex._lineas(fuente)
    for _ in range(cabecera.lineas):
        next(lineas, None)

    estado = _Estado()
    if cabecera.es_v2:
        _pasar_v2(lineas, cabecera, estado)
    else:
        _pasar_v3(lineas, cabecera, estado)
    return estado.informe(cabecera)


class _Estado:
    def __init__(self) -> None:
        self.epocas = 0
        self.minimo: int | None = None
        self.maximo = 0
        self.suma = 0
        self.presencia: Counter[str] = Counter()
        self.recortado = False
        self.presentes: Counter[tuple[str, str]] = Counter()
        self.posibles: Counter[tuple[str, str]] = Counter()

    def epoca(self, satelites: list[str]) -> None:
        self.epocas += 1
        cuantos = len(satelites)
        self.suma += cuantos
        self.maximo = max(self.maximo, cuantos)
        self.minimo = cuantos if self.minimo is None else min(self.minimo, cuantos)
        for sat in satelites:
            if sat in self.presencia or len(self.presencia) < SATELITES_MAXIMOS:
                self.presencia[sat] += 1
            else:
                self.recortado = True

    def informe(self, cabecera: CabeceraRinex) -> InformeDeCalidad:
        satelites = tuple(
            SatelitePresente(sat, veces, 100.0 * veces / self.epocas if self.epocas else 0.0)
            for sat, veces in sorted(self.presencia.items(), key=lambda p: (-p[1], p[0]))
        )
        por_constelacion: dict[str, list[int]] = {}
        for (letra, _tipo), posibles in self.posibles.items():
            cuenta = por_constelacion.setdefault(letra, [0, 0])
            cuenta[0] += self.presentes[(letra, _tipo)]
            cuenta[1] += posibles
        notas: list[str] = []
        if cabecera.es_v2:
            notas.append(
                "En RINEX 2 los campos van en líneas aparte: no se cuentan las observaciones "
                "presentes frente a las posibles."
            )
        if self.recortado:
            notas.append(f"Solo se listan los primeros {SATELITES_MAXIMOS} identificadores.")
        return InformeDeCalidad(
            epocas=self.epocas,
            satelites_minimo=self.minimo or 0,
            satelites_medio=(self.suma / self.epocas) if self.epocas else 0.0,
            satelites_maximo=self.maximo,
            satelites=satelites,
            completitud=tuple(
                (letra, presentes, posibles)
                for letra, (presentes, posibles) in sorted(por_constelacion.items())
            ),
            por_tipo=tuple(
                (letra, tipo, self.presentes[(letra, tipo)], posibles)
                for (letra, tipo), posibles in sorted(self.posibles.items())
            ),
            recortado=self.recortado,
            notas=tuple(notas),
        )


def _pasar_v3(lineas, cabecera: CabeceraRinex, estado: _Estado) -> None:
    for linea in lineas:
        if not linea.startswith(">"):
            continue
        partes = linea[1:].split()
        try:
            indicador, cuantos = int(partes[6]), int(partes[7])
        except (ValueError, IndexError):
            return
        sats: list[str] = []
        completa = True
        for _ in range(cuantos):
            registro = next(lineas, None)
            if registro is None:
                completa = False
                break
            if indicador > 1:
                continue
            sat = registro[:3].replace(" ", "0")
            sats.append(sat)
            _contar_campos(registro, sat[:1], cabecera, estado)
        if not completa:
            return  # la época a medias no se cuenta, como en `resumir_epocas`
        if indicador <= 1:
            estado.epoca(sats)


def _contar_campos(registro: str, letra: str, cabecera: CabeceraRinex, estado: _Estado) -> None:
    tipos = cabecera.tipos_de_observacion.get(letra, ())
    for i, tipo in enumerate(tipos):
        inicio = 3 + i * ANCHO_DE_CAMPO
        valor = registro[inicio : inicio + ANCHO_DEL_VALOR]
        clave = (letra, tipo)
        estado.posibles[clave] += 1
        if valor.strip():
            estado.presentes[clave] += 1


def _pasar_v2(lineas, cabecera: CabeceraRinex, estado: _Estado) -> None:
    por_satelite = max(1, -(-cabecera.numero_de_tipos // 5))
    for linea in lineas:
        if len(linea) < 32 or not linea[:1].isspace():
            continue
        try:
            indicador, cuantos = int(linea[28:29]), int(linea[29:32])
        except ValueError:
            continue
        # Los identificadores caben 12 por línea; la primera está en la línea de época.
        texto = linea[32:68]
        extra = max(0, -(-cuantos // 12) - 1)
        for _ in range(extra):
            siguiente = next(lineas, None)
            if siguiente is None:
                return
            texto += siguiente[32:68]
        a_saltar = cuantos if indicador > 1 else cuantos * por_satelite
        for _ in range(a_saltar):
            if next(lineas, None) is None:
                return
        if indicador > 1:
            continue
        sats = [
            texto[i : i + 3].replace(" ", "0")
            for i in range(0, 3 * cuantos, 3)
            if texto[i : i + 3].strip()
        ]
        estado.epoca(sats)


def a_markdown(
    informe: InformeDeCalidad, cabecera: CabeceraRinex, resumen: rinex.ResumenDeEpocas
) -> str:
    """El informe, como texto que se puede guardar o pegar en un acta."""
    renglones = ["# Informe de calidad de un RINEX", ""]
    renglones.append(f"- Versión: RINEX {cabecera.version:.2f}")
    if cabecera.marcador:
        renglones.append(f"- Punto: {cabecera.marcador}")
    if cabecera.receptor:
        renglones.append(f"- Receptor: {cabecera.receptor}")
    if cabecera.antena:
        renglones.append(f"- Antena: {cabecera.antena}")
    if resumen.primera and resumen.ultima:
        renglones.append(
            f"- Del {resumen.primera:%Y-%m-%d %H:%M:%S} al {resumen.ultima:%Y-%m-%d %H:%M:%S} "
            f"({rinex.duracion_legible(resumen.duracion_s)})"
        )
    esperadas = resumen.esperadas
    if esperadas:
        renglones.append(
            f"- Épocas: {resumen.epocas} de {esperadas} esperadas a "
            f"{resumen.intervalo_s:g} s ({100.0 * resumen.epocas / esperadas:.1f} %)"
        )
    else:
        renglones.append(f"- Épocas: {resumen.epocas}")
    renglones.append(f"- Huecos: {resumen.total_de_huecos}")
    renglones.append(
        f"- Satélites por época: mínimo {informe.satelites_minimo}, "
        f"media {informe.satelites_medio:.1f}, máximo {informe.satelites_maximo}"
    )
    porcentaje = informe.porcentaje_completo
    if porcentaje is not None:
        renglones.append(f"- Observaciones presentes: {porcentaje:.1f} % de las posibles")

    if informe.completitud:
        renglones += ["", "## Por constelación", "", "| Constelación | Presentes | Posibles | % |"]
        renglones.append("| --- | ---: | ---: | ---: |")
        for letra, presentes, posibles in informe.completitud:
            nombre = rinex.CONSTELACIONES.get(letra, letra)
            parte = 100.0 * presentes / posibles if posibles else 0.0
            renglones.append(f"| {nombre} | {presentes} | {posibles} | {parte:.1f} |")

    if informe.satelites:
        renglones += ["", "## Satélites", "", "| Satélite | Épocas | % de las épocas |"]
        renglones.append("| --- | ---: | ---: |")
        for sat in informe.satelites:
            renglones.append(f"| {sat.id} | {sat.epocas} | {sat.porcentaje:.1f} |")

    renglones += ["", "## Lo que este informe no mide", ""]
    renglones.append(
        "Multitrayecto, saltos de ciclo, elevación y acimut: harían falta la efeméride y la "
        "posición, y un informe que los inventara sería peor que no tenerlo. Cuenta lo que "
        "el archivo dice; no se compara con lo que grabó el receptor."
    )
    for nota in informe.notas:
        renglones.append("")
        renglones.append(f"> {nota}")
    return "\n".join(renglones) + "\n"
