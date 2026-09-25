"""La contraseña de «Proteger», entre la pantalla y el obrero.

## El problema

Hasta la fase 9 la contraseña entraba en un POST, se usaba en la misma petición y se iba con
ella. Al pasar por la cola deja de ser posible: quien la recibe es gunicorn y quien la usa es
el obrero, **otro proceso**, a veces segundos después. Algo tiene que llevarla de uno a otro.

## Por dónde no va

Por ningún sitio que se quede:

- **ni en la base** —`options`, `JobEvent`, nada—: se copia en cada respaldo y se lee con
  cualquier cliente de SQLite;
- **ni en el argv del hijo**: el corredor lo escribe entero en la bitácora, y en Linux lo ve
  cualquiera con `ps`;
- **ni en el encargo**: es un archivo en claro que describe el trabajo.

## Por dónde va

Un archivo propio del trabajo en la carpeta de trabajo, **cifrado con Fernet** y una clave
derivada de `SECRET_KEY`. El obrero lo **lee y lo borra en el mismo paso**, y se lo pasa al
hijo por la variable de entorno `AEROCONVERT_CONTRASENA`, que no se registra.

Conviene decir lo que el cifrado protege y lo que no. **No protege de quien tiene la máquina
entera**: con `SECRET_KEY` se descifra. Protege de lo que sí pasa de verdad: que la carpeta de
trabajo acabe en una copia, en un listado o en la pantalla de alguien con la clave legible.

## Y cuánto dura

Lo que tarde el obrero en cogerlo, y **como mucho una hora**: el nombre lleva la marca
`.parcial.`, así que el barrido de huérfanos se lo lleva aunque el trabajo nunca llegue a
correr, y Fernet además rechaza un testigo de más de una hora. Si pasa, el trabajo falla con
`falta-la-contrasena` y «Reintentar» lleva a la pantalla a escribirla otra vez: **reintentar
sin volver a pedirla es imposible por diseño**.
"""

from __future__ import annotations

import base64
from pathlib import Path

from django.conf import settings

from . import tarea

#: La variable de entorno por la que la recibe el hijo. Se define en `tarea`, que no puede
#: importar nada que traiga Django, y aquí se nombra para el lado del padre.
VARIABLE = tarea.VARIABLE_CONTRASENA

#: Segundos que vale un testigo. Ver el docstring: la misma hora que el barrido.
VIGENCIA_S = 3600

#: Para que la clave derivada no coincida con ninguna otra que salga de `SECRET_KEY`.
_PROPOSITO = b"aeroconvert/documentos/secretos-de-trabajo/v1"


class SinSecreto(Exception):
    """No hay contraseña para este trabajo: caducó, ya se usó, o nunca se guardó."""


def _fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    clave = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_PROPOSITO).derive(
        settings.SECRET_KEY.encode("utf-8")
    )
    return Fernet(base64.urlsafe_b64encode(clave))


def ruta(job) -> Path:
    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{job.pk}.parcial.secreto"


def guardar(job, contrasena: str) -> None:
    """Deja la contraseña para el obrero. Solo la puede leer este trabajo, y una vez."""
    destino = ruta(job)
    destino.parent.mkdir(parents=True, exist_ok=True)
    testigo = _fernet().encrypt(contrasena.encode("utf-8"))
    # `x`: si ya hubiera uno sería de otro intento, y pisarlo sin saberlo es peor que fallar.
    with open(destino, "xb") as salida:
        salida.write(testigo)
    try:
        destino.chmod(0o600)
    except OSError:  # pragma: no cover - en Windows chmod solo toca el bit de solo lectura
        pass


def tomar(job) -> str:
    """Lee la contraseña **y la borra**. Levanta `SinSecreto` si no está o ya no vale."""
    from cryptography.fernet import InvalidToken

    origen = ruta(job)
    try:
        testigo = origen.read_bytes()
    except FileNotFoundError as fallo:
        raise SinSecreto("No hay contraseña guardada para este trabajo.") from fallo
    finally:
        olvidar(job)

    try:
        return _fernet().decrypt(testigo, ttl=VIGENCIA_S).decode("utf-8")
    except InvalidToken as fallo:
        raise SinSecreto("La contraseña guardada caducó o no se puede leer.") from fallo


def olvidar(job) -> None:
    """Borra el archivo si sigue ahí. Se llama en cada final, bueno o malo."""
    try:
        ruta(job).unlink(missing_ok=True)
    except OSError:
        pass
