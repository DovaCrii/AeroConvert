"""Perfiles de destino: **donde tiene que abrir el archivo**, no a que extension va.

## Por que el selector primario es un programa y no un formato

Porque esa es la pregunta que la gente se hace de verdad. Nadie quiere «un GeoTIFF con
BIGTIFF=NO y tres bandas»: quiere que la ortofoto abra en el PC del proyectista. Todas las
herramientas del mercado -- FME, Global Mapper, MyGeodata -- parten de que ya sabes el
formato de destino. Aqui se invierte: se elige el programa y el perfil elige el formato y
las opciones.

El caso que origino la aplicacion lo ilustra entero: una ortofoto de Metashape que abria en
la maquina de quien la genero y no en la de al lado. El archivo no estaba roto ni le
faltaba georreferencia -- era BigTIFF, y Civil 3D no lee BigTIFF. Ninguna herramienta lo
decia. Este modulo existe para decirlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.formats import catalogo

#: Severidad de un veredicto. Nunca va solo el color: cada uno lleva icono propio y texto,
#: porque uno de cada doce hombres no distingue el rojo del verde (WCAG 1.4.1).
ABRE = "abre"
CON_REPAROS = "con-reparos"
NO_ABRE = "no-abre"

ICONOS = {
    ABRE: "icon-veredicto-abre",
    CON_REPAROS: "icon-veredicto-reparos",
    NO_ABRE: "icon-veredicto-no",
}
ETIQUETAS = {ABRE: "Abre", CON_REPAROS: "Abre con reparos", NO_ABRE: "No abre"}


@dataclass(frozen=True)
class Veredicto:
    perfil_id: str
    perfil_nombre: str
    severidad: str
    #: Una linea. Si hace falta un parrafo, el veredicto esta mal escrito.
    motivo: str
    #: Que hacer. Vacio cuando ya abre.
    remedio: str = ""

    @property
    def icono(self) -> str:
        return ICONOS[self.severidad]

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self.severidad]


@dataclass(frozen=True)
class PerfilDeDestino:
    id: str
    nombre: str
    descripcion: str
    #: Formatos que este programa lee sin problema, en orden de preferencia.
    formatos_preferidos: tuple[str, ...]
    #: Formatos que lee, pero no son la mejor opcion.
    formatos_aceptados: tuple[str, ...] = ()
    #: El formato al que se convierte cuando se elige este perfil.
    formato_destino: str = ""
    #: Y el que se usa cuando la entrada es de otra familia.
    #:
    #: Un perfil es «donde tiene que abrir», no «a qué formato». Civil 3D quiere un GeoTIFF
    #: si le llega una ortofoto y un LandXML si le llega una libreta de puntos, y son la
    #: misma respuesta a la misma pregunta. Sin esto, el boton de Civil 3D salia apagado
    #: delante de una libreta -- diciendo que no se puede -- porque el unico destino que
    #: sabia ofrecer era el raster.
    destinos_por_familia: dict[str, str] = field(default_factory=dict)
    #: Las opciones que fija el perfil. Se pueden ver y cambiar en «ajustar a mano».
    opciones: dict = field(default_factory=dict)
    #: Acompanantes que hay que escribir al lado.
    escribir_acompanantes: tuple[str, ...] = ()

    def lee(self, codigo_formato: str) -> bool:
        return (
            codigo_formato in self.formatos_preferidos or codigo_formato in self.formatos_aceptados
        )

    def destino_para(self, familia: str) -> str:
        """El formato al que lleva este perfil una entrada de esa familia."""
        return self.destinos_por_familia.get(familia, self.formato_destino)


# --- Los perfiles ----------------------------------------------------------

CIVIL3D = PerfilDeDestino(
    id="civil3d",
    nombre="Civil 3D / AutoCAD",
    descripcion="Lo que abre en cualquier puesto con Civil 3D, tenga o no Raster Design.",
    # TIFF clasico primero: es lo que abre AutoCAD base, sin complementos.
    formatos_preferidos=("geotiff", "landxml"),
    formatos_aceptados=("jp2", "ecw", "mrsid", "img", "png", "jpeg", "dxf", "puntos"),
    formato_destino="geotiff",
    # Una libreta de puntos va a **LandXML**, no a un ráster.
    #
    # Y no a DXF, que también se podría: un DXF entra en Civil 3D como dibujo —entidades
    # `AcDbPoint` sueltas— y un LandXML entra como grupo de puntos COGO, con su número y su
    # descripción. Es la diferencia entre entregar un plano y entregar topografía.
    destinos_por_familia={"vector": "landxml"},
    # **Las claves son las que declara el motor, no las de GDAL.**
    #
    # Escribirlas como `COMPRESS` o `BLOCKXSIZE` parecia natural -- es lo que acaba en el
    # comando -- y estaba mal: el motor lee `compresion` y `tamano_tesela`, asi que el
    # perfil no fijaba nada y el trabajo salia con los valores por omision. El perfil de
    # Civil 3D prometia descartar la banda alfa y **no lo hacia**.
    #
    # Es justo el fallo que la regla de «las opciones las declara el motor» existe para
    # impedir, y hay una prueba que compara ambos vocabularios para que no vuelva.
    opciones={
        # La opcion que resuelve el caso que origino la aplicacion.
        "bigtiff": "NO",
        "compresion": "DEFLATE",
        "tamano_tesela": "512",
        "solo_rgb": True,
        "piramides": "2 4 8 16 32",
    },
)

QGIS = PerfilDeDestino(
    id="qgis",
    nombre="QGIS",
    descripcion="Lee practicamente todo. El destino recomendado es COG.",
    formatos_preferidos=("cog", "geotiff", "bigtiff", "gpkg"),
    formatos_aceptados=(
        "jp2",
        "ecw",
        "mrsid",
        "img",
        "asc",
        "shp",
        "kml",
        "kmz",
        "geojson",
        "las",
        "laz",
        "copc",
        # QGIS abre una libreta de puntos como **texto delimitado**, preguntando qué columna
        # es la X y cuál la Y. Decir que «no la abre» seria mentir; el veredicto de una
        # libreta lo escribe `_veredicto_de_libreta`, que es donde está el matiz que importa.
        "puntos",
    ),
    formato_destino="cog",
    # GeoPackage para lo vectorial: un solo archivo, con el CRS y los atributos dentro. Es lo
    # que el propio catalogo llama «el destino recomendado». Y COPC para nubes, que es lo que
    # QGIS abre por rangos sin cargarla entera.
    destinos_por_familia={"vector": "gpkg", "nube": "copc"},
    opciones={"compresion": "DEFLATE"},
)

ARCGIS = PerfilDeDestino(
    id="arcgis",
    nombre="ArcGIS Pro",
    descripcion="Lee BigTIFF y la mayoria de los raster; prefiere GeoTIFF o CRF.",
    formatos_preferidos=("geotiff", "bigtiff", "cog", "img", "gpkg"),
    # `puntos`: ArcGIS los importa con «XY Table To Point», eligiendo las columnas a mano.
    formatos_aceptados=("jp2", "ecw", "mrsid", "asc", "shp", "geojson", "las", "laz", "puntos"),
    formato_destino="geotiff",
    # Shapefile y no GeoPackage: ArcGIS lee los dos, pero el shapefile sigue siendo lo que
    # espera media administracion publica cuando pide «los puntos». Quien quiera GPKG lo
    # tiene a un clic en «ajustar a mano».
    destinos_por_familia={"vector": "shp", "nube": "laz"},
    # ArcGIS si lee BigTIFF, asi que no hay razon para forzar el clasico y arriesgarse a
    # que un raster grande no quepa.
    opciones={"compresion": "LZW", "bigtiff": "IF_SAFER", "piramides": "2 4 8 16 32"},
)

GOOGLE_EARTH = PerfilDeDestino(
    id="google-earth",
    nombre="Google Earth",
    descripcion="Solo KMZ con superposicion teselada, y en EPSG:4326.",
    formatos_preferidos=("kmz",),
    formatos_aceptados=("kml",),
    formato_destino="kmz",
    opciones={"reproyectar_a": "EPSG:4326", "teselar": True},
)

WEB = PerfilDeDestino(
    id="web",
    nombre="Visor web",
    descripcion="COG servido por rangos HTTP: se ve el trozo que se mira, no el archivo.",
    formatos_preferidos=("cog",),
    formatos_aceptados=("mbtiles", "geojson", "copc"),
    formato_destino="cog",
    # GeoJSON para lo vectorial y COPC para nubes: los dos formatos que un visor lee sin
    # servidor detras. Y los dos van en EPSG:4326 o por rangos, que es lo que los hace web.
    destinos_por_familia={"vector": "geojson", "nube": "copc"},
    opciones={"compresion": "DEFLATE"},
)

AEROBIM = PerfilDeDestino(
    id="aerobim",
    nombre="AeroBim",
    descripcion="La aplicacion hermana: COG para raster, COPC para nubes, DXF para planos.",
    formatos_preferidos=("cog", "copc", "dxf", "ifc"),
    formato_destino="cog",
    # Lo que ya dice su propia descripcion, ahora tambien en el boton: DXF para planos y
    # COPC para nubes. Antes prometia las tres cosas y solo sabia ofrecer la primera.
    destinos_por_familia={"vector": "dxf", "nube": "copc"},
    opciones={"compresion": "DEFLATE"},
)

PERFILES: dict[str, PerfilDeDestino] = {
    p.id: p for p in (CIVIL3D, QGIS, ARCGIS, GOOGLE_EARTH, WEB, AEROBIM)
}


def perfil(identificador: str) -> PerfilDeDestino:
    return PERFILES[identificador]


# --- Los veredictos --------------------------------------------------------
#
# Cada regla vive aqui, con su motivo escrito para una persona. Que sea una lista de
# funciones y no un `if` gigante es a proposito: agregar «Bentley MicroStation» tiene que
# ser agregar una regla, no editar un arbol.


def _veredicto_civil3d(inspeccion) -> Veredicto:
    tiff = inspeccion.tiff
    codigo = inspeccion.codigo_formato

    if codigo == "bigtiff":
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=NO_ABRE,
            motivo="Es BigTIFF, y Civil 3D no lee BigTIFF aunque la extensión sea .tif.",
            remedio="Reescribir como TIFF clásico. No pierde un solo píxel.",
        )

    if not CIVIL3D.lee(codigo):
        formato = catalogo.FORMATOS.get(codigo)
        nombre = formato.nombre if formato else codigo or "desconocido"
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=NO_ABRE,
            motivo=f"Civil 3D no abre {nombre}.",
            remedio=_remedio_hacia(CIVIL3D, inspeccion),
        )

    if codigo == "puntos":
        # **Este es el formato nativo de puntos de Civil 3D**, así que el veredicto no es
        # que no abra: es que al importarlo hay que elegir el formato de puntos —PNEZD,
        # PENZD— de una lista, y ahí está todo el riesgo. En LandXML no hay lista que
        # elegir: el orden y el sistema de referencia van dentro del archivo.
        base = _veredicto_de_libreta(CIVIL3D, inspeccion)
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=base.severidad,
            motivo=base.motivo,
            remedio=(
                "Convertir a LandXML: entra como grupo de puntos COGO, con el orden y el "
                "EPSG dentro, y sin lista que elegir."
            ),
        )

    if tiff is not None and tiff.tiene_alfa:
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Trae banda alfa: AutoCAD suele pintarla como una banda gris o dejar negro.",
            remedio="Escribir tres bandas y pasar el alfa a mascara.",
        )

    if codigo in ("jp2", "ecw", "mrsid"):
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Necesita Raster Design o Map 3D; AutoCAD base no lo lee.",
            remedio="Si el puesto no lo tiene, convertir a GeoTIFF clásico.",
        )

    if not inspeccion.crs.conocido:
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero sin sistema de referencia: entrara en el origen del dibujo.",
            remedio="Declarar el EPSG y escribir el .prj al lado.",
        )

    return Veredicto(CIVIL3D.id, CIVIL3D.nombre, ABRE, "Abre tal cual.")


def _remedio_hacia(perfil_destino: PerfilDeDestino, inspeccion) -> str:
    """«Convertir a X.», con la X que de verdad se va a ofrecer.

    **Por familia.** Antes se leía `formato_destino` a secas, y delante de una libreta de
    puntos el veredicto de QGIS decía «convertir a Cloud Optimized GeoTIFF» — un ráster, a
    partir de un archivo de texto con coordenadas — mientras el botón de al lado ofrecía
    GeoPackage. Dos respuestas distintas a la misma pregunta, en la misma pantalla.
    """
    destino = catalogo.FORMATOS.get(perfil_destino.destino_para(inspeccion.familia))
    return f"Convertir a {destino.nombre}." if destino else ""


#: Lo que hay que decir de una libreta de puntos en **cualquier** programa que la abra.
#:
#: Es la frase que resume el producto entero: el archivo se abre, y ahí está el problema. Va
#: corta porque el motivo es **una línea** de la tira de veredictos; la consecuencia y el
#: arreglo van en el remedio, que es la segunda.
AVISO_DEL_ORDEN = "Abre, pero hay que elegir a mano el orden de columnas, y elegir mal no avisa."


def _veredicto_de_libreta(perfil_destino: PerfilDeDestino, inspeccion) -> Veredicto:
    """El veredicto de un archivo de puntos en un programa que sí lo lee.

    **Nunca es «abre tal cual», por bien que esté el archivo.** QGIS lo abre como texto
    delimitado y ArcGIS con «XY Table To Point»; los dos preguntan qué columna es la X y
    cuál la Y, y los dos aceptan la respuesta equivocada sin decir nada. Marcar esto en
    verde sería tranquilizar a alguien justo antes del único paso donde se puede equivocar.
    """
    if inspeccion.puntos is not None and inspeccion.puntos.hay_que_preguntar:
        aviso = "Aquí el orden no se puede deducir del rango UTM: hay que elegirlo. "
    else:
        aviso = "Equivocarse deja los puntos a miles de kilómetros. "

    return Veredicto(
        perfil_id=perfil_destino.id,
        perfil_nombre=perfil_destino.nombre,
        severidad=CON_REPAROS,
        motivo=AVISO_DEL_ORDEN,
        remedio=aviso + _remedio_hacia(perfil_destino, inspeccion) + " Ahí ya va resuelto.",
    )


def _veredicto_generico(perfil_destino: PerfilDeDestino, inspeccion) -> Veredicto:
    codigo = inspeccion.codigo_formato

    if not perfil_destino.lee(codigo):
        formato = catalogo.FORMATOS.get(codigo)
        nombre = formato.nombre if formato else codigo or "desconocido"
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=NO_ABRE,
            motivo=f"{perfil_destino.nombre} no abre {nombre}.",
            remedio=_remedio_hacia(perfil_destino, inspeccion),
        )

    if codigo == "puntos":
        return _veredicto_de_libreta(perfil_destino, inspeccion)

    if not inspeccion.crs.conocido and codigo not in ("kml", "kmz"):
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero no declara sistema de referencia.",
            remedio="Declarar el EPSG antes de convertir.",
        )

    if codigo not in perfil_destino.formatos_preferidos:
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero no es el formato que mejor le sienta.",
            remedio=_remedio_hacia(perfil_destino, inspeccion),
        )

    return Veredicto(perfil_destino.id, perfil_destino.nombre, ABRE, "Abre tal cual.")


#: Megapíxeles a partir de los cuales una superposición de Google Earth hay que teselarla.
#:
#: No es un límite documentado con una cifra redonda, es la práctica: Google Earth remuestrea
#: cada `GroundOverlay` a la textura que la tarjeta admita —del orden de 2048 × 2048— así que
#: una imagen mucho mayor se ve borrosa entera, no en detalle al acercarse. Lo que resuelve
#: eso es una `SuperOverlay`: la misma imagen partida en teselas con niveles.
MPX_QUE_OBLIGAN_A_TESELAR = 20.0


def _veredicto_google_earth(inspeccion) -> Veredicto:
    """Google Earth es el destino más estrecho, y decirlo entero ahorra un viaje.

    Son **tres** condiciones, no una, y las tres se descubren normalmente de una en una:
    tiene que ser KMZ, tiene que ir en EPSG:4326, y si la imagen es grande tiene que ir
    teselada. Un veredicto que solo diga «convertir a KMZ» manda a alguien a hacer un KMZ
    que se verá borroso o en el sitio equivocado.
    """
    codigo = inspeccion.codigo_formato
    tiff = inspeccion.tiff

    condiciones = []
    if inspeccion.crs.conocido and inspeccion.crs.codigo not in ("4326", ""):
        condiciones.append(f"reproyectar de EPSG:{inspeccion.crs.codigo} a EPSG:4326")
    if tiff is not None and tiff.megapixeles >= MPX_QUE_OBLIGAN_A_TESELAR:
        condiciones.append(
            f"teselar los {tiff.megapixeles:.0f} Mpx — en una sola superposición Google "
            "Earth la remuestrea entera y se ve borrosa"
        )

    # El motivo es **una línea**; las condiciones van en el remedio, que es la segunda.
    pasos = ("Hay que " + " y ".join(condiciones) + ". ") if condiciones else ""

    if GOOGLE_EARTH.lee(codigo):
        if not condiciones:
            return Veredicto(GOOGLE_EARTH.id, GOOGLE_EARTH.nombre, ABRE, "Abre tal cual.")
        return Veredicto(
            perfil_id=GOOGLE_EARTH.id,
            perfil_nombre=GOOGLE_EARTH.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero no como está.",
            remedio=pasos + _remedio_hacia(GOOGLE_EARTH, inspeccion),
        )

    formato = catalogo.FORMATOS.get(codigo)
    nombre = formato.nombre if formato else codigo or "desconocido"
    return Veredicto(
        perfil_id=GOOGLE_EARTH.id,
        perfil_nombre=GOOGLE_EARTH.nombre,
        severidad=NO_ABRE,
        motivo=f"Google Earth solo abre KML y KMZ, y esto es {nombre}.",
        remedio=pasos + _remedio_hacia(GOOGLE_EARTH, inspeccion),
    )


def _veredicto_web(inspeccion) -> Veredicto:
    codigo = inspeccion.codigo_formato
    tiff = inspeccion.tiff

    if codigo == "cog":
        return Veredicto(WEB.id, WEB.nombre, ABRE, "Es COG: se sirve por rangos HTTP.")

    if tiff is not None:
        faltas = []
        if not tiff.teselado:
            faltas.append("no esta teselado")
        if not tiff.tiene_piramides_internas:
            faltas.append("no trae piramides que GDAL reconozca")
        detalle = " y ".join(faltas) if faltas else "el orden interno no es el de un COG"
        return Veredicto(
            perfil_id=WEB.id,
            perfil_nombre=WEB.nombre,
            severidad=CON_REPAROS,
            motivo=f"Se puede servir, pero {detalle}: el navegador se lo descarga entero.",
            remedio="Convertir a COG.",
        )

    return _veredicto_generico(WEB, inspeccion)


def _veredicto_aerobim(inspeccion) -> Veredicto:
    """AeroBim lee tres formatos y nada mas, y para nubes solo lee COPC.

    Un LAZ corriente **no** le sirve, aunque comparta extension con un COPC: lo que AeroBim
    necesita es el octree que va dentro. Decir «abre» porque es un `.laz` seria mandar a
    alguien a una pantalla en blanco.
    """
    codigo = inspeccion.codigo_formato

    if codigo == "copc":
        return Veredicto(AEROBIM.id, AEROBIM.nombre, ABRE, "Es COPC: se abre por rangos.")

    if codigo in ("las", "laz"):
        cabecera = inspeccion.las
        detalle = ""
        if cabecera is not None and cabecera.puntos:
            detalle = f" Son {cabecera.puntos / 1e6:.1f} millones de puntos."
        return Veredicto(
            perfil_id=AEROBIM.id,
            perfil_nombre=AEROBIM.nombre,
            severidad=NO_ABRE,
            motivo=f"AeroBim solo lee nubes en COPC, y esta no lo es.{detalle}",
            remedio="Convertir a COPC.",
        )

    return _veredicto_generico(AEROBIM, inspeccion)


#: Las reglas propias. Lo que no esta aqui usa `_veredicto_generico`.
REGLAS = {
    CIVIL3D.id: _veredicto_civil3d,
    GOOGLE_EARTH.id: _veredicto_google_earth,
    WEB.id: _veredicto_web,
    AEROBIM.id: _veredicto_aerobim,
}


def veredictos(inspeccion) -> tuple[Veredicto, ...]:
    """La tira de veredictos: un juicio por destino, cada uno con su motivo en una linea.

    Es lo primero que ve la persona despues de la ficha del archivo, y es lo que ninguna
    otra herramienta da.
    """
    salida = []
    for identificador, perfil_destino in PERFILES.items():
        regla = REGLAS.get(identificador)
        salida.append(
            regla(inspeccion) if regla else _veredicto_generico(perfil_destino, inspeccion)
        )
    return tuple(salida)
