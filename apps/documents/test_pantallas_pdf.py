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


class TestElIndice:
    def test_carga_y_lista_las_herramientas(self, sesion):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert herramienta["nombre"] in cuerpo

    def test_cada_una_lleva_a_su_pantalla(self, sesion):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert reverse(herramienta["url"]) in cuerpo

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
