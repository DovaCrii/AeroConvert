"""Vistas de documentos: firma digital y verificación. Ver `apps/documents/views/__init__.py`.

**El certificado no se guarda.** El `.p12` llega en el POST, se abre aquí solo para decir de quién
es (y fallar con el formulario delante si la contraseña no lo abre o está vencido) y viaja a la cola
**junto con su contraseña como un solo secreto** (`secretos.py`): cifrado, de un solo uso, nunca en
`options` ni en la base. El campo de contraseña no vuelve nunca al formulario.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import firma_digital as firma_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario

EXTENSIONES_DE_CERTIFICADO = (".p12", ".pfx")


@login_required
def firmar_vista(request):
    """Firmar un PDF con el certificado de la persona."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Firmar con certificado",
        "proposito": "Un sello criptográfico con su certificado: si alguien cambia algo, se nota.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "motivo": "",
        "lugar": "",
    }
    if request.method != "POST":
        return render(request, "documents/firmar.html", contexto)

    contexto["motivo"] = (request.POST.get("motivo") or "").strip()[:120]
    contexto["lugar"] = (request.POST.get("lugar") or "").strip()[:120]
    clave = request.POST.get("clave") or ""
    try:
        origen = _origen_del_formulario(request)
        certificado = request.FILES.get("certificado")
        if certificado is None:
            raise ComposicionInvalida("Falta el certificado: un archivo .p12 o .pfx.")
        if Path(certificado.name).suffix.lower() not in EXTENSIONES_DE_CERTIFICADO:
            raise ComposicionInvalida("El certificado tiene que ser un archivo .p12 o .pfx.")
        if certificado.size > firma_mod.TAMANO_MAXIMO_P12:
            raise ComposicionInvalida("Ese archivo no parece un certificado: pesa demasiado.")
        if not clave:
            raise ComposicionInvalida("Escriba la contraseña del certificado.")
        p12 = certificado.read()
        # Se abre aquí, con el formulario delante: contraseña mala o certificado vencido se dicen
        # ahora y no en una ficha roja de la cola.
        firma_mod.leer_certificado(p12, clave)
        if Path(origen.nombre).suffix.lower() != ".pdf":
            raise ComposicionInvalida(f"{origen.nombre} no es un PDF.")
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/firmar.html", contexto)

    contexto["ruta_texto"] = origen.token
    secreto = json.dumps({"p12": base64.b64encode(p12).decode("ascii"), "clave": clave})
    try:
        return cola_mod.encolar(
            request,
            "firmar",
            [origen],
            # `pide_contrasena`: «Reintentar» vuelve aquí a pedir el certificado, en vez de
            # repetir un trabajo que ya no lo tiene.
            {"motivo": contexto["motivo"], "lugar": contexto["lugar"], "pide_contrasena": True},
            sufijo="_firmado.pdf",
            secreto=secreto,
        )
    finally:
        secreto = clave = ""  # noqa: F841 - que no sigan vivos en el marco


@login_required
def verificar_firmas_vista(request):
    """Qué firmas trae un PDF recibido y si siguen intactas."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Verificar firmas",
        "proposito": "Quién firmó un PDF, cuándo, y si cambió algo después.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }
    if request.method != "POST":
        return render(request, "documents/verificar_firmas.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        if Path(origen.nombre).suffix.lower() != ".pdf":
            raise ComposicionInvalida(f"{origen.nombre} no es un PDF.")
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/verificar_firmas.html", contexto)

    return cola_mod.encolar(request, "verificar_firmas", [origen], {}, sufijo="_firmas.md")
