"""La API de conversión (F16.4): token por persona, permiso aparte, y las reglas de la pantalla.

Cada extremo trae su 401 (sin token o con uno malo) y su 403 (token bueno sin el permiso
`jobs.usar_api`). Lo de otra persona es un 404. Y de punta a punta, **un cliente HTTP de verdad**
(`requests` contra el servidor en marcha de la prueba) encola un GeoTIFF, el despachador lo
convierte y se descarga lo mismo que quedó en disco.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.urls import reverse

from apps.core.api_auth import huella, partes
from apps.core.models import TokenDeApi
from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


def _persona(nombre="ana", *, con_permiso=True):
    usuario = get_user_model().objects.create_user(nombre, password="x" * 20)  # nosec B106
    if con_permiso:
        usuario.user_permissions.add(Permission.objects.get(codename="usar_api"))
    return usuario


def _cabecera(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.fixture
def carpeta(settings, tmp_path):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    registry.limpiar()
    registry.registrar(MotorDeMentira("m", (("geotiff", "cog"),), escribe="cog de mentira"))
    origen = tmp_path / "orto.tif"
    origen.write_bytes(geotiff_minimo())
    yield tmp_path
    registry.limpiar()


EXTREMOS = [
    ("get", "api-trabajos", False),
    ("post", "api-trabajos", False),
    ("get", "api-trabajo", True),
    ("get", "api-trabajo-descarga", True),
    ("get", "api-capacidades", False),
]


def _url(nombre, con_id, pk="11111111-1111-1111-1111-111111111111"):
    return reverse(nombre, args=[pk]) if con_id else reverse(nombre)


class TestElToken:
    def test_solo_se_guarda_la_huella_y_el_token_tiene_su_forma(self):
        ana = _persona()
        registro, token = TokenDeApi.emitir(ana, "pruebas")
        assert partes(token) is not None and token.startswith("ac_")
        assert registro.huella == hashlib.sha256(token.encode()).hexdigest()
        fila = TokenDeApi.objects.filter(pk=registro.pk).values().get()
        assert token not in str(fila), "el token entero no queda en ninguna columna"

    @pytest.mark.parametrize("metodo,nombre,con_id", EXTREMOS)
    def test_sin_token_es_401(self, client, metodo, nombre, con_id):
        respuesta = getattr(client, metodo)(_url(nombre, con_id))
        assert respuesta.status_code in (401, 403)
        if nombre != "api-capacidades":
            assert respuesta.status_code == 401
            assert respuesta["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize("metodo,nombre,con_id", EXTREMOS[:4])
    def test_con_token_y_sin_permiso_es_403(self, client, metodo, nombre, con_id):
        _, token = TokenDeApi.emitir(_persona(con_permiso=False), "x")
        respuesta = getattr(client, metodo)(_url(nombre, con_id), **_cabecera(token))
        assert respuesta.status_code == 403
        assert "jobs.usar_api" in respuesta.json()["detail"]

    @pytest.mark.parametrize(
        "malo",
        [
            "ac_00000000_" + "a" * 43,  # prefijo que no existe
            "otra_cosa",
            "ac_corto_x",
        ],
    )
    def test_un_token_que_no_vale_es_401(self, client, malo):
        _persona()
        respuesta = client.get(reverse("api-trabajos"), **_cabecera(malo))
        assert respuesta.status_code == 401

    def test_el_secreto_cambiado_con_el_mismo_prefijo_no_vale(self, client):
        _, token = TokenDeApi.emitir(_persona(), "x")
        alterado = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        assert client.get(reverse("api-trabajos"), **_cabecera(alterado)).status_code == 401

    def test_un_token_revocado_no_vale(self, client):
        registro, token = TokenDeApi.emitir(_persona(), "x")
        registro.revocado = True
        registro.save()
        assert client.get(reverse("api-trabajos"), **_cabecera(token)).status_code == 401

    def test_una_cuenta_desactivada_no_entra(self, client):
        ana = _persona()
        _, token = TokenDeApi.emitir(ana, "x")
        ana.is_active = False
        ana.save()
        assert client.get(reverse("api-trabajos"), **_cabecera(token)).status_code == 401

    def test_el_uso_se_anota(self, client):
        registro, token = TokenDeApi.emitir(_persona(), "x")
        client.get(reverse("api-trabajos"), **_cabecera(token))
        registro.refresh_from_db()
        assert registro.ultimo_uso is not None


class TestEncolar:
    def _token(self, nombre="ana"):
        return TokenDeApi.emitir(_persona(nombre), "x")[1]

    def test_encola_con_las_reglas_de_la_pantalla(self, client, carpeta):
        token = self._token()
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog"},
            content_type="application/json",
            **_cabecera(token),
        )
        assert respuesta.status_code == 201, respuesta.content
        datos = respuesta.json()
        trabajo = ConversionJob.objects.get(pk=datos["id"])
        assert trabajo.owner.username == "ana" and trabajo.target_format_code == "cog"
        assert datos["estado"] == "queued" and "descarga" not in datos

    def test_una_ruta_fuera_de_las_raices_no_se_mira(self, client, carpeta):
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta.parent), "formato": "cog"},
            content_type="application/json",
            **_cabecera(self._token()),
        )
        assert respuesta.status_code == 400 and not ConversionJob.objects.exists()

    def test_un_par_que_nadie_sabe_hacer_es_422_con_su_codigo(self, client, carpeta):
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "dxf"},
            content_type="application/json",
            **_cabecera(self._token()),
        )
        assert respuesta.status_code == 422 and respuesta.json()["codigo"]

    def test_no_se_acepta_un_crs_encima_del_que_trae_el_archivo(self, client, carpeta):
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog", "crs_declarado": "EPSG:4326"},
            content_type="application/json",
            **_cabecera(self._token()),
        )
        assert respuesta.status_code == 400 and respuesta.json()["codigo"] == "crs-invalido"

    def test_el_trabajo_de_otra_persona_es_404(self, client, carpeta):
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog"},
            content_type="application/json",
            **_cabecera(self._token("ana")),
        )
        pk = respuesta.json()["id"]
        token_beto = self._token("beto")
        for nombre in ("api-trabajo", "api-trabajo-descarga"):
            assert (
                client.get(reverse(nombre, args=[pk]), **_cabecera(token_beto)).status_code == 404
            )
        assert client.get(reverse("api-trabajos"), **_cabecera(token_beto)).json()["trabajos"] == []

    def test_descargar_antes_de_terminar_es_409(self, client, carpeta):
        token = self._token()
        pk = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog"},
            content_type="application/json",
            **_cabecera(token),
        ).json()["id"]
        assert (
            client.get(reverse("api-trabajo-descarga", args=[pk]), **_cabecera(token)).status_code
            == 409
        )


class TestLoQueVinoDeLaRevision:
    def _hecho(self, client, carpeta):
        from apps.jobs import despachador

        token = TokenDeApi.emitir(_persona(), "x")[1]
        pk = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog"},
            content_type="application/json",
            **_cabecera(token),
        ).json()["id"]
        despachador.procesar_una_vez()
        return token, ConversionJob.objects.get(pk=pk)

    def test_la_retencion_efimera_se_aplica_igual_que_en_la_pantalla(
        self, client, carpeta, settings
    ):
        settings.RETENCION = "efimera"
        token, trabajo = self._hecho(client, carpeta)
        assert trabajo.status == "done", trabajo.reason_detail
        respuesta = client.get(
            reverse("api-trabajo-descarga", args=[trabajo.pk]), **_cabecera(token)
        )
        assert respuesta.status_code == 200 and b"".join(respuesta.streaming_content)
        respuesta.close()
        trabajo.refresh_from_db()
        assert trabajo.output_path == "", "entregada entera, se consume"
        otra = client.get(reverse("api-trabajo-descarga", args=[trabajo.pk]), **_cabecera(token))
        assert otra.status_code == 410

    def test_una_salida_reemplazada_o_desaparecida_es_410_y_el_original_queda(
        self, client, carpeta
    ):
        token, trabajo = self._hecho(client, carpeta)
        origen = carpeta / "orto.tif"
        huella_antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        salida = Path(trabajo.output_path)
        salida.write_bytes(b"otra cosa de otro tamano")
        url = reverse("api-trabajo-descarga", args=[trabajo.pk])
        respuesta = client.get(url, **_cabecera(token))
        assert respuesta.status_code == 410 and respuesta.json()["codigo"] == "salida-invalida"
        salida.unlink()
        assert client.get(url, **_cabecera(token)).status_code == 410
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == (
            huella_antes
        )

    def test_capacidades_con_token_pide_el_permiso_y_con_sesion_no(self, client):
        _, token = TokenDeApi.emitir(_persona("sinpermiso", con_permiso=False), "x")
        respuesta = client.get(reverse("api-capacidades"), **_cabecera(token))
        assert respuesta.status_code == 403
        client.force_login(get_user_model().objects.get(username="sinpermiso"))
        assert client.get(reverse("api-capacidades")).status_code == 200

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"ruta": ["a"], "formato": "cog"},
            {"ruta": 5, "formato": "cog"},
        ],
    )
    def test_una_ruta_que_no_es_cadena_es_400(self, client, carpeta, cuerpo):
        token = TokenDeApi.emitir(_persona(), "x")[1]
        respuesta = client.post(
            reverse("api-trabajos"), cuerpo, content_type="application/json", **_cabecera(token)
        )
        assert respuesta.status_code == 400

    @pytest.mark.parametrize("opciones", [{"compresion": ["a", "b"]}, {"x": None}, {"y": {"z": 1}}])
    def test_opciones_que_no_son_valores_simples_son_400_y_no_500(self, client, carpeta, opciones):
        token = TokenDeApi.emitir(_persona(), "x")[1]
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog", "opciones": opciones},
            content_type="application/json",
            **_cabecera(token),
        )
        assert respuesta.status_code == 400 and respuesta.json()["codigo"] == "opcion-invalida"

    def test_coordenadas_locales_solo_en_nubes_y_nunca_encima_de_un_crs(self, client, carpeta):
        token = TokenDeApi.emitir(_persona(), "x")[1]
        respuesta = client.post(
            reverse("api-trabajos"),
            {"ruta": str(carpeta / "orto.tif"), "formato": "cog", "crs_local": True},
            content_type="application/json",
            **_cabecera(token),
        )
        assert respuesta.status_code == 400 and respuesta.json()["codigo"] == "crs-invalido"
        assert not ConversionJob.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_de_punta_a_punta_con_un_cliente_http_de_verdad(live_server, carpeta):
    """`requests` contra el servidor en marcha: encolar, convertir, consultar y descargar."""
    import requests

    from apps.jobs import despachador

    _, token = TokenDeApi.emitir(_persona(), "punta a punta")
    cabecera = {"Authorization": f"Bearer {token}"}
    origen = carpeta / "orto.tif"
    huella_original = hashlib.sha256(origen.read_bytes()).hexdigest()

    creado = requests.post(
        live_server.url + reverse("api-trabajos"),
        json={"ruta": str(origen), "formato": "cog"},
        headers=cabecera,
        timeout=30,
    )
    assert creado.status_code == 201, creado.text
    pk = creado.json()["id"]

    assert despachador.procesar_una_vez() == 1

    estado = requests.get(
        live_server.url + reverse("api-trabajo", args=[pk]), headers=cabecera, timeout=30
    )
    datos = estado.json()
    assert datos["estado"] == "done", datos
    descarga = requests.get(datos["descarga"], headers=cabecera, timeout=30)
    assert descarga.status_code == 200
    salida = Path(ConversionJob.objects.get(pk=pk).output_path)
    assert descarga.content == salida.read_bytes() == b"cog de mentira"
    assert hashlib.sha256(origen.read_bytes()).hexdigest() == huella_original


@pytest.mark.oraculo
@pytest.mark.django_db(transaction=True)
def test_de_punta_a_punta_un_tiff_de_verdad_a_cog_con_gdal(live_server, settings, tmp_path):
    """Con GDAL: un GeoTIFF real pasa a COG por la API y `gdalinfo` (otro lector) lo confirma."""
    import json
    import shutil
    import subprocess

    import requests
    from PIL import Image

    from apps.jobs import despachador
    from apps.raster.motores import MotorGdalRaster, _bin

    if shutil.which("gdalinfo") is None and not Path(_bin("gdalinfo")).is_file():
        pytest.skip("GDAL no está en esta máquina")
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    registry.limpiar()
    registry.registrar(MotorGdalRaster())
    png = tmp_path / "t.png"
    Image.new("L", (64, 64), 128).save(png)
    origen = tmp_path / "orto.tif"
    subprocess.run(  # noqa: S603 - argumentos fijos
        [_bin("gdal_translate"), "-q", "-a_srs", "EPSG:32719",
         "-a_ullr", "495000", "7318900", "495064", "7318836", str(png), str(origen)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip

    _, token = TokenDeApi.emitir(_persona(), "oráculo")
    cabecera = {"Authorization": f"Bearer {token}"}
    creado = requests.post(
        live_server.url + reverse("api-trabajos"),
        json={"ruta": str(origen), "formato": "cog"},
        headers=cabecera,
        timeout=30,
    )
    assert creado.status_code == 201, creado.text
    despachador.procesar_una_vez()
    datos = requests.get(
        live_server.url + reverse("api-trabajo", args=[creado.json()["id"]]),
        headers=cabecera,
        timeout=30,
    ).json()
    assert datos["estado"] == "done", datos
    descargado = tmp_path / "descargado.tif"
    descargado.write_bytes(requests.get(datos["descarga"], headers=cabecera, timeout=60).content)
    info = json.loads(
        subprocess.run(  # noqa: S603
            [_bin("gdalinfo"), "-json", str(descargado)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout  # fmt: skip
    )
    assert info["size"] == [64, 64]
    assert info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"
    registry.limpiar()


def test_la_orden_emite_y_revoca(capsys):
    _persona("ana", con_permiso=False)
    call_command("emitir_token_api", "ana", "--nombre", "script")
    salida = capsys.readouterr().out
    token = next(linea for linea in salida.splitlines() if linea.startswith("ac_"))
    registro = TokenDeApi.objects.get()
    assert registro.huella == huella(token) and "jobs.usar_api" in salida
    call_command("emitir_token_api", "--revocar", registro.prefijo)
    registro.refresh_from_db()
    assert registro.revocado
