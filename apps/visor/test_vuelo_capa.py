"""Un vuelo propio como capas del mapa (F19.3): dueño, proyección, motivos y pantalla.

Sin GDAL. El vuelo es sintético: cuatro disparos y un recorrido en puntos del GeoTIFF de prueba cuya
posición **midió `gdaltransform`** (`testing.PUNTOS_DE_GDAL`, GDAL 3.12.4, 2026-10-09). La
proyección a Web Mercator se compara con esas cifras, no con nuestra cuenta.
"""

from __future__ import annotations

import html
import json
import re
import uuid

import pytest
from django.urls import reverse
from PIL import Image

from apps.engines.base import Disponibilidad
from apps.jobs.models import ConversionJob
from apps.visor import capas, motor, vuelo
from apps.visor.testing import PUNTOS_DE_GDAL, crear_vuelo_sintetico

pytestmark = pytest.mark.django_db

#: Un milímetro y medio de tolerancia: PROJ y la fórmula esférica coinciden a menos de eso.
TOLERANCIA_M = 0.002


def _capas_de(cuerpo: str) -> list[dict]:
    crudo = re.search(r'data-capas="([^"]*)"', cuerpo)
    assert crudo, "la pantalla trae la lista de capas"
    return json.loads(html.unescape(crudo.group(1)))


@pytest.fixture
def un_vuelo(persona, raiz_de_obra):
    return crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")


def _datos(sesion, job):
    return sesion.get(reverse("visor:vuelo", args=[job.pk]))


class TestSesionYMetodo:
    def test_sin_sesion_va_a_la_entrada(self, client, un_vuelo):
        respuesta = client.get(reverse("visor:vuelo", args=[un_vuelo.pk]))
        assert respuesta.status_code == 302 and reverse("login") in respuesta["Location"]

    def test_es_de_solo_lectura(self, con_sesion, un_vuelo):
        url = reverse("visor:vuelo", args=[un_vuelo.pk])
        assert con_sesion.post(url).status_code == 405
        assert con_sesion.put(url).status_code == 405
        assert con_sesion.delete(url).status_code == 405

    def test_no_se_guarda_en_cachés_compartidas(self, con_sesion, un_vuelo):
        assert "no-store" in _datos(con_sesion, un_vuelo)["Cache-Control"]


class TestDeQuienEs:
    """404 para todo lo que no es **suyo**, igual que el visor del vuelo: un 403 confirmaría que
    el identificador existe."""

    def test_de_otra_persona_es_404_y_no_dice_que_existe(
        self, con_sesion, otra_persona, raiz_de_obra
    ):
        ajeno = crear_vuelo_sintetico(otra_persona, raiz_de_obra / "salidas")
        respuesta = _datos(con_sesion, ajeno)
        inexistente = con_sesion.get(reverse("visor:vuelo", args=[uuid.uuid4()]))
        assert respuesta.status_code == 404 == inexistente.status_code
        assert respuesta.json() == inexistente.json()
        assert respuesta.json()["codigo"] == "vuelo-no-encontrado"

    def test_de_otra_herramienta_es_404(self, con_sesion, persona, raiz_de_obra):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        ConversionJob.objects.filter(pk=job.pk).update(herramienta="unir_pdf")
        assert _datos(con_sesion, job).status_code == 404

    def test_sin_terminar_es_404(self, con_sesion, persona, raiz_de_obra):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        ConversionJob.objects.filter(pk=job.pk).update(status="running")
        assert _datos(con_sesion, job).status_code == 404

    def test_con_el_zip_borrado_es_404(self, con_sesion, un_vuelo):
        import os

        os.remove(un_vuelo.output_path)
        assert _datos(con_sesion, un_vuelo).status_code == 404

    def test_con_un_zip_sin_vuelo_json_es_404_con_su_codigo(self, con_sesion, un_vuelo):
        import zipfile

        with zipfile.ZipFile(un_vuelo.output_path, "w") as paquete:
            paquete.writestr("otra-cosa.txt", "x")
        respuesta = _datos(con_sesion, un_vuelo)
        assert respuesta.status_code == 404 and respuesta.json()["codigo"] == "vuelo-ilegible"

    def test_la_pantalla_con_un_vuelo_ajeno_o_malformado_es_404(
        self, con_sesion, otra_persona, raiz_de_obra
    ):
        ajeno = crear_vuelo_sintetico(otra_persona, raiz_de_obra / "salidas")
        assert con_sesion.get(reverse("visor:inicio"), {"vuelo": str(ajeno.pk)}).status_code == 404
        assert con_sesion.get(reverse("visor:inicio"), {"vuelo": "no-es-un-id"}).status_code == 404
        assert (
            con_sesion.get(reverse("visor:inicio"), {"vuelo": str(uuid.uuid4())}).status_code == 404
        )

    def test_la_miniatura_y_la_ficha_que_da_el_mapa_son_las_del_vuelo_con_su_dueno(
        self, con_sesion, client, persona, otra_persona, raiz_de_obra
    ):
        """El mapa **no** reimplementa la miniatura: apunta a las vistas del vuelo, que comprueban
        dueño y carpeta. De otra persona, esas mismas direcciones dan 404."""
        fotos = raiz_de_obra / "fotos"
        fotos.mkdir()
        for n in range(1, 5):
            Image.new("RGB", (64, 48), (30, 90, 160)).save(fotos / f"DJI_{n:04d}.JPG", "JPEG")
        propio = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas", carpeta_de_fotos=fotos)
        urls = _datos(con_sesion, propio).json()["urls"]
        assert urls["miniatura"].endswith("/foto/{n}/")
        assert urls["ficha"].endswith("/foto/{n}/ficha/")

        miniatura = con_sesion.get(urls["miniatura"].replace("{n}", "2"))
        assert miniatura.status_code == 200 and miniatura["Content-Type"] == "image/jpeg"

        client.logout()
        client.force_login(otra_persona)
        assert client.get(urls["miniatura"].replace("{n}", "2")).status_code == 404
        assert client.get(urls["ficha"].replace("{n}", "2")).status_code == 404


