"""`apps.vuelos` no se enreda con `apps.documents` más de lo estrictamente compartido (F18.13).

## Por qué se vigila

Los vuelos de dron salieron de `apps/documents/` para poder crecer a su ritmo y alimentar al visor
(F19) sin arrastrar las cuarenta y una herramientas de documentos. Esa separación dura **mientras
nadie importe por comodidad** una función de PDF desde un módulo de vuelos: basta una, y el día que
se quiera mover o probar aparte vuelve a estar pegado.

Lo que sí comparten, y por tanto se permite, es lo que **no es de documentos sino de la aplicación
que documentos hospeda**:

- la cola (`cola`), que encola el trabajo y lo despacha;
- la entrada de archivos (`views._comun`: subir del equipo o andar la carpeta compartida);
- `composicion.ComposicionInvalida`, el error con el que todo motor dice «esto no se puede»;
- `motor.disponibilidad`, que dice si una herramienta está apagada y por qué (regla 4).

Las pruebas (`test_*.py`) quedan fuera: ejercen `motor` y `tarea` a propósito, porque lo que
comprueban es justamente la cadena entera.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent

#: Lo único de `apps.documents` que un módulo de vuelos puede importar, con el motivo.
LISTA_BLANCA = {
    "apps.documents.cola": "la cola de trabajos",
    "apps.documents.composicion": "ComposicionInvalida",
    "apps.documents.views._comun": "la entrada de archivos",
    "apps.documents.motor": "disponibilidad(): el motivo de una herramienta apagada",
}


def _modulos_de_vuelos() -> list[Path]:
    return sorted(p for p in RAIZ.rglob("*.py") if not p.name.startswith("test_"))


def _importaciones(ruta: Path) -> list[tuple[int, str]]:
    paquete = ["apps", "vuelos", *ruta.relative_to(RAIZ).parent.parts]
    return _importaciones_de(ruta.read_text(encoding="utf-8"), paquete)


def _importaciones_de(texto: str, paquete: list[str]) -> list[tuple[int, str]]:
    """Cada módulo importado, como nombre absoluto con punto.

    Las importaciones relativas se resuelven contra `paquete` para que `from ...documents import
    x` no se escape por no llevar escrito `apps.`.
    """
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
            # `from apps.documents import cola`: lo importado también cuenta como submódulo.
            encontradas += [(nodo.lineno, f"{modulo}.{a.name}") for a in nodo.names]
    return encontradas


def _permitida(modulo: str) -> bool:
    return any(modulo == ok or modulo.startswith(ok + ".") for ok in LISTA_BLANCA)


def test_hay_modulos_que_vigilar():
    nombres = {p.name for p in _modulos_de_vuelos()}
    assert {"vuelo_ppk.py", "pantalla_vuelo.py", "urls.py"} <= nombres


@pytest.mark.parametrize("ruta", _modulos_de_vuelos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_solo_importa_de_documents_lo_compartido(ruta):
    ajenas = [
        (linea, modulo)
        for linea, modulo in _importaciones(ruta)
        if (modulo == "apps.documents" or modulo.startswith("apps.documents."))
        and not _permitida(modulo)
        # `from apps.documents import cola` genera `apps.documents` (el paquete) y
        # `apps.documents.cola`; solo el segundo dice qué se importa de verdad.
        and modulo != "apps.documents"
    ]
    assert not ajenas, (
        f"{ruta.relative_to(RAIZ)} importa de apps.documents algo que no es compartido: {ajenas}. "
        "Si de verdad lo es, añádalo a LISTA_BLANCA con su motivo; si no, no lo importe."
    )


def test_la_lista_blanca_no_se_infla_en_silencio():
    """Cuatro entradas. Añadir una quinta es una decisión, no un descuido."""
    assert len(LISTA_BLANCA) == 4


def test_la_vigilancia_detecta_lo_que_debe():
    """El vigilante no puede ser uno que da verde por no mirar: comprueba que sí ve un intruso."""
    texto = (
        "from apps.documents import dividir\n"
        "from ...documents import tamano\n"
        "import apps.documents.ocr\n"
    )
    vistas = [m for _, m in _importaciones_de(texto, ["apps", "vuelos", "views"])]
    assert "apps.documents.dividir" in vistas
    assert "apps.documents.tamano" in vistas
    assert "apps.documents.ocr" in vistas
    assert not any(_permitida(m) for m in vistas if m != "apps.documents")
