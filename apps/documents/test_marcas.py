"""Numerar y marcar.

Aquí hay **dos oráculos distintos y los dos son externos a este código**:

- *Qué dice* la marca lo lee el extractor de texto de pypdf, que no sabe nada de cómo se
  escribió.
- *Dónde cae* se comprueba **dibujando la página con PDFium y mirando los píxeles**. Es la
  única forma honesta de probar la geometría del giro: comprobarla contra mi propio cálculo
  sería el código dándose la razón, y el fallo que este módulo existe para evitar —el número
  de canto en el borde equivocado de una lámina girada— no se ve de ninguna otra manera.
"""

from pathlib import Path

import pytest

from apps.documents import marcas
from apps.documents.composicion import ComposicionInvalida
from apps.formats import pdf as lector

A4_ANCHO = 210 / lector.MM_POR_PUNTO
A4_ALTO = 297 / lector.MM_POR_PUNTO


def _pdf(carpeta: Path, nombre: str, cuantas: int = 3, giro: int = 0, apaisada=False) -> Path:
    from pypdf import PdfWriter

    escritor = PdfWriter()
    ancho, alto = (A4_ALTO, A4_ANCHO) if apaisada else (A4_ANCHO, A4_ALTO)
    for _ in range(cuantas):
        pagina = escritor.add_blank_page(width=ancho, height=alto)
        if giro:
            pagina.rotate(giro)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _texto(ruta: Path, pagina: int = 1) -> str:
    from pypdf import PdfReader

    return PdfReader(str(ruta)).pages[pagina - 1].extract_text()


#: Qué cuenta como tinta. **Cualquier cosa que no sea papel**, y no «negro»: una marca de
#: agua al 8 % sobre blanco da un gris de 235, así que un umbral de 128 la daría por
#: inexistente — que es justo lo que me pasó al escribir estas pruebas.
PAPEL = 250


def _pintado(ruta: Path, pagina: int = 1, escala: float = 1.5):
    """La página dibujada por PDFium, en gris, como bytes: uno por píxel."""
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        imagen = documento[pagina - 1].render(scale=escala).to_pil().convert("L")
    finally:
        documento.close()
    with imagen:
        return imagen.size, imagen.tobytes()


def _donde_cae_la_tinta(ruta: Path, pagina: int = 1) -> tuple[float, float]:
    """Centro de gravedad de lo pintado, **tal y como se ve**, en fracción de la hoja.

    `(0, 0)` es la esquina superior izquierda y `(1, 1)` la inferior derecha, que es como se
    mira una hoja. Devuelve dónde está la tinta, no dónde debería estar.
    """
    (ancho, _alto), pixeles = _pintado(ruta, pagina)

    suma_x = suma_y = cuantos = 0
    for indice, valor in enumerate(pixeles):
        if valor < PAPEL:
            suma_x += indice % ancho
            suma_y += indice // ancho
            cuantos += 1

    if not cuantos:
        raise AssertionError("La página salió en blanco: no se pintó nada.")
    alto_real = len(pixeles) // ancho
    return suma_x / cuantos / ancho, suma_y / cuantos / alto_real


def _cuanta_tinta(ruta: Path) -> float:
    """Fracción de la hoja que no es papel."""
    _tamano, pixeles = _pintado(ruta, escala=1.0)
    return sum(1 for valor in pixeles if valor < PAPEL) / len(pixeles)


def _claridad(ruta: Path) -> float:
    """Lo blanca que queda la hoja de media. Más marca de agua, menos claridad."""
    _tamano, pixeles = _pintado(ruta, escala=1.0)
    return sum(pixeles) / len(pixeles)


