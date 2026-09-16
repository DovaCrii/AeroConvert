"""El catálogo de todo lo que se puede hacer, y su buscador.

Las capacidades vivían en tres pantallas que no se hablan: «Convertir» para lo geoespacial,
«PDF» para los once de documentos, y «Compatibilidad» para la matriz. Quien llega con un
archivo y una intención —«juntar estos planos y numerarlos»— tenía que saber de antemano en
cuál mirar.

Lo que estas pruebas fijan es lo que hace útil al buscador: **que encuentre por la palabra que
usa quien busca, no por la que eligió quien programó.**
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from . import acciones as acciones_mod

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def sesion(client, db, settings):
    settings.MODO = "taller"
    usuario = get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106
    client.force_login(usuario)
    return client


def _nombres(grupos):
    return [a.nombre for g in grupos for a in g["acciones"]]


class TestElCatalogo:
    def test_estan_las_de_pdf_y_las_geoespaciales(self):
        categorias = {a.categoria for a in acciones_mod.todas()}
        assert "documentos" in categorias
        assert "planos" in categorias

    def test_lo_geoespacial_entra_por_destino_y_no_por_par_de_formatos(self):
        """La matriz tiene 189 celdas. Esto contesta «¿qué quiero hacer?», que es una
        pregunta con veinte respuestas, no con ciento ochenta y nueve."""
        planos = [a for a in acciones_mod.todas() if a.categoria == "planos"]
        assert 0 < len(planos) <= 12
        assert all(a.nombre.startswith("Llevarlo a") for a in planos)

    def test_cada_una_dice_que_sale(self):
        assert all(a.sale for a in acciones_mod.todas())


class TestQueLaTarjetaNoTireLaEleccion:
    """**El defecto que traía este catálogo desde que se escribió.**

    Las seis tarjetas geoespaciales apuntaban a `dashboard:convertir` a secas. O sea que
    pulsar «Llevarlo a QGIS» —una tarjeta cuyo único contenido es esa elección— llevaba a la
    pantalla genérica a elegir otra vez. Resolvía bien la URL y por eso no fallaba nada.
    """

    def _planos(self):
        return [a for a in acciones_mod.todas() if a.categoria == "planos"]

    def test_cada_destino_lleva_el_suyo_en_el_enlace(self):
        for accion in self._planos():
            assert accion.consulta.get("destino"), accion.nombre
            assert f"destino={accion.consulta['destino']}" in accion.enlace

    def test_y_por_eso_los_seis_enlaces_son_distintos(self):
        enlaces = {a.enlace for a in self._planos()}
        assert len(enlaces) == len(self._planos())

    def test_una_accion_sin_consulta_no_arrastra_interrogacion(self):
        """Las de PDF no llevan parámetros: un `?` suelto al final es basura en la barra."""
        pdf = [a for a in acciones_mod.todas() if a.categoria == "documentos" and a.url]
        assert pdf
        assert all("?" not in a.enlace for a in pdf)

    def test_una_apagada_no_tiene_a_donde_ir(self):
        for accion in acciones_mod.todas():
            if not accion.disponible:
                assert accion.enlace == ""


class TestQueLasSeisNoSeanLaMismaTarjeta:
    """Icono, color y «Sale:» distinguían cero: los seis compartían los tres."""

    def _planos(self):
        return [a for a in acciones_mod.todas() if a.categoria == "planos"]

    def test_cada_una_con_su_icono(self):
        iconos = {a.icono for a in self._planos()}
        assert len(iconos) == len(self._planos())

    def test_y_ninguna_dice_ya_el_formato_que_ese_programa_abre(self):
        """Una línea igual en las seis no informa: ocupa dos renglones y no distingue nada."""
        for accion in self._planos():
            assert "el formato que ese programa abre" not in accion.sale

    def test_el_sale_nombra_formatos_de_verdad(self):
        salidas = {a.sale for a in self._planos()}
        assert len(salidas) > 1, "Si todas dicen lo mismo, seguimos igual."
        qgis = next(a for a in self._planos() if a.consulta["destino"] == "qgis")
        # COG para ráster, GeoPackage para vectorial y COPC para nubes: los tres destinos
        # que el perfil declara en `destinos_por_familia`.
        assert "COG" in qgis.sale
        assert "GeoPackage" in qgis.sale

    def test_no_repite_un_formato_cuando_coincide_con_el_de_por_omision(self):
        """Google Earth va a KMZ y solo a KMZ: «KMZ · KMZ» sería un fallo visible."""
        tierra = next(a for a in self._planos() if a.consulta["destino"] == "google-earth")
        assert tierra.sale == "KMZ"

    def test_las_seis_llevan_la_familia_de_color_propia(self):
        assert {a.familia for a in self._planos()} == {"destino"}


class TestElBuscador:
    def test_sin_texto_salen_todas(self):
        assert len(_nombres(acciones_mod.por_categoria())) == len(acciones_mod.todas())

    def test_encuentra_por_el_nombre(self):
        assert "Unir PDF" in _nombres(acciones_mod.por_categoria("unir"))

    def test_y_por_una_palabra_que_no_esta_en_el_nombre(self):
        """**Lo que hace útil a un buscador.** Nadie escribe «unir»: escribe «juntar»."""
        assert "Unir PDF" in _nombres(acciones_mod.por_categoria("juntar"))

    def test_encuentra_la_marca_de_agua_por_lo_que_estampa(self):
        assert "Marca de agua" in _nombres(acciones_mod.por_categoria("confidencial"))

    def test_encuentra_proteger_por_contrasena(self):
        assert "Proteger PDF" in _nombres(acciones_mod.por_categoria("clave"))

    def test_varias_palabras_en_cualquier_orden(self):
        """«Todas tienen que aparecer», y da igual el orden y en qué campo estén."""
        assert _nombres(acciones_mod.por_categoria("pdf juntar"))
        assert _nombres(acciones_mod.por_categoria("juntar pdf"))

    def test_lo_que_no_existe_no_devuelve_nada(self):
        assert acciones_mod.por_categoria("xilofono") == []

    @pytest.mark.parametrize(
        ("con", "sin"), [("contraseña", "contrasena"), ("numeración", "numeracion")]
    )
    def test_los_acentos_y_la_ene_no_cambian_nada(self, con, sin):
        """**Un fallo que se veía.** «quitar contraseña» —escrito como lo escribe cualquiera—
        no encontraba nada, porque los sinónimos están sin acentos y se comparaba literal. Y
        cero resultados se lee como «no se puede», que era falso."""
        assert _nombres(acciones_mod.por_categoria(con)) == _nombres(
            acciones_mod.por_categoria(sin)
        )
        assert _nombres(acciones_mod.por_categoria(con)), f"«{con}» no encuentra nada."

    def test_una_palabra_de_mas_no_tira_la_busqueda(self):
        """«juntar planos» daba cero: «juntar» sí está y «planos» no, y se exigían las dos. Se
        descartan los términos que no encuentran nada **por sí solos**, no se rebaja a
        «cualquiera de las palabras» — eso devolvería media aplicación."""
        assert "Unir PDF" in _nombres(acciones_mod.por_categoria("juntar planos"))

    def test_pero_una_palabra_inventada_sola_sigue_sin_devolver_nada(self):
        """El respaldo no puede convertirse en «siempre hay resultados»."""
        assert acciones_mod.por_categoria("xilofono") == []
        assert acciones_mod.por_categoria("xilofono trombon") == []

    def test_y_no_se_ensancha_una_busqueda_que_ya_encontraba(self):
        """Si exigir todas ya devuelve algo, el respaldo no entra: «marca de agua» no puede
        empezar a devolver todo lo que lleve «de»."""
        estricta = _nombres(acciones_mod.por_categoria("marca agua"))
        assert estricta == ["Marca de agua"]

    def test_una_categoria_vacia_no_se_pinta(self):
        """Un encabezado sobre un hueco hace pensar que algo se rompió."""
        grupos = acciones_mod.por_categoria("contrasena")
        assert all(g["acciones"] for g in grupos)


class TestBuscarPorParDeFormatos:
    """**El hueco que dejaba un catálogo ordenado por intención.**

    «Llevarlo a QGIS» cubre a quien llega con un archivo y una necesidad. No cubre a quien ya
    sabe exactamente lo que quiere: escribir «tif a jp2» no encontraba nada, aunque la
    aplicación sepa hacerlo desde la primera fase. Y cero resultados se lee como «no se
    puede», que es una respuesta falsa.
    """

    @pytest.mark.parametrize(
        "escrito",
        ["tif a jp2", "de tif a jp2", "tif jp2", "geotiff jpeg2000", "pasar un tif a jp2"],
    )
    def test_lo_encuentra_se_escriba_como_se_escriba(self, escrito):
        respuesta = acciones_mod.conversion_pedida(escrito)
        assert respuesta is not None, escrito
        assert (respuesta.origen, respuesta.destino) == ("geotiff", "jp2")
        assert respuesta.se_puede

    def test_un_tif_es_el_clasico_y_no_el_cog(self):
        """`.tif` es extensión de `geotiff`, `cog` y `bigtiff` a la vez. Quien escribe «un tif»
        quiere decir el clásico; sin desempate salía `cog`, o sea el orden del diccionario."""
        assert acciones_mod.formatos_nombrados("tif")[0] == "geotiff"

    def test_dos_formatos_pegados_se_encuentran_los_dos(self):
        """Compartían el espacio de en medio: el primero se lo quedaba y el segundo dejaba de
        existir. La búsqueda devolvía un solo formato y por tanto ninguna respuesta."""
        assert acciones_mod.formatos_nombrados("geotiff jpeg2000") == ["geotiff", "jp2"]

    def test_el_nombre_largo_gana_al_codigo_corto(self):
        """«jpeg 2000» tiene que ganar a «jpeg» aunque «jpeg» sea un código exacto: al revés se
        come las cuatro primeras letras y deja un «2000» suelto que no es nada."""
        assert acciones_mod.formatos_nombrados("jpeg 2000")[0] == "jp2"

    def test_con_un_solo_formato_no_contesta(self):
        """Con uno no hay pregunta: «jp2» a secas puede ser de dónde o hacia dónde, y elegir
        por la persona es contestar otra cosa."""
        assert acciones_mod.conversion_pedida("jp2") is None

    def test_una_frase_normal_no_dispara_nada(self):
        """`las` y `asc` son formatos **y** palabras corrientes. Buscar por trozos convertiría
        media aplicación en un par de formatos."""
        for frase in ("juntar las paginas", "quitar la contrasena", "marca de agua"):
            assert acciones_mod.conversion_pedida(frase) is None, frase

    def test_dice_que_no_cuando_no_se_puede(self):
        """**Y eso no es lo mismo que «nada coincide».** Confundirlos manda a alguien a buscar
        de otra manera algo que sencillamente no existe."""
        respuesta = acciones_mod.conversion_pedida("tif a ecw")
        assert respuesta is not None
        assert not respuesta.se_puede
        assert respuesta.motivo

    def test_la_pantalla_lo_pinta_arriba(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "tif a jp2"}
        ).content.decode()
        assert "Sí se puede" in cuerpo
        assert "Nada coincide" not in cuerpo, "No se contesta y se desmiente en la misma página."

    def test_y_lleva_a_convertir_con_el_formato_puesto(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "tif a jp2"}
        ).content.decode()
        assert f"{reverse('dashboard:convertir')}?formato=jp2" in cuerpo

    def test_convertir_recoge_ese_formato(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir"), {"formato": "jp2"}).content.decode()
        assert "Vas a convertir a" in cuerpo
        assert 'name="formato" value="jp2"' in cuerpo

    def test_un_formato_inventado_se_ignora(self, sesion):
        respuesta = sesion.get(reverse("dashboard:convertir"), {"formato": "xilofono"})
        assert respuesta.status_code == 200
        assert 'name="formato"' not in respuesta.content.decode()


class TestCadaCategoriaEnSuSitio:
    """**Las dos columnas del desplegable llevaban al mismo sitio.**

    «Documentos y PDF» y «Texto y tablas» compartían índice: al entrar en la primera aparecían
    también las siete de Markdown y las dos de catálogos, y quien venía a pasar un Excel tenía
    que bajar por delante de nueve herramientas de PDF. Ofrecer dos columnas distintas que
    terminan en la misma pantalla es prometer una separación que no existe.
    """

    def test_cada_categoria_tiene_su_pantalla(self):
        secciones = {c[0]: c[3] for c in acciones_mod.CATEGORIAS}
        assert secciones["documentos"] and secciones["texto"]
        assert secciones["documentos"] != secciones["texto"]

    def _contenido(self, sesion, nombre: str) -> str:
        """Solo `<main>`. **La página entera no vale**: el desplegable de la barra lista todas
        las herramientas en todas las pantallas, así que buscar en el HTML completo encuentra
        siempre cualquier nombre y la prueba pasaría dijera lo que dijera el índice."""
        cuerpo = sesion.get(reverse(nombre)).content.decode()
        return cuerpo[cuerpo.index("<main") :]

    def test_en_pdf_no_salen_las_de_texto(self, sesion):
        contenido = self._contenido(sesion, "documents:inicio")
        assert "Unir PDF" in contenido
        assert "Excel a Markdown" not in contenido

    def test_y_en_texto_no_salen_las_de_pdf(self, sesion):
        contenido = self._contenido(sesion, "documents:texto")
        assert "Excel a Markdown" in contenido
        assert "Unir PDF" not in contenido

    def test_las_apagadas_se_cuentan_dentro_de_su_categoria(self, sesion):
        """Decirle a quien mira las de texto que hay dos apagadas de Office sería contarle un
        problema que no es el suyo."""
        assert sesion.get(reverse("documents:texto")).status_code == 200


class TestLosEjemplosDeBusqueda:
    """**Un buscador con truco que nadie descubre es un buscador que no sirve.**

    Este tiene tres —la palabra de quien busca, el par de formatos, y el contenido del
    archivo— y ninguno se adivina escribiendo en una caja vacía. Los ejemplos los enseñan
    pulsando, que es como se aprenden.
    """

    @pytest.mark.parametrize("texto", [e[0] for e in acciones_mod.EJEMPLOS])
    def test_todos_devuelven_algo(self, texto):
        """**Un ejemplo que no encuentra nada es peor que ninguno**: enseña, en la primera
        pantalla y con un solo clic, que el buscador no funciona."""
        hay_acciones = bool(acciones_mod.por_categoria(texto))
        hay_conversion = acciones_mod.conversion_pedida(texto) is not None
        assert hay_acciones or hay_conversion, f"«{texto}» no encuentra nada."

    def test_cada_uno_lleva_su_pista(self):
        """La pista es lo que convierte un ejemplo en una lección: dice **qué truco** está
        demostrando, no solo qué se busca."""
        assert all(pista for _, pista in acciones_mod.EJEMPLOS)

    def test_salen_en_la_portada_como_enlaces(self, sesion):
        """Enlaces y no botones: cada búsqueda tiene su dirección, que se copia y se comparte.
        Y es lo único que funcionaría sin JavaScript, que la CSP no deja poner en línea."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert cuerpo.count('class="ejemplo"') == len(acciones_mod.EJEMPLOS)
        assert "?q=juntar%20planos" in cuerpo


