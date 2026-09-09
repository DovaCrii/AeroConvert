"""El dibujo de la libreta de puntos.

Las dos primeras pruebas son las que importan, y las dos vigilan un fallo que **no se ve**:
un dibujo reflejado sigue pareciendo un levantamiento, y un dibujo estirado sigue pareciendo
una forma. Los dos mienten sobre lo único que la vista previa existe para enseñar.
"""

import pytest

from apps.dashboard import vista_previa as vp
from apps.formats import puntos as puntos_mod

CRUCE_MINERO = """P1,7318729.036,495279.406,3042.641,pr
P2,7318700.292,495137.090,3045.004,pr
P3,7318656.894,495192.496,3046.322,pr
P4,7318609.156,495087.401,3045.287,pr
P5,7318567.524,495195.695,3045.963,pr
"""


def _leer(tmp_path, contenido=CRUCE_MINERO, nombre="puntos.csv"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return puntos_mod.leer(ruta)


class TestElNorteVaHaciaArriba:
    def test_el_punto_mas_al_norte_se_dibuja_mas_arriba(self, tmp_path):
        """En SVG la Y crece hacia abajo y el norte crece hacia arriba.

        Sin invertirlo, un levantamiento que sube hacia el noreste se enseña bajando hacia
        el sureste — y sigue pareciendo un levantamiento, así que nadie lo nota.
        """
        cabecera = _leer(tmp_path)
        dibujo = vp.dibujo_de_puntos(cabecera)

        por_id = {p.identificador: p for p in dibujo.puntos}
        # P1 es el más al norte (7.318.729) y P5 el más al sur (7.318.567).
        assert por_id["P1"].y < por_id["P5"].y

    def test_el_punto_mas_al_este_se_dibuja_mas_a_la_derecha(self, tmp_path):
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path))
        por_id = {p.identificador: p for p in dibujo.puntos}
        # P1 es el más al este (495.279) y P4 el más al oeste (495.087).
        assert por_id["P1"].x > por_id["P4"].x


class TestLaEscalaEsLaMismaEnLosDosEjes:
    def test_una_franja_larga_y_estrecha_no_se_dibuja_cuadrada(self, tmp_path):
        """Quien mira una vista previa está juzgando **la forma**. Estirar cada eje para
        llenar la caja convierte una franja de 200 × 20 m en un cuadrado."""
        franja = "\n".join(f"P{i},7318500.0,{495000 + i * 20}.0,3040.0,pr" for i in range(1, 11))
        # 180 m de ancho y 0 de alto: la franja más extrema posible.
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path, franja))

        alturas = {p.y for p in dibujo.puntos}
        assert len(alturas) == 1, "Todos están en el mismo norte: deben dibujarse alineados."

    def test_las_proporciones_del_terreno_se_conservan(self, tmp_path):
        """Dos veces más ancho que alto en el terreno, dos veces más ancho en el dibujo."""
        rejilla = []
        for fila in range(3):
            for columna in range(5):
                # 400 m de ancho por 200 m de alto.
                norte = 7318000 + fila * 100
                este = 495000 + columna * 100
                rejilla.append(f"P{fila}{columna},{norte}.0,{este}.0,3040.0,pr")
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path, "\n".join(rejilla)))

        ancho_dibujado = max(p.x for p in dibujo.puntos) - min(p.x for p in dibujo.puntos)
        alto_dibujado = max(p.y for p in dibujo.puntos) - min(p.y for p in dibujo.puntos)
        assert ancho_dibujado / alto_dibujado == pytest.approx(2.0, rel=0.01)


class TestLosLimites:
    def test_todo_cabe_dentro_de_la_caja(self, tmp_path):
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path))
        for punto in dibujo.puntos:
            assert 0 <= punto.x <= dibujo.ancho
            assert 0 <= punto.y <= dibujo.alto

    def test_ningun_punto_queda_cortado_por_el_borde(self, tmp_path):
        """El margen existe para esto: un punto en el borde exacto se dibujaría a medias."""
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path))
        for punto in dibujo.puntos:
            assert punto.x >= dibujo.radio
            assert punto.y >= dibujo.radio


class TestCasosDegenerados:
    def test_un_solo_punto_se_dibuja_en_el_centro(self, tmp_path):
        """Sin extensión no hay escala que calcular, y dividir por cero no es una opción."""
        uno = "P1,7318729.036,495279.406,3042.641,pr\nP1,7318729.036,495279.406,3042.641,pr\n"
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path, uno))

        assert dibujo.hay_algo
        assert dibujo.puntos[0].x == pytest.approx(dibujo.ancho / 2, abs=1)
        assert dibujo.puntos[0].y == pytest.approx(dibujo.alto / 2, abs=1)

    def test_sin_muestra_no_hay_dibujo_y_no_revienta(self):
        vacia = puntos_mod.CabeceraPuntos(
            orden="pnezd",
            certeza=puntos_mod.CERTEZA_RANGO,
            delimitador=",",
            columnas=5,
            tiene_encabezado=False,
            puntos_leidos=0,
            lineas_ignoradas=0,
            minimo=(0.0, 0.0, 0.0),
            maximo=(0.0, 0.0, 0.0),
            muestra=(),
        )
        assert vp.dibujo_de_puntos(vacia).hay_algo is False


class TestLoQueSeLee:
    def test_cada_punto_lleva_su_titulo_con_las_coordenadas(self, tmp_path):
        """Un dibujo sin alternativa textual es una imagen sin `alt`. El `<title>` es lo
        que lee un lector de pantalla y lo que sale al pasar el ratón."""
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path))
        titulo = dibujo.puntos[0].titulo
        assert "P1" in titulo
        assert "7318729.036" in titulo
        assert "495279.406" in titulo
        assert "3042.641" in titulo
        assert "pr" in titulo

    def test_dice_cuanto_mide_el_levantamiento(self, tmp_path):
        """Un dibujo sin escala no dice si son 200 m o 200 km."""
        dibujo = vp.dibujo_de_puntos(_leer(tmp_path))
        assert 190 < dibujo.lado_mayor_m < 195

    def test_con_pocos_puntos_se_rotulan(self, tmp_path):
        assert vp.dibujo_de_puntos(_leer(tmp_path)).con_rotulos is True

    def test_con_muchos_no(self, tmp_path):
        """Tres mil rótulos son una mancha negra."""
        muchos = "\n".join(
            f"P{i},{7318000 + i * 0.5},{495000 + (i % 50)}.0,3040.0,pr"
            for i in range(vp.MAXIMO_CON_ROTULO + 5)
        )
        assert vp.dibujo_de_puntos(_leer(tmp_path, muchos)).con_rotulos is False
