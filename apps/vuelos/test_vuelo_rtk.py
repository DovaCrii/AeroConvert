"""«Las fotos ya traen la posición RTK» (F18.8): leer lo que el dron escribió, con su calidad.

El vuelo es **sintético y de fórmula conocida** (el de `test_vuelo_proceso.py`): la antena sigue una
recta en la cuadrícula UTM 19 sur, y de ella salen **a la vez** el XMP de cada foto y el `.MRK`. La
posición de la cámara que esperamos se calcula **aparte, a mano, en la cuadrícula** (la antena más
el desfase: norte y este suman, la vertical resta), sin pasar por `vuelo_sync`. Los lectores que no
son el nuestro: `exifread` y un analizador de XML en `test_ficha_foto.py`, y `ogrinfo` para el
GeoJSON y el KML cuando GDAL está.

Lo que se comprueba: que la posición sale de las fotos y coincide con el cálculo a mano; que la
calidad sale de `RtkFlag` y lo que falta se dice («no informada»); que la altura solo se llama
elipsoidal si coincide con la del `.MRK`; que un `.MRK` ajeno o con otro número de disparos se
rechaza sin entregar nada; y que las fotos originales no cambian, ni en el camino feliz ni en los
que fallan.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents.composicion import ComposicionInvalida
from apps.vuelos import vuelo_rtk
from apps.vuelos.test_ficha_foto import jpeg_de_dji
from apps.vuelos.test_vuelo_proceso import (
    A_ENU,
    A_LL,
    EPSG,
    N_FOTOS,
    SEMANA,
    T0_TOW,
    _antena,
    _desfase,
    _instante,
)

#: Las banderas de cada foto: se reparten fija, flotante y simple, con dos casos raros.
CALIDAD_POR_BANDERA = {"50": "fija", "34": "flotante", "16": "simple"}
BANDERA_AUSENTE = 5
BANDERA_RARA = 6


def _bandera(i: int) -> str | None:
    if i == BANDERA_AUSENTE:
        return None
    if i == BANDERA_RARA:
        return "99"
    return ("50", "34", "16")[i % 3]


def _calidad_esperada(i: int) -> str:
    b = _bandera(i)
    if b is None:
        return "no informada"
    return CALIDAD_POR_BANDERA.get(b, f"no reconocida (código {b})")


def _antena_ll(i: int) -> tuple[float, float, float]:
    este, norte, alto = _antena(_instante(i))
    lon, lat = A_LL.transform(este, norte)
    return lat, lon, alto


def _mrk(*, desplazar_lat_grados: float = 0.0, sumar_altura_m: float = 0.0, sin_posicion=False):
    lineas = []
    for i in range(N_FOTOS):
        n, e, v = _desfase(i)
        lat, lon, alto = _antena_ll(i)
        posicion = (
            ""
            if sin_posicion
            else (
                f"{lat + desplazar_lat_grados:.8f},Lat\t{lon:.8f},Lon\t"
                f"{alto + sumar_altura_m:.3f},Ellh\t"
            )
        )
        lineas.append(
            f"{i + 1}\t{T0_TOW + _instante(i):.6f}\t[{SEMANA}]\t{n},N\t{e},E\t{v},V\t{posicion}"
            "1.5, 1.6, 3.5\t16,Q"
        )
    return ("\n".join(lineas) + "\n").encode()


def _foto(i: int, **cambios) -> bytes:
    lat, lon, alto = _antena_ll(i)
    return jpeg_de_dji(
        GpsLatitude=f"{lat:.9f}",
        GpsLongitude=f"{lon:.9f}",
        AbsoluteAltitude=f"{alto:+.3f}",
        RtkFlag=_bandera(i),
        RtkStdLat="0.01573",
        RtkStdLon="0.01621",
        RtkStdHgt="0.03532",
        **cambios,
    )


def _carpeta(tmp_path: Path, n: int = N_FOTOS) -> Path:
    carpeta = tmp_path / "fotos"
    carpeta.mkdir()
    for i in range(n):
        (carpeta / f"DJI_20251229123852_{i + 1:04d}_V.JPG").write_bytes(_foto(i))
    return carpeta


def _procesar(tmp_path, *, mrk: bytes | None = None, nombre="vuelo_Timestamp.MRK", **extra):
    fichas = vuelo_rtk.leer_carpeta(_carpeta(tmp_path))
    argumentos = {
        "fichas": fichas,
        "disparos": mrk if mrk is not None else _mrk(),
        "nombre_de_disparos": nombre,
        "sistema": str(EPSG),
    }
    argumentos.update(extra)
    return vuelo_rtk.procesar(**argumentos)


def _filas(r) -> list[dict]:
    return list(csv.DictReader(io.StringIO(r.archivos["fotos.csv"].decode())))


class TestLaPosicionSaleDeLasFotos:
    def test_los_entregables_y_el_resumen(self, tmp_path):
        r = _procesar(tmp_path)
        assert set(r.archivos) == {
            "fotos.csv", "fotos.geojson", "fotos.kml", "calidad.md", "vuelo.json",
        }  # fmt: skip
        assert r.resumen["fotos"] == r.resumen["con_posicion"] == N_FOTOS
        assert r.resumen["sin_posicion"] == 0 and r.resumen["puntos_de_trayectoria"] == 0
        assert r.resumen["desfase_aplicado"] == N_FOTOS
        assert r.resumen["contraste_maximo_mm"] is None
        assert r.resumen["trayectoria_de"].startswith("las fotos")

    def test_la_posicion_de_la_camara_coincide_con_el_calculo_a_mano(self, tmp_path):
        """El oráculo es la cuadrícula: antena + (N, E) y − V, sin pasar por `vuelo_sync`."""
        filas = _filas(_procesar(tmp_path))
        peores = [0.0, 0.0, 0.0]
        for i, fila in enumerate(filas):
            n, e, v = _desfase(i)
            ea, na, ha = _antena(_instante(i))
            este, norte = A_ENU.transform(float(fila["lon"]), float(fila["lat"]))
            peores[0] = max(peores[0], abs(este - (ea + e / 1000)))
            peores[1] = max(peores[1], abs(norte - (na + n / 1000)))
            peores[2] = max(peores[2], abs(float(fila["altura_m"]) - (ha - v / 1000)))
        assert max(peores) < 0.0015, f"el peor caso es de {max(peores) * 1000:.2f} mm"

    def test_sin_el_desfase_es_la_posicion_de_la_antena_y_el_csv_lo_dice(self, tmp_path):
        r = _procesar(tmp_path, aplicar_desfase=False)
        filas = _filas(r)
        assert {f["desfase_aplicado"] for f in filas} == {"no"}
        for i, fila in enumerate(filas):
            lat, lon, alto = _antena_ll(i)
            assert float(fila["lat"]) == pytest.approx(lat, abs=1e-9)
            assert float(fila["lon"]) == pytest.approx(lon, abs=1e-9)
            assert float(fila["altura_m"]) == pytest.approx(alto, abs=1e-3)
        assert "de la **antena** (sin el desfase" in r.archivos["calidad.md"].decode()

    def test_las_desviaciones_del_dron_van_a_sus_columnas(self, tmp_path):
        fila = _filas(_procesar(tmp_path))[0]
        assert (fila["sdn_m"], fila["sde_m"], fila["sdu_m"]) == ("0.0157", "0.0162", "0.0353")

    def test_los_nombres_y_los_disparos_son_los_de_la_carpeta_y_el_mrk(self, tmp_path):
        filas = _filas(_procesar(tmp_path))
        assert [f["foto"] for f in filas][:2] == [
            "DJI_20251229123852_0001_V.JPG",
            "DJI_20251229123852_0002_V.JPG",
        ]
        assert float(filas[0]["t_gps_s"]) == pytest.approx(SEMANA * 604_800 + T0_TOW + _instante(0))
        assert filas[3]["desfase_antena_n_mm"] == f"{_desfase(3)[0]:.1f}"

    def test_el_geojson_y_el_kml_traen_una_por_foto_y_en_el_sistema_dicho(self, tmp_path):
        r = _procesar(tmp_path)
        gj = json.loads(r.archivos["fotos.geojson"])
        assert len(gj["features"]) == N_FOTOS and gj["sistema"] == "WGS84"
        assert r.archivos["fotos.kml"].decode().count("<Placemark>") == N_FOTOS


class TestLaCalidadSaleDeLaBandera:
    def test_cada_foto_dice_su_calidad_y_lo_que_falta_se_dice(self, tmp_path):
        filas = _filas(_procesar(tmp_path))
        assert [f["calidad"] for f in filas] == [_calidad_esperada(i) for i in range(N_FOTOS)]
        assert filas[BANDERA_AUSENTE]["calidad"] == "no informada"
        assert filas[BANDERA_RARA]["calidad"] == "no reconocida (código 99)"

    def test_lo_que_no_es_fijo_se_avisa_con_la_cuenta(self, tmp_path):
        r = _procesar(tmp_path)
        fijas = sum(1 for i in range(N_FOTOS) if _calidad_esperada(i) == "fija")
        assert r.resumen["fotos_con_posicion_fija"] == fijas
        aviso = next(a for a in r.avisos if "no tienen posición fija" in a)
        assert aviso.startswith(f"{N_FOTOS - fijas} foto(s)")

    def test_el_informe_tiene_la_tabla_de_banderas_y_la_nota_del_estado_del_gps(self, tmp_path):
        texto = _procesar(tmp_path).archivos["calidad.md"].decode()
        assert "| 50 | fija |" in texto and "| 34 | flotante |" in texto
        assert "| — | no informada | 1 |" in texto
        assert "| 99 | no reconocida (código 99) | 1 |" in texto
        assert "Solo el 16 se ha visto en un archivo real" in texto

    def test_el_visor_recibe_la_calidad_y_las_dibuja_con_su_forma(self, tmp_path):
        datos = json.loads(_procesar(tmp_path).archivos["vuelo.json"])
        assert [f["calidad"] for f in datos["fotos"]][:3] == ["fija", "flotante", "simple"]


class TestLaAlturaSoloSeLlamaElipsoidalSiSeComprueba:
    def test_si_coincide_con_la_ellh_del_mrk_la_referencia_es_elipsoidal(self, tmp_path):
        r = _procesar(tmp_path)
        assert r.referencia_de_altura.startswith("elipsoidal")
        assert {f["referencia_de_altura"] for f in _filas(r)} == {r.referencia_de_altura}
        texto = r.archivos["calidad.md"].decode()
        assert "**Coinciden**: es la altura elipsoidal." in texto
        assert not any("Ellh" in a for a in r.avisos)

    def test_si_no_coincide_no_se_afirma_y_se_avisa(self, tmp_path):
        r = _procesar(tmp_path, mrk=_mrk(sumar_altura_m=35.0))
        assert "elipsoidal" not in r.referencia_de_altura.split("no coincide")[0]
        assert "no afirmada" in r.referencia_de_altura
        assert any("difiere de la «Ellh»" in a and "35.000 m" in a for a in r.avisos)
        assert "**No coinciden**" in r.archivos["calidad.md"].decode()

    def test_si_el_mrk_no_trae_posicion_no_hay_con_que_comprobar_y_se_dice(self, tmp_path):
        r = _procesar(tmp_path, mrk=_mrk(sin_posicion=True))
        assert "no comprobada" in r.referencia_de_altura
        assert any("no trae la posición de sus disparos" in a for a in r.avisos)
        assert "no hay con qué comprobar" in r.archivos["calidad.md"].decode()


class TestLoQueNoSeAceptaYNoSeEntregaNada:
    def test_un_mrk_de_otro_vuelo_se_rechaza_con_la_foto_y_la_distancia(self, tmp_path):
        # 0,0001° de latitud son unos 11 m: las fotos no son de ese .MRK.
        with pytest.raises(ComposicionInvalida, match=r"queda a 11\.\d\d m .* No se entregó nada"):
            _procesar(tmp_path, mrk=_mrk(desplazar_lat_grados=0.0001))

    def test_un_desfase_ya_aplicado_por_el_dron_tambien_se_detiene(self, tmp_path):
        # 5 cm de diferencia: más que el redondeo del .MRK, menos que un vuelo ajeno.
        with pytest.raises(ComposicionInvalida, match="ya aplicó"):
            _procesar(tmp_path, mrk=_mrk(desplazar_lat_grados=0.5 / 111_132.0))

    def test_distinto_numero_de_fotos_y_disparos_no_se_empareja(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_20251229123852_0040_V.JPG").unlink()
        fichas = vuelo_rtk.leer_carpeta(carpeta)
        with pytest.raises(ComposicionInvalida, match="no se pueden emparejar"):
            vuelo_rtk.procesar(
                fichas=fichas, disparos=_mrk(), nombre_de_disparos="a.MRK", sistema=str(EPSG)
            )

    def test_sin_mrk_no_se_procesa(self, tmp_path):
        with pytest.raises(ComposicionInvalida, match="hace falta el archivo .MRK"):
            _procesar(tmp_path, nombre="tiempos.txt")

    @pytest.mark.parametrize("sistema", ["medir", ""])
    def test_el_sistema_no_se_mide_ni_se_adivina(self, tmp_path, sistema):
        with pytest.raises(ComposicionInvalida, match="no hay con qué medir"):
            _procesar(tmp_path, sistema=sistema)

    def test_un_sistema_que_no_se_sabe_leer_se_rechaza(self, tmp_path):
        with pytest.raises(ComposicionInvalida, match="sistema antiguo"):
            _procesar(tmp_path, sistema="24879")

    def test_sin_fotos_no_hay_nada_que_leer(self, tmp_path):
        vacia = tmp_path / "vacia"
        vacia.mkdir()
        with pytest.raises(ComposicionInvalida, match="no trae ninguna foto"):
            vuelo_rtk.leer_carpeta(vacia)


class TestUnaFotoSinPosicion:
    def test_se_cuenta_con_su_motivo_y_no_entra_en_los_mapas(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_20251229123852_0003_V.JPG").write_bytes(
            jpeg_de_dji(xmp=b"", con_exif_gps=False)
        )
        r = vuelo_rtk.procesar(
            fichas=vuelo_rtk.leer_carpeta(carpeta),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            sistema=str(EPSG),
        )
        assert r.resumen["sin_posicion"] == 1 and r.resumen["con_posicion"] == N_FOTOS - 1
        fila = _filas(r)[2]
        assert fila["lat"] == "" and "no trae posición" in fila["motivo"]
        assert len(json.loads(r.archivos["fotos.geojson"])["features"]) == N_FOTOS - 1
        assert any("sin posición" in a for a in r.avisos)


class TestElSistemaYElDatum:
    def test_un_sistema_declarado_en_otro_marco_que_dicen_las_fotos_se_avisa(self, tmp_path):
        # Las fotos dicen «WGS-84»; SIRGAS-Chile no es WGS84: se entrega tal cual y se dice.
        r = _procesar(tmp_path, sistema="5361")
        assert any("Las fotos dicen «WGS-84»" in a for a in r.avisos)
        assert r.resumen["sistema_epsg"] == 5361

    def test_con_wgs84_no_hay_aviso_y_el_visor_dice_como_se_eligio(self, tmp_path):
        r = _procesar(tmp_path)
        assert not any("WGS-84" in a for a in r.avisos)
        assert "declarado por usted" in r.resumen["sistema_como"]
        assert "no dice en qué marco está la corrección RTK" in r.archivos["calidad.md"].decode()


class TestElVisorNoInventaUnRecorrido:
    def test_no_hay_trayectoria_y_las_fotos_traen_su_desfase(self, tmp_path):
        datos = json.loads(_procesar(tmp_path).archivos["vuelo.json"])
        assert datos["trayectoria"] == [] and datos["trayectoria_total"] == 0
        assert len(datos["fotos"]) == N_FOTOS and datos["sistema"]["epsg"] == EPSG
        assert all(f["miniatura"] for f in datos["fotos"])

    def test_el_origen_sale_de_las_fotos(self, tmp_path):
        datos = json.loads(_procesar(tmp_path).archivos["vuelo.json"])
        este0, norte0 = datos["origen"]["este"], datos["origen"]["norte"]
        f = datos["fotos"][0]
        ea, na, _ = _antena(_instante(0))
        assert este0 + f["x"] == pytest.approx(ea + _desfase(0)[1] / 1000, abs=0.01)
        assert norte0 + f["y"] == pytest.approx(na + _desfase(0)[0] / 1000, abs=0.01)


def _huellas(rutas) -> dict:
    return {
        str(r): (hashlib.sha256(Path(r).read_bytes()).hexdigest(), Path(r).stat().st_mtime_ns)
        for r in rutas
    }


class TestLasFotosNoSeTocan:
    def test_camino_feliz(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        antes = _huellas(sorted(carpeta.iterdir()))
        vuelo_rtk.procesar(
            fichas=vuelo_rtk.leer_carpeta(carpeta),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            sistema=str(EPSG),
        )
        assert _huellas(sorted(carpeta.iterdir())) == antes

    def test_camino_que_falla_por_una_foto_rota(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_20251229123852_0007_V.JPG").write_bytes(b"no es un jpeg")
        antes = _huellas(sorted(carpeta.iterdir()))
        with pytest.raises(ComposicionInvalida, match="0007"):
            vuelo_rtk.leer_carpeta(carpeta)
        assert _huellas(sorted(carpeta.iterdir())) == antes

    def test_camino_que_falla_por_un_mrk_ajeno(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        antes = _huellas(sorted(carpeta.iterdir()))
        with pytest.raises(ComposicionInvalida):
            vuelo_rtk.procesar(
                fichas=vuelo_rtk.leer_carpeta(carpeta),
                disparos=_mrk(desplazar_lat_grados=0.001),
                nombre_de_disparos="a.MRK",
                sistema=str(EPSG),
            )
        assert _huellas(sorted(carpeta.iterdir())) == antes


def _ogrinfo() -> str | None:
    encontrado = shutil.which("ogrinfo")
    if encontrado:
        return encontrado
    candidato = Path(r"C:\Program Files\QGIS 4.0.2\bin\ogrinfo.exe")
    return str(candidato) if candidato.exists() else None


@pytest.mark.oraculo
@pytest.mark.skipif(_ogrinfo() is None, reason="GDAL no está en esta máquina")
def test_ogrinfo_abre_el_geojson_y_el_kml_y_cuenta_las_mismas_fotos(tmp_path):
    """El oráculo del GeoJSON y el KML: GDAL, que no los escribió, cuenta las fotos."""
    r = _procesar(tmp_path)
    (tmp_path / "f.geojson").write_bytes(r.archivos["fotos.geojson"])
    (tmp_path / "f.kml").write_bytes(r.archivos["fotos.kml"])
    for nombre in ("f.geojson", "f.kml"):
        salida = subprocess.run(  # noqa: S603 - argumentos fijos y rutas de la prueba
            [_ogrinfo(), "-ro", "-so", "-al", str(tmp_path / nombre)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
        assert f"Feature Count: {N_FOTOS}" in salida, nombre


# --- La pantalla y el trabajo -----------------------------------------------------------------


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    )
    return client


def _enviar(sesion, tmp_path, *, carpeta=True, mrk=None, nombre="vuelo_Timestamp.MRK", **extra):
    disparos = tmp_path / nombre
    if mrk is not False:  # `False`: el .MRK ya está escrito y no se vuelve a tocar
        disparos.write_bytes(mrk if mrk is not None else _mrk())
    datos = {
        "origen": "fotos",
        "disparos": str(disparos),
        "sistema_fotos": str(EPSG),
        "aplicar_desfase": "on",
        **extra,
    }
    if carpeta is True:
        datos["carpeta_de_fotos"] = str(_carpeta(tmp_path))
    elif carpeta:
        datos["carpeta_de_fotos"] = str(carpeta)
    return sesion.post(reverse("documents:vuelo_dron"), datos)


@pytest.mark.django_db
class TestLaPantalla:
    def test_la_tercera_respuesta_esta_a_la_vista_y_dice_lo_que_hace(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        assert "¿De dónde sale la posición precisa?" in cuerpo
        assert "Las fotos ya traen la posición RTK" in cuerpo
        assert "El dron voló con RTK" in cuerpo
        assert 'id="id_origen_fotos"' in cuerpo and "vuelo-solo-fotos" in cuerpo
        # El paso de la carpeta pasa a ser obligatorio con esta entrada: se dice en la página.
        assert "La carpeta con los JPG del vuelo, tal como salieron del dron" in cuerpo

    def test_sin_carpeta_se_dice_con_el_formulario_delante(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        respuesta = _enviar(sesion, tmp_path, carpeta=False)
        assert "Elija la carpeta de fotos" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_sin_mrk_se_dice(self, sesion, tmp_path):
        respuesta = _enviar(sesion, tmp_path, disparos="")
        # `disparos` del formulario queda vacío: la vista pide el .MRK.
        assert "Faltan los disparos de la cámara" in respuesta.content.decode()

    def test_una_lista_de_tiempos_no_vale_con_rtk(self, sesion, tmp_path):
        respuesta = _enviar(sesion, tmp_path, nombre="tiempos.txt")
        assert "no es un .MRK" in respuesta.content.decode()

    def test_el_sistema_no_se_mide_ni_se_adivina_aqui(self, sesion, tmp_path):
        respuesta = _enviar(sesion, tmp_path, sistema_fotos="")
        assert "Elija el sistema de coordenadas del visor" in respuesta.content.decode()
        assert "no se supone" in respuesta.content.decode()

    def test_el_selector_no_trae_ninguno_elegido(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelo_dron")).content.decode()
        bloque = cuerpo[cuerpo.index('id="id_sistema_fotos"') :].split("</select>")[0]
        assert 'value="" selected' in bloque and "Elija el sistema…" in bloque
        assert bloque.count("selected") == 1
        assert "medir" not in bloque

    def test_un_sistema_que_no_se_ofrece_se_rechaza(self, sesion, tmp_path):
        respuesta = _enviar(sesion, tmp_path, sistema_fotos="24879")
        assert "no es de los que se ofrecen" in respuesta.content.decode()

    def test_distinto_numero_de_fotos_y_disparos_se_dice_antes_de_encolar(self, sesion, tmp_path):
        from apps.jobs.models import ConversionJob

        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_20251229123852_0001_V.JPG").unlink()
        respuesta = _enviar(sesion, tmp_path, carpeta=carpeta)
        assert "no se pueden emparejar" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_una_carpeta_fuera_de_las_raices_no_vale(self, sesion, tmp_path):
        respuesta = _enviar(sesion, tmp_path, carpeta=r"C:\Windows")
        assert respuesta.status_code == 200 and "fuera" in respuesta.content.decode().lower()


def _correr(sesion, tmp_path, **extra):
    from apps.jobs import despachador
    from apps.jobs.models import ConversionJob

    respuesta = _enviar(sesion, tmp_path, **extra)
    assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
    assert despachador.procesar_una_vez() == 1
    return ConversionJob.objects.latest("created_at")


@pytest.mark.django_db
class TestElTrabajo:
    def test_de_extremo_a_extremo_el_zip_trae_lo_que_dice(self, sesion, tmp_path):
        trabajo = _correr(sesion, tmp_path)
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.herramienta == "vuelo_dron" and trabajo.progress_percent == 100
        assert trabajo.options["origen"] == "fotos"
        with zipfile.ZipFile(trabajo.output_path) as z:
            assert sorted(z.namelist()) == sorted(
                ["fotos.csv", "fotos.geojson", "fotos.kml", "calidad.md", "vuelo.json"]
            )
        assert trabajo.verification["piezas_verificadas"] == 5
        assert trabajo.verification["fotos"] == N_FOTOS
        assert trabajo.verification["trayectoria_de"].startswith("las fotos")

    def test_la_unica_entrada_es_el_mrk(self, sesion, tmp_path):
        trabajo = _correr(sesion, tmp_path)
        assert [e.papel for e in trabajo.entradas.all()] == ["disparos"]

    def test_un_trabajo_rtk_no_pide_rtklib(self, sesion, tmp_path, settings):
        from apps.documents import motor

        settings.RTKLIB_RNX2RTKP = ""
        assert motor.disponibilidad("vuelo_dron", {"origen": "fotos"}).disponible

    def test_las_fotos_y_el_mrk_no_cambian(self, sesion, tmp_path):
        carpeta = _carpeta(tmp_path)
        mrk = tmp_path / "vuelo_Timestamp.MRK"
        mrk.write_bytes(_mrk())
        antes = _huellas([*sorted(carpeta.iterdir()), mrk])
        trabajo = _correr(sesion, tmp_path, carpeta=carpeta, mrk=False)
        assert trabajo.status == "done", trabajo.reason_detail
        assert _huellas([*sorted(carpeta.iterdir()), mrk]) == antes

    def test_si_el_mrk_es_ajeno_el_trabajo_falla_sin_zip_y_sin_tocar_las_fotos(
        self, sesion, tmp_path
    ):
        carpeta = _carpeta(tmp_path)
        antes = _huellas(sorted(carpeta.iterdir()))
        trabajo = _correr(sesion, tmp_path, carpeta=carpeta, mrk=_mrk(desplazar_lat_grados=0.0001))
        assert trabajo.status == "error" and "No se entregó nada" in trabajo.reason_detail
        assert not Path(trabajo.output_path).exists()
        assert _huellas(sorted(carpeta.iterdir())) == antes

    def test_el_visor_dibuja_los_puntos_sin_recorrido(self, sesion, tmp_path):
        trabajo = _correr(sesion, tmp_path)
        pagina = sesion.get(reverse("documents:vuelo_ver", args=[trabajo.pk]))
        assert pagina.status_code == 200 and "EPSG:32719" in pagina.content.decode()
        datos = json.loads(sesion.get(reverse("documents:vuelo_datos", args=[trabajo.pk])).content)
        assert datos["trayectoria"] == [] and len(datos["fotos"]) == N_FOTOS
        miniatura = sesion.get(reverse("documents:vuelo_miniatura", args=[trabajo.pk, 2]))
        assert miniatura.status_code == 200 and miniatura["Content-Type"] == "image/jpeg"
