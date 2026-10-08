"""Anotar cuándo cambia lo que el equipo puede hacer. Ver `models.RegistroDeSonda`."""

from __future__ import annotations

from dataclasses import dataclass

from . import registry
from .models import RegistroDeSonda


@dataclass(frozen=True)
class Cambio:
    motor: str
    antes: str  # «» si es la primera vez que se ve
    ahora: str
    registro: RegistroDeSonda


def _firma(disponible: bool, codigo: str, version: str) -> tuple:
    return (disponible, codigo or "", version or "")


def registrar() -> list[Cambio]:
    """Sondea cada motor y anota **solo lo que cambió** desde la última fila de ese motor.

    Devuelve los cambios de esta pasada. No lanza ninguna conversión: usa lo mismo que pinta la
    pantalla de compatibilidad.
    """
    cambios: list[Cambio] = []
    for motor in registry.todos():
        estado = motor.disponibilidad()
        nueva = _firma(estado.disponible, estado.codigo_motivo, estado.version)
        ultima = RegistroDeSonda.objects.filter(motor=motor.id).first()
        if (
            ultima is not None
            and _firma(ultima.disponible, ultima.codigo_motivo, ultima.version) == nueva
        ):
            continue
        fila = RegistroDeSonda.objects.create(
            motor=motor.id,
            disponible=estado.disponible,
            codigo_motivo=estado.codigo_motivo or "",
            mensaje=estado.mensaje or "",
            version=estado.version or "",
        )
        cambios.append(Cambio(motor.id, describir(ultima) if ultima else "", describir(fila), fila))
    return cambios


def describir(fila: RegistroDeSonda) -> str:
    if fila.disponible:
        return f"disponible ({fila.version})" if fila.version else "disponible"
    return f"apagado: {fila.codigo_motivo}" if fila.codigo_motivo else "apagado"


def recientes(cuantos: int = 15) -> list[RegistroDeSonda]:
    """Las últimas filas, de la más nueva a la más vieja."""
    return list(RegistroDeSonda.objects.all()[:cuantos])
