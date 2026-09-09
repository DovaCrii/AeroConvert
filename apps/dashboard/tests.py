"""Convertir: la puerta, la ficha, los veredictos y el encolado."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import bigtiff_minimo, geotiff_minimo
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def entrado(client, usuario):
    client.force_login(usuario)
    return client


@pytest.fixture
def taller(tmp_path, settings):
    settings.MODO = "taller"
    settings.RAICES_PERMITIDAS = str(tmp_path)
    return tmp_path


@pytest.fixture
def ortofoto(taller):
    """Una ortofoto BigTIFF con alfa: el caso que originó la aplicación, en 400 bytes."""
    ruta = taller / "Cruce Minero.tif"
    ruta.write_bytes(bigtiff_minimo(bandas=4, alfa=True, compresion=5))
    return ruta


@pytest.fixture
def con_motor():
    guardado = registry.todos()
    registry.limpiar()
    registry.registrar(MotorDeMentira("mentira", ((("bigtiff", "geotiff")), (("geotiff", "cog")))))
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


class TestLaPuerta:
    """Prueba de acceso por vista, como exige el estándar de la familia."""

    @pytest.mark.parametrize(
        "ruta", ["/", "/inspeccionar/", "/trabajos/", "/motores/", "/preajustes/"]
    )
    def test_sin_entrar_se_va_al_login(self, client, ruta):
        respuesta = client.get(ruta)
        assert respuesta.status_code == 302
        assert "/entrar/" in respuesta["Location"]

    def test_convertir_no_admite_get(self, entrado):
        """Encolar cambia estado: un GET no puede hacerlo, ni desde un enlace ni desde una
        imagen incrustada en un correo."""
        assert entrado.get("/encolar/").status_code == 405


class TestLaMesa:
    def test_se_pinta(self, entrado, taller):
        respuesta = entrado.get("/")
        assert respuesta.status_code == 200
        assert b"Inspeccionar" in respuesta.content

    def test_la_chapa_del_modo_esta_en_todas_las_pantallas(self, entrado, taller):
        """Saber si los archivos salen o no de la máquina es lo primero que hay que ver."""
        for ruta in ("/", "/trabajos/", "/motores/"):
            assert b"Taller" in entrado.get(ruta).content


class TestLaEstimacion:
    """La línea honesta: cuánto va a pesar y cuánto va a tardar, antes de pulsar."""

    def test_cada_destino_disponible_trae_su_estimacion(self, entrado, ortofoto, con_motor):
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "≈" in contenido

    def test_un_destino_apagado_no_estima_nada(self, entrado, ortofoto, con_motor):
        """Estimar lo que no se puede hacer sería ruido con cifras."""
        from apps.dashboard.views import _destinos_para
        from apps.formats.deteccion import inspeccionar as inspeccionar_archivo

        for destino in _destinos_para(inspeccionar_archivo(ortofoto)):
            if not destino.se_puede:
                assert destino.estimacion is None


class TestModoExperto:
    def test_los_ajustes_se_piden_aparte_al_cambiar_el_formato(self, entrado, ortofoto, con_motor):
        """JP2 tiene calidad y GeoTIFF tiene tamaño de tesela: cambiar el destino cambia el
        formulario, así que htmx lo vuelve a pedir."""
        respuesta = entrado.get("/ajustes/", {"ruta": str(ortofoto), "formato": "geotiff"})
        assert respuesta.status_code == 200

    def test_un_formato_inventado_no_pinta_ajustes(self, entrado, ortofoto, con_motor):
        respuesta = entrado.get("/ajustes/", {"ruta": str(ortofoto), "formato": "xyzzy"})
        assert respuesta.status_code == 200
        assert b"<input" not in respuesta.content

    def test_sin_entrar_no_se_piden_ajustes(self, client, ortofoto):
        assert client.get("/ajustes/").status_code == 302


class TestInspeccionar:
    def test_sin_ruta_no_se_queja_todavia(self, entrado, taller):
        """Es el estado inicial de la pantalla, no un error."""
        respuesta = entrado.get("/inspeccionar/")
        assert respuesta.status_code == 200
        assert b"Inspeccionar" in respuesta.content

    def test_una_ruta_fuera_de_las_raices_se_rechaza_con_su_motivo(self, entrado, taller):
        respuesta = entrado.get("/inspeccionar/", {"ruta": r"C:\Windows\notepad.exe"})
        assert b"ruta-no-permitida" in respuesta.content

    def test_un_archivo_que_no_existe_da_su_motivo(self, entrado, taller):
        respuesta = entrado.get("/inspeccionar/", {"ruta": str(taller / "fantasma.tif")})
        assert b"origen-no-legible" in respuesta.content

    def test_la_ficha_dice_lo_que_hay_dentro(self, entrado, ortofoto):
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "BigTIFF" in contenido
        assert "EPSG:32719" in contenido
        assert "con banda alfa" in contenido

    def test_avisa_de_que_bigtiff_no_hacia_falta(self, entrado, ortofoto):
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "sin necesitarlo" in contenido

    def test_la_tira_de_veredictos_dice_que_civil3d_no_abre(self, entrado, ortofoto):
        """El diagnóstico que da nombre al producto."""
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "Civil 3D" in contenido
        assert "no lee BigTIFF" in contenido

    def test_un_geotiff_normal_abre_en_civil3d(self, entrado, taller):
        limpio = taller / "limpio.tif"
        limpio.write_bytes(geotiff_minimo(bandas=3))
        contenido = entrado.get("/inspeccionar/", {"ruta": str(limpio)}).content.decode()
        assert "Abre tal cual" in contenido

    def test_hay_un_destino_por_perfil(self, entrado, ortofoto, con_motor):
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        for nombre in ("Civil 3D", "QGIS", "ArcGIS Pro", "Google Earth", "Visor web", "AeroBim"):
            assert nombre in contenido

    def test_un_destino_sin_motor_sale_apagado_pero_no_desaparece(
        self, entrado, ortofoto, con_motor
    ):
        """Ocultarlo haría parecer que ese destino nunca existió."""
        contenido = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "Google Earth" in contenido
        assert "disabled" in contenido


class TestConvertir:
    def test_encola_y_lleva_a_la_ficha(self, entrado, ortofoto, con_motor):
        respuesta = entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})

        job = ConversionJob.objects.get()
        assert respuesta.status_code == 302
        assert str(job.pk) in respuesta["Location"]
        assert job.status == "queued"

    def test_el_perfil_fija_formato_y_opciones(self, entrado, ortofoto, con_motor):
        """Nadie quiere «un GeoTIFF con BIGTIFF=NO»: quiere que abra en el PC del
        proyectista. El perfil traduce lo segundo en lo primero."""
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})

        job = ConversionJob.objects.get()
        assert job.target_format_code == "geotiff"
        assert job.target_profile_id == "civil3d"
        assert job.options["bigtiff"] == "NO"
        assert job.options["solo_rgb"] is True

    def test_guarda_lo_inspeccionado_para_no_repetirlo(self, entrado, ortofoto, con_motor):
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})
        job = ConversionJob.objects.get()
        assert job.source_format_code == "bigtiff"
        assert job.source_crs_code == "32719"
        assert job.source_size_bytes > 0

    def test_la_salida_va_junto_al_original_en_taller(self, entrado, ortofoto, con_motor):
        """Quien convierte una ortofoto la quiere al lado de su entregable, no perdida en
        un directorio de la aplicación."""
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})
        job = ConversionJob.objects.get()
        assert job.output_path.startswith(str(ortofoto.parent))
        assert job.output_path.endswith("_civil3d.tif")

    def test_el_modo_experto_acepta_un_formato_suelto(self, entrado, ortofoto, con_motor):
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "", "formato": "geotiff"})
        job = ConversionJob.objects.get()
        assert job.target_format_code == "geotiff"
        assert job.target_profile_id == ""

    def test_el_modo_experto_lee_los_ajustes_que_el_motor_declara(
        self, entrado, ortofoto, con_motor
    ):
        """El motor de mentira no declara ninguno, así que el resultado tiene que ser un
        diccionario vacío y no lo que venga en el POST."""
        entrado.post(
            "/encolar/",
            {"ruta": str(ortofoto), "perfil": "", "formato": "geotiff", "inventado": "x"},
        )
        assert ConversionJob.objects.get().options == {}

    def test_un_par_que_ningun_motor_sabe_hacer_se_rechaza(self, entrado, ortofoto, con_motor):
        """Encolarlo sería condenar a alguien a esperar un fallo que ya se sabe. El motor de
        mentira sabe `bigtiff→geotiff`, no `bigtiff→jp2`."""
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "", "formato": "jp2"})
        assert ConversionJob.objects.count() == 0

    def test_un_preajuste_fija_su_destino_y_cuenta_el_uso(self, entrado, ortofoto, con_motor):
        from apps.presets.models import ConversionPreset

        preajuste = ConversionPreset.objects.create(
            slug="entrega-bhp",
            nombre="Entrega cliente BHP",
            target_format_code="geotiff",
            options={"compresion": "DEFLATE", "solo_rgb": True},
        )

        entrado.post("/encolar/", {"ruta": str(ortofoto), "preajuste": preajuste.slug})

        job = ConversionJob.objects.get()
        assert job.target_format_code == "geotiff"
        assert job.options == {"compresion": "DEFLATE", "solo_rgb": True}
        preajuste.refresh_from_db()
        assert preajuste.veces_usado == 1

    def test_un_preajuste_borrado_no_encola_nada(self, entrado, ortofoto, con_motor):
        entrado.post("/encolar/", {"ruta": str(ortofoto), "preajuste": "ya-no-existe"})
        assert ConversionJob.objects.count() == 0

    def test_un_formato_inventado_se_rechaza(self, entrado, ortofoto, con_motor):
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "", "formato": "xyzzy"})
        assert ConversionJob.objects.count() == 0

    def test_una_ruta_prohibida_no_encola_nada(self, entrado, taller, con_motor):
        entrado.post("/encolar/", {"ruta": r"C:\Windows\notepad.exe", "perfil": "civil3d"})
        assert ConversionJob.objects.count() == 0

    def test_no_se_convierte_sin_entrar(self, client, ortofoto):
        respuesta = client.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})
        assert respuesta.status_code == 302
        assert ConversionJob.objects.count() == 0

    @override_settings(MODO="nube")
    def test_en_nube_la_salida_va_a_la_carpeta_de_trabajo(
        self, entrado, ortofoto, con_motor, tmp_path, settings
    ):
        settings.MODO = "taller"  # comprobar_ruta exige taller para leer del disco
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        entrado.post("/encolar/", {"ruta": str(ortofoto), "perfil": "civil3d"})
        assert ConversionJob.objects.count() == 1
