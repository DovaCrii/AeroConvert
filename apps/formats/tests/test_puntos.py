"""El lector de archivos de puntos, y sobre todo la detección del orden de columnas.

La prueba que manda es la primera: las cinco líneas reales de `puntos control cruce
minero.csv`. Si el orden se detecta mal ahí, todo lo demás sobra.
"""

import pytest

from apps.formats import puntos as mod

#: Las cinco líneas del archivo de control del cruce minero, tal cual.
#:
#: PNEZD sin encabezado. Los nortes rondan 7.318.xxx y los estes 495.xxx, así que el rango
#: UTM decide sin ambigüedad: 7,3 millones no cabe como este.
CRUCE_MINERO = """P1,7318729.036,495279.406,3042.641,pr
P2,7318700.292,495137.090,3045.004,pr
P3,7318656.894,495192.496,3046.322,pr
P4,7318609.156,495087.401,3045.287,pr
P5,7318567.524,495195.695,3045.963,pr
"""


def _escribir(tmp_path, contenido, nombre="puntos.csv"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class TestElArchivoReal:
    @pytest.fixture
    def leido(self, tmp_path):
        return mod.leer(_escribir(tmp_path, CRUCE_MINERO))

    def test_detecta_pnezd(self, leido):
        assert leido.orden == "pnezd"

    def test_y_lo_detecta_con_certeza_no_a_ojo(self, leido):
        """Lo que separa esto de una corazonada: 7.318.729 **no cabe** como este UTM."""
        assert leido.certeza == mod.CERTEZA_RANGO
        assert leido.hay_que_preguntar is False
        assert leido.orden_alternativo == ""

    def test_lee_los_cinco_puntos(self, leido):
        assert leido.puntos_leidos == 5
        assert leido.lineas_ignoradas == 0

    def test_el_primer_punto_cae_donde_debe(self, leido):
        primero = leido.muestra[0]
        assert primero.identificador == "P1"
        assert primero.norte_m == pytest.approx(7318729.036)
        assert primero.este_m == pytest.approx(495279.406)
        assert primero.cota_m == pytest.approx(3042.641)
        assert primero.descripcion == "pr"

    def test_no_confunde_la_descripcion_con_una_columna_mas(self, leido):
        assert leido.columnas == 5
        assert all(p.descripcion == "pr" for p in leido.muestra)

    def test_la_extension_del_levantamiento_es_de_metros_no_de_millones(self, leido):
        """Si el orden estuviera mal, la extensión saldría de millones de metros. Es la
        comprobación que delata una lectura invertida sin mirar el orden."""
        norte, este, _ = leido.extension_m
        assert norte < 200
        assert este < 200

    def test_dice_a_que_distancia_caerian_si_se_leyera_al_reves(self, leido):
        """La cifra que hace entender el problema sin explicarlo."""
        assert leido.distancia_si_se_invierte_m > 9_000_000


class TestElOrdenInverso:
    def test_un_penzd_se_detecta_como_penzd(self, tmp_path):
        """El mismo archivo con las dos columnas intercambiadas. Misma certeza, otro orden:
        el detector no tiene preferencia, mira el rango."""
        invertido = "\n".join(
            ",".join([celda[0], celda[2], celda[1], celda[3], celda[4]])
            for celda in (linea.split(",") for linea in CRUCE_MINERO.strip().splitlines())
        )
        leido = mod.leer(_escribir(tmp_path, invertido))
        assert leido.orden == "penzd"
        assert leido.certeza == mod.CERTEZA_RANGO
        assert leido.muestra[0].norte_m == pytest.approx(7318729.036)
        assert leido.muestra[0].este_m == pytest.approx(495279.406)

    def test_leer_al_reves_pone_los_puntos_a_miles_de_kilometros(self, tmp_path):
        """El fallo que este módulo existe para impedir, escrito como prueba.

        Forzar `penzd` sobre un archivo PNEZD es exactamente lo que hace media herramienta
        del sector sin avisar. Aquí se mide el destrozo: la obra se va del continente.
        """
        ruta = _escribir(tmp_path, CRUCE_MINERO)
        bien = mod.leer(ruta)
        mal = mod.leer(ruta, orden="penzd")

        desplazamiento = abs(mal.centro[0] - bien.centro[0])
        assert desplazamiento > 6_800_000


class TestCuandoNoSePuedeDecidir:
    def test_dos_columnas_en_rango_de_este_es_ambiguo(self, tmp_path):
        """Pasa de verdad en el hemisferio norte, donde el norte también cabe en la banda
        del este. Aquí la respuesta correcta es no responder."""
        contenido = "\n".join(f"P{i},4{500 + i}00.10,5{100 + i}00.20,120.5,pr" for i in range(1, 6))
        leido = mod.leer(_escribir(tmp_path, contenido))

        assert leido.certeza == mod.CERTEZA_AMBIGUA
        assert leido.hay_que_preguntar is True
        assert leido.orden_alternativo == "penzd"
        assert leido.nombre_del_alternativo.startswith("PENZD")

    def test_y_aun_asi_lee_los_puntos(self, tmp_path):
        """Ambiguo no es ilegible: se leen y se dibujan, y se pide confirmar el orden. No
        enseñar nada dejaría a la persona sin la vista previa, que es justo lo que
        resolvería su duda."""
        contenido = "\n".join(f"P{i},4{500 + i}00.10,5{100 + i}00.20,120.5,pr" for i in range(1, 6))
        assert mod.leer(_escribir(tmp_path, contenido)).puntos_leidos == 5


class TestVariantesDeArchivo:
    def test_identificador_numerico(self, tmp_path):
        """`1,` en vez de `P1,`. Aquí la magnitud no sirve para distinguir el identificador
        de una coordenada: lo que decide es que las coordenadas son **tres**, así que una
        cuarta columna numérica solo puede ser el número de punto."""
        contenido = "\n".join(f"{i},7318{700 + i}.0,4952{i}0.0,3042.6,pr" for i in range(1, 6))
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.orden == "pnezd"
        assert leido.muestra[0].identificador == "1"
        assert leido.muestra[0].norte_m == pytest.approx(7318701.0)

    def test_sin_identificador_ni_descripcion(self, tmp_path):
        contenido = "\n".join(f"7318{700 + i}.0,495279.4,3042.6" for i in range(1, 6))
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.orden == "nez"
        assert leido.muestra[0].identificador == ""

    def test_con_encabezado(self, tmp_path):
        contenido = "Punto,Norte,Este,Cota,Desc\n" + CRUCE_MINERO
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.tiene_encabezado is True
        assert leido.puntos_leidos == 5

    def test_punto_y_coma_con_coma_decimal(self, tmp_path):
        """Lo que sale de un Excel en español. El delimitador es `;` y el decimal es `,`."""
        contenido = "\n".join(f"P{i};7318{700 + i},036;495279,406;3042,641;pr" for i in range(1, 6))
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.delimitador == ";"
        assert leido.orden == "pnezd"
        assert leido.muestra[0].norte_m == pytest.approx(7318701.036)

    def test_separado_por_espacios(self, tmp_path):
        contenido = "\n".join(f"P{i} 7318{700 + i}.036 495279.406 3042.641" for i in range(1, 6))
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.delimitador == " "
        assert leido.orden == "pnez"

    def test_una_descripcion_con_espacios_no_engana_al_delimitador(self, tmp_path):
        """El espacio aparece más veces que la coma y parte cada línea en un número
        distinto de trozos. Puntuar por consistencia y no por frecuencia es lo que lo
        arregla."""
        contenido = "\n".join(
            f"P{i},7318{700 + i}.036,495279.406,3042.641,punto de control {i}" for i in range(1, 6)
        )
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.delimitador == ","
        assert leido.muestra[0].descripcion == "punto de control 1"

    def test_las_lineas_rotas_se_cuentan_y_no_tumban_la_lectura(self, tmp_path):
        contenido = CRUCE_MINERO + "P6,esto,no,son,numeros\n"
        leido = mod.leer(_escribir(tmp_path, contenido))
        assert leido.puntos_leidos == 5
        assert leido.lineas_ignoradas == 1

    def test_la_muestra_se_reparte_por_todo_el_archivo(self, tmp_path):
        """Y no son los primeros N: los primeros puntos de un levantamiento son una esquina
        de la obra, y dibujarlos daría una vista previa que no representa nada."""
        contenido = "\n".join(
            f"P{i},{7318000 + i}.0,495279.4,3042.6,pr" for i in range(mod.MUESTRA_MAXIMA * 3)
        )
        leido = mod.leer(_escribir(tmp_path, contenido))

        assert leido.puntos_leidos == mod.MUESTRA_MAXIMA * 3
        assert len(leido.muestra) <= mod.MUESTRA_MAXIMA
        # El último punto de la muestra tiene que venir del final del archivo.
        assert leido.muestra[-1].norte_m > 7318000 + mod.MUESTRA_MAXIMA * 2


class TestLoQueNoEsUnArchivoDePuntos:
    def test_un_texto_cualquiera(self, tmp_path):
        with pytest.raises(mod.NoEsArchivoDePuntos):
            mod.leer(_escribir(tmp_path, "hola que tal\nesto no es nada\n", "x.txt"))

    def test_dos_columnas_no_bastan(self, tmp_path):
        with pytest.raises(mod.NoEsArchivoDePuntos):
            mod.leer(_escribir(tmp_path, "1,2\n3,4\n5,6\n"))

    def test_un_archivo_vacio(self, tmp_path):
        with pytest.raises(mod.NoEsArchivoDePuntos):
            mod.leer(_escribir(tmp_path, "\n\n\n"))

    def test_un_orden_inventado(self, tmp_path):
        with pytest.raises(mod.NoEsArchivoDePuntos):
            mod.leer(_escribir(tmp_path, CRUCE_MINERO), orden="xyzw")


class TestElVocabulario:
    def test_todo_orden_tiene_nombre_legible(self):
        assert set(mod.ORDENES) == set(mod.NOMBRES_DE_ORDEN)

    def test_toda_certeza_tiene_etiqueta(self):
        certezas = {mod.CERTEZA_RANGO, mod.CERTEZA_DECLARADA, mod.CERTEZA_AMBIGUA}
        assert certezas == set(mod.ETIQUETAS_CERTEZA)
