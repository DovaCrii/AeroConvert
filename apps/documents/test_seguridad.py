"""Poner y quitar la contraseña de un PDF.

El oráculo es **pypdf volviendo a abrir el archivo escrito**, no lo que dijo la función: que
`is_encrypted` sea cierto, que la clave correcta abra y que una distinta no. Un «se cifró»
devuelto por quien cifra no prueba nada.
"""

from pathlib import Path

import pytest

from apps.documents import seguridad
from apps.documents.composicion import ComposicionInvalida
from apps.formats import pdf as lector

CLAVE = "obra-2026-bhp"


def _pdf(carpeta: Path, nombre: str, cuantas: int = 2) -> Path:
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _leer(ruta: Path, clave: str | None = None):
    from pypdf import PdfReader

    lectura = PdfReader(str(ruta))
    if clave is not None:
        lectura.decrypt(clave)
    return lectura


class TestProteger:
    def test_el_archivo_escrito_pide_contrasena(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        destino = tmp_path / "cerrado.pdf"

        assert seguridad.proteger(informe, destino, CLAVE) == 2
        assert _leer(destino).is_encrypted

    def test_y_se_abre_con_la_clave(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 3)
        destino = tmp_path / "cerrado.pdf"
        seguridad.proteger(informe, destino, CLAVE)

        abierto = _leer(destino, CLAVE)
        assert len(abierto.pages) == 3

    def test_y_no_con_otra(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        destino = tmp_path / "cerrado.pdf"
        seguridad.proteger(informe, destino, CLAVE)

        assert not _leer(destino).decrypt("otra-cosa")

    def test_el_original_se_queda_como_estaba(self, tmp_path):
        """Cifrar *en el sitio* dejaría sin archivo a quien se equivoque al teclear."""
        informe = _pdf(tmp_path, "informe.pdf")
        antes = informe.read_bytes()
        seguridad.proteger(informe, tmp_path / "cerrado.pdf", CLAVE)
        assert informe.read_bytes() == antes

    def test_una_contrasena_corta_no_se_acepta(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        destino = tmp_path / "cerrado.pdf"
        with pytest.raises(ComposicionInvalida, match=f"al menos {seguridad.MINIMO}"):
            seguridad.proteger(informe, destino, "1234")
        assert not destino.exists()

    def test_ni_una_vacia(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        with pytest.raises(ComposicionInvalida):
            seguridad.proteger(informe, tmp_path / "cerrado.pdf", "")

    def test_uno_que_ya_esta_protegido_no_se_vuelve_a_cifrar(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        cerrado = tmp_path / "cerrado.pdf"
        seguridad.proteger(informe, cerrado, CLAVE)

        with pytest.raises(ComposicionInvalida, match="ya está protegido"):
            seguridad.proteger(cerrado, tmp_path / "otra_vez.pdf", CLAVE)

    def test_algo_que_no_es_un_pdf(self, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida, match="No se pudo leer"):
            seguridad.proteger(falso, tmp_path / "y.pdf", CLAVE)


class TestQuitarLaContrasena:
    def test_devuelve_uno_que_se_abre_sin_nada(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf", 4)
        cerrado = tmp_path / "cerrado.pdf"
        abierto = tmp_path / "abierto.pdf"
        seguridad.proteger(informe, cerrado, CLAVE)

        assert seguridad.quitar_contrasena(cerrado, abierto, CLAVE) == 4
        assert not _leer(abierto).is_encrypted
        assert lector.leer_cabecera(abierto).cuantas == 4

    def test_con_la_clave_equivocada_se_para_y_lo_dice(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        cerrado = tmp_path / "cerrado.pdf"
        seguridad.proteger(informe, cerrado, CLAVE)

        with pytest.raises(ComposicionInvalida, match="no abre el archivo"):
            seguridad.quitar_contrasena(cerrado, tmp_path / "abierto.pdf", "la-que-no-es")

    def test_uno_que_no_pide_nada(self, tmp_path):
        informe = _pdf(tmp_path, "informe.pdf")
        with pytest.raises(ComposicionInvalida, match="no pide contraseña"):
            seguridad.quitar_contrasena(informe, tmp_path / "abierto.pdf", CLAVE)

    def test_algo_que_no_es_un_pdf(self, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida, match="No se pudo leer"):
            seguridad.quitar_contrasena(falso, tmp_path / "y.pdf", CLAVE)


class TestElAlgoritmo:
    def test_es_aes_256_y_no_hay_donde_elegir_otro(self):
        """RC4 de 40 y de 128 bits están rotos desde hace veinte años. Un desplegable con
        tres opciones de las que dos no protegen es peor que no tener desplegable."""
        assert seguridad.ALGORITMO == "AES-256"

    def test_y_la_biblioteca_de_verdad_lo_hace(self, tmp_path):
        """pypdf sin `cryptography` levanta `DependencyError` en vez de cifrar con AES.
        Este test es el que se rompería si la dependencia desapareciera del bloqueo."""
        informe = _pdf(tmp_path, "informe.pdf")
        cerrado = tmp_path / "cerrado.pdf"
        seguridad.proteger(informe, cerrado, CLAVE)

        lectura = _leer(cerrado)
        assert lectura.is_encrypted
        assert lectura.decrypt(CLAVE)
