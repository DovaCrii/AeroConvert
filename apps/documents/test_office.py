"""Word, Excel y PowerPoint a PDF.

**Estas pruebas corren en una máquina sin Office**, que es el requisito del gate, y por eso
están partidas en dos como toda la capa de motores:

- `plan()` describe el `argv` y no ejecuta nada, así que se comprueba en cualquier sitio.
- `convertir()` sí lanza un proceso, y aquí se le lanza **uno de mentira**: un `python -c`
  que escribe el archivo, o que no lo escribe, o que se queda quieto. Eso prueba el
  pegamento —que es donde están los errores caros— sin depender de que haya Office.

La conversión de verdad se comprobó contra documentos reales y está anotada con sus cifras
en `docs/PRUEBAS_CON_ORACULO.md`.
"""

import sys

import pytest
from django.core.cache import cache

from apps.documents import office
from apps.documents.composicion import ComposicionInvalida

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def sin_memoria():
    office.olvidar()
    yield
    office.olvidar()


@pytest.fixture
def con_office():
    """Finge que hay Office, sin que lo haya.

    Se siembra la caché de la sonda, igual que `con_ogr` hace con la de GDAL: así estas
    pruebas dicen lo mismo en esta máquina y en la de integración continua.
    """
    cache.set(office.CLAVE_DE_CACHE, office.Disponible(frozenset({"word", "excel", "powerpoint"})))
    return office.sondar()


def _hijo_que(codigo_python: str) -> list[str]:
    return [sys.executable, "-c", codigo_python]


class TestLaSonda:
    def test_en_modo_nube_no_hay_office_y_lo_dice(self, settings):
        settings.MODO = "nube"
        estado = office.sondar(recordar=False)
        assert not estado
        assert "taller" in estado.motivo

    def test_sin_office_da_el_motivo_y_por_que_es_a_proposito(self, settings, monkeypatch):
        settings.MODO = "taller"
        monkeypatch.setattr(office, "_registrado", lambda _prog: False)
        estado = office.sondar(recordar=False)
        assert not estado
        assert "Office" in estado.motivo
        # Lo importante no es decir que falta: es decir **por que se depende de el**, o
        # parece una limitacion tonta.
        assert "se parece" in estado.sugerencia

    def test_con_office_dice_que_extensiones_valen(self, con_office):
        assert con_office
        assert ".docx" in con_office.extensiones
        assert ".xlsx" in con_office.extensiones
        assert con_office.nombres == ("Word", "Excel", "PowerPoint")

    def test_solo_con_word_no_ofrece_las_de_excel(self):
        estado = office.Disponible(frozenset({"word"}))
        assert ".docx" in estado.extensiones
        assert ".xlsx" not in estado.extensiones
        assert estado.nombres == ("Word",)

    def test_se_recuerda(self, settings, monkeypatch):
        settings.MODO = "taller"
        llamadas = []

        def contar(prog):
            llamadas.append(prog)
            return False

        monkeypatch.setattr(office, "_registrado", contar)
        office.sondar()
        cuantas = len(llamadas)
        office.sondar()
        assert len(llamadas) == cuantas, "la segunda vez volvió a mirar el registro"


class TestQueProgramaAbreQue:
    @pytest.mark.parametrize(
        ("nombre", "programa"),
        [
            ("informe.docx", "word"),
            ("contrato.DOC", "word"),
            ("plantilla.rtf", "word"),
            ("curvas.xlsx", "excel"),
            ("presupuesto.xls", "excel"),
            ("avance.pptx", "powerpoint"),
        ],
    )
    def test_por_la_extension(self, nombre, programa):
        assert office.programa_de(nombre) == programa

    def test_algo_que_no_es_de_office(self):
        with pytest.raises(ComposicionInvalida, match="no es un documento de Office"):
            office.programa_de("plano.dwg")

    def test_ni_un_pdf(self):
        with pytest.raises(ComposicionInvalida):
            office.programa_de("memoria.pdf")


class TestElPlan:
    def test_lleva_el_guion_el_origen_y_el_destino(self, tmp_path):
        argv = office.plan(tmp_path / "a.docx", tmp_path / "a.pdf", "word")
        assert argv[0] == "pwsh"
        assert "office_convertir.ps1" in " ".join(argv)
        assert "-Programa" in argv and "word" in argv
        assert str(tmp_path / "a.docx") in argv
        assert str(tmp_path / "a.pdf") in argv

    def test_no_carga_el_perfil_ni_pregunta_nada(self, tmp_path):
        """Un perfil de PowerShell con un `Read-Host` dentro dejaría el hijo esperando para
        siempre, y `-NonInteractive` es lo que impide que cualquier aviso lo haga."""
        argv = office.plan(tmp_path / "a.docx", tmp_path / "a.pdf", "word")
        assert "-NoProfile" in argv
        assert "-NonInteractive" in argv

    def test_el_ajuste_de_ancho_solo_va_en_excel(self, tmp_path):
        de_excel = office.plan(tmp_path / "a.xlsx", tmp_path / "a.pdf", "excel", ajustar_ancho=True)
        de_word = office.plan(tmp_path / "a.docx", tmp_path / "a.pdf", "word", ajustar_ancho=True)
        assert "-AjustarAncho" in de_excel
        assert "-AjustarAncho" not in de_word


