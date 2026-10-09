"""Ver en el mapa, de punta a punta con un GDAL de mentira: permisos, 403, caché HTTP y rechazos.

Cada vista nueva trae su prueba de **sesión** (302) y de **403** (lo que está fuera de las carpetas
permitidas, o es de otra persona), como pide `AGENTS.md`. Y la regla 5 en cada camino de fallo: el
original, con el mismo `sha256` y el mismo `mtime` antes y después.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.engines.base import Disponibilidad
from apps.jobs.models import HECHO, ConversionJob
from apps.visor import cache, mercator, motor
from apps.visor.testing import (
    WKT_LOCAL,
    GdalDeMentira,
    info_de_gdal,
)

pytestmark = pytest.mark.django_db

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def obra(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path / "obra")
    settings.MODO = settings.MODO_TALLER
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 64
    carpeta = tmp_path / "obra"
    carpeta.mkdir()
    return carpeta


@pytest.fixture
def original(obra):
    ruta = obra / "ortofoto.tif"
    ruta.write_bytes(b"II*\x00" + b"ortofoto sintetica" * 200)
    return ruta


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana")


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto")


@pytest.fixture
def sesion(client, ana):
    client.force_login(ana)
    return client


@pytest.fixture
def falso(monkeypatch):
    """GDAL de mentira, y presente."""
    mentira = GdalDeMentira()
    monkeypatch.setattr(motor, "correr", mentira)
    monkeypatch.setattr(motor, "disponibilidad", lambda: Disponibilidad.si("GDAL de mentira"))
    return mentira


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _url_de_tesela(z=1, x=0, y=0) -> str:
    return reverse("visor:tesela", args=[z, x, y])


def _tesela_de_la_capa(sesion, original) -> tuple[str, dict]:
    """Una tesela que sí toca la capa (la del centro, al último nivel) y su ficha."""
    ficha = sesion.get(reverse("visor:capa"), {"ruta": str(original)}).json()
    z = ficha["zoom_maximo"]
    x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)
    return _url_de_tesela(z, x, y), ficha


class TestSesion:
    @pytest.mark.parametrize(
        "url",
        [
            reverse("visor:inicio"),
            reverse("visor:capa"),
            reverse("visor:punto"),
            "/mapa/teselas/3/2/2.png",
        ],
    )
    def test_sin_sesion_va_a_la_entrada(self, client, url):
        respuesta = client.get(url)
        assert respuesta.status_code == 302
        assert reverse("login") in respuesta["Location"]

    @pytest.mark.parametrize(
        "url", [reverse("visor:inicio"), reverse("visor:capa"), reverse("visor:punto")]
    )
    def test_son_de_solo_lectura(self, sesion, url):
        assert sesion.post(url).status_code == 405
        assert sesion.put(url).status_code == 405
        assert sesion.delete(url).status_code == 405

    def test_la_tesela_tampoco_se_escribe(self, sesion):
        assert sesion.post(_url_de_tesela()).status_code == 405


class TestElCuatroCientosTres:
    """Lo que no es de quien pregunta o está fuera de las raíces **es 403**, con su código."""

    def test_una_ruta_fuera_de_las_raices_es_403_en_las_cuatro(self, sesion, falso, obra, tmp_path):
        fuera = tmp_path / "secreto.tif"
        fuera.write_bytes(b"II*\x00fuera")
        antes = _huella(fuera)

        pantalla = sesion.get(reverse("visor:inicio"), {"ruta": str(fuera)})
        assert pantalla.status_code == 403
        assert "fuera de las carpetas permitidas" in pantalla.content.decode()
        for nombre in ("visor:capa", "visor:punto"):
            respuesta = sesion.get(reverse(nombre), {"ruta": str(fuera), "lon": 0, "lat": 0})
            assert respuesta.status_code == 403, nombre
            assert respuesta.json()["codigo"] == "ruta-no-permitida"
        respuesta = sesion.get(_url_de_tesela(), {"ruta": str(fuera)})
        assert respuesta.status_code == 403
        assert respuesta.json()["codigo"] == "ruta-no-permitida"

        assert falso.llamadas == [], "ni siquiera se le preguntó a GDAL"
        assert _huella(fuera) == antes

    def test_un_recorrido_con_puntos_puntos_tampoco_sale(self, sesion, falso, obra, tmp_path):
        fuera = tmp_path / "secreto.tif"
        fuera.write_bytes(b"II*\x00fuera")
        truco = obra / ".." / "secreto.tif"
        assert sesion.get(reverse("visor:capa"), {"ruta": str(truco)}).status_code == 403

    def test_en_modo_nube_no_se_lee_del_disco_del_servidor(self, sesion, falso, original, settings):
        settings.MODO = settings.MODO_NUBE
        respuesta = sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        assert respuesta.status_code == 403
        assert respuesta.json()["codigo"] == "ruta-no-permitida"

    def test_sin_ruta_la_api_dice_403_y_no_500(self, sesion, falso):
        assert sesion.get(reverse("visor:capa")).status_code == 403
        assert sesion.get(reverse("visor:capa"), {"ruta": "   "}).status_code == 403

    def test_una_subida_que_no_es_suya_es_403_y_no_confirma_nada(self, sesion, falso):
        respuesta = sesion.get(
            reverse("visor:capa"), {"ruta": "subida:00000000-0000-0000-0000-000000000000"}
        )
        assert respuesta.status_code == 403
        assert respuesta.json()["codigo"] == "origen-no-legible"

    def test_el_resultado_de_otra_persona_es_403(self, sesion, falso, beto, obra):
        salida = obra / "salida.tif"
        salida.write_bytes(b"II*\x00" + b"x" * 50)
        ajeno = ConversionJob.objects.create(
            owner=beto,
            source_name="x.tif",
            target_format_code="cog",
            status=HECHO,
            output_path=str(salida),
            finished_at=timezone.now(),
        )
        respuesta = sesion.get(reverse("visor:capa"), {"ruta": f"resultado:{ajeno.pk}"})
        assert respuesta.status_code == 403
        assert str(salida) not in respuesta.content.decode(), "no se filtra la ruta del servidor"

    def test_una_ruta_a_un_archivo_que_ya_no_esta_es_404(self, sesion, falso, obra):
        respuesta = sesion.get(reverse("visor:capa"), {"ruta": str(obra / "no-esta.tif")})
        assert respuesta.status_code == 404
        assert respuesta.json()["codigo"] == "origen-no-legible"


class TestSoloImagenesLlegaAGdal:
    """Un `.vrt` o un `.xml` pueden apuntar a otro archivo (fuera de las raíces) o a internet:
    abrirlos con GDAL saltaría el 403 y la regla D5. Solo `.tif` y `.tiff`."""

    @pytest.mark.parametrize(
        "nombre", ["capa.vrt", "servicio.xml", "datos.gpkg", "nube.laz", "x.tif.vrt"]
    )
    def test_otra_extension_no_llega_a_gdal(self, sesion, falso, obra, nombre):
        ajeno = obra / nombre
        ajeno.write_text("<VRTDataset><SourceFilename>/etc/passwd</SourceFilename></VRTDataset>")
        antes = _huella(ajeno)
        for url, pedido in (
            (reverse("visor:capa"), {}),
            (reverse("visor:punto"), {"lon": 0, "lat": 0}),
            (_url_de_tesela(10, 300, 600), {}),
        ):
            respuesta = sesion.get(url, {"ruta": str(ajeno), **pedido})
            assert respuesta.status_code == 422, url
            assert respuesta.json()["codigo"] == "formato-no-reconocido"
        pantalla = sesion.get(reverse("visor:inicio"), {"ruta": str(ajeno)})
        assert pantalla.status_code == 422
        assert "solo abre GeoTIFF" in pantalla.content.decode()
        assert falso.llamadas == []
        assert _huella(ajeno) == antes

    def test_tif_en_mayusculas_si(self, sesion, falso, obra):
        mayus = obra / "ORTO.TIF"
        mayus.write_bytes(b"II*\x00" + b"x" * 50)
        assert sesion.get(reverse("visor:capa"), {"ruta": str(mayus)}).status_code == 200

    def test_la_tesela_se_revalida_siempre(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        cabecera = sesion.get(url, {"ruta": str(original)})["Cache-Control"]
        assert "must-revalidate" in cabecera and "max-age=0" in cabecera


class TestUnFalloDeDiscoNoFiltraRutas:
    """Un `OSError` de la caché lleva la ruta del servidor: a la persona, un mensaje fijo y un
    código estable; el detalle, solo al registro."""

    SECRETO = r"C:\servidor\carpeta-privada\cache-visor\ab\0123"

    @pytest.fixture
    def disco_roto(self, monkeypatch):
        def falla(*_a, **_k):
            raise PermissionError(13, "Acceso denegado", self.SECRETO)

        monkeypatch.setattr(cache, "escribir", falla)

    def _sin_filtrar(self, respuesta):
        cuerpo = respuesta.content.decode()
        assert "carpeta-privada" not in cuerpo and "Acceso denegado" not in cuerpo
        assert respuesta.status_code == 500

    def test_la_ficha(self, sesion, falso, original, disco_roto, caplog):
        respuesta = sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        self._sin_filtrar(respuesta)
        assert respuesta.json()["codigo"] == "cache-no-disponible"
        assert "carpeta-privada" in caplog.text, "el detalle sí queda en el registro"

    def test_la_tesela(self, sesion, falso, original, monkeypatch):
        _, ficha = _tesela_de_la_capa(sesion, original)  # la ficha queda en la caché
        z = ficha["zoom_maximo"]
        x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)

        def falla(*_a, **_k):
            raise OSError(28, "No space left on device", self.SECRETO)

        monkeypatch.setattr(cache, "reemplazar", falla)
        respuesta = sesion.get(_url_de_tesela(z, x, y), {"ruta": str(original)})
        self._sin_filtrar(respuesta)
        assert respuesta.json()["codigo"] == "cache-no-disponible"

    def test_el_punto(self, sesion, falso, original, disco_roto):
        respuesta = sesion.get(
            reverse("visor:punto"), {"ruta": str(original), "lon": -70.66, "lat": -33.47}
        )
        self._sin_filtrar(respuesta)

    def test_la_pantalla(self, sesion, falso, original, disco_roto):
        respuesta = sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        self._sin_filtrar(respuesta)
        assert "no se pudo leer o escribir" in respuesta.content.decode()

    def test_un_archivo_que_desaparece_sigue_siendo_404(self, sesion, falso, original, monkeypatch):
        def sin_archivo(_ruta):
            raise FileNotFoundError(2, "No existe", self.SECRETO)

        monkeypatch.setattr(cache, "clave_de", sin_archivo)
        for nombre in ("visor:capa", "visor:punto"):
            respuesta = sesion.get(reverse(nombre), {"ruta": str(original), "lon": 0, "lat": 0})
            assert respuesta.status_code == 404
            assert "carpeta-privada" not in respuesta.content.decode()

    def test_el_codigo_esta_en_el_catalogo(self):
        from apps.jobs.motivos import MOTIVOS

        assert "cache-no-disponible" in MOTIVOS

    def test_el_mensaje_de_gdal_no_trae_la_carpeta_del_servidor(self):
        ruta = r"C:\obra\privada\ortofoto.tif"
        texto = motor._sin_rutas(f"ERROR 4: {ruta}: not recognized", ["-json", ruta])
        assert "privada" not in texto and "ortofoto.tif" in texto

    @pytest.mark.parametrize(
        ("ruta", "como_la_escribe_gdal"),
        [
            # Las dos en cualquier sistema: el CI (Linux) vio pasar entera una ruta de Windows.
            (r"C:\obra\privada\ortofoto.tif", r"C:\obra\privada\ortofoto.tif"),
            (r"C:\obra\privada\ortofoto.tif", "C:/obra/privada/ortofoto.tif"),
            ("/srv/obra/privada/ortofoto.tif", "/srv/obra/privada/ortofoto.tif"),
        ],
    )
    def test_quita_la_carpeta_con_cualquier_barra(self, ruta, como_la_escribe_gdal):
        texto = motor._sin_rutas(f"ERROR 4: {como_la_escribe_gdal}: not recognized", [ruta])
        assert "privada" not in texto and "ortofoto.tif" in texto


class TestUnArchivoQueNoAbreSeRecuerda:
    def test_cinco_teselas_de_un_archivo_roto_preguntan_a_gdal_una_vez(
        self, sesion, falso, original
    ):
        falso.fallar_con = motor.ErrorDeGdal("ERROR 4: no es un raster", "error-del-motor")
        for x in range(5):
            respuesta = sesion.get(_url_de_tesela(10, 300 + x, 600), {"ruta": str(original)})
            assert respuesta.status_code == 502 or respuesta.status_code == 422
        assert falso.contar("gdalinfo") == 1

    def test_si_el_archivo_cambia_se_vuelve_a_intentar(self, sesion, falso, original):
        falso.fallar_con = motor.ErrorDeGdal("roto", "error-del-motor")
        sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        assert falso.contar("gdalinfo") == 1
        falso.fallar_con = None
        original.write_bytes(b"II*\x00" + b"arreglado y mas largo" * 30)
        assert sesion.get(reverse("visor:capa"), {"ruta": str(original)}).status_code == 200
        assert falso.contar("gdalinfo") == 2


class TestElVisorDiceElMotivoDeUnaTeselaFallida:
    JS = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")

    def test_pide_las_teselas_con_fetch_para_leer_el_motivo(self):
        assert "fetch(direccion(" in self.JS
        assert "new Image" not in self.JS, "una imagen que falla no dice por qué"
        assert "datos.mensaje" in self.JS and "datos.codigo" in self.JS

    def test_el_aviso_va_a_la_vista_y_se_lee_en_voz_alta(self, sesion, falso, original):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        aviso = re.search(r'<p[^>]*id="mapa-aviso"[^>]*>', cuerpo).group(0)
        assert 'role="status"' in aviso and 'aria-live="polite"' in aviso
        assert "icon-veredicto-reparos" in cuerpo, "el aviso lleva su forma además del color"
        assert "Aviso: " in cuerpo, "y su palabra para quien no ve el color ni el dibujo"

    def test_un_codigo_se_avisa_una_sola_vez(self):
        # Una vez **por capa y código** (F19.3): decenas de teselas con el mismo fallo, un aviso.
        assert "avisados.has(clave)" in self.JS and "avisados.add(clave)" in self.JS
        assert 'l.id + ":" + codigo' in self.JS

    def test_la_respuesta_de_un_504_trae_lo_que_se_va_a_mostrar(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        falso.fallar_con = motor.ErrorDeGdal(
            "gdalwarp tardó más de 90 s. Conviértala a COG.", "tardo-demasiado"
        )
        datos = sesion.get(url, {"ruta": str(original)}).json()
        assert datos["codigo"] == "tardo-demasiado" and "COG" in datos["mensaje"]


class TestDemasiadasTeselas:
    JS = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")

    def test_el_tope_es_120_y_dice_que_hay_que_acercarse(self):
        assert "MAXIMO_VISIBLES = 120" in self.JS
        assert "lista.length > MAXIMO_VISIBLES" in self.JS
        assert "demasiadas para pedirlas todas. Acerque el mapa" in self.JS

    def test_el_aviso_se_quita_cuando_deja_de_haber_demasiadas(self):
        assert 'quitarAviso("demasiadas:" + l.id)' in self.JS

    def test_pasado_el_tope_no_se_piden(self):
        """El `return` va antes de `pedirTesela`, dentro de la rama del aviso."""
        rama = self.JS[self.JS.index("lista.length > MAXIMO_VISIBLES") :]
        assert rama.index("return;") < rama.index("pedirTesela(")


class TestLasEtiquetasDelCanvasSeMiden:
    """Texto sobre una imagen cualquiera no se mide; sobre un fondo **opaco** del token, sí."""

    JS = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")

    def test_los_colores_son_tokens_de_la_hoja(self):
        for token in ("--av-text-secondary", "--av-surface", "--av-text"):
            assert f'"{token}"' in self.JS
        assert not re.search(r"colores\.(texto|papel|escala)\s*=\s*[\"']#", self.JS)

    def test_el_fondo_de_las_etiquetas_y_de_la_escala_es_opaco(self):
        # La transparencia de una capa (F19.3) se aplica **solo** dentro de `dibujarCapa`, entre
        # `save()` y `restore()`: las etiquetas y la escala se pintan después, opacas.
        inicio = self.JS.index("function dibujarCapa")
        fin = self.JS.index("function dibujar()")
        assert self.JS.count("globalAlpha") == 1
        assert inicio < self.JS.index("globalAlpha") < fin
        for funcion in ("function dibujarEtiquetas", "function dibujarEscala"):
            cuerpo = self.JS[self.JS.index(funcion) :]
            assert "globalAlpha" not in cuerpo[: cuerpo.index("restore()")]

    def test_las_etiquetas_se_pintan_sobre_el_fondo_del_token(self):
        cuerpo = self.JS[self.JS.index("function dibujarEtiquetas") :]
        cuerpo = cuerpo[: cuerpo.index("restore()")]
        assert cuerpo.index("colores.papel") < cuerpo.index("colores.texto")


class TestLaPantalla:
    def test_sin_ruta_ofrece_la_carpeta_y_los_trabajos_propios(self, sesion, falso):
        cuerpo = sesion.get(reverse("visor:inicio")).content.decode()
        assert "De la carpeta compartida" in cuerpo
        assert "De un trabajo suyo" in cuerpo
        assert 'hx-get="/explorar/?ext=.tif,.tiff"' in cuerpo
        assert 'data-enviar="#forma-mapa"' in cuerpo
        assert "Todavía no hay ninguna salida" in cuerpo

    def test_un_trabajo_propio_con_salida_tif_se_ofrece_y_abre(self, sesion, falso, ana, obra):
        salida = obra / "ortofoto_cog.tif"
        salida.write_bytes(b"II*\x00" + b"x" * 50)
        trabajo = ConversionJob.objects.create(
            owner=ana,
            source_name="x.tif",
            target_format_code="cog",
            status=HECHO,
            output_path=str(salida),
            finished_at=timezone.now(),
        )
        ofrecido = sesion.get(reverse("visor:inicio")).content.decode()
        assert f"resultado%3A{trabajo.pk}" in ofrecido or f"resultado:{trabajo.pk}" in ofrecido
        assert "ortofoto_cog.tif" in ofrecido

        abierto = sesion.get(reverse("visor:inicio"), {"ruta": f"resultado:{trabajo.pk}"})
        assert abierto.status_code == 200
        assert 'id="mapa-lienzo"' in abierto.content.decode()

    def test_solo_se_ofrecen_las_salidas_de_imagen(self, sesion, falso, ana, obra):
        for nombre in ("informe.pdf", "nube.laz", "imagen.tif"):
            ruta = obra / nombre
            ruta.write_bytes(b"x")
            ConversionJob.objects.create(
                owner=ana,
                source_name="x",
                target_format_code="x",
                status=HECHO,
                output_path=str(ruta),
                finished_at=timezone.now(),
            )
        cuerpo = sesion.get(reverse("visor:inicio")).content.decode()
        assert "imagen.tif" in cuerpo
        assert "informe.pdf" not in cuerpo and "nube.laz" not in cuerpo

    def test_con_un_archivo_dibujable_trae_el_mapa_y_su_contrato_con_el_js(
        self, sesion, falso, original
    ):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        assert 'id="mapa-visor"' in cuerpo
        assert f'data-ruta="{original}"' in cuerpo
        assert 'data-teselas="/mapa/teselas/0/0/0.png"' in cuerpo
        assert 'data-punto="/mapa/punto/"' in cuerpo
        assert "static/js/visor.js" in cuerpo
        # Quien no ve el mapa también tiene las cifras.
        assert "WGS 84 / UTM zone 19S" in cuerpo and "EPSG:32719" in cuerpo
        assert "-33,4723649" in cuerpo or "-33,472365" in cuerpo
        assert "Esquinas y centro" in cuerpo

    def test_dice_la_resolucion_del_pixel_y_el_tamano(self, sesion, falso, original):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        assert "200 × 100 px" in cuerpo
        assert "200,00 cm" in cuerpo  # 2 m de píxel

    def test_el_teclado_esta_documentado_en_la_pantalla(self, sesion, falso, original):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        assert "Con el teclado" in cuerpo
        for tecla in ("←", "+", "0", "Intro"):
            assert tecla in cuerpo

    def test_el_lienzo_se_puede_enfocar_y_tiene_nombre(self, sesion, falso, original):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        lienzo = re.search(r'<canvas[^>]*id="mapa-lienzo"[^>]*>', cuerpo).group(0)
        assert 'tabindex="0"' in lienzo and "aria-label=" in lienzo

    def test_el_enlace_del_lateral_lleva_a_la_pantalla(self, sesion, falso):
        cuerpo = sesion.get(reverse("visor:inicio")).content.decode()
        lateral = cuerpo[cuerpo.index('<aside class="lateral"') : cuerpo.index("</aside>")]
        assert f'href="{reverse("visor:inicio")}"' in lateral
        assert 'aria-current="page"' in lateral[lateral.index("Ver en el mapa") - 400 :]

    def test_un_archivo_corrupto_se_dice_con_422(self, sesion, falso, original):
        falso.fallar_con = motor.ErrorDeGdal("ERROR 4: no es un raster", "error-del-motor")
        respuesta = sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        assert respuesta.status_code == 422
        assert "No se pudo abrir" in respuesta.content.decode()


class TestSinGdalApagadaConMotivo:
    """**Regla 4**: se muestra apagada, con su motivo y su alternativa; ni oculta ni sustituida."""

    @pytest.fixture
    def sin_gdal(self, monkeypatch):
        monkeypatch.setattr(
            motor,
            "disponibilidad",
            lambda: Disponibilidad.no(
                "sin-gdal",
                "Esta máquina no tiene GDAL, que es lo que corta la imagen en teselas.",
                sugerencia="Instale GDAL. Mientras tanto, la ficha de «Convertir» la sitúa.",
            ),
        )

    def test_la_pantalla_sale_y_dice_por_que_y_que_hacer(self, sesion, sin_gdal, original):
        respuesta = sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert "Ahora mismo no se puede" in cuerpo
        assert "no tiene GDAL" in cuerpo
        assert "Mientras tanto" in cuerpo
        assert reverse("dashboard:convertir") in cuerpo, "la alternativa es un enlace que funciona"
        assert 'id="mapa-lienzo"' not in cuerpo, "no se finge un mapa que no hay"

    def test_el_enlace_del_lateral_sigue_y_no_desaparece(self, sesion, sin_gdal):
        cuerpo = sesion.get(reverse("visor:inicio")).content.decode()
        assert "Ver en el mapa" in cuerpo[cuerpo.index('<aside class="lateral"') :]

    @pytest.mark.parametrize("nombre", ["visor:capa", "visor:punto"])
    def test_la_api_dice_503_con_el_codigo_estable(self, sesion, sin_gdal, original, nombre):
        respuesta = sesion.get(reverse(nombre), {"ruta": str(original), "lon": 0, "lat": 0})
        assert respuesta.status_code == 503
        datos = respuesta.json()
        assert datos["codigo"] == "sin-gdal"
        assert datos["sugerencia"]

    def test_la_tesela_dice_503_y_no_entrega_otra_cosa(self, sesion, sin_gdal, original):
        respuesta = sesion.get(_url_de_tesela(), {"ruta": str(original)})
        assert respuesta.status_code == 503
        assert respuesta["Content-Type"].startswith("application/json")
        assert respuesta.json()["codigo"] == "sin-gdal"


class TestSinCrsNoSeDibuja:
    """**Regla 3**: el CRS no se adivina. Se dice y no se pinta; sin «el más probable»."""

    @pytest.mark.parametrize("wkt", [None, "", WKT_LOCAL])
    def test_la_pantalla_lo_dice_y_no_dibuja(self, sesion, falso, original, wkt):
        falso.info = info_de_gdal(wkt=wkt)
        respuesta = sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert "no se dibuja en el mapa" in cuerpo
        assert "no declara un sistema de referencia" in cuerpo
        assert 'id="mapa-lienzo"' not in cuerpo
        assert "visor.js" not in cuerpo
        assert "32719" not in cuerpo and "probable" not in cuerpo.lower()

    def test_la_api_de_la_capa_dice_que_no_es_dibujable(self, sesion, falso, original):
        falso.info = info_de_gdal(wkt=None)
        datos = sesion.get(reverse("visor:capa"), {"ruta": str(original)}).json()
        assert datos["dibujable"] is False and datos["motivo"] == "capa-sin-crs"

    def test_y_la_tesela_no_se_corta(self, sesion, falso, original):
        falso.info = info_de_gdal(wkt=None)
        respuesta = sesion.get(_url_de_tesela(10, 300, 600), {"ruta": str(original)})
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "capa-sin-crs"
        assert falso.contar("gdalwarp") == 0

    def test_ni_se_le_pregunta_el_punto(self, sesion, falso, original):
        falso.info = info_de_gdal(wkt=None)
        respuesta = sesion.get(
            reverse("visor:punto"), {"ruta": str(original), "lon": -70.6, "lat": -33.4}
        )
        assert respuesta.status_code == 409

    def test_sin_matriz_tambien_se_dice(self, sesion, falso, original):
        info = info_de_gdal()
        del info["geoTransform"]
        falso.info = info
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        assert "no trae su matriz de transformación" in cuerpo


class TestLaFichaDeLaCapa:
    def test_trae_lo_que_el_js_necesita_y_no_el_wkt(self, sesion, falso, original):
        datos = sesion.get(reverse("visor:capa"), {"ruta": str(original)}).json()
        for campo in (
            "caja_3857",
            "contorno_3857",
            "esquinas_4326",
            "centro_4326",
            "zoom_minimo",
            "zoom_maximo",
            "sistema",
            "epsg",
        ):
            assert campo in datos, campo
        assert "wkt" not in datos and "geotransform" not in datos
        assert datos["dibujable"] is True

    def test_no_se_guarda_en_cache_compartida(self, sesion, falso, original):
        respuesta = sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        assert "no-store" in respuesta["Cache-Control"]

    def test_pregunta_a_gdal_una_sola_vez_aunque_se_pida_varias(self, sesion, falso, original):
        for _ in range(3):
            sesion.get(reverse("visor:capa"), {"ruta": str(original)})
        assert falso.contar("gdalinfo") == 1


class TestLaTeselaPorHttp:
    def test_devuelve_un_png_con_etag_y_cache_privada(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        respuesta = sesion.get(url, {"ruta": str(original)})
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "image/png"
        assert respuesta.content.startswith(b"\x89PNG")
        assert respuesta["ETag"].startswith('"') and respuesta["ETag"].endswith('"')
        cabecera = respuesta["Cache-Control"]
        assert "private" in cabecera and "public" not in cabecera
        assert "max-age" in cabecera

    def test_con_if_none_match_responde_304_sin_cortar_nada(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        primera = sesion.get(url, {"ruta": str(original)})
        cortes = falso.contar("gdalwarp")
        segunda = sesion.get(url, {"ruta": str(original)}, HTTP_IF_NONE_MATCH=primera["ETag"])
        assert segunda.status_code == 304
        assert segunda.content == b""
        assert segunda["ETag"] == primera["ETag"]
        assert "private" in segunda["Cache-Control"]
        assert falso.contar("gdalwarp") == cortes

    def test_el_etag_cambia_con_la_tesela_y_con_el_archivo(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        a = sesion.get(url, {"ruta": str(original)})["ETag"]
        otra = url.replace(".png", "").rsplit("/", 1)
        b = sesion.get(f"{otra[0]}/{int(otra[1]) + 1}.png", {"ruta": str(original)})["ETag"]
        assert a != b
        original.write_bytes(b"II*\x00" + b"otro contenido, otro tamano" * 50)
        c = sesion.get(url, {"ruta": str(original)})["ETag"]
        assert c != a, "un archivo distinto no se sirve con la tesela vieja"

    def test_un_etag_de_otra_tesela_no_da_304(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        respuesta = sesion.get(url, {"ruta": str(original)}, HTTP_IF_NONE_MATCH='"otra-cosa"')
        assert respuesta.status_code == 200

    def test_un_etag_valido_no_abre_el_archivo_a_quien_no_puede(
        self, sesion, falso, original, obra
    ):
        """El 304 va **después** de la puerta: sin permiso, 403 aunque traiga un ETag."""
        url, _ = _tesela_de_la_capa(sesion, original)
        etag = sesion.get(url, {"ruta": str(original)})["ETag"]
        respuesta = sesion.get(
            url, {"ruta": str(obra.parent / "otra.tif")}, HTTP_IF_NONE_MATCH=etag
        )
        assert respuesta.status_code == 403

    def test_una_tesela_fuera_de_la_capa_es_transparente_y_no_corta(self, sesion, falso, original):
        _, ficha = _tesela_de_la_capa(sesion, original)
        z = ficha["zoom_maximo"]
        lejos = mercator.tesela_de_lonlat(ficha["centro_4326"][0] + 3, ficha["centro_4326"][1], z)
        respuesta = sesion.get(_url_de_tesela(z, *lejos), {"ruta": str(original)})
        assert respuesta.status_code == 200
        assert falso.contar("gdalwarp") == 0

    @pytest.mark.parametrize("z,x,y", [(0, 1, 0), (2, 0, 4), (25, 0, 0)])
    def test_una_tesela_que_no_existe_es_404(self, sesion, falso, original, z, x, y):
        respuesta = sesion.get(_url_de_tesela(z, x, y), {"ruta": str(original)})
        assert respuesta.status_code == 404
        assert respuesta.json()["codigo"] == "tesela-fuera-de-la-cuadricula"

    def test_mas_alla_del_sobreacercamiento_no_se_corta(self, sesion, falso, original):
        _, ficha = _tesela_de_la_capa(sesion, original)
        z = ficha["zoom_maximo"] + 3
        x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)
        respuesta = sesion.get(_url_de_tesela(z, x, y), {"ruta": str(original)})
        assert respuesta.status_code == 404
        assert falso.contar("gdalwarp") == 0

    def test_si_gdal_no_deja_nada_la_respuesta_es_502_y_el_original_sigue_igual(
        self, sesion, falso, original
    ):
        url, _ = _tesela_de_la_capa(sesion, original)
        antes = _huella(original)
        falso.escribir = False
        respuesta = sesion.get(url, {"ruta": str(original)})
        assert respuesta.status_code == 502
        assert respuesta.json()["codigo"] == "sin-salida"
        assert _huella(original) == antes

    def test_si_tarda_demasiado_es_504(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        falso.fallar_con = motor.ErrorDeGdal("tardó", "tardo-demasiado")
        respuesta = sesion.get(url, {"ruta": str(original)})
        assert respuesta.status_code == 504
        assert respuesta.json()["codigo"] == "tardo-demasiado"

    def test_el_original_sigue_igual_tras_servir_teselas(self, sesion, falso, original):
        antes = _huella(original)
        url, _ = _tesela_de_la_capa(sesion, original)
        sesion.get(url, {"ruta": str(original)})
        sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        assert _huella(original) == antes
        assert sorted(p.name for p in original.parent.iterdir()) == ["ortofoto.tif"]

    def test_la_tesela_cortada_queda_en_la_cache(self, sesion, falso, original):
        url, _ = _tesela_de_la_capa(sesion, original)
        sesion.get(url, {"ruta": str(original)})
        clave = cache.clave_de(original)
        assert any(cache.carpeta_de(clave).glob("*.png"))


class TestElPunto:
    def _punto(self, sesion, original, lon, lat, valor=False):
        pedido = {"ruta": str(original), "lon": lon, "lat": lat}
        if valor:
            pedido["valor"] = "1"
        return sesion.get(reverse("visor:punto"), pedido)

    def test_el_centro_cae_en_el_centro_de_la_imagen(self, sesion, falso, original):
        _, ficha = _tesela_de_la_capa(sesion, original)
        lon, lat = ficha["centro_4326"]
        datos = self._punto(sesion, original, lon, lat).json()
        assert datos["dentro"] is True
        assert datos["x"] == pytest.approx(345200.0, abs=0.01)
        assert datos["y"] == pytest.approx(6295000.0, abs=0.01)
        assert datos["columna"] == pytest.approx(100.0, abs=0.01)
        assert datos["fila"] == pytest.approx(50.0, abs=0.01)
        assert datos["epsg"] == "32719" and datos["sistema"] == "WGS 84 / UTM zone 19S"
        assert datos["valores"] == [], "sin `valor=1` no se lanza gdallocationinfo"
        assert falso.contar("gdallocationinfo") == 0

    def test_la_esquina_noroeste_es_la_columna_0_fila_0(self, sesion, falso, original):
        _, ficha = _tesela_de_la_capa(sesion, original)
        lon, lat = ficha["esquinas_4326"][0]
        datos = self._punto(sesion, original, lon, lat).json()
        assert datos["columna"] == pytest.approx(0.0, abs=0.01)
        assert datos["fila"] == pytest.approx(0.0, abs=0.01)

    def test_un_punto_fuera_de_la_imagen_lo_dice(self, sesion, falso, original):
        datos = self._punto(sesion, original, -60.0, -20.0).json()
        assert datos["dentro"] is False
        assert datos["columna"] is None or datos["columna"] < 0 or datos["columna"] > 200

    def test_con_valor_pregunta_por_el_pixel_del_original(self, sesion, falso, original):
        from pyproj import Transformer

        # El centro del píxel (130, 20): lejos de un borde, donde un redondeo no cambia de píxel.
        este, norte = 345000.0 + 130.5 * 2.0, 6295100.0 - 20.5 * 2.0
        lon, lat = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True).transform(
            este, norte
        )
        datos = self._punto(sesion, original, lon, lat, valor=True).json()
        assert datos["valores"] == [10.0, 20.0, 30.0]
        _, argumentos = [c for c in falso.llamadas if c[0] == "gdallocationinfo"][0]
        assert argumentos == ["-valonly", str(original), "130", "20"]

    def test_con_valor_fuera_de_la_imagen_no_pregunta(self, sesion, falso, original):
        datos = self._punto(sesion, original, -60.0, -20.0, valor=True).json()
        assert datos["valores"] == []
        assert falso.contar("gdallocationinfo") == 0

    def test_un_valor_sin_dato_sale_como_null(self, sesion, falso, original):
        falso.valores = ["10", "-9999x", "30"]
        _, ficha = _tesela_de_la_capa(sesion, original)
        lon, lat = ficha["centro_4326"]
        datos = self._punto(sesion, original, lon, lat, valor=True).json()
        assert datos["valores"] == [10.0, None, 30.0]

    @pytest.mark.parametrize(
        ("lon", "lat"), [("abc", "0"), ("0", ""), ("181", "0"), ("0", "91"), ("nan", "0"), ("", "")]
    )
    def test_coordenadas_que_no_valen_son_400(self, sesion, falso, original, lon, lat):
        respuesta = sesion.get(
            reverse("visor:punto"), {"ruta": str(original), "lon": lon, "lat": lat}
        )
        assert respuesta.status_code == 400
        assert respuesta.json()["codigo"] == "coordenadas-no-validas"

    def test_acepta_coma_decimal(self, sesion, falso, original):
        respuesta = sesion.get(
            reverse("visor:punto"), {"ruta": str(original), "lon": "-70,6665", "lat": "-33,4733"}
        )
        assert respuesta.status_code == 200

    def test_no_se_guarda_en_cache(self, sesion, falso, original):
        assert "no-store" in self._punto(sesion, original, -70.66, -33.47)["Cache-Control"]


class TestSinTrucosDeRed:
    """**D5: nada sale del equipo.** Ni un CDN, ni una tesela de internet, ni script en línea."""

    def test_el_js_no_nombra_ningun_otro_origen(self):
        js = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")
        codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)  # los comentarios no hacen peticiones
        assert not re.search(r"https?://", codigo)
        assert "//cdn" not in codigo and "WebSocket" not in codigo
        assert "eval(" not in codigo and "new Function" not in codigo
        # Todo lo que pide al servidor es relativo (viene de `data-*`) y va con la sesión.
        assert 'credentials: "same-origin"' in codigo

    def test_el_js_pone_texto_con_textcontent_y_nunca_como_html(self):
        js = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js
        assert "document.write" not in js

    def test_la_plantilla_no_lleva_scripts_ni_estilos_en_linea_ni_manejadores(self):
        html = (RAIZ / "templates" / "visor" / "inicio.html").read_text(encoding="utf-8")
        sin_comentarios = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", html, flags=re.S
        )
        assert not re.search(r"<script(?![^>]*\bsrc=)", sin_comentarios)
        assert not re.search(r"\sstyle=", sin_comentarios)
        assert not re.search(r"\son[a-z]+=", sin_comentarios)
        assert not re.search(r"https?://", sin_comentarios)

    def test_el_js_se_sirve_de_los_estaticos_propios(self, sesion, falso, original):
        cuerpo = sesion.get(reverse("visor:inicio"), {"ruta": str(original)}).content.decode()
        for fuente in re.findall(r'<script[^>]*\bsrc="([^"]+)"', cuerpo):
            assert fuente.startswith("/static/"), fuente
        assert "visor.js" in cuerpo

    def test_nada_se_esconde_en_hover(self):
        for ruta in (
            (RAIZ / "static" / "js" / "visor.js"),
            (RAIZ / "templates" / "visor" / "inicio.html"),
        ):
            texto = ruta.read_text(encoding="utf-8")
            assert "group-hover" not in texto and "opacity-0" not in texto
            assert "mouseover" not in texto and "mouseenter" not in texto

    def test_el_teclado_tiene_lo_que_la_pantalla_promete(self):
        js = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")
        for tecla in (
            "ArrowLeft",
            "ArrowRight",
            "ArrowUp",
            "ArrowDown",
            '"+"',
            '"-"',
            '"0"',
            '"Enter"',
        ):
            assert tecla in js, tecla

    def test_el_csp_de_la_respuesta_sigue_siendo_self(self, sesion, falso, original):
        respuesta = sesion.get(reverse("visor:inicio"), {"ruta": str(original)})
        csp = respuesta.get("Content-Security-Policy", "")
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
        assert "img-src 'self' data:" in csp
        assert "connect-src 'self'" in csp


class TestLaFichaDelArchivoEnConvertir:
    """El enlace «Ver en el mapa» de la ficha: presente con GDAL y apagado, con motivo, sin él."""

    def _ficha(self, sesion, original):
        return sesion.get(reverse("dashboard:inspeccionar"), {"ruta": str(original)})

    def test_el_enlace_de_la_ficha_lleva_la_ruta_sin_escapar_la_del_servidor(self):
        from apps.dashboard import views as vistas_dashboard

        class Falso:
            token = "subida:123"

        class Insp:
            tiff = object()

        enlace = vistas_dashboard._enlace_al_visor(Insp(), Falso())
        assert enlace["url"] == f"{reverse('visor:inicio')}?ruta=subida%3A123"

    def test_si_no_es_un_tiff_no_hay_enlace(self):
        from apps.dashboard import views as vistas_dashboard

        class Insp:
            tiff = None

        assert vistas_dashboard._enlace_al_visor(Insp(), object()) is None

    def test_sin_gdal_el_enlace_sale_apagado_con_motivo(self, monkeypatch):
        from apps.dashboard import views as vistas_dashboard

        monkeypatch.setattr(
            motor,
            "disponibilidad",
            lambda: Disponibilidad.no("sin-gdal", "Esta máquina no tiene GDAL.", sugerencia="x"),
        )

        class Falso:
            token = "/obra/o.tif"

        class Insp:
            tiff = object()

        enlace = vistas_dashboard._enlace_al_visor(Insp(), Falso())
        assert enlace["disponible"] is False
        assert "GDAL" in enlace["motivo"]

    def test_las_respuestas_json_son_utf8_legible(self, sesion, falso, original):
        crudo = sesion.get(reverse("visor:capa"), {"ruta": str(original)}).content.decode()
        assert "\\u" not in crudo, "sin escapes: se lee en una prueba y en un registro"
        assert json.loads(crudo)["sistema"].startswith("WGS 84")
