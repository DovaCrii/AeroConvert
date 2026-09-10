"""La pantalla de convertir: que se entienda sin saber de geodesia.

Los tres pasos son lo primero que lee alguien que llega. La primera versión los escribió en
vocabulario de una sola familia —«ortofoto, nube de puntos, cartografía», «dimensiones,
bandas, sistema de referencia»— y eso tiene dos problemas: no le dice nada a quien llega con
una libreta de puntos o con un plano, y **envejece cada vez que entra una familia nueva**.

Lo que estos pasos explican es cómo funciona la herramienta. Qué formatos hay se mira en la
matriz de compatibilidad, que es la pantalla que existe para eso.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.jobs.models import HECHO, ConversionJob

pytestmark = pytest.mark.django_db

#: Palabras de una sola familia. Ninguna puede aparecer en los tres pasos.
JERGA = ("ortofoto", "bandas", "nube de puntos", "cartografía", "ráster", "Civil 3D", "QGIS")


@pytest.fixture
def sesion(client, db):
    usuario = get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    client.force_login(usuario)
    return client, usuario


def _pasos(cuerpo: str) -> str:
    """Solo el bloque de los tres pasos, sin el resto de la página."""
    inicio = cuerpo.index('<ol class="pasos">')
    return cuerpo[inicio : cuerpo.index("</ol>", inicio)]


class TestLosTresPasos:
    def test_estan_los_tres(self, sesion):
        cliente, _ = sesion
        pasos = _pasos(cliente.get(reverse("dashboard:convertir")).content.decode())
        assert pasos.count("<li>") == 3

    @pytest.mark.parametrize("palabra", JERGA)
    def test_ninguno_usa_vocabulario_de_una_sola_familia(self, sesion, palabra):
        """Un paso que habla de bandas no le dice nada a quien trae un archivo de puntos."""
        cliente, _ = sesion
        pasos = _pasos(cliente.get(reverse("dashboard:convertir")).content.decode())
        assert palabra.lower() not in pasos.lower()

    def test_prometen_lo_que_la_aplicacion_cumple(self, sesion):
        """«El original no se toca» no es una frase bonita: hay una prueba por cada camino
        de fallo que compara su hash y su fecha."""
        cliente, _ = sesion
        pasos = _pasos(cliente.get(reverse("dashboard:convertir")).content.decode())
        assert "no se toca" in pasos
        assert "no se copia ni se sube" in pasos.lower()

    def test_el_subtitulo_no_repite_los_pasos(self, sesion):
        """Decían casi lo mismo con otras palabras. Leer dos veces la misma explicación no
        aclara: cansa. El subtítulo dice **cuándo** usar esto, que no lo dice nadie más."""
        cliente, _ = sesion
        cuerpo = cliente.get(reverse("dashboard:convertir")).content.decode()
        assert "abre en un equipo y en otro no" in cuerpo


class TestElHistorialSeLee:
    def test_muestra_el_nombre_del_formato_y_no_su_codigo(self, sesion):
        """`geotiff` es la clave interna, y tiene que serlo: estable, en minúscula y sin
        espacios. Pero enseñarla obliga a traducir `gpkg` o `xyz_nube` mentalmente."""
        cliente, usuario = sesion
        ConversionJob.objects.create(
            owner=usuario,
            source_name="Cruce Minero.tif",
            target_format_code="geotiff",
            status=HECHO,
            output_size_bytes=285_000_000,
        )
        cuerpo = cliente.get(reverse("dashboard:convertir")).content.decode()

        assert "GeoTIFF clásico" in cuerpo
        assert "→ geotiff" not in cuerpo

    def test_un_codigo_sin_nombre_no_deja_la_celda_vacia(self, sesion):
        """Si un día se encola algo que ya no está en el catálogo, se enseña el código: es
        feo, y es mucho mejor que una fila en blanco."""
        cliente, usuario = sesion
        trabajo = ConversionJob.objects.create(
            owner=usuario,
            source_name="x.tif",
            target_format_code="formato-que-no-existe",
            status=HECHO,
        )
        assert trabajo.nombre_del_destino == "formato-que-no-existe"
