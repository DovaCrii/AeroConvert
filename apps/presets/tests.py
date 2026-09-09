"""Preajustes: el sembrado idempotente, la copia y la puerta."""

import pytest
from django.contrib.auth import get_user_model

from apps.presets.models import ConversionPreset, sembrar
from apps.targets import perfiles as perfiles_mod

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def entrado(client, usuario):
    client.force_login(usuario)
    return client


class TestSembrado:
    def test_crea_uno_por_perfil(self):
        creados, actualizados = sembrar()
        assert creados == len(perfiles_mod.PERFILES)
        assert actualizados == 0

    def test_correrlo_dos_veces_no_duplica(self):
        """Un `get_or_create` por nombre visible se rompe en cuanto alguien renombra el
        preajuste. Por `slug` es estable."""
        sembrar()
        creados, actualizados = sembrar()
        assert creados == 0
        assert actualizados == len(perfiles_mod.PERFILES)
        assert ConversionPreset.objects.count() == len(perfiles_mod.PERFILES)

    def test_hereda_las_opciones_del_perfil(self):
        """Se derivan y no se copian a mano justo por lo que pasó con las claves: si mañana
        el perfil corrige una opción, el preajuste la hereda sin que nadie se acuerde."""
        sembrar()
        preajuste = ConversionPreset.objects.get(target_profile_id="civil3d")
        assert preajuste.options == perfiles_mod.CIVIL3D.opciones
        assert preajuste.target_format_code == "geotiff"

    def test_resembrar_corrige_un_preajuste_desviado(self):
        sembrar()
        ConversionPreset.objects.filter(target_profile_id="civil3d").update(
            options={"compresion": "MAL"}
        )
        sembrar()
        preajuste = ConversionPreset.objects.get(target_profile_id="civil3d")
        assert preajuste.options == perfiles_mod.CIVIL3D.opciones

    def test_los_de_fabrica_quedan_marcados(self):
        sembrar()
        assert ConversionPreset.objects.filter(de_fabrica=True).count() == len(
            perfiles_mod.PERFILES
        )
        assert all(not p.editable for p in ConversionPreset.objects.all())

    def test_el_nombre_del_destino_se_resuelve_en_el_modelo(self):
        """Encadenar filtros en la plantilla para buscar en un diccionario es la forma de
        que devuelva lo que no era."""
        sembrar()
        preajuste = ConversionPreset.objects.get(target_profile_id="civil3d")
        assert "GeoTIFF" in preajuste.nombre_destino


class TestUso:
    def test_usar_suma_sin_tocar_el_resto(self):
        sembrar()
        preajuste = ConversionPreset.objects.first()
        preajuste.usar()
        preajuste.refresh_from_db()
        assert preajuste.veces_usado == 1


class TestVistas:
    def test_sin_entrar_no_se_ven(self, client):
        respuesta = client.get("/preajustes/")
        assert respuesta.status_code == 302
        assert "/entrar/" in respuesta["Location"]

    def test_se_listan(self, entrado):
        sembrar()
        contenido = entrado.get("/preajustes/").content.decode()
        assert "Civil 3D" in contenido
        assert "De fábrica" in contenido

    def test_copiar_crea_uno_propio(self, entrado, usuario):
        sembrar()
        original = ConversionPreset.objects.get(target_profile_id="civil3d")

        entrado.post(f"/preajustes/{original.slug}/copiar/")

        copia = ConversionPreset.objects.get(de_fabrica=False)
        assert copia.owner == usuario
        assert copia.options == original.options
        assert copia.editable is True

    def test_copiar_dos_veces_no_choca_de_slug(self, entrado):
        sembrar()
        original = ConversionPreset.objects.get(target_profile_id="civil3d")
        entrado.post(f"/preajustes/{original.slug}/copiar/")
        entrado.post(f"/preajustes/{original.slug}/copiar/")
        assert ConversionPreset.objects.filter(de_fabrica=False).count() == 2

    def test_los_de_fabrica_no_se_borran(self, entrado):
        """Son el punto de partida de todos los demás; perderlos dejaría a alguien sin
        referencia."""
        sembrar()
        original = ConversionPreset.objects.get(target_profile_id="civil3d")

        entrado.post(f"/preajustes/{original.slug}/borrar/")

        assert ConversionPreset.objects.filter(slug=original.slug).exists()

    def test_los_propios_si_se_borran(self, entrado):
        sembrar()
        original = ConversionPreset.objects.get(target_profile_id="civil3d")
        entrado.post(f"/preajustes/{original.slug}/copiar/")
        copia = ConversionPreset.objects.get(de_fabrica=False)

        entrado.post(f"/preajustes/{copia.slug}/borrar/")

        assert not ConversionPreset.objects.filter(pk=copia.pk).exists()

    def test_copiar_y_borrar_no_admiten_get(self, entrado):
        """Cambian estado: un enlace o una imagen en un correo no pueden dispararlos."""
        sembrar()
        slug = ConversionPreset.objects.first().slug
        assert entrado.get(f"/preajustes/{slug}/copiar/").status_code == 405
        assert entrado.get(f"/preajustes/{slug}/borrar/").status_code == 405