class TestConvertir:
    def test_lo_normal(self, con_office, tmp_path):
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"finge que soy un docx")
        destino = tmp_path / "informe.pdf"

        escrito = office.convertir(
            origen,
            destino,
            argv=_hijo_que(f"open({str(destino)!r}, 'wb').write(b'%PDF-1.7 ')"),
        )
        assert escrito == destino
        assert destino.exists()

    def test_si_dice_que_si_pero_no_escribe_nada(self, con_office, tmp_path):
        """**El código de salida no es la prueba de que funcionó.** Es la regla escrita en
        `AGENTS.md`, y Office devuelve 0 sin escribir nada más veces de las que parece."""
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")

        with pytest.raises(ComposicionInvalida, match="no llegó a escribir"):
            office.convertir(origen, tmp_path / "informe.pdf", argv=_hijo_que("pass"))

    def test_si_falla_no_deja_el_archivo_a_medias(self, con_office, tmp_path):
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")
        destino = tmp_path / "informe.pdf"

        with pytest.raises(ComposicionInvalida, match="falló al convertir"):
            office.convertir(
                origen,
                destino,
                argv=_hijo_que(
                    f"open({str(destino)!r}, 'wb').write(b'a medias'); "
                    "import sys; sys.stderr.write('se rompio algo'); sys.exit(1)"
                ),
            )
        assert not destino.exists()

    def test_y_cuenta_lo_que_dijo_con_sus_tildes(self, con_office, tmp_path):
        """Con `text=True` a secas esto vuelve como «contraseÃ±a»: Python decodifica con la
        página de códigos de Windows y el hijo escribe UTF-8. Y el mensaje que más falta hace
        es justo el que salía ilegible."""
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")
        destino = tmp_path / "informe.pdf"

        with pytest.raises(ComposicionInvalida, match="el documento pide una contraseña"):
            office.convertir(
                origen,
                destino,
                argv=_hijo_que(
                    "import sys; "
                    "sys.stderr.buffer.write('el documento pide una contraseña\\n'"
                    ".encode('utf-8')); "
                    "sys.exit(1)"
                ),
            )

    def test_si_se_queda_colgado_se_mata_y_se_explica(self, con_office, tmp_path):
        """Es el caso real que justifica el proceso hijo: un documento que pide algo al
        abrirse deja a Word esperando para siempre."""
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")

        with pytest.raises(ComposicionInvalida, match="sin responder"):
            office.convertir(
                origen,
                tmp_path / "informe.pdf",
                tiempo_maximo_s=1,
                argv=_hijo_que("import time; time.sleep(30)"),
            )

    def test_sin_pwsh_lo_dice_claro(self, con_office, tmp_path):
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")

        with pytest.raises(ComposicionInvalida, match="PowerShell"):
            office.convertir(
                origen,
                tmp_path / "informe.pdf",
                argv=["no-existe-este-programa-aeroconvert"],
            )

    def test_un_archivo_que_no_esta(self, con_office, tmp_path):
        with pytest.raises(ComposicionInvalida, match="No existe"):
            office.convertir(tmp_path / "fantasma.docx", tmp_path / "fantasma.pdf")

    def test_sin_office_no_se_intenta_siquiera(self, tmp_path, monkeypatch, settings):
        settings.MODO = "taller"
        monkeypatch.setattr(office, "_registrado", lambda _prog: False)
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"x")

        with pytest.raises(ComposicionInvalida, match="Word no está disponible"):
            office.convertir(origen, tmp_path / "informe.pdf")

    def test_el_original_no_se_toca(self, con_office, tmp_path):
        origen = tmp_path / "informe.docx"
        origen.write_bytes(b"finge que soy un docx")
        antes = origen.read_bytes()
        destino = tmp_path / "informe.pdf"

        office.convertir(
            origen,
            destino,
            argv=_hijo_que(f"open({str(destino)!r}, 'wb').write(b'%PDF-1.7 ')"),
        )
        assert origen.read_bytes() == antes


