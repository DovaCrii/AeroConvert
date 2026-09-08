from . import modo as modo_mod


def modo(request):
    """La chapa del modo, disponible en `base.html` y por tanto en todas las pantallas.

    Saber si los archivos salen o no de la maquina es lo primero que hay que ver, no algo
    que se averigua entrando a una pantalla de ajustes.
    """
    return {"chapa": modo_mod.chapa()}
