"""Buscar un sistema de referencia por nombre, zona o código, sin saber el EPSG.

Quien mide no siempre sabe que «WGS 84 / UTM 19 sur» es el 32719: sabe que trabajó en «UTM 19
sur» o en «SIRGAS». La lista sale de la base de PROJ que ya trae `pyproj`, así que no hay
biblioteca nueva ni nada copiado.

**Esto no adivina el sistema** (regla 3 de `AGENTS.md`): no hay valor por omisión, con la caja
vacía no se ofrece nada, y el orden de los resultados lo decide **solo lo escrito**, nunca una
idea de cuál es «el más probable». Elegir uno de la lista es declararlo, igual que teclear su
número.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

LIMITE = 12

#: Una consulta más corta que esto devuelve demasiado: 5 000 sistemas empiezan por «u».
MINIMO_DE_LETRAS = 2

#: Del texto del área de uso solo cabe un trozo en una fila (y el de WGS 84 enumera el mundo).
AREA_MAX = 110


@dataclass(frozen=True)
class Resultado:
    codigo: int
    nombre: str
    tipo: str
    area: str

    @property
    def epsg(self) -> str:
        return f"EPSG:{self.codigo}"


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin if unicodedata.category(c) != "Mn")


def _terminos(texto: str) -> list[str]:
    """Lo escrito, dicho como lo dice PROJ: «utm 19 sur» es «utm zone 19s»."""
    t = _plano(texto)
    t = re.sub(r"\bepsg\s*:?\s*", "", t)
    t = re.sub(r"\butm\s*(?:zona\s*)?(\d{1,2})\s*(sur|s|norte|n)\b", _utm, t)
    t = re.sub(r"\b(\d{1,2})\s*(sur|norte)\b", _utm_corto, t)
    t = re.sub(r"\bzona\b", "zone", t)
    return t.split()


def _letra(texto: str) -> str:
    return "s" if texto.startswith("s") else "n"


def _utm(m: re.Match) -> str:
    return f"utm zone {m.group(1)}{_letra(m.group(2))}"


def _utm_corto(m: re.Match) -> str:
    return f"zone {m.group(1)}{_letra(m.group(2))}"


@lru_cache(maxsize=1)
def _catalogo() -> tuple[tuple[Resultado, str], ...]:
    """Los sistemas vigentes de EPSG, proyectados y geográficos, con su texto de búsqueda."""
    try:
        from pyproj.database import query_crs_info
        from pyproj.enums import PJType
    except ImportError:  # pragma: no cover - pyproj es dependencia dura
        return ()

    filas = []
    for info in query_crs_info(
        auth_name="EPSG",
        pj_types=[PJType.PROJECTED_CRS, PJType.GEOGRAPHIC_2D_CRS],
        allow_deprecated=False,
    ):
        area = (info.area_of_use.name if info.area_of_use else "") or ""
        area = area if len(area) <= AREA_MAX else area[: AREA_MAX - 1].rstrip(" ,;") + "…"
        tipo = "proyectado" if info.type == PJType.PROJECTED_CRS else "geográfico"
        resultado = Resultado(int(info.code), info.name, tipo, area)
        plano = _plano(f"{info.name} {area}")
        # Con y sin espacios: «wgs84» y «wgs 84» llegan al mismo sitio.
        filas.append((resultado, f"{plano} {plano.replace(' ', '')}"))
    return tuple(filas)


def buscar(texto: str, limite: int = LIMITE) -> list[Resultado]:
    """Los sistemas que cuadran con lo escrito, o nada si lo escrito es muy poco.

    Con un número busca por código; con palabras, todas tienen que aparecer en el nombre o en
    el área («chile utm 19 sur»). El orden: el código exacto, luego los que empiezan por lo
    escrito, luego los demás por nombre. **Nunca** por popularidad.
    """
    limpio = (texto or "").strip()
    if len(limpio) < MINIMO_DE_LETRAS:
        return []

    como_codigo = re.fullmatch(r"(?:epsg\s*:?\s*)?(\d{3,6})", limpio, re.IGNORECASE)
    if como_codigo:
        codigo = como_codigo.group(1)
        return sorted(
            (r for r, _ in _catalogo() if str(r.codigo).startswith(codigo)),
            key=lambda r: (str(r.codigo) != codigo, r.codigo),
        )[:limite]

    terminos = _terminos(limpio)
    if not terminos:
        return []
    acertados = [(r, texto_r) for r, texto_r in _catalogo() if all(t in texto_r for t in terminos)]
    primero = terminos[0]
    acertados.sort(
        key=lambda par: (
            not _plano(par[0].nombre).startswith(primero),
            par[0].nombre,
            par[0].codigo,
        )
    )
    return [r for r, _ in acertados[:limite]]
