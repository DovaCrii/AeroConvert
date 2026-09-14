"""Un preajuste es de quien lo hizo.

## Por qué esto no se veía

En una estación de trabajo de una persona, «los que no son de fábrica» y «los míos» son el
mismo conjunto, así que la consulta sin dueño funcionaba y el comentario que decía «solo los
propios» parecía cierto. En el servidor compartido dejan de coincidir, y aparecen tres cosas
distintas:

1. La lista enseñaba los preajustes de todos. **Un preajuste lleva el nombre del cliente y
   del contrato** —«Entrega cliente BHP»— así que la lista de otro dice con quién está
   trabajando.
2. El desplegable de la pantalla de convertir, igual.
3. Y el borrado aceptaba cualquier `slug`: bastaba conocerlo para destruir el trabajo de
   otro, de un clic y sin dejar rastro. Ese es el grave, porque no se deshace.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import ConversionPreset, sembrar

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def de_fabrica(db):
    """Los que trae la aplicación. No están en la base de pruebas hasta sembrarlos."""
    sembrar()
    return ConversionPreset.objects.filter(de_fabrica=True).first()


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto", password=CLAVE)  # nosec B106


#: El nombre es raro **a propósito**: «Entrega cliente BHP» es el ejemplo que la propia
#: pantalla imprime en su texto de ayuda, así que como centinela daba un falso positivo.
NOMBRE_SOLO_DE_ANA = "Faena Escondida turno noche"


def _preajuste(dueno, slug="entrega-cliente", nombre=NOMBRE_SOLO_DE_ANA):
    return ConversionPreset.objects.create(
        slug=slug,
        nombre=nombre,
        target_format_code="geotiff",
        owner=dueno,
        de_fabrica=False,
    )


class TestLaLista:
    def test_sale_el_propio(self, client, ana):
        _preajuste(ana)
        client.force_login(ana)
        respuesta = client.get(reverse("presets:lista"))
        assert NOMBRE_SOLO_DE_ANA in respuesta.content.decode()

    def test_y_no_el_de_otro(self, client, ana, beto):
        """El nombre de un preajuste dice con qué cliente está trabajando alguien."""
        _preajuste(ana)
        client.force_login(beto)
        respuesta = client.get(reverse("presets:lista"))
        assert NOMBRE_SOLO_DE_ANA not in respuesta.content.decode()

    def test_los_de_fabrica_los_ve_todo_el_mundo(self, client, beto, de_fabrica):
        """No son de nadie: son el punto de partida de los demás."""
        client.force_login(beto)
        respuesta = client.get(reverse("presets:lista"))
        assert de_fabrica.nombre in respuesta.content.decode()


class TestElBorrado:
    """El defecto que no era de información, sino de destrucción."""

    def test_el_propio_se_borra(self, client, ana):
        preajuste = _preajuste(ana)
        client.force_login(ana)
        client.post(reverse("presets:borrar", args=[preajuste.slug]))
        assert not ConversionPreset.objects.filter(pk=preajuste.pk).exists()

    def test_el_de_otro_no(self, client, ana, beto):
        preajuste = _preajuste(ana)
        client.force_login(beto)
        respuesta = client.post(reverse("presets:borrar", args=[preajuste.slug]))
        assert respuesta.status_code == 404
        assert ConversionPreset.objects.filter(pk=preajuste.pk).exists()

    def test_y_el_de_fabrica_sigue_explicando_por_que(self, client, ana, de_fabrica):
        """404 aquí sería correcto y además inútil: quien lo intenta necesita saber que la
        salida es copiarlo."""
        client.force_login(ana)
        respuesta = client.post(reverse("presets:borrar", args=[de_fabrica.slug]), follow=True)
        assert respuesta.status_code == 200
        assert ConversionPreset.objects.filter(pk=de_fabrica.pk).exists()
        assert "cópialos" in respuesta.content.decode()


class TestLaCopia:
    def test_uno_de_fabrica_se_copia(self, client, ana, de_fabrica):
        client.force_login(ana)
        client.post(reverse("presets:copiar", args=[de_fabrica.slug]))
        copia = ConversionPreset.objects.get(de_fabrica=False)
        assert copia.owner == ana

    def test_el_de_otro_no_se_puede_copiar(self, client, ana, beto):
        """Si no se puede ver, tampoco duplicar: la copia llevaría dentro el destino y las
        opciones que otro configuró."""
        preajuste = _preajuste(ana)
        client.force_login(beto)
        respuesta = client.post(reverse("presets:copiar", args=[preajuste.slug]))
        assert respuesta.status_code == 404


class TestElDesplegableDeConvertir:
    def test_no_ofrece_el_de_otro(self, client, ana, beto):
        _preajuste(ana)
        client.force_login(beto)
        respuesta = client.get(reverse("dashboard:convertir"))
        assert NOMBRE_SOLO_DE_ANA not in respuesta.content.decode()
