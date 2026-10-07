"""La convención de nombres (F13.2) y que los nombres viejos sigan encontrando su herramienta.

**Tres patrones mezclados** había: verbo + objeto («Unir PDF»), sustantivo («Marca de agua») y
frase larga («Reconocer el texto de un escaneo»). Ahora:

- **conversiones** como «Origen a destino» («PDF a Word», «T02, T04 y crudos a RINEX»);
- **operaciones** con un verbo en infinitivo al frente («Poner marca de agua», «Reconocer texto
  (OCR)»);
- **programas de destino** por su nombre, con el propósito debajo («QGIS» y «Para analizar y hacer
  mapas»);
- y **como mucho 28 caracteres**: lo que no quepa va en `que_hace`.

Lo que se quedó sin nombre nuevo se sigue encontrando por el viejo: quien recuerda «Marca de agua»
o «Llevarlo a QGIS» no tiene que enterarse de que cambió.
"""

from __future__ import annotations

import re

import pytest

from apps.dashboard import acciones as acciones_mod
from apps.dashboard import taxonomia

LIMITE = 28
INFINITIVO = re.compile(r"^\w+(ar|er|ir)\b", re.IGNORECASE)


def _documentos():
    return [a for a in acciones_mod.todas() if a.id.startswith("pdf-")]


def _perfiles():
    return [a for a in acciones_mod.todas() if a.id.startswith("perfil-")]


class TestLaConvencion:
    def test_ningun_nombre_pasa_de_28_caracteres(self):
        largos = [
            f"{a.nombre} ({len(a.nombre)})" for a in acciones_mod.todas() if len(a.nombre) > LIMITE
        ]
        assert not largos, largos

    @pytest.mark.parametrize("accion", _documentos(), ids=lambda a: a.id)
    def test_cada_herramienta_es_una_conversion_o_empieza_por_un_verbo(self, accion):
        es_conversion = " a " in accion.nombre
        assert es_conversion or INFINITIVO.match(accion.nombre), (
            f"«{accion.nombre}»: una conversión es «Origen a destino» y una operación empieza "
            "por un verbo en infinitivo"
        )

    @pytest.mark.parametrize("accion", _documentos(), ids=lambda a: a.id)
    def test_empieza_por_mayuscula_y_no_lleva_punto(self, accion):
        assert accion.nombre[0].isupper() and not accion.nombre.endswith(".")

    def test_los_programas_de_destino_son_el_programa_y_dicen_para_que_sirven_debajo(self):
        perfiles = [a for a in _perfiles() if a.categoria == "entregar"]
        assert len(perfiles) == 6
        for accion in perfiles:
            assert accion.para.startswith("Para "), accion.nombre
            assert "Llevarlo" not in accion.nombre and "·" not in accion.nombre

    def test_los_nombres_son_unicos(self):
        nombres = [a.nombre for a in acciones_mod.todas()]
        assert len(nombres) == len(set(nombres))

    def test_ninguna_herramienta_nueva_queda_sin_nombre_en_su_pantalla(self):
        """El nombre de la herramienta y el título de su pantalla no se contradicen."""
        from apps.documents.herramientas import HERRAMIENTAS

        assert all(h["nombre"].strip() for h in HERRAMIENTAS)
        assert {h["id"] for h in HERRAMIENTAS} == set(taxonomia.DE_DOCUMENTOS)


#: (lo que alguien recuerda y escribe, el nombre nuevo que tiene que aparecer)
VIEJOS = [
    ("Marca de agua", "Poner marca de agua"),
    ("Proteger PDF", "Proteger o desbloquear PDF"),
    ("Reconocer el texto de un escaneo", "Reconocer texto (OCR)"),
    ("Word, Excel o PowerPoint a PDF", "Office a PDF"),
    ("Catálogo de tubería a Excel", "Catálogo Plant 3D a Excel"),
    ("Excel a catálogo de tubería", "Excel a catálogo Plant 3D"),
    ("Datos de un receptor GNSS a RINEX", "T02, T04 y crudos a RINEX"),
    ("Llevarlo a QGIS", "QGIS"),
    ("Diseño y planos", "Civil 3D / AutoCAD"),
    ("Ver en el globo", "Google Earth"),
    ("Publicar en la web", "Visor web"),
    ("Modelos BIM", "AeroBim"),
]


class TestLosNombresViejosSiguenEncontrando:
    @pytest.mark.parametrize(("viejo", "nuevo"), VIEJOS)
    def test_buscar_por_el_nombre_viejo_halla_la_herramienta(self, viejo, nuevo):
        nombres = [a.nombre for g in acciones_mod.por_categoria(viejo) for a in g["acciones"]]
        assert nuevo in nombres, f"«{viejo}» ya no encuentra «{nuevo}»: {nombres}"
