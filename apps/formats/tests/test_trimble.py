"""El lector de la cabecera de un crudo de Trimble, y su paso por la detección.

Los archivos son sintéticos y salen de `constructor.trimble_minimo()`, con la estructura
medida el 2026-10-05 en dos archivos reales. **No hay forma de probar contra Trimble**: su
formato es cerrado, y lo que se vigila es que el lector reconozca lo que se midió, rechace
lo que no es, y no se deje arrastrar por un bzip2 hostil.
"""

import bz2

import pytest

from apps.formats import deteccion, trimble
from apps.formats.tests.constructor import trimble_minimo


def _escribir(tmp_path, nombre, contenido: bytes):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return ruta


class TestLoQueSeLee:
    def test_un_netr9(self, tmp_path):
        cabecera = trimble.leer_cabecera(_escribir(tmp_path, "a.T02", trimble_minimo()))
        assert cabecera.modelo == "TRIMBLE NETR9"
        assert cabecera.serie == "5303K49763"
        assert cabecera.id_receptor == 76
        assert cabecera.encendido_s == 3136987
        assert cabecera.nivel_bzip2 == 1

    def test_un_r12i_con_otro_tamano_de_bloque(self, tmp_path):
        ruta = _escribir(
            tmp_path,
            "b.T04",
            trimble_minimo(modelo="TRIMBLE R12i", serie="6212F01411", nivel_bzip2=3),
        )
        cabecera = trimble.leer_cabecera(ruta)
        assert cabecera.modelo == "TRIMBLE R12i"
        assert cabecera.nivel_bzip2 == 3

    def test_dice_la_carpeta_pero_no_el_nombre(self, tmp_path):
        """En lo medido el nombre del archivo llega cortado; la carpeta es lo único entero."""
        cabecera = trimble.leer_cabecera(_escribir(tmp_path, "a.T02", trimble_minimo()))
        assert cabecera.carpeta_en_receptor == "/Internal/VUELOS/2023/01/31"

    def test_se_describe_para_la_ficha(self, tmp_path):
        cabecera = trimble.leer_cabecera(_escribir(tmp_path, "a.T02", trimble_minimo()))
        assert cabecera.descripcion == "TRIMBLE NETR9, serie 5303K49763"


class TestLoQueSeRechaza:
    def test_algo_que_no_empieza_como_trimble(self, tmp_path):
        ruta = _escribir(tmp_path, "x.T02", b"LASF" + b"\x00" * 200)
        with pytest.raises(trimble.NoEsTrimble):
            trimble.leer_cabecera(ruta)

    def test_el_prefijo_solo_no_basta(self, tmp_path):
        """Cuatro bytes los puede tener cualquier cosa; hay que ver el bloque que va detrás."""
        ruta = _escribir(tmp_path, "x.T02", b"\x00\x00\x00\x0d" + b"\x01" * 300)
        with pytest.raises(trimble.NoEsTrimble, match="bloque comprimido"):
            trimble.leer_cabecera(ruta)

    def test_un_bzip2_roto(self, tmp_path):
        roto = bytearray(trimble_minimo())
        for i in range(30, len(roto)):
            roto[i] = 0xFF
        with pytest.raises(trimble.NoEsTrimble):
            trimble.leer_cabecera(_escribir(tmp_path, "x.T02", bytes(roto)))

    def test_un_archivo_cortado_a_mitad_del_bloque(self, tmp_path):
        """No devuelve a medias ni revienta con una excepción que no sea la suya."""
        entero = trimble_minimo()
        ruta = _escribir(tmp_path, "x.T02", entero[: len(entero) // 2])
        try:
            cabecera = trimble.leer_cabecera(ruta)
        except trimble.NoEsTrimble:
            return
        assert not cabecera.identificado

    def test_un_bloque_con_tamano_cero(self, tmp_path):
        ruta = _escribir(tmp_path, "x.T02", b"\x00\x00\x00\x0d" + b"\x00" * 17 + b"BZh0AY&SY")
        with pytest.raises(trimble.NoEsTrimble):
            trimble.leer_cabecera(ruta)


class TestUnBzip2HostilNoSeDescomprimeEntero:
    def test_pide_la_salida_acotada(self, tmp_path, monkeypatch):
        """Lo que importa no es qué devuelve sino **con qué límite lo pide**."""
        pedidos = []
        real = bz2.BZ2Decompressor

        class Espia:
            """`BZ2Decompressor` no se puede heredar: se envuelve y se anota lo que se pide."""

            def __init__(self):
                self._real = real()

            def decompress(self, datos, max_length=-1):
                pedidos.append(max_length)
                return self._real.decompress(datos, max_length=max_length)

        monkeypatch.setattr(trimble.bz2, "BZ2Decompressor", Espia)
        trimble.leer_cabecera(_escribir(tmp_path, "a.T02", trimble_minimo()))
        assert pedidos == [trimble.SALIDA_MAXIMA]

    def test_ocho_megas_de_ceros_no_se_vuelven_ocho_megas_en_memoria(self, tmp_path):
        """Un bloque de pocos KB que descomprime a mucho. Se lee, se acota y se dice que no
        se pudo identificar; no se carga entero."""
        bomba = b"\x00\x00\x00\x0d" + b"\x00" * 17 + bz2.compress(b"\x00" * 8_000_000, 1)
        assert len(bomba) < 2_000
        cabecera = trimble.leer_cabecera(_escribir(tmp_path, "a.T02", bomba))
        assert not cabecera.identificado


class TestEnLaDeteccion:
    def test_se_reconoce_por_su_contenido(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_escribir(tmp_path, "GMLA.T02", trimble_minimo()))
        assert inspeccion.codigo_formato == "trimble_t0x"
        assert inspeccion.confianza == deteccion.CONFIANZA_FIRMA
        assert inspeccion.familia == "gnss"
        assert inspeccion.trimble.modelo == "TRIMBLE NETR9"

    def test_la_ficha_lo_dice_con_el_modelo_y_la_serie(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_escribir(tmp_path, "GMLA.T02", trimble_minimo()))
        assert any("NETR9" in a and "5303K49763" in a for a in inspeccion.avisos)

    def test_no_declara_sistema_de_referencia_y_no_pasa_nada(self, tmp_path):
        """Una observación GNSS no es una coordenada: no hay CRS que echar en falta."""
        inspeccion = deteccion.inspeccionar(_escribir(tmp_path, "GMLA.T02", trimble_minimo()))
        assert not inspeccion.crs.conocido
        assert not inspeccion.faltan_imprescindibles

    def test_se_reconoce_aunque_la_extension_sea_otra(self, tmp_path):
        inspeccion = deteccion.inspeccionar(_escribir(tmp_path, "copia.bin", trimble_minimo()))
        assert inspeccion.codigo_formato == "trimble_t0x"

    def test_cuatro_bytes_de_firma_sin_el_bloque_no_son_de_trimble(self, tmp_path):
        ruta = _escribir(tmp_path, "otro.bin", b"\x00\x00\x00\x0d" + b"\x07" * 400)
        inspeccion = deteccion.inspeccionar(ruta)
        assert inspeccion.codigo_formato == ""
        assert not inspeccion.reconocido
        assert any("no lo es" in a for a in inspeccion.avisos)

    def test_una_extension_de_trimble_sobre_otra_cosa_no_engana(self, tmp_path):
        ruta = _escribir(tmp_path, "falso.T02", b"hola, esto es texto")
        inspeccion = deteccion.inspeccionar(ruta)
        assert inspeccion.codigo_formato == ""
        assert not inspeccion.reconocido
        assert inspeccion.trimble is None
