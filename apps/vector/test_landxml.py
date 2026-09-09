"""El escritor de LandXML.

Aquí **no hay oráculo externo**: OGR no lee LandXML, así que no existe una segunda
herramienta a la que preguntarle si el archivo está bien, y comprobarlo con nuestro propio
lector sería el código dándose la razón. Lo que se hace en su lugar:

- Se fija el formato **contra un ejemplo escrito a mano**, no contra lo que salga.
- Se comprueba que el XML esté bien formado con el analizador de la biblioteca estándar,
  que sí es de fuera.
- La aceptación de verdad —abrirlo en Civil 3D— es un procedimiento manual documentado, la
  misma decisión que se tomó con ECW.
"""

from pathlib import Path
from xml.etree import ElementTree  # nosec B405

import pytest

from apps.formats import puntos as puntos_mod
from apps.vector import landxml

CRUCE_MINERO = """P1,7318729.036,495279.406,3042.641,pr
P2,7318700.292,495137.090,3045.004,pr
P3,7318656.894,495192.496,3046.322,pr
P4,7318609.156,495087.401,3045.287,pr
P5,7318567.524,495195.695,3045.963,pr
"""

ESPACIO = "{http://www.landxml.org/schema/LandXML-1.2}"


def _libreta(tmp_path, contenido=CRUCE_MINERO, nombre="libreta.csv"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _escribir(tmp_path, contenido=CRUCE_MINERO, **extra):
    origen = _libreta(tmp_path, contenido)
    destino = tmp_path / "salida.xml"
    puestos = landxml.escribir(puntos_mod.iterar(origen), destino, **extra)
    return destino, puestos


def _arbol(destino):
    return ElementTree.parse(destino).getroot()  # nosec B314


def _cgpoints(destino):
    return _arbol(destino).findall(f".//{ESPACIO}CgPoint")


class TestElOrdenDeLasCoordenadas:
    """Norte, este, cota. En ese orden, y separados por espacios.

    Coincide con PNEZD, que es una simetría cómoda y una trampa: es el mismo error de
    siempre esperando en otro sitio. Por eso se fija contra un valor escrito a mano.
    """

    def test_el_contenido_es_norte_este_cota(self, tmp_path):
        destino, _ = _escribir(tmp_path)
        assert _cgpoints(destino)[0].text == "7318729.036000 495279.406000 3042.641000"

    def test_y_no_este_norte_cota(self, tmp_path):
        """La comprobación explícita del error, porque el archivo saldría igual de válido."""
        destino, _ = _escribir(tmp_path)
        assert not _cgpoints(destino)[0].text.startswith("495279")


class TestLosPuntos:
    def test_los_escribe_todos(self, tmp_path):
        destino, puestos = _escribir(tmp_path)
        assert puestos == 5
        assert len(_cgpoints(destino)) == 5

    def test_no_se_queda_en_la_muestra(self, tmp_path):
        """`leer()` recorta a `MUESTRA_MAXIMA` para poder dibujar. Entregar ese recorte como
        si fuera el archivo sería el peor fallo posible aquí: un LandXML con tres mil puntos
        de los cien mil que traía la libreta, y con la misma cara."""
        cuantos = puntos_mod.MUESTRA_MAXIMA + 500
        contenido = "\n".join(
            f"P{i},{7318000 + i}.0,495279.4,3042.6,pr" for i in range(1, cuantos + 1)
        )
        destino, puestos = _escribir(tmp_path, contenido)
        assert puestos == cuantos
        assert len(_cgpoints(destino)) == cuantos

    def test_el_nombre_lleva_el_numero_de_punto(self, tmp_path):
        destino, _ = _escribir(tmp_path)
        assert [p.get("name") for p in _cgpoints(destino)] == ["P1", "P2", "P3", "P4", "P5"]

    def test_la_descripcion_va_como_code(self, tmp_path):
        """`code` es la descripción bruta del topógrafo, y es la que engancha con los
        estilos de punto de Civil 3D."""
        destino, _ = _escribir(tmp_path)
        assert all(p.get("code") == "pr" for p in _cgpoints(destino))

    def test_sin_numero_de_punto_se_pone_el_correlativo(self, tmp_path):
        """Un `name` vacío hace que Civil 3D importe **un solo punto**, machacando los
        anteriores, y sin decir nada."""
        contenido = "\n".join(f"7318{700 + i}.0,495279.4,3042.6" for i in range(1, 4))
        destino, _ = _escribir(tmp_path, contenido)
        assert [p.get("name") for p in _cgpoints(destino)] == ["1", "2", "3"]

    def test_ningun_nombre_queda_vacio(self, tmp_path):
        destino, _ = _escribir(tmp_path)
        assert all(p.get("name") for p in _cgpoints(destino))


class TestElSistemaDeReferencia:
    def test_el_epsg_va_donde_civil_lo_mira(self, tmp_path):
        destino, _ = _escribir(tmp_path, epsg="32719")
        sistema = _arbol(destino).find(f"{ESPACIO}CoordinateSystem")
        assert sistema is not None
        assert sistema.get("epsgCode") == "32719"

    def test_sin_epsg_no_se_inventa_el_elemento(self, tmp_path):
        """Un `CoordinateSystem` vacío es peor que ninguno: dice que se sabe y no se sabe."""
        destino, _ = _escribir(tmp_path)
        assert _arbol(destino).find(f"{ESPACIO}CoordinateSystem") is None


class TestElXmlEsValido:
    def test_esta_bien_formado(self, tmp_path):
        """Lo dice el analizador de la biblioteca estándar, que no es nuestro."""
        destino, _ = _escribir(tmp_path)
        assert _arbol(destino).tag == f"{ESPACIO}LandXML"

    def test_declara_las_unidades(self, tmp_path):
        """Sin `Units`, Civil 3D pregunta al importar."""
        destino, _ = _escribir(tmp_path)
        metrico = _arbol(destino).find(f"{ESPACIO}Units/{ESPACIO}Metric")
        assert metrico is not None
        assert metrico.get("linearUnit") == "meter"

    def test_lo_que_lleva_comillas_o_signos_no_rompe_el_archivo(self, tmp_path):
        """Una descripción con `<`, `&` o comillas sale de una libreta real más a menudo de
        lo que parece, y sin escapar deja un XML que no abre en ninguna parte."""
        contenido = 'P<1>,7318729.036,495279.406,3042.641,cerco & "malla"\n' * 2
        destino, _ = _escribir(tmp_path, contenido)

        punto = _cgpoints(destino)[0]
        assert punto.get("name") == "P<1>"
        assert punto.get("code") == 'cerco & "malla"'


class TestLaOrdenDeConsola:
    """El módulo se ejecuta como proceso hijo, así que su salida y su código importan."""

    def test_escribe_y_devuelve_cero(self, tmp_path, capsys):
        origen = _libreta(tmp_path)
        destino = tmp_path / "salida.xml"
        assert landxml.main([str(origen), str(destino), "--epsg", "32719"]) == 0
        assert "5 puntos escritos" in capsys.readouterr().out

    def test_respeta_el_orden_elegido_a_mano(self, tmp_path):
        origen = _libreta(tmp_path)
        destino = tmp_path / "salida.xml"
        landxml.main([str(origen), str(destino), "--orden", "penzd"])
        # Con PENZD, la segunda columna es el este: el contenido empieza por la tercera.
        assert _cgpoints(destino)[0].text.startswith("495279")

    def test_un_archivo_que_no_es_libreta_falla_con_codigo_propio(self, tmp_path, capsys):
        origen = _libreta(tmp_path, "esto no es nada\nni esto tampoco\n", "x.txt")
        assert landxml.main([str(origen), str(tmp_path / "s.xml")]) == 2
        assert "No se pudo leer" in capsys.readouterr().err

    def test_el_grupo_se_puede_nombrar(self, tmp_path):
        origen = _libreta(tmp_path)
        destino = tmp_path / "salida.xml"
        landxml.main([str(origen), str(destino), "--grupo", "Control BHP"])
        assert _arbol(destino).find(f"{ESPACIO}CgPoints").get("name") == "Control BHP"

    def test_sin_nombre_de_grupo_se_usa_el_del_archivo(self, tmp_path):
        origen = _libreta(tmp_path)
        destino = tmp_path / "control_cruce.xml"
        landxml.main([str(origen), str(destino)])
        assert _arbol(destino).find(f"{ESPACIO}CgPoints").get("name") == "control_cruce"


class TestElIteradorNoSeQuedaConNada:
    """`iterar()` existe para poder escribir cien mil puntos sin materializarlos."""

    def test_recorre_los_mismos_puntos_que_leer(self, tmp_path):
        origen = _libreta(tmp_path)
        leidos = puntos_mod.leer(origen)
        iterados = list(puntos_mod.iterar(origen))
        assert len(iterados) == leidos.puntos_leidos
        assert iterados[0] == leidos.muestra[0]

    def test_salta_el_encabezado(self, tmp_path):
        origen = _libreta(tmp_path, "Punto,Norte,Este,Cota,Desc\n" + CRUCE_MINERO)
        iterados = list(puntos_mod.iterar(origen))
        assert len(iterados) == 5
        assert iterados[0].identificador == "P1"

    def test_lo_salta_aunque_el_archivo_empiece_con_una_linea_en_blanco(self, tmp_path):
        """Contar líneas del archivo en vez de líneas con contenido dejaría el rótulo
        dentro de los datos, y `Norte` no es un número: saldría como línea ignorada y
        nadie lo notaría salvo por un punto de menos."""
        origen = _libreta(tmp_path, "\n\nPunto,Norte,Este,Cota,Desc\n" + CRUCE_MINERO)
        iterados = list(puntos_mod.iterar(origen))
        assert len(iterados) == 5
        assert iterados[0].identificador == "P1"

    def test_devuelve_un_generador_y_no_una_lista(self, tmp_path):
        origen = _libreta(tmp_path)
        recorrido = puntos_mod.iterar(origen)
        assert not isinstance(recorrido, (list, tuple))
        assert next(iter(recorrido)).identificador == "P1"

    def test_un_orden_inventado_se_rechaza(self, tmp_path):
        with pytest.raises(puntos_mod.NoEsArchivoDePuntos):
            list(puntos_mod.iterar(_libreta(tmp_path), orden="xyzw"))

    def test_un_archivo_vacio_se_rechaza(self, tmp_path):
        with pytest.raises(puntos_mod.NoEsArchivoDePuntos):
            list(puntos_mod.iterar(_libreta(tmp_path, "\n\n\n")))


class TestElConteoDeLaVerificacion:
    def test_cuenta_los_puntos(self, tmp_path):
        from apps.vector.motores import _contar_cgpoints

        destino, _ = _escribir(tmp_path)
        assert _contar_cgpoints(destino) == 5

    def test_un_xml_roto_levanta(self, tmp_path):
        from apps.vector.motores import _contar_cgpoints

        roto = tmp_path / "roto.xml"
        roto.write_text("<LandXML><CgPoints>", encoding="utf-8")
        with pytest.raises(ValueError):
            _contar_cgpoints(Path(roto))
