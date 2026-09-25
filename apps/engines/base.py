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


def ruta_parcial(destino: Path | str) -> Path:
    """El nombre del archivo a medio escribir, **conservando la extensión**.

    `salida.tif` → `salida.parcial.tif`, y `nube.copc.laz` → `nube.parcial.copc.laz`.

    Poner `.parcial` **al final** parecía lo natural y era un error de fondo: media
    herramienta geoespacial deduce el formato de la extensión, así que un
    `nube.copc.laz.parcial` no lo puede escribir PDAL ni leerlo `pdal info`. Se descubrió
    convirtiendo la nube de verdad, después de 37 segundos de trabajo tirados.

    Se corta en el **primer** punto, no en el último, porque las extensiones compuestas
    -- `.copc.laz`, `.aux.xml` -- son parte del formato y perderlas es el mismo problema.

    Vive aquí y no en el runner porque los motores también la necesitan: es a ese nombre al
    que escriben. Tenerla en dos sitios fue lo que permitió que se desincronizaran.
    """
    destino = Path(destino)
    raiz, punto, extensiones = destino.name.partition(".")
    if not punto:
        return destino.with_name(f"{raiz}.parcial")
    return destino.with_name(f"{raiz}.parcial.{extensiones}")


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
    #: `True` cuando esto **no se va a poder nunca**, haga lo que haga quien lo lea.
    #:
    #: Distinguirlo de «falta instalar algo» importa: RCS y RCP son binarios cerrados de
    #: Autodesk y no hay lector abierto ni lo va a haber. Presentarlos como «instalable»
    #: mandaría a alguien a buscar un paquete que no existe.
    irremediable: bool = False

    @classmethod
    def si(cls, version: str) -> Disponibilidad:
        return cls(disponible=True, version=version)

    @classmethod
    def nunca(
        cls,
        codigo_motivo: str,
        mensaje: str,
        *,
        sugerencia: str = "",
        alternativas: tuple[str, ...] = (),
    ) -> Disponibilidad:
        """No se puede, y no es cuestión de instalar nada. Pero sí hay un camino."""
        return cls(
            disponible=False,
            codigo_motivo=codigo_motivo,
            mensaje=mensaje,
            sugerencia=sugerencia,
            alternativas=alternativas,
            irremediable=True,
        )

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
    #: `True` cuando el archivo de salida **lo escribe un paso posterior**, no el principal.
    #:
    #: Por omision el runner comprueba que el parcial exista en cuanto termina el comando
    #: principal, y esa comprobacion es la regla numero uno del proyecto: el codigo de
    #: salida no es la prueba de que funciono. Pero hay conversiones que **no las hace una
    #: sola herramienta**: un LandXML lo lee un modulo nuestro -- OGR no sabe -- y lo
    #: escribe `ogr2ogr` a partir de un intermedio. Ahi el principal no produce el parcial
    #: y no tiene por que.
    #:
    #: Se declara en vez de mover la comprobacion para todos: en `gdal_translate` seguido
    #: de `gdaladdo`, el principal **si** escribe la salida, y comprobarlo ahi da un motivo
    #: mucho mas claro que dejar que `gdaladdo` falle sobre un archivo que no existe.
    salida_en_posteriores: bool = False
    #: Variables del entorno del **proceso hijo**. Nunca se tocan las del servidor: es
    #: donde viaja la clave de ECW, y no puede acabar en un log del padre.
    #: Fuera del `repr`: puede llevar la contraseña de «Proteger», y un plan que acabara en un
    #: registro o en una traza la dejaría escrita. Ver `apps/documents/secretos.py`.
    env: dict[str, str] = field(default_factory=dict, repr=False)
    #: Siempre un temporal local. Una ruta de red como directorio de trabajo rompe varias
    #: herramientas de formas que no dan un error claro.
    cwd: Path | None = None
    timeout_s: int = 3600
    #: Recibe una linea de la salida y devuelve la fraccion completada, o `None` si esa
    #: linea no habla de progreso.
    analizador_de_progreso: Callable[[str], float | None] | None = None
    #: `False` cuando la herramienta **no dice nada mientras trabaja**. PDAL es asi: no
    #: emite avance por ninguna via usable desde un subproceso.
    #:
    #: Importa mas de lo que parece. El detector de atasco del runner se apoya en que llegue
    #: alguna senal cada tanto; con una herramienta muda, un trabajo perfectamente sano se
    #: daria por atascado y **se mataria a si mismo** en cuanto pasara del umbral de
    #: silencio. Declararlo aqui es lo que permite al runner apoyarse solo en el presupuesto
    #: total de tiempo para estos motores.
    emite_progreso: bool = True
    #: `True` cuando **terminar sin archivo puede ser la respuesta correcta**.
    #:
    #: Es la excepción a la regla número uno, y por eso va declarada y no por omisión.
    #: Comprimir un PDF que ya venía comprimido lo engordaría, y entregar eso sería la peor
    #: respuesta; un escaneo no tiene texto que sacar a Markdown. En los dos casos lo correcto
    #: es no escribir nada **y decir por qué**.
    #:
    #: El runner no se fía de la ausencia: con esto puesto, además exige que el hijo lo haya
    #: **declarado** en su informe con un desenlace. Un hijo que simplemente no escribe sigue
    #: siendo `sin-salida`.
    salida_opcional: bool = False


@dataclass(frozen=True)
class CeldaVacia:
    """El hueco de la rejilla donde ningun motor declara nada.

    Existe para que la plantilla no tenga que distinguir entre «no hay celda» y «la celda
    dice que no se puede»: las dos se pintan igual y con el mismo atributo.
    """

    origen: str
    destino: str
    estado: str = NO_SOPORTADO
    codigo_motivo: str = ""
    mensaje: str = ""
    sugerencia: str = ""
    alternativas: tuple[str, ...] = ()

    @property
    def se_puede(self) -> bool:
        return False


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
