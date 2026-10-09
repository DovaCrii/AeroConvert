"""El estado de varias capas (F19.3): orden, visibilidad y transparencia, sin navegador ni GDAL.

Es lo que se guarda en `e=` y lo que el servidor vuelve a leer al abrir el enlace. Cada formato y
cada límite se mide aquí; `static/js/visor.js` escribe el mismo formato.
"""

from __future__ import annotations

import pytest

from apps.visor import capas

IDS = ["va1b2c3f", "ra1b2c3", "rffffff", "fondo"]


class TestElFormatoDelEstado:
    def test_lo_que_se_guarda_se_vuelve_a_leer_igual(self):
        estados = [
            capas.EstadoDeCapa("rffffff", visible=True, transparencia=35),
            capas.EstadoDeCapa("fondo", visible=False, transparencia=0),
            capas.EstadoDeCapa("va1b2c3f", visible=True, transparencia=100),
            capas.EstadoDeCapa("ra1b2c3", visible=True, transparencia=5),
        ]
        texto = capas.a_texto(estados)
        assert texto == "rffffff:35:1,fondo:0:0,va1b2c3f:100:1,ra1b2c3:5:1"
        assert capas.normalizar(texto, IDS) == estados

    def test_el_orden_de_arriba_abajo_es_el_del_texto(self):
        leidas = capas.normalizar("fondo:0:1,rffffff:0:1,ra1b2c3:0:1,va1b2c3f:0:1", IDS)
        assert [e.id for e in leidas] == ["fondo", "rffffff", "ra1b2c3", "va1b2c3f"]

    def test_sin_estado_es_el_orden_por_omision_y_todo_visible_y_opaco(self):
        for vacio in (None, "", "   "):
            leidas = capas.normalizar(vacio, IDS)
            assert [e.id for e in leidas] == IDS
            assert all(e.visible and e.transparencia == 0 for e in leidas)

    def test_lo_que_falta_va_detras_en_su_orden_por_omision(self):
        leidas = capas.normalizar("fondo:20:0", IDS)
        assert [e.id for e in leidas] == ["fondo", "va1b2c3f", "ra1b2c3", "rffffff"]
        assert leidas[0] == capas.EstadoDeCapa("fondo", False, 20)

    def test_una_capa_nueva_no_cambia_el_estado_de_las_que_ya_estaban(self):
        guardado = capas.a_texto(
            [capas.EstadoDeCapa("ra1b2c3", True, 40), capas.EstadoDeCapa("fondo", False, 0)]
        )
        leidas = capas.normalizar(guardado, [*IDS, "rnueva1"])
        assert leidas[0] == capas.EstadoDeCapa("ra1b2c3", True, 40)
        assert leidas[1] == capas.EstadoDeCapa("fondo", False, 0)
        assert leidas[-1].id == "rnueva1" and leidas[-1].transparencia == 0


class TestLoQueNoSeEntiendeNoTumbaNiAbreNada:
    def test_un_identificador_que_no_existe_se_ignora(self):
        leidas = capas.normalizar("rinventada:0:1,../../etc:0:1,fondo:10:1", IDS)
        assert [e.id for e in leidas][0] == "fondo"
        assert {e.id for e in leidas} == set(IDS)

    def test_un_identificador_repetido_vale_el_primero(self):
        leidas = capas.normalizar("fondo:10:1,fondo:90:0", IDS)
        assert leidas[0] == capas.EstadoDeCapa("fondo", True, 10)
        assert [e.id for e in leidas].count("fondo") == 1

    @pytest.mark.parametrize(
        ("crudo", "esperada"),
        [("-5", 0), ("250", 100), ("100", 100), ("0", 0), ("abc", 0), ("", 0), ("12.7", 0)],
    )
    def test_la_transparencia_se_recorta_a_0_100(self, crudo, esperada):
        leidas = capas.normalizar(f"fondo:{crudo}:1", IDS)
        assert leidas[0].transparencia == esperada

    @pytest.mark.parametrize("basura", ["fondo", "fondo:1", "fondo:1:1:1", ",,,", ":::", "fondo::"])
    def test_un_elemento_mal_formado_se_salta(self, basura):
        leidas = capas.normalizar(basura, IDS)
        assert [e.id for e in leidas] == IDS or leidas[0].id == "fondo"
        assert {e.id for e in leidas} == set(IDS)

    def test_un_estado_demasiado_largo_se_descarta_entero(self):
        largo = ",".join(f"x{i}:0:1" for i in range(400))
        assert len(largo) > capas.LARGO_MAXIMO_DEL_ESTADO
        assert [e.id for e in capas.normalizar(largo, IDS)] == IDS

    def test_visible_es_todo_lo_que_no_sea_cero(self):
        assert capas.normalizar("fondo:0:0", IDS)[0].visible is False
        assert capas.normalizar("fondo:0:1", IDS)[0].visible is True
        assert capas.normalizar("fondo:0:si", IDS)[0].visible is True


