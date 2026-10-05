"""El motor de Trimble: el plan, la sonda y el verificador, sin el programa de Trimble.

El `argv` se compara entero y en orden: es lo que el corredor escribe en la bitácora y lo que
se mira cuando la salida no es la esperada. El verificador se prueba con zips armados a mano,
que es donde caben todos los modales que se midieron en el convertidor de verdad.
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from apps.engines import sondas
from apps.engines.base import ParDeFormatos
from apps.formats.tests.constructor import rinex_minimo, trimble_minimo
from apps.gnss import empaquetar, motores

pytestmark = pytest.mark.django_db


def _nav(version="3.04") -> str:
    cabecera = f"{version:>9}           NAVIGATION DATA     M".ljust(60) + "RINEX VERSION / TYPE"
    return cabecera + "\n" + "".ljust(60) + "END OF HEADER\n"


def _zip(tmp_path: Path, archivos: dict[str, str | bytes], nombre="salida.parcial.zip") -> Path:
    ruta = tmp_path / nombre
    with zipfile.ZipFile(ruta, "w") as paquete:
        for clave, contenido in archivos.items():
            paquete.writestr(clave, contenido)
    return ruta


def _trabajo(tmp_path, **opciones):
    origen = tmp_path / "GMLA.T02"
    origen.write_bytes(trimble_minimo())
    return SimpleNamespace(
        pk="0f5a",
        source_path=str(origen),
        source_size_bytes=origen.stat().st_size,
        output_path=str(tmp_path / "GMLA_rinex.zip"),
        options=opciones,
    )


@pytest.fixture(autouse=True)
def carpeta_de_trabajo(tmp_path, settings):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.WINEPREFIX = ""


class TestElPar:
    def test_declara_trimble_a_rinex_y_nada_mas(self):
        assert motores.MotorTrimbleARinex().pares() == {ParDeFormatos("trimble_t0x", "rinex")}

    def test_va_por_delante_de_cualquier_otro(self):
        """No hay otro que lea un T02, pero la prioridad es la que dice quién gana si lo hay."""
        assert motores.MotorTrimbleARinex.prioridad <= 10


class TestLaSonda:
    def test_sin_ruta_dice_que_es_el_programa_de_trimble(self, monkeypatch):
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: "")
        estado = sondas.sondar_trimble_rinex()
        assert not estado.disponible
        assert estado.codigo_motivo == "sin-conversor-trimble"
        assert "Trimble Business Center" in estado.sugerencia

    def test_una_ruta_que_no_existe(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: str(tmp_path / "no.exe"))
        estado = sondas.sondar_trimble_rinex()
        assert estado.codigo_motivo == "sin-conversor-trimble"
        assert "no hay ningún archivo" in estado.mensaje

    def test_en_linux_sin_wine_lo_dice_con_su_propio_motivo(self, monkeypatch, tmp_path):
        """No es lo mismo que falte el programa de Trimble que que no haya con qué correrlo."""
        exe = tmp_path / "convertToRinex.exe"
        exe.write_bytes(b"MZ")
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: str(exe))
        monkeypatch.setattr(sondas.os, "name", "posix")
        monkeypatch.setattr(sondas.shutil, "which", lambda _nombre: None)
        estado = sondas.sondar_trimble_rinex()
        assert estado.codigo_motivo == "sin-wine"
        assert "apt install wine" in estado.sugerencia

    def test_con_wine_y_el_programa_esta_disponible(self, monkeypatch, tmp_path):
        exe = tmp_path / "convertToRinex.exe"
        exe.write_bytes(b"MZ")
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: str(exe))
        monkeypatch.setattr(sondas.os, "name", "posix")
        monkeypatch.setattr(sondas.shutil, "which", lambda _nombre: "/usr/bin/wine")
        estado = sondas.sondar_trimble_rinex()
        assert estado.disponible
        assert "bajo Wine" in estado.version

    def test_lo_configurado_gana_a_lo_habitual(self, settings):
        settings.TRIMBLE_RINEX = '"D:\\otro\\convertToRinex.exe"'
        assert sondas.ruta_de_trimble_rinex() == "D:\\otro\\convertToRinex.exe"

    def test_los_dos_motivos_existen_en_el_catalogo(self):
        from apps.jobs import motivos

        for codigo in (
            "sin-conversor-trimble",
            "sin-wine",
            "crudo-incompleto",
            "rinex-invalido",
            "rinex-sin-epocas",
        ):
            assert codigo in motivos.MOTIVOS


class TestElPlanEnWindows:
    @pytest.fixture(autouse=True)
    def sin_wine(self, monkeypatch):
        monkeypatch.setattr(sondas, "necesita_wine", lambda: False)
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: "C:/T/convertToRinex.exe")

    def test_el_argv_completo_y_en_orden(self, tmp_path):
        trabajo = _trabajo(tmp_path)
        plan = motores.MotorTrimbleARinex().plan(trabajo)
        carpeta = motores._carpeta_de_transito(trabajo)
        assert plan.argv == (
            "C:/T/convertToRinex.exe",
            trabajo.source_path,
            "-p",
            str(carpeta),
            "-v",
            "3.04",
            "-mx",
        )

    def test_el_segundo_paso_empaqueta_en_el_parcial(self, tmp_path):
        trabajo = _trabajo(tmp_path)
        plan = motores.MotorTrimbleARinex().plan(trabajo)
        carpeta = motores._carpeta_de_transito(trabajo)
        (paso,) = plan.posteriores
        assert paso[1:] == (
            "-m",
            "apps.gnss.empaquetar",
            str(carpeta),
            str(tmp_path / "GMLA_rinex.parcial.zip"),
        )
        # El principal no escribe el parcial: lo escribe el segundo.
        assert plan.salida_en_posteriores

    def test_es_mudo_y_no_hay_que_esperar_avance(self, tmp_path):
        assert not motores.MotorTrimbleARinex().plan(_trabajo(tmp_path)).emite_progreso

    def test_las_opciones_se_traducen_a_sus_banderas(self, tmp_path):
        plan = motores.MotorTrimbleARinex().plan(
            _trabajo(
                tmp_path,
                version="2.11",
                navegacion_unica=False,
                doppler=True,
                snr=True,
                marcador="PUNTO-1",
            )
        )
        # Sin `-mx`, porque se pidió una navegación por constelación.
        assert plan.argv[-6:] == ("-v", "2.11", "-d", "-s", "-mo", "PUNTO-1")

    def test_la_carpeta_de_transito_cuelga_de_la_de_trabajo_y_lleva_la_marca(self, tmp_path):
        carpeta = motores._carpeta_de_transito(_trabajo(tmp_path))
        assert carpeta.parent == tmp_path / "trabajo"
        assert ".parcial." in carpeta.name

    def test_un_intento_anterior_no_deja_nada_en_la_carpeta(self, tmp_path):
        """Mezclar su salida con la de este sería entregar archivos de otra conversión."""
        trabajo = _trabajo(tmp_path)
        carpeta = motores._carpeta_de_transito(trabajo)
        carpeta.mkdir(parents=True)
        (carpeta / "viejo.23o").write_text("de un intento anterior")
        motores.MotorTrimbleARinex().plan(trabajo)
        assert list(carpeta.iterdir()) == []

    def test_el_plazo_crece_con_el_tamano(self, tmp_path):
        chico = _trabajo(tmp_path)
        grande = _trabajo(tmp_path)
        grande.source_size_bytes = 200 * 1_048_576
        motor = motores.MotorTrimbleARinex()
        assert motor.plan(grande).timeout_s > motor.plan(chico).timeout_s

    def test_una_version_que_no_se_ofrece(self, tmp_path):
        with pytest.raises(ValueError, match="versión"):
            motores.MotorTrimbleARinex().plan(_trabajo(tmp_path, version="9.99"))

    @pytest.mark.parametrize("marcador", ["-mx", "a b", "../x", 'a"b', "x" * 61, "-"])
    def test_un_nombre_de_punto_que_se_leeria_como_opcion_o_ruta(self, tmp_path, marcador):
        with pytest.raises(ValueError, match="nombre del punto"):
            motores.MotorTrimbleARinex().plan(_trabajo(tmp_path, marcador=marcador))


class TestElPlanBajoWine:
    @pytest.fixture(autouse=True)
    def con_wine(self, monkeypatch):
        monkeypatch.setattr(sondas, "necesita_wine", lambda: True)
        monkeypatch.setattr(sondas, "ruta_de_trimble_rinex", lambda: "/opt/trimble/convert.exe")
        monkeypatch.setattr(motores.shutil, "which", lambda n: f"/usr/bin/{n}")
        monkeypatch.delenv("DISPLAY", raising=False)

    def test_las_rutas_van_como_de_windows(self, tmp_path):
        """Wine monta la raíz como `Z:`, y el programa de Windows no entiende `/var/…`."""
        assert motores.a_ruta_de_wine(PurePosixPath("/var/lib/x/a.T02")) == "Z:\\var\\lib\\x\\a.T02"

    def test_va_con_xvfb_y_wine_delante(self, tmp_path):
        plan = motores.MotorTrimbleARinex().plan(_trabajo(tmp_path))
        assert plan.argv[:4] == (
            "/usr/bin/xvfb-run",
            "-a",
            "/usr/bin/wine",
            "/opt/trimble/convert.exe",
        )
        assert plan.argv[4].startswith("Z:")
        assert plan.argv[plan.argv.index("-p") + 1].startswith("Z:")

    def test_el_prefijo_de_wine_viaja_en_el_entorno_del_hijo(self, tmp_path, settings):
        settings.WINEPREFIX = "/var/lib/aeroconvert/wine"
        plan = motores.MotorTrimbleARinex().plan(_trabajo(tmp_path))
        assert plan.env["WINEPREFIX"] == "/var/lib/aeroconvert/wine"
        assert plan.env["WINEDEBUG"] == "-all"

    def test_y_tarda_mas_que_en_windows(self, tmp_path, monkeypatch):
        trabajo = _trabajo(tmp_path)
        trabajo.source_size_bytes = 50 * 1_048_576
        bajo_wine = motores.MotorTrimbleARinex().plan(trabajo).timeout_s
        monkeypatch.setattr(sondas, "necesita_wine", lambda: False)
        assert bajo_wine > motores.MotorTrimbleARinex().plan(trabajo).timeout_s


class TestElVerificador:
    def _verificar(self, tmp_path, archivos, version="3.04", crudo=""):
        return motores.verificar_rinex(_zip(tmp_path, archivos), version=version, crudo=crudo)

    def test_un_zip_bueno(self, tmp_path):
        veredicto = self._verificar(tmp_path, {"a.23o": rinex_minimo(epocas=10), "a.23mix": _nav()})
        assert veredicto.correcta, veredicto.motivo
        d = veredicto.detalles
        assert d["epocas"] == 10
        assert d["esperadas"] == 10
        assert d["intervalo_s"] == 30.0
        assert d["marcador"] == "GMLA"
        assert d["receptor"] == "TRIMBLE NETR9"
        assert d["constelaciones"] == "G R"
        assert d["primera"] == "2023-01-31 17:00:00"
        assert d["avisos"] == []
        assert [a["nombre"] for a in d["archivos"]] == ["a.23mix", "a.23o"]

    def test_algo_que_no_es_un_zip(self, tmp_path):
        ruta = tmp_path / "x.parcial.zip"
        ruta.write_bytes(b"PK no del todo")
        veredicto = motores.verificar_rinex(ruta, version="3.04")
        assert veredicto.codigo_motivo == "rinex-invalido"

    def test_un_zip_vacio(self, tmp_path):
        assert self._verificar(tmp_path, {}).codigo_motivo == "rinex-invalido"

    def test_un_archivo_que_no_es_rinex(self, tmp_path):
        veredicto = self._verificar(tmp_path, {"a.23o": "esto no es un RINEX\n"})
        assert veredicto.codigo_motivo == "rinex-invalido"
        assert "a.23o" in veredicto.motivo

    def test_la_version_que_sale_es_la_que_se_pidio(self, tmp_path):
        veredicto = self._verificar(
            tmp_path, {"a.23o": rinex_minimo(version="2.11"), "a.23n": _nav("2.11")}
        )
        assert veredicto.codigo_motivo == "rinex-invalido"
        assert "3.04" in veredicto.motivo and "2.11" in veredicto.motivo

    def test_solo_navegacion_no_es_una_entrega(self, tmp_path):
        veredicto = self._verificar(tmp_path, {"a.23n": _nav()})
        assert veredicto.codigo_motivo == "rinex-invalido"
        assert "observación" in veredicto.motivo

    def test_cabecera_sin_una_epoca(self, tmp_path):
        """El caso de 200 bytes de basura: el convertidor dice «Success» y escribe 1.476 bytes."""
        veredicto = self._verificar(tmp_path, {"a.23o": rinex_minimo(epocas=0)})
        assert veredicto.codigo_motivo == "rinex-sin-epocas"

    def test_cortado_a_mitad_de_una_epoca(self, tmp_path):
        veredicto = self._verificar(
            tmp_path, {"a.23o": rinex_minimo(truncar_la_ultima=True), "a.23n": _nav()}
        )
        assert veredicto.codigo_motivo == "rinex-invalido"
        assert "cortado" in veredicto.motivo

    def test_un_hueco_avisa_pero_no_tumba(self, tmp_path):
        veredicto = self._verificar(
            tmp_path, {"a.23o": rinex_minimo(epocas=10, huecos_en=(4, 5)), "a.23n": _nav()}
        )
        assert veredicto.correcta
        assert veredicto.detalles["huecos"] == 1
        assert any("Faltan 2 épocas" in a for a in veredicto.detalles["avisos"])

    def test_sin_navegacion_avisa(self, tmp_path):
        veredicto = self._verificar(tmp_path, {"a.23o": rinex_minimo()})
        assert veredicto.correcta
        assert any("navegación" in a for a in veredicto.detalles["avisos"])

    def test_el_receptor_del_crudo_y_el_del_rinex_se_cruzan(self, tmp_path):
        crudo = tmp_path / "a.T02"
        crudo.write_bytes(trimble_minimo(modelo="TRIMBLE NETR9"))
        veredicto = self._verificar(
            tmp_path, {"a.23o": rinex_minimo(), "a.23n": _nav()}, crudo=str(crudo)
        )
        assert veredicto.correcta
        assert not any("crudo es de un" in a for a in veredicto.detalles["avisos"])
        assert veredicto.detalles["bloques_del_crudo"] == 1

    def test_si_no_coinciden_se_dice(self, tmp_path):
        crudo = tmp_path / "a.T04"
        crudo.write_bytes(trimble_minimo(modelo="TRIMBLE R12i", serie="6212F01411"))
        veredicto = self._verificar(
            tmp_path, {"a.23o": rinex_minimo(), "a.23n": _nav()}, crudo=str(crudo)
        )
        assert veredicto.correcta
        assert any("R12i" in a and "NETR9" in a for a in veredicto.detalles["avisos"])

    def test_un_crudo_que_no_se_lee_no_tumba_la_verificacion(self, tmp_path):
        veredicto = self._verificar(
            tmp_path,
            {"a.23o": rinex_minimo(), "a.23n": _nav()},
            crudo=str(tmp_path / "no_existe.T02"),
        )
        assert veredicto.correcta

    def test_los_detalles_se_pueden_guardar_como_json(self, tmp_path):
        import json

        veredicto = self._verificar(tmp_path, {"a.23o": rinex_minimo(), "a.23n": _nav()})
        assert json.loads(json.dumps(veredicto.detalles)) == veredicto.detalles


class TestElEmpaquetado:
    def test_mete_lo_que_hay_y_borra_la_carpeta(self, tmp_path):
        carpeta = tmp_path / "transito"
        carpeta.mkdir()
        (carpeta / "a.23o").write_text("obs")
        (carpeta / "a.23n").write_text("nav")
        destino = tmp_path / "salida.parcial.zip"
        assert empaquetar.main([str(carpeta), str(destino)]) == 0
        with zipfile.ZipFile(destino) as z:
            assert sorted(z.namelist()) == ["a.23n", "a.23o"]
        assert not carpeta.exists()

    def test_una_carpeta_vacia_es_un_fallo_aunque_el_convertidor_dijera_exito(
        self, tmp_path, capsys
    ):
        """La regla número uno: «Success» no prueba nada."""
        carpeta = tmp_path / "transito"
        carpeta.mkdir()
        destino = tmp_path / "salida.parcial.zip"
        assert empaquetar.main([str(carpeta), str(destino)]) == 1
        assert not destino.exists()
        assert "no escribió ningún archivo" in capsys.readouterr().err
        assert not carpeta.exists()

    def test_los_archivos_de_cero_bytes_no_cuentan(self, tmp_path):
        carpeta = tmp_path / "transito"
        carpeta.mkdir()
        (carpeta / "a.23o").write_bytes(b"")
        assert empaquetar.main([str(carpeta), str(tmp_path / "s.zip")]) == 1

    def test_los_de_transito_no_entran(self, tmp_path):
        carpeta = tmp_path / "transito"
        carpeta.mkdir()
        (carpeta / "a.23o").write_text("obs")
        (carpeta / "_salida.txt").write_text("log")
        destino = tmp_path / "s.zip"
        empaquetar.main([str(carpeta), str(destino)])
        with zipfile.ZipFile(destino) as z:
            assert z.namelist() == ["a.23o"]

    def test_uso_incorrecto(self, capsys):
        assert empaquetar.main(["solo-uno"]) == 2
