"""El sistema de referencia, dicho por su nombre y no solo por su número.

`EPSG:32719` no le dice nada a quien no se lo sepa de memoria. Y el número solo es además
**peligroso**: 32718 y 32719 son husos contiguos, se diferencian en una cifra, y confundirlos
mueve el trabajo seiscientos kilómetros. Con «WGS 84 / UTM zone 19S» al lado, el error salta a
la vista antes de mandar nada al cliente.
"""

from __future__ import annotations

import pytest
from django.template import Context, Template

from apps.formats import crs as crs_mod
from apps.formats.templatetags.referencia import nombre_del_crs


class TestElNombre:
    @pytest.mark.parametrize("entrada", [32719, "32719", "EPSG:32719", " epsg:32719 "])
    def test_acepta_las_tres_formas_que_circulan(self, entrada):
        """Por el proyecto viajan el entero, la cadena y la cadena con prefijo. Una etiqueta
        que solo entiende una falla en silencio justo donde nadie mira."""
        assert nombre_del_crs(entrada) == "WGS 84 / UTM zone 19S"

    def test_los_husos_contiguos_se_distinguen(self):
        """**El motivo de que esto exista.** Una cifra de diferencia, seiscientos kilómetros."""
        assert nombre_del_crs(32718) != nombre_del_crs(32719)
        assert "18S" in nombre_del_crs(32718)

    @pytest.mark.parametrize("nada", ["", None, "no-es-un-codigo", 0])
    def test_lo_que_no_es_un_codigo_no_revienta(self, nada):
        """Sale de un JSON guardado hace meses: puede ser cualquier cosa. Una plantilla que
        levanta deja la pantalla entera en un 500 por un dato decorativo."""
        assert nombre_del_crs(nada) == ""

    def test_un_codigo_que_proj_no_conoce_devuelve_vacio(self):
        assert crs_mod.nombre_epsg(999_999) == ""


class TestEnLaPlantilla:
    def _pintar(self, valor):
        plantilla = Template(
            "{% load referencia %}EPSG:{{ v }}"
            "{% with n=v|nombre_del_crs %}{% if n %} — {{ n }}{% endif %}{% endwith %}"
        )
        return plantilla.render(Context({"v": valor}))

    def test_sale_el_numero_y_el_nombre(self):
        assert self._pintar("32719") == "EPSG:32719 — WGS 84 / UTM zone 19S"

    def test_y_solo_el_numero_cuando_no_hay_nombre(self):
        """Sin nombre no se pinta un guion suelto colgando del número."""
        assert self._pintar("999999") == "EPSG:999999"


class TestElRecibo:
    """Que el recibo del trabajo lo use de verdad. Las de arriba pueden pasar todas y la
    plantilla seguir enseñando el número pelado."""

    def test_el_progreso_carga_la_etiqueta(self):
        from pathlib import Path

        from django.conf import settings

        crudo = (Path(settings.BASE_DIR) / "templates" / "jobs" / "_progreso.html").read_text(
            encoding="utf-8"
        )
        assert "referencia" in crudo.split("\n")[0], "Falta cargar la etiqueta."
        assert "nombre_del_crs" in crudo, "El recibo volvió a enseñar el número a secas."
