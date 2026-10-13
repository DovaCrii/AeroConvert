"""Las apps geoespaciales no dependen de `apps.documents` (F21.2, decisión D11).

## Por qué se vigila

AeroConvert es el motor geoespacial de la suite Aero; las herramientas de PDF, Office, EPUB, OCR y
video son de otra aplicación y saldrán a otro repositorio por etapas (inventario en
`docs/FRONTERA_DOCUMENTOS.md`; decisión en `docs/ARQUITECTURA_PRODUCTO.md`). Eso solo es
posible si lo geoespacial **no importa** documentos: basta un `from apps.documents import x` por
comodidad para que el corte vuelva a doler.

`apps/vuelos/test_independencia.py` ya vigila el caso de vuelos con más detalle; esta prueba cubre
las nueve apps geoespaciales con el mismo método (análisis de `ast`, sin importar nada) y además
vigila las dos formas de acoplamiento que un `import` no muestra: los nombres de ruta
`documents:...` y las plantillas `documents/...`.

Las pruebas (`test_*.py`) quedan fuera, como en vuelos: ejercen la cadena entera a propósito.

## Excepciones

Lo declarado abajo es **deuda a la vista, no permiso**. Cada entrada dice por qué
existe, y la prueba falla también cuando una entrada ya no hace falta (así la lista solo puede
encogerse en silencio).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

#: Las apps que hoy son geoespaciales. `mesh` y `targets` están casi vacías: entran para que, al
#: llenarse, nazcan ya separadas de documentos.
APPS_GEO = (
    "raster",
    "pointcloud",
    "vector",
    "gnss",
    "mesh",
    "visor",
    "vuelos",
    "formats",
    "targets",
)

#: Excepciones de importación, por app: lo único de `apps.documents` que puede importar, y por qué.
#: Hoy solo `vuelos`, cuyas herramientas (telemetría, fotos, vuelo PPK) viven registradas en la cola
#: de documentos. Deben coincidir con `LISTA_BLANCA` de `apps/vuelos/test_independencia.py`.
EXCEPCIONES_DE_IMPORT: dict[str, dict[str, str]] = {
    "vuelos": {
        "apps.documents.cola": "la cola de trabajos",
        "apps.documents.composicion": "ComposicionInvalida, el error con el que todo motor dice no",
        "apps.documents.views._comun": "la entrada de archivos (subida o carpeta compartida)",
        "apps.documents.motor": "disponibilidad(): el motivo de una herramienta apagada",
    },
}

#: Acoplamientos que no son `import`: archivo -> motivo. Nacen de que las pantallas y los trabajos
#: de vuelo se montan hoy bajo el espacio de nombres `documents:` (`apps/documents/urls.py` incluye
#: las rutas de vuelos) y de que sus plantillas reutilizan piezas de `templates/documents/`.
EXCEPCIONES_DE_RUTA_Y_PLANTILLA: dict[str, str] = {
    "apps/visor/vuelo.py": "enlaza a documents:vuelo_ver, vuelo_miniatura y vuelo_ficha",
    "templates/vuelos/telemetria.html": "incluye documents/_origen.html",
    "templates/vuelos/video.html": "incluye documents/_origen.html",
    "templates/vuelos/vuelo_dron.html": "incluye documents/_paso_vuelo.html",
    "templates/vuelos/vuelo_visor.html": "enlaza a documents:vuelo_datos, miniatura y ficha",
}

_RUTA_O_PLANTILLA = re.compile(
    r"""["'](?:documents:\w+|documents/[\w./-]+)["']|\{%\s*url\s+['"]documents:"""
)


def _modulos(app: str) -> list[Path]:
    base = RAIZ / "apps" / app
    return sorted(p for p in base.rglob("*.py") if not p.name.startswith("test_"))


def _leer(ruta: Path) -> str:
    # `read_bytes().decode` y no `read_text`: sin traducción de saltos de línea, igual en Windows
    # y en Linux.
    return ruta.read_bytes().decode("utf-8")