def _pdf(carpeta, nombre="memoria.pdf", cuantas=2, texto=""):
    """Un PDF de verdad, con o sin texto dentro."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    ruta = carpeta / nombre
    escritor = PdfWriter()
    for _ in range(cuantas):
        pagina = escritor.add_blank_page(width=595, height=842)
        if texto:
            import io

            memoria = io.BytesIO()
            lienzo = canvas.Canvas(memoria, pagesize=(595, 842))
            lienzo.setFont("Helvetica", 12)
            lienzo.drawString(60, 700, texto)
            lienzo.save()
            memoria.seek(0)
            pagina.merge_page(PdfReader(memoria).pages[0], over=True)
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


class TestMirarElPdfAntesDeMandarloAWord:
    def test_cuenta_las_paginas_y_el_texto(self, tmp_path):
        memoria = _pdf(tmp_path, cuantas=3, texto="Esto es un informe con texto de verdad dentro")
        que_trae = office.mirar_pdf(memoria)
        assert que_trae.paginas == 3
        assert que_trae.caracteres > office.MINIMO_DE_TEXTO
        assert not que_trae.es_un_escaneo

    def test_uno_sin_texto_se_reconoce_como_escaneo(self, tmp_path):
        """El fallo silencioso: Word «convierte» un escaneo, devuelve medio mega y sale con
        código cero, y lo que hay dentro son las mismas fotos. Medido sobre una bitácora
        real de esta oficina: cero caracteres."""
        escaneo = _pdf(tmp_path, cuantas=2)
        que_trae = office.mirar_pdf(escaneo)
        assert que_trae.caracteres == 0
        assert que_trae.es_un_escaneo

    def test_algo_que_no_es_un_pdf_aunque_se_llame_pdf(self, tmp_path):
        """A Word le das un archivo de texto con la extensión cambiada y lo abre tan
        contento, lo guarda como .docx y sale con código cero. Probado."""
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida):
            office.mirar_pdf(falso)

    def test_uno_cifrado_manda_a_la_pantalla_que_corresponde(self, tmp_path):
        from apps.documents import seguridad

        memoria = _pdf(tmp_path, texto="hola")
        cerrado = tmp_path / "cerrado.pdf"
        seguridad.proteger(memoria, cerrado, "una-clave-larga")
        with pytest.raises(ComposicionInvalida, match="Proteger PDF"):
            office.mirar_pdf(cerrado)


class TestAWord:
    def test_lo_normal(self, con_office, tmp_path):
        memoria = _pdf(tmp_path, texto="Un informe con texto suficiente para no ser un escaneo")
        destino = tmp_path / "memoria.docx"

        escrito = office.a_word(
            memoria,
            destino,
            argv=_hijo_que(f"open({str(destino)!r}, 'wb').write(b'PK finge que soy un docx')"),
        )
        assert escrito == destino

    def test_el_plan_usa_el_modo_de_vuelta(self, tmp_path):
        argv = office.plan(tmp_path / "a.pdf", tmp_path / "a.docx", office.PDF_A_WORD)
        assert office.PDF_A_WORD in argv

    def test_no_se_le_manda_a_word_algo_que_no_es_un_pdf(self, con_office, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida):
            office.a_word(falso, tmp_path / "x.docx", argv=_hijo_que("pass"))

    def test_un_archivo_que_no_esta(self, con_office, tmp_path):
        with pytest.raises(ComposicionInvalida, match="No existe"):
            office.a_word(tmp_path / "fantasma.pdf", tmp_path / "fantasma.docx")

    def test_sin_word_no_se_intenta(self, tmp_path, monkeypatch, settings):
        settings.MODO = "taller"
        monkeypatch.setattr(office, "_registrado", lambda _prog: False)
        memoria = _pdf(tmp_path, texto="texto suficiente para que no parezca un escaneo")
        with pytest.raises(ComposicionInvalida, match="Word no está disponible"):
            office.a_word(memoria, tmp_path / "memoria.docx")

    def test_el_original_no_se_toca(self, con_office, tmp_path):
        memoria = _pdf(tmp_path, texto="texto suficiente para que no parezca un escaneo")
        antes = memoria.read_bytes()
        destino = tmp_path / "memoria.docx"
        office.a_word(
            memoria, destino, argv=_hijo_que(f"open({str(destino)!r}, 'wb').write(b'PK')")
        )
        assert memoria.read_bytes() == antes


class TestElGuionDePowerShell:
    def test_esta_donde_el_plan_dice(self):
        from pathlib import Path

        from django.conf import settings

        assert (Path(settings.BASE_DIR) / "scripts" / "office_convertir.ps1").is_file()

    def test_cierra_office_pase_lo_que_pase(self):
        """Un WINWORD.EXE huérfano se queda con el archivo bloqueado y el intento siguiente
        falla sin decir por qué. El `finally` es la única defensa."""
        from pathlib import Path

        from django.conf import settings

        guion = (Path(settings.BASE_DIR) / "scripts" / "office_convertir.ps1").read_text(
            encoding="utf-8"
        )
        assert "finally" in guion
        assert "$app.Quit()" in guion

    def test_comprueba_que_el_archivo_existe_antes_de_decir_que_si(self):
        from pathlib import Path

        from django.conf import settings

        guion = (Path(settings.BASE_DIR) / "scripts" / "office_convertir.ps1").read_text(
            encoding="utf-8"
        )
        assert "Test-Path -LiteralPath $Destino" in guion

    def test_sabe_ir_en_los_dos_sentidos(self):
        from pathlib import Path

        from django.conf import settings

        guion = (Path(settings.BASE_DIR) / "scripts" / "office_convertir.ps1").read_text(
            encoding="utf-8"
        )
        for modo in ("'word'", "'excel'", "'powerpoint'", f"'{office.PDF_A_WORD}'"):
            assert modo in guion
