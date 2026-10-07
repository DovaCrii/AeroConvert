"""«Organizar páginas» (F12.1): girar, reordenar, quitar y repetir las páginas de un PDF.

Es la receta de «Unir» con un solo archivo, y las pruebas lo dicen: la misma máquina, otra
pantalla. **El oráculo de la salida es pypdf y el lector de cabeceras reabriendo el archivo
escrito**, no lo que devuelve la tarea: una página que «se repitió» en los detalles pero no en
el PDF sería justo el fallo que no se vería.
"""

from __future__ import annotations

import hashlib
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader, PdfWriter

from apps.dashboard import acciones as acciones_mod
from apps.documents import receta as receta_mod
from apps.formats import pdf as lector
from apps.jobs import despachador

pytestmark = pytest.mark.django_db


def _pdf(carpeta, nombre, tamanos):
    """Un PDF con páginas de tamaños distintos: así cada una se reconoce por su forma."""
    escritor = PdfWriter()
    for ancho, alto in tamanos:
        escritor.add_blank_page(
            width=ancho / lector.MM_POR_PUNTO, height=alto / lector.MM_POR_PUNTO
        )
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


@pytest.fixture
def memoria(tmp_path):
    # A4, A3 y A2, todas verticales: el tamaño dice cuál es cuál.
    return _pdf(tmp_path, "memoria.pdf", [(210, 297), (297, 420), (420, 594)])


def _receta_de(respuesta) -> str:
    encontrado = re.search(r'name="receta" value="([^"]*)"', respuesta.content.decode())
    return encontrado.group(1) if encontrado else ""


def _accion(sesion, *archivos, accion, receta=""):
    return sesion.post(
        reverse("documents:componer_organizar"),
        {"archivos_texto": "\n".join(str(a) for a in archivos), "receta": receta, "accion": accion},
    )


def _huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestDuplicarEnLaReceta:
    def test_pone_la_copia_justo_detras_con_el_mismo_giro(self):
        base = [receta_mod.Entrada(0, 1, 0), receta_mod.Entrada(0, 2, 90)]
        assert receta_mod.duplicar(base, 1) == [
            receta_mod.Entrada(0, 1, 0),
            receta_mod.Entrada(0, 2, 90),
            receta_mod.Entrada(0, 2, 90),
        ]

    @pytest.mark.parametrize("indice", [-1, 2, 99])
    def test_un_indice_fuera_de_rango_no_cambia_nada(self, indice):
        base = [receta_mod.Entrada(0, 1), receta_mod.Entrada(0, 2)]
        assert receta_mod.duplicar(base, indice) == base

    def test_una_receta_llena_no_crece(self):
        llena = [receta_mod.Entrada(0, 1)] * receta_mod.MAXIMO_PAGINAS
        assert len(receta_mod.duplicar(llena, 0)) == receta_mod.MAXIMO_PAGINAS


class TestLaPantalla:
    def test_carga_y_habla_de_un_solo_pdf(self, sesion):
        cuerpo = sesion.get(reverse("documents:organizar")).content.decode()
        assert "Organiza las páginas de un PDF" in cuerpo
        assert reverse("documents:componer_organizar") in cuerpo
        assert "<title>Organizar páginas" in cuerpo
        assert " multiple " not in cuerpo, "organizar trabaja sobre un solo archivo"

    def test_unir_sigue_aceptando_varios_y_apuntando_a_lo_suyo(self, sesion):
        cuerpo = sesion.get(reverse("documents:unir")).content.decode()
        assert " multiple " in cuerpo
        assert reverse("documents:componer") in cuerpo
        assert "Organiza las páginas" not in cuerpo

    @pytest.mark.parametrize("nombre", ["documents:organizar", "documents:componer_organizar"])
    def test_sin_sesion_no_se_entra(self, client, nombre):
        respuesta = client.get(reverse(nombre))
        assert respuesta.status_code == 302 and "/entrar/" in respuesta["Location"]

    def test_la_pantalla_trae_el_boton_de_repetir_en_cada_pagina(self, sesion, memoria):
        cuerpo = _accion(sesion, memoria, accion="analizar").content.decode()
        assert cuerpo.count('value="duplicar:') == 3
        assert "Generar el PDF organizado" in cuerpo