class TestOrdenarDescriptores:
    DESCRIPTORES = [
        {"id": "va1b2c3f", "tipo": capas.VUELO_FOTOS, "nombre": "Fotos"},
        {"id": "ra1b2c3", "tipo": capas.RASTER, "nombre": "Ortofoto"},
        {"id": "fondo", "tipo": capas.FONDO, "nombre": "Fondo"},
    ]

    def test_devuelve_copias_en_el_orden_y_con_el_estado_guardado(self):
        ordenadas = capas.ordenar(self.DESCRIPTORES, "fondo:0:1,ra1b2c3:60:0,va1b2c3f:10:1")
        assert [d["id"] for d in ordenadas] == ["fondo", "ra1b2c3", "va1b2c3f"]
        assert ordenadas[1]["transparencia"] == 60 and ordenadas[1]["visible"] is False
        assert ordenadas[1]["nombre"] == "Ortofoto"
        assert "visible" not in self.DESCRIPTORES[1], "no se tocan los originales"

    def test_sin_estado_conserva_el_orden_por_omision(self):
        ordenadas = capas.ordenar(self.DESCRIPTORES, None)
        assert [d["id"] for d in ordenadas] == ["va1b2c3f", "ra1b2c3", "fondo"]
        assert all(d["visible"] and d["transparencia"] == 0 for d in ordenadas)


class TestIdentificadoresEstables:
    def test_el_de_un_raster_sale_de_su_token_y_no_de_su_posicion(self):
        assert capas.id_de_raster("D:\\obra\\a.tif") == capas.id_de_raster("D:\\obra\\a.tif")
        assert capas.id_de_raster("D:\\obra\\a.tif") != capas.id_de_raster("D:\\obra\\b.tif")
        assert capas.id_de_raster("x").startswith("r") and len(capas.id_de_raster("x")) == 7

    def test_el_de_un_vuelo_lleva_la_parte(self):
        pk = "d4e5f6a7-0000-4000-8000-000000000001"
        assert capas.id_de_vuelo(pk, "t") == "vd4e5f6t"
        assert capas.id_de_vuelo(pk, "f") == "vd4e5f6f"
        assert capas.id_de_vuelo(pk, "c") == "vd4e5f6c"

    def test_ningun_identificador_lleva_coma_ni_dos_puntos(self):
        ids = [capas.id_de_raster("a:b,c"), capas.id_de_vuelo("1-2", "f"), capas.id_de_fondo()]
        assert all("," not in i and ":" not in i for i in ids)


class TestLaCalidadDeUnaFoto:
    @pytest.mark.parametrize(
        ("calidad", "clase"),
        [
            ("PPK", "buena"),
            ("fija", "buena"),
            ("Flotante", "flotante"),
            ("simple", "simple"),
            ("SBAS", "simple"),
            ("dgps", "simple"),
            ("ppp", "simple"),
            ("", "sin"),
            (None, "sin"),
            ("rara", "sin"),
        ],
    )
    def test_cada_calidad_su_clase(self, calidad, clase):
        assert capas.clase_de_calidad(calidad) == clase

    def test_la_clase_es_la_misma_del_visor_del_vuelo(self):
        """`vuelo.js` decide con las mismas listas: si una cambia, la otra debe cambiar."""
        from pathlib import Path

        js = (Path(__file__).resolve().parents[2] / "static" / "js" / "vuelo.js").read_text(
            encoding="utf-8"
        )
        assert '"ppk" || c === "fija"' in js or 'c === "ppk" || c === "fija"' in js
        assert '["simple", "sbas", "dgps", "ppp"]' in js
