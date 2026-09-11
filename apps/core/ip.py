"""De dónde viene la petición, cuando hay un nginx delante.

Sin esto, django-axes lee `REMOTE_ADDR`, que con un proxy es **siempre la dirección del
proxy**. Todos los usuarios comparten una sola IP, y entonces el bloqueo por intentos
fallidos deja de distinguir a nadie: ocho equivocaciones de cualquiera dejan fuera a toda la
oficina durante el tiempo de enfriamiento. Es el fallo operativo más probable del primer día
de una instalación compartida.

## Esto confía en una cabecera, y una cabecera la escribe quien quiera

Es seguro aquí por **dos** razones, y las dos tienen que seguir siendo ciertas:

1. **Gunicorn escucha en un socket unix**, no en un puerto. La única forma de llegar a la
   aplicación es a través de nginx. Si algún día se cambia a TCP, cualquiera en la red puede
   mandar la cabecera a mano y el bloqueo se vuelve evadible.
2. **nginx la sobrescribe, no la añade.** Va con `proxy_set_header X-Forwarded-For
   $remote_addr` y no con el habitual `$proxy_add_x_forwarded_for`, que *anexa*: con ese,
   alguien que mande `X-Forwarded-For: 9.9.9.9` produce `9.9.9.9, <la de verdad>`, y basta
   con leer mal la lista para volver al problema.

Aun así se toma **la última** de la lista y no la primera, que es la defensa que queda si
alguien cambia la configuración de nginx sin leer esto: la última es la que observó el proxy
más cercano, la primera es la que pudo inventarse el cliente.
"""

from __future__ import annotations

#: Lo que cabe en el campo de la base de axes. Una IPv6 son 45 caracteres como mucho.
MAXIMO = 45


def ip_del_cliente(request) -> str:
    """La dirección del cliente, mirando la cabecera que pone el proxy."""
    cadena = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if cadena:
        return cadena.split(",")[-1].strip()[:MAXIMO]
    return (request.META.get("REMOTE_ADDR") or "")[:MAXIMO]
