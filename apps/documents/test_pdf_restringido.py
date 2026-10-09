"""Un PDF restringido (contraseña de apertura vacía) no «pide contraseña».

En p340 (2026-10-09) un certificado que abre en cualquier visor salió en «Organizar páginas» con
«pide contraseña». Iba cifrado solo para restringir permisos, con la contraseña de apertura vacía,
y `is_encrypted` no distingue ese caso del de una contraseña de verdad.

**El oráculo es PDFium**, otro lector que no es pypdf: si abre el archivo sin contraseña, un visor
también, y la aplicación no puede decir lo contrario.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2
import pytest
from pypdf import PdfReader, PdfWriter

from apps.documents import composicion, marcas, tamano
from apps.formats import pdf as lectura

CLAVE_DEL_DUENO = "solo-permisos-1234"  # nosec B105 - clave de prueba
CLAVE_DE_APERTURA = "de-verdad-5678"  # nosec B105 - clave de prueba


def _pdf(destino: Path, *, apertura: str | None) -> Path:
    escritor = PdfWriter()
    for _ in range(3):
        escritor.add_blank_page(width=595, height=842)
    if apertura is not None:
        escritor.encrypt(
            user_password=apertura, owner_password=CLAVE_DEL_DUENO, algorithm="AES-256"
        )
    with destino.open("wb") as f:
        escritor.write(f)
    return destino


@pytest.fixture
def restringido(tmp_path):
    return _pdf(tmp_path / "certificado.pdf", apertura="")


@pytest.fixture
def con_clave(tmp_path):
    return _pdf(tmp_path / "cerrado.pdf", apertura=CLAVE_DE_APERTURA)


def _huella(ruta: Path):
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def test_el_oraculo_abre_el_restringido_y_no_el_cerrado(restringido, con_clave):
    """Lo que se le pide a la aplicación es lo que hace un visor: PDFium."""
    assert len(pypdfium2.PdfDocument(str(restringido))) == 3
    with pytest.raises(pypdfium2.PdfiumError):
        pypdfium2.PdfDocument(str(con_clave))
    # Y los dos están cifrados para pypdf: el caso que confundía.
    assert PdfReader(str(restringido)).is_encrypted
    assert PdfReader(str(con_clave)).is_encrypted


def test_la_cabecera_solo_marca_el_que_pide_clave(restringido, con_clave):
    cabecera = lectura.leer_cabecera(restringido)
    assert not cabecera.cifrado
    assert cabecera.cuantas == 3
    assert lectura.leer_cabecera(con_clave).cifrado


def test_organizar_compone_el_restringido_y_no_lo_toca(restringido, tmp_path):
    antes = _huella(restringido)
    destino = tmp_path / "organizado.pdf"
    receta = [
        composicion.PaginaElegida(archivo=restringido, numero=n, giro=g)
        for n, g in ((3, 0), (1, 90))
    ]
    composicion.componer(receta, destino)
    # El oráculo lee la salida: dos páginas y la segunda apaisada por el giro.
    salida = pypdfium2.PdfDocument(str(destino))
    assert len(salida) == 2
    assert salida[1].get_rotation() == 90
    assert _huella(restringido) == antes


@pytest.mark.parametrize(
    "hacer",
    [
        lambda o, d: marcas.marca_de_agua(o, d, "BORRADOR"),
        lambda o, d: tamano.cambiar_tamano(o, d, "a4"),
    ],
    ids=["marca", "tamano"],
)
def test_otras_herramientas_tambien_lo_abren(restringido, tmp_path, hacer):
    destino = tmp_path / "salida.pdf"
    hacer(restringido, destino)
    assert len(pypdfium2.PdfDocument(str(destino))) == 3


def test_la_pantalla_de_organizar_lo_acepta_y_deja_ver_cada_pagina_en_grande(
    client, django_user_model, restringido
):
    """El caso de p340 de extremo a extremo, y lo que se pidió después: poder leer cada hoja."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse

    client.force_login(django_user_model.objects.create_user("organiza"))
    subida = SimpleUploadedFile("certificado.pdf", restringido.read_bytes(), "application/pdf")
    cuerpo = client.post(reverse("documents:componer_organizar"), {"archivos": subida}).content
    cuerpo = cuerpo.decode()
    assert "pide contraseña" not in cuerpo
    assert cuerpo.count("data-ampliar=") == 3
    assert cuerpo.count("&amp;ancho=1400") == 3
    assert "Ver en grande" in cuerpo


def test_el_que_si_pide_clave_se_sigue_parando(con_clave, tmp_path):
    from apps.documents.composicion import ComposicionInvalida

    with pytest.raises(ComposicionInvalida, match="contraseña"):
        marcas.marca_de_agua(con_clave, tmp_path / "x.pdf", "BORRADOR")
