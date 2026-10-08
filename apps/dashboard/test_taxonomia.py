"""Una sola taxonomía (F13.1): toda herramienta en exactamente un grupo, y las pantallas coinciden.

Había dos clasificaciones que no se parecían (la de la portada y el lateral, y la de
`/documentos/`), y los catálogos de Plant 3D vivían en «Sacar texto». Lo que se vigila aquí es lo
que no se ve hasta que alguien busca una herramienta donde no está: que **ninguna quede sin
grupo**, que **las pantallas lean el mismo árbol en el mismo orden**, y que el **identificador de
cada grupo no cambie con su título** (con él se recuerda, en el navegador, qué grupos dejó abiertos
cada persona).
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboard import acciones as acciones_mod
from apps.dashboard import taxonomia
from apps.documents.herramientas import HERRAMIENTAS
from apps.documents.views import estado_de_herramientas
from apps.targets import perfiles as perfiles_mod

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def _titulos(cuerpo: str, patron: str) -> list[str]:
    return re.findall(patron, cuerpo)


class TestElArbol:
    def test_los_identificadores_son_unicos_y_estables_en_formato(self):
        ids = [g.id for g in taxonomia.GRUPOS]
        assert len(ids) == len(set(ids))
        assert all(re.fullmatch(r"[a-z]+", i) for i in ids), "un id sin tildes, espacios ni guiones"

    def test_toda_herramienta_de_documentos_tiene_grupo(self):
        faltan = [h["id"] for h in HERRAMIENTAS if h["id"] not in taxonomia.DE_DOCUMENTOS]
        assert not faltan, f"sin grupo: {faltan} (añádalas a `DE_DOCUMENTOS`)"

    def test_y_no_sobra_ninguna_asignacion_a_algo_que_no_existe(self):
        ids = {h["id"] for h in HERRAMIENTAS}
        assert not set(taxonomia.DE_DOCUMENTOS) - ids

    def test_todo_perfil_cae_en_un_grupo_que_existe(self):
        for perfil in perfiles_mod.PERFILES.values():
            assert taxonomia.grupo_de_perfil(perfil) in taxonomia.POR_ID

    def test_una_herramienta_sin_grupo_levanta_en_vez_de_caer_en_uno_por_omision(self):
        with pytest.raises(KeyError, match="no tiene grupo"):
            taxonomia.grupo_de_documento("inventada")

    def test_toda_accion_del_catalogo_esta_en_exactamente_un_grupo(self):
        por_grupo: dict[str, list[str]] = {}
        for accion in acciones_mod.todas():
            assert accion.categoria in taxonomia.POR_ID, accion.nombre
            por_grupo.setdefault(accion.categoria, []).append(accion.id)
        asignadas = [i for ids in por_grupo.values() for i in ids]
        assert len(asignadas) == len(set(asignadas)) == len(acciones_mod.todas())

    def test_ningun_grupo_queda_con_menos_de_dos_salvo_los_declarados(self):
        for grupo in taxonomia.GRUPOS:
            cuantas = sum(a.categoria == grupo.id for a in acciones_mod.todas())
            assert cuantas >= 1, f"el grupo «{grupo.titulo}» está vacío"
            assert cuantas >= 2 or grupo.admite_uno, (
                f"«{grupo.titulo}» tiene una sola herramienta: añada otra o márquelo `admite_uno`"
            )

    def test_los_indices_de_documentos_leen_grupos_que_existen_y_no_se_pisan(self):
        vistos: set[str] = set()
        for ids in taxonomia.INDICES.values():
            assert set(ids) <= set(taxonomia.POR_ID)
            assert not vistos & set(ids), "un grupo en dos índices"
            vistos |= set(ids)

    def test_los_catalogos_de_planta_ya_no_estan_entre_el_texto(self):
        assert taxonomia.DE_DOCUMENTOS["catalogo_excel"] == "planta"
        assert taxonomia.DE_DOCUMENTOS["excel_catalogo"] == "planta"
        assert taxonomia.DE_DOCUMENTOS["md_a_pdf"] == "texto"


class TestLasPantallasLeenElMismoArbol:
    def test_la_portada_y_el_lateral_pintan_los_mismos_grupos_en_el_mismo_orden(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        portada = _titulos(cuerpo, r'<h2 class="grupo-titulo">([^<]+)</h2>')
        lateral = _titulos(cuerpo, r'<span class="lateral-grupo-nombre">([^<]+)</span>')
        esperado = [g.titulo for g in taxonomia.GRUPOS]
        assert lateral == esperado
        assert portada == esperado

    def test_los_dos_indices_de_documentos_enseñan_cada_uno_su_trozo_en_orden(self, sesion):
        for nombre, indice in (("documents:inicio", "documentos"), ("documents:texto", "texto")):
            cuerpo = sesion.get(reverse(nombre)).content.decode()
            cuerpo = cuerpo[cuerpo.index("<main") :]
            titulos = _titulos(cuerpo, r'<h2 class="bloque-titulo">([^<]+)</h2>')
            # **Lo que hay disponible en esta máquina, no lo que existe**: sin Access (como en el
            # CI) los catálogos están apagados, «planta» queda vacío y no se pinta. Y con un solo
            # grupo el encabezado sobra, así que tampoco sale.
            con_algo = {
                taxonomia.grupo_de_documento(h["id"])
                for h in estado_de_herramientas()
                if h["disponible"]
            }
            esperado = [
                taxonomia.POR_ID[i].titulo for i in taxonomia.INDICES[indice] if i in con_algo
            ]
            assert titulos == (esperado if len(esperado) > 1 else [])

    @pytest.mark.parametrize("hay_access", [True, False])
    def test_el_indice_de_texto_se_comporta_igual_con_y_sin_access(
        self, sesion, monkeypatch, hay_access
    ):
        """**Esto falló en el CI y no en la estación**: allí hay Access, en el CI no. Sin él los
        catálogos están apagados, «planta» queda vacío y «texto» se queda solo, sin encabezado.
        Aquí se fuerzan los dos casos para que la prueba no dependa de la máquina."""
        from apps.documents import catalogos

        estado = catalogos.Disponible(
            controlador="Microsoft Access Driver" if hay_access else "",
            motivo="" if hay_access else "No hay.",
        )
        monkeypatch.setattr(catalogos, "sondar", lambda *a, **k: estado)

        cuerpo = sesion.get(reverse("documents:texto")).content.decode()
        cuerpo = cuerpo[cuerpo.index("<main") :]
        titulos = _titulos(cuerpo, r'<h2 class="bloque-titulo">([^<]+)</h2>')

        assert "Excel a Markdown" in cuerpo
        # «Planta» ya no depende de Access: la traza de un dron (F14.18) vive ahí y no necesita
        # ningún programa, así que con o sin él hay dos grupos y los dos llevan encabezado.
        assert titulos == ["Texto, tablas y Markdown", "Imagen, video y planta"]
        assert ("Catálogo Plant 3D a Excel" in cuerpo) is hay_access

    def test_buscar_deja_los_grupos_en_el_mismo_orden_del_arbol(self):
        orden = [g.id for g in taxonomia.GRUPOS]
        grupos = [g["clave"] for g in acciones_mod.por_categoria("pdf")]
        assert grupos == sorted(grupos, key=orden.index)


class TestRecordarQueGruposSeAbrieron:
    def test_la_clave_sale_del_id_y_no_del_titulo(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        claves = re.findall(r'data-recuerda="(grupo-[^"]+|lateral-[^"]+)"', cuerpo)
        assert claves, "los grupos tienen que recordar si se abrieron"
        permitidas = {f"{p}-{g.id}" for g in taxonomia.GRUPOS for p in ("grupo", "lateral")}
        assert set(claves) <= permitidas, sorted(set(claves) - permitidas)

    def test_renombrar_un_grupo_no_cambia_su_clave(self, sesion, monkeypatch):
        antes = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        claves_antes = set(re.findall(r'data-recuerda="(lateral-[^"]+)"', antes))

        renombrados = tuple(
            taxonomia.Grupo(g.id, g.titulo + " (renombrado)", g.cuando, g.seccion, g.admite_uno)
            for g in taxonomia.GRUPOS
        )
        monkeypatch.setattr(taxonomia, "GRUPOS", renombrados)
        despues = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()

        assert "(renombrado)" in despues
        assert set(re.findall(r'data-recuerda="(lateral-[^"]+)"', despues)) == claves_antes
