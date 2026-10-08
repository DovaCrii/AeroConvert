"""PDF a PDF/A-2b (F14.9): Ghostscript escribe, **pikepdf comprueba**, veraPDF valida si está.

En el CI no hay Ghostscript: el pegamento se prueba con un `gs` de mentira que deja en
`-sOutputFile` un PDF hecho aquí (bueno o malo a propósito). Lo que se comprueba del resultado lo
mira pikepdf, que no lo escribió. Con Ghostscript de verdad (el de QGIS), la prueba `oraculo` de
abajo convierte un PDF con una fuente sin incrustar y exige que salga incrustada y PDF/A-2B.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
from pathlib import Path

import pikepdf
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from reportlab.pdfgen import canvas

from apps.documents import motor, pdfa
from apps.documents.composicion import ComposicionInvalida


def _pdf_comun(ruta: Path, con_texto: bool = True) -> Path:
    memoria = io.BytesIO()
    c = canvas.Canvas(memoria)
    if con_texto:
        c.drawString(100, 700, "Contrato para archivar")  # Helvetica: sin incrustar
    c.rect(100, 600, 50, 50, fill=1)
    c.showPage()
    c.save()
    ruta.write_bytes(memoria.getvalue())
    return ruta


def _pdf_como_pdfa(ruta: Path) -> Path:
    """Un PDF **sin fuentes** con la identificación y la intención de salida de un PDF/A-2b."""
    from PIL import ImageCms

    # Hecho con pikepdf y no con reportlab: reportlab declara Helvetica en los recursos de la
    # página aunque no escriba texto, y eso ya sería una fuente sin incrustar.
    with pikepdf.new() as nuevo:
        nuevo.add_blank_page(page_size=(595, 842))
        nuevo.save(ruta)
    with pikepdf.open(ruta, allow_overwriting_input=True) as pdf:
        icc = pdf.make_stream(
            ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes(), N=3
        )
        pdf.Root.OutputIntents = pikepdf.Array(
            [
                pikepdf.Dictionary(
                    Type=pikepdf.Name.OutputIntent,
                    S=pikepdf.Name.GTS_PDFA1,
                    DestOutputProfile=icc,
                    OutputConditionIdentifier="sRGB",
                )
            ]
        )
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["pdfaid:part"] = "2"
            meta["pdfaid:conformance"] = "B"
        pdf.save(ruta)
    return ruta


FALSO = r"""
import shutil, sys
from pathlib import Path
salida = next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("-sOutputFile="))
modo = Path(__file__).with_suffix(".modo").read_text().strip()
if modo != "nada":
    shutil.copyfile(Path(__file__).with_suffix(".pdf"), salida)
