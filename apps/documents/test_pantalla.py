"""La pantalla de unir PDF, de punta a punta.

Toda la pantalla es una función de lo que hay escrito en su formulario: la receta viaja en
un campo oculto y cada botón la lee, la cambia y la devuelve. Eso la hace trivial de probar
—se manda un POST y se lee la receta que vuelve— y es la razón de que no haya estado en el
servidor que caducar ni limpiar.

**El campo oculto lo puede escribir cualquiera**, así que la mitad de estas pruebas son
sobre recetas imposibles: índices fuera de rango, giros que un PDF no admite, basura. Todas
tienen que dejar la pantalla usable, no una traza.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import receta as receta_mod
from apps.formats import pdf as lector
from apps.jobs import despachador

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


@pytest.fixture
def sesion(client, db, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


@pytest.fixture
def archivos(tmp_path):
    memoria = _crear(tmp_path, "memoria.pdf", [(210, 297, 0)] * 3)
    planos = _crear(tmp_path, "planos.pdf", [(841, 594, 0), (594, 841, 270)])
    return memoria, planos


def _receta_de(respuesta) -> str:
    encontrado = re.search(r'name="receta" value="([^"]*)"', respuesta.content.decode())
    return encontrado.group(1) if encontrado else ""


def _accion(sesion, archivos, accion, receta=""):
    return sesion.post(
        reverse("documents:componer"),
        {
            "archivos_texto": "\n".join(str(a) for a in archivos),
            "receta": receta,
            "accion": accion,
        },
    )


class TestElRecorrido:
    def test_la_pantalla_carga_vacia(self, sesion):
        assert sesion.get(reverse("documents:unir")).status_code == 200

    def test_analizar_lista_todas_las_paginas_de_todos(self, sesion, archivos):
        respuesta = _accion(sesion, archivos, "analizar")
        assert _receta_de(respuesta) == "0:1:0,0:2:0,0:3:0,1:1:0,1:2:0"

    def test_quitar_saca_esa_y_solo_esa(self, sesion, archivos):
        respuesta = _accion(sesion, archivos, "quitar:0", "0:1:0,0:2:0,1:1:0")
        assert _receta_de(respuesta) == "0:2:0,1:1:0"

    def test_subir_y_bajar_cambian_el_orden(self, sesion, archivos):
        assert _receta_de(_accion(sesion, archivos, "bajar:0", "0:1:0,0:2:0")) == "0:2:0,0:1:0"
        assert _receta_de(_accion(sesion, archivos, "subir:1", "0:1:0,0:2:0")) == "0:2:0,0:1:0"

    def test_girar_suma_noventa_y_da_la_vuelta(self, sesion, archivos):
        """Cuatro pulsaciones vuelven al principio, que es lo que espera quien lo pulsa."""
        receta = "0:1:0"
        for esperado in ("0:1:90", "0:1:180", "0:1:270", "0:1:0"):
            receta = _receta_de(_accion(sesion, archivos, "girar:0", receta))
            assert receta == esperado

    def test_generar_escribe_lo_que_dice_la_receta(self, sesion, archivos, tmp_path):
        assert _accion(sesion, archivos, "generar", "0:2:90,1:1:0").status_code == 302
        assert despachador.procesar_una_vez() == 1

        salida = tmp_path / "memoria_unido.pdf"
        assert salida.exists()

        leido = lector.leer_cabecera(salida)
        assert leido.cuantas == 2
        # La A4 vertical, girada 90, sale apaisada.
        assert leido.paginas[0].etiqueta == "A4 apaisada"
        assert leido.paginas[1].etiqueta == "A1 apaisada"

    def test_y_los_originales_no_se_tocan(self, sesion, archivos):
        antes = [a.read_bytes() for a in archivos]
        _accion(sesion, archivos, "generar", "0:1:90,1:1:0")
        despachador.procesar_una_vez()
        assert [a.read_bytes() for a in archivos] == antes


class TestLaRecetaQueLlegaDeFuera:
    """El campo oculto lo puede escribir cualquiera."""

    @pytest.mark.parametrize(
        "basura",
        ["", "esto no es una receta", "9:1:0", "0:0:0", "0:1:45", "0:1", "a:b:c", "0:1:0,,,"],
    )
    def test_una_receta_imposible_no_revienta(self, sesion, archivos, basura):
        respuesta = _accion(sesion, archivos, "subir:0", basura)
        assert respuesta.status_code == 200

    def test_un_indice_de_archivo_que_no_existe_se_descarta(self):
        assert receta_mod.desde_texto("0:1:0,7:1:0", cuantos_archivos=2) == [
            receta_mod.Entrada(0, 1, 0)
        ]

    def test_un_giro_que_un_pdf_no_admite_se_descarta(self):
        assert receta_mod.desde_texto("0:1:45", cuantos_archivos=1) == []

    def test_hay_un_tope_de_paginas(self):
        """Un campo oculto manipulado no puede pedir un millón de páginas."""
        muchas = ",".join("0:1:0" for _ in range(receta_mod.MAXIMO_PAGINAS + 50))
        assert len(receta_mod.desde_texto(muchas, 1)) == receta_mod.MAXIMO_PAGINAS

    def test_pulsar_sobre_una_fila_que_ya_no_esta_no_es_un_error(self):
        """Entre que se pinta la lista y se pulsa un botón puede haber pasado cualquier
        cosa. Un 500 ahí sería una forma tonta de perder el trabajo hecho."""
        entradas = [receta_mod.Entrada(0, 1)]
        for accion in (receta_mod.subir, receta_mod.bajar, receta_mod.quitar, receta_mod.girar):
            assert accion(entradas, 99) == entradas


class TestLasRutas:
    def test_una_ruta_fuera_de_las_raices_permitidas_se_rechaza(self, sesion, archivos):
        """La misma puerta que la inspección: en taller una ruta es lectura del disco."""
        respuesta = sesion.post(
            reverse("documents:componer"),
            {"archivos_texto": "C:\\Windows\\System32\\config\\SAM", "accion": "analizar"},
            follow=True,
        )
        assert not any("página" in str(m) for m in respuesta.context["messages"])

    def test_se_admiten_las_comillas_que_pone_el_explorador(self, sesion, archivos):
        """«Copiar como ruta» las pone, y quitarlas a mano cada vez sobra."""
        respuesta = sesion.post(
            reverse("documents:componer"),
            {"archivos_texto": f'"{archivos[0]}"', "accion": "analizar"},
        )
        assert _receta_de(respuesta) == "0:1:0,0:2:0,0:3:0"

    def test_sin_ninguna_ruta_lo_dice(self, sesion):
        respuesta = sesion.post(
            reverse("documents:componer"),
            {"archivos_texto": "  \n \n", "accion": "analizar"},
            follow=True,
        )
        assert any("ningún archivo" in str(m) for m in respuesta.context["messages"])


class TestLaFichaLlevaAqui:
    def test_un_pdf_ofrece_unirlo_en_vez_de_convertirlo(self, sesion, archivos):
        """Y **no** enseña el formulario de conversión: ningún motor sale de un PDF, así
        que ese botón terminaba en «ningún motor sabe hacer esa conversión»."""
        cuerpo = sesion.get(
            reverse("dashboard:inspeccionar"), {"ruta": str(archivos[0])}
        ).content.decode()

        assert reverse("documents:unir") in cuerpo
        assert "¿Dónde tiene que abrir?" not in cuerpo
        assert "Convertir con estos ajustes" not in cuerpo
