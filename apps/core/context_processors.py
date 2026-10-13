from django.conf import settings

from . import modo as modo_mod


def modo(request):
    """La chapa del modo, disponible en `base.html` y por tanto en todas las pantallas.

    Saber si los archivos salen o no de la maquina es lo primero que hay que ver, no algo
    que se averigua entrando a una pantalla de ajustes.

    Y el **tope de subida**, que hasta ahora solo existia en el servidor: quien elegia un
    archivo de 600 MB con el tope en 200 subia doscientos megabytes para que al final le
    dijeran que no -- y encima se lo decian mal. Con el numero en la pantalla, el navegador
    lo para antes de mandar un solo byte.
    """
    return {"chapa": modo_mod.chapa(), "tope_mb": settings.TOPE_MB}


def tino(request):
    """Si Tino se enseña. Apagado, las plantillas no pintan ni un enlace hacia él.

    Va en un procesador y no en cada vista porque los enlaces están en el pie del menú, que
    sale en todas las pantallas, y en el «nada coincide» del buscador.
    """
    return {"tino_visible": bool(getattr(settings, "TINO_VISIBLE", False))}


def menu(request):
    """Lo que se puede hacer, para el desplegable de la barra.

    **Solo para quien ha entrado.** A quien esta en la pantalla de acceso no se le ensena el
    inventario de la casa, y ademas construirlo ahi seria trabajo tirado en cada 302.

    El import va dentro y no arriba a proposito: `acciones` acaba llegando a las vistas de
    documentos, y un procesador de contexto se carga al arrancar Django. Arriba seria una
    dependencia circular con forma de error de importacion.

    No cuesta una consulta: la unica parte cara es la sonda de Office, y `sondar()` la
    cachea diez minutos (`apps/documents/office.py`).
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from apps.dashboard import acciones as acciones_mod

    # El lateral solo enseña las que se pueden hacer, así que **cuenta solo esas**: con una
    # apagada, «Imagen, video y planta» decía 2 y enseñaba 1 (p340, 2026-10-09). Un grupo sin
    # ninguna disponible no se pinta. Las apagadas siguen, con su motivo, en la portada.
    grupos = []
    for grupo in acciones_mod.por_categoria():
        disponibles = [a for a in grupo["acciones"] if a.disponible]
        if disponibles:
            grupos.append({**grupo, "acciones": disponibles})
    return {"menu_grupos": grupos, "menu_modulos": _modulos(grupos)}


def _modulos(grupos: list[dict]) -> list[dict]:
    """Los módulos de producto (F21.1) con sus grupos disponibles, en el orden del flujo.

    Un módulo que aún no existe sale **apagado con su motivo y su alternativa**, no se omite
    (regla 4). Uno que existe pero no tiene herramientas que se puedan hacer aquí no se pinta,
    como pasa con los grupos.
    """
    from django.urls import reverse

    from apps.dashboard import taxonomia
    from apps.jobs.motivos import MOTIVOS

    por_id = {g["clave"]: g for g in grupos}
    salida = []
    for modulo in taxonomia.MODULOS:
        propios = [por_id[i] for i in modulo.grupos if i in por_id]
        motivo = MOTIVOS.get(modulo.motivo) if modulo.motivo else None
        if modulo.grupos and not propios:
            continue
        salida.append(
            {
                "id": modulo.id,
                "titulo": modulo.titulo,
                "cuando": modulo.cuando,
                "icono": modulo.icono,
                "aparte": modulo.aparte,
                "grupos": propios,
                "enlace": reverse(modulo.enlace) if modulo.enlace else "",
                "motivo": motivo,
                "cuenta": sum(len(g["acciones"]) for g in propios),
            }
        )
    return salida
