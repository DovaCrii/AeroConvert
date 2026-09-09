"""Almacen de estaticos: el manifiesto, sin morir por un mapa de fuentes que no existe.

`CompressedManifestStaticFilesStorage` reescribe las referencias que encuentra dentro del
CSS y del JS para que apunten al nombre con huella. Entre esas referencias cuenta el
comentario final que dejan los minificadores:

    /*# sourceMappingURL=bootstrap.min.css.map */

Nosotros vendorizamos el minificado y **no** el mapa: es una ayuda de depuracion de cientos
de kilobytes que ningun navegador pide salvo con las herramientas de desarrollo abiertas. El
manifiesto, en cambio, exige que toda referencia se resuelva, y `collectstatic` aborta:

    The file 'vendor/bootstrap.bundle.min.js.map' could not be found.

Y abortar `collectstatic` no se queda ahi. En `taller` no hay manifiesto, y sin manifiesto la
primera etiqueta `{% static %}` revienta: **todas** las paginas devuelven 500. El sintoma que
llega a la pantalla es una pagina con el HTML nuevo y los estilos viejos, que se lee como un
error de diseno y no lo es. Ver `test_arranque.py`.

## Por que no se arregla en los archivos

Habia tres salidas y dos son peores:

- **Vendorizar los mapas.** Suma casi un megabyte al repositorio para algo que nadie sirve.
- **Borrar el comentario del minificado.** Rompe el `integrity` de la plantilla — el hash
  SRI se calcula sobre los bytes exactos — y el navegador bloquea la hoja entera. El
  arreglo causaria justo el fallo que intenta arreglar.
- **Que el almacen no persiga los mapas.** Un mapa ausente no rompe nada: el navegador
  pide el `.map` solo si alguien abre las herramientas, y recibe un 404 que no afecta a la
  pagina. Es esta.

Los patrones se filtran a partir de los del padre en vez de reescribirse: asi una version
nueva de Django que anada patrones los sigue aplicando, y solo se cae el de los mapas.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage

MARCA_DE_MAPA = "sourceMappingURL"


def _sin_mapas_de_fuentes(patrones):
    """Devuelve los patrones del padre menos los que resuelven `sourceMappingURL`.

    La forma de `patterns` es `((glob, (regla, ...)), ...)`, donde cada regla es o un patron
    a secas o una pareja `(patron, plantilla)`. Se mira siempre el patron, que es el primer
    elemento cuando hay pareja.
    """
    filtrados = []
    for glob, reglas in patrones:
        conservadas = tuple(
            regla
            for regla in reglas
            if MARCA_DE_MAPA not in (regla[0] if isinstance(regla, (tuple, list)) else regla)
        )
        filtrados.append((glob, conservadas))
    return tuple(filtrados)


class AlmacenDeEstaticos(CompressedManifestStaticFilesStorage):
    """El almacen de produccion y de taller."""

    patterns = _sin_mapas_de_fuentes(CompressedManifestStaticFilesStorage.patterns)
