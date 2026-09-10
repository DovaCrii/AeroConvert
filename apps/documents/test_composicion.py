"""Componer un PDF: qué páginas, en qué orden y hacia dónde miran.

No es una conversión. El resto de la aplicación coge un archivo y lo lleva a otro formato;
aquí se cogen varios, se eligen páginas sueltas de cada uno, se ordenan y algunas se giran.

La comprobación de fondo es que **lo que sale es lo que se pidió**: tantas páginas como se
eligieron, en el orden pedido, y con el giro pedido. Y se comprueba releyendo el resultado
con el lector, que es código distinto del que lo escribió.
"""

import pytest

from apps.documents import composicion
from apps.formats import pdf


def _pdf(tmp_path, paginas, nombre):
    """Un PDF real. `paginas` son pares (ancho_mm, alto_mm, giro)."""
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for ancho_mm, alto_mm, giro in paginas:
        pagina = escritor.add_blank_page(
            width=ancho_mm / pdf.MM_POR_PUNTO, height=alto_mm / pdf.MM_POR_PUNTO
        )
        if giro:
            pagina.rotate(giro)
    ruta = tmp_path / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


@pytest.fixture
def memoria(tmp_path):
    """Tres hojas A4 verticales: una memoria de cálculo."""
    return _pdf(tmp_path, [(210, 297, 0)] * 3, "memoria.pdf")


@pytest.fixture
def planos(tmp_path):
    """Dos láminas A1, la segunda ya girada. Como salen de AutoCAD."""
    return _pdf(tmp_path, [(841, 594, 0), (594, 841, 270)], "planos.pdf")


class TestUnirEntero:
    def test_junta_los_dos_archivos_en_orden(self, tmp_path, memoria, planos):
        receta = composicion.receta_de_archivos([memoria, planos])
        resultado = composicion.componer(receta, tmp_path / "entrega.pdf")

        assert resultado.paginas_escritas == 5
        assert dict(resultado.por_archivo) == {"memoria.pdf": 3, "planos.pdf": 2}

    def test_y_el_orden_de_la_lista_es_el_del_pdf(self, tmp_path, memoria, planos):
        """Primero los planos y después la memoria, si así se pide."""
        receta = composicion.receta_de_archivos([planos, memoria])
        destino = tmp_path / "entrega.pdf"
        composicion.componer(receta, destino)

        leido = pdf.leer_cabecera(destino)
        assert [p.orientacion for p in leido.paginas] == [
            "apaisada",
            "apaisada",
            "vertical",
            "vertical",
            "vertical",
        ]

    def test_los_originales_no_se_tocan(self, tmp_path, memoria, planos):
        antes = (memoria.read_bytes(), planos.read_bytes())
        composicion.componer(composicion.receta_de_archivos([memoria, planos]), tmp_path / "e.pdf")
        assert (memoria.read_bytes(), planos.read_bytes()) == antes


class TestElegirPaginas:
    def test_solo_las_que_se_piden(self, tmp_path, memoria, planos):
        """La portada de la memoria y la primera lámina, y nada más."""
        receta = [
            composicion.PaginaElegida(memoria, 1),
            composicion.PaginaElegida(planos, 1),
        ]
        resultado = composicion.componer(receta, tmp_path / "resumen.pdf")
        assert resultado.paginas_escritas == 2

    def test_se_puede_repetir_una_pagina(self, tmp_path, memoria):
        """Una portada que va delante y detrás es un caso real de entrega."""
        receta = [composicion.PaginaElegida(memoria, n) for n in (1, 2, 3, 1)]
        assert composicion.componer(receta, tmp_path / "x.pdf").paginas_escritas == 4

    def test_pedir_una_pagina_que_no_existe_lo_dice(self, tmp_path, memoria):
        with pytest.raises(composicion.ComposicionInvalida) as fallo:
            composicion.componer([composicion.PaginaElegida(memoria, 9)], tmp_path / "x.pdf")
        assert "tiene 3 página(s)" in str(fallo.value)

    def test_una_receta_vacia_no_escribe_un_pdf_de_cero_paginas(self, tmp_path):
        """Un PDF sin páginas es válido, abre en cualquier visor y no enseña nada. Es un
        error, no un resultado."""
        with pytest.raises(composicion.ComposicionInvalida):
            composicion.componer([], tmp_path / "vacio.pdf")

    def test_un_archivo_que_no_esta(self, tmp_path):
        with pytest.raises(composicion.ComposicionInvalida) as fallo:
            composicion.componer(
                [composicion.PaginaElegida(tmp_path / "fantasma.pdf", 1)], tmp_path / "x.pdf"
            )
        assert "No hay ningún archivo" in str(fallo.value)


