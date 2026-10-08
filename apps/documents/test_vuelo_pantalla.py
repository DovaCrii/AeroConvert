"""«Corregir un vuelo de dron»: la pantalla, el trabajo y el visor, de punta a punta (F18.4).

Los archivos son los **sintéticos y de fórmula conocida** de `test_vuelo_proceso.py`. El recorrido
completo es: llenar el formulario → encolar → el despachador corre la herramienta → el zip trae lo
que dice → el visor lo dibuja con sus datos, y la miniatura sale de la carpeta de fotos.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.documents import motor, tarea
from apps.documents.test_vuelo_proceso import (
    N_FOTOS,
    _fotos_de_trimble,
    _mrk,
    _trayectoria,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    )
    return client


def _archivos(tmp_path) -> dict[str, Path]:
    datos = {
        "trayectoria": ("009.csv", _trayectoria()),
        "disparos": ("vuelo_Timestamp.MRK", _mrk()),
        "referencia": ("export_extended.csv", _fotos_de_trimble()),
    }
    rutas = {}
    for clave, (nombre, contenido) in datos.items():
        rutas[clave] = tmp_path / nombre
        rutas[clave].write_bytes(contenido)
    return rutas


def _carpeta_de_fotos(tmp_path) -> Path:
    carpeta = tmp_path / "fotos"
    carpeta.mkdir()
    for i in range(N_FOTOS):
        Image.new("RGB", (1200, 900), (30, 90, 160)).save(
            carpeta / f"DJI_{i + 1:04d}_V.JPG", "JPEG"
        )
    return carpeta


def _enviar(sesion, rutas, **extra):
    datos = {
        "trayectoria": str(rutas["trayectoria"]),
        "disparos": str(rutas["disparos"]),
        "referencia": str(rutas["referencia"]),
        "sistema": "medir",
        "escala_de_tiempo": "GPST",
        "aplicar_desfase": "on",
        **extra,
    }
    return sesion.post(reverse("documents:vuelo_dron"), datos)


class TestLaPantalla:
    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("documents:vuelo_dron")).status_code == 302

    def test_se_abre_y_dice_lo_que_hace_cada_paso(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert "Corregir un vuelo de dron" in cuerpo
        for paso in ("La trayectoria", "Los disparos de la cámara", "Las posiciones de Trimble"):
            assert paso in cuerpo
        assert "La carpeta de fotos" in cuerpo and "Medirlo con las posiciones de Trimble" in cuerpo
        assert "data-avance-subida" in cuerpo and "hace falta" in cuerpo

    def test_las_dos_vias_de_cada_paso_y_ninguna_pide_teclear_una_ruta(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert cuerpo.count('type="file"') == 3  # las fotos se eligen por carpeta
        assert cuerpo.count("de la carpeta compartida") >= 3
        assert 'type="text"' not in cuerpo

    def test_el_explorador_pide_solo_lo_suyo(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert "ext=.mrk" in cuerpo and "carpeta=1" in cuerpo

    @pytest.mark.parametrize(
        "quitar,mensaje",
        [
            ("trayectoria", "Falta la trayectoria"),
            ("disparos", "Faltan los disparos"),
        ],
    )
    def test_falta_un_archivo_y_lo_dice_con_el_formulario_delante(
        self, sesion, tmp_path, quitar, mensaje
    ):
        rutas = _archivos(tmp_path)
        respuesta = _enviar(sesion, rutas, **{quitar: ""})
        assert respuesta.status_code == 200 and mensaje in respuesta.content.decode()

    def test_medir_sin_las_posiciones_de_trimble_se_dice_antes_de_encolar(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        rutas = _archivos(tmp_path)
        respuesta = _enviar(sesion, rutas, referencia="")
        assert "No hay con qué medir" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_un_sistema_declarado_que_no_coincide_se_rechaza_con_lo_que_se_midio(
        self, sesion, tmp_path
    ):
        respuesta = _enviar(sesion, _archivos(tmp_path), sistema="32718")
        assert "quedan a" in respuesta.content.decode()

    def test_un_sistema_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path):
        respuesta = _enviar(sesion, _archivos(tmp_path), sistema="24879")
        assert "no es de los que se ofrecen" in respuesta.content.decode()

    def test_una_escala_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path):
        respuesta = _enviar(sesion, _archivos(tmp_path), escala_de_tiempo="local")
        assert "escala de tiempo" in respuesta.content.decode()

    def test_un_archivo_que_no_es_lo_que_dice_se_rechaza(self, sesion, tmp_path):
        rutas = _archivos(tmp_path)
        rutas["trayectoria"] = tmp_path / "mapa.dxf"
        rutas["trayectoria"].write_text("x", encoding="utf-8")
        assert "no es un CSV de trayectoria" in _enviar(sesion, rutas).content.decode()

    def test_una_carpeta_fuera_de_las_raices_no_vale(self, sesion, tmp_path):
        rutas = _archivos(tmp_path)
        respuesta = _enviar(sesion, rutas, carpeta_de_fotos=r"C:\Windows")
        assert respuesta.status_code == 200 and "fuera" in respuesta.content.decode().lower()

    def test_registrada_en_el_motor_y_en_la_tarea(self):
        assert "vuelo_dron" in motor.ESPECIFICACIONES and "vuelo_dron" in tarea.TAREAS
        assert motor.carril_de("vuelo_dron") == "pesado"


def _correr(sesion, tmp_path, **extra):
    from apps.jobs import despachador
    from apps.jobs.models import ConversionJob

    rutas = _archivos(tmp_path)
    respuesta = _enviar(sesion, rutas, **extra)
    assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
    assert despachador.procesar_una_vez() == 1
    return ConversionJob.objects.latest("created_at"), rutas


class TestElTrabajo:
    def test_de_extremo_a_extremo_el_zip_trae_lo_que_dice(self, sesion, tmp_path):
        trabajo, rutas = _correr(sesion, tmp_path)
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.herramienta == "vuelo_dron" and trabajo.progress_percent == 100
        with zipfile.ZipFile(trabajo.output_path) as z:
            assert sorted(z.namelist()) == sorted(
                ["fotos.csv", "fotos.geojson", "fotos.kml", "calidad.md", "vuelo.json"]
            )
        # La verificación del motor leyó cada pieza con otro lector.
        assert trabajo.verification["verificado_con"]
        assert trabajo.verification["piezas_verificadas"] == 5
        # Los originales, intactos.
        for ruta in rutas.values():
            assert ruta.stat().st_size > 0

    def test_las_entradas_quedan_con_su_papel(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        assert {e.papel for e in trabajo.entradas.all()} == {
            "trayectoria",
            "disparos",
            "referencia",
        }

    def test_el_resumen_del_recibo(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        v = trabajo.verification
        assert v["fotos"] == N_FOTOS and v["con_posicion"] == N_FOTOS
        assert v["sistema_epsg"] == 32719 and v["contraste_maximo_mm"] < 1.5

    def test_si_una_pieza_sale_mal_el_motor_la_rechaza(self, tmp_path):
        parcial = tmp_path / "vuelo.zip"
        with zipfile.ZipFile(parcial, "w") as z:
            z.writestr("fotos.csv", "foto,disparo\na,1\n")
        veredicto = motor._verificar_zip(
            parcial, {"piezas": [{"nombre": "fotos.csv", "filas": 40}]}
        )
        assert not veredicto.correcta and "debía traer 40 fila" in veredicto.motivo

    def test_el_progreso_dice_que_se_esta_haciendo(self):
        analizar = motor._analizar_progreso
        assert analizar("PROGRESO 0.550 Sincronizando las fotos") == (
            0.55,
            "Sincronizando las fotos",
        )
        assert analizar("PROGRESO 0.550") == 0.55 and analizar("otra cosa") is None

    def test_la_ficha_ofrece_ver_el_vuelo(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        cuerpo = sesion.get(reverse("jobs:ficha", args=[trabajo.pk])).content.decode()
        assert reverse("documents:vuelo_ver", args=[trabajo.pk]) in cuerpo
        assert "Ver el vuelo en el mapa" in cuerpo and "Descargar el zip" in cuerpo


class TestElVisor:
    def test_la_pagina_dice_el_sistema_que_se_proceso(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        cuerpo = sesion.get(reverse("documents:vuelo_ver", args=[trabajo.pk])).content.decode()
        assert "WGS 84 / UTM 19S" in cuerpo and "EPSG:32719" in cuerpo
        assert "Medido contra la latitud y la longitud de Trimble" in cuerpo
        assert "no declarada" in cuerpo  # la referencia de la altura
        assert reverse("documents:vuelo_datos", args=[trabajo.pk]) in cuerpo

    def test_los_datos_son_los_del_vuelo(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        respuesta = sesion.get(reverse("documents:vuelo_datos", args=[trabajo.pk]))
        assert respuesta.status_code == 200 and "no-store" in respuesta["Cache-Control"]
        datos = json.loads(respuesta.content)
        assert len(datos["fotos"]) == N_FOTOS and datos["sistema"]["epsg"] == 32719

    def test_las_miniaturas_salen_de_la_carpeta_elegida(self, sesion, tmp_path):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        assert trabajo.status == "done", trabajo.reason_detail
        respuesta = sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 3]))
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "image/jpeg"
        imagen = Image.open(io.BytesIO(respuesta.content))
        assert max(imagen.size) <= 480 and imagen.size[0] > imagen.size[1]

    def test_sin_carpeta_no_hay_miniatura(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1])).status_code
            == 404
        )

    def test_una_foto_que_no_existe_o_fuera_de_rango_es_404(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(_carpeta_de_fotos(tmp_path)))
        for n in (0, N_FOTOS + 1, 9999):
            assert (
                sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, n])).status_code
                == 404
            )

    def test_una_foto_borrada_de_la_carpeta_es_404_y_no_revienta(self, sesion, tmp_path):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        (carpeta / "DJI_0002_V.JPG").unlink()
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 2])).status_code
            == 404
        )

    def test_una_foto_que_no_es_imagen_es_404(self, sesion, tmp_path):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        (carpeta / "DJI_0002_V.JPG").write_bytes(b"no soy una foto")
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 2])).status_code
            == 404
        )

    def test_si_la_carpeta_deja_de_estar_permitida_no_se_sirve(self, sesion, tmp_path, settings):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        settings.RAICES_PERMITIDAS = str(tmp_path / "trabajo")
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1])).status_code
            == 404
        )

    def test_todo_es_solo_de_quien_pidio_el_trabajo(self, sesion, client, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(_carpeta_de_fotos(tmp_path)))
        client.logout()
        client.force_login(
            get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        )
        for nombre, args in (
            ("vuelo_ver", [trabajo.pk]),
            ("vuelo_datos", [trabajo.pk]),
            ("vuelo_miniatura", [trabajo.pk, 1]),
        ):
            assert client.get(reverse(f"documents:{nombre}", args=args)).status_code == 404, nombre

    def test_sin_sesion_redirigen(self, sesion, client, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path)
        anonimo = type(client)()
        for nombre, args in (("vuelo_ver", [trabajo.pk]), ("vuelo_datos", [trabajo.pk])):
            assert anonimo.get(reverse(f"documents:{nombre}", args=args)).status_code == 302

    def test_un_trabajo_de_otra_herramienta_no_se_ve_como_vuelo(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        ajeno = ConversionJob.objects.create(
            owner=get_user_model().objects.get(username="ana"),
            source_name="x.srt",
            target_format_code="gpx",
            herramienta="telemetria",
            status="done",
            output_path=str(tmp_path / "x.gpx"),
        )
        (tmp_path / "x.gpx").write_text("x", encoding="utf-8")
        assert sesion.get(reverse("documents:vuelo_ver", args=[ajeno.pk])).status_code == 404

    def test_el_visor_no_pone_nada_del_csv_como_html(self, sesion, tmp_path):
        """Los nombres de las fotos vienen de un CSV: la página no los incrusta, los pide."""
        trabajo, _ = _correr(sesion, tmp_path)
        cuerpo = sesion.get(reverse("documents:vuelo_ver", args=[trabajo.pk])).content.decode()
        assert "DJI_0001_V.JPG" not in cuerpo


def test_subir_los_archivos_desde_el_equipo_tambien_funciona(sesion, tmp_path):
    from apps.jobs import despachador
    from apps.jobs.models import ConversionJob

    respuesta = sesion.post(
        reverse("documents:vuelo_dron"),
        {
            "trayectoria_subida": SimpleUploadedFile("009.csv", _trayectoria()),
            "disparos_subida": SimpleUploadedFile("vuelo_Timestamp.MRK", _mrk()),
            "referencia_subida": SimpleUploadedFile("export_extended.csv", _fotos_de_trimble()),
            "sistema": "medir",
            "escala_de_tiempo": "GPST",
            "aplicar_desfase": "on",
        },
    )
    assert respuesta.status_code == 302
    assert despachador.procesar_una_vez() == 1
    assert ConversionJob.objects.latest("created_at").status == "done"


def _huellas(rutas):
    return {
        k: (r.stat().st_mtime_ns, __import__("hashlib").sha256(r.read_bytes()).hexdigest())
        for k, r in rutas.items()
    }


class TestElOriginalNoSeToca:
    """Regla 5: sha256 y mtime de las tres entradas, en el camino feliz y en los de fallo."""

    def test_camino_feliz(self, sesion, tmp_path):
        rutas = _archivos(tmp_path)
        antes = _huellas(rutas)
        _enviar(sesion, rutas)
        from apps.jobs import despachador

        despachador.procesar_una_vez()
        assert _huellas(rutas) == antes

    def test_la_vista_rechaza_y_no_toca(self, sesion, tmp_path):
        rutas = _archivos(tmp_path)
        antes = _huellas(rutas)
        _enviar(sesion, rutas, sistema="32718")  # no coincide: se rechaza
        assert _huellas(rutas) == antes

    def test_la_tarea_falla_sin_escala_y_no_toca(self, tmp_path):
        rutas = _archivos(tmp_path)
        antes = _huellas(rutas)
        entradas = [{"papel": k, "ruta": str(r)} for k, r in rutas.items()]
        with pytest.raises(tarea.FalloDeTarea):
            tarea._vuelo_dron(entradas, {"sistema": "medir"}, tmp_path / "x.parcial")
        assert _huellas(rutas) == antes and not (tmp_path / "x.parcial").exists()

    def test_el_zip_rechazado_por_el_motor_no_toca(self, tmp_path):
        rutas = _archivos(tmp_path)
        antes = _huellas(rutas)
        parcial = tmp_path / "v.zip"
        with zipfile.ZipFile(parcial, "w") as z:
            z.writestr("fotos.csv", "foto,disparo\na,1\n")
        assert not motor._verificar_zip(
            parcial, {"piezas": [{"nombre": "fotos.csv", "filas": 40}]}
        ).correcta
        assert _huellas(rutas) == antes


class TestLaEscalaNoSeSupone:
    def test_sin_escala_la_vista_pide_elegirla(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        respuesta = _enviar(sesion, _archivos(tmp_path), escala_de_tiempo="")
        assert "Elija la escala de tiempo" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_sin_referencia_el_informe_avisa_que_no_pudo_comprobarla(self, sesion, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path, referencia="", sistema="32719")
        assert trabajo.status == "done", trabajo.reason_detail
        with zipfile.ZipFile(trabajo.output_path) as z:
            informe = z.read("calidad.md").decode()
        assert "no hay con qué comprobar" in informe


def _cambiar_vuelo_json(trabajo, cambio):
    with zipfile.ZipFile(trabajo.output_path) as z:
        piezas = {n: z.read(n) for n in z.namelist()}
    datos = json.loads(piezas["vuelo.json"])
    cambio(datos)
    piezas["vuelo.json"] = json.dumps(datos).encode()
    with zipfile.ZipFile(trabajo.output_path, "w") as z:
        for n, b in piezas.items():
            z.writestr(n, b)


class TestLaMiniaturaEsDura:
    def test_el_nombre_real_de_la_carpeta_se_guarda_en_vuelo_json(self, sesion, tmp_path):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        datos = json.loads(sesion.get(reverse("documents:vuelo_datos", args=[trabajo.pk])).content)
        reales = {p.name for p in carpeta.iterdir()}
        assert all(f["archivo"] in reales for f in datos["fotos"] if f.get("miniatura"))

    @pytest.mark.parametrize(
        "hostil", ["../x.jpg", "..\\x.jpg", "<img src=x onerror=alert(1)>.jpg", "/etc/passwd"]
    )
    def test_un_nombre_hostil_no_sale_de_la_carpeta(self, sesion, tmp_path, hostil):
        carpeta = _carpeta_de_fotos(tmp_path)
        Image.new("RGB", (50, 50)).save(tmp_path / "x.jpg", "JPEG")
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        _cambiar_vuelo_json(trabajo, lambda d: d["fotos"][0].update(archivo=hostil, miniatura=True))
        respuesta = sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1]))
        assert respuesta.status_code == 404

    def test_un_enlace_simbolico_que_sale_de_la_carpeta_no_se_sirve(self, sesion, tmp_path):
        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        fuera = tmp_path.parent / f"{tmp_path.name}_fuera.jpg"
        Image.new("RGB", (50, 50)).save(fuera, "JPEG")
        destino = carpeta / "DJI_0001_V.JPG"
        destino.unlink()
        try:
            destino.symlink_to(fuera)
        except OSError:
            pytest.skip("sin permiso para crear enlaces simbólicos")
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1])).status_code
            == 404
        )

    def test_una_foto_demasiado_grande_es_404(self, sesion, tmp_path, monkeypatch):
        from apps.documents.views import pantalla_vuelo

        carpeta = _carpeta_de_fotos(tmp_path)
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(carpeta))
        monkeypatch.setattr(pantalla_vuelo, "LIMITE_DE_PIXELES", 10)
        assert (
            sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1])).status_code
            == 404
        )

    def test_sin_sesion_la_miniatura_redirige(self, sesion, client, tmp_path):
        trabajo, _ = _correr(sesion, tmp_path, carpeta_de_fotos=str(_carpeta_de_fotos(tmp_path)))
        anonimo = type(client)()
        url = reverse("documents:vuelo_miniatura", args=[trabajo.pk, 1])
        assert anonimo.get(url).status_code == 302


class TestElScriptDelVisor:
    """No hay pruebas de JavaScript en este repositorio: lo que se puede vigilar, se vigila en el
    texto. Esto es lo que se rompió una vez y lo vio una persona."""

    def _js(self) -> str:
        from django.conf import settings

        return (Path(settings.BASE_DIR) / "static" / "js" / "vuelo.js").read_text(encoding="utf-8")

    def test_el_este_y_el_norte_se_formatean_desde_el_texto_con_tres_decimales(self):
        js = self._js()
        # Redondear el entero y pegarle los decimales detrás subía un metro entero (414 884,611
        # salía «414 885,611»). Se comprueba que no se vuelva a escribir así.
        assert 'miles(datos.origen.este + f.x) + ","' not in js
        assert 'fila("Este", metros(datos.origen.este + f.x))' in js
        assert 'fila("Norte", metros(datos.origen.norte + f.y))' in js
        assert ".toFixed(3).split(" in js

    def test_los_textos_de_un_csv_nunca_entran_como_html(self):
        js = self._js()
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js

    def test_no_hay_manejadores_en_linea_ni_cdn(self):
        js = self._js()
        assert "http://" not in js and "https://" not in js and "eval(" not in js
