"""Un RINEX que ya existe como origen: se reconoce por su nombre y se confirma al abrirlo."""

from __future__ import annotations

import pytest

from apps.formats import catalogo, deteccion

from .constructor import rinex_minimo


@pytest.mark.parametrize("extension", [".23o", ".24o", ".99o", ".rnx", ".obs", ".23O"])
def test_las_extensiones_de_observacion_apuntan_a_rinex_obs(extension):
    assert "rinex_obs" in {f.codigo for f in catalogo.por_extension(extension)}


@pytest.mark.parametrize("extension", [".23n", ".23g", ".o", ".2o", ".233o", ".zip"])
def test_la_navegacion_y_lo_que_no_es_un_nombre_de_rinex_no(extension):
    assert "rinex_obs" not in {f.codigo for f in catalogo.por_extension(extension)}


def test_un_rinex_de_verdad_se_reconoce_y_dice_su_version(tmp_path):
    ruta = tmp_path / "GMLA.23o"
    ruta.write_text(rinex_minimo(epocas=3), encoding="latin-1", newline="")
    inspeccion = deteccion.inspeccionar(ruta)
    assert inspeccion.codigo_formato == "rinex_obs"
    assert any("RINEX 3.04 de observación" in aviso for aviso in inspeccion.avisos)


def test_un_obs_que_no_es_rinex_se_declara_desconocido(tmp_path):
    """`.obs` lo usan otros programas: la extensión no promete nada."""
    ruta = tmp_path / "otra_cosa.obs"
    ruta.write_text("no soy un RINEX\n", encoding="latin-1")
    inspeccion = deteccion.inspeccionar(ruta)
    assert inspeccion.codigo_formato == ""
    assert any("pero no lo es" in aviso for aviso in inspeccion.avisos)


def test_un_rinex_de_navegacion_con_extension_obs_tampoco_vale(tmp_path):
    ruta = tmp_path / "nav.obs"
    cabecera = "     3.04           NAVIGATION DATA     M".ljust(60) + "RINEX VERSION / TYPE\n"
    ruta.write_text(cabecera + "".ljust(60) + "END OF HEADER\n", encoding="latin-1")
    assert deteccion.inspeccionar(ruta).codigo_formato == ""
