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

    return {"menu_grupos": acciones_mod.por_categoria()}
