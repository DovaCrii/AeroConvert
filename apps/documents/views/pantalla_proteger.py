"""Vistas de documentos: proteger. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.formats import pdf as lectura_pdf

from .. import cola as cola_mod
from .. import seguridad as seguridad_mod

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _origen_del_formulario


@login_required
def proteger_vista(request):
    """Poner o quitar la contraseña.

    **Aquí no hay paso de «mirar» con miniaturas**, a propósito: si el archivo ya está
    cifrado no se puede dibujar nada de él sin la clave, y una pantalla que a veces enseña
    las hojas y a veces no confunde más de lo que ayuda. Lo que sí se dice es en cuál de los
    dos casos está el archivo, que es lo que decide qué botón pulsar.

    La contraseña **no vuelve nunca al formulario**: el campo sale vacío en cada respuesta,
    también cuando hubo un error, para que no se quede escrita en una pantalla que alguien
    deja abierta. Ver el docstring de `seguridad.py`.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Proteger un PDF",
        "proposito": "Póngale contraseña antes de mandarlo, o quítesela para poder componerlo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "minimo": seguridad_mod.MINIMO,
        "algoritmo": seguridad_mod.ALGORITMO,
    }

    if request.method != "POST":
        return render(request, "documents/proteger.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)

    contexto["cifrado"] = cabecera.cifrado
    contexto["cabecera"] = cabecera

    accion = request.POST.get("accion")
    if accion not in ("proteger", "quitar"):
        return render(request, "documents/proteger.html", contexto)

    contrasena = request.POST.get("contrasena") or ""
    try:
        # **Todo lo que se puede decir aquí se dice aquí**, con el formulario delante: una
        # contraseña corta o que no abre el archivo, descubierta en la cola, manda a una
        # ficha roja y de vuelta a esta pantalla a escribirla otra vez.
        problema = _problema_de_proteger(accion, origen, cabecera, contrasena)
        if problema:
            messages.error(request, problema)
            return render(request, "documents/proteger.html", contexto)

        sufijo = "_protegido.pdf" if accion == "proteger" else "_sin_clave.pdf"
        return cola_mod.encolar(
            request,
            "proteger",
            [origen],
            # `pide_contrasena` es lo que hace que «Reintentar» vuelva aquí a pedirla, en vez
            # de repetir un trabajo que ya no tiene con qué abrir el archivo.
            {"accion": accion, "pide_contrasena": True},
            sufijo=sufijo,
            secreto=contrasena,
        )
    finally:
        # Que no quede viva en el marco más de lo necesario.
        contrasena = ""  # noqa: F841


def _problema_de_proteger(accion: str, origen, cabecera, contrasena: str) -> str:
    """Lo que impide proteger o quitar, en una frase. Vacío si se puede.

    Con `origen.nombre`: el que la persona reconoce, no el que quedó en el servidor.
    """
    if accion == "proteger":
        if cabecera.cifrado:
            return (
                f"{origen.nombre} ya está protegido. Quítele la contraseña primero si quiere "
                "cambiarla."
            )
        if len(contrasena) < seguridad_mod.MINIMO:
            return f"La contraseña tiene que tener al menos {seguridad_mod.MINIMO} caracteres."
        return ""
    if not cabecera.cifrado:
        return f"{origen.nombre} no pide contraseña: no hay nada que quitar."
    if not seguridad_mod.abre(origen.ruta, contrasena):
        return "Esa contraseña no abre el archivo."
    return ""
