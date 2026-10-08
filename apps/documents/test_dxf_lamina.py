"""Un plano DXF a una lámina (F14.16).

Los DXF de partida se **escriben con `ezdxf` y geometría conocida** (un rectángulo de 200 × 100 m en
un plano con unidades declaradas). La lámina se lee con **PDFium**, otro lector que el que dibujó
(`reportlab`): el dibujo debe tocar el margen fijo en el eje que manda y quedar centrado en el otro,
y el SVG se cuenta contra lo que se escribió, no contra la cuenta que lo dibujó.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import ezdxf
import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import dxf_lamina, motor, tarea
from apps.documents.composicion import ComposicionInvalida

MM = 72 / 25.4


def _plano(
    ruta: Path, *, unidades: int | None = 6, con_hatch: bool = False, capa_apagada: bool = True
) -> Path:
    documento = ezdxf.new("R2010", setup=True)
    # `ezdxf.new` ya declara metros: «sin unidades» hay que pedirlo escribiendo 0.
    documento.header["$INSUNITS"] = 0 if unidades is None else unidades
    documento.layers.add("OCULTA", color=3)
    if capa_apagada:
        documento.layers.get("OCULTA").off()
    espacio = documento.modelspace()
    espacio.add_lwpolyline(
        [(0, 0), (200, 0), (200, 100), (0, 100)], close=True, dxfattribs={"color": 1}
    )
    espacio.add_circle((100, 50), 30)
    espacio.add_text("Lote 7", height=5, dxfattribs={"insert": (10, 10)})
    espacio.add_line((0, 0), (400, 300), dxfattribs={"layer": "OCULTA"})
    if con_hatch:
        espacio.add_hatch()
    documento.saveas(ruta)
    return ruta


def _oscuros(ruta: Path) -> tuple[int, int, int, int, int, int]:
    """Caja (en px a 72 ppp) de lo no blanco, y el tamaño de la página, leídos con PDFium."""
    pagina = pypdfium2.PdfDocument(str(ruta))[0]
    ancho, alto = pagina.get_size()
    imagen = pagina.render(scale=1).to_pil().convert("L")
    caja = imagen.point(lambda v: 255 if v < 200 else 0).getbbox()
    assert caja is not None, "la lámina salió en blanco"
    return (*caja, round(ancho), round(alto))


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class TestLamina:
    def test_el_dibujo_toca_el_margen_donde_manda_y_queda_centrado(self, tmp_path):
        destino = tmp_path / "a.pdf"
        dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), destino, papel="a3")
        izq, arriba, der, abajo, ancho, alto = _oscuros(destino)
        assert (ancho, alto) == (round(420 * MM), round(297 * MM))
        margen = dxf_lamina.MARGEN_MM * MM
        # La línea de la capa apagada (0,0)-(400,300) no se dibuja: si se dibujara, el plano
        # mediría 400 y no 200 y no llegaría al margen.
        assert izq == pytest.approx(margen, abs=3)
        assert der == pytest.approx(ancho - margen, abs=3)
        assert (arriba + abajo) / 2 == pytest.approx(alto / 2, abs=3)  # centrado vertical

    def test_la_escala_se_dice_cuando_hay_unidades(self, tmp_path):
        # 200 m en 400 mm de papel: 2 mm por metro = 1:500.
        hecha = dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), tmp_path / "a.pdf", papel="a3")
        assert hecha.escala == "1:500" and hecha.ajuste == pytest.approx(2.0)

    def test_sin_unidades_no_se_inventa_una_escala(self, tmp_path):
        hecha = dxf_lamina.convertir(
            _plano(tmp_path / "a.dxf", unidades=None), tmp_path / "a.pdf", papel="a3"
        )
        assert hecha.escala == ""

    def test_un_papel_mayor_agranda_el_dibujo(self, tmp_path):
        a3 = dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), tmp_path / "a3.pdf", papel="a3")
        a1 = dxf_lamina.convertir(tmp_path / "a.dxf", tmp_path / "a1.pdf", papel="a1")
        assert a1.ajuste > a3.ajuste and a1.escala == "1:244"  # 821 mm / 200 m

    def test_un_plano_alto_sale_vertical(self, tmp_path):
        documento = ezdxf.new("R2010")
        documento.modelspace().add_line((0, 0), (10, 100))
        documento.saveas(tmp_path / "v.dxf")
        hecha = dxf_lamina.convertir(tmp_path / "v.dxf", tmp_path / "v.pdf", papel="a4")
        assert (hecha.ancho_mm, hecha.alto_mm) == (210.0, 297.0)

    def test_cuenta_lo_dibujado_y_lo_que_no(self, tmp_path):
        hecha = dxf_lamina.convertir(
            _plano(tmp_path / "a.dxf", con_hatch=True, capa_apagada=True), tmp_path / "a.pdf"
        )
        # polilínea + círculo + texto = 3 entidades; la línea de la capa apagada no cuenta.
        assert hecha.entidades == 3
        assert hecha.omitidas == {"HATCH": 1}
        assert hecha.capas_apagadas == 1

    def test_los_bloques_se_expanden(self, tmp_path):
        documento = ezdxf.new("R2010")
        bloque = documento.blocks.new("POSTE")
        bloque.add_line((0, 0), (0, 5))
        bloque.add_circle((0, 5), 1)
        espacio = documento.modelspace()
        for x in (0, 50, 100):
            espacio.add_blockref("POSTE", (x, 0))
        documento.saveas(tmp_path / "b.dxf")
        dibujo = dxf_lamina.leer(tmp_path / "b.dxf")
        assert len(dibujo.trazos) == 6  # tres postes, una línea y un círculo cada uno

    def test_el_blanco_se_dibuja_negro(self):
        assert dxf_lamina._contra_blanco((255, 255, 255)) == (0, 0, 0)
        assert dxf_lamina._contra_blanco((255, 0, 0)) == (255, 0, 0)

    def test_el_color_de_la_capa_llega_a_la_lamina(self, tmp_path):
        destino = tmp_path / "a.pdf"
        dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), destino)
        imagen = pypdfium2.PdfDocument(str(destino))[0].render(scale=1).to_pil().convert("RGB")
        rojos = [p for p in imagen.getdata() if p[0] > 200 and p[1] < 80 and p[2] < 80]
        assert rojos, "el rectángulo (color 1, rojo) debía salir rojo"

    def test_el_texto_esta_en_la_lamina(self, tmp_path):
        destino = tmp_path / "a.pdf"
        dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), destino)
        texto = pypdfium2.PdfDocument(str(destino))[0].get_textpage().get_text_range()
        assert "Lote 7" in texto

    def test_svg_trae_una_trayectoria_por_trazo(self, tmp_path):
        destino = tmp_path / "a.svg"
        hecha = dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), destino, formato="svg")
        texto = destino.read_text(encoding="utf-8")
        assert len(re.findall(r"<path ", texto)) == hecha.trazos == 2
        assert ">Lote 7</text>" in texto and texto.rstrip().endswith("</svg>")

    def test_dwg_no_se_lee_aqui(self, tmp_path):
        dwg = tmp_path / "a.dwg"
        dwg.write_bytes(b"AC1027")
        with pytest.raises(ComposicionInvalida, match="DWG"):
            dxf_lamina.convertir(dwg, tmp_path / "a.pdf")

    def test_un_archivo_que_no_es_dxf_se_rechaza(self, tmp_path):
        malo = tmp_path / "a.dxf"
        malo.write_text("esto no es un dxf", encoding="utf-8")
        with pytest.raises(ComposicionInvalida, match="no se lee como un DXF"):
            dxf_lamina.convertir(malo, tmp_path / "a.pdf")

    def test_un_plano_vacio_se_rechaza(self, tmp_path):
        ezdxf.new("R2010").saveas(tmp_path / "v.dxf")
        with pytest.raises(ComposicionInvalida, match="nada que se pueda dibujar"):
            dxf_lamina.convertir(tmp_path / "v.dxf", tmp_path / "v.pdf")

    @pytest.mark.parametrize("campo,valor", [("papel", "a9"), ("formato", "doc")])
    def test_opciones_desconocidas_se_rechazan(self, tmp_path, campo, valor):
        with pytest.raises(ComposicionInvalida):
            dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), tmp_path / "a.pdf", **{campo: valor})

    def test_el_original_no_se_toca_ni_al_fallar(self, tmp_path):
        bueno = _plano(tmp_path / "a.dxf")
        malo = tmp_path / "m.dxf"
        malo.write_text("no", encoding="utf-8")
        antes = {p: (_sha(p), p.stat().st_mtime_ns) for p in (bueno, malo)}
        dxf_lamina.convertir(bueno, tmp_path / "a.pdf")
        with pytest.raises(ComposicionInvalida):
            dxf_lamina.convertir(malo, tmp_path / "m.pdf")
        assert {p: (_sha(p), p.stat().st_mtime_ns) for p in (bueno, malo)} == antes


class TestVerificador:
    def test_un_svg_a_medias_se_rechaza(self, tmp_path):
        roto = tmp_path / "a.svg"
        roto.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0"/>', encoding="utf-8"
        )
        assert not motor._verificar_svg(roto, {}).correcta

    def test_un_svg_con_otra_cuenta_se_rechaza(self, tmp_path):
        destino = tmp_path / "a.svg"
        dxf_lamina.convertir(_plano(tmp_path / "a.dxf"), destino, formato="svg")
        assert motor._verificar_svg(destino, {"trazos": 2}).correcta
        assert not motor._verificar_svg(destino, {"trazos": 9}).correcta

    def test_registrada_en_el_motor_y_en_la_tarea(self):
        assert "dxf_lamina" in motor.ESPECIFICACIONES and "dxf_lamina" in tarea.TAREAS


@pytest.mark.django_db
class TestPantalla:
    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("documents:dxf_lamina")).status_code == 302

    def test_se_abre(self, sesion):
        respuesta = sesion.get(reverse("documents:dxf_lamina"))
        assert respuesta.status_code == 200 and "Plano DXF a PDF" in respuesta.content.decode()

    def test_un_dwg_se_rechaza_con_su_camino(self, sesion, tmp_path):
        dwg = tmp_path / "a.dwg"
        dwg.write_bytes(b"AC1027")
        respuesta = sesion.post(reverse("documents:dxf_lamina"), {"ruta": str(dwg)})
        assert respuesta.status_code == 200 and "es un DWG" in respuesta.content.decode()

    def test_un_papel_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:dxf_lamina"),
            {"ruta": str(_plano(tmp_path / "a.dxf")), "papel": "a9"},
        )
        assert (
            respuesta.status_code == 200
            and "no es de los que se ofrecen" in respuesta.content.decode()
        )

    @pytest.mark.parametrize("formato", ["pdf", "svg"])
    def test_de_extremo_a_extremo(self, sesion, tmp_path, formato):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        plano = _plano(tmp_path / "a.dxf")
        antes = _sha(plano)
        respuesta = sesion.post(
            reverse("documents:dxf_lamina"),
            {"ruta": str(plano), "papel": "a3", "formato": formato},
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        salida = Path(trabajo.output_path)
        assert salida.suffix == f".{formato}"
        if formato == "pdf":
            assert len(pypdfium2.PdfDocument(str(salida))) == 1
        assert _sha(plano) == antes
        assert not zipfile.is_zipfile(salida) or formato == "pdf"
