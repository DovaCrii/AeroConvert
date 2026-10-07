"""Las portadas de J.E.J. (F14.19).

Las plantillas reales **no están en el repositorio** (llevan el logotipo), así que las pruebas
arman unas con **la misma estructura** que las dos de la empresa —leída de ellas—: marcadores
`XXXX` sueltos en el cuerpo y el encabezado, el pie enlazado a `dc:creator`, y el `PAGE`. La
prueba con las plantillas de verdad está al final, marcada `oraculo`, y se salta si no están.

El oráculo de lo escrito es **un lector que no lo escribió**: el zip y una expresión sobre el
texto de cada parte; y, con Word delante, el PDF que Word saca del `.docx`, leído con `pypdf`.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import motor, portadas, tarea

pytestmark = pytest.mark.django_db

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)


def _t(*textos: str) -> str:
    return "".join(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>' for t in textos)


def _parte(raiz: str, cuerpo: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><w:{raiz} {NS}>{cuerpo}</w:{raiz}>'


def _docx(ruta: Path, partes: dict[str, str]) -> Path:
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        for nombre, contenido in partes.items():
            z.writestr(nombre, contenido)
    return ruta


def _core(creador: str) -> str:
    return (
        '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>1</dc:title><dc:creator>{creador}</dc:creator></cp:coreProperties>"
    )


def _pie_con_autor(texto: str) -> str:
    return _parte(
        "ftr",
        '<w:sdt><w:sdtPr><w:alias w:val="Autor"/><w:dataBinding w:xpath="/ns1:coreProperties[1]/'
        'ns0:creator[1]"/></w:sdtPr><w:sdtContent><w:p>'
        + _t(texto)
        + "</w:p></w:sdtContent></w:sdt>"
        "<w:p><w:r><w:instrText>PAGE   \\* MERGEFORMAT</w:instrText></w:r>" + _t("2") + "</w:p>",
    )


def _plantillas(carpeta: Path) -> Path:
    """Las dos plantillas, con la estructura de las reales."""
    doc_documentos = _parte(
        "document",
        "<w:p>"
        + _t("JEJ-", "XXXXXX", "PROCEDIMIENTO ", "XXXXXXXXXX")
        + "</w:p><w:p>"
        + _t("JEJ-", "XXXXXX", "PROCEDIMIENTO ", "XXXXXXXXXX")
        + "</w:p><w:p>"
        + _t("z", "Inicio prueba")
        + "</w:p>",
    )
    cabecera = _parte(
        "hdr",
        "<w:p>"
        + _t("JEJ-", "XXXXXXXX", "PROCEDIMIENTO", "XXXXXXXXXXXXX")
        + "</w:p><w:p>"
        + _t("JEJ-", "XXXXXXXX", "PROCEDIMIENTO", "XXXXXXXXXXXXX")
        + "</w:p>",
    )
    _docx(
        carpeta / "Portada Documentos.docx",
        {
            "word/document.xml": doc_documentos,
            "word/header1.xml": cabecera,
            "word/header2.xml": cabecera,
            "word/footer1.xml": _pie_con_autor("XXXXXXXx"),
            "word/footer2.xml": _parte("ftr", "<w:p/>"),
            "docProps/core.xml": _core("XXXXXXXx"),
        },
    )
    doc_ofertas = _parte(
        "document",
        "<w:p>"
        + _t("SERVICIO DE ", "XXXXXXXXXXXXXXXXXXXXX", "PLAN DE XXXXXXXXXXXXX")
        + "</w:p><w:p>"
        + _t("SERVICIO DE ", "XXXXXXXXXXXXXXXXXXXXX", "PLAN DE XXXXXXXXXXXXX")
        + "</w:p>",
    )
    _docx(
        carpeta / "Portada Ofertas y Planes Licitaciones.docx",
        {
            "word/document.xml": doc_ofertas,
            "word/header1.xml": _parte("hdr", "<w:p/>"),
            "word/footer1.xml": _pie_con_autor("PLAN DE XXXXXX"),
            "docProps/core.xml": _core("PLAN DE XXXXXX"),
        },
    )
    return carpeta


def _textos(ruta: Path) -> dict[str, list[str]]:
    """El texto de cada parte con el lector del zip, no con el código que lo escribió."""
    salida = {}
    with zipfile.ZipFile(ruta) as z:
        for nombre in z.namelist():
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nombre):
                xml = z.read(nombre).decode("utf-8")
                salida[nombre] = re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml)
    return salida


def _creador(ruta: Path) -> str:
    with zipfile.ZipFile(ruta) as z:
        return re.search(r"<dc:creator>([^<]*)</dc:creator>", z.read("docProps/core.xml").decode())[
            1
        ]


@pytest.fixture
def carpeta(tmp_path, settings):
    settings.PLANTILLAS_JEJ = (
        str(_plantillas(tmp_path / "plantillas"))
        if ((tmp_path / "plantillas").mkdir() or True)
        else ""
    )
    return Path(settings.PLANTILLAS_JEJ)


class TestRellenar:
    def test_documento_pone_codigo_titulo_y_autor_donde_van(self, carpeta, tmp_path):
        destino = tmp_path / "salida.docx"
        portadas.rellenar(
            "documento",
            {"codigo": "010203", "titulo": "TRABAJO SEGURO", "autor": "Ana Pérez"},
            destino,
        )
        textos = _textos(destino)
        assert textos["word/document.xml"] == [
            "JEJ-", "010203", "PROCEDIMIENTO ", "TRABAJO SEGURO",
            "JEJ-", "010203", "PROCEDIMIENTO ", "TRABAJO SEGURO",
            "z", "Inicio prueba",
        ]  # fmt: skip
        assert (
            textos["word/header1.xml"] == ["JEJ-", "010203", "PROCEDIMIENTO", "TRABAJO SEGURO"] * 2
        )
        assert textos["word/header2.xml"][1] == "010203"
        assert textos["word/footer1.xml"] == ["Ana Pérez", "2"]
        # El pie está enlazado a las propiedades: si no cambian, Word lo vuelve a escribir.
        assert _creador(destino) == "Ana Pérez"

    def test_oferta_pone_servicio_y_plan_y_el_pie_es_la_leyenda(self, carpeta, tmp_path):
        destino = tmp_path / "oferta.docx"
        portadas.rellenar("oferta", {"servicio": "TOPOGRAFÍA", "plan": "CALIDAD"}, destino)
        textos = _textos(destino)
        assert textos["word/document.xml"] == ["SERVICIO DE ", "TOPOGRAFÍA", "PLAN DE CALIDAD"] * 2
        assert textos["word/footer1.xml"] == ["PLAN DE CALIDAD", "2"]
        assert _creador(destino) == "PLAN DE CALIDAD"

    def test_no_queda_ningun_marcador_de_relleno(self, carpeta, tmp_path):
        for tipo, valores in (
            ("documento", {"codigo": "1", "titulo": "T", "autor": "A"}),
            ("oferta", {"servicio": "S", "plan": "P"}),
        ):
            destino = tmp_path / f"{tipo}.docx"
            portadas.rellenar(tipo, valores, destino)
            for partes in _textos(destino).values():
                assert not [t for t in partes if re.search(r"X{3,}", t)], tipo

    def test_lo_que_se_escribe_se_escapa(self, carpeta, tmp_path):
        destino = tmp_path / "salida.docx"
        portadas.rellenar(
            "documento",
            {"codigo": "A&B", "titulo": "<script>1</script>", "autor": 'Ana "la" jefa'},
            destino,
        )
        with zipfile.ZipFile(destino) as z:
            for nombre in z.namelist():
                if nombre.endswith(".xml"):
                    assert b"<script>" not in z.read(nombre)
        assert "A&amp;B" in _textos(destino)["word/document.xml"]

    def test_la_plantilla_no_se_toca(self, carpeta, tmp_path):
        import hashlib

        plantilla = carpeta / "Portada Documentos.docx"
        antes = (hashlib.sha256(plantilla.read_bytes()).hexdigest(), plantilla.stat().st_mtime_ns)
        portadas.rellenar(
            "documento", {"codigo": "1", "titulo": "T", "autor": "A"}, tmp_path / "x.docx"
        )
        assert (
            hashlib.sha256(plantilla.read_bytes()).hexdigest(),
            plantilla.stat().st_mtime_ns,
        ) == antes

    def test_un_campo_vacio_o_demasiado_largo_se_rechaza(self, carpeta, tmp_path):
        with pytest.raises(portadas.ComposicionInvalida, match="Falta «Código»"):
            portadas.rellenar(
                "documento", {"codigo": " ", "titulo": "T", "autor": "A"}, tmp_path / "x.docx"
            )
        with pytest.raises(portadas.ComposicionInvalida, match="no puede pasar"):
            portadas.rellenar(
                "documento", {"codigo": "x" * 500, "titulo": "T", "autor": "A"}, tmp_path / "x.docx"
            )

    def test_si_la_plantilla_cambio_y_no_tiene_el_campo_se_dice_y_no_se_entrega(self, tmp_path):
        base = tmp_path / "plantillas"
        base.mkdir()
        # Sin «PROCEDIMIENTO»: el título no tiene dónde ir.
        _docx(
            base / "Portada Documentos.docx",
            {
                "word/document.xml": _parte("document", "<w:p>" + _t("JEJ-", "XXXXXX") + "</w:p>"),
                "word/footer1.xml": _pie_con_autor("XXXXXXXx"),
                "docProps/core.xml": _core("XXXXXXXx"),
            },
        )
        destino = tmp_path / "x.docx"
        with pytest.raises(portadas.ComposicionInvalida, match="no tiene dónde poner: Título"):
            portadas.rellenar(
                "documento", {"codigo": "1", "titulo": "T", "autor": "A"}, destino, base=base
            )
        assert not destino.exists()

    def test_un_tipo_que_no_existe_se_rechaza(self, carpeta, tmp_path):
        with pytest.raises(portadas.ComposicionInvalida, match="no es una portada"):
            portadas.rellenar("otra", {}, tmp_path / "x.docx")


class TestSondar:
    def test_sin_carpeta_dice_como_ponerla(self, settings):
        settings.PLANTILLAS_JEJ = ""
        estado = portadas.sondar()
        assert not estado and "AEROCONVERT_PLANTILLAS_JEJ" in estado.sugerencia

    def test_con_una_sola_plantilla_la_otra_sale_apagada(self, tmp_path, settings):
        base = tmp_path / "p"
        base.mkdir()
        _plantillas(base)
        (base / "Portada Ofertas y Planes Licitaciones.docx").unlink()
        settings.PLANTILLAS_JEJ = str(base)
        estado = portadas.sondar()
        assert estado.tiene("documento") and not estado.tiene("oferta")

    def test_la_herramienta_sale_apagada_con_su_motivo_sin_plantillas(self, settings):
        from apps.documents import views

        settings.PLANTILLAS_JEJ = ""
        fila = next(h for h in views.estado_de_herramientas() if h["id"] == "portada")
        assert fila["disponible"] is False and "plantillas" in fila["motivo"]
        assert motor.disponibilidad("portada").codigo_motivo == "sin-plantillas"

    def test_con_plantillas_esta_disponible(self, carpeta):
        from apps.documents import views

        fila = next(h for h in views.estado_de_herramientas() if h["id"] == "portada")
        assert fila["disponible"] is True


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_rellena_con_la_plantilla_como_entrada(self, carpeta, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "portada",
            {
                "entradas": [{"ruta": str(carpeta / "Portada Ofertas y Planes Licitaciones.docx")}],
                "opciones": {"tipo": "oferta", "valores": {"servicio": "S", "plan": "P"}},
            },
            parcial,
        )
        assert "codigo" not in informe
        assert _creador(parcial) == "PLAN DE P"

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:portada")).status_code == 302

    def test_sin_plantillas_la_pantalla_dice_por_que_no_se_puede(self, sesion, settings):
        settings.PLANTILLAS_JEJ = ""
        cuerpo = sesion.get(reverse("documents:portada")).content.decode()
        assert "Aquí no se puede" in cuerpo and "AEROCONVERT_PLANTILLAS_JEJ" in cuerpo
        assert "Hacer la portada" not in cuerpo

    def test_con_plantillas_ofrece_las_dos_y_sus_campos(self, sesion, carpeta):
        cuerpo = sesion.get(reverse("documents:portada")).content.decode()
        assert "Título del procedimiento" in cuerpo and "Hacer la portada" in cuerpo
        oferta = sesion.get(reverse("documents:portada"), {"tipo": "oferta"}).content.decode()
        assert "Servicio" in oferta and "Plan" in oferta and "Autor" not in oferta

    def test_un_campo_vacio_avisa_y_no_encola(self, sesion, carpeta):
        respuesta = sesion.post(
            reverse("documents:portada"),
            {"tipo": "documento", "codigo": "", "titulo": "T", "autor": "A"},
        )
        assert respuesta.status_code == 200 and "Falta" in respuesta.content.decode()

    def test_hacer_la_portada_encola_y_entrega_un_docx_en_la_carpeta_de_trabajo(
        self, sesion, carpeta, tmp_path
    ):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(
            reverse("documents:portada"),
            {"tipo": "documento", "codigo": "030405", "titulo": "IZAJE", "autor": "Luis"},
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail

        salida = Path(trabajo.output_path)
        assert salida.suffix == ".docx" and "030405" in salida.name
        # No quedó entre las plantillas.
        assert carpeta not in salida.parents
        assert "030405" in " ".join(_textos(salida)["word/document.xml"])

    def test_el_word_terminado_ofrece_seguir_a_pdf_si_hay_office(
        self, sesion, carpeta, monkeypatch
    ):
        from apps.documents import office
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        sesion.post(
            reverse("documents:portada"),
            {"tipo": "oferta", "servicio": "S", "plan": "P"},
        )
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")

        monkeypatch.setattr(office, "sondar", lambda **_: office.Disponible(frozenset({"word"})))
        con = sesion.get(reverse("jobs:ficha", args=[trabajo.pk])).content.decode()
        assert "Office a PDF" in con and f"resultado%3A{trabajo.pk}" in con

        monkeypatch.setattr(office, "sondar", lambda **_: office.Disponible(frozenset(), "no hay"))
        sin = sesion.get(reverse("jobs:ficha", args=[trabajo.pk])).content.decode()
        assert "Office a PDF" not in sin.split("Seguir con este archivo")[-1][:600]


class TestLaVerificacion:
    def test_una_portada_con_marcadores_sin_cambiar_no_se_da_por_buena(self, carpeta, tmp_path):
        # Una portada **sin rellenar**: la plantilla tal cual.
        copia = tmp_path / "sin_rellenar.docx"
        copia.write_bytes((carpeta / "Portada Documentos.docx").read_bytes())
        veredicto = motor.verificar(copia, {"detalles": {"portada": "documento"}})
        assert not veredicto.correcta and "marcadores de relleno" in veredicto.motivo

    def test_una_portada_rellena_si(self, carpeta, tmp_path):
        destino = tmp_path / "ok.docx"
        portadas.rellenar("oferta", {"servicio": "S", "plan": "P"}, destino)
        assert motor.verificar(destino, {"detalles": {"portada": "oferta"}}).correcta


REALES = Path(
    r"D:\OneDrive - J.E.J. Ingeniería S.A\APLICACIONES NUEVO LOGO - presentaciones jej\2023"
)


@pytest.mark.oraculo
@pytest.mark.skipif(
    not (REALES / "Portada Documentos.docx").is_file(), reason="las plantillas reales no están aquí"
)
@pytest.mark.parametrize(
    ("tipo", "valores", "esperado"),
    [
        (
            "documento",
            {"codigo": "990011", "titulo": "IZAJE DE CARGAS", "autor": "Prueba Autor"},
            "IZAJE DE CARGAS",
        ),
        ("oferta", {"servicio": "LEVANTAMIENTO TOPOGRÁFICO", "plan": "CALIDAD"}, "LEVANTAMIENTO"),
    ],
)  # fmt: skip
def test_con_las_plantillas_reales_word_las_abre_y_el_pdf_lleva_los_datos(
    tmp_path, tipo, valores, esperado
):
    """El oráculo de verdad: Word abre el `.docx` y exporta a PDF; `pypdf` lee el texto."""
    from pypdf import PdfReader

    from apps.documents import office

    if not office.sondar().tiene("word"):
        pytest.skip("Word no está en esta máquina")

    docx = tmp_path / "portada.docx"
    portadas.rellenar(tipo, valores, docx, base=REALES)
    assert not [t for p in _textos(docx).values() for t in p if re.search(r"X{3,}", t)]

    pdf = tmp_path / "portada.pdf"
    office.convertir(docx, pdf)
    texto = " ".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)
    assert esperado in texto
    assert not re.search(r"X{4,}", texto)
