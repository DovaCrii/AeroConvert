"""DWG y DGN por el ODA File Converter.

## Qué se comprueba aquí, y qué no

El conversor de ODA **no está instalado en esta máquina ni en el servidor**, así que lo que
se prueba es el comando que se construye, las negativas y el criterio — la capa 1 del plan de
pruebas, igual que el resto de motores vectoriales. Es donde han estado los errores caros:
`-a_srs` y `-t_srs` juntos, y el KML sin reproyectar que deja la obra fuera del planeta.

Lo que **no** se puede afirmar todavía es que un DWG real se convierta. Para eso hace falta
el programa, y hasta entonces la herramienta sale apagada con su motivo — que es lo correcto
y es lo que sí se comprueba.

## El caso que más importa y que casi se escribe mal

ODA **convierte carpetas, no archivos**, y su código de salida es cero aunque no escriba
nada. Un motor que mirase el código de salida diría «hecho» y entregaría un trabajo sin
archivo. Por eso lo que decide es si hay DXF, y hay una prueba solo para eso.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from apps.engines.base import ParDeFormatos
from apps.vector import desde_cad, motores


@dataclass
class TrabajoDeMentira:
    source_path: str
    output_path: str
    target_format_code: str
    source_crs_authority: str = "EPSG"
    source_crs_code: str = "32719"
    target_crs_authority: str = ""
    target_crs_code: str = ""
    source_size_bytes: int = 195
    options: dict = field(default_factory=dict)


@pytest.fixture
def plano(tmp_path):
    """Un «DWG». No se abre en estas pruebas: lo que se mira es el comando."""
    ruta = tmp_path / "levantamiento.dwg"
    ruta.write_bytes(b"AC1032" + b"\0" * 64)
    return ruta


def _trabajo(plano, tmp_path, formato, **extra):
    extensiones = {"gpkg": ".gpkg", "shp": ".shp", "kml": ".kml", "dxf": ".dxf"}
    return TrabajoDeMentira(
        source_path=str(plano),
        output_path=str(tmp_path / f"salida{extensiones[formato]}"),
        target_format_code=formato,
        **extra,
    )


class TestLaMatriz:
    def test_dwg_deja_de_ser_un_callejon(self):
        """**El formato de intercambio diario de una oficina de topografía**, y hasta ahora
        había que abrirlo en un CAD y guardarlo como DXF a mano antes de usar nada de esto."""
        pares = motores.MotorCadPorOda().pares()
        assert ParDeFormatos("dwg", "gpkg") in pares
        assert ParDeFormatos("dwg", "kmz") in pares

    def test_dgn_tambien_y_sin_quitarselo_a_ogr(self):
        """La v7 la lee GDAL sola y la v8 no, y **la versión no se sabe hasta abrir**. Los dos
        motores declaran el par; la prioridad decide, y OGR va delante porque no necesita que
        haya nada instalado."""
        assert ParDeFormatos("dgn", "gpkg") in motores.MotorCadPorOda().pares()
        assert ParDeFormatos("dgn", "gpkg") in motores.MotorOgrVector().pares()
        assert motores.MotorOgrVector().prioridad < motores.MotorCadPorOda().prioridad

    def test_no_se_ofrece_escribir_dwg_ni_dgn(self):
        """El catálogo ya dice que no se escriben, y ODA tampoco cambia eso: escribir DWG
        exigiría la SDK de pago."""
        for par in motores.MotorCadPorOda().pares():
            assert par.destino not in ("dwg", "dgn")

    def test_todo_destino_declarado_tiene_controlador(self):
        for par in motores.MotorCadPorOda().pares():
            assert par.destino in motores.CONTROLADOR


class TestElComando:
    def test_el_primer_paso_es_nuestro_y_el_segundo_es_ogr(self, plano, tmp_path):
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg"))
        assert plan.argv[:3] == (sys.executable, "-m", "apps.vector.desde_cad")
        assert len(plan.posteriores) == 1
        assert "ogr2ogr" in plan.posteriores[0][0]

    def test_el_dxf_intermedio_cuelga_del_parcial(self, plano, tmp_path):
        """Para que lo barra la limpieza que ya existe, que borra `<parcial>.*`. Si colgara
        de otro sitio, cada conversión dejaría un DXF olvidado junto al resultado."""
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg"))
        intermedio = Path(plan.argv[4])
        assert intermedio.name.endswith(".dxf")
        assert intermedio.name.startswith(Path(plan.posteriores[0][3]).name)

    def test_la_salida_la_escribe_el_segundo_paso(self, plano, tmp_path):
        """Sin esto, el runner buscaría el resultado al terminar el primero —que solo deja un
        DXF intermedio— y daría el trabajo por fallido."""
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg"))
        assert plan.salida_en_posteriores

    def test_un_kmz_se_reproyecta_solo(self, plano, tmp_path):
        """**El error que sí convierte.** Un KML con estes y nortes UTM dentro es válido,
        abre en Google Earth, y pone la obra a cientos de kilómetros del planeta."""
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "kml"))
        segundo = plan.posteriores[0]
        assert "-t_srs" in segundo
        assert segundo[segundo.index("-t_srs") + 1] == "EPSG:4326"

    def test_nunca_etiqueta_y_mueve_a_la_vez(self, plano, tmp_path):
        """`ogr2ogr` rechaza `-a_srs` y `-t_srs` juntos y no convierte nada."""
        for formato in ("gpkg", "shp", "kml", "dxf"):
            segundo = (
                motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, formato)).posteriores[0]
            )
            assert not ("-a_srs" in segundo and "-t_srs" in segundo), formato

    def test_sin_destino_en_grados_solo_etiqueta(self, plano, tmp_path):
        segundo = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg")).posteriores[0]
        assert "-a_srs" in segundo
        assert segundo[segundo.index("-a_srs") + 1] == "EPSG:32719"

    def test_lleva_el_entorno_de_gdal(self, plano, tmp_path):
        """Sin `GDAL_DATA` el controlador DXF no arranca, y aquí **todo** pasa por DXF."""
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg"))
        assert "GDAL_DATA" in plan.env

    def test_el_plazo_es_mas_largo_que_el_del_resto(self, plano, tmp_path):
        """Son dos conversiones seguidas, y la primera es un programa de escritorio
        auditando un plano que puede tener cien mil entidades."""
        plan = motores.MotorCadPorOda().plan(_trabajo(plano, tmp_path, "gpkg"))
        assert plan.timeout_s > 1800


class TestLaDisponibilidad:
    def test_sin_conversor_dice_cual_falta_y_ofrece_la_salida(self, settings, monkeypatch):
        """**Un «no se puede» sin salida es una pared.** Aquí la salida existe y es real:
        «Guardar como DXF» desde cualquier CAD hace el mismo primer paso."""
        settings.ODA_CONVERTER = ""
        monkeypatch.setattr(desde_cad.shutil, "which", lambda _: None)
        from apps.engines import sondas

        monkeypatch.setattr(sondas.shutil, "which", lambda _: None)

        estado = motores.MotorCadPorOda().disponibilidad()
        assert not estado.disponible
        assert "dxf" in estado.alternativas
        assert "ODA" in estado.mensaje or "ODA" in estado.sugerencia

    def test_una_ruta_configurada_que_no_existe_lo_dice(self, settings):
        """Callarlo dejaría a alguien convencido de que lo configuró bien."""
        settings.ODA_CONVERTER = str(Path("C:/no/existe/ODAFileConverter.exe"))
        estado = motores.MotorCadPorOda().disponibilidad()
        assert not estado.disponible


class TestElPasoDeOda:
    def test_sin_conversor_el_mensaje_dice_que_hacer_mientras_tanto(self, monkeypatch, plano):
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "")
        with pytest.raises(desde_cad.SinConversorDeCad) as fallo:
            desde_cad.a_dxf(plano, plano.with_suffix(".dxf"))
        texto = str(fallo.value)
        assert "ODA File Converter" in texto
        assert "DXF" in texto

    def test_algo_que_no_es_cad_se_rechaza_antes_de_lanzar_nada(self, monkeypatch, tmp_path):
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        otro = tmp_path / "hoja.xlsx"
        otro.write_bytes(b"x")
        with pytest.raises(desde_cad.SinConversorDeCad):
            desde_cad.a_dxf(otro, tmp_path / "salida.dxf")

    def test_el_filtro_de_entrada_va_en_mayusculas(self):
        """ODA compara la extensión en mayúsculas: con `*.dwg` no encuentra el archivo que
        tiene delante y termina, con código cero, sin convertir nada."""
        assert desde_cad.FILTROS[".dwg"] == "*.DWG"
        assert desde_cad.FILTROS[".dgn"] == "*.DGN"

    def test_se_baja_de_version_a_proposito(self):
        """Parece una pérdida y es lo contrario: al bajar, ODA **descompone** las entidades
        modernas que el lector DXF de GDAL se saltaría en silencio."""
        assert desde_cad.VERSION_DE_SALIDA == "ACAD2000"

    def test_cero_de_salida_sin_dxf_es_un_fallo(self, monkeypatch, plano, tmp_path):
        """**El fallo que habría entregado un trabajo vacío diciendo «hecho».** ODA devuelve
        cero habiendo escrito un registro de errores y ningún archivo."""
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        monkeypatch.setattr(desde_cad, "_envoltura", list)

        class Cero:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(desde_cad.subprocess, "run", lambda *a, **k: Cero())
        with pytest.raises(desde_cad.SinConversorDeCad) as fallo:
            desde_cad.a_dxf(plano, tmp_path / "salida.dxf")
        assert "sin escribir nada" in str(fallo.value)

    def test_el_motivo_sale_del_registro_que_deja_oda(self, monkeypatch, plano, tmp_path):
        """Escribe los errores **en la carpeta de salida**, no en `stderr`. Quedarse con
        `stderr` da un mensaje vacío justo en el caso que importa."""
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        monkeypatch.setattr(desde_cad, "_envoltura", list)

        def fingir(orden, **kwargs):
            Path(orden[2]).mkdir(parents=True, exist_ok=True)
            (Path(orden[2]) / "errores.txt").write_text("Archivo dañado", encoding="utf-8")

            class Cero:
                returncode = 0
                stdout = ""
                stderr = ""

            return Cero()

        monkeypatch.setattr(desde_cad.subprocess, "run", fingir)
        with pytest.raises(desde_cad.SinConversorDeCad) as fallo:
            desde_cad.a_dxf(plano, tmp_path / "salida.dxf")
        assert "Archivo dañado" in str(fallo.value)

    def test_un_dxf_escrito_se_recoge_y_se_mueve(self, monkeypatch, plano, tmp_path):
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        monkeypatch.setattr(desde_cad, "_envoltura", list)

        def fingir(orden, **kwargs):
            carpeta = Path(orden[2])
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "plano.dxf").write_text("0\nSECTION\n", encoding="utf-8")

            class Cero:
                returncode = 0
                stdout = ""
                stderr = ""

            return Cero()

        monkeypatch.setattr(desde_cad.subprocess, "run", fingir)
        destino = tmp_path / "salida.dxf"
        assert desde_cad.a_dxf(plano, destino) == destino
        assert destino.read_text(encoding="utf-8").startswith("0")

    def test_y_no_deja_la_carpeta_temporal(self, monkeypatch, plano, tmp_path):
        """Un plano de obra pesa decenas de megabytes: dejarse la copia por cada conversión
        llena el disco del servidor sin que nadie sepa de qué."""
        import tempfile

        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        monkeypatch.setattr(desde_cad, "_envoltura", list)
        monkeypatch.setattr(desde_cad.tempfile, "tempdir", None)

        antes = set(Path(tempfile.gettempdir()).glob("aeroconvert-cad-*"))

        class Cero:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(desde_cad.subprocess, "run", lambda *a, **k: Cero())
        with pytest.raises(desde_cad.SinConversorDeCad):
            desde_cad.a_dxf(plano, tmp_path / "salida.dxf")

        assert set(Path(tempfile.gettempdir()).glob("aeroconvert-cad-*")) == antes


class TestLoQueSoloPasaEnLinux:
    def test_sin_servidor_grafico_se_dice_con_el_paquete_que_falta(self, monkeypatch, plano):
        """**ODA está hecho con Qt y necesita un servidor gráfico aunque no dibuje nada.**

        Sin esto, lo que sale en el servidor es un error de Qt sobre un «display» que nadie
        pidió, y nadie relaciona eso con convertir un plano.
        """
        monkeypatch.setattr(desde_cad, "donde_esta", lambda: "/usr/bin/ODAFileConverter")
        monkeypatch.setattr(desde_cad.os, "name", "posix")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(desde_cad.shutil, "which", lambda nombre: None)

        with pytest.raises(desde_cad.SinConversorDeCad) as fallo:
            desde_cad.a_dxf(plano, plano.with_suffix(".dxf"))
        assert "xvfb" in str(fallo.value)

    def test_con_xvfb_se_envuelve(self, monkeypatch):
        monkeypatch.setattr(desde_cad.os, "name", "posix")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(
            desde_cad.shutil,
            "which",
            lambda nombre: "/usr/bin/xvfb-run" if "xvfb" in nombre else None,
        )
        assert desde_cad._envoltura() == ["/usr/bin/xvfb-run", "-a"]

    def test_en_windows_no_se_envuelve_nada(self, monkeypatch):
        monkeypatch.setattr(desde_cad.os, "name", "nt")
        assert desde_cad._envoltura() == []
