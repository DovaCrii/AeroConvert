"""Paquetes de entrega y lotes (F16.1 y F16.2).

Los archivos son GeoTIFF mínimos (los que usa el resto de la suite) y el motor es `MotorDeMentira`,
que lanza un proceso de verdad sin GDAL. Lo que se prueba es el pegamento: que los nombres salgan
solos y seguros, que ningún trabajo pise un original, que el lote no esconda lo que dejó fuera y que
su estado salga de los hijos.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import models as jm
from apps.jobs.models import ConversionJob, LoteDeTrabajos
from apps.presets import aplicar, paquetes
from apps.presets.models import ConversionPreset, PaqueteDeEntrega

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 8)


def _preajuste(slug, formato, **extra):
    return SimpleNamespace(
        slug=slug,
        target_format_code=formato,
        target_profile_id=extra.get("perfil", ""),
        options=extra.get("options", {}),
        target_crs_code=extra.get("crs", ""),
    )


def _paquete(pasos, patron="{origen}_{destino}", crs="", nombre="Entrega a BHP"):
    return SimpleNamespace(nombre=nombre, pasos=pasos, patron_de_nombre=patron, target_crs_code=crs)


class TestLosNombres:
    @pytest.mark.parametrize(
        "origen",
        [
            "../../etc/passwd",
            "..\\..\\x",
            'a<b>"c|d?e*',
            "CON",
            "con",
            "nul",
            "a.",
            "  a  ",
            "\x00x",
        ],
    )
    def test_un_nombre_hostil_no_sale_de_su_carpeta_ni_rompe_windows(self, origen):
        nombre = paquetes.nombre_de_salida(
            "{origen}_{destino}", origen=origen, destino="cog", perfil="", fecha=HOY, n=1
        )
        assert nombre and "/" not in nombre and "\\" not in nombre and ".." not in nombre
        assert not set('<>:"|?*') & set(nombre)
        assert nombre.lower() not in {"con", "prn", "aux", "nul"}
        assert nombre == nombre.strip(" .")

    def test_las_marcas_salen_de_la_receta_y_de_la_fecha_que_se_pasa(self):
        nombre = paquetes.nombre_de_salida(
            "{origen}-{destino}-{perfil}-{fecha}-{n}",
            origen="orto", destino="cog", perfil="civil3d", fecha=HOY, n=2,
        )  # fmt: skip
        assert nombre == "orto-cog-civil3d-20261008-2"

    def test_un_valor_con_llaves_no_se_lee_como_otra_marca(self):
        nombre = paquetes.nombre_de_salida(
            "{origen}_{destino}", origen="{fecha}", destino="cog", perfil="", fecha=HOY, n=1
        )
        assert "20261008" not in nombre

    @pytest.mark.parametrize(
        "patron,motivo",
        [
            ("", "vacío"),
            ("{nada}", "no es una marca"),
            ("{origen", "llave suelta"),
            ("a/b", "carácter"),
            ("x" * 200, "pasa de"),
        ],
    )
    def test_un_patron_malo_se_rechaza_con_su_motivo(self, patron, motivo):
        with pytest.raises(paquetes.PaqueteInvalido, match=motivo):
            paquetes.validar_patron(patron)

    def test_dos_pasos_con_el_mismo_nombre_no_se_pisan(self):
        pre = {"a": _preajuste("a", "cog"), "b": _preajuste("b", "cog")}
        pasos = paquetes.expandir(
            _paquete(["a", "b"], patron="{origen}"), pre, nombre_origen="orto", fecha=HOY
        )
        assert [p.nombre_de_salida for p in pasos] == ["orto", "orto_2"]

    def test_la_misma_receta_da_los_mismos_parametros_en_dos_corridas(self):
        pre = {"a": _preajuste("a", "cog", options={"z": 1, "a": 2}), "b": _preajuste("b", "jp2")}
        paquete = _paquete(["a", "b"], crs="EPSG:32719")
        uno = paquetes.expandir(paquete, pre, nombre_origen="orto", fecha=HOY)
        dos = paquetes.expandir(
            paquete, dict(reversed(list(pre.items()))), nombre_origen="orto", fecha=HOY
        )
        assert uno == dos
        assert uno[0].opciones == (("a", 2), ("z", 1)), "las opciones salen ordenadas"

    def test_un_preajuste_que_ya_no_existe_se_dice_con_su_nombre(self):
        with pytest.raises(paquetes.PaqueteInvalido, match="«fantasma»"):
            paquetes.expandir(_paquete(["fantasma"]), {}, nombre_origen="x", fecha=HOY)

    def test_un_paquete_sin_pasos_se_rechaza(self):
        with pytest.raises(paquetes.PaqueteInvalido, match="ningún paso"):
            paquetes.expandir(_paquete([]), {}, nombre_origen="x", fecha=HOY)


# --- Aplicar a una carpeta ---------------------------------------------------------------------


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106


@pytest.fixture
def taller(settings, tmp_path):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    registry.limpiar()
    registry.registrar(
        MotorDeMentira("m", (("geotiff", "cog"), ("geotiff", "jp2"), ("geotiff", "geotiff")))
    )
    yield tmp_path
    registry.limpiar()


def _carpeta(base: Path, nombres=("a.tif", "b.tif"), extra=()):
    carpeta = base / "entrega"
    carpeta.mkdir()
    for n in nombres:
        (carpeta / n).write_bytes(geotiff_minimo())
    for n in extra:
        (carpeta / n).write_text("no soy un raster", encoding="utf-8")
    return carpeta


def _paquete_de(usuario, destinos=("cog", "jp2"), patron="{origen}_{destino}", crs=""):
    slugs = []
    for destino in destinos:
        p = ConversionPreset.objects.create(
            slug=f"{usuario.username}-{destino}-{uuid.uuid4().hex[:6]}",
            nombre=f"Mi {destino}",
            target_format_code=destino,
            options={"compresion": "DEFLATE"},
            owner=usuario,
        )
        slugs.append(p.slug)
    return PaqueteDeEntrega.objects.create(
        slug=f"entrega-{usuario.username}-{uuid.uuid4().hex[:6]}",
        nombre="Entrega a BHP",
        pasos=slugs,
        patron_de_nombre=patron,
        target_crs_code=crs,
        owner=usuario,
    )


def _huellas(carpeta: Path):
    return {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in carpeta.iterdir()
        if p.is_file()
    }


class TestAplicarAUnaCarpeta:
    def test_cada_archivo_da_un_trabajo_por_paso_y_todos_cuelgan_del_lote(self, ana, taller):
        carpeta = _carpeta(taller)
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta)
        )
        assert len(resultado.trabajos) == 4
        assert {t.lote_id for t in resultado.trabajos} == {resultado.lote.pk}
        salidas = sorted(Path(t.output_path).name for t in resultado.trabajos)
        from apps.formats import catalogo

        ext_cog = catalogo.FORMATOS["cog"].extension_para_escribir
        ext_jp2 = catalogo.FORMATOS["jp2"].extension_para_escribir
        assert salidas == sorted(
            [f"a_cog{ext_cog}", f"a_jp2{ext_jp2}", f"b_cog{ext_cog}", f"b_jp2{ext_jp2}"]
        )
        assert {t.owner_id for t in resultado.trabajos} == {ana.pk}

    def test_los_originales_no_se_tocan_ni_se_pisan(self, ana, taller):
        carpeta = _carpeta(taller)
        antes = _huellas(carpeta)
        aplicar.aplicar_paquete(usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta))
        assert _huellas(carpeta) == antes

    def test_un_nombre_que_pisaria_el_original_se_deja_fuera_y_se_dice(self, ana, taller):
        carpeta = _carpeta(taller, nombres=("a.tif", "b.tif"))
        paquete = _paquete_de(ana, destinos=("geotiff",), patron="{origen}")
        with pytest.raises(paquetes.PaqueteInvalido, match="sobre el archivo original"):
            aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(carpeta))
        assert not LoteDeTrabajos.objects.exists() and not ConversionJob.objects.exists()

    def test_lo_que_no_se_reconoce_queda_en_omitidos_con_su_nombre(self, ana, taller):
        carpeta = _carpeta(taller, extra=("notas.txt",))
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta)
        )
        assert [o["nombre"] for o in resultado.omitidos] == ["notas.txt"]
        resultado.lote.refresh_from_db()
        assert resultado.lote.omitidos[0]["nombre"] == "notas.txt"

    def test_un_paso_sin_motor_deja_fuera_el_archivo_entero_y_no_encola_nada_a_medias(
        self, ana, taller
    ):
        carpeta = _carpeta(taller, nombres=("a.tif",))
        paquete = _paquete_de(ana, destinos=("cog", "dxf"))  # geotiff → dxf no lo hace nadie
        with pytest.raises(paquetes.PaqueteInvalido, match="No se encoló nada"):
            aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(carpeta))
        assert not ConversionJob.objects.exists(), "o todos los pasos o ninguno"

    def test_si_unos_archivos_sirven_y_otros_no_el_lote_sale_con_lo_que_sirve(self, ana, taller):
        carpeta = _carpeta(taller, extra=("mapa.dxf",))
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana, destinos=("cog",)), ruta=str(carpeta)
        )
        assert len(resultado.trabajos) == 2 and [o["nombre"] for o in resultado.omitidos] == [
            "mapa.dxf"
        ]

    def test_un_archivo_solo_tambien_es_un_lote(self, ana, taller):
        carpeta = _carpeta(taller, nombres=("a.tif",))
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta / "a.tif")
        )
        assert len(resultado.trabajos) == 2 and resultado.lote.carpeta == str(carpeta)

    def test_el_sistema_del_paquete_va_al_trabajo_y_el_del_archivo_no_se_inventa(self, ana, taller):
        carpeta = _carpeta(taller, nombres=("a.tif",))
        paquete = _paquete_de(ana, destinos=("cog",), crs="EPSG:32718")
        (trabajo,) = aplicar.aplicar_paquete(
            usuario=ana, paquete=paquete, ruta=str(carpeta)
        ).trabajos
        assert trabajo.target_crs_authority == "EPSG" and trabajo.target_crs_code == "32718"
        # Lo que el archivo dijo de su sistema se conserva tal cual: el paquete no lo rellena.
        assert trabajo.source_crs_code != "32718"

    def test_una_carpeta_vacia_o_con_demasiados_archivos_se_rechaza(self, ana, taller, monkeypatch):
        vacia = taller / "vacia"
        vacia.mkdir()
        with pytest.raises(paquetes.PaqueteInvalido, match="no tiene archivos"):
            aplicar.aplicar_paquete(usuario=ana, paquete=_paquete_de(ana), ruta=str(vacia))
        carpeta = _carpeta(taller)
        monkeypatch.setattr(aplicar, "MAXIMO_DE_ARCHIVOS_POR_LOTE", 1)
        with pytest.raises(paquetes.PaqueteInvalido, match="admite hasta 1"):
            aplicar.aplicar_paquete(usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta))

    def test_una_ruta_fuera_de_las_carpetas_permitidas_no_se_mira(self, ana, taller):
        with pytest.raises(paquetes.PaqueteInvalido):
            aplicar.aplicar_paquete(usuario=ana, paquete=_paquete_de(ana), ruta=str(taller.parent))
        assert not LoteDeTrabajos.objects.exists()

    def test_dos_archivos_que_darian_la_misma_salida_no_se_pisan(self, ana, taller):
        carpeta = _carpeta(taller)
        paquete = _paquete_de(ana, destinos=("cog",), patron="entrega")
        resultado = aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(carpeta))
        assert len(resultado.trabajos) == 1, "el segundo archivo daría el mismo nombre"
        assert "mismo archivo de salida" in resultado.omitidos[0]["motivo"]

    def test_el_preajuste_de_otra_persona_no_se_puede_usar(self, ana, beto, taller):
        carpeta = _carpeta(taller, nombres=("a.tif",))
        ajeno = _paquete_de(beto, destinos=("cog",))
        paquete = PaqueteDeEntrega.objects.create(
            slug="mio", nombre="Mío", pasos=list(ajeno.pasos), owner=ana
        )
        with pytest.raises(paquetes.PaqueteInvalido):
            aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(carpeta))


class TestOtrosOriginalesDeLaCarpeta:
    """Regla 5: una salida no puede caer sobre OTRO archivo de la carpeta (también es original)."""

    def test_una_salida_que_cae_sobre_un_hermano_no_lo_pisa(self, ana, taller):
        carpeta = _carpeta(taller, nombres=("a.tif", "a_cog.tif"))
        antes = _huellas(carpeta)
        paquete = _paquete_de(ana, destinos=("cog",))
        resultado = aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(carpeta))
        salidas = {Path(t.output_path).name for t in resultado.trabajos}
        assert "a_cog.tif" not in salidas
        assert [o["nombre"] for o in resultado.omitidos] == ["a.tif"]
        assert "puede ser un original" in resultado.omitidos[0]["motivo"]
        assert resultado.omitidos[0]["codigo"] == "paquete-no-aplicable"
        assert _huellas(carpeta) == antes, "sha256 y mtime de todos los originales"

    def test_mayusculas_y_minusculas_cuentan_igual(self, ana, taller):
        carpeta = _carpeta(taller, nombres=("a.tif", "A_COG.tif"))
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana, destinos=("cog",)), ruta=str(carpeta)
        )
        assert "A_COG.tif" not in {Path(t.output_path).name for t in resultado.trabajos}


class TestLosNombresReservados:
    @pytest.mark.parametrize(
        "origen", ["CON", "con", "Aux", "nul", "com1", "lpt9", "con.v2", "aux.x"]
    )
    def test_con_el_patron_origen_a_secas_tampoco_sale_un_reservado(self, origen):
        nombre = paquetes.nombre_de_salida(
            "{origen}", origen=origen, destino="cog", perfil="", fecha=HOY, n=1
        )
        assert nombre.split(".")[0].lower() not in {"con", "prn", "aux", "nul", "com1", "lpt9"}
        assert nombre == nombre.rstrip(" .")

    def test_el_largo_maximo_no_deja_un_punto_al_final(self):
        nombre = paquetes.nombre_de_salida(
            "{origen}", origen="a" * 119 + ".b", destino="cog", perfil="", fecha=HOY, n=1
        )
        assert len(nombre) <= paquetes.LARGO_MAXIMO_DE_NOMBRE and not nombre.endswith(".")


class TestTodoONada:
    def test_un_fallo_inesperado_a_mitad_no_deja_un_lote_huerfano(self, ana, taller, monkeypatch):
        carpeta = _carpeta(taller)
        llamadas = {"n": 0}
        original = aplicar.encolar_paquete_para_un_archivo

        def a_medias(**kw):
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                raise RuntimeError("se cayó")
            return original(**kw)

        monkeypatch.setattr(aplicar, "encolar_paquete_para_un_archivo", a_medias)
        with pytest.raises(RuntimeError):
            aplicar.aplicar_paquete(usuario=ana, paquete=_paquete_de(ana), ruta=str(carpeta))
        assert not LoteDeTrabajos.objects.exists() and not ConversionJob.objects.exists()

    def test_el_uso_del_paquete_se_suma_en_la_base(self, ana, taller):
        paquete = _paquete_de(ana, destinos=("cog",))
        aplicar.aplicar_paquete(usuario=ana, paquete=paquete, ruta=str(_carpeta(taller)))
        paquete.refresh_from_db()
        assert paquete.veces_usado == 1


class TestElEstadoDelLote:
    def _lote(self, ana, estados):
        lote = LoteDeTrabajos.objects.create(owner=ana, nombre="x")
        for i, estado in enumerate(estados):
            ConversionJob.objects.create(
                owner=ana, lote=lote, source_path="x", source_name=f"{i}.tif",
                source_format_code="geotiff", target_format_code="cog",
                output_path=f"y{i}", status=estado,
            )  # fmt: skip
        return lote

    def test_todos_hechos_es_hecho(self, ana):
        assert self._lote(ana, [jm.HECHO, jm.HECHO]).estado == "hecho"

    def test_uno_en_curso_es_en_curso_aunque_otro_haya_fallado(self, ana):
        assert self._lote(ana, [jm.ERROR, jm.EJECUTANDO]).estado == "en-curso"

    def test_si_falla_uno_el_lote_falla(self, ana):
        lote = self._lote(ana, [jm.HECHO, jm.ERROR])
        assert lote.estado == "con-fallos" and lote.cuentas()["fallidos"] == 1

    def test_un_cancelado_tambien_deja_el_lote_incompleto(self, ana):
        assert self._lote(ana, [jm.HECHO, jm.CANCELADO]).estado == "con-fallos"

    def test_un_lote_sin_hijos_no_dice_hecho(self, ana):
        assert self._lote(ana, []).estado == "con-fallos"


class TestDeExtremoAExtremo:
    def test_el_despachador_corre_el_lote_y_el_padre_lo_refleja(self, ana, taller):
        from apps.jobs import despachador

        carpeta = _carpeta(taller, nombres=("a.tif",))
        resultado = aplicar.aplicar_paquete(
            usuario=ana, paquete=_paquete_de(ana, destinos=("cog",)), ruta=str(carpeta)
        )
        assert resultado.lote.estado == "en-curso"
        despachador.procesar_una_vez()
        assert resultado.lote.estado == "hecho"
        assert (carpeta / "a_cog.tif").exists()


# --- Las vistas --------------------------------------------------------------------------------


@pytest.fixture
def entrada_de_ana(client, ana):
    client.force_login(ana)
    return client


class TestLasVistas:
    @pytest.mark.parametrize(
        "nombre,args",
        [
            ("paquetes", []),
            ("paquete_nuevo", []),
            ("lote_nuevo", []),
            ("paquete_borrar", ["x"]),
            ("lote", ["11111111-1111-1111-1111-111111111111"]),
        ],
    )
    def test_sin_sesion_redirige_a_entrar(self, client, nombre, args):
        url = reverse(f"presets:{nombre}", args=args)
        respuesta = (
            client.post(url)
            if nombre in {"paquete_nuevo", "lote_nuevo", "paquete_borrar"}
            else client.get(url)
        )
        assert respuesta.status_code == 302 and "/entrar/" in respuesta["Location"]

    def test_la_pagina_se_abre_y_dice_lo_que_hace(self, entrada_de_ana):
        cuerpo = entrada_de_ana.get(reverse("presets:paquetes")).content.decode()
        assert "Paquetes de entrega" in cuerpo and "Nuevo paquete" in cuerpo

    def test_crear_un_paquete(self, entrada_de_ana, ana):
        p = ConversionPreset.objects.create(
            slug="p1", nombre="Mi cog", target_format_code="cog", owner=ana
        )
        r = entrada_de_ana.post(
            reverse("presets:paquete_nuevo"),
            {
                "nombre": "Entrega a BHP",
                "pasos": [p.slug],
                "patron": "{origen}_{destino}",
                "crs": "EPSG:32719",
            },
        )
        assert r.status_code == 302
        paquete = PaqueteDeEntrega.objects.get(owner=ana)
        assert paquete.pasos == ["p1"] and paquete.target_crs_code == "32719"

    @pytest.mark.parametrize(
        "datos,texto",
        [
            ({"nombre": "", "pasos": ["p1"]}, "necesita un nombre"),
            ({"nombre": "x", "pasos": []}, "al menos un preajuste"),
            ({"nombre": "x", "pasos": ["p1"], "patron": "{mal}"}, "no es una marca"),
            ({"nombre": "x", "pasos": ["p1"], "crs": "no-es-un-epsg"}, ""),
            ({"nombre": "x", "pasos": ["ajeno"]}, "ya no existe"),
        ],
    )
    def test_un_paquete_mal_hecho_no_se_guarda_y_se_dice_por_que(
        self, entrada_de_ana, ana, beto, datos, texto
    ):
        ConversionPreset.objects.create(slug="p1", nombre="a", target_format_code="cog", owner=ana)
        ConversionPreset.objects.create(
            slug="ajeno", nombre="b", target_format_code="cog", owner=beto
        )
        r = entrada_de_ana.post(reverse("presets:paquete_nuevo"), datos)
        assert r.status_code == 200 and not PaqueteDeEntrega.objects.exists()
        assert texto in r.content.decode()

    def test_el_paquete_de_otro_no_se_borra_ni_se_confirma_que_existe(self, entrada_de_ana, beto):
        ajeno = _paquete_de(beto, destinos=("cog",))
        r = entrada_de_ana.post(reverse("presets:paquete_borrar", args=[ajeno.slug]))
        assert r.status_code == 404 and PaqueteDeEntrega.objects.filter(pk=ajeno.pk).exists()

    def test_el_propio_se_borra(self, entrada_de_ana, ana):
        propio = _paquete_de(ana, destinos=("cog",))
        assert (
            entrada_de_ana.post(reverse("presets:paquete_borrar", args=[propio.slug])).status_code
            == 302
        )
        assert not PaqueteDeEntrega.objects.exists()

    def test_aplicar_con_el_paquete_de_otro_es_404(self, entrada_de_ana, beto, taller):
        ajeno = _paquete_de(beto, destinos=("cog",))
        r = entrada_de_ana.post(
            reverse("presets:lote_nuevo"), {"paquete": ajeno.slug, "ruta": str(_carpeta(taller))}
        )
        assert r.status_code == 404 and not LoteDeTrabajos.objects.exists()

    def test_aplicar_lleva_a_la_ficha_del_lote_que_lista_los_trabajos_y_los_omitidos(
        self, entrada_de_ana, ana, taller
    ):
        paquete = _paquete_de(ana, destinos=("cog",))
        carpeta = _carpeta(taller, extra=("notas.txt",))
        r = entrada_de_ana.post(
            reverse("presets:lote_nuevo"), {"paquete": paquete.slug, "ruta": str(carpeta)}
        )
        assert r.status_code == 302 and "/lotes/" in r["Location"]
        cuerpo = entrada_de_ana.get(r["Location"]).content.decode()
        assert "a.tif" in cuerpo and "b.tif" in cuerpo
        assert "Archivos que no entraron (1)" in cuerpo and "notas.txt" in cuerpo
        assert "En curso" in cuerpo and 'http-equiv="refresh"' in cuerpo

    def test_un_lote_con_fallo_no_se_presenta_como_completo(self, entrada_de_ana, ana):
        lote = LoteDeTrabajos.objects.create(owner=ana, nombre="x")
        ConversionJob.objects.create(
            owner=ana, lote=lote, source_path="x", source_name="roto.tif",
            source_format_code="geotiff", target_format_code="cog", output_path="y",
            status=jm.ERROR, reason_code="crs-ausente", reason_detail="Falta el sistema.",
        )  # fmt: skip
        cuerpo = entrada_de_ana.get(reverse("presets:lote", args=[lote.pk])).content.decode()
        assert "Con fallos" in cuerpo and "no está completo" in cuerpo
        assert "crs-ausente" in cuerpo and "roto.tif" in cuerpo
        assert 'http-equiv="refresh"' not in cuerpo

    def test_el_lote_de_otra_persona_es_404(self, entrada_de_ana, beto):
        lote = LoteDeTrabajos.objects.create(owner=beto, nombre="x")
        assert entrada_de_ana.get(reverse("presets:lote", args=[lote.pk])).status_code == 404

    def test_las_acciones_no_admiten_get(self, entrada_de_ana):
        for nombre in ("paquete_nuevo", "lote_nuevo"):
            assert entrada_de_ana.get(reverse(f"presets:{nombre}")).status_code == 405

    def test_la_pagina_de_preajustes_enlaza_a_los_paquetes(self, entrada_de_ana):
        cuerpo = entrada_de_ana.get(reverse("presets:lista")).content.decode()
        assert reverse("presets:paquetes") in cuerpo
