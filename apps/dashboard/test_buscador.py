"""Las dos vías para elegir un archivo, que antes era una sola y equivocada.

## Lo que pasaba

La pantalla pedía «pega su ruta» y eso solo tiene sentido en una estación de trabajo. En el
servidor compartido, alguien del equipo pegaba la ruta de su propio OneDrive y recibía «esa
ruta está fuera de las carpetas permitidas (/mnt/entregas)». El mensaje era **cierto y
completamente inútil**: el servidor no ve el disco de nadie, y no había forma de decírselo.

Ahora hay dos, y las dos evitan teclear:

- **Subir** lo que está en el equipo de quien mira.
- **Explorar** la carpeta compartida, que el servidor sí ve.
"""

import io
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import ArchivoSubido

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"

#: Un PNG de verdad de 1x1. La inspección abre el archivo, así que unos bytes cualesquiera
#: darían «no se reconoce» y la prueba mediría otra cosa.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00"
    b"\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9b"
    b"\xdd\xed\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106


@pytest.fixture
def entrada(tmp_path, settings):
    """Una carpeta compartida de mentira, con una subcarpeta y un archivo dentro."""
    raiz = tmp_path / "entregas"
    (raiz / "CC716").mkdir(parents=True)
    (raiz / "CC716" / "ortofoto.png").write_bytes(PNG)
    # `.zip` y no `.docx`: Word a PDF existe, así que un `.docx` **sí** es de los nuestros y
    # aparecer en la lista es lo correcto. Con él, esta prueba medía lo contrario de lo que
    # dice su nombre.
    (raiz / "CC716" / "respaldo.zip").write_bytes(b"no es de las nuestras")
    # Una cadena y no una lista: el ajuste viaja así desde el `.env`, separado por `;`, y
    # `raices_permitidas()` es quien lo parte.
    settings.RAICES_PERMITIDAS = str(raiz)
    return raiz


class TestSubirDesdeElEquipo:
    def test_devuelve_la_ficha_del_archivo(self, client, ana):
        client.force_login(ana)
        archivo = io.BytesIO(PNG)
        archivo.name = "desde-mi-pc.png"
        respuesta = client.post(reverse("dashboard:subir"), {"archivo": archivo})
        assert respuesta.status_code == 200
        assert "desde-mi-pc.png" in respuesta.content.decode()

    def test_y_el_formulario_lleva_un_identificador_no_una_ruta(self, client, ana):
        """**La línea donde equivocarse sería una fuga.** Devolver la ruta del servidor
        dejaría que el POST siguiente la tratara como una ruta del disco, que es justo la vía
        que `entrada.py` existe para mantener separada."""
        client.force_login(ana)
        archivo = io.BytesIO(PNG)
        archivo.name = "plano.png"
        cuerpo = client.post(reverse("dashboard:subir"), {"archivo": archivo}).content.decode()

        subida = ArchivoSubido.objects.get()
        assert f'value="subida:{subida.pk}"' in cuerpo
        assert str(subida.ruta) not in cuerpo

    def test_sin_archivo_lo_dice_y_no_revienta(self, client, ana):
        client.force_login(ana)
        respuesta = client.post(reverse("dashboard:subir"), {})
        assert respuesta.status_code == 200
        assert "No llegó ningún archivo" in respuesta.content.decode()

    def test_hay_que_haber_entrado(self, client):
        assert client.post(reverse("dashboard:subir"), {}).status_code == 302


class TestExplorarLaCarpetaCompartida:
    def test_lista_lo_que_hay(self, client, ana, entrada):
        client.force_login(ana)
        cuerpo = client.get(reverse("dashboard:explorar")).content.decode()
        assert "CC716" in cuerpo

    def test_solo_los_formatos_que_sabemos_abrir(self, client, ana, entrada):
        """Un `.docx` en medio de la obra es ruido cuando lo que se busca es la ortofoto."""
        client.force_login(ana)
        cuerpo = client.get(
            reverse("dashboard:explorar"), {"en": str(entrada / "CC716")}
        ).content.decode()
        assert "ortofoto.png" in cuerpo
        assert "respaldo.zip" not in cuerpo

    def test_no_se_sale_de_las_raices_permitidas(self, client, ana, entrada, tmp_path):
        """**El explorador no abre ni un milímetro más que lo que ya estaba abierto.** Usa
        `comprobar_ruta`, la misma de siempre."""
        fuera = tmp_path / "privado"
        fuera.mkdir()
        (fuera / "secreto.png").write_bytes(PNG)

        client.force_login(ana)
        cuerpo = client.get(reverse("dashboard:explorar"), {"en": str(fuera)}).content.decode()
        assert "secreto.png" not in cuerpo

    def test_las_migas_no_suben_por_encima_de_la_raiz(self, client, ana, entrada):
        """Un `..` que lleva a donde luego se recibe «fuera de las carpetas permitidas» es
        peor que no tenerlo.

        Se miran **los destinos de navegación**, no el texto entero: la ruta del padre aparece
        dentro de la de cualquier archivo por ser su prefijo, así que buscarla a secas daría
        un fallo donde no lo hay.
        """
        client.force_login(ana)
        cuerpo = client.get(
            reverse("dashboard:explorar"), {"en": str(entrada / "CC716")}
        ).content.decode()

        destinos = [unquote(d) for d in re.findall(r"\?en=([^\"']+)", cuerpo)]
        assert destinos, "Sin migas no se puede volver atrás."
        for destino in destinos:
            assert Path(destino) == entrada or entrada in Path(destino).parents

    def test_hay_que_haber_entrado(self, client):
        assert client.get(reverse("dashboard:explorar")).status_code == 302


class TestConvertirLoSubido:
    def test_se_puede_encolar_con_el_identificador(self, client, ana):
        """El recorrido entero: subir, y que el trabajo salga con el nombre que la persona
        reconoce y no con el que quedó en el servidor."""
        client.force_login(ana)
        archivo = io.BytesIO(PNG)
        archivo.name = "OF-220kv.png"
        client.post(reverse("dashboard:subir"), {"archivo": archivo})
        subida = ArchivoSubido.objects.get()

        respuesta = client.post(
            reverse("dashboard:encolar"),
            {"ruta": f"subida:{subida.pk}", "formato": "geotiff"},
        )
        assert respuesta.status_code == 302

        from apps.jobs.models import ConversionJob

        job = ConversionJob.objects.get()
        assert job.source_name == "OF-220kv.png"