def _importaciones_de(texto: str, paquete: list[str]) -> list[tuple[int, str]]:
    """Cada módulo importado, con nombre absoluto (las relativas se resuelven contra `paquete`)."""
    encontradas: list[tuple[int, str]] = []
    for nodo in ast.walk(ast.parse(texto)):
        if isinstance(nodo, ast.Import):
            encontradas += [(nodo.lineno, a.name) for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                base = paquete[: len(paquete) - nodo.level + 1]
                modulo = ".".join([*base, *([nodo.module] if nodo.module else [])])
            else:
                modulo = nodo.module or ""
            encontradas.append((nodo.lineno, modulo))
            # `from apps import documents` y `from apps.documents import cola`: lo importado
            # también cuenta como submódulo.
            encontradas += [(nodo.lineno, f"{modulo}.{a.name}") for a in nodo.names]
    return encontradas


def _es_documents(modulo: str) -> bool:
    return modulo == "apps.documents" or modulo.startswith("apps.documents.")


def _intrusos(texto: str, paquete: list[str], permitidos: dict[str, str]) -> list[tuple[int, str]]:
    """Importaciones de `apps.documents` que no están declaradas."""
    return [
        (linea, modulo)
        for linea, modulo in _importaciones_de(texto, paquete)
        # `from apps.documents import cola` genera también `apps.documents` (el paquete): solo
        # `apps.documents.cola` dice qué se trae de verdad.
        if _es_documents(modulo)
        and modulo != "apps.documents"
        and not any(modulo == ok or modulo.startswith(ok + ".") for ok in permitidos)
    ]


def _paquete_de(ruta: Path) -> list[str]:
    relativa = ruta.relative_to(RAIZ)
    partes = list(relativa.with_suffix("").parts)
    return partes if ruta.name == "__init__.py" else partes[:-1]


def _todos() -> list[tuple[str, Path]]:
    return [(app, ruta) for app in APPS_GEO for ruta in _modulos(app)]


def test_hay_modulos_que_vigilar():
    por_app = {app: _modulos(app) for app in APPS_GEO}
    assert all(por_app[app] for app in APPS_GEO), {a: len(m) for a, m in por_app.items()}
    # Las que más pesan, para que un cambio de carpeta no deje la vigilancia mirando al vacío.
    assert {"motores.py"} <= {p.name for p in por_app["raster"]}
    assert {"terreno.py"} <= {p.name for p in por_app["visor"]}


@pytest.mark.parametrize(
    ("app", "ruta"), _todos(), ids=lambda v: v if isinstance(v, str) else v.name
)
def test_lo_geoespacial_no_importa_documents(app, ruta):
    ajenas = _intrusos(_leer(ruta), _paquete_de(ruta), EXCEPCIONES_DE_IMPORT.get(app, {}))
    assert not ajenas, (
        f"{ruta.relative_to(RAIZ).as_posix()} importa de apps.documents: {ajenas}. "
        "La frontera de F21.2 lo prohíbe; si de verdad es compartido, declárelo en "
        "EXCEPCIONES_DE_IMPORT con su motivo."
    )


def test_las_excepciones_de_import_siguen_haciendo_falta():
    """Una excepción que nadie usa ya es un permiso olvidado."""
    for app, permitidos in EXCEPCIONES_DE_IMPORT.items():
        vistas: set[str] = set()
        for ruta in _modulos(app):
            vistas |= {m for _, m in _importaciones_de(_leer(ruta), _paquete_de(ruta))}
        for ok in permitidos:
            assert any(m == ok or m.startswith(ok + ".") for m in vistas), (
                f"{app} ya no importa {ok}: quítelo de EXCEPCIONES_DE_IMPORT."
            )


def test_la_lista_de_excepciones_no_se_infla_en_silencio():
    """Solo vuelos, con cuatro entradas. Añadir otra es una decisión, no un descuido."""
    assert {a: len(v) for a, v in EXCEPCIONES_DE_IMPORT.items()} == {"vuelos": 4}


def test_las_excepciones_de_vuelos_son_las_de_su_prueba():
    """Una sola verdad: la lista de aquí y la de `apps/vuelos/test_independencia.py` coinciden."""
    from apps.vuelos.test_independencia import LISTA_BLANCA

    assert set(LISTA_BLANCA) == set(EXCEPCIONES_DE_IMPORT["vuelos"])


def _con_rutas_o_plantillas() -> set[str]:
    candidatas = [r for app in APPS_GEO for r in _modulos(app)]
    candidatas += [
        p
        for app in APPS_GEO
        for p in (RAIZ / "templates" / app).rglob("*.html")
        if (RAIZ / "templates" / app).is_dir()
    ]
    return {
        p.relative_to(RAIZ).as_posix() for p in candidatas if _RUTA_O_PLANTILLA.search(_leer(p))
    }


def test_rutas_y_plantillas_de_documents_estan_declaradas():
    encontradas = _con_rutas_o_plantillas()
    assert encontradas == set(EXCEPCIONES_DE_RUTA_Y_PLANTILLA), (
        f"sin declarar: {sorted(encontradas - set(EXCEPCIONES_DE_RUTA_Y_PLANTILLA))}; "
        f"ya no hacen falta: {sorted(set(EXCEPCIONES_DE_RUTA_Y_PLANTILLA) - encontradas)}"
    )


# ---------------------------------------------------------------------------------------------
# El oráculo del vigilante: tiene que fallar de verdad ante un intruso.
# ---------------------------------------------------------------------------------------------


def test_la_vigilancia_detecta_los_import_prohibidos():
    texto = (
        "from apps.documents import dividir\n"
        "from ...documents import tamano\n"
        "import apps.documents.ocr\n"
        "from apps import documents\n"
    )
    vistas = {m for _, m in _intrusos(texto, ["apps", "vuelos", "views"], {})}
    assert {"apps.documents.dividir", "apps.documents.tamano", "apps.documents.ocr"} <= vistas
    assert "apps.documents" in {m for _, m in _importaciones_de(texto, ["apps", "vuelos", "views"])}


def test_la_vigilancia_respeta_lo_declarado_y_nada_mas():
    texto = "from apps.documents.cola import encolar\nfrom apps.documents.ocr import x\n"
    intrusos = _intrusos(texto, ["apps", "raster"], {"apps.documents.cola": "la cola"})
    assert {m for _, m in intrusos} == {"apps.documents.ocr", "apps.documents.ocr.x"}


def test_un_modulo_sintetico_en_una_carpeta_temporal_se_detecta(tmp_path):
    """De punta a punta: un archivo real en disco con un intruso, leído como lee la prueba."""
    paquete = tmp_path / "apps" / "raster"
    paquete.mkdir(parents=True)
    limpio = paquete / "limpio.py"
    sucio = paquete / "sucio.py"
    limpio.write_bytes(b"from apps.formats import pdf\n")
    sucio.write_bytes(b"def f():\n    from apps.documents.office import convertir\n")

    assert _intrusos(_leer(limpio), ["apps", "raster"], {}) == []
    assert "apps.documents.office" in {
        m for _, m in _intrusos(_leer(sucio), ["apps", "raster"], {})
    }


def test_el_patron_de_rutas_y_plantillas_ve_lo_que_debe():
    assert _RUTA_O_PLANTILLA.search("reverse('documents:vuelo_ver', args=[1])")
    assert _RUTA_O_PLANTILLA.search('{% include "documents/_origen.html" %}')
    assert _RUTA_O_PLANTILLA.search("{% url 'documents:unir' %}")
    assert not _RUTA_O_PLANTILLA.search('reverse("visor:inicio")')