class TestLaProyeccionContraGdal:
    def test_las_fotos_estan_donde_gdaltransform_las_puso(self, con_sesion, un_vuelo):
        puntos = _datos(con_sesion, un_vuelo).json()["fotos"]["puntos"]
        assert [p["n"] for p in puntos] == [1, 2, 3, 4]
        for foto, medido in zip(puntos, PUNTOS_DE_GDAL[1:5], strict=True):
            assert foto["mx"] == pytest.approx(medido[4], abs=TOLERANCIA_M)
            assert foto["my"] == pytest.approx(medido[5], abs=TOLERANCIA_M)
            assert foto["lon"] == pytest.approx(medido[2], abs=1e-12)
            assert foto["lat"] == pytest.approx(medido[3], abs=1e-12)

    def test_la_trayectoria_pasa_por_los_puntos_que_midio_gdaltransform(self, con_sesion, un_vuelo):
        """Solo trae Este y Norte relativos al origen: se vuelven grados con PROJ y de ahí a Web
        Mercator. Cada punto debe caer donde `gdaltransform` dijo que cae el suyo."""
        recorrido = _datos(con_sesion, un_vuelo).json()["trayectoria"]
        assert recorrido["disponible"] is True and len(recorrido["puntos"]) == 5
        for (mx, my), medido in zip(recorrido["puntos"], PUNTOS_DE_GDAL[:5], strict=True):
            assert mx == pytest.approx(medido[4], abs=TOLERANCIA_M)
            assert my == pytest.approx(medido[5], abs=TOLERANCIA_M)

    def test_la_caja_cubre_todo_lo_que_se_dibuja(self, con_sesion, un_vuelo):
        datos = _datos(con_sesion, un_vuelo).json()
        x0, y0, x1, y1 = datos["caja_3857"]
        todos = [*datos["trayectoria"]["puntos"]] + [
            [p["mx"], p["my"]] for p in datos["fotos"]["puntos"]
        ]
        assert x0 == min(p[0] for p in todos) and x1 == max(p[0] for p in todos)
        assert y0 == min(p[1] for p in todos) and y1 == max(p[1] for p in todos)
        assert x0 == pytest.approx(PUNTOS_DE_GDAL[0][4], abs=TOLERANCIA_M)  # el oeste
        assert y0 == pytest.approx(PUNTOS_DE_GDAL[4][5], abs=TOLERANCIA_M)  # el sur

    def test_dice_el_sistema_que_uso(self, con_sesion, un_vuelo):
        datos = _datos(con_sesion, un_vuelo).json()
        assert datos["sistema"] == {"epsg": 32719, "nombre": "WGS 84 / UTM zone 19S"}
        assert datos["dibujable"] is True and datos["nombre"].startswith("vuelo")


