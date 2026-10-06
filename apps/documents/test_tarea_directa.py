"""`tarea.py` por dentro: cada herramienta que corre el hijo, sin pasar por la cola.

Las pruebas de la cola cubren el camino entero (pantalla, cola, corredor, descarga). Esto cubre
lo que solo se ve llamando a `tarea.ejecutar` con un encargo: qué sale al fallar, cuándo no
hay archivo y por qué, y que ninguna carpeta de piezas se quede sin barrer.

El oráculo de cada salida es **pypdf reabriéndola**, no lo que la tarea devuelve en `detalles`.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from apps.documents import tarea


def _pdf(carpeta: Path, nombre: str = "doc.pdf", cuantas: int = 3) -> Path:
    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=595, height=842)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _encargo(*rutas: Path, **opciones) -> dict:
    return {"entradas": [{"ruta": str(r)} for r in rutas], "opciones": opciones}


def _paginas(ruta: Path) -> int:
    return len(PdfReader(str(ruta)).pages)


class TestElDespacho:
    def test_una_herramienta_desconocida_no_se_ejecuta_desde_la_cola(self, tmp_path):
        informe = tarea.ejecutar("no-existe", {}, tmp_path / "p")
        assert informe["codigo"] == "sin-motor"

    def test_un_fallo_de_tarea_viaja_con_su_codigo(self, tmp_path, monkeypatch):
        monkeypatch.delenv(tarea.VARIABLE_CONTRASENA, raising=False)
        informe = tarea.ejecutar(
            "proteger", _encargo(_pdf(tmp_path), accion="proteger"), tmp_path / "p"
        )
        assert informe["codigo"] == "falta-la-contrasena"

    def test_el_progreso_se_recorta_a_cero_y_uno(self, capsys):
        tarea.progreso(-3)
        tarea.progreso(7)
        tarea.progreso(0.5)
        assert capsys.readouterr().out.split("\n")[:3] == [
            "PROGRESO 0.000",
            "PROGRESO 1.000",
            "PROGRESO 0.500",
        ]


class TestMarcasYComposicion:
    def test_numerar_escribe_todas_las_paginas(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar("numerar", _encargo(_pdf(tmp_path)), parcial)
        assert "codigo" not in informe
        assert _paginas(parcial) == 3
        assert informe["detalles"]["paginas"] == 3

    def test_la_marca_de_agua_escribe_un_pdf_del_mismo_largo(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "marca", _encargo(_pdf(tmp_path, cuantas=2), texto="BORRADOR"), parcial
        )
        assert "codigo" not in informe
        assert _paginas(parcial) == 2

    def test_unir_junta_las_paginas_de_la_receta(self, tmp_path):
        a, b = _pdf(tmp_path, "a.pdf", 2), _pdf(tmp_path, "b.pdf", 1)
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar("unir", _encargo(a, b, receta="0:1:0,1:1:0,0:2:0"), parcial)
        assert "codigo" not in informe
        assert _paginas(parcial) == 3
        assert informe["detalles"]["paginas"] == 3

    def test_una_receta_vacia_es_un_documento_invalido(self, tmp_path):
        informe = tarea.ejecutar(
            "unir", _encargo(_pdf(tmp_path), receta="basura"), tmp_path / "salida.parcial"
        )
        assert informe["codigo"] == "documento-invalido"
        assert "vacía" in informe["mensaje"]

    def test_imagenes_a_pdf_hace_una_pagina_por_imagen(self, tmp_path):
        from PIL import Image

        rutas = []
        for n in range(2):
            ruta = tmp_path / f"i{n}.png"
            Image.new("RGB", (40, 30), "white").save(ruta)
            rutas.append(ruta)
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar("imagenes", _encargo(*rutas, tamano="a4"), parcial)
        assert "codigo" not in informe
        assert _paginas(parcial) == 2


class TestPiezas:
    def test_varias_piezas_salen_en_un_zip_y_la_carpeta_se_barre(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "dividir", _encargo(_pdf(tmp_path), trozos=[[1, 1], [2, 3]]), parcial
        )
        assert "codigo" not in informe
        with zipfile.ZipFile(parcial) as paquete:
            nombres = paquete.namelist()
            assert len(nombres) == 2
        assert [p["paginas"] for p in informe["detalles"]["piezas"]] == [1, 2]
        assert not tarea.carpeta_de_piezas(parcial).exists()

    def test_una_sola_pieza_sale_suelta_sin_zip(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar("dividir", _encargo(_pdf(tmp_path), trozos=[[1, 2]]), parcial)
        assert "codigo" not in informe
        assert not zipfile.is_zipfile(parcial)
        assert _paginas(parcial) == 2
        assert not tarea.carpeta_de_piezas(parcial).exists()

    def test_paginas_a_imagenes_en_zip_y_suelta(self, tmp_path):
        varias = tmp_path / "varias.parcial"
        informe = tarea.ejecutar(
            "a_imagenes", _encargo(_pdf(tmp_path), paginas=[1, 2], formato="png", ppp=96), varias
        )
        assert "codigo" not in informe
        with zipfile.ZipFile(varias) as paquete:
            assert len(paquete.namelist()) == 2
        assert not tarea.carpeta_de_piezas(varias).exists()

        una = tmp_path / "una.parcial"
        tarea.ejecutar(
            "a_imagenes", _encargo(_pdf(tmp_path), paginas=[3], formato="png", ppp=96), una
        )
        assert not zipfile.is_zipfile(una)
        assert una.read_bytes()[:4] == b"\x89PNG"

    def test_el_zip_guarda_sin_comprimir_lo_que_ya_viene_comprimido(self, tmp_path):
        pdf, png = tmp_path / "a.pdf", tmp_path / "b.png"
        pdf.write_bytes(b"%PDF-1.4\n" + b"a" * 4000)
        png.write_bytes(b"\x89PNG" + b"a" * 4000)
        parcial = tmp_path / "salida.parcial"
        tarea._entregar_piezas([pdf, png], parcial, [{"nombre": "a.pdf"}, {"nombre": "b.png"}])
        with zipfile.ZipFile(parcial) as paquete:
            modos = {i.filename: i.compress_type for i in paquete.infolist()}
        assert modos == {"a.pdf": zipfile.ZIP_DEFLATED, "b.png": zipfile.ZIP_STORED}


class TestProtegerYOcr:
    def test_proteger_y_quitar_la_contrasena_dan_la_vuelta_completa(self, tmp_path, monkeypatch):
        origen = _pdf(tmp_path)
        cifrado = tmp_path / "cifrado.parcial"
        monkeypatch.setenv(tarea.VARIABLE_CONTRASENA, "obra-2026-bhp")
        informe = tarea.ejecutar("proteger", _encargo(origen, accion="proteger"), cifrado)
        assert informe["detalles"]["accion"] == "proteger"
        assert PdfReader(str(cifrado)).is_encrypted
        assert tarea.VARIABLE_CONTRASENA not in __import__("os").environ, "no queda en el entorno"

        abierto = tmp_path / "abierto.parcial"
        monkeypatch.setenv(tarea.VARIABLE_CONTRASENA, "obra-2026-bhp")
        informe = tarea.ejecutar("proteger", _encargo(cifrado, accion="quitar"), abierto)
        assert "codigo" not in informe
        assert not PdfReader(str(abierto)).is_encrypted

    def test_una_accion_que_no_es_ni_poner_ni_quitar_se_rechaza(self, tmp_path, monkeypatch):
        monkeypatch.setenv(tarea.VARIABLE_CONTRASENA, "x" * 12)
        informe = tarea.ejecutar(
            "proteger", _encargo(_pdf(tmp_path), accion="girar"), tmp_path / "p"
        )
        assert informe["codigo"] == "documento-invalido"

    def test_ocr_sin_la_ruta_de_tesseract_falla_con_su_codigo(self, tmp_path, monkeypatch):
        monkeypatch.delenv(tarea.VARIABLE_TESSERACT, raising=False)
        informe = tarea.ejecutar("ocr", _encargo(_pdf(tmp_path)), tmp_path / "p")
        assert informe["codigo"] == "sin-tesseract"


class TestSinArchivo:
    def test_un_pdf_sin_texto_no_es_un_fallo_es_la_respuesta(self, tmp_path):
        informe = tarea.ejecutar("md_pdf", _encargo(_pdf(tmp_path)), tmp_path / "salida.parcial")
        assert informe["desenlace"] == "sin-texto-que-sacar"
        assert "motivo" in informe["detalles"]
        assert not (tmp_path / "salida.parcial").exists()

    def test_los_avisos_salen_aparte_de_los_detalles(self, tmp_path, monkeypatch):
        monkeypatch.setitem(
            tarea.TAREAS, "numerar", lambda e, o, p: {"avisos": ["una tabla vacía"], "x": 1}
        )
        informe = tarea.ejecutar("numerar", {}, tmp_path / "p")
        assert informe == {"detalles": {"x": 1}, "avisos": ["una tabla vacía"]}


class TestCatalogosYMarkdown:
    def test_excel_a_catalogo_pide_los_dos_archivos(self, tmp_path):
        encargo = {
            "entradas": [{"ruta": str(tmp_path / "h.xlsx"), "papel": "hoja"}],
            "opciones": {},
        }
        informe = tarea.ejecutar("excel_catalogo", encargo, tmp_path / "p")
        assert informe["codigo"] == "documento-invalido"
        assert "los dos archivos" in informe["mensaje"]

    def test_markdown_a_pdf_escribe_un_pdf_que_se_abre(self, tmp_path):
        md = tmp_path / "nota.md"
        md.write_text("# Título\n\nUn párrafo con **negrita**.\n", encoding="utf-8")
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar("md_a_pdf", _encargo(md), parcial)
        assert informe == {"detalles": {}}
        assert _paginas(parcial) >= 1


class TestElPuntoDeEntrada:
    def test_con_otro_numero_de_argumentos_explica_el_uso(self, capsys):
        assert tarea.main(["solo-uno"]) == 2
        assert "uso:" in capsys.readouterr().out

    def test_escribe_el_informe_y_devuelve_cero(self, tmp_path):
        encargo = tmp_path / "encargo.json"
        encargo.write_text(json.dumps(_encargo(_pdf(tmp_path))), encoding="utf-8")
        informe = tmp_path / "informe.json"
        parcial = tmp_path / "salida.parcial"

        codigo = tarea.main(["numerar", str(encargo), str(parcial), str(informe)])

        assert codigo == 0
        assert json.loads(informe.read_text(encoding="utf-8"))["detalles"]["paginas"] == 3

    def test_un_fallo_devuelve_uno_y_escribe_error_por_stderr(self, tmp_path, capsys):
        encargo = tmp_path / "encargo.json"
        encargo.write_text(json.dumps({"entradas": [], "opciones": {}}), encoding="utf-8")
        informe = tmp_path / "informe.json"

        codigo = tarea.main(["desconocida", str(encargo), str(tmp_path / "p"), str(informe)])

        assert codigo == 1
        assert json.loads(informe.read_text(encoding="utf-8"))["codigo"] == "sin-motor"
        assert "ERROR:" in capsys.readouterr().err
