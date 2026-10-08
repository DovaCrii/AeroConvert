from dataclasses import asdict

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import registry


class ConTokenHacePermiso(BasePermission):
    """Con sesión basta haber entrado; **con token**, además el permiso `jobs.usar_api`, como el
    resto de la API. Sin esto, un token de una cuenta sin el permiso leía las capacidades."""

    message = "Su cuenta no tiene el permiso para usar la API (jobs.usar_api)."

    def has_permission(self, request, view):
        from apps.core.models import TokenDeApi

        if isinstance(request.auth, TokenDeApi):
            return request.user.has_perm("jobs.usar_api")
        return True


class Capacidades(APIView):
    """Que sabe hacer esta instalacion, en JSON.

    Solo lectura y solo para quien ha entrado. No hay serializer con `fields = "__all__"`:
    la forma la fija `CeldaDeCapacidad`, que es un dataclass y no un modelo, asi que no
    puede filtrarse un campo por descuido.
    """

    permission_classes = [IsAuthenticated, ConTokenHacePermiso]

    def get(self, request):
        celdas = registry.matriz_de_capacidades().values()
        return Response({"capacidades": [asdict(c) for c in celdas]})