class TestLasFotos:
    def test_cada_calidad_su_clase_y_la_que_no_se_informa_se_dice(self, con_sesion, un_vuelo):
        puntos = _datos(con_sesion, un_vuelo).json()["fotos"]["puntos"]
        assert [p["clase"] for p in puntos] == ["buena", "flotante", "simple", "sin"]
        assert [p["calidad"] for p in puntos] == ["PPK", "flotante", "simple", ""]

    def test_una_sin_posicion_no_se_dibuja_y_se_cuenta(self, con_sesion, un_vuelo):
        fotos = _datos(con_sesion, un_vuelo).json()["fotos"]
        assert fotos["sin_posicion"] == 1
        assert 5 not in [p["n"] for p in fotos["puntos"]]

    def test_las_posiciones_que_no_son_numeros_se_descartan(
        self, persona, raiz_de_obra, con_sesion, monkeypatch
    ):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        datos = vuelo.leer_datos(job)
        datos["fotos"][0]["lat"] = float("nan")
        datos["fotos"][1]["lon"] = "x"
        datos["fotos"][2]["lat"] = 89.0  # Web Mercator no llega
        datos["fotos"][3]["lon"] = 400.0
        respuesta = vuelo.para_el_mapa(job, datos)
        assert respuesta["fotos"]["disponible"] is False
        assert respuesta["fotos"]["codigo"] == "vuelo-sin-fotos-con-posicion"
        assert respuesta["fotos"]["sin_posicion"] == 5


class TestUnVueloSinSistemaNoSeDibuja:
    """Regla 3: el sistema no se adivina. Sin él, ubicar el vuelo sería inventar dónde voló."""

    @pytest.mark.parametrize("epsg", [None, 0, -1, "32719", True, 99999999])
    def test_sin_un_epsg_que_se_conozca_no_se_dibuja_nada(
        self, epsg, persona, raiz_de_obra, con_sesion
    ):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas", epsg=epsg)
        datos = _datos(con_sesion, job).json()
        assert datos["dibujable"] is False and datos["codigo"] == "vuelo-sin-crs"
        assert datos["caja_3857"] is None
        for parte in ("trayectoria", "fotos", "control"):
            assert datos[parte]["disponible"] is False and datos[parte]["puntos"] == []
            assert datos[parte]["codigo"] == "vuelo-sin-crs"
        assert "inventar" in datos["mensaje"] and datos["sugerencia"]
        # Y no sugiere «el más probable»: ningún EPSG en el mensaje.
        assert not re.search(r"EPSG|32719|UTM", datos["mensaje"] + datos["sugerencia"])

    def test_sin_el_bloque_sistema_tampoco(self, persona, raiz_de_obra):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        datos = vuelo.leer_datos(job)
        del datos["sistema"]
        assert vuelo.para_el_mapa(job, datos)["codigo"] == "vuelo-sin-crs"

    def test_sin_origen_la_trayectoria_se_apaga_pero_las_fotos_siguen(self, persona, raiz_de_obra):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        datos = vuelo.leer_datos(job)
        del datos["origen"]
        respuesta = vuelo.para_el_mapa(job, datos)
        assert respuesta["trayectoria"]["codigo"] == "vuelo-sin-crs"
        assert respuesta["fotos"]["disponible"] is True


class TestLoQueUnVueloNoTraeSeDiceYNoSeInventa:
    def test_con_rtk_no_hay_recorrido_y_no_se_une_las_fotos(
        self, persona, raiz_de_obra, con_sesion
    ):
        job = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas", con_trayectoria=False)
        datos = _datos(con_sesion, job).json()
        assert datos["trayectoria"] == {
            "disponible": False,
            "puntos": [],
            "codigo": "vuelo-sin-trayectoria",
            "mensaje": datos["trayectoria"]["mensaje"],
            "sugerencia": datos["trayectoria"]["sugerencia"],
        }
        assert "inventar" in datos["trayectoria"]["mensaje"]
        assert datos["fotos"]["disponible"] is True and datos["dibujable"] is True

    def test_sin_puntos_de_control_la_capa_dice_que_no_los_trae(self, con_sesion, un_vuelo):
        control = _datos(con_sesion, un_vuelo).json()["control"]
        assert control["disponible"] is False
        assert control["codigo"] == "vuelo-sin-puntos-de-control"

    def test_con_puntos_de_control_se_proyectan(self, persona, raiz_de_obra, con_sesion):
        medido = PUNTOS_DE_GDAL[5]
        job = crear_vuelo_sintetico(
            persona,
            raiz_de_obra / "salidas",
            puntos_de_control=[
                {"nombre": "PC-1", "lon": medido[2], "lat": medido[3]},
                {"nombre": "sin posición"},
                "basura",
            ],
        )
        control = _datos(con_sesion, job).json()["control"]
        assert control["disponible"] is True and len(control["puntos"]) == 1
        punto = control["puntos"][0]
        assert punto["nombre"] == "PC-1"
        assert punto["mx"] == pytest.approx(medido[4], abs=TOLERANCIA_M)
        assert punto["my"] == pytest.approx(medido[5], abs=TOLERANCIA_M)

    def test_los_motivos_estan_en_el_catalogo(self):
        from apps.jobs.motivos import MOTIVOS

        for codigo in (
            "vuelo-sin-crs",
            "vuelo-sin-trayectoria",
            "vuelo-sin-puntos-de-control",
            "vuelo-sin-fotos-con-posicion",
            "vuelo-no-encontrado",
            "vuelo-ilegible",
        ):
            assert codigo in MOTIVOS and MOTIVOS[codigo].mensaje


