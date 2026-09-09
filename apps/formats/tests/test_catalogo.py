"""Invariantes del catalogo. Cierran la puerta a errores que no darian sintoma."""

from apps.formats import catalogo


class TestCoherencia:
    def test_la_clave_coincide_con_el_codigo(self):
        for clave, formato in catalogo.FORMATOS.items():
            assert clave == formato.codigo

    def test_toda_familia_declarada_existe(self):
        for formato in catalogo.FORMATOS.values():
            assert formato.familia in catalogo.FAMILIAS, formato.codigo

    def test_las_extensiones_empiezan_con_punto(self):
        for formato in catalogo.FORMATOS.values():
            for extension in formato.extensiones:
                assert extension.startswith("."), (formato.codigo, extension)

    def test_un_formato_que_no_se_lee_ni_se_escribe_tiene_que_explicarse(self):
        """Estar en el catálogo sin poder hacer nada con él es legítimo **y útil**: quien
        suelte un `.rcs` merece leer «esto sale de ReCap, expórtalo a E57» en vez de
        «formato no reconocido», que suena a fallo de la aplicación.

        Lo que no es legítimo es estar ahí sin decir por qué. La invariante original pedía
        que todo formato fuera legible o escribible; esta pide algo más útil.
        """
        for formato in catalogo.FORMATOS.values():
            if formato.admite_lectura or formato.admite_escritura:
                continue
            assert formato.nota, (
                f"«{formato.codigo}» no se lee ni se escribe y no dice por qué. "
                "Un hueco sin explicación es peor que no tener la entrada."
            )


class TestBigtiffEsUnaEntradaPropia:
    """Si BigTIFF fuera una bandera de GeoTIFF, la matriz no podria decir que uno abre en
    Civil 3D y el otro no. Es el diagnostico principal del producto."""

    def test_existen_los_dos(self):
        assert "geotiff" in catalogo.FORMATOS
        assert "bigtiff" in catalogo.FORMATOS

    def test_comparten_extension(self):
        assert catalogo.FORMATOS["geotiff"].extensiones == catalogo.FORMATOS["bigtiff"].extensiones

    def test_tienen_firmas_distintas(self):
        geotiff = set(catalogo.FORMATOS["geotiff"].firmas)
        bigtiff = set(catalogo.FORMATOS["bigtiff"].firmas)
        assert not (geotiff & bigtiff)

    def test_la_extension_tif_devuelve_varios_candidatos(self):
        codigos = {f.codigo for f in catalogo.por_extension(".tif")}
        assert {"geotiff", "bigtiff", "cog"} <= codigos


class TestMrsid:
    def test_se_lee_pero_nunca_se_escribe(self):
        """Escribir MrSID exige el SDK de Extensis. Declararlo escribible haria aparecer
        una columna que fallaria siempre."""
        mrsid = catalogo.FORMATOS["mrsid"]
        assert mrsid.admite_lectura is True
        assert mrsid.admite_escritura is False
        assert mrsid not in catalogo.escribibles()


class TestConPerdida:
    def test_los_formatos_con_perdida_estan_marcados(self):
        """La marca decide como se escribe la asercion del oraculo: igualdad de
        estadisticas para los sin perdida, piso de PSNR para los demas."""
        for codigo in ("jp2", "ecw", "mrsid", "jpeg"):
            assert catalogo.FORMATOS[codigo].con_perdida is True

    def test_geotiff_y_cog_no_son_con_perdida(self):
        for codigo in ("geotiff", "bigtiff", "cog", "img", "asc"):
            assert catalogo.FORMATOS[codigo].con_perdida is False


class TestAcompanantes:
    def test_el_shapefile_declara_los_suyos(self):
        """Un .shp sin su .dbf ni su .prj no es un shapefile: es un tercio de uno."""
        acompanantes = catalogo.FORMATOS["shp"].acompanantes
        assert {".shx", ".dbf", ".prj"} <= acompanantes

    def test_los_geoespaciales_sin_crs_incrustado_esperan_un_prj(self):
        """Acotado a las familias geoespaciales a proposito.

        Un OBJ tambien lleva acompanante (`.mtl`) y tampoco lleva CRS dentro, pero no es
        que le falte: **una malla no tiene sistema de referencia que perder**. Exigirle un
        `.prj` seria pedirle algo que no existe en ese formato.
        """
        geoespaciales = {catalogo.RASTER, catalogo.NUBE, catalogo.VECTOR}
        for formato in catalogo.FORMATOS.values():
            if formato.familia not in geoespaciales:
                continue
            if formato.acompanantes and not formato.lleva_crs_incrustado:
                assert ".prj" in formato.acompanantes, formato.codigo
