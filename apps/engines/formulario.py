"""Convierte lo que un motor declara en `opciones()` en campos de formulario, y de vuelta.

## Por que existe este modulo

Porque la alternativa es escribir el formulario a mano, y entonces hay **dos** listas de lo
que el motor acepta: la que el motor declara y la que el formulario ofrece. Se
desincronizan, y ya paso una vez en este proyecto -- los perfiles de destino estaban
escritos con las claves de GDAL en vez de las del motor, asi que el perfil de Civil 3D
prometia descartar la banda alfa y **no lo hacia**. Nada fallaba: simplemente no pasaba.

Con este modulo hay una sola lista. El formulario no puede ofrecer un ajuste que el motor
no sepa traducir, ni al reves.

## Y por que se valida aqui aunque no haya inyeccion posible

El `argv` se construye como lista y se lanza con `shell=False`, asi que un valor con
espacios no puede partirse en dos argumentos: no hay inyeccion de comandos. Pero un
`QUALITY=999` si llega a GDAL, y GDAL falla veinte minutos despues con un mensaje que no
menciona la opcion. Validar contra lo declarado convierte eso en un error inmediato y
legible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Motor, OpcionDeMotor, ParDeFormatos

TIPOS = ("texto", "entero", "decimal", "eleccion", "booleano")


class OpcionInvalida(Exception):
    def __init__(self, nombre: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.nombre = nombre
        self.mensaje = mensaje


@dataclass(frozen=True)
class Campo:
    """Un ajuste, listo para pintar. La plantilla no decide nada: solo dibuja."""

    opcion: OpcionDeMotor
    valor: object = None

    @property
    def nombre(self) -> str:
        return self.opcion.nombre

    @property
    def etiqueta(self) -> str:
        return self.opcion.etiqueta

    @property
    def ayuda(self) -> str:
        return self.opcion.ayuda

    @property
    def es_eleccion(self) -> bool:
        return self.opcion.tipo == "eleccion"

    @property
    def es_booleano(self) -> bool:
        return self.opcion.tipo == "booleano"

    @property
    def es_numero(self) -> bool:
        return self.opcion.tipo in ("entero", "decimal")

    @property
    def paso(self) -> str:
        """El `step` del `<input type=number>`. Un entero con paso decimal deja teclear
        `2,5` y luego lo rechaza el servidor, lo cual es confuso."""
        return "1" if self.opcion.tipo == "entero" else "any"

    @property
    def elecciones(self) -> tuple[tuple[str, str], ...]:
        return self.opcion.elecciones

    @property
    def marcado(self) -> bool:
        return bool(self.valor)

    @property
    def minimo(self):
        return self.opcion.minimo

    @property
    def maximo(self):
        return self.opcion.maximo


@dataclass
class Formulario:
    """Los campos de un par origen→destino, con los valores que se le hayan puesto."""

    par: ParDeFormatos
    campos: tuple[Campo, ...] = field(default_factory=tuple)
    errores: dict[str, str] = field(default_factory=dict)

    @property
    def hay_campos(self) -> bool:
        return bool(self.campos)

    @property
    def valores(self) -> dict:
        return {c.nombre: c.valor for c in self.campos}


def construir(motor: Motor, par: ParDeFormatos, valores: dict | None = None) -> Formulario:
    """El formulario de ese par, con los valores dados o los del motor."""
    puestos = valores or {}
    campos = tuple(
        Campo(opcion=opcion, valor=puestos.get(opcion.nombre, opcion.por_defecto))
        for opcion in motor.opciones(par)
    )
    return Formulario(par=par, campos=campos)


def leer(motor: Motor, par: ParDeFormatos, datos) -> dict:
    """Saca de los datos enviados solo lo que el motor declara, ya convertido y validado.

    **Lo que no esta declarado se descarta en silencio.** No es un error del que avisar: es
    un campo que sobra, y quien lo mando no es la persona -- es un formulario viejo en una
    pestana abierta desde ayer, o alguien probando. Lo que si es un error es un valor
    declarado con contenido imposible, y eso levanta.
    """
    resultado: dict = {}
    for opcion in motor.opciones(par):
        if opcion.nombre not in datos:
            # Un desmarcado no llega en el POST: hay que distinguirlo de «no enviado».
            if opcion.tipo == "booleano":
                resultado[opcion.nombre] = False
            continue
        resultado[opcion.nombre] = _convertir(opcion, datos.get(opcion.nombre))
    return resultado


def _convertir(opcion: OpcionDeMotor, crudo):
    if opcion.tipo == "booleano":
        return str(crudo).strip().lower() in ("1", "true", "on", "si", "sí")

    texto = str(crudo if crudo is not None else "").strip()

    if opcion.tipo == "eleccion":
        permitidos = [valor for valor, _ in opcion.elecciones]
        if texto not in permitidos:
            raise OpcionInvalida(
                opcion.nombre,
                f"«{texto}» no es una opción de {opcion.etiqueta}.",
            )
        return texto

    if opcion.tipo in ("entero", "decimal"):
        if not texto:
            return opcion.por_defecto
        # Se acepta la coma decimal: es lo que teclea quien tiene el teclado en espanol, y
        # rechazarla seria pedantear con la persona en vez de con el dato.
        normalizado = texto.replace(",", ".")
        try:
            numero = int(normalizado) if opcion.tipo == "entero" else float(normalizado)
        except ValueError as fallo:
            esperado = "un número entero" if opcion.tipo == "entero" else "un número"
            raise OpcionInvalida(
                opcion.nombre, f"{opcion.etiqueta} necesita {esperado}, no «{texto}»."
            ) from fallo
        if opcion.minimo is not None and numero < opcion.minimo:
            raise OpcionInvalida(
                opcion.nombre, f"{opcion.etiqueta} no puede bajar de {opcion.minimo:g}."
            )
        if opcion.maximo is not None and numero > opcion.maximo:
            raise OpcionInvalida(
                opcion.nombre, f"{opcion.etiqueta} no puede pasar de {opcion.maximo:g}."
            )
        return numero

    return texto
