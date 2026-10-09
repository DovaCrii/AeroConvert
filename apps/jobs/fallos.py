"""El fallo con motivo que el corredor levanta y `ejecutar` recoge (F11.8)."""

from __future__ import annotations

from . import motivos as motivos_mod


class TrabajoFallido(Exception):
    def __init__(self, codigo: str, mensaje: str = "") -> None:
        super().__init__(mensaje or motivos_mod.mensaje(codigo))
        self.codigo = codigo
        self.mensaje = mensaje or motivos_mod.mensaje(codigo)
