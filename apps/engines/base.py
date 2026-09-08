"""El contrato de motor.

## La decision que ordena todo lo demas: los motores no ejecutan nada

Un motor **describe** una conversion -- que par de formatos sabe hacer, si esta disponible
en esta maquina, que opciones acepta, y que comando habria que lanzar -- pero no lanza
nada. Quien ejecuta es un unico runner en `apps.jobs`.

Suena a ceremonia y no lo es. Es lo que hace que toda esta capa se pueda probar **sin GDAL
instalado**: una prueba compara el `argv` que el motor construyo contra el que se esperaba,
y eso atrapa el error que de verdad ocurre. El precedente es literal:
`AeroBim/services/api/apps/documents/conversion.py` le pasa a ODA File Converter seis
argumentos **posicionales y sin nombre**; equivocarse de orden no da error, da una
conversion a otra version, y nadie se entera hasta que el cliente abre el archivo.

## Y la segunda: disponible no es lo mismo que sabe escribir

El controlador ECW de GDAL **lee siempre**. Escribir necesita ademas la SDK con clave OEM.
Preguntar `GetDriverByName("ECW")` y dar por hecho que se puede escribir es lo que produce
un trabajo que corre veinte minutos y muere al final. Por eso `Disponibilidad` distingue, y
por eso lleva `alternativas`: cuando algo no se puede, la respuesta util no es «no», es
«no, y esto si».
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# --- Estados de una celda de la matriz de capacidades -----------------------
# Tres y no dos, porque para quien mira son tres cosas distintas: funciona ahora,
# funcionaria si instalas algo (y aqui va la sugerencia), y nadie sabe hacerlo.
DISPONIBLE = "disponible"
INSTALABLE = "instalable"
NO_SOPORTADO = "no-soportado"


@dataclass(frozen=True)
class ParDeFormatos:
    origen: str
    destino: str

    def __str__(self) -> str:
        return f"{self.origen} -> {self.destino}"


@dataclass(frozen=True)
class Disponibilidad:
    disponible: bool
    #: La cadena de version exacta, tal cual la da la herramienta: "GDAL 3.12.4, released
    #: 2026/04/22". Se congela en el trabajo al arrancar, y es lo que permite diagnosticar
    #: un "ayer funcionaba" seis meses despues.
    version: str = ""
    codigo_motivo: str = ""
    mensaje: str = ""
    sugerencia: str = ""
    alternativas: tuple[str, ...] = ()

    @classmethod
    def si(cls, version: str) -> Disponibilidad:
        return cls(disponible=True, version=version)

    @classmethod
    def no(
        cls,
        codigo_motivo: str,
        mensaje: str,
        *,
        sugerencia: str = "",
        alternativas: tuple[str, ...] = (),
        version: str = "",
    ) -> Disponibilidad:
        return cls(
            disponible=False,
            version=version,
            codigo_motivo=codigo_motivo,
            mensaje=mensaje,
            sugerencia=sugerencia,
            alternativas=alternativas,
        )


@dataclass(frozen=True)
class OpcionDeMotor:
    """Un ajuste que el motor sabe pasar.

    El formulario **se genera desde aqui**. No es comodidad: es la unica forma de que el
    formulario no pueda ofrecer algo que el motor no sabe traducir a un argumento.
    """

    nombre: str
    etiqueta: str
    tipo: str  # "texto" | "entero" | "decimal" | "eleccion" | "booleano"
    por_defecto: object = None
    elecciones: tuple[tuple[str, str], ...] = ()
    minimo: float | None = None
    maximo: float | None = None
    ayuda: str = ""


@dataclass(frozen=True)
class PlanDeEjecucion:
    """Lo que hay que hacer, descrito. El runner lo ejecuta."""

    argv: tuple[str, ...]
    ruta_de_salida: Path
    #: Comandos que se ejecutan **despues** del principal y antes de verificar, con el mismo
    #: entorno. Existe porque las piramides son un `gdaladdo` aparte: no hay forma de
    #: pedirlas a `gdal_translate`. Se ejecutan en orden y un fallo en cualquiera detiene el
    #: trabajo -- una salida sin sus piramides es una salida distinta de la que se pidio.
    posteriores: tuple[tuple[str, ...], ...] = ()
    #: Variables del entorno del **proceso hijo**. Nunca se tocan las del servidor: es
    #: donde viaja la clave de ECW, y no puede acabar en un log del padre.
    env: dict[str, str] = field(default_factory=dict)
    #: Siempre un temporal local. Una ruta de red como directorio de trabajo rompe varias
    #: herramientas de formas que no dan un error claro.
    cwd: Path | None = None
    timeout_s: int = 3600
    #: Recibe una linea de la salida y devuelve la fraccion completada, o `None` si esa
    #: linea no habla de progreso.
    analizador_de_progreso: Callable[[str], float | None] | None = None


@dataclass(frozen=True)
class Verificacion:
    """El resultado de mirar la salida. `correcta=False` significa que se borra."""

    correcta: bool
    motivo: str = ""
    codigo_motivo: str = ""
    detalles: dict = field(default_factory=dict)


class Motor(abc.ABC):
    #: Identificador estable. Se guarda en el trabajo y aparece en la matriz.
    id: str = ""
    nombre: str = ""
    familia: str = ""
    #: Cuando dos motores disponibles saben el mismo par, gana el numero menor.
    prioridad: int = 100

    @abc.abstractmethod
    def pares(self) -> frozenset[ParDeFormatos]:
        """Que sabe convertir, disponible o no. La matriz lo necesita para poder pintar
        una celda apagada con su motivo en vez de dejar un hueco."""

    @abc.abstractmethod
    def disponibilidad(self) -> Disponibilidad:
        """Si esta en esta maquina. **Nunca ejecuta una conversion**, y a ser posible
        tampoco lanza el programa: esto se consulta al pintar una pagina."""

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return ()

    @abc.abstractmethod
    def plan(self, trabajo) -> PlanDeEjecucion:
        """El comando a lanzar para este trabajo."""

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        """Mirar la salida y decidir si sirve.

        La implementacion por omision comprueba lo minimo, y lo minimo ya atrapa el error
        mas caro: **el codigo de salida no es la prueba de que funciono**. ODA devuelve 0
        sin convertir nada; GDAL devuelve 0 tras dejar un archivo vacio si el controlador
        fallo al cerrar. Lo que se comprueba es que el archivo exista y no este vacio.
        """
        if not salida.exists():
            return Verificacion(
                correcta=False,
                motivo="El motor termino sin escribir ningun archivo.",
                codigo_motivo="sin-salida",
            )
        if salida.stat().st_size == 0:
            return Verificacion(
                correcta=False,
                motivo="El archivo de salida quedo vacio.",
                codigo_motivo="salida-invalida",
            )
        return Verificacion(correcta=True, detalles={"bytes": salida.stat().st_size})
