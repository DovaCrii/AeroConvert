"""El enlace a la administración, que es por donde se da de alta al equipo.

No estaba en ninguna parte. La pantalla existía —Django la trae— pero para llegar había que
saberse `/admin/` de memoria, y quien administra esta instalación no es quien la programó.
Una pantalla que existe y no se encuentra es, a efectos prácticos, una pantalla que no existe.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def ana(db):
    """Alguien del equipo: usa la aplicación entera, pero no administra."""
    return get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106


@pytest.fixture
def jefa(db):
    return get_user_model().objects.create_superuser(  # nosec B106
        "jefa", email="jefa@ejemplo.test", password=CLAVE
    )


class TestElEnlaceDeCuentas:
    def test_lo_ve_quien_administra(self, client, jefa):
        client.force_login(jefa)
        respuesta = client.get(reverse("dashboard:convertir"))
        assert "Cuentas" in respuesta.content.decode()

    def test_y_no_lo_ve_el_resto(self, client, ana):
        """Enseñarlo a todo el mundo sería un enlace que lleva a un 403."""
        client.force_login(ana)
        assert "Cuentas" not in client.get(reverse("dashboard:convertir")).content.decode()

    def test_la_condicion_es_la_misma_que_deja_entrar(self, client, ana):
        """`is_staff` y no `is_superuser`: es justo lo que exige `/admin/`, así que el
        enlace no puede aparecer para quien luego se encontraría la puerta cerrada."""
        ana.is_staff = True
        ana.save(update_fields=["is_staff"])
        client.force_login(ana)
        assert "Cuentas" in client.get(reverse("dashboard:convertir")).content.decode()
