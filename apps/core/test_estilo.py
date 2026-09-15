"""La regla de escritura, comprobada sobre lo que de verdad se lee en pantalla.

**Mayúscula inicial solo en la primera palabra.** «Marca de agua», no «Marca de Agua».

## Por qué esta prueba entiende las excepciones, y no podría no entenderlas

Una versión ingenua —«ninguna palabra que no sea la primera empieza por mayúscula»— da
**cuarenta y ocho** avisos sobre el repositorio actual, y los cuarenta y ocho son correctos:

- «Unir **PDF**», «**Word**, **Excel** o **PowerPoint** a PDF», «Excel a **Markdown**»: nombres
  propios, siglas y formatos.
- «Pone «3 / 56» en cada hoja. **S**in numerar la portada, si no quieres»: segunda frase, o sea
  ortografía y no estilo.

Una prueba que avisa cuarenta y ocho veces sin razón se desactiva a la semana, y entonces deja
de vigilar también lo que sí importaba. Así que distingue las tres cosas, y el precio es una
lista de nombres propios que hay que mantener — barata, y visible cuando falta.

Ver `docs/ESTILO.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

#: Lo que se pinta tal cual en una pantalla. No se miran los comentarios del código: son para
#: quien programa y ahí importa otra cosa.
CLAVES = ("titulo_pagina", "etiqueta_seccion", "proposito", "nombre", "que_hace", "sale")

#: Nombres propios, marcas y formatos. **Van en mayúscula esté donde esté la palabra.**
#:
#: Traducirlos o bajarlos a minúscula haría que alguien buscara en Google algo que no existe,
#: que es el mismo razonamiento que ya gobierna `catalogo.Formato.nombre`.
PROPIOS = {
    # Programas y marcas
    "word",
    "excel",
    "powerpoint",
    "office",
    "outlook",
    "windows",
    "linux",
    "qgis",
    "arcgis",
    "autocad",
    "civil",
    "google",
    "earth",
    "explorador",
    "aeroconvert",
    "aerocontrol",
    "aerobim",
    "aerolink",
    "tailscale",
    "markdown",
    # Los catálogos de tubería: «Access» es el programa de Microsoft y «Plant 3D» el de
    # Autodesk. Los dos entraron el 2026-09-15 y esta prueba los cazó el mismo día.
    "access",
    "plant",
    # Formatos y siglas
    "pdf",
    "pdfs",
    "docx",
    "xlsx",
    "xlsm",
    "pptx",
    "csv",
    "epub",
    "html",
    "htm",
    "jpg",
    "jpeg",
    "png",
    "tif",
    "tiff",
    "geotiff",
    "bigtiff",
    "cog",
    "jp2",
    "ecw",
    "mrsid",
    "img",
    "asc",
    "shp",
    "shapefile",
    "gpkg",
    "geopackage",
    "geojson",
    "kml",
    "kmz",
    "dxf",
    "dwg",
    "landxml",
    "las",
    "laz",
    "copc",
    "ifc",
    "crs",
    "epsg",
    "wgs84",
    "utm",
    "ocr",
    "aes",
    "rgb",
    "ppp",
    "http",
    "https",
    "url",
    "api",
    "id",
    "gb",
    "mb",
    "kb",
}

#: Donde acaba una frase. Después de cualquiera de estos, la mayúscula es obligatoria.
FIN_DE_FRASE = re.compile(r"[.!?:;»)]\s+$|—\s+$")


def _visibles() -> list[tuple[str, str, str]]:
    """`(archivo, clave, texto)` de todo lo que se enseña, sacado de las vistas."""
    patron = re.compile(r'"(' + "|".join(CLAVES) + r')":\s*\(?\s*"([^"]{4,200})"')
    salida = []
    for fichero in sorted((Path(settings.BASE_DIR) / "apps").rglob("*.py")):
        if "test" in fichero.name:
            continue
        for encontrado in patron.finditer(fichero.read_text(encoding="utf-8")):
            salida.append((fichero.name, encontrado.group(1), encontrado.group(2)))
    return salida


def _rotulos() -> list[tuple[str, str]]:
    """`(plantilla, texto)` de los rótulos `eyebrow`, que son los que encabezan cada bloque."""
    salida = []
    for fichero in sorted((Path(settings.BASE_DIR) / "templates").rglob("*.html")):
        for encontrado in re.finditer(
            r'class="eyebrow"[^>]*>([^<{]+)<', fichero.read_text("utf-8")
        ):
            texto = encontrado.group(1).strip()
            if texto:
                salida.append((fichero.name, texto))
    return salida


def mayusculas_de_mas(texto: str) -> list[str]:
    """Las palabras en mayúscula que no deberían estarlo.

    Se recorre el texto entero llevando la cuenta de si toca principio de frase, en vez de
    partirlo primero: una abreviatura o un «3 / 56» dentro de la frase desordenarían el corte.
    """
    sobran = []
    principio = True
    for pieza in re.finditer(r"\S+\s*", texto):
        crudo = pieza.group(0)
        palabra = crudo.strip()
        # Fuera la puntuación de los extremos. **Con una expresión y no con `strip()`**: a
        # `strip()` se le pasa un conjunto de caracteres, no una cadena, así que `.strip("-256")`
        # quitaba cualquier guion, dos, cinco o seis de los bordes. Con «AES-256» daba el
        # resultado correcto por pura casualidad.
        limpia = re.sub(r"^\W+|\W+$", "", palabra, flags=re.UNICODE)

        if limpia and limpia[0].isalpha():
            if not principio and limpia[0].isupper():
                # Una sigla no es una mayúscula inicial. Se mira **solo la parte con letras**,
                # que es lo que hace que «AES-256» y «A4» cuenten como siglas igual que «PDF».
                letras = "".join(c for c in limpia if c.isalpha())
                es_sigla = letras.isupper()
                if not es_sigla and limpia.lower() not in PROPIOS:
                    sobran.append(palabra)
            principio = False

        if FIN_DE_FRASE.search(crudo) or palabra.endswith(("«", "—")):
            principio = True
    return sobran


class TestLaMayusculaInicial:
    @pytest.mark.parametrize(("origen", "clave", "texto"), _visibles(), ids=lambda v: str(v)[:40])
    def test_en_lo_que_pintan_las_vistas(self, origen, clave, texto):
        sobran = mayusculas_de_mas(texto)
        assert not sobran, f"{origen} · {clave}: «{texto}» → sobran mayúsculas en {sobran}"

    @pytest.mark.parametrize(("plantilla", "texto"), _rotulos(), ids=lambda v: str(v)[:40])
    def test_en_los_rotulos_de_bloque(self, plantilla, texto):
        sobran = mayusculas_de_mas(texto)
        assert not sobran, f"{plantilla}: «{texto}» → sobran mayúsculas en {sobran}"


class TestQueLaPruebaSirvaDeAlgo:
    """**Lo que separa esto de una prueba que siempre pasa.**

    Si `PROPIOS` creciera hasta tragárselo todo, o si el detector dejara de mirar, estas tres
    seguirían pasando sin decirlo. Aquí se comprueba que caza lo que tiene que cazar.
    """

    def test_caza_el_titulo_a_la_inglesa(self):
        assert mayusculas_de_mas("Marca de Agua") == ["Agua"]
        assert mayusculas_de_mas("Sacar el Contenido a Markdown") == ["Contenido"]

    def test_y_deja_pasar_los_nombres_propios(self):
        assert mayusculas_de_mas("Word, Excel o PowerPoint a PDF") == []
        assert mayusculas_de_mas("Excel a Markdown") == []

    def test_las_siglas_con_numero_pasan_por_sus_letras(self):
        """«AES-256» y «A4» son siglas aunque lleven cifras. Se mira solo la parte con letras.

        La versión anterior usaba `.strip("-256")`, que a `strip()` no se le pasa una cadena
        sino un **conjunto de caracteres**: quitaba cualquier guion, dos, cinco o seis de los
        extremos. Daba el resultado correcto para «AES-256» por casualidad.
        """
        assert mayusculas_de_mas("Le pone contraseña, con AES-256.") == []
        assert mayusculas_de_mas("Fotos en un solo documento, en A4 o al tamaño original") == []

    def test_y_deja_pasar_la_segunda_frase(self):
        assert mayusculas_de_mas("Pone «3 / 56» en cada hoja. Sin numerar la portada.") == []
        assert mayusculas_de_mas("El texto que el PDF ya tiene. Si es un escaneo, se dice.") == []

    def test_hay_algo_que_mirar(self):
        """Si los extractores dejaran de encontrar nada, las de arriba pasarían vacías."""
        assert len(_visibles()) > 30
        assert len(_rotulos()) > 10
