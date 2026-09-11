"""Las pantallas de dividir e imágenes a PDF, y el índice que las junta.

Lo que se vigila aquí es lo mismo que en el resto de la aplicación: que las rutas pasen por
la misma puerta, que el original no se toque, y que un error deje la pantalla usable en vez
de media entrega repartida por la carpeta.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import views
from apps.formats import pdf as lector

pytestmark = pytest.mark.django_db


def _pdf(carpeta, nombre, cuantas):
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _imagen(carpeta, nombre, tamano=(1200, 800)):
    from PIL import Image

    ruta = carpeta / nombre
    Image.new("RGB", tamano, (200, 40, 40)).save(ruta)
    return ruta


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


@pytest.fixture
def con_office():
    """Finge que hay Office. Ver `test_office.py`."""
    from django.core.cache import cache

    from apps.documents import office

    office.olvidar()
    cache.set(office.CLAVE_DE_CACHE, office.Disponible(frozenset({"word", "excel", "powerpoint"})))
    yield
    office.olvidar()


@pytest.fixture
def sin_office(monkeypatch, settings):
    from apps.documents import office

    settings.MODO = "taller"
    office.olvidar()
    monkeypatch.setattr(office, "_registrado", lambda _prog: False)
    yield
    office.olvidar()


class TestElIndice:
    def test_carga_y_lista_las_herramientas(self, sesion, con_office):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert herramienta["nombre"] in cuerpo

    def test_cada_una_lleva_a_su_pantalla(self, sesion, con_office):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert reverse(herramienta["url"]) in cuerpo

    def test_sin_office_la_tarjeta_sigue_saliendo_apagada_y_con_el_motivo(self, sesion, sin_office):
        """Regla de la familia: una capacidad ausente **no se oculta**. Ocultarla haría
        parecer que nunca existió."""
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        assert "Word, Excel o PowerPoint a PDF" in cuerpo
        assert "herramienta-apagada" in cuerpo
        assert "No hay Microsoft Office instalado" in cuerpo
        # Y sin enlace, porque no lleva a ninguna parte util.
        assert f'href="{reverse("documents:office")}"' not in cuerpo

    def test_dice_por_que_no_se_usa_una_web(self, sesion):
        """Es la razón de que esto exista: un plano bajo acuerdo de confidencialidad no
        puede subirse al servidor de nadie."""
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        assert "suben tu archivo" in cuerpo


class TestDividir:
    def test_mirar_enseña_cuantas_paginas_hay(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        cuerpo = sesion.post(
            reverse("documents:dividir"), {"ruta": str(memoria), "accion": "mirar"}
        ).content.decode()
        assert "8 página(s)" in cuerpo

    def test_partir_por_rangos(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "rangos", "rangos": "1-3, 7"},
        )
        assert sorted(p.name for p in tmp_path.glob("memoria_*.pdf")) == [
            "memoria_1-3.pdf",
            "memoria_7.pdf",
        ]

    def test_partir_en_hojas_sueltas(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "hojas"},
        )
        assert len(list(tmp_path.glob("memoria_*.pdf"))) == 3

    def test_un_rango_al_reves_lo_dice_y_no_escribe_nada(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        cuerpo = sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "rangos", "rangos": "5-2"},
            follow=True,
        ).content.decode()

        assert "al revés" in cuerpo
        assert list(tmp_path.glob("memoria_*.pdf")) == []

    def test_el_original_no_se_toca(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        antes = memoria.read_bytes()
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "hojas"},
        )
        assert memoria.read_bytes() == antes

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:dividir"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "mirar"},
            follow=True,
        ).content.decode()
        assert "página(s)" not in cuerpo

    def test_algo_que_no_es_un_pdf(self, sesion, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"%PDF-1.7\nno soy un pdf\n")
        respuesta = sesion.post(
            reverse("documents:dividir"), {"ruta": str(falso), "accion": "mirar"}, follow=True
        )
        assert respuesta.status_code == 200


class TestImagenesAPdf:
    def test_una_pagina_por_imagen(self, sesion, tmp_path):
        fotos = [_imagen(tmp_path, f"foto{i}.jpg") for i in (1, 2)]
        sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": "\n".join(str(f) for f in fotos), "tamano": "a4"},
        )
        salida = tmp_path / "foto1_imagenes.pdf"
        assert lector.leer_cabecera(salida).cuantas == 2

    def test_cada_hoja_toma_la_orientacion_de_su_foto(self, sesion, tmp_path):
        fotos = [
            _imagen(tmp_path, "ancha.jpg", (1200, 800)),
            _imagen(tmp_path, "alta.jpg", (800, 1200)),
        ]
        sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": "\n".join(str(f) for f in fotos), "tamano": "a4"},
        )
        paginas = lector.leer_cabecera(tmp_path / "ancha_imagenes.pdf").paginas
        assert [p.orientacion for p in paginas] == ["apaisada", "vertical"]

    def test_sin_imagenes_lo_dice(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:imagenes"), {"archivos_texto": "  ", "tamano": "a4"}, follow=True
        ).content.decode()
        assert "ninguna imagen" in cuerpo

    def test_un_pdf_no_es_una_imagen(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": str(memoria), "tamano": "a4"},
            follow=True,
        ).content.decode()
        assert "no es una imagen" in cuerpo

    def test_y_no_deja_un_parcial_tirado(self, sesion, tmp_path):
        """El parcial existe mientras se escribe; si falla, se borra."""
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        sesion.post(reverse("documents:imagenes"), {"archivos_texto": str(memoria), "tamano": "a4"})
        assert list(tmp_path.glob("*parcial*")) == []


class TestPdfAImagenes:
    def test_sin_rangos_salen_todas(self, sesion, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 3)
        sesion.post(
            reverse("documents:a_imagenes"),
            {"ruta": str(lamina), "accion": "convertir", "formato": "png", "ppp": "96"},
        )
        assert len(list(tmp_path.glob("lamina_*.png"))) == 3

    def test_con_rangos_salen_esas(self, sesion, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 6)
        sesion.post(
            reverse("documents:a_imagenes"),
            {
                "ruta": str(lamina),
                "accion": "convertir",
                "rangos": "2, 5",
                "formato": "jpg",
                "ppp": "96",
            },
        )
        assert sorted(p.name for p in tmp_path.glob("lamina_*.jpg")) == [
            "lamina_2.jpg",
            "lamina_5.jpg",
        ]

    def test_mirar_no_escribe_nada(self, sesion, tmp_path):
        """El primer botón enseña el documento; solo «convertir» toca el disco."""
        lamina = _pdf(tmp_path, "lamina.pdf", 3)
        cuerpo = sesion.post(
            reverse("documents:a_imagenes"), {"ruta": str(lamina), "accion": "mirar"}
        ).content.decode()
        assert "3 página(s)" in cuerpo
        assert list(tmp_path.glob("lamina_*.png")) == []

    def test_un_rango_imposible_lo_dice(self, sesion, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 3)
        cuerpo = sesion.post(
            reverse("documents:a_imagenes"),
            {"ruta": str(lamina), "accion": "convertir", "rangos": "9-12", "ppp": "96"},
            follow=True,
        ).content.decode()
        assert "3 página(s)" in cuerpo
        assert list(tmp_path.glob("lamina_*.png")) == []

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:a_imagenes"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "convertir"},
            follow=True,
        ).content.decode()
        assert "página(s)" not in cuerpo

    def test_un_ppp_que_no_es_un_numero_cae_al_de_siempre(self, sesion, tmp_path):
        lamina = _pdf(tmp_path, "lamina.pdf", 1)
        respuesta = sesion.post(
            reverse("documents:a_imagenes"),
            {"ruta": str(lamina), "accion": "convertir", "ppp": "muchísimo"},
        )
        assert respuesta.status_code == 200
        assert (tmp_path / "lamina_1.png").exists()


class TestNumerar:
    def _texto(self, ruta, pagina=1):
        from pypdf import PdfReader

        return PdfReader(str(ruta)).pages[pagina - 1].extract_text()

    def test_numera_de_punta_a_punta(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        sesion.post(
            reverse("documents:numerar"),
            {
                "ruta": str(memoria),
                "accion": "numerar",
                "formato": "{n} / {total}",
                "posicion": "pie-derecha",
                "desde": "1",
                "empezar_en": "1",
            },
        )
        salida = tmp_path / "memoria_numerado.pdf"
        assert "1 / 4" in self._texto(salida, 1)
        assert "4 / 4" in self._texto(salida, 4)

    def test_saltando_la_portada(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        sesion.post(
            reverse("documents:numerar"),
            {
                "ruta": str(memoria),
                "accion": "numerar",
                "formato": "{n}",
                "posicion": "pie-centro",
                "desde": "2",
                "empezar_en": "1",
            },
        )
        salida = tmp_path / "memoria_numerado.pdf"
        assert self._texto(salida, 1).strip() == ""
        assert "1" in self._texto(salida, 2)

    def test_mirar_no_escribe_nada(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        cuerpo = sesion.post(
            reverse("documents:numerar"), {"ruta": str(memoria), "accion": "mirar"}
        ).content.decode()
        assert "4 página(s)" in cuerpo
        assert not (tmp_path / "memoria_numerado.pdf").exists()

    def test_un_numero_disparatado_en_el_campo_no_revienta(self, sesion, tmp_path):
        """Un campo numérico es evadible desde fuera del navegador."""
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        respuesta = sesion.post(
            reverse("documents:numerar"),
            {
                "ruta": str(memoria),
                "accion": "numerar",
                "desde": "pepe",
                "empezar_en": "-4",
                "formato": "{n}",
            },
        )
        assert respuesta.status_code == 200
        assert (tmp_path / "memoria_numerado.pdf").exists()

    def test_empezar_mas_alla_del_final_lo_dice_y_no_escribe(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        cuerpo = sesion.post(
            reverse("documents:numerar"),
            {"ruta": str(memoria), "accion": "numerar", "desde": "40", "formato": "{n}"},
            follow=True,
        ).content.decode()
        assert "no se puede empezar" in cuerpo
        assert not (tmp_path / "memoria_numerado.pdf").exists()
        assert list(tmp_path.glob("*parcial*")) == []

    def test_el_original_no_se_toca(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        antes = memoria.read_bytes()
        sesion.post(
            reverse("documents:numerar"),
            {"ruta": str(memoria), "accion": "numerar", "formato": "{n}"},
        )
        assert memoria.read_bytes() == antes

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:numerar"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "numerar"},
            follow=True,
        ).content.decode()
        assert "página(s)" not in cuerpo


class TestMarcaDeAgua:
    def _texto(self, ruta, pagina=1):
        from pypdf import PdfReader

        return PdfReader(str(ruta)).pages[pagina - 1].extract_text()

    def test_marca_todas_las_paginas(self, sesion, tmp_path):
        plano = _pdf(tmp_path, "plano.pdf", 3)
        sesion.post(
            reverse("documents:marca"),
            {
                "ruta": str(plano),
                "accion": "marcar",
                "texto": "BORRADOR",
                "opacidad": "normal",
                "orientacion": "diagonal",
            },
        )
        salida = tmp_path / "plano_marcado.pdf"
        for numero in (1, 2, 3):
            assert "BORRADOR" in self._texto(salida, numero)

    def test_horizontal_tambien(self, sesion, tmp_path):
        plano = _pdf(tmp_path, "plano.pdf", 1)
        sesion.post(
            reverse("documents:marca"),
            {
                "ruta": str(plano),
                "accion": "marcar",
                "texto": "COPIA",
                "opacidad": "suave",
                "orientacion": "horizontal",
            },
        )
        assert "COPIA" in self._texto(tmp_path / "plano_marcado.pdf")

    def test_sin_texto_lo_dice_y_no_escribe(self, sesion, tmp_path):
        plano = _pdf(tmp_path, "plano.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:marca"),
            {"ruta": str(plano), "accion": "marcar", "texto": "   "},
            follow=True,
        ).content.decode()
        assert "No escribiste" in cuerpo
        assert not (tmp_path / "plano_marcado.pdf").exists()
        assert list(tmp_path.glob("*parcial*")) == []

    def test_mirar_no_escribe_nada(self, sesion, tmp_path):
        plano = _pdf(tmp_path, "plano.pdf", 2)
        cuerpo = sesion.post(
            reverse("documents:marca"), {"ruta": str(plano), "accion": "mirar"}
        ).content.decode()
        assert "2 página(s)" in cuerpo
        assert not (tmp_path / "plano_marcado.pdf").exists()

    def test_el_original_no_se_toca(self, sesion, tmp_path):
        plano = _pdf(tmp_path, "plano.pdf", 2)
        antes = plano.read_bytes()
        sesion.post(
            reverse("documents:marca"),
            {"ruta": str(plano), "accion": "marcar", "texto": "CONFIDENCIAL"},
        )
        assert plano.read_bytes() == antes

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:marca"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "marcar", "texto": "COPIA"},
            follow=True,
        ).content.decode()
        assert "página(s)" not in cuerpo


class TestOfficeAPdf:
    def test_sin_office_la_pantalla_explica_en_vez_de_dar_un_403(self, sesion, sin_office):
        cuerpo = sesion.get(reverse("documents:office")).content.decode()
        assert "No hay Microsoft Office instalado" in cuerpo
        # Y dice **por que** se depende de Office, o parece una limitacion tonta.
        assert "se parece" in cuerpo

    def test_ni_intenta_convertir_sin_office(self, sesion, sin_office, tmp_path):
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")
        sesion.post(reverse("documents:office"), {"ruta": str(origen)})
        assert not (tmp_path / "informe.pdf").exists()

    def test_con_office_dice_que_extensiones_valen(self, sesion, con_office):
        cuerpo = sesion.get(reverse("documents:office")).content.decode()
        assert ".docx" in cuerpo
        assert ".xlsx" in cuerpo

    def test_y_explica_lo_del_ancho_de_excel_con_la_cifra_medida(self, sesion, con_office):
        """La razón de la casilla es una cifra real de esta oficina, no una opinión."""
        cuerpo = sesion.get(reverse("documents:office")).content.decode()
        assert "68 páginas sin ajustar, 6 ajustado" in cuerpo

    def test_algo_que_no_es_de_office_lo_dice(self, sesion, con_office, tmp_path):
        plano = tmp_path / "plano.dwg"
        plano.write_bytes(b"x")
        cuerpo = sesion.post(
            reverse("documents:office"), {"ruta": str(plano)}, follow=True
        ).content.decode()
        assert "no es un documento de Office" in cuerpo

    def test_una_ruta_fuera_de_las_raices(self, sesion, con_office):
        cuerpo = sesion.post(
            reverse("documents:office"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM"},
            follow=True,
        ).content.decode()
        assert "Hecho" not in cuerpo


class TestPdfAWord:
    def _con_texto(self, carpeta, nombre="memoria.pdf", cuantas=2):
        from apps.documents.test_office import _pdf as fabricar

        # Holgadamente por encima de `MINIMO_DE_TEXTO`: con una frase corta en dos hojas se
        # queda en 74 caracteres y se clasifica como escaneo, **que es lo correcto**.
        return fabricar(
            carpeta,
            nombre,
            cuantas,
            texto=(
                "Informe de avance semanal del contrato, con el detalle de las partidas "
                "ejecutadas y las observaciones levantadas en terreno durante el periodo."
            ),
        )

    def test_avisa_de_lo_que_se_recibe_antes_de_convertir(self, sesion, con_office):
        """El aviso va siempre y delante, no solo cuando falla."""
        cuerpo = sesion.get(reverse("documents:a_word")).content.decode()
        assert "no guarda párrafos" in cuerpo
        assert "97,7 %" in cuerpo

    def test_un_escaneo_se_detecta_y_no_se_ofrece_convertirlo(self, sesion, con_office, tmp_path):
        escaneo = _pdf(tmp_path, "escaneo.pdf", 2)
        cuerpo = sesion.post(
            reverse("documents:a_word"), {"ruta": str(escaneo), "accion": "mirar"}
        ).content.decode()
        assert "Esto es un escaneo" in cuerpo
        assert 'value="convertir"' not in cuerpo

    def test_uno_con_texto_si(self, sesion, con_office, tmp_path):
        memoria = self._con_texto(tmp_path)
        cuerpo = sesion.post(
            reverse("documents:a_word"), {"ruta": str(memoria), "accion": "mirar"}
        ).content.decode()
        assert "Trae texto de verdad" in cuerpo
        assert 'value="convertir"' in cuerpo

    def test_mirar_no_escribe_nada(self, sesion, con_office, tmp_path):
        memoria = self._con_texto(tmp_path)
        sesion.post(reverse("documents:a_word"), {"ruta": str(memoria), "accion": "mirar"})
        assert not (tmp_path / "memoria.docx").exists()

    def test_algo_que_no_es_un_pdf_lo_dice(self, sesion, con_office, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        respuesta = sesion.post(
            reverse("documents:a_word"), {"ruta": str(falso), "accion": "convertir"}, follow=True
        )
        assert respuesta.status_code == 200
        assert not (tmp_path / "x.docx").exists()

    def test_sin_office_explica_en_vez_de_reventar(self, sesion, sin_office):
        cuerpo = sesion.get(reverse("documents:a_word")).content.decode()
        assert "No hay Microsoft Office instalado" in cuerpo

    def test_una_ruta_fuera_de_las_raices(self, sesion, con_office):
        cuerpo = sesion.post(
            reverse("documents:a_word"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "convertir"},
            follow=True,
        ).content.decode()
        assert "Hecho" not in cuerpo


class TestProteger:
    CLAVE = "obra-2026-bhp"

    def test_dice_que_este_se_abre_sin_nada(self, sesion, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 2)
        cuerpo = sesion.post(
            reverse("documents:proteger"), {"ruta": str(informe), "accion": "mirar"}
        ).content.decode()
        assert "Se abre sin nada" in cuerpo

    def test_avisa_de_que_la_clave_no_se_recupera_antes_de_ponerla(self, sesion, tmp_path):
        """El aviso va en la pantalla donde se decide, no en el recibo: después ya no
        sirve de nada."""
        informe = _pdf(tmp_path, "informe.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:proteger"), {"ruta": str(informe), "accion": "mirar"}
        ).content.decode()
        assert "No hay forma de recuperarla" in cuerpo

    def test_protege_y_deja_el_original(self, sesion, tmp_path):
        from pypdf import PdfReader

        informe = _pdf(tmp_path, "informe.pdf", 2)
        antes = informe.read_bytes()
        sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": self.CLAVE},
        )

        salida = tmp_path / "informe_protegido.pdf"
        assert PdfReader(str(salida)).is_encrypted
        assert informe.read_bytes() == antes

    def test_la_contrasena_no_vuelve_en_la_respuesta(self, sesion, tmp_path):
        """Prueba con clave centinela, igual que con la clave de ECW: no puede quedar
        escrita en una pantalla que alguien deje abierta."""
        informe = _pdf(tmp_path, "informe.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": self.CLAVE},
        ).content.decode()
        assert self.CLAVE not in cuerpo

    def test_ni_cuando_falla(self, sesion, tmp_path):
        # Corta -- para que la rechace -- y a la vez lo bastante rara como para que
        # encontrarla en el HTML signifique que salio del campo y no de una ruta.
        centinela = "Qzx9w"
        informe = _pdf(tmp_path, "informe.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": centinela},
            follow=True,
        ).content.decode()
        assert centinela not in cuerpo
        assert not (tmp_path / "informe_protegido.pdf").exists()

    def test_reconoce_uno_cifrado_y_ofrece_quitarla(self, sesion, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 1)
        sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": self.CLAVE},
        )
        cuerpo = sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(tmp_path / "informe_protegido.pdf"), "accion": "mirar"},
        ).content.decode()
        assert "Pide contraseña" in cuerpo

    def test_y_la_quita_con_la_clave_buena(self, sesion, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 3)
        sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": self.CLAVE},
        )
        sesion.post(
            reverse("documents:proteger"),
            {
                "ruta": str(tmp_path / "informe_protegido.pdf"),
                "accion": "quitar",
                "contrasena": self.CLAVE,
            },
        )
        salida = tmp_path / "informe_protegido_sin_clave.pdf"
        assert lector.leer_cabecera(salida).cuantas == 3

    def test_con_la_clave_mala_no_escribe_nada(self, sesion, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 1)
        sesion.post(
            reverse("documents:proteger"),
            {"ruta": str(informe), "accion": "proteger", "contrasena": self.CLAVE},
        )
        sesion.post(
            reverse("documents:proteger"),
            {
                "ruta": str(tmp_path / "informe_protegido.pdf"),
                "accion": "quitar",
                "contrasena": "la-que-no-es",
            },
        )
        assert not (tmp_path / "informe_protegido_sin_clave.pdf").exists()
        assert list(tmp_path.glob("*parcial*")) == []

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:proteger"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "proteger"},
            follow=True,
        ).content.decode()
        assert "Se abre sin nada" not in cuerpo

    def test_algo_que_no_es_un_pdf(self, sesion, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        respuesta = sesion.post(
            reverse("documents:proteger"), {"ruta": str(falso), "accion": "mirar"}, follow=True
        )
        assert respuesta.status_code == 200
