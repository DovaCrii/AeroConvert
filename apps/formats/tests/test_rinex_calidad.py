"""Calidad de un RINEX: los números contra archivos armados a mano, donde se sabe la respuesta."""

from __future__ import annotations

import pytest

from apps.formats import rinex, rinex_calidad

from .constructor import rinex_minimo


def _medir(tmp_path, texto: str):
    ruta = tmp_path / "x.rnx"
    ruta.write_text(texto, encoding="latin-1", newline="")
    cabecera = rinex.leer_cabecera(ruta)
    resumen = rinex.resumir_epocas(ruta, cabecera)
    return cabecera, resumen, rinex_calidad.calcular(ruta, cabecera)


class TestRinex3:
    def test_un_archivo_completo_tiene_todo_presente(self, tmp_path):
        _, _, informe = _medir(tmp_path, rinex_minimo(epocas=5))
        assert (informe.satelites_minimo, informe.satelites_maximo) == (3, 3)
        assert informe.satelites_medio == pytest.approx(3.0)
        assert informe.porcentaje_completo == pytest.approx(100.0)
        # Dos satélites GPS y uno GLONASS, 4 tipos, 5 épocas.
        assert dict((c, (h, p)) for c, h, p in informe.completitud) == {
            "G": (40, 40),
            "R": (20, 20),
        }

    def test_cada_satelite_dice_en_cuantas_epocas_esta(self, tmp_path):
        _, _, informe = _medir(tmp_path, rinex_minimo(epocas=5))
        assert {s.id: s.epocas for s in informe.satelites} == {"G01": 5, "G02": 5, "R05": 5}
        assert all(s.porcentaje == pytest.approx(100.0) for s in informe.satelites)

    def test_un_campo_en_blanco_baja_el_porcentaje(self, tmp_path):
        texto = rinex_minimo(epocas=2)
        lineas = texto.split("\n")
        # La primera línea de satélite GPS: se borra el primer valor (C1C).
        i = next(n for n, linea in enumerate(lineas) if linea.startswith("G01"))
        lineas[i] = lineas[i][:3] + " " * 16 + lineas[i][19:]
        _, _, informe = _medir(tmp_path, "\n".join(lineas))
        presentes = {(c, t): h for c, t, h, _ in informe.por_tipo}
        posibles = {(c, t): p for c, t, _, p in informe.por_tipo}
        assert presentes[("G", "C1C")] == 3 and posibles[("G", "C1C")] == 4
        assert informe.porcentaje_completo < 100.0

    def test_un_hueco_se_ve_en_el_resumen_y_la_presencia_es_de_las_que_hay(self, tmp_path):
        cabecera, resumen, informe = _medir(tmp_path, rinex_minimo(epocas=8, huecos_en=(3, 4)))
        assert resumen.total_de_huecos == 1
        assert informe.epocas == resumen.epocas == 6

    def test_la_epoca_cortada_no_cuenta(self, tmp_path):
        _, resumen, informe = _medir(tmp_path, rinex_minimo(epocas=5, truncar_la_ultima=True))
        assert informe.epocas == resumen.epocas


class TestRinex2:
    def test_cuenta_satelites_y_avisa_de_lo_que_no_mide(self, tmp_path):
        _, _, informe = _medir(tmp_path, rinex_minimo(version="2.11", epocas=4))
        assert informe.satelites_maximo == 3
        assert {s.id for s in informe.satelites} == {"G01", "G02", "R05"}
        assert informe.completitud == ()
        assert informe.porcentaje_completo is None
        assert any("RINEX 2" in nota for nota in informe.notas)


class TestLimites:
    def test_navegacion_no_se_mide(self, tmp_path):
        ruta = tmp_path / "n.rnx"
        cabecera = "     3.04           NAVIGATION DATA     M".ljust(60) + "RINEX VERSION / TYPE\n"
        ruta.write_text(cabecera + "".ljust(60) + "END OF HEADER\n", encoding="latin-1")
        with pytest.raises(rinex.NoEsRinex):
            rinex_calidad.calcular(ruta, rinex.leer_cabecera(ruta))

    def test_identificadores_inventados_no_hacen_crecer_la_memoria(self):
        estado = rinex_calidad._Estado()
        estado.epoca([f"X{n:03d}" for n in range(rinex_calidad.SATELITES_MAXIMOS + 50)])
        assert len(estado.presencia) == rinex_calidad.SATELITES_MAXIMOS
        assert estado.recortado


class TestElMarkdown:
    def test_dice_lo_que_mide_y_lo_que_no(self, tmp_path):
        cabecera, resumen, informe = _medir(tmp_path, rinex_minimo(epocas=5))
        texto = rinex_calidad.a_markdown(informe, cabecera, resumen)
        assert texto.startswith("# Informe de calidad de un RINEX")
        assert "RINEX 3.04" in texto
        assert "Satélites por época: mínimo 3, media 3.0, máximo 3" in texto
        assert "| GPS |" in texto and "| G01 | 5 | 100.0 |" in texto
        assert "Lo que este informe no mide" in texto
        assert "Multitrayecto" in texto