class TestGirarLaminas:
    def test_poner_una_vertical_en_apaisada(self, tmp_path, memoria):
        """Es lo que se pide de verdad: una hoja de texto entre planos, tumbada."""
        receta = [composicion.PaginaElegida(memoria, 1, giro=90)]
        destino = tmp_path / "girada.pdf"
        composicion.componer(receta, destino)

        assert pdf.leer_cabecera(destino).paginas[0].orientacion == "apaisada"

    def test_el_giro_se_suma_al_que_la_pagina_ya_traia(self, tmp_path, planos):
        """La segunda lámina tiene la caja vertical y `/Rotate=270`, así que **se ve
        apaisada**. Pedirle 90 más la deja en 360 —es decir, sin giro— y entonces se ve
        vertical.

        Es lo que espera quien mira la pantalla: ve una hoja tumbada, pulsa girar, y la ve
        de pie. Tratar el giro como absoluto obligaría a saber qué traía el archivo por
        dentro, que es justo lo que nadie sabe ni tiene por qué.
        """
        antes = pdf.leer_cabecera(planos).paginas[1]
        assert antes.orientacion == "apaisada"
        assert antes.giro == 270

        destino = tmp_path / "enderezada.pdf"
        composicion.componer([composicion.PaginaElegida(planos, 2, giro=90)], destino)

        despues = pdf.leer_cabecera(destino).paginas[0]
        assert despues.giro == 0
        assert despues.orientacion == "vertical"

    def test_girar_no_engorda_el_archivo(self, tmp_path, memoria):
        """`/Rotate` es un número en el diccionario de la página: no se vuelve a dibujar
        nada, así que se puede ofrecer sin advertir de ninguna pérdida."""
        sin_girar = tmp_path / "a.pdf"
        girada = tmp_path / "b.pdf"
        composicion.componer([composicion.PaginaElegida(memoria, 1)], sin_girar)
        composicion.componer([composicion.PaginaElegida(memoria, 1, giro=90)], girada)

        assert abs(girada.stat().st_size - sin_girar.stat().st_size) < 200

    @pytest.mark.parametrize("grados", [45, 1, -1, 360, 91])
    def test_un_giro_que_un_pdf_no_admite_se_rechaza(self, tmp_path, memoria, grados):
        with pytest.raises(composicion.ComposicionInvalida):
            composicion.PaginaElegida(memoria, 1, giro=grados)

    @pytest.mark.parametrize("grados", composicion.GIROS)
    def test_los_cuatro_validos_se_aceptan(self, tmp_path, memoria, grados):
        assert composicion.PaginaElegida(memoria, 1, giro=grados).giro == grados


class TestLaRecetaDePartida:
    def test_son_todas_las_paginas_de_todos(self, memoria, planos):
        receta = composicion.receta_de_archivos([memoria, planos])
        assert [(p.archivo.name, p.numero) for p in receta] == [
            ("memoria.pdf", 1),
            ("memoria.pdf", 2),
            ("memoria.pdf", 3),
            ("planos.pdf", 1),
            ("planos.pdf", 2),
        ]

    def test_y_ninguna_viene_girada(self, memoria):
        """El giro es una decisión de quien compone, no algo que se herede sin querer."""
        assert all(p.giro == 0 for p in composicion.receta_de_archivos([memoria]))

    def test_una_pagina_se_cuenta_desde_uno(self, memoria):
        with pytest.raises(composicion.ComposicionInvalida):
            composicion.PaginaElegida(memoria, 0)