"""


def _gs_falso(carpeta: Path, modo: str, pdf_de_salida: Path | None = None) -> str:
    guion = carpeta / "gs_falso.py"
    guion.write_text(FALSO, encoding="utf-8")
    guion.with_suffix(".modo").write_text(modo, encoding="utf-8")
    if pdf_de_salida is not None:
        shutil.copyfile(pdf_de_salida, guion.with_suffix(".pdf"))
    if os.name == "nt":
        lanzador = carpeta / "gs_falso.cmd"
        lanzador.write_text(f'@"{sys.executable}" "{guion}" %*\n', encoding="utf-8")
    else:
        lanzador = carpeta / "gs_falso"
        lanzador.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{guion}" "$@"\n', encoding="utf-8"
        )
        lanzador.chmod(0o755)
    return str(lanzador)


def _huella(ruta: Path):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestElPlan:
    def test_seguro_y_solo_lee_su_carpeta(self, tmp_path):
        argv = pdfa.plan("gs", tmp_path / "e.pdf", tmp_path / "s.pdf", tmp_path / "t")
        assert "-dSAFER" in argv and "-dPDFA=2" in argv and "-dPDFACompatibilityPolicy=1" in argv
        permiso = next(a for a in argv if a.startswith("--permit-file-read="))
        assert permiso.endswith("/t/") and "-sDEVICE=pdfwrite" in argv
        assert argv[-1] == str(tmp_path / "e.pdf")


class TestLaComprobacion:
    def test_un_pdf_comun_no_pasa_por_pdfa(self, tmp_path):
        problemas = pdfa.comprobar(_pdf_comun(tmp_path / "a.pdf"))["problemas"]
        assert any("identificación" in p for p in problemas)
        assert any("intención de salida" in p for p in problemas)
        assert any("Helvetica" in p for p in problemas)

    def test_uno_con_identificacion_perfil_y_sin_fuentes_pasa(self, tmp_path):
        resultado = pdfa.comprobar(_pdf_como_pdfa(tmp_path / "a.pdf"))
        assert resultado["problemas"] == [] and resultado["pdfa"] == "2B"


class TestLaConversion:
    def test_con_un_gs_que_escribe_bien(self, tmp_path):
        origen = _pdf_comun(tmp_path / "entrada.pdf")
        antes = _huella(origen)
        destino = tmp_path / "salida.parcial.pdf"
        bueno = _pdf_como_pdfa(tmp_path / "bueno.pdf")
        resultado = pdfa.convertir(origen, destino, _gs_falso(tmp_path, "bien", bueno))
        assert resultado["pdfa"] == "2B" and resultado["conforme"] is None  # sin veraPDF
        assert _huella(origen) == antes
        assert not destino.with_name(destino.name + ".pdfa").exists()

    def test_si_gs_no_escribe_nada_falla_y_limpia(self, tmp_path):
        origen = _pdf_comun(tmp_path / "entrada.pdf")
        destino = tmp_path / "salida.parcial.pdf"
        with pytest.raises(ComposicionInvalida, match="no escribió"):
            pdfa.convertir(origen, destino, _gs_falso(tmp_path, "nada"))
        assert not destino.exists() and not destino.with_name(destino.name + ".pdfa").exists()

    def test_si_gs_escribe_algo_que_no_es_pdfa_se_rechaza_y_no_queda(self, tmp_path):
        origen = _pdf_comun(tmp_path / "entrada.pdf")
        antes = _huella(origen)
        destino = tmp_path / "salida.parcial.pdf"
        malo = _pdf_comun(tmp_path / "malo.pdf")
        with pytest.raises(ComposicionInvalida, match="no cumple lo mínimo"):
            pdfa.convertir(origen, destino, _gs_falso(tmp_path, "mal", malo))
        assert not destino.exists() and _huella(origen) == antes

    @pytest.mark.parametrize("dice,esperado", [("PASS", True), ("FAIL", False), ("???", None)])
    def test_lo_que_dice_verapdf(self, tmp_path, monkeypatch, dice, esperado):
        import subprocess

        monkeypatch.setattr(
            pdfa.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, f"... {dice} ...", ""),
        )
        assert pdfa.validar_con_verapdf(tmp_path / "x.pdf", "verapdf") is esperado


class TestLaSonda:
    def test_lo_configurado_se_usa(self, settings, tmp_path):
        programa = tmp_path / "gs"
        programa.write_text("x")
        settings.GHOSTSCRIPT = str(programa)
        assert pdfa.sondar(recordar=False).programa == str(programa)

    def test_sin_ghostscript_sale_apagada_con_su_paso(self, settings, monkeypatch):
        settings.GHOSTSCRIPT = ""
        settings.GDAL_BIN = ""
        monkeypatch.setattr(pdfa.shutil, "which", lambda n: None)
        estado = pdfa.sondar(recordar=False)
        assert not estado and "Ghostscript" in estado.motivo


@pytest.fixture
def entrado(client, db, settings, tmp_path):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


class TestLaPantalla:
    def test_sin_sesion_redirige(self, client, db):
        assert client.get(reverse("documents:pdf_a")).status_code == 302

    def test_sin_ghostscript_dice_el_motivo(self, entrado, monkeypatch):
        monkeypatch.setattr(
            pdfa, "sondar", lambda **k: pdfa.Disponible(motivo="No hay Ghostscript.")
        )
        cuerpo = entrado.get(reverse("documents:pdf_a")).content.decode()
        assert "No hay Ghostscript." in cuerpo and 'name="ruta"' not in cuerpo

    def test_sin_verapdf_avisa_que_no_afirmara_la_conformidad(self, entrado, monkeypatch):
        monkeypatch.setattr(pdfa, "sondar", lambda **k: pdfa.Disponible(programa="gs"))
        monkeypatch.setattr(pdfa, "sondar_verapdf", lambda: "")
        cuerpo = entrado.get(reverse("documents:pdf_a")).content.decode()
        assert "no afirmará que sea conforme" in cuerpo

    def test_lo_que_no_es_pdf_se_rechaza(self, entrado, monkeypatch, tmp_path):
        from apps.jobs.models import ConversionJob

        monkeypatch.setattr(pdfa, "sondar", lambda **k: pdfa.Disponible(programa="gs"))
        (tmp_path / "a.txt").write_text("x")
        respuesta = entrado.post(reverse("documents:pdf_a"), {"ruta": str(tmp_path / "a.txt")})
        assert "no es un PDF" in respuesta.content.decode() and not ConversionJob.objects.exists()

    def test_de_extremo_a_extremo_por_la_cola(self, entrado, monkeypatch, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        bueno = _pdf_como_pdfa(tmp_path / "bueno.pdf")
        falso = _gs_falso(tmp_path, "bien", bueno)
        monkeypatch.setattr(pdfa, "sondar", lambda **k: pdfa.Disponible(programa=falso))
        monkeypatch.setattr(pdfa, "sondar_verapdf", lambda: "")
        carpeta = tmp_path / "compartida"
        carpeta.mkdir()
        origen = _pdf_comun(carpeta / "contrato.pdf")
        antes = _huella(origen)
        entrado.post(reverse("documents:pdf_a"), {"ruta": str(origen)})
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.get()
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.verification["pdfa"] == "2B" and trabajo.verification["conforme"] is None
        assert _huella(origen) == antes
        assert motor.ESPECIFICACIONES["pdf_a"].exige == "ghostscript"


def _gs_real() -> str:
    for candidato in (
        shutil.which("gs"),
        shutil.which("gswin64c"),
        r"C:\Program Files\QGIS 4.0.2\bin\gswin64c.exe",
    ):
        if candidato and Path(candidato).is_file():
            return candidato
    return ""


@pytest.mark.oraculo
@pytest.mark.skipif(not _gs_real(), reason="Ghostscript no está en esta máquina")
def test_ghostscript_de_verdad_incrusta_las_fuentes_y_marca_pdfa_2b(tmp_path):
    origen = _pdf_comun(tmp_path / "contrato.pdf")
    assert any("Helvetica" in p for p in pdfa.comprobar(origen)["problemas"]), "de partida, no"
    destino = tmp_path / "contrato_pdfa.pdf"
    resultado = pdfa.convertir(origen, destino, _gs_real())
    assert resultado["problemas"] == [] and resultado["pdfa"] == "2B"
    with pikepdf.open(destino) as pdf:
        assert pdf.open_metadata().pdfa_status == "2B"
