"""El mapa base propio (F19.5, D5): de la casa, comprobado en cada petición, sin rutas hacia fuera.

Con un GDAL de mentira (lo que se mide es el pegamento: configuración, raíces permitidas, permisos,
caché HTTP y que el original no se toca). Lo que dice GDAL de una tesela del fondo lo mide la prueba
`oraculo` de `test_capas_oraculo.py`.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

import pytest
from django.urls import reverse

from apps.core.entrada import EntradaNoPermitida
from apps.engines.base import Disponibilidad
from apps.jobs.motivos import MOTIVOS
from apps.visor import fondo, mercator, motor
from apps.visor.testing import crear_vuelo_sintetico

pytestmark = pytest.mark.django_db


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _capas_de(cuerpo: str) -> list[dict]:
    """Las capas que la pantalla le declara al JavaScript (`data-capas`)."""
    crudo = re.search(r'data-capas="([^"]*)"', cuerpo)
    assert crudo, "la pantalla trae la lista de capas"
    return json.loads(html.unescape(crudo.group(1)))


@pytest.fixture
def mosaico(raiz_de_obra):
    ruta = raiz_de_obra / "mosaico.tif"
    ruta.write_bytes(b"II*\x00" + b"mosaico sintetico" * 300)
    return ruta


class TestLaConfiguracion:
    def test_sin_configurar_no_hay_fondos(self, raiz_de_obra, settings):
        for vacio in ("", "   ", ";;"):
            settings.VISOR_MAPA_BASE = vacio
            assert fondo.configurados() == []

    def test_una_ruta_sola_toma_el_nombre_del_archivo(self, mosaico, settings):
        settings.VISOR_MAPA_BASE = str(mosaico)
        (f,) = fondo.configurados()
        assert f.nombre == "mosaico" and f.usable and f.ruta == mosaico.resolve()
        assert f.token == "fondo:0" and f.indice == 0

    def test_varias_con_nombre_y_separadas_por_punto_y_coma(self, mosaico, raiz_de_obra, settings):
        otra = raiz_de_obra / "ortofoto-2026.tif"
        otra.write_bytes(b"II*\x00x")
        settings.VISOR_MAPA_BASE = f"Mosaico de la obra={mosaico}; {otra}"
        a, b = fondo.configurados()
        assert (a.nombre, a.indice) == ("Mosaico de la obra", 0)
        assert (b.nombre, b.indice) == ("ortofoto-2026", 1)
        assert a.usable and b.usable

    def test_un_igual_dentro_de_la_ruta_no_es_un_nombre(self, raiz_de_obra, settings):
        carpeta = raiz_de_obra / "vuelo=1"
        carpeta.mkdir()
        archivo = carpeta / "m.tif"
        archivo.write_bytes(b"II*\x00x")
        settings.VISOR_MAPA_BASE = str(archivo)
        (f,) = fondo.configurados()
        assert f.nombre == "m" and f.usable

    def test_no_se_aceptan_mas_de_ocho(self, mosaico, settings):
        settings.VISOR_MAPA_BASE = ";".join(f"N{i}={mosaico}" for i in range(12))
        assert len(fondo.configurados()) == fondo.MAXIMO_DE_FONDOS


class TestUnFondoQueNoSirveSeMuestraApagadoConSuMotivo:
    def test_fuera_de_las_raices_permitidas(self, mosaico, tmp_path, settings):
        fuera = tmp_path / "secreto.tif"
        fuera.write_bytes(b"II*\x00x")
        settings.VISOR_MAPA_BASE = f"Ajeno={fuera}"
        (f,) = fondo.configurados()
        assert not f.usable and f.ruta is None
        assert "fuera de las carpetas permitidas" in f.detalle
        assert str(fuera) not in f.detalle and "secreto" not in f.detalle

    def test_que_no_es_un_geotiff(self, raiz_de_obra, settings):
        imagen = raiz_de_obra / "mapa.png"
        imagen.write_bytes(b"x")
        settings.VISOR_MAPA_BASE = str(imagen)
        (f,) = fondo.configurados()
        assert not f.usable and "GeoTIFF" in f.detalle

    def test_un_vrt_no_pasa_porque_puede_apuntar_a_internet(self, raiz_de_obra, settings):
        vrt = raiz_de_obra / "remoto.vrt"
        vrt.write_text("<VRTDataset/>", encoding="utf-8")
        settings.VISOR_MAPA_BASE = str(vrt)
        (f,) = fondo.configurados()
        assert not f.usable

    def test_que_ya_no_esta(self, raiz_de_obra, settings):
        settings.VISOR_MAPA_BASE = str(raiz_de_obra / "no-esta.tif")
        (f,) = fondo.configurados()
        assert not f.usable and "ya no está" in f.detalle

    def test_una_direccion_de_internet_no_es_una_ruta_y_no_sirve(self, settings):
        """Aquí no hay forma de configurar un servidor de teselas (D5)."""
        settings.VISOR_MAPA_BASE = "https://tile.example.org/{z}/{x}/{y}.png"
        for f in fondo.configurados():
            assert not f.usable

    def test_el_motivo_esta_en_el_catalogo_con_codigo_estable(self):
        assert fondo.CODIGO_NO_VALIDO == "mapa-base-no-valido"
        assert fondo.CODIGO_NO_VALIDO in MOTIVOS
        assert MOTIVOS[fondo.CODIGO_NO_VALIDO].sugerencia


class TestCualSeVe:
    def test_sin_pedir_ninguno_el_primero_de_la_casa_que_se_pueda_usar(
        self, mosaico, raiz_de_obra, settings
    ):
        settings.VISOR_MAPA_BASE = f"Roto={raiz_de_obra / 'x.png'};Bueno={mosaico}"
        fondos = fondo.configurados()
        assert fondo.elegir(None, fondos).nombre == "Bueno"
        assert fondo.elegir("", fondos).nombre == "Bueno"

    def test_ninguno_es_la_reticula(self, mosaico, settings):
        settings.VISOR_MAPA_BASE = str(mosaico)
        assert fondo.elegir(fondo.SIN_FONDO, fondo.configurados()) is None
        assert fondo.elegir("NINGUNO", fondo.configurados()) is None

    def test_uno_pedido_por_su_posicion(self, mosaico, raiz_de_obra, settings):
        otra = raiz_de_obra / "otra.tif"
        otra.write_bytes(b"II*\x00x")
        settings.VISOR_MAPA_BASE = f"A={mosaico};B={otra}"
        assert fondo.elegir("1", fondo.configurados()).nombre == "B"

    @pytest.mark.parametrize("pedido", ["7", "-1", "abc", "1.5", "0; DROP", "../x"])
    def test_uno_que_no_existe_no_se_sustituye_por_otro(self, pedido, mosaico, settings):
        settings.VISOR_MAPA_BASE = str(mosaico)
        assert fondo.elegir(pedido, fondo.configurados()) is None

    def test_uno_pedido_que_no_sirve_tampoco_se_sustituye(self, mosaico, raiz_de_obra, settings):
        settings.VISOR_MAPA_BASE = f"Roto={raiz_de_obra / 'x.png'};Bueno={mosaico}"
        assert fondo.elegir("0", fondo.configurados()) is None


class TestElToken:
    def test_resuelve_a_la_ruta_de_la_casa(self, mosaico, settings):
        settings.VISOR_MAPA_BASE = f"Mosaico={mosaico}"
        origen = fondo.resolver("fondo:0")
        assert origen.ruta == mosaico.resolve() and origen.nombre == "Mosaico"

    @pytest.mark.parametrize("token", ["fondo:3", "fondo:-1", "fondo:", "fondo:x", "fondo:0;1"])
    def test_uno_que_no_existe_es_403_con_su_codigo_y_sin_la_ruta(self, token, mosaico, settings):
        settings.VISOR_MAPA_BASE = str(mosaico)
        with pytest.raises(EntradaNoPermitida) as caido:
            fondo.resolver(token)
        assert caido.value.codigo == "mapa-base-no-valido"
        assert str(mosaico) not in str(caido.value)

    def test_si_la_ruta_sale_de_las_raices_despues_deja_de_servir(
        self, mosaico, tmp_path, settings
    ):
        settings.VISOR_MAPA_BASE = str(mosaico)
        assert fondo.resolver("fondo:0")
        settings.RAICES_PERMITIDAS = str(tmp_path / "otra-carpeta")  # el administrador la cambió
        with pytest.raises(EntradaNoPermitida):
            fondo.resolver("fondo:0")


class TestPorHttp:
    def test_la_ficha_y_la_tesela_del_fondo_salen_de_su_posicion_y_no_de_su_ruta(
        self, con_sesion, gdal_de_mentira, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = f"Mosaico={mosaico}"
        antes = _huella(mosaico)

        ficha = con_sesion.get(reverse("visor:capa"), {"ruta": "fondo:0"})
        assert ficha.status_code == 200 and ficha.json()["dibujable"] is True
        assert str(mosaico) not in ficha.content.decode()

        z = ficha.json()["zoom_maximo"]
        x, y = mercator.tesela_de_lonlat(*ficha.json()["centro_4326"], z)
        tesela = con_sesion.get(reverse("visor:tesela", args=[z, x, y]), {"ruta": "fondo:0"})
        assert tesela.status_code == 200 and tesela["Content-Type"] == "image/png"
        assert tesela["Cache-Control"].startswith("private")
        asegurada = con_sesion.get(
            reverse("visor:tesela", args=[z, x, y]),
            {"ruta": "fondo:0"},
            HTTP_IF_NONE_MATCH=tesela["ETag"],
        )
        assert asegurada.status_code == 304
        assert _huella(mosaico) == antes, "el original no se toca (regla 5)"

    def test_un_fondo_que_no_existe_es_403_y_ni_se_le_pregunta_a_gdal(
        self, con_sesion, gdal_de_mentira, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = str(mosaico)
        for nombre, extra in (("visor:capa", {}), ("visor:punto", {"lon": 0, "lat": 0})):
            respuesta = con_sesion.get(reverse(nombre), {"ruta": "fondo:9", **extra})
            assert respuesta.status_code == 403, nombre
            assert respuesta.json()["codigo"] == "mapa-base-no-valido"
        respuesta = con_sesion.get(reverse("visor:tesela", args=[3, 2, 2]), {"ruta": "fondo:9"})
        assert respuesta.status_code == 403
        assert gdal_de_mentira.llamadas == []

    def test_un_fondo_mueve_lo_mismo_que_exige_sesion(self, client, mosaico, settings):
        settings.VISOR_MAPA_BASE = str(mosaico)
        respuesta = client.get(reverse("visor:capa"), {"ruta": "fondo:0"})
        assert respuesta.status_code == 302 and reverse("login") in respuesta["Location"]


class TestEnLaPantalla:
    def test_con_un_fondo_configurado_es_la_capa_de_abajo_y_no_lleva_su_ruta(
        self, con_sesion, gdal_de_mentira, tif_de_obra, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = f"Mosaico de la obra={mosaico}"
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra)}
        ).content.decode()
        capas = _capas_de(cuerpo)
        assert [c["tipo"] for c in capas] == ["raster", "fondo"], "el fondo queda debajo"
        assert capas[1]["token"] == "fondo:0" and capas[1]["id"] == "fondo"
        assert "Mosaico de la obra" in capas[1]["nombre"]
        assert str(mosaico) not in cuerpo, "la ruta de la casa no sale al navegador"
        assert capas[1]["fuente"] == {"param": "fondo", "poner": "ninguno"}

    def test_ninguno_deja_solo_la_reticula(
        self, con_sesion, gdal_de_mentira, tif_de_obra, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = str(mosaico)
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "fondo": "ninguno"}
        ).content.decode()
        assert [c["tipo"] for c in _capas_de(cuerpo)] == ["raster"]
        assert 'value="ninguno" selected' in cuerpo

    def test_sin_configurar_dice_como_configurarlo_y_se_ve_la_reticula(
        self, con_sesion, gdal_de_mentira, tif_de_obra
    ):
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra)}
        ).content.decode()
        assert [c["tipo"] for c in _capas_de(cuerpo)] == ["raster"]
        assert 'data-motivo="sin-mapa-base"' in cuerpo
        assert "AEROCONVERT_VISOR_MAPA_BASE" in cuerpo
        assert "Nunca se piden teselas de internet" in cuerpo

    def test_uno_roto_se_lista_apagado_con_su_motivo(
        self, con_sesion, gdal_de_mentira, tif_de_obra, raiz_de_obra, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = f"Roto={raiz_de_obra / 'x.png'};Bueno={mosaico}"
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra)}
        ).content.decode()
        assert re.search(
            r"<option value=\"0\"[^>]* disabled>Roto \(no disponible: Solo se admiten", cuerpo
        )
        assert '<option value="1" selected>Bueno' in cuerpo
        assert str(raiz_de_obra / "x.png") not in cuerpo

    def test_pedir_uno_que_no_sirve_no_lo_cambia_por_otro(
        self, con_sesion, gdal_de_mentira, tif_de_obra, raiz_de_obra, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = f"Roto={raiz_de_obra / 'x.png'};Bueno={mosaico}"
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "fondo": "0"}
        ).content.decode()
        assert [c["tipo"] for c in _capas_de(cuerpo)] == ["raster"]

    def test_el_formulario_de_cambiar_conserva_lo_que_ya_hay(
        self, con_sesion, gdal_de_mentira, tif_de_obra, mosaico, settings
    ):
        settings.VISOR_MAPA_BASE = str(mosaico)
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "e": "fondo:40:0"}
        ).content.decode()
        assert f'name="ruta" value="{tif_de_obra}"' in cuerpo
        assert 'name="e" id="capas-estado" value="fondo:40:0"' in cuerpo
        assert 'name="fondo" id="capas-fondo"' in cuerpo

    def test_junto_a_una_imagen_y_a_un_vuelo_el_fondo_queda_debajo_de_todo(
        self, con_sesion, gdal_de_mentira, tif_de_obra, mosaico, raiz_de_obra, persona, settings
    ):
        settings.VISOR_MAPA_BASE = f"Casa={mosaico}"
        vuelo = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        otra = raiz_de_obra / "otra.tif"
        otra.write_bytes(b"II*\x00otra")
        cuerpo = con_sesion.get(
            reverse("visor:inicio"),
            {"ruta": str(tif_de_obra), "capa": str(otra), "vuelo": str(vuelo.pk)},
        ).content.decode()
        assert [c["tipo"] for c in _capas_de(cuerpo)] == [
            "vuelo-control",
            "vuelo-fotos",
            "vuelo-trayectoria",
            "raster",
            "raster",
            "fondo",
        ]

    def test_un_mapa_solo_de_vuelos_sin_gdal_dice_que_el_fondo_esta_apagado(
        self, con_sesion, persona, raiz_de_obra, mosaico, settings, monkeypatch
    ):
        settings.VISOR_MAPA_BASE = f"Casa={mosaico}"
        vuelo = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        monkeypatch.setattr(
            motor,
            "disponibilidad",
            lambda: Disponibilidad.no("sin-gdal", "Sin GDAL.", sugerencia="Instálelo."),
        )
        cuerpo = con_sesion.get(reverse("visor:inicio"), {"vuelo": str(vuelo.pk)}).content.decode()
        assert "ni un mapa de fondo" in cuerpo and "Instálelo." in cuerpo
        assert [c["tipo"] for c in _capas_de(cuerpo)][-1] != "fondo", "sin GDAL no hay fondo"
        assert 'name="fondo" id="capas-fondo" disabled' in cuerpo