class TestLaPantalla:
    def test_un_mapa_solo_de_vuelos_no_necesita_gdal(self, con_sesion, un_vuelo, monkeypatch):
        monkeypatch.setattr(
            motor,
            "disponibilidad",
            lambda: Disponibilidad.no("sin-gdal", "Sin GDAL.", sugerencia="Instálelo."),
        )
        respuesta = con_sesion.get(reverse("visor:inicio"), {"vuelo": str(un_vuelo.pk)})
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200 and 'id="mapa-lienzo"' in cuerpo
        assert "Esquinas y centro" not in cuerpo, "no hay imagen principal"
        assert "Sin GDAL no se pueden sumar imágenes" in cuerpo and "Sin GDAL." in cuerpo
        assert "static/js/visor.js" in cuerpo and "Foto del vuelo" in cuerpo

    def test_trae_las_tres_partes_y_la_leyenda_de_calidad_escrita(
        self, con_sesion, gdal_de_mentira, un_vuelo
    ):
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"vuelo": str(un_vuelo.pk)}
        ).content.decode()
        partes = _capas_de(cuerpo)
        assert [c["tipo"] for c in partes] == [
            capas.VUELO_CONTROL,
            capas.VUELO_FOTOS,
            capas.VUELO_TRAYECTORIA,
        ]
        assert [c["id"] for c in partes] == [
            capas.id_de_vuelo(un_vuelo.pk, "c"),
            capas.id_de_vuelo(un_vuelo.pk, "f"),
            capas.id_de_vuelo(un_vuelo.pk, "t"),
        ]
        assert all(c["datos"] == reverse("visor:vuelo", args=[un_vuelo.pk]) for c in partes)
        # Solo la fila de las fotos quita el vuelo entero.
        assert [bool(c.get("fuente")) for c in partes] == [False, True, False]
        # La calidad no va solo en color: está escrita.
        for texto in (
            "Foto PPK o fija",
            "Foto flotante",
            "Foto simple",
            "Foto sin calidad informada",
        ):
            assert texto in cuerpo
        assert "Punto de control" in cuerpo and "Trayectoria" in cuerpo

    def test_el_orden_y_la_transparencia_guardados_vuelven_en_la_pantalla(
        self, con_sesion, gdal_de_mentira, un_vuelo
    ):
        f, t = capas.id_de_vuelo(un_vuelo.pk, "f"), capas.id_de_vuelo(un_vuelo.pk, "t")
        c = capas.id_de_vuelo(un_vuelo.pk, "c")
        cuerpo = con_sesion.get(
            reverse("visor:inicio"),
            {"vuelo": str(un_vuelo.pk), "e": f"{t}:0:1,{f}:60:1,{c}:100:0"},
        ).content.decode()
        partes = _capas_de(cuerpo)
        assert [x["id"] for x in partes] == [t, f, c]
        assert [(x["transparencia"], x["visible"]) for x in partes] == [
            (0, True),
            (60, True),
            (100, False),
        ]

    def test_un_estado_inventado_no_abre_nada_ni_rompe(
        self, con_sesion, gdal_de_mentira, un_vuelo, persona
    ):
        cuerpo = con_sesion.get(
            reverse("visor:inicio"),
            {"vuelo": str(un_vuelo.pk), "e": "rINVENTADA:0:1,vffffffc:5:1,../../x:1:1"},
        ).content.decode()
        assert len(_capas_de(cuerpo)) == 3
        assert "rINVENTADA" not in cuerpo.split("data-capas=")[1].split(">")[0]

    def test_junto_a_una_imagen_el_vuelo_va_encima(
        self, con_sesion, gdal_de_mentira, un_vuelo, tif_de_obra, raiz_de_obra
    ):
        otra = raiz_de_obra / "otra.tif"
        otra.write_bytes(b"II*\x00otra")
        cuerpo = con_sesion.get(
            reverse("visor:inicio"),
            {"ruta": str(tif_de_obra), "capa": str(otra), "vuelo": str(un_vuelo.pk)},
        ).content.decode()
        orden = [c["tipo"] for c in _capas_de(cuerpo)]
        assert orden == [
            "vuelo-control",
            "vuelo-fotos",
            "vuelo-trayectoria",
            "raster",
            "raster",
        ]
        rasters = [c for c in _capas_de(cuerpo) if c["tipo"] == "raster"]
        assert [c["principal"] for c in rasters] == [True, False]
        assert rasters[0]["fuente"] == {"param": "ruta", "valor": str(tif_de_obra)}
        assert rasters[1]["fuente"] == {"param": "capa", "valor": str(otra)}

    def test_una_imagen_extra_fuera_de_las_raices_es_403(
        self, con_sesion, gdal_de_mentira, tif_de_obra, tmp_path
    ):
        ajena = tmp_path / "secreto.tif"
        ajena.write_bytes(b"II*\x00x")
        respuesta = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "capa": str(ajena)}
        )
        assert respuesta.status_code == 403
        assert gdal_de_mentira.llamadas == [] or all(
            "secreto" not in " ".join(a) for _, a in gdal_de_mentira.llamadas
        )

    def test_una_imagen_extra_que_no_es_un_tiff_es_422(
        self, con_sesion, gdal_de_mentira, tif_de_obra, raiz_de_obra
    ):
        vrt = raiz_de_obra / "remoto.vrt"
        vrt.write_text("<VRTDataset/>", encoding="utf-8")
        respuesta = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "capa": str(vrt)}
        )
        assert respuesta.status_code == 422

    def test_lo_repetido_cuenta_una_vez_y_lo_que_sobra_se_dice(
        self, con_sesion, gdal_de_mentira, tif_de_obra, raiz_de_obra, persona
    ):
        extras = []
        for i in range(8):
            ruta = raiz_de_obra / f"extra{i}.tif"
            ruta.write_bytes(b"II*\x00x")
            extras.append(str(ruta))
        vuelos = [crear_vuelo_sintetico(persona, raiz_de_obra / "salidas") for _ in range(5)]
        respuesta = con_sesion.get(
            reverse("visor:inicio"),
            {
                "ruta": str(tif_de_obra),
                "capa": [str(tif_de_obra), *extras],
                "vuelo": [str(v.pk) for v in vuelos] + [str(vuelos[0].pk)],
            },
        )
        cuerpo = respuesta.content.decode()
        partes = _capas_de(cuerpo)
        assert [c["tipo"] for c in partes].count("raster") == capas.MAXIMO_DE_RASTERS
        assert [c["tipo"] for c in partes].count("vuelo-fotos") == capas.MAXIMO_DE_VUELOS
        assert "Se muestran como máximo" in cuerpo