class TestLaBienvenida:
    """**Solo mientras hace falta, y sin guardar nada.**

    Una pantalla de «cómo funciona» separada se lee una vez y después es un clic de más todos
    los días. Una tira fija encima del catálogo ocupa el sitio de lo que se viene a hacer. El
    disparador es no haber convertido nada todavía, que es el dato que ya existe y que además
    es la definición exacta de «primera vez».
    """

    def test_sale_a_quien_no_ha_convertido_nada(self, sesion):
        assert (
            "Cómo funciona esto"
            in sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        )

    def test_y_desaparece_sola_en_cuanto_hay_un_trabajo(self, sesion, django_user_model):
        from apps.jobs.models import ConversionJob

        ConversionJob.objects.create(
            owner=django_user_model.objects.get(username="ana"),
            source_path="C:/x.tif",
            source_format_code="geotiff",
            target_format_code="cog",
        )
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Cómo funciona esto" not in cuerpo

    def test_no_estorba_cuando_se_esta_buscando(self, sesion):
        """Quien escribe algo ya sabe lo que quiere: la explicación empujaría los resultados
        hacia abajo justo cuando son lo único que importa."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer"), {"q": "unir"}).content.decode()
        assert "Cómo funciona esto" not in cuerpo


class TestElViajeCompleto:
    """De la tarjeta a la pantalla de convertir **sin perder por el camino lo elegido**.

    Es el trozo que no comprueba ninguna prueba de unidad: `Accion.enlace` puede ser perfecto
    y la pantalla de destino ignorar el parámetro, que es exactamente lo que pasaba.
    """

    def test_convertir_reconoce_el_destino_y_lo_dice(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir"), {"destino": "qgis"}).content.decode()
        assert "Vas a llevarlo a" in cuerpo
        assert "QGIS" in cuerpo

    def test_y_lo_lleva_escondido_para_que_la_ficha_lo_marque(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir"), {"destino": "civil3d"}).content.decode()
        assert 'name="destino" value="civil3d"' in cuerpo

    def test_sin_destino_no_aparece_la_linea_ni_el_campo(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
        assert "Vas a llevarlo a" not in cuerpo
        assert 'name="destino"' not in cuerpo

    def test_un_destino_inventado_se_ignora_en_silencio(self, sesion):
        """Lo escribe cualquiera en la barra. La pantalla sin preferencia funciona igual, así
        que no hay nada que avisar — y un mensaje de error aquí sería ruido."""
        respuesta = sesion.get(reverse("dashboard:convertir"), {"destino": "xilofono"})
        assert respuesta.status_code == 200
        assert 'name="destino"' not in respuesta.content.decode()


class TestLaPantalla:
    def test_abre(self, sesion):
        respuesta = sesion.get(reverse("dashboard:que_puedo_hacer"))
        assert respuesta.status_code == 200
        assert "¿Qué necesitas hacer?" in respuesta.content.decode()

    def test_filtra_con_lo_escrito(self, sesion):
        """**Se mira el fragmento, no la página.**

        La página entera trae ahora el desplegable de la barra, que lista todas las
        herramientas en todas las pantallas: buscar «Marca de agua» en el HTML completo la
        encuentra siempre, y la prueba pasaría dijera lo que dijera el buscador.
        """
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"),
            {"q": "contrasena"},
            headers={"HX-Request": "true"},
        ).content.decode()
        assert "Proteger PDF" in cuerpo
        assert "Marca de agua" not in cuerpo

    def test_htmx_devuelve_solo_el_fragmento(self, sesion):
        """Sin la página entera: es lo que se reemplaza con cada tecla."""
        respuesta = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "unir"}, headers={"HX-Request": "true"}
        )
        cuerpo = respuesta.content.decode()
        assert "Unir PDF" in cuerpo
        assert "<!doctype html>" not in cuerpo.lower()

    def test_sin_resultados_lo_dice_y_ofrece_donde_mirar(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "xilofono"}
        ).content.decode()
        assert "Nada coincide" in cuerpo
        assert reverse("engines:matriz") in cuerpo

    def test_hay_que_haber_entrado(self, client):
        assert client.get(reverse("dashboard:que_puedo_hacer")).status_code == 302

    def test_es_la_portada(self):
        """**Estaba escrita como «la puerta que faltaba» y vivía en `/que-hacer/`.**

        O sea que solo llegaba quien ya sabía que existía, que es justo lo contrario de una
        puerta. Es la única pantalla que empieza preguntando la intención, y quien entra trae
        una intención, no un formato.
        """
        assert reverse("dashboard:que_puedo_hacer") == "/"

    def test_y_es_a_donde_lleva_entrar(self, client, db, settings):
        settings.MODO = "taller"
        get_user_model().objects.create_user("bea", password=CLAVE)  # nosec B106
        respuesta = client.post(reverse("login"), {"username": "bea", "password": CLAVE})
        assert respuesta.status_code == 302
        assert respuesta["Location"] == reverse("dashboard:que_puedo_hacer")

    def test_el_rotulo_no_dice_TODO(self, sesion):
        """El CSS lo pone en mayúsculas, y «TODO» a secas es el marcador de pendiente que
        dejamos los programadores — delante de un equipo que sabe lo que es."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert ">TODO<" not in cuerpo.replace(" ", "").replace("\n", "")
        assert "Inicio" in cuerpo, "La portada tiene que decir dónde estás."

    def test_la_barra_no_crece_sin_control(self, sesion):
        """**La barra no puede envolver, así que hay un tope de entradas.**

        Con seis más el buscador se partía en dos líneas, y eso duplica la altura de la
        cabecera en todas las pantallas a cambio de nada. Lo que sobra se mueve al desplegable
        —ahí fue «Preajustes»— o se queda en icono, como «Cuentas».

        Cuatro con palabra es lo que cabe cómodo en un portátil. Si esta prueba falla es que
        alguien añadió una quinta: la decisión no es subir el número, es decidir cuál baja.
        """
        import re

        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        barra = cuerpo[cuerpo.index('class="barra-nav"') : cuerpo.index("</nav>")]
        # Se cuentan las entradas, no los `<span>`: el panel del desplegable va dentro de esta
        # misma etiqueta y tiene uno por herramienta, así que contar spans daba veintiocho.
        con_palabra = [
            c for c in re.findall(r'class="(nav-item[^"]*)"', barra) if "solo-icono" not in c
        ]
        assert len(con_palabra) <= 4, f"La barra no aguanta más entradas: {con_palabra}"

    def test_preajustes_sigue_alcanzable_desde_el_menu(self, sesion):
        """Sacarlo de la barra no puede ser perderlo: se llega desde el pie del desplegable."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        menu = cuerpo[cuerpo.index('class="menu-panel"') : cuerpo.index("</details>")]
        assert reverse("presets:lista") in menu

    def test_convertir_sigue_en_la_barra(self, sesion):
        """**La pantalla que más se abre no puede vivir solo dentro de un menú.**

        Al reducir la barra de siete entradas a cuatro, «Convertir» pasó a ser el encabezado de
        una columna del desplegable. Sobre el papel coherente; en uso, volver a ella desde la
        portada exigía abrir el menú y acertar con el título de una columna.
        """
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        barra = cuerpo[cuerpo.index('class="barra-nav"') : cuerpo.index("</nav>")]
        assert f'href="{reverse("dashboard:convertir")}"' in barra
        assert "<span>Convertir</span>" in barra