class TestQueDiceElNumero:
    def test_el_formato_se_respeta(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        destino = tmp_path / "numerada.pdf"
        marcas.numerar(memoria, destino, formato="Página {n} de {total}")
        assert "Página 1 de 4" in _texto(destino, 1)
        assert "Página 4 de 4" in _texto(destino, 4)

    def test_saltar_la_portada_y_empezar_a_contar_en_uno(self, tmp_path):
        """El caso de una memoria: portada sin número, y la hoja siguiente es la 1."""
        memoria = _pdf(tmp_path, "memoria.pdf", 5)
        destino = tmp_path / "numerada.pdf"
        resultado = marcas.numerar(memoria, destino, desde=2, empezar_en=1)

        assert resultado.paginas == 5
        assert resultado.marcadas == 4
        assert _texto(destino, 1).strip() == ""
        assert "1 / 4" in _texto(destino, 2)
        assert "4 / 4" in _texto(destino, 5)

    def test_el_total_es_el_ultimo_numero_impreso_no_el_de_hojas(self, tmp_path):
        """Si la portada no se numera, «de 5» no cuadraría con nada de lo que se ve."""
        memoria = _pdf(tmp_path, "memoria.pdf", 5)
        destino = tmp_path / "numerada.pdf"
        marcas.numerar(memoria, destino, desde=2, empezar_en=1)
        assert "/ 5" not in _texto(destino, 2)

    def test_empezar_en_un_numero_que_no_es_uno(self, tmp_path):
        """Un anexo que continúa la numeración del documento principal."""
        anexo = _pdf(tmp_path, "anexo.pdf", 3)
        destino = tmp_path / "numerado.pdf"
        marcas.numerar(anexo, destino, empezar_en=40, formato="{n}")
        assert "40" in _texto(destino, 1)
        assert "42" in _texto(destino, 3)


class TestDondeCaeElNumero:
    """La prueba que de verdad importa: se dibuja y se mira."""

    @pytest.mark.parametrize("giro", [0, 90, 180, 270])
    def test_el_pie_a_la_derecha_cae_abajo_a_la_derecha_con_cualquier_giro(self, tmp_path, giro):
        """Es el fallo que este módulo existe para evitar. Una lámina con `/Rotate 270` y una
        capa dibujada en el sistema de la caja pone el número **de canto en un lateral**, y el
        archivo «funciona»: abre, imprime, y está mal."""
        plano = _pdf(tmp_path, f"plano_{giro}.pdf", 1, giro=giro)
        destino = tmp_path / f"numerado_{giro}.pdf"
        marcas.numerar(plano, destino, posicion="pie-derecha", formato="{n} / {total}")

        x, y = _donde_cae_la_tinta(destino)
        assert x > 0.6, f"con /Rotate={giro} el número no salió a la derecha (x={x:.2f})"
        assert y > 0.6, f"con /Rotate={giro} el número no salió abajo (y={y:.2f})"

    @pytest.mark.parametrize("giro", [0, 90, 180, 270])
    def test_la_cabecera_a_la_izquierda_tambien(self, tmp_path, giro):
        plano = _pdf(tmp_path, f"plano_{giro}.pdf", 1, giro=giro)
        destino = tmp_path / f"numerado_{giro}.pdf"
        marcas.numerar(plano, destino, posicion="cabecera-izquierda", formato="{n}")

        x, y = _donde_cae_la_tinta(destino)
        assert x < 0.4, f"con /Rotate={giro} no salió a la izquierda (x={x:.2f})"
        assert y < 0.4, f"con /Rotate={giro} no salió arriba (y={y:.2f})"

    def test_el_pie_centrado_esta_centrado(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        destino = tmp_path / "numerada.pdf"
        marcas.numerar(memoria, destino, posicion="pie-centro", formato="{n}")

        x, y = _donde_cae_la_tinta(destino)
        assert 0.45 < x < 0.55
        assert y > 0.9

    def test_el_numero_cae_dentro_del_papel_en_una_hoja_apaisada(self, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 1, apaisada=True)
        destino = tmp_path / "numerada.pdf"
        marcas.numerar(lamina, destino, posicion="pie-derecha")
        # Que `_donde_cae_la_tinta` no reviente ya prueba que se pinto algo: una capa mal
        # colocada en una hoja apaisada sale **fuera del papel** y la pagina queda en blanco.
        x, y = _donde_cae_la_tinta(destino)
        assert x > 0.6 and y > 0.6


class TestElTamanoDeLetra:
    def test_en_una_hoja_grande_la_letra_es_mayor(self, tmp_path):
        """Diez puntos en un A1 son una mota. Se compara cuánta tinta hay, que es la medida
        directa de lo grande que salió el texto."""
        from pypdf import PdfWriter

        a1 = tmp_path / "a1.pdf"
        escritor = PdfWriter()
        escritor.add_blank_page(width=841 / lector.MM_POR_PUNTO, height=594 / lector.MM_POR_PUNTO)
        with open(a1, "wb") as salida:
            escritor.write(salida)

        a4 = _pdf(tmp_path, "a4.pdf", 1)
        marcas.numerar(a4, tmp_path / "a4_n.pdf", formato="{n}")
        marcas.numerar(a1, tmp_path / "a1_n.pdf", formato="{n}")

        proporcion_a4 = _cuanta_tinta(tmp_path / "a4_n.pdf")
        proporcion_a1 = _cuanta_tinta(tmp_path / "a1_n.pdf")
        # Sin escalado, el numero en el A1 ocuparia una fraccion mucho menor de la hoja.
        assert proporcion_a1 > proporcion_a4 * 0.4


class TestLaMarcaDeAgua:
    def test_dice_lo_que_se_le_pidio_en_todas_las_paginas(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        destino = tmp_path / "marcada.pdf"
        resultado = marcas.marca_de_agua(memoria, destino, "BORRADOR")

        assert resultado.marcadas == 3
        for numero in (1, 2, 3):
            assert "BORRADOR" in _texto(destino, numero)

    @pytest.mark.parametrize("giro", [0, 90, 180, 270])
    def test_cae_centrada_con_cualquier_giro(self, tmp_path, giro):
        plano = _pdf(tmp_path, f"plano_{giro}.pdf", 1, giro=giro)
        destino = tmp_path / f"marcado_{giro}.pdf"
        marcas.marca_de_agua(plano, destino, "CONFIDENCIAL", opacidad="marcada")

        x, y = _donde_cae_la_tinta(destino)
        assert 0.4 < x < 0.6, f"con /Rotate={giro} no salió centrada (x={x:.2f})"
        assert 0.4 < y < 0.6, f"con /Rotate={giro} no salió centrada (y={y:.2f})"

    def test_horizontal_tambien_se_puede(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        destino = tmp_path / "marcada.pdf"
        marcas.marca_de_agua(memoria, destino, "COPIA", diagonal=False)
        assert "COPIA" in _texto(destino)

    def test_mas_opacidad_deja_mas_tinta(self, tmp_path):
        """Las tres intensidades tienen que ser distinguibles de verdad, no tres nombres."""
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        marcas.marca_de_agua(memoria, tmp_path / "suave.pdf", "COPIA", opacidad="suave")
        marcas.marca_de_agua(memoria, tmp_path / "media.pdf", "COPIA", opacidad="normal")
        marcas.marca_de_agua(memoria, tmp_path / "fuerte.pdf", "COPIA", opacidad="marcada")

        assert (
            _claridad(tmp_path / "fuerte.pdf")
            < _claridad(tmp_path / "media.pdf")
            < _claridad(tmp_path / "suave.pdf")
        )

    def test_los_espacios_de_mas_se_recortan(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        destino = tmp_path / "marcada.pdf"
        marcas.marca_de_agua(memoria, destino, "  NO   VÁLIDO  ")
        assert "NO VÁLIDO" in _texto(destino)


class TestLoQueSeNiegaAHacer:
    def test_una_posicion_que_no_existe(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="posición"):
            marcas.numerar(memoria, tmp_path / "x.pdf", posicion="en-medio")

    def test_un_formato_que_no_existe(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="formato de numeración"):
            marcas.numerar(memoria, tmp_path / "x.pdf", formato="{n} de {nada}")

    def test_empezar_a_numerar_mas_alla_del_final(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        with pytest.raises(ComposicionInvalida, match="no se puede empezar en la 9"):
            marcas.numerar(memoria, tmp_path / "x.pdf", desde=9)

    def test_una_marca_sin_texto(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="No escribiste"):
            marcas.marca_de_agua(memoria, tmp_path / "x.pdf", "   ")

    def test_una_marca_kilometrica(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="ilegible"):
            marcas.marca_de_agua(memoria, tmp_path / "x.pdf", "palabra " * 20)

    def test_una_intensidad_que_no_existe(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="intensidades"):
            marcas.marca_de_agua(memoria, tmp_path / "x.pdf", "COPIA", opacidad="brutal")

    def test_uno_cifrado_manda_a_la_pantalla_que_corresponde(self, tmp_path):
        from apps.documents import seguridad

        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        cerrado = tmp_path / "cerrado.pdf"
        seguridad.proteger(memoria, cerrado, "una-clave-larga")

        with pytest.raises(ComposicionInvalida, match="Proteger PDF"):
            marcas.numerar(cerrado, tmp_path / "x.pdf")

    def test_algo_que_no_es_un_pdf(self, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida, match="No se pudo leer"):
            marcas.marca_de_agua(falso, tmp_path / "y.pdf", "COPIA")


class TestElOriginal:
    def test_no_se_toca_al_numerar(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        antes = memoria.read_bytes()
        marcas.numerar(memoria, tmp_path / "numerada.pdf")
        assert memoria.read_bytes() == antes

    def test_ni_al_marcar(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        antes = memoria.read_bytes()
        marcas.marca_de_agua(memoria, tmp_path / "marcada.pdf", "COPIA")
        assert memoria.read_bytes() == antes

    def test_y_la_copia_conserva_paginas_tamano_y_orientacion(self, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 2, giro=270)
        destino = tmp_path / "marcada.pdf"
        marcas.marca_de_agua(lamina, destino, "CONFIDENCIAL")

        original = lector.leer_cabecera(lamina)
        copia = lector.leer_cabecera(destino)
        assert copia.cuantas == original.cuantas
        assert [p.formato for p in copia.paginas] == [p.formato for p in original.paginas]
        assert [p.orientacion for p in copia.paginas] == [p.orientacion for p in original.paginas]