class TestElSelectorDeLaPantalla:
    def test_ofrece_solo_los_vuelos_propios_terminados_y_los_que_no_estan_ya(
        self,
        con_sesion,
        gdal_de_mentira,
        tif_de_obra,
        un_vuelo,
        otra_persona,
        raiz_de_obra,
        persona,
    ):
        ajeno = crear_vuelo_sintetico(otra_persona, raiz_de_obra / "salidas")
        otro_propio = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
        cuerpo = con_sesion.get(
            reverse("visor:inicio"), {"ruta": str(tif_de_obra), "vuelo": str(un_vuelo.pk)}
        ).content.decode()
        assert f'<option value="{otro_propio.pk}">' in cuerpo
        assert f'<option value="{un_vuelo.pk}">' not in cuerpo, "ese ya está en el mapa"
        assert str(ajeno.pk) not in cuerpo, "ni se menciona el de otra persona"

    def test_la_pantalla_de_elegir_ofrece_los_vuelos_propios(
        self, con_sesion, gdal_de_mentira, un_vuelo, otra_persona, raiz_de_obra
    ):
        ajeno = crear_vuelo_sintetico(otra_persona, raiz_de_obra / "salidas")
        cuerpo = con_sesion.get(reverse("visor:inicio")).content.decode()
        assert "Un vuelo suyo" in cuerpo
        assert f"?vuelo={un_vuelo.pk}" in cuerpo and str(ajeno.pk) not in cuerpo
