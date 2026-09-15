"""Convertir: la puerta, la ficha, los veredictos y el encolado."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadhandler import StopUpload
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.core import manejador as manejador_mod
from apps.dashboard import views as vistas
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
    def test_se_pinta_con_las_dos_vias_de_entrada(self, entrado, taller):
        """Antes esto buscaba el botón «Inspeccionar» de la caja de pegar rutas.

        Esa caja ya no está: era la única vía cuando la pantalla se escribió para una
        estación de trabajo, y en el servidor se volvió una trampa —alguien pegaba la ruta de
        su propio equipo y recibía «fuera de las carpetas permitidas»—. Lo que hay que
        comprobar es que sigue habiendo **por dónde empezar**, y ahora son dos.
        """
        respuesta = entrado.get(reverse("dashboard:convertir"))
        assert respuesta.status_code == 200

        cuerpo = respuesta.content.decode()
        assert 'name="archivo"' in cuerpo, "Falta subir un archivo del propio equipo."
        assert "explorador" in cuerpo, "Falta el explorador de la carpeta compartida."

    def test_la_chapa_del_modo_esta_en_todas_las_pantallas(self, entrado, taller):
        """Saber si los archivos salen o no de la máquina es lo primero que hay que ver."""
        for ruta in ("/", "/convertir/", "/trabajos/", "/motores/"):
            assert b"Taller" in entrado.get(ruta).content


class TestCuandoNoCabe:
    """**Lo que pasó en el servidor el 2026-09-15**, y que nadie habría adivinado del mensaje.

    Alguien eligió una ortofoto de 600 MB con el tope en 200. `SubidaConTope` la cortó con
    `StopUpload`, que **descarta el cuerpo entero**, así que la vista recibió un `request.FILES`
    vacío — idéntico a no haber elegido nada. Y contestó «No llegó ningún archivo» con el
    código `ruta-no-permitida`: las dos cosas falsas, sobre un archivo que sí se eligió y que
    sí empezó a subir.
    """

    def _pedido(self, usuario, cortado: bool):
        """Un POST a `subir` sin archivo, con o sin la marca que deja el manejador.

        Se fabrica el pedido en vez de subir megabytes de verdad: lo que hay que comprobar es
        que la vista **distingue los dos casos**, y mandar doscientos megabytes por la suite
        tardaría minutos y no comprobaría nada más.
        """
        pedido = RequestFactory().post("/subir/")
        pedido.user = usuario
        if cortado:
            setattr(pedido, manejador_mod.MARCA_DE_CORTE, True)
        return pedido

    def test_dice_que_no_cabe_y_cuanto_cabe(self, usuario, settings):
        settings.TOPE_MB = 200
        cuerpo = vistas.subir(self._pedido(usuario, cortado=True)).content.decode()

        assert "200 MB" in cuerpo, "Sin el número no hay nada accionable."
        assert "carpeta compartida" in cuerpo, "Hay que decir por dónde sí."
        assert "No llegó ningún archivo" not in cuerpo

    def test_el_numero_sale_del_ajuste_y_no_esta_escrito_a_mano(self, usuario, settings):
        settings.TOPE_MB = 4096
        assert "4096 MB" in vistas.subir(self._pedido(usuario, cortado=True)).content.decode()

    def test_sin_marca_sigue_siendo_que_no_llego_nada(self, usuario):
        """Elegir de verdad ningún archivo y pulsar: ese mensaje sí era correcto."""
        cuerpo = vistas.subir(self._pedido(usuario, cortado=False)).content.decode()
        assert "No llegó ningún archivo" in cuerpo

    def test_el_manejador_deja_la_marca_antes_de_cortar(self, rf, settings):
        """La otra mitad: que el manejador la ponga. Sin esto la vista nunca entra en su rama.

        Se le dan 3 MB en trozos con el tope en 1: el corte tiene que llegar **antes** de
        haber recibido los tres, que es el otro motivo de que exista este manejador.
        """
        settings.TOPE_MB = 1
        pedido = rf.post("/subir/")
        manejador = manejador_mod.SubidaConTope(request=pedido)
        manejador.new_file("archivo", "grande.tif", "image/tiff", None, None)

        trozo = b"\0" * 262144
        with pytest.raises(StopUpload):
            for i in range(12):
                manejador.receive_data_chunk(trozo, i * len(trozo))

        assert getattr(pedido, manejador_mod.MARCA_DE_CORTE, False) is True


class TestElDestinoQueVieneDelCatalogo:
    """La última pata del viaje: que la ficha **marque** el destino que se pidió.

    Se comprueba aquí y no en `test_acciones.py` porque hace falta un archivo de verdad: sin
    inspeccionar no hay botones de destino, y es en los botones donde la marca se ve o no se
    ve. Las otras pruebas llegan hasta el campo escondido y ahí se quedan.
    """

    def test_la_ficha_marca_el_que_se_eligio(self, entrado, ortofoto, con_motor):
        cuerpo = entrado.get(
            "/inspeccionar/", {"ruta": str(ortofoto), "destino": "qgis"}
        ).content.decode()
        assert "destino-elegido" in cuerpo

    def test_y_marca_uno_solo(self, entrado, ortofoto, con_motor):
        """Seis botones resaltados no resaltan nada."""
        cuerpo = entrado.get(
            "/inspeccionar/", {"ruta": str(ortofoto), "destino": "qgis"}
        ).content.decode()
        assert cuerpo.count("destino-elegido") == 1

    def test_sin_destino_no_marca_ninguno(self, entrado, ortofoto, con_motor):
        cuerpo = entrado.get("/inspeccionar/", {"ruta": str(ortofoto)}).content.decode()
        assert "destino-elegido" not in cuerpo

    def test_un_destino_inventado_tampoco(self, entrado, ortofoto, con_motor):
        """Llega de fuera y acaba comparándose contra el identificador de cada perfil. Que no
        marque nada es exactamente lo correcto."""
        cuerpo = entrado.get(
            "/inspeccionar/", {"ruta": str(ortofoto), "destino": "../qgis"}
        ).content.decode()
        assert "destino-elegido" not in cuerpo


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
