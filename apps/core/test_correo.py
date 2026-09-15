"""Entrar con el correo.

Es lo que la gente recuerda sin pensar, y además deja **una forma de escribirle** a quien
tiene cuenta. Lo que sigue fija las decisiones que no son obvias:

- El nombre de usuario **sigue sirviendo**, porque la cuenta de administración que creó el
  servidor no tiene correo y quitarlo la dejaría fuera de su propia aplicación.
- Con dos cuentas compartiendo correo **no entra ninguna**: elegir «la primera» dejaría que
  quien registre un correo repetido decida a qué cuenta se entra.
- Y el alta lo exige, porque una cuenta sin correo es una cuenta con la que no se puede
  entrar: creada, guardada, y silenciosamente inútil.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .admin import AltaDeCuenta
from .autenticacion import PorCorreo

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user(  # nosec B106
        "ana", email="ana@jej.cl", password=CLAVE
    )


class TestEntrarConElCorreo:
    def test_se_entra_con_el_correo(self, client, ana):
        respuesta = client.post(reverse("login"), {"username": "ana@jej.cl", "password": CLAVE})
        assert respuesta.status_code == 302

    def test_sin_distinguir_mayusculas(self, client, ana):
        """Nadie teclea su correo con las mismas mayúsculas dos veces."""
        respuesta = client.post(reverse("login"), {"username": "Ana@JEJ.CL", "password": CLAVE})
        assert respuesta.status_code == 302

    def test_y_el_nombre_de_usuario_sigue_sirviendo(self, client, ana):
        """La cuenta que creó el servidor no tiene correo. Quitarle esta vía la dejaría
        fuera de su propia aplicación."""
        respuesta = client.post(reverse("login"), {"username": "ana", "password": CLAVE})
        assert respuesta.status_code == 302

    def test_la_contrasena_sigue_importando(self, client, ana):
        respuesta = client.post(reverse("login"), {"username": "ana@jej.cl", "password": "otra"})
        assert respuesta.status_code == 200

    def test_un_correo_que_no_existe_no_entra(self, client, db):
        respuesta = client.post(reverse("login"), {"username": "nadie@jej.cl", "password": CLAVE})
        assert respuesta.status_code == 200


class TestElCorreoRepetido:
    def test_con_dos_cuentas_iguales_no_entra_ninguna(self, db):
        """`auth.User` no declara el correo único, así que esto puede pasar. Elegir una sería
        dejar que quien registre el repetido decida a qué cuenta se entra.

        Se apunta al backend y no a `authenticate()`: el de la cadena es axes, que exige una
        petición y aquí no la hay. Además lo que se mide es esta decisión, no el recorrido.
        """
        Usuario = get_user_model()
        Usuario.objects.create_user("ana", email="dos@jej.cl", password=CLAVE)  # nosec B106
        Usuario.objects.create_user("beto", email="dos@jej.cl", password=CLAVE)  # nosec B106

        assert PorCorreo().authenticate(None, username="dos@jej.cl", password=CLAVE) is None

    def test_pero_con_una_sola_si(self, db):
        """El control de la anterior: que devuelva `None` por el motivo correcto y no porque
        el backend no funcione."""
        Usuario = get_user_model()
        sola = Usuario.objects.create_user(  # nosec B106
            "sola", email="una@jej.cl", password=CLAVE
        )
        assert PorCorreo().authenticate(None, username="una@jej.cl", password=CLAVE) == sola

    def test_y_el_alta_lo_impide_antes(self, ana):
        formulario = AltaDeCuenta(data={"correo": "ana@jej.cl"})
        assert not formulario.is_valid()
        assert "Ya hay una cuenta con ese correo." in formulario.errors["correo"]

    def test_tampoco_cambiando_las_mayusculas(self, ana):
        formulario = AltaDeCuenta(data={"correo": "ANA@jej.cl"})
        assert not formulario.is_valid()


class TestElAltaExigeCorreo:
    def test_sin_correo_no_se_crea(self, db):
        assert not AltaDeCuenta(data={}).is_valid()

    def test_con_correo_nuevo_si(self, db):
        assert AltaDeCuenta(data={"correo": "nueva@jej.cl"}).is_valid()


class TestLaPantalla:
    def test_pide_el_correo_y_no_el_usuario(self, client):
        cuerpo = client.get(reverse("login")).content.decode()
        assert "Correo" in cuerpo
        assert 'autocomplete="email"' in cuerpo

    def test_pero_el_campo_sigue_llamandose_username(self, client):
        """django-axes cuenta los intentos fallidos por lo que venga en ese campo.
        Renombrarlo dejaría el bloqueo por tanteo contando otra cosa, o nada."""
        assert 'name="username"' in client.get(reverse("login")).content.decode()
