"""El registro de motores y la matriz de capacidades.

El registro es **explicito**: cada familia llama a `registrar()` desde el `ready()` de su
`AppConfig`. Nada de escanear modulos buscando subclases -- los efectos secundarios de
import rompen `makemigrations --check` de formas que cuestan una tarde entera de encontrar.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import DISPONIBLE, INSTALABLE, NO_SOPORTADO, Motor, ParDeFormatos

_MOTORES: dict[str, Motor] = {}


def registrar(motor: Motor) -> None:
    if not motor.id:
        raise ValueError("Un motor sin id no se puede registrar.")
    _MOTORES[motor.id] = motor


def limpiar() -> None:
    """Vacia el registro. Solo lo usan las pruebas."""
    _MOTORES.clear()


def todos() -> tuple[Motor, ...]:
    return tuple(sorted(_MOTORES.values(), key=lambda m: (m.prioridad, m.id)))


def motores_para(par: ParDeFormatos) -> tuple[Motor, ...]:
    """Todos los que dicen saber ese par, **esten disponibles o no**.

    Que devuelva tambien los no disponibles es el punto: sin ellos la matriz no podria
    pintar una celda apagada con su motivo, y una capacidad ausente se veria igual que una
    inexistente.
    """
    return tuple(m for m in todos() if par in m.pares())


def motor_para(par: ParDeFormatos) -> Motor | None:
    """El disponible de menor prioridad, o `None`."""
    for motor in motores_para(par):
        if motor.disponibilidad().disponible:
            return motor
    return None


@dataclass(frozen=True)
class CeldaDeCapacidad:
    origen: str
    destino: str
    estado: str
    motor_id: str = ""
    version: str = ""
    codigo_motivo: str = ""
    mensaje: str = ""
    sugerencia: str = ""
    alternativas: tuple[str, ...] = ()

    @property
    def se_puede(self) -> bool:
        return self.estado == DISPONIBLE


def celda(par: ParDeFormatos) -> CeldaDeCapacidad:
    candidatos = motores_para(par)
    if not candidatos:
        return CeldaDeCapacidad(
            origen=par.origen,
            destino=par.destino,
            estado=NO_SOPORTADO,
            codigo_motivo="sin-motor",
            mensaje="Todavía no hay ningún motor para esta conversión.",
        )

    fallos = []
    for motor in candidatos:
        estado = motor.disponibilidad()
        if estado.disponible:
            return CeldaDeCapacidad(
                origen=par.origen,
                destino=par.destino,
                estado=DISPONIBLE,
                motor_id=motor.id,
                version=estado.version,
            )
        fallos.append((motor, estado))

    # Ninguno disponible. Se reporta el primero por prioridad: es el que se usaria.
    #
    # Y si **todos** los que saben este par dicen que no se va a poder nunca, la celda no es
    # «instalable»: es «no soportado» -- pero con su motivo y su remedio, que es lo que la
    # distingue de un hueco vacio. Presentar RCS como instalable mandaria a alguien a buscar
    # un paquete que no existe.
    motor, estado = fallos[0]
    todos_irremediables = all(e.irremediable for _, e in fallos)
    return CeldaDeCapacidad(
        origen=par.origen,
        destino=par.destino,
        estado=NO_SOPORTADO if todos_irremediables else INSTALABLE,
        motor_id=motor.id,
        codigo_motivo=estado.codigo_motivo,
        mensaje=estado.mensaje,
        sugerencia=estado.sugerencia,
        alternativas=estado.alternativas,
    )


def matriz_de_capacidades() -> dict[tuple[str, str], CeldaDeCapacidad]:
    """Todas las celdas que algun motor declara. Lo consultan la pantalla de motores, la
    API y el selector de destino del formulario -- los tres desde aqui, para que no puedan
    discrepar."""
    pares: set[ParDeFormatos] = set()
    for motor in todos():
        pares |= motor.pares()
    return {(p.origen, p.destino): celda(p) for p in sorted(pares, key=str)}
