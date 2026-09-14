from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import registry
from .base import CeldaVacia


@dataclass(frozen=True)
class Fila:
    origen: str
    celdas: tuple


@login_required
def matriz(request):
    """La rejilla origen × destino.

    Se pinta **entera**, con huecos incluidos, y no solo las conversiones que hoy funcionan.
    Una capacidad ausente tiene que verse distinta de una inexistente: la primera se arregla
    instalando algo, la segunda no se arregla.
    """
    celdas = registry.matriz_de_capacidades()

    origenes = sorted({o for o, _ in celdas})
    destinos = sorted({d for _, d in celdas})

    filas = tuple(
        Fila(
            origen=origen,
            celdas=tuple(
                celdas.get((origen, destino)) or CeldaVacia(origen, destino) for destino in destinos
            ),
        )
        for origen in origenes
    )

    motores = tuple(
        {"id": m.id, "nombre": m.nombre, "estado": m.disponibilidad(), "pares": len(m.pares())}
        for m in registry.todos()
    )

    # **Separadas, y las apagadas primero en su propio bloque.** Mezcladas en una tabla, las
    # dos o tres que necesitan algo se perdian entre las siete que funcionan, y son justo las
    # unicas sobre las que hay algo que hacer. Se parte aqui y no en la plantilla con un `if`
    # dentro del bucle: dos recorridos de la misma lista dejan el orden a merced de quien
    # edite el HTML.
    listas = tuple(m for m in motores if m["estado"].disponible)
    apagadas = tuple(m for m in motores if not m["estado"].disponible)

    conversiones_posibles = sum(1 for c in celdas.values() if c.estado == "disponible")

    # Lo que falta, agrupado por motivo. Repetir el mismo mensaje en cuarenta celdas no
    # ayuda a nadie; verlo una vez con su cuenta, sí.
    por_motivo: dict[str, dict] = {}
    for celda in celdas.values():
        if celda.estado == "disponible" or not celda.codigo_motivo:
            continue
        entrada = por_motivo.setdefault(
            celda.codigo_motivo,
            {"codigo": celda.codigo_motivo, "mensaje": celda.mensaje, "cuantas": 0},
        )
        entrada["cuantas"] += 1

    return render(
        request,
        "engines/matriz.html",
        {
            "filas": filas,
            "destinos": destinos,
            "motores": motores,
            "listas": listas,
            "apagadas": apagadas,
            "conversiones_posibles": conversiones_posibles,
            "conversiones_totales": len(celdas),
            "motivos": sorted(por_motivo.values(), key=lambda m: -m["cuantas"]),
            "seccion": "compatibilidad",
            "etiqueta_seccion": "Compatibilidad",
            "titulo_pagina": "Qué se puede convertir en este equipo",
            "proposito": (
                "Es la pantalla que hay que mirar antes de escribir a soporte. Nada se "
                "oculta: lo que falta aparece apagado y dice qué falta y qué sirve en su "
                "lugar."
            ),
        },
    )
