"""Registrar lo que sale mal, y resumir el uso para saber si algo mejoró (F9.6).

Dos cosas separadas que van juntas porque la segunda no tiene sentido sin la primera:

- `registrar()` anota un incidente **sin guardar nada personal** (ver `Incidente`).
- `resumen_de_uso()` cuenta, con lo que ya hay en la base, qué se usa, qué sale bien y qué se
  rompe, para poder comparar un periodo con otro después de un cambio.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import Incidente

#: Cuántos se aceptan por hora, en total. Un fallo que se repite en bucle desde un navegador
#: (o alguien que lo provoque a propósito) no puede llenar la base: pasado esto se descartan.
TOPE_POR_HORA = 500


def _limpiar_ruta(ruta: str) -> str:
    """La ruta sin consulta ni fragmento: `?q=` puede llevar lo que escribió una persona."""
    return (ruta or "").split("?", 1)[0].split("#", 1)[0][:200]


def registrar(tipo: str, ruta: str, *, estado=None, detalle: str = "", usuario=None):
    """Anota un incidente. Devuelve la fila, o `None` si se pasó del tope por hora.

    Nunca levanta una excepción hacia quien llama: registrar un fallo no puede crear otro.
    """
    try:
        hace_una_hora = timezone.now() - timedelta(hours=1)
        if Incidente.objects.filter(created_at__gte=hace_una_hora).count() >= TOPE_POR_HORA:
            return None
        return Incidente.objects.create(
            tipo=tipo,
            ruta=_limpiar_ruta(ruta),
            estado=estado if isinstance(estado, int) and 0 <= estado <= 599 else None,
            detalle=(detalle or "")[:300],
            owner=usuario if getattr(usuario, "is_authenticated", False) else None,
        )
    except Exception:  # noqa: BLE001 - ver el docstring: esto no puede tumbar nada
        return None


def resumen_de_uso(dias: int = 30) -> dict:
    """Lo que se usó y cómo salió en los últimos `dias`, con cifras y no con impresiones.

    Comparar dos resúmenes —antes y después de un cambio— es la forma de saber si mejoró algo:
    la tasa de éxito, los motivos de fallo más repetidos y los incidentes del navegador.
    """
    from apps.jobs.models import ConversionJob

    desde = timezone.now() - timedelta(days=dias)
    trabajos = ConversionJob.objects.filter(created_at__gte=desde)

    por_estado = {
        fila["status"]: fila["n"] for fila in trabajos.values("status").annotate(n=Count("id"))
    }
    hechos = por_estado.get("done", 0)
    fallidos = por_estado.get("error", 0)
    terminados = hechos + fallidos

    def top(campo: str, filtro=None, cuantos: int = 8) -> list[tuple[str, int]]:
        consulta = trabajos.filter(**filtro) if filtro else trabajos
        filas = (
            consulta.exclude(**{campo: ""})
            .values(campo)
            .annotate(n=Count("id"))
            .order_by("-n")[:cuantos]
        )
        return [(fila[campo], fila["n"]) for fila in filas]

    incidentes = Incidente.objects.filter(created_at__gte=desde)
    return {
        "dias": dias,
        "trabajos": trabajos.count(),
        "por_estado": por_estado,
        "tasa_de_exito": round(100.0 * hechos / terminados, 1) if terminados else None,
        "personas_activas": trabajos.values("owner").distinct().count(),
        "destinos_mas_pedidos": top("target_format_code"),
        "origenes_mas_vistos": top("source_format_code"),
        "motivos_de_fallo": top("reason_code", {"status": "error"}),
        "incidentes": incidentes.count(),
        "incidentes_por_tipo": {
            fila["tipo"]: fila["n"] for fila in incidentes.values("tipo").annotate(n=Count("id"))
        },
        "rutas_con_mas_incidentes": [
            (fila["ruta"], fila["n"])
            for fila in incidentes.values("ruta").annotate(n=Count("id")).order_by("-n")[:5]
        ],
    }


def en_texto(resumen: dict) -> str:
    """El resumen como texto para la terminal o para pegarlo en un acta."""
    lineas = [f"Uso de los últimos {resumen['dias']} días", ""]
    lineas.append(
        f"Trabajos: {resumen['trabajos']} · personas activas: {resumen['personas_activas']}"
    )
    if resumen["tasa_de_exito"] is None:
        lineas.append("Tasa de éxito: sin trabajos terminados todavía")
    else:
        lineas.append(f"Tasa de éxito: {resumen['tasa_de_exito']} % de los terminados")
    for estado, n in sorted(resumen["por_estado"].items()):
        lineas.append(f"  · {estado}: {n}")

    for titulo, clave in (
        ("Destinos más pedidos", "destinos_mas_pedidos"),
        ("Orígenes más vistos", "origenes_mas_vistos"),
        ("Motivos de fallo", "motivos_de_fallo"),
        ("Rutas con más incidentes", "rutas_con_mas_incidentes"),
    ):
        if resumen[clave]:
            lineas += ["", titulo + ":"]
            lineas += [f"  {n:>5}  {nombre}" for nombre, n in resumen[clave]]

    lineas += ["", f"Incidentes: {resumen['incidentes']}"]
    for tipo, n in sorted(resumen["incidentes_por_tipo"].items()):
        lineas.append(f"  · {tipo}: {n}")
    return "\n".join(lineas) + "\n"
