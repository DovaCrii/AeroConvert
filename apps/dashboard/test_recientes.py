"""«Seguir donde lo dejaste», que es historial y no favoritos.

Los dos son «guarda lo que usas para tenerlo a mano» y cuestan lo mismo de escribir. La
diferencia decide cuál sirve: **uno se llena solo y el otro nace vacío**. Lo que se vigila
aquí es lo que hace que el historial sea útil y no un log más — que agrupe, que no adivine, y
que se quite de en medio cuando alguien ya ha dicho qué quiere.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.dashboard import recientes
from apps.jobs.models import CANCELADO, ERROR, HECHO, ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def topografo():
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


#: Un contador para separar en el tiempo los trabajos que crea una prueba.
#:
#: **Hace falta y no es cosmética.** `created_at` es `auto_now_add`, y el reloj de Windows
#: tiene unos 15 ms de resolución: dos `create()` seguidos caen en el mismo instante, el
#: orden por fecha empata y la prueba pasa o falla según el orden de inserción. El
#: identificador es un UUID, así que no hay desempate cronológico al que recurrir.
_segundos = iter(range(1, 10_000))


def _trabajo(usuario, *, nombre="vuelo.tif", perfil="qgis", formato="gpkg", estado=HECHO):
    trabajo = ConversionJob.objects.create(
        owner=usuario,
        source_name=nombre,
        source_path=f"D:/obras/{nombre}",
        target_format_code=formato,
        target_profile_id=perfil,
        status=estado,
    )
    trabajo.created_at = timezone.now() + timedelta(seconds=next(_segundos))
    trabajo.save()
    return trabajo


class TestLoQueSeOfreceRepetir:
    def test_sin_historial_no_hay_nada_que_enseniar(self, topografo):
        """**Y por eso no es un panel de favoritos.** Uno vacío ocuparía sitio en la portada
        sin dar nada; éste sencillamente no está hasta que hay algo que recordar."""
        assert recientes.repetibles(topografo) == []

    def test_lo_ultimo_sale_primero(self, topografo):
        _trabajo(topografo, nombre="antiguo.tif", perfil="civil3d")
        _trabajo(topografo, nombre="nuevo.tif", perfil="qgis")
        titulos = [r.titulo for r in recientes.repetibles(topografo)]
        assert titulos == ["A QGIS", "A Civil 3D / AutoCAD"]

    def test_el_enlace_llega_con_el_destino_ya_elegido(self, topografo):
        """Es lo que lo separa de un historial: no lleva a mirar lo que hiciste, lleva a
        **volver a hacerlo** sin tener que reencontrar el destino en el catálogo."""
        _trabajo(topografo, perfil="qgis")
        assert recientes.repetibles(topografo)[0].enlace == (
            f"{reverse('dashboard:convertir')}?destino=qgis"
        )


class TestQueAgrupePorDestino:
    """**Lo que lo hace útil en vez de un log.** Cinco ortofotos a QGIS son una fila."""

    def test_cinco_conversiones_al_mismo_sitio_son_una_fila(self, topografo):
        for i in range(5):
            _trabajo(topografo, nombre=f"vuelo_{i}.tif", perfil="qgis")
        filas = recientes.repetibles(topografo)
        assert len(filas) == 1
        assert filas[0].veces == 5

    def test_y_enseña_el_ultimo_archivo_para_reconocerla(self, topografo):
        _trabajo(topografo, nombre="primero.tif", perfil="qgis")
        _trabajo(topografo, nombre="ultimo.tif", perfil="qgis")
        assert recientes.repetibles(topografo)[0].ultimo_archivo == "ultimo.tif"

    def test_no_crece_sin_freno(self, topografo):
        """Va encima del catálogo: lo que empuja al catálogo fuera de la pantalla deja de ser
        una ayuda para ser un estorbo."""
        for perfil in ("qgis", "civil3d", "arcgis", "google-earth", "web", "aerobim"):
            _trabajo(topografo, perfil=perfil)
        assert len(recientes.repetibles(topografo)) == recientes.CUANTAS


class TestLoQueNoSeOfrece:
    def test_lo_que_fallo_no_se_ofrece_repetir(self, topografo):
        """Repetirlo igual va a fallar igual. Está en el historial con su motivo, que es
        donde sirve — aquí sería mandar a alguien a chocarse dos veces."""
        _trabajo(topografo, perfil="qgis", estado=ERROR)
        _trabajo(topografo, perfil="civil3d", estado=CANCELADO)
        assert recientes.repetibles(topografo) == []

    def test_lo_de_otra_persona_no_se_ve(self, topografo):
        otra = get_user_model().objects.create_user("otra", password="y" * 20)  # nosec B106
        _trabajo(otra, perfil="qgis")
        assert recientes.repetibles(topografo) == []

    def test_un_destino_que_ya_no_existe_se_calla(self, topografo):
        """El trabajo sigue en el historial con su ficha, pero **no se ofrece repetir algo
        que hoy no se sabe hacer**: el enlace llevaría a una pantalla sin destino."""
        _trabajo(topografo, perfil="perfil-que-se-retiro", formato="formato-que-se-retiro")
        assert recientes.repetibles(topografo) == []

    def test_sin_perfil_se_cae_al_formato(self, topografo):
        """Quien llegó por «tif a jp2» no eligió programa de destino, eligió formato. Su
        repetición es al formato, y sigue siendo repetible."""
        _trabajo(topografo, perfil="", formato="gpkg")
        fila = recientes.repetibles(topografo)[0]
        assert fila.enlace.endswith("?formato=gpkg")


class TestEnLaPortada:
    def test_sale_encima_del_catalogo(self, client, topografo):
        client.force_login(topografo)
        _trabajo(topografo, perfil="qgis")
        cuerpo = client.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Seguir donde lo dejaste" in cuerpo

    def test_y_desaparece_al_buscar(self, client, topografo):
        """Quien escribió algo en la caja **ya dijo qué quiere**, y ponerle delante lo que
        hizo ayer es ruido. Sin JavaScript: la vista deja la lista vacía y el fragmento que
        htmx reemplaza es el mismo que la contiene."""
        client.force_login(topografo)
        _trabajo(topografo, perfil="qgis")
        cuerpo = client.get(reverse("dashboard:que_puedo_hacer"), {"q": "unir"}).content.decode()
        assert "Seguir donde lo dejaste" not in cuerpo

    def test_la_bienvenida_y_el_historial_no_coinciden_nunca(self, client, topografo):
        """Uno sale cuando no has convertido nada y el otro cuando sí: **son la misma
        franja de pantalla**, y verlos juntos sería decir «es tu primera vez» encima de lo
        que hiciste ayer."""
        client.force_login(topografo)
        vacia = client.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Cómo funciona esto" in vacia

        _trabajo(topografo, perfil="qgis")
        llena = client.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Cómo funciona esto" not in llena
        assert "Seguir donde lo dejaste" in llena
