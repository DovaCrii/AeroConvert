from dataclasses import asdict

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import registry


class Capacidades(APIView):
    """Que sabe hacer esta instalacion, en JSON.

    Solo lectura y solo para quien ha entrado. No hay serializer con `fields = "__all__"`:
    la forma la fija `CeldaDeCapacidad`, que es un dataclass y no un modelo, asi que no
    puede filtrarse un campo por descuido.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        celdas = registry.matriz_de_capacidades().values()
        return Response({"capacidades": [asdict(c) for c in celdas]})
