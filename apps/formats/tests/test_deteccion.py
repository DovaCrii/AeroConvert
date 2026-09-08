"""La inspeccion: que hay dentro, y cuanto nos fiamos."""

import pytest

from apps.formats import deteccion

from .constructor import ASC_MINIMO, PRJ_METASHAPE, bigtiff_minimo, geotiff_minimo


def _crear(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    if isinstance(contenido, str):
        ruta.write_text(contenido, encoding="utf-8")
    else:
        ruta.write_bytes(contenido)
    return ruta


class TestLaFirmaManda:
    def test_distingue_bigtiff_de_geotiff_con_la_misma_extension(self, tmp_path):
        clasico = deteccion.inspeccionar(_crear(tmp_path, "a.tif", geotiff_minimo()))
        grande = deteccion.inspeccionar(_crear(tmp_path, "b.tif", bigtiff_minimo()))
        assert clasico.codigo_formato == "geotiff"
        assert grande.codigo_formato == "bigtiff"
        assert clasico.confianza == deteccion.CONFIANZA_FIRMA

    def test_un_jp2_renombrado_a_tif_se_reconoce_por_dentro(self, tmp_path):
        """Pasa de verdad, y creer a la extension llevaria a una pantalla en blanco."""
        jp2 = b"\x00\x00\x00\x0cjP  \r\n\x87\n" + bytes(64)
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "mentira.tif", jp2))
        assert inspeccion.codigo_formato == "jp2"
        assert any("Gana el contenido" in aviso for aviso in inspeccion.avisos)

    def test_compartir_extension_no_es_discrepancia(self, tmp_path):
        """`.tif` es geotiff y bigtiff a la vez: avisar de eso seria ruido en cada archivo."""
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "b.tif", bigtiff_minimo()))
        assert inspeccion.avisos == () or all(
            "Gana el contenido" not in a for a in inspeccion.avisos
        )


class TestSinFirma:
    def test_un_asc_se_reconoce_por_extension_con_menos_confianza(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "terreno.asc", ASC_MINIMO))
        assert inspeccion.codigo_formato == "asc"
        assert inspeccion.confianza == deteccion.CONFIANZA_EXTENSION
        assert inspeccion.etiqueta_confianza == "supuesto por la extension"

    def test_una_extension_desconocida_no_se_inventa(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "cosa.zzz", b"\x01\x02\x03\x04"))
        assert inspeccion.reconocido is False
        assert inspeccion.codigo_formato == ""


class TestGeorreferencia:
    def test_el_crs_incrustado_gana(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", geotiff_minimo(epsg=32719)))
        assert inspeccion.crs.codigo == "32719"
        assert inspeccion.crs.origen == "incrustado"

    def test_sin_crs_dentro_se_mira_el_prj_de_al_lado(self, tmp_path):
        _crear(tmp_path, "x.prj", PRJ_METASHAPE)
        contenido = geotiff_minimo(epsg=None, escala_m=None, origen=None)
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", contenido))
        assert inspeccion.crs.codigo == "32719"
        assert inspeccion.crs.origen == "sidecar-prj"

    def test_sin_nada_el_crs_queda_desconocido_y_no_se_supone(self, tmp_path):
        contenido = geotiff_minimo(epsg=None, escala_m=None, origen=None)
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", contenido))
        assert inspeccion.crs.conocido is False


class TestAvisos:
    def test_avisa_de_bigtiff_innecesario(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", bigtiff_minimo()))
        assert any("sin necesitarlo" in aviso for aviso in inspeccion.avisos)

    def test_no_avisa_cuando_bigtiff_hacia_falta(self, tmp_path):
        contenido = bigtiff_minimo(ancho=40000, alto=40000, bandas=3)
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", contenido))
        assert not any("sin necesitarlo" in aviso for aviso in inspeccion.avisos)


class TestAcompanantes:
    def test_los_encuentra_y_dice_cuales_faltan(self, tmp_path):
        _crear(tmp_path, "x.tfw", "0.025577\n0\n0\n-0.025577\n495003.2\n7318841.8\n")
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "x.tif", geotiff_minimo()))
        presentes = {a.extension for a in inspeccion.acompanantes if a.presente}
        assert ".tfw" in presentes
        assert ".prj" not in presentes

    def test_al_shapefile_le_faltan_los_imprescindibles(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_crear(tmp_path, "z.shp", b"\x00\x00'\n" + bytes(96)))
        faltan = {a.extension for a in inspeccion.faltan_imprescindibles}
        assert {".shx", ".dbf", ".prj"} <= faltan


class TestOrigenIlegible:
    def test_un_archivo_que_no_existe_da_su_motivo(self, tmp_path):
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(tmp_path / "no-esta.tif")
        assert fallo.value.codigo == "origen-no-legible"

    def test_una_carpeta_no_es_un_archivo(self, tmp_path):
        with pytest.raises(deteccion.OrigenIlegible):
            deteccion.inspeccionar(tmp_path)

    def test_un_archivo_vacio_da_su_motivo(self, tmp_path):
        with pytest.raises(deteccion.OrigenIlegible):
            deteccion.inspeccionar(_crear(tmp_path, "vacio.tif", b""))


class TestHuella:
    def test_es_el_sha256_del_contenido(self, tmp_path):
        import hashlib

        contenido = geotiff_minimo()
        ruta = _crear(tmp_path, "x.tif", contenido)
        assert deteccion.huella(ruta) == hashlib.sha256(contenido).hexdigest()

    def test_informa_del_avance(self, tmp_path):
        """En un archivo de gigabytes la huella tarda minutos, y tiene que verse."""
        ruta = _crear(tmp_path, "x.bin", b"x" * 3_000_000)
        avances = []
        deteccion.huella(ruta, trozo=1_000_000, progreso=avances.append)
        assert len(avances) == 3
        assert avances[-1] == pytest.approx(1.0)