class TestElRecorrido:
    def test_analizar_lista_las_paginas_de_ese_archivo(self, sesion, memoria):
        assert _receta_de(_accion(sesion, memoria, accion="analizar")) == "0:1:0,0:2:0,0:3:0"

    def test_repetir_quitar_girar_y_mover_se_combinan(self, sesion, memoria):
        receta = "0:1:0,0:2:0,0:3:0"
        receta = _receta_de(_accion(sesion, memoria, accion="duplicar:0", receta=receta))
        assert receta == "0:1:0,0:1:0,0:2:0,0:3:0"
        receta = _receta_de(_accion(sesion, memoria, accion="quitar:2", receta=receta))
        assert receta == "0:1:0,0:1:0,0:3:0"
        receta = _receta_de(_accion(sesion, memoria, accion="girar:2", receta=receta))
        assert receta == "0:1:0,0:1:0,0:3:90"
        receta = _receta_de(_accion(sesion, memoria, accion="subir:2", receta=receta))
        assert receta == "0:1:0,0:3:90,0:1:0"

    def test_con_dos_archivos_se_niega_y_manda_a_unir(self, sesion, memoria, tmp_path):
        otro = _pdf(tmp_path, "otro.pdf", [(210, 297)])
        respuesta = _accion(sesion, memoria, otro, accion="analizar")
        assert respuesta.status_code == 302
        pantalla = sesion.get(respuesta["Location"]).content.decode()
        assert "Unir PDF" in pantalla and "un solo PDF" in pantalla

    def test_sin_archivo_lo_dice(self, sesion):
        respuesta = _accion(sesion, accion="analizar")
        assert respuesta.status_code == 302


class TestLoQueSale:
    """El oráculo: el PDF escrito, reabierto por otro lector."""

    def test_sale_con_las_paginas_en_el_orden_y_el_giro_pedidos(self, sesion, memoria, tmp_path):
        # A2 girada 90, A4 repetida dos veces, y sin la A3.
        respuesta = _accion(sesion, memoria, accion="generar", receta="0:3:90,0:1:0,0:1:0")
        assert respuesta.status_code == 302
        assert despachador.procesar_una_vez() == 1

        salida = tmp_path / "memoria_organizado.pdf"
        assert salida.exists()
        paginas = lector.leer_cabecera(salida).paginas
        assert [p.etiqueta for p in paginas] == ["A2 apaisada", "A4 vertical", "A4 vertical"]

        assert len(PdfReader(str(salida)).pages) == 3

    def test_el_original_no_se_toca_ni_al_salir_bien(self, sesion, memoria):
        antes = _huella(memoria)
        _accion(sesion, memoria, accion="generar", receta="0:2:0")
        despachador.procesar_una_vez()
        assert _huella(memoria) == antes

    def test_el_original_no_se_toca_cuando_falla(self, sesion, tmp_path):
        """Camino de fallo: un archivo que no es un PDF. Ni se lee ni se cambia."""
        roto = tmp_path / "roto.pdf"
        roto.write_bytes(b"esto no es un pdf")
        antes = _huella(roto)
        respuesta = _accion(sesion, roto, accion="analizar")
        assert respuesta.status_code == 200
        assert "pdf" in respuesta.content.decode().lower()
        assert _huella(roto) == antes
        assert not list(tmp_path.glob("*_organizado.pdf*"))


class TestSeEncuentra:
    @pytest.mark.parametrize("busqueda", ["girar", "reordenar", "duplicar", "borrar paginas"])
    def test_el_buscador_la_encuentra_por_lo_que_la_persona_dice(self, busqueda):
        nombres = [a.nombre for g in acciones_mod.por_categoria(busqueda) for a in g["acciones"]]
        assert "Organizar páginas" in nombres

    def test_no_le_quita_la_pregunta_a_proteger(self):
        """«Quitar la contraseña de un PDF» es de Proteger. Organizar hablaba de quitar páginas
        y empataba con ella: Tino, que solo contesta cuando una gana sola, se quedaba mudo."""
        ganadora = acciones_mod.mejor("quitar la contraseña de un PDF")
        assert ganadora is not None and ganadora.id == "pdf-proteger"

    def test_esta_en_el_catalogo_de_trabajar_con_pdf(self):
        grupos = {
            g["titulo"]: [a.nombre for a in g["acciones"]] for g in acciones_mod.por_categoria()
        }
        assert "Organizar páginas" in grupos["Trabajar con PDF"]
