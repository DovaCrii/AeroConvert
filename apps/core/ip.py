"""De dónde viene la petición, cuando hay un proxy delante.

Sin esto, django-axes lee `REMOTE_ADDR`, que con un proxy es **siempre la dirección del
proxy** — `127.0.0.1` si termina en la propia máquina. Todos los usuarios comparten una sola
dirección, y el bloqueo por intentos fallidos deja de distinguir a nadie: ocho equivocaciones
de cualquiera dejan fuera a toda la oficina durante el tiempo de enfriamiento. Es el fallo
operativo más probable del primer día de una instalación compartida.

## Esto confía en una cabecera, y una cabecera la escribe quien quiera

Lo que lo hace seguro **no es la cabecera: es que la aplicación solo sea alcanzable a través
del proxy**. Gunicorn escucha en `127.0.0.1`, así que nada de fuera de la máquina puede
hablarle directamente y mandar la cabecera a mano. Si algún día se pone a escuchar en
`0.0.0.0`, esta función se vuelve falsificable y el bloqueo, evadible.

Se toma **la última** de la lista y no la primera, y esa es la defensa que queda si alguien
cambia el proxy sin leer esto: la última es la que observó el salto más cercano; la primera
es la que pudo inventarse quien llamó.

## Los dos montajes que existen aquí

**Tailscale directo** (`tailscale funnel --https=8443 127.0.0.1:8001`). Tailscale añade la
dirección real a `X-Forwarded-For`, así que la última es la buena. Y de paso manda
`Tailscale-Funnel-Request` cuando la petición viene de internet y no de la red privada —
`viene_de_internet()` lo usa.

**Con nginx en medio**, y aquí hay una trampa que ya se coló una vez: la configuración decía
`proxy_set_header X-Forwarded-For $remote_addr`, que es lo correcto cuando nginx es el
**primer** salto. Detrás de Tailscale, `$remote_addr` es `127.0.0.1` **para todo el mundo**, y
el bloqueo vuelve a ser «todos comparten una IP» — justo el defecto que esto arregla. Con un
proxy delante hay que usar `real_ip_header` para que `$remote_addr` sea la dirección de
verdad antes de reenviarla. Está escrito en `despliegue/aeroconvert.nginx.conf`.
"""

from __future__ import annotations

#: Lo que cabe en el campo de la base de axes. Una IPv6 son 45 caracteres como mucho.
MAXIMO = 45

#: La pone Tailscale cuando la peticion entro por Funnel, o sea desde internet abierto, y no
#: por la red privada. Es la unica forma de distinguirlas: las dos llegan por el mismo puerto.
CABECERA_DE_FUNNEL = "HTTP_TAILSCALE_FUNNEL_REQUEST"


def ip_del_cliente(request) -> str:
    """La dirección del cliente, mirando la cabecera que pone el proxy."""
    cadena = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if cadena:
        return cadena.split(",")[-1].strip()[:MAXIMO]
    return (request.META.get("REMOTE_ADDR") or "")[:MAXIMO]


def viene_de_internet(request) -> bool:
    """`True` si la petición entró por Funnel y no por la red privada de Tailscale.

    Sirve para lo que de verdad importa de esa distinción: **que quede escrito en el
    registro**. Una entrada desde la red del equipo y una desde internet abierto son dos
    cosas distintas, y el día que haya que revisar quién entró, esa columna es la diferencia
    entre saberlo y suponerlo.

    Devuelve `False` cuando no hay Tailscale delante, que es lo correcto: sin Funnel no hay
    internet abierto del que venir.
    """
    return bool(request.META.get(CABECERA_DE_FUNNEL))
