"""El corredor con una herramienta de documentos, **con el proceso hijo de verdad**.

## Por qué el hijo de verdad y no uno de mentira

Porque lo que puede fallar aquí está justo en la frontera: que el hijo arranque sin Django,
que el progreso llegue antes del final, que el informe diga el motivo verdadero, que el
parcial acabe donde el corredor lo busca. Un motor de mentira se saltaría las cuatro.

Se usa **Numerar** porque no necesita nada instalado y tarda un instante: es el caso
mínimo que ejercita todo el camino.

## Y la regla que se vigila en cada camino de fallo

**El original no se toca.** Se comparan su `sha256` y su fecha antes y después, no solo en
el camino feliz: es en los caminos de fallo donde aparecen los `unlink` mal apuntados.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.documents import motor as documentos
from apps.engines.base import PlanDeEjecucion, Verificacion
from apps.jobs import despachador, runner
from apps.jobs.models import CANCELADO, ENCOLADO, ERROR, HECHO, ConversionJob, EntradaDeTrabajo

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def carpeta_de_trabajo(tmp_path, settings):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    return tmp_path / "trabajo"


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


def _pdf(ruta: Path, paginas: int = 3) -> Path:
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    for n in range(paginas):
        hoja.drawString(72, 720, f"Página {n + 1}")
        hoja.showPage()
    hoja.save()
    return ruta


@pytest.fixture
def plano(tmp_path):
    return _pdf(tmp_path / "plano.pdf")


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _trabajo(usuario, origen: Path, herramienta="numerar", salida=None, **opciones):
    salida = salida or origen.with_name(f"{origen.stem}_numerado{origen.suffix}")
    job = ConversionJob.objects.create(
        owner=usuario,
        herramienta=herramienta,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code=f"doc:{herramienta}",
        output_path=str(salida),
        options=opciones,
        status=ENCOLADO,
    )
    EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(origen), nombre=origen.name)
    return job


def _correr(job) -> ConversionJob:
    assert runner.reclamar(job.pk)
    job.refresh_from_db()
    runner.ejecutar(job)
    job.refresh_from_db()
    return job


class TestElCaminoEntero:
    def test_numera_y_queda_hecho(self, usuario, plano):
        job = _correr(_trabajo(usuario, plano))
        assert job.status == HECHO, job.reason_detail
        salida = Path(job.output_path)
        assert salida.exists()
        assert job.verification["paginas_verificadas"] == 3

    def test_lo_verifica_otra_biblioteca(self, usuario, plano):
        """Las herramientas escriben con pypdf; contar las páginas con pypdf sería el código
        dándose la razón. Se cuentan con PDFium."""
        job = _correr(_trabajo(usuario, plano))
        assert job.verification["verificado_con"] == "PDFium"

    def test_el_historial_dice_la_herramienta(self, usuario, plano):
        """«doc:numerar» en el historial sería el mismo defecto que enseñar `geotiff`."""
        job = _correr(_trabajo(usuario, plano))
        assert job.nombre_del_destino == "Numerar páginas"

    def test_guarda_la_huella_de_la_entrada(self, usuario, plano):
        antes, _ = _huella(plano)
        job = _correr(_trabajo(usuario, plano))
        entrada = job.entradas.get()
        assert entrada.sha256 == antes
        assert entrada.mtime_ns is not None

    def test_no_deja_ni_parcial_ni_encargo_ni_informe(self, usuario, plano, carpeta_de_trabajo):
        job = _correr(_trabajo(usuario, plano))
        assert not list(plano.parent.glob("*.parcial*"))
        assert not list(carpeta_de_trabajo.glob(f"{job.pk}.*"))

    def test_un_csv_no_se_lee_como_libreta_de_puntos(self, usuario, tmp_path):
        """**El fallo que obligó a tener una rama propia.** Por el camino geoespacial, un
        `.csv` se inspecciona como libreta de puntos y se rechaza con `crs-ausente`."""
        tabla = tmp_path / "coordenadas.csv"
        tabla.write_text("punto;este;norte\nP1;495279.4;7318729.0\n", encoding="utf-8")
        job = _correr(
            _trabajo(usuario, tabla, herramienta="md_csv", salida=tmp_path / "coordenadas.md")
        )
        assert job.status == HECHO, job.reason_detail
        assert job.reason_code != "crs-ausente"
        assert "P1" in Path(job.output_path).read_text(encoding="utf-8")


class TestElHijo:
    def test_corre_sin_django(self, plano, tmp_path):
        """Leer una cadena de ajustes no justifica levantar la base de datos, y las sondas que
        la necesitan las hace el padre. Si el hijo importara Django, esto fallaría."""
        import json

        encargo = tmp_path / "encargo.json"
        encargo.write_text(
            json.dumps({"entradas": [{"ruta": str(plano), "nombre": plano.name}], "opciones": {}}),
            encoding="utf-8",
        )
        parcial = tmp_path / "salida.parcial.pdf"
        informe = tmp_path / "informe.json"
        entorno = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}

        resultado = subprocess.run(  # nosec B603 - argv fijo de la prueba
            [
                sys.executable,
                "-m",
                "apps.documents.tarea",
                "numerar",
                str(encargo),
                str(parcial),
                str(informe),
            ],
            cwd=settings.BASE_DIR,
            env=entorno,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert resultado.returncode == 0, resultado.stderr
        assert parcial.exists()
        assert json.loads(informe.read_text(encoding="utf-8"))["detalles"]["paginas"] == 3


class TestLosCaminosDeFallo:
    """En cada uno, **el original sigue exactamente como estaba**."""

    def test_un_pdf_que_no_lo_es_dice_por_que(self, usuario, tmp_path):
        """El hijo sabe el motivo verdadero; sin el informe, el corredor solo vería un código
        de salida distinto de cero y lo llamaría «error del motor»."""
        falso = tmp_path / "falso.pdf"
        falso.write_bytes(b"esto no es un PDF")
        antes = _huella(falso)

        job = _correr(_trabajo(usuario, falso))

        assert job.status == ERROR
        assert job.reason_code == "documento-invalido"
        assert _huella(falso) == antes
        assert not list(tmp_path.glob("*.parcial*"))

    def test_una_verificacion_fallida_no_deja_nada(self, usuario, plano, monkeypatch):
        antes = _huella(plano)
        monkeypatch.setattr(
            documentos,
            "verificar",
            lambda parcial, informe, plan=None: Verificacion(False, "inventado", "salida-invalida"),
        )
        job = _correr(_trabajo(usuario, plano))
        assert job.status == ERROR
        assert job.reason_code == "salida-invalida"
        assert not Path(job.output_path).exists()
        assert _huella(plano) == antes

    def test_terminar_sin_archivo_y_sin_decir_por_que_es_sin_salida(
        self, usuario, plano, monkeypatch
    ):
        """**La excepción a la regla número uno exige un motivo.** Con `salida_opcional`, un
        hijo que simplemente no escribe nada sigue siendo `sin-salida`."""
        antes = _huella(plano)

        def plan_mudo(job):
            return PlanDeEjecucion(
                argv=(sys.executable, "-c", "pass"),
                ruta_de_salida=Path(job.output_path),
                salida_opcional=True,
                emite_progreso=False,
                timeout_s=30,
            )

        monkeypatch.setattr(documentos, "plan", plan_mudo)
        job = _correr(_trabajo(usuario, plano))
        assert job.status == ERROR
        assert job.reason_code == "sin-salida"
        assert _huella(plano) == antes

    def test_cancelar_mata_al_hijo(self, usuario, plano, monkeypatch):
        from django.utils import timezone

        antes = _huella(plano)

        def plan_lento(job):
            return PlanDeEjecucion(
                argv=(sys.executable, "-c", "import time; time.sleep(60)"),
                ruta_de_salida=Path(job.output_path),
                emite_progreso=False,
                timeout_s=120,
            )

        monkeypatch.setattr(documentos, "plan", plan_lento)
        job = _trabajo(usuario, plano)
        job.cancel_requested_at = timezone.now()
        job.save(update_fields=["cancel_requested_at"])

        job = _correr(job)
        assert job.status == CANCELADO
        assert _huella(plano) == antes

    def test_una_herramienta_que_falta_se_dice_con_su_codigo(self, usuario, plano, monkeypatch):
        from apps.engines.base import Disponibilidad

        monkeypatch.setattr(
            documentos,
            "disponibilidad",
            lambda h: Disponibilidad.no("sin-office", "No hay Office en esta máquina."),
        )
        job = _correr(_trabajo(usuario, plano))
        assert job.status == ERROR
        assert job.reason_code == "sin-office"


class TestTerminarBienSinArchivo:
    def test_un_escaneo_a_markdown_es_un_desenlace_y_no_un_fallo(self, usuario, tmp_path):
        """**No hay texto que sacar, y eso es la respuesta.** Un `.md` vacío sería la peor forma
        de decirlo, y un error rojo mandaría a reintentar con el mismo archivo."""
        from PIL import Image

        foto = tmp_path / "hoja.png"
        Image.new("RGB", (400, 400), "white").save(foto)
        escaneo = tmp_path / "escaneo.pdf"
        hoja = canvas.Canvas(str(escaneo), pagesize=A4)
        hoja.drawImage(str(foto), 50, 50, width=400, height=400)
        hoja.showPage()
        hoja.save()

        job = _correr(
            _trabajo(usuario, escaneo, herramienta="md_pdf", salida=tmp_path / "escaneo.md")
        )
        assert job.status == HECHO, job.reason_detail
        assert job.desenlace == "sin-texto-que-sacar"
        assert job.output_path == ""
        assert not (tmp_path / "escaneo.md").exists()


class TestLosOriginalesSeMiranTodos:
    def test_un_cambio_en_cualquier_entrada_queda_escrito(self, usuario, tmp_path):
        """Con un solo `source_path` solo se vigilaba la primera: en un «Unir» de veinte, las
        otras diecinueve quedaban sin mirar."""
        uno, dos = _pdf(tmp_path / "uno.pdf"), _pdf(tmp_path / "dos.pdf")
        job = _trabajo(usuario, uno)
        segunda = EntradaDeTrabajo.objects.create(
            job=job, orden=1, ruta=str(dos), nombre=dos.name, mtime_ns=1
        )

        runner._comprobar_originales(job, [job.entradas.get(orden=0), segunda])

        mensajes = " ".join(e.message for e in job.eventos.all())
        assert "dos.pdf" in mensajes and "cambió" in mensajes


class TestLosCarriles:
    """Un «numerar» de un segundo no espera detrás de una ortofoto de tres horas."""

    def test_el_carril_ligero_coge_el_documento(self, usuario, plano, tmp_path):
        geo = ConversionJob.objects.create(
            owner=usuario,
            source_path=str(tmp_path / "orto.tif"),
            source_name="orto.tif",
            target_format_code="cog",
            status=ENCOLADO,
        )
        doc = _trabajo(usuario, plano)

        ligeros = despachador._del_carril(ConversionJob.objects.filter(status=ENCOLADO), "ligero")
        pesados = despachador._del_carril(ConversionJob.objects.filter(status=ENCOLADO), "pesado")
        assert list(ligeros) == [doc]
        assert list(pesados) == [geo]

    def test_lo_geoespacial_es_siempre_pesado(self):
        assert documentos.carril_de("") == "pesado"

    def test_procesar_el_carril_ligero_hace_el_documento(self, usuario, plano):
        doc = _trabajo(usuario, plano)
        assert despachador.procesar_una_vez("ligero") == 1
        doc.refresh_from_db()
        assert doc.status == HECHO, doc.reason_detail


class TestVariasPiezas:
    """Dividir y PDF a imágenes: **varias salidas en un zip, y todas o ninguna**."""

    def _dividir(self, usuario, origen, trozos):
        salida = origen.with_name(f"{origen.stem}_partes.zip")
        return _trabajo(usuario, origen, herramienta="dividir", salida=salida, trozos=trozos)

    def test_el_zip_sale_con_cada_pieza_abierta_por_pdfium(self, usuario, plano):
        import zipfile

        antes = _huella(plano)
        job = _correr(self._dividir(usuario, plano, [[1, 1], [2, 3]]))
        assert job.status == HECHO, job.reason_detail
        with zipfile.ZipFile(job.output_path) as paquete:
            assert sorted(paquete.namelist()) == ["plano_1.pdf", "plano_2-3.pdf"]
        assert job.verification["piezas_verificadas"] == 2
        assert _huella(plano) == antes
        assert not list(plano.parent.glob("*.piezas"))

    def test_un_trozo_imposible_no_deja_ni_zip_ni_piezas(self, usuario, plano):
        """El tercer trozo pide la página 9 de un documento de 3: las dos primeras piezas ya
        estaban escritas, y **no se entregan**."""
        antes = _huella(plano)
        job = _correr(self._dividir(usuario, plano, [[1, 1], [2, 2], [9, 9]]))
        assert job.status == ERROR
        assert job.reason_code == "documento-invalido"
        assert "3 página(s)" in job.reason_detail
        assert not Path(job.output_path).exists()
        assert not list(plano.parent.glob("*.parcial*"))
        assert _huella(plano) == antes

    def test_si_el_hijo_muere_el_corredor_se_lleva_las_piezas(self, usuario, plano):
        """El hijo las borra al terminar; si lo mata un plazo, no llega a hacerlo."""
        from apps.documents.tarea import carpeta_de_piezas
        from apps.engines.base import ruta_parcial

        job = self._dividir(usuario, plano, [[1, 1]])
        carpeta = carpeta_de_piezas(ruta_parcial(Path(job.output_path)))
        carpeta.mkdir()
        (carpeta / "plano_1.pdf").write_bytes(b"%PDF-1.7\n")
        documentos.borrar_auxiliares(job)
        assert not carpeta.exists()

    def test_y_el_barrido_las_reconoce_si_murio_el_obrero_entero(self, carpeta_de_trabajo):
        """Las piezas se llaman como dentro del zip —`plano_3.pdf`—, sin marca de trabajo.
        La lleva la carpeta, y el barrido tiene que mirarla."""
        from apps.jobs import retencion

        carpeta = carpeta_de_trabajo / "plano_partes.parcial.zip.piezas"
        carpeta.mkdir(parents=True)
        pieza = carpeta / "plano_3.pdf"
        pieza.write_bytes(b"x" * 10)
        hace_dos_horas = pieza.stat().st_mtime - 7200
        os.utime(pieza, (hace_dos_horas, hace_dos_horas))
        retencion._barrer_huerfanos()
        assert not pieza.exists()


class TestVariasEntradas:
    """Unir e Imágenes a PDF: **la huella de cada una**, no solo de la primera."""

    def _con_entradas(self, usuario, origenes, herramienta, salida, **opciones):
        job = _trabajo(usuario, origenes[0], herramienta=herramienta, salida=salida, **opciones)
        for orden, origen in enumerate(origenes[1:], start=1):
            EntradaDeTrabajo.objects.create(
                job=job, orden=orden, ruta=str(origen), nombre=origen.name
            )
        return job

    def test_unir_sigue_la_receta_y_guarda_cada_huella(self, usuario, tmp_path):
        memoria = _pdf(tmp_path / "memoria.pdf", 3)
        planos = _pdf(tmp_path / "planos.pdf", 2)
        job = _correr(
            self._con_entradas(
                usuario,
                [memoria, planos],
                "unir",
                tmp_path / "memoria_unido.pdf",
                receta="1:2:0,0:1:90,0:3:0",
            )
        )
        assert job.status == HECHO, job.reason_detail
        assert job.verification["paginas_verificadas"] == 3
        assert job.verification["por_archivo"] == [["planos.pdf", 1], ["memoria.pdf", 2]]
        assert [e.sha256 for e in job.entradas.all()] == [
            _huella(memoria)[0],
            _huella(planos)[0],
        ]

    def test_una_imagen_que_no_lo_es_no_toca_ninguna(self, usuario, tmp_path):
        from PIL import Image

        buena = tmp_path / "foto1.jpg"
        Image.new("RGB", (300, 200), (200, 40, 40)).save(buena)
        mala = tmp_path / "foto2.jpg"
        mala.write_bytes(b"esto no es un jpeg")
        antes = [_huella(buena), _huella(mala)]

        job = _correr(
            self._con_entradas(usuario, [buena, mala], "imagenes", tmp_path / "foto1_imagenes.pdf")
        )
        assert job.status == ERROR
        assert job.reason_code == "documento-invalido"
        assert "foto2.jpg" in job.reason_detail
        assert not (tmp_path / "foto1_imagenes.pdf").exists()
        assert not list(tmp_path.glob("*.parcial*"))
        assert [_huella(buena), _huella(mala)] == antes


class TestProteger:
    CLAVE = "obra-2026-bhp-centinela"

    def _trabajo(self, usuario, origen, accion="proteger"):
        return _trabajo(
            usuario,
            origen,
            herramienta="proteger",
            salida=origen.with_name(f"{origen.stem}_protegido.pdf"),
            accion=accion,
            pide_contrasena=True,
        )

    def test_con_la_contrasena_guardada_cifra_y_la_borra(self, usuario, plano):
        from apps.documents import secretos

        job = self._trabajo(usuario, plano)
        secretos.guardar(job, self.CLAVE)
        job = _correr(job)
        assert job.status == HECHO, job.reason_detail
        assert job.verification["cifrado"] == "AES-256"
        assert not secretos.ruta(job).exists()

    def test_sin_ella_para_antes_de_escribir_nada(self, usuario, plano):
        """Caducó, o el barrido se la llevó: se dice, y «Reintentar» lleva a escribirla."""
        antes = _huella(plano)
        job = _correr(self._trabajo(usuario, plano))
        assert job.status == ERROR
        assert job.reason_code == "falta-la-contrasena"
        assert not Path(job.output_path).exists()
        assert _huella(plano) == antes

    def test_si_falla_antes_de_tomarla_no_se_queda_en_disco(self, usuario, plano):
        from apps.documents import secretos

        job = self._trabajo(usuario, plano)
        secretos.guardar(job, self.CLAVE)
        plano.unlink()  # el original desaparece: falla al calcular la huella
        job = _correr(job)
        assert job.status == ERROR
        assert not secretos.ruta(job).exists()

    def test_un_pdf_que_se_abre_sin_clave_no_esta_protegido(self, plano, tmp_path):
        """Un error que dejara el PDF en claro se abriría bien y parecería que funcionó."""
        hecho = documentos.verificar(
            plano,
            {"detalles": {"accion": "proteger", "paginas": 3}},
            PlanDeEjecucion(argv=(), ruta_de_salida=plano, env={"AEROCONVERT_CONTRASENA": "x"}),
        )
        assert not hecho.correcta
        assert "sin contraseña" in hecho.motivo

    def test_rc4_no_pasa_por_aes(self, plano, tmp_path):
        """RC4 lleva veinte años roto. PDFium dice la revisión; pypdf, que cifró, no opina."""
        from pypdf import PdfReader, PdfWriter

        escritor = PdfWriter()
        for pagina in PdfReader(str(plano)).pages:
            escritor.add_page(pagina)
        escritor.encrypt(self.CLAVE, algorithm="RC4-128")
        debil = tmp_path / "debil.parcial.pdf"
        with open(debil, "wb") as salida:
            escritor.write(salida)

        hecho = documentos.verificar(
            debil,
            {"detalles": {"accion": "proteger", "paginas": 3}},
            PlanDeEjecucion(
                argv=(), ruta_de_salida=debil, env={"AEROCONVERT_CONTRASENA": self.CLAVE}
            ),
        )
        assert not hecho.correcta
        assert "AES-256" in hecho.motivo

    def test_el_plan_no_la_ensena_en_su_repr(self, usuario, plano):
        """Un plan que acabara en un registro o en una traza la dejaría escrita."""
        from apps.documents import secretos

        job = self._trabajo(usuario, plano)
        secretos.guardar(job, self.CLAVE)
        plan = documentos.plan(job)
        assert plan.env[secretos.VARIABLE] == self.CLAVE
        assert self.CLAVE not in repr(plan)
        assert self.CLAVE not in " ".join(plan.argv)
        assert self.CLAVE not in documentos.ruta_del_encargo(job).read_text(encoding="utf-8")
        documentos.borrar_auxiliares(job)


class TestLaVerificacionDeLasPiezas:
    """Un zip íntegro con un PDF roto dentro sigue estando roto."""

    def _zip(self, ruta, piezas: dict[str, bytes]) -> Path:
        import zipfile

        with zipfile.ZipFile(ruta, "w") as paquete:
            for nombre, datos in piezas.items():
                paquete.writestr(nombre, datos)
        return ruta

    def test_un_pdf_roto_dentro_del_zip(self, plano, tmp_path):
        parcial = self._zip(
            tmp_path / "x.parcial.zip",
            {"plano_1.pdf": plano.read_bytes(), "plano_2.pdf": b"%PDF-1.7\nroto"},
        )
        hecho = documentos.verificar(parcial, {})
        assert not hecho.correcta
        assert "plano_2.pdf" in hecho.motivo

    def test_una_pieza_de_menos(self, plano, tmp_path):
        parcial = self._zip(tmp_path / "x.parcial.zip", {"plano_1.pdf": plano.read_bytes()})
        informe = {"detalles": {"piezas": [{"nombre": "plano_1.pdf"}, {"nombre": "plano_2.pdf"}]}}
        hecho = documentos.verificar(parcial, informe)
        assert not hecho.correcta
        assert "2 piezas" in hecho.motivo

    def test_una_pieza_con_otras_paginas(self, plano, tmp_path):
        parcial = self._zip(tmp_path / "x.parcial.zip", {"plano_1-2.pdf": plano.read_bytes()})
        informe = {"detalles": {"piezas": [{"nombre": "plano_1-2.pdf", "paginas": 2}]}}
        hecho = documentos.verificar(parcial, informe)
        assert not hecho.correcta
        assert "tiene 3" in hecho.motivo

    def test_algo_que_no_es_un_zip(self, tmp_path):
        parcial = tmp_path / "x.parcial.zip"
        parcial.write_bytes(b"PK no del todo")
        assert documentos.verificar(parcial, {}).codigo_motivo == "salida-invalida"

    def test_una_imagen_cortada(self, tmp_path):
        from PIL import Image

        entera = tmp_path / "entera.png"
        Image.new("RGB", (300, 200), (10, 20, 30)).save(entera)
        cortada = tmp_path / "x.parcial.png"
        cortada.write_bytes(entera.read_bytes()[:120])
        assert not documentos.verificar(cortada, {}).correcta
