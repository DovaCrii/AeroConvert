"""El sistema de referencia, dicho por su nombre y no solo por su numero.

## Por que hace falta

`EPSG:32719` no le dice nada a nadie que no se lo sepa de memoria, y **el numero solo es
peligroso**: 32718 y 32719 son husos contiguos, se diferencian en una cifra, y confundirlos
mueve el trabajo seiscientos kilometros. Con el nombre al lado —«WGS 84 / UTM zone 19S»— el
error salta a la vista.

La ficha del archivo ya lo hacia, porque ahi el `Crs` viaja entero con su `nombre` dentro. El
recibo de verificacion no: ahi se guardo el codigo a secas dentro de un JSON.

## Por que se resuelve al mostrar y no al guardar

Se penso en anadir `epsg_nombre` junto al codigo en el momento de verificar. Resolverlo aqui
tiene una ventaja concreta que la otra via no tiene: **los trabajos que ya estaban en la base
salen con nombre sin tocar una sola fila**. Y el nombre no es un dato del trabajo: es una
propiedad del codigo, que no cambia.

El coste es cero en la practica — `nombre_epsg` esta cacheado y PROJ solo se abre la primera
vez que aparece cada codigo.
"""

from __future__ import annotations

from django import template

from .. import crs as crs_mod

register = template.Library()


@register.filter
def nombre_del_crs(codigo) -> str:
    """El nombre legible de un EPSG, o cadena vacia si PROJ no lo conoce.

    Acepta `32719`, `"32719"` y `"EPSG:32719"`, porque por el proyecto circulan las tres
    formas y una etiqueta de plantilla que solo entiende una es una etiqueta que falla en
    silencio justo donde no se mira.

        EPSG:{{ codigo }}
        {% with n=codigo|nombre_del_crs %}{% if n %} — {{ n }}{% endif %}{% endwith %}

    El `if` no sobra: sin nombre quedaria un guion suelto colgando del numero.
    """
    return crs_mod.nombre_epsg(codigo) if codigo else ""
