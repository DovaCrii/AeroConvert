"""Las miniaturas: ver la hoja antes de ordenarla.

Ordenar cincuenta y seis filas de texto no es ordenar. La miniatura es la diferencia entre
«página 12 · A1 apaisada» y ver que esa es la lámina de armaduras y va la tercera.

Dos cosas se prueban con cuidado porque, mal hechas, no fallan — solo enseñan algo
distinto de lo que va a salir en el papel:

1. **El giro pedido va aplicado en la imagen.** Si la miniatura enseña la hoja como venía y
   el PDF final la escribe girada, la vista previa está mintiendo justo sobre lo único que
   se estaba decidiendo.
2. **El `ETag` cambia cuando cambia el archivo.** Es lo que hace que la caché del navegador
   sea correcta y no una trampa: sin eso, regenerar el PDF con el mismo nombre dejaría la
   pantalla enseñando las hojas de ayer con toda la confianza del mundo.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import miniaturas
from apps.formats import pdf as lector

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"

pytestmark = pytest.mark.django_db


def _crear(carpeta, nombre, paginas):
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for ancho, alto, giro in paginas:
        pagina = escritor.add_blank_page(
            width=ancho / lector.MM_POR_PUNTO, height=alto / lector.MM_POR_PUNTO
        )
        if giro:
            pagina.rotate(giro)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _tamano(png: bytes) -> tuple[int, int]:
    """Ancho y alto del PNG, leídos de su cabecera IHDR.

    A mano y no con Pillow: comprobar el resultado con la misma biblioteca que lo escribió
    no probaría gran cosa. Los bytes 16-24 de un PNG son ancho y alto, big-endian.
    """
    import struct

    assert png[:8] == FIRMA_PNG
    return struct.unpack(">II", png[16:24])


@pytest.fixture
def carta(tmp_path):
    return _crear(tmp_path, "carta.pdf", [(210, 297, 0)])


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


class TestDibujar:
    def test_devuelve_un_png(self, carta):
        assert miniaturas.dibujar(carta, 1)[:8] == FIRMA_PNG

    def test_del_ancho_pedido(self, carta):
        ancho, _alto = _tamano(miniaturas.dibujar(carta, 1, ancho=180))
        assert ancho == 180

    def test_una_hoja_vertical_sale_mas_alta_que_ancha(self, carta):
        ancho, alto = _tamano(miniaturas.dibujar(carta, 1))
        assert alto > ancho

    def test_y_girada_noventa_sale_al_reves(self, carta):
        """Lo que se ve tiene que ser lo que va a salir en el papel."""
        ancho, alto = _tamano(miniaturas.dibujar(carta, 1, giro=90))
        assert ancho > alto

    def test_el_giro_se_suma_al_que_traia_la_pagina(self, tmp_path):
        """La caja es vertical y el PDF pide girarla 270: se ve apaisada. La miniatura sin
        pedir nada tiene que salir apaisada también."""
        plano = _crear(tmp_path, "plano.pdf", [(594, 841, 270)])
        ancho, alto = _tamano(miniaturas.dibujar(plano, 1))
        assert ancho > alto

    def test_una_pagina_que_no_existe_lo_dice(self, carta):
        with pytest.raises(miniaturas.NoSePudoDibujar):
            miniaturas.dibujar(carta, 9)

    def test_un_archivo_que_no_es_pdf(self, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"%PDF-1.7\nno soy un pdf\n")
        with pytest.raises(miniaturas.NoSePudoDibujar):
            miniaturas.dibujar(falso, 1)

    def test_un_ancho_disparatado_se_acota(self, carta):
        """Una petición manipulada no puede pedir una imagen de veinte mil píxeles."""
        ancho, _alto = _tamano(miniaturas.dibujar(carta, 1, ancho=20_000))
        assert ancho == miniaturas.ANCHO_MAXIMO


class TestLaEtiqueta:
    def test_la_misma_peticion_da_la_misma(self, carta):
        assert miniaturas.etiqueta(carta, 1, 0, 220) == miniaturas.etiqueta(carta, 1, 0, 220)

    @pytest.mark.parametrize("cambio", [{"pagina": 2}, {"giro": 90}, {"ancho": 300}])
    def test_cambia_con_cada_parametro(self, carta, cambio):
        base = {"pagina": 1, "giro": 0, "ancho": 220}
        otra = {**base, **cambio}
        assert miniaturas.etiqueta(carta, **base) != miniaturas.etiqueta(carta, **otra)

    def test_y_cambia_si_el_archivo_cambia(self, tmp_path, carta):
        """Regenerar el PDF con el mismo nombre no puede dejar la pantalla enseñando las
        hojas de ayer."""
        antes = miniaturas.etiqueta(carta, 1, 0, 220)
        _crear(tmp_path, "carta.pdf", [(210, 297, 0), (210, 297, 0)])
        assert miniaturas.etiqueta(carta, 1, 0, 220) != antes


class TestLaVista:
    def test_sirve_el_png(self, sesion, carta):
        respuesta = sesion.get(reverse("documents:miniatura"), {"ruta": str(carta), "pagina": "1"})
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "image/png"
        assert respuesta.content[:8] == FIRMA_PNG

    def test_la_segunda_vez_la_pone_el_navegador(self, sesion, carta):
        """Al pulsar «bajar» se repintan las cincuenta y seis filas. Sin esto se
        redibujarían las cincuenta y seis miniaturas en cada pulsación."""
        primera = sesion.get(reverse("documents:miniatura"), {"ruta": str(carta), "pagina": "1"})
        segunda = sesion.get(
            reverse("documents:miniatura"),
            {"ruta": str(carta), "pagina": "1"},
            HTTP_IF_NONE_MATCH=primera["ETag"],
        )
        assert segunda.status_code == 304

    def test_no_se_guarda_en_ninguna_cache_compartida(self, sesion, carta):
        """Es el archivo de alguien."""
        respuesta = sesion.get(reverse("documents:miniatura"), {"ruta": str(carta), "pagina": "1"})
        assert "private" in respuesta["Cache-Control"]

    def test_una_ruta_fuera_de_las_raices_no_se_dibuja(self, sesion):
        """La misma puerta que la inspección: una vista que sirve imágenes también lee
        del disco."""
        respuesta = sesion.get(
            reverse("documents:miniatura"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "pagina": "1"},
        )
        assert respuesta.status_code == 400

    def test_una_pagina_que_no_existe_no_tumba_la_pantalla(self, sesion, carta):
        """La fila se queda sin imagen y con su texto, que sigue diciendo qué página es."""
        respuesta = sesion.get(reverse("documents:miniatura"), {"ruta": str(carta), "pagina": "99"})
        assert respuesta.status_code == 400

    def test_parametros_que_no_son_numeros(self, sesion, carta):
        respuesta = sesion.get(
            reverse("documents:miniatura"), {"ruta": str(carta), "pagina": "tres"}
        )
        assert respuesta.status_code == 400

    def test_hay_que_haber_entrado(self, client, carta, settings):
        settings.RAICES_PERMITIDAS = str(carta.parent)
        respuesta = client.get(reverse("documents:miniatura"), {"ruta": str(carta)})
        assert respuesta.status_code == 302
