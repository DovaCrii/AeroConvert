"""Ver en el mapa: una ortofoto o una imagen georreferenciada, con zoom y paneo por teselas.

## Quién puede qué

Todas las vistas piden **sesión** (`login_required`, 302 a la entrada) y son de **solo lectura**
(`require_GET`). El archivo llega por `entrada.resolver`, la puerta única: una ruta de la carpeta
compartida **dentro de las raíces permitidas** o el resultado de un trabajo **de quien pregunta**.
Lo que no pasa por ahí es un **403** con su código (`ruta-no-permitida`, `origen-no-legible`), no un
404, porque aquí no hay nada que esconder: la respuesta no confirma que el archivo exista.

## Nada sale del equipo (D5)

Las teselas las corta GDAL del propio archivo. No hay ninguna petición a un servidor de mapas, y el
JavaScript (`static/js/visor.js`) es propio y se sirve de `'self'`.
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.formats import huella as huella_mod
from apps.jobs.motivos import MOTIVOS

from . import cache, mercator, motor, terreno, teselas
from . import capa as capa_mod
from . import capas as capas_mod
from . import punto as punto_mod
from . import vuelo as vuelo_mod

registro = logging.getLogger(__name__)

#: Cuánto vive una tesela en el navegador antes de preguntar si cambió. El `ETag` hace barata la
#: pregunta (304 sin cortar nada) y el original que cambia cambia también la clave.
EDAD_EN_EL_NAVEGADOR_S = 0

#: `must-revalidate` con edad 0: el navegador **pregunta cada vez** (con `If-None-Match`, y la
#: respuesta 304 es casi gratis) y así una cuenta a la que se le quita el permiso, o una sesión que
#: se cierra, no sigue viendo teselas guardadas en ese navegador.
CACHE_CONTROL = f"private, max-age={EDAD_EN_EL_NAVEGADOR_S}, must-revalidate"

#: Cuántos niveles más allá del último útil se sirven. Acercar más inventa detalle.
NIVELES_DE_SOBRE_ACERCAMIENTO = 2

#: Lo que se enseña de las salidas propias en la pantalla de elegir.
MAXIMO_DE_PROPIOS = 8

EXTENSIONES_DE_IMAGEN = (".tif", ".tiff")


def _error(codigo: str, mensaje: str, estado: int, **extra) -> JsonResponse:
    cuerpo = {"codigo": codigo, "mensaje": mensaje, **extra}
    respuesta = JsonResponse(cuerpo, status=estado, json_dumps_params={"ensure_ascii": False})
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


def _resolver(texto: str, usuario):
    """La puerta del visor: `entrada.resolver` (ruta de la carpeta compartida, resultado propio)."""
    return entrada_mod.resolver(texto, usuario=usuario)


def _origen(request):
    """`(origen, None)` si se puede leer, o `(None, respuesta de error)`."""
    pedida = (request.GET.get("ruta") or "").strip()
    try:
        origen = _resolver(pedida, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        return None, _error(fallo.codigo, str(fallo), 403)
    if not Path(origen.ruta).is_file():
        return None, _error("origen-no-legible", "Ese archivo ya no está.", 404)
    if not _es_imagen(origen.ruta):
        return None, _error("formato-no-reconocido", _SOLO_TIFF, 422)
    return origen, None


_SOLO_TIFF = "El mapa solo abre GeoTIFF y COG (.tif o .tiff)."


def _es_imagen(ruta) -> bool:
    """Solo `.tif` y `.tiff` llegan a GDAL: un `.vrt` o un `.xml` pueden apuntar a otro archivo o a
    una dirección de internet, y abrirlos saltaría las raíces permitidas y la regla D5."""
    return Path(ruta).suffix.lower() in EXTENSIONES_DE_IMAGEN


CODIGO_DE_DISCO = "cache-no-disponible"
MENSAJE_DE_DISCO = (
    "La caché de teselas no se pudo leer o escribir. Avise a quien administra el equipo para que "
    "revise el disco."
)


def _anotar_fallo_de_disco(fallo: OSError) -> None:
    """El detalle (con rutas del servidor) va al registro; a la persona, solo el mensaje fijo."""
    registro.error("Fallo de disco en el visor: %s", fallo, exc_info=True)


def _de_disco(fallo: OSError) -> JsonResponse:
    _anotar_fallo_de_disco(fallo)
    return _error(CODIGO_DE_DISCO, MENSAJE_DE_DISCO, 500)


def _con_gdal():
    """`None` si GDAL está, o la respuesta 503 que lo dice (con su alternativa)."""
    disponibilidad = motor.disponibilidad()
    if disponibilidad.disponible:
        return None
    return _error(
        disponibilidad.codigo_motivo,
        disponibilidad.mensaje,
        503,
        sugerencia=disponibilidad.sugerencia,
    )


def _resultados_propios(usuario) -> list[dict]:
    """Las salidas de trabajos **propios**, terminados y que son una imagen que se puede ver."""
    from apps.jobs.models import HECHO, ConversionJob

    propios = []
    trabajos = ConversionJob.objects.filter(owner=usuario, status=HECHO).exclude(output_path="")
    for trabajo in trabajos.order_by("-finished_at")[:60]:
        salida = Path(trabajo.output_path)
        if salida.suffix.lower() not in EXTENSIONES_DE_IMAGEN:
            continue
        try:
            existe = salida.is_file()
        except OSError:
            existe = False
        if not existe:
            continue
        propios.append(
            {
                "token": f"{entrada_mod.PREFIJO_RESULTADO}{trabajo.pk}",
                "nombre": salida.name,
                "fecha": trabajo.finished_at,
            }
        )
        if len(propios) >= MAXIMO_DE_PROPIOS:
            break
    return propios


def _contexto_base() -> dict:
    return {
        "seccion": "mapa",
        "etiqueta_seccion": "Ver en el mapa",
        "titulo_pagina": "Ver una ortofoto en el mapa",
        "proposito": (
            "Acerque y recorra una ortofoto o una imagen georreferenciada sobre una retícula de "
            "coordenadas. Se corta del propio archivo: nada sale del equipo."
        ),
    }


def _sin_repetidos(valores: list[str]) -> list[str]:
    vistos: list[str] = []
    for v in valores:
        v = (v or "").strip()
        if v and v not in vistos:
            vistos.append(v)
    return vistos


def _vuelos_pedidos(request) -> list:
    """Los trabajos de vuelo pedidos con `vuelo=<id>`, **todos de quien mira** o 404.

    Un identificador mal formado, ajeno, de otra herramienta o sin terminar es el mismo 404: la
    respuesta no confirma que exista (como en el visor del vuelo).
    """
    trabajos = []
    for crudo in _sin_repetidos(request.GET.getlist("vuelo")):
        try:
            pk = uuid.UUID(crudo)
        except ValueError as fallo:
            raise Http404("Ese vuelo ya no está.") from fallo
        try:
            trabajos.append(vuelo_mod.propio(request.user, pk))
        except vuelo_mod.VueloNoEncontrado as fallo:
            raise Http404("Ese vuelo ya no está.") from fallo
    return trabajos


def _preparar_principal(request, contexto: dict, texto: str):
    """La imagen principal: su ficha y su estado. `None` si se dibuja o hay algo que decir en el
    mapa; una respuesta ya renderizada si no se puede ni abrir (los estados 2 de la plantilla)."""
    try:
        origen = _resolver(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto.update(error=str(fallo), codigo_error=fallo.codigo, propios=[])
        return render(request, "visor/inicio.html", contexto, status=403)

    try:
        if not _es_imagen(origen.ruta):
            raise motor.ErrorDeGdal(_SOLO_TIFF, "formato-no-reconocido")
        try:
            clave = cache.clave_de(origen.ruta)
        except OSError as fallo:
            raise motor.ErrorDeGdal("Ese archivo ya no está.", "origen-no-legible") from fallo
        capa = capa_mod.con_cache(origen.ruta, clave)
    except motor.ErrorDeGdal as fallo:
        contexto.update(
            error=str(fallo),
            codigo_error=fallo.codigo,
            propios=_resultados_propios(request.user),
        )
        return render(request, "visor/inicio.html", contexto, status=422)
    except OSError as fallo:
        _anotar_fallo_de_disco(fallo)
        contexto.update(
            error=MENSAJE_DE_DISCO,
            codigo_error=CODIGO_DE_DISCO,
            propios=_resultados_propios(request.user),
        )
        return render(request, "visor/inicio.html", contexto, status=500)

    contexto["capa"] = capa
    contexto["nombre_origen"] = origen.nombre
    contexto["token"] = origen.token
    contexto["origen_principal"] = origen
    if not capa.dibujable:
        contexto["motivo"] = MOTIVOS.get(capa.motivo)
    else:
        contexto["esquinas"] = _esquinas(capa)
        if capa.pixel_size_m:
            contexto["gsd_cm"] = capa.pixel_size_m * 100
        if capa.es_dem:
            contexto["sombreado"] = motor.disponibilidad_sombreado()
            contexto["azimut_deg"] = terreno.AZIMUT_POR_OMISION_DEG
            contexto["altura_deg"] = terreno.ALTURA_POR_OMISION_DEG
            contexto["exageracion_z"] = terreno.EXAGERACION_POR_OMISION
    return None


def _resolver_extra(request, contexto: dict, texto: str):
    """Otra imagen de la lista de capas: se comprueba que se puede leer y que es un GeoTIFF. Su
    ficha la pide el navegador, y si falla, la falla es de **esa capa** y no de todo el mapa.
    Devuelve `(origen, None)` o `(None, respuesta de error)`."""
    try:
        origen = _resolver(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto.update(error=str(fallo), codigo_error=fallo.codigo, propios=[])
        return None, render(request, "visor/inicio.html", contexto, status=403)
    if not _es_imagen(origen.ruta):
        contexto.update(error=_SOLO_TIFF, codigo_error="formato-no-reconocido", propios=[])
        return None, render(request, "visor/inicio.html", contexto, status=422)
    return origen, None


def _descriptores_de_capas(rasters: list[dict], trabajos: list) -> list[dict]:
    """Las capas del mapa, **por omisión de arriba abajo**: lo del vuelo, las imágenes en el orden
    en que se pidieron. `fuente` está en la fila que «quita» la capa entera
    (en un vuelo, la de las fotos: quita las tres)."""
    lista: list[dict] = []
    for job in trabajos:
        nombre = vuelo_mod.nombre_de(job)
        for parte, tipo, rotulo in (
            ("c", capas_mod.VUELO_CONTROL, "Puntos de control"),
            ("f", capas_mod.VUELO_FOTOS, "Fotos"),
            ("t", capas_mod.VUELO_TRAYECTORIA, "Trayectoria"),
        ):
            fila = {
                "id": capas_mod.id_de_vuelo(job.pk, parte),
                "tipo": tipo,
                "nombre": f"{rotulo} del vuelo {nombre}",
                "vuelo": str(job.pk),
                "datos": reverse("visor:vuelo", args=[job.pk]),
            }
            if parte == "f":
                fila["fuente"] = {"param": "vuelo", "valor": str(job.pk)}
            lista.append(fila)
    for i, r in enumerate(rasters):
        lista.append(
            {
                "id": capas_mod.id_de_raster(r["token"]),
                "tipo": capas_mod.RASTER,
                "nombre": r["nombre"],
                "token": r["token"],
                "principal": i == 0,
                "fuente": {"param": r["param"], "valor": r["texto"]},
            }
        )
    return lista


@login_required
@require_GET
def inicio(request):
    """Elegir un archivo y, ya elegido, verlo con las capas que se le sumen."""
    contexto = _contexto_base()
    disponibilidad = motor.disponibilidad()
    contexto["gdal"] = disponibilidad
    contexto["ruta_texto"] = (request.GET.get("ruta") or "").strip()

    pedidos = []
    if contexto["ruta_texto"]:
        pedidos.append(("ruta", contexto["ruta_texto"]))
    for texto in _sin_repetidos(request.GET.getlist("capa")):
        if texto != contexto["ruta_texto"]:
            pedidos.append(("capa", texto))
    omitidas = max(0, len(pedidos) - capas_mod.MAXIMO_DE_RASTERS)
    pedidos = pedidos[: capas_mod.MAXIMO_DE_RASTERS]

    trabajos = _vuelos_pedidos(request)
    omitidas_de_vuelo = max(0, len(trabajos) - capas_mod.MAXIMO_DE_VUELOS)
    trabajos = trabajos[: capas_mod.MAXIMO_DE_VUELOS]

    solo_vuelos = bool(trabajos) and not pedidos
    if not disponibilidad.disponible and not solo_vuelos:
        # Regla 4: apagada, con su motivo y su alternativa. No se esconde ni se sustituye.
        return render(request, "visor/inicio.html", contexto)

    if not pedidos and not trabajos:
        contexto["propios"] = _resultados_propios(request.user)
        contexto["vuelos_propios"] = _vuelos_para_elegir(request.user)
        return render(request, "visor/inicio.html", contexto)

    rasters: list[dict] = []
    if pedidos:
        error = _preparar_principal(request, contexto, pedidos[0][1])
        if error is not None:
            return error
        origen = contexto["origen_principal"]
        rasters.append(
            {
                "param": pedidos[0][0],
                "texto": pedidos[0][1],
                "token": origen.token,
                "nombre": origen.nombre,
            }
        )
        for param, texto in pedidos[1:]:
            otro, error = _resolver_extra(request, contexto, texto)
            if error is not None:
                return error
            if otro.token not in [r["token"] for r in rasters]:
                rasters.append(
                    {"param": param, "texto": texto, "token": otro.token, "nombre": otro.nombre}
                )
    contexto["solo_vuelo"] = solo_vuelos
    if solo_vuelos:
        contexto["nombre_origen"] = ", ".join(vuelo_mod.nombre_de(j) for j in trabajos)

    contexto["sin_gdal"] = None if disponibilidad.disponible else disponibilidad

    descriptores = _descriptores_de_capas(rasters, trabajos)
    ordenadas = capas_mod.ordenar(descriptores, request.GET.get("e"))
    contexto["capas_json"] = json.dumps(ordenadas, ensure_ascii=False)
    contexto["estado_e"] = (request.GET.get("e") or "")[: capas_mod.LARGO_MAXIMO_DEL_ESTADO]
    ficha_principal = contexto.get("capa")
    contexto["hay_mapa"] = bool(
        solo_vuelos or (ficha_principal is not None and ficha_principal.dibujable)
    )
    contexto["hay_vuelo"] = bool(trabajos)
    contexto["omitidas"] = omitidas
    contexto["omitidas_de_vuelo"] = omitidas_de_vuelo
    contexto["maximo_de_rasters"] = capas_mod.MAXIMO_DE_RASTERS
    contexto["maximo_de_vuelos"] = capas_mod.MAXIMO_DE_VUELOS

    # Lo que el formulario de «añadir» conserva: lo que ya se pidió y el estado de las capas.
    ocultos = [(p, t) for p, t in pedidos]
    ocultos += [("vuelo", str(j.pk)) for j in trabajos]
    contexto["ocultos"] = ocultos
    en_uso = {r["token"] for r in rasters}
    contexto["propios"] = [p for p in _resultados_propios(request.user) if p["token"] not in en_uso]
    usados = {str(j.pk) for j in trabajos}
    contexto["vuelos_propios"] = [
        v for v in _vuelos_para_elegir(request.user) if str(v["pk"]) not in usados
    ]
    return render(request, "visor/inicio.html", contexto)


def _vuelos_para_elegir(usuario) -> list[dict]:
    """Los vuelos terminados **de quien mira**, para sumarlos al mapa."""
    return [
        {"pk": j.pk, "nombre": vuelo_mod.nombre_de(j), "fecha": j.finished_at}
        for j in vuelo_mod.propios(usuario)
    ]


@login_required
@require_GET
def vuelo(request, pk):
    """Las partes de un vuelo propio ya en Web Mercator: trayectoria, fotos y puntos de control.

    Del trabajo **de quien pregunta**, terminado: lo demás es 404 con el mismo mensaje (no confirma
    que un identificador ajeno exista). La miniatura y la ficha de cada foto las sirven las vistas
    de «Corregir un vuelo de dron», con sus comprobaciones.
    """
    try:
        job = vuelo_mod.propio(request.user, pk)
    except vuelo_mod.VueloNoEncontrado:
        return _error("vuelo-no-encontrado", MOTIVOS["vuelo-no-encontrado"].mensaje, 404)
    try:
        datos = vuelo_mod.leer_datos(job)
    except vuelo_mod.VueloIlegible:
        return _error("vuelo-ilegible", MOTIVOS["vuelo-ilegible"].mensaje, 404)
    respuesta = JsonResponse(
        vuelo_mod.para_el_mapa(job, datos), json_dumps_params={"ensure_ascii": False}
    )
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


def _esquinas(ficha) -> list[dict]:
    """Las cuatro esquinas de la imagen y su centro, en grados y en el sistema del archivo."""
    nombres = (*huella_mod.ESQUINAS, "centro")
    en_grados = [*ficha.esquinas_4326, ficha.centro_4326]
    en_su_sistema = [*ficha.esquinas, ficha.centro]
    return [
        {"nombre": nombre, "lon": ll[0], "lat": ll[1], "x": xy[0], "y": xy[1]}
        for nombre, ll, xy in zip(nombres, en_grados, en_su_sistema, strict=True)
    ]


@login_required
@require_GET
def capa(request):
    """La ficha de la capa en JSON: lo que el navegador necesita para encuadrar y dibujar."""
    sin_gdal = _con_gdal()
    if sin_gdal is not None:
        return sin_gdal
    origen, error = _origen(request)
    if error is not None:
        return error
    try:
        clave = cache.clave_de(origen.ruta)
    except OSError:
        return _error("origen-no-legible", "Ese archivo ya no está.", 404)
    try:
        ficha = capa_mod.con_cache(origen.ruta, clave)
    except motor.ErrorDeGdal as fallo:
        return _error(fallo.codigo, str(fallo), 422)
    except OSError as fallo:
        return _de_disco(fallo)

    datos = ficha.a_dict()
    datos.pop("wkt", None)  # pesa y el navegador no lo usa
    datos.pop("geotransform", None)
    if ficha.es_dem:
        datos["sombreado"] = _sombreado_a_dict()
    respuesta = JsonResponse(datos, json_dumps_params={"ensure_ascii": False})
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


def _sombreado_a_dict() -> dict:
    """Si el sombreado está o está apagado, con su motivo y su alternativa (regla 4)."""
    d = motor.disponibilidad_sombreado()
    return {
        "disponible": d.disponible,
        "codigo": d.codigo_motivo,
        "mensaje": d.mensaje,
        "sugerencia": d.sugerencia,
    }


def _etiqueta(clave: str, z: int, x: int, y: int, sufijo: str = "") -> str:
    """El `ETag` de una tesela. El terreno añade su sufijo (modo y huella de los parámetros): la
    misma tesela con otro sol es **otra** tesela y no debe devolver un 304."""
    return f'"{clave}{"-" + sufijo if sufijo else ""}-{z}-{x}-{y}"'


def _sin_gdaldem() -> JsonResponse | None:
    """`None` si hay `gdaldem`, o el 503 que dice por qué el sombreado está apagado (regla 4)."""
    disponibilidad = motor.disponibilidad_sombreado()
    if disponibilidad.disponible:
        return None
    return _error(
        disponibilidad.codigo_motivo,
        disponibilidad.mensaje,
        503,
        sugerencia=disponibilidad.sugerencia,
    )


def _modo_o_error(request, ficha) -> tuple[terreno.Modo | None, JsonResponse | None]:
    """El modo de terreno de la petición, o la respuesta que explica por qué no se puede."""
    try:
        modo = terreno.modo_de(request.GET, ficha)
    except terreno.ParametrosNoValidos as fallo:
        return None, _error("parametros-no-validos", str(fallo), 400)
    except terreno.CapaNoEsDem:
        return None, _error("capa-no-es-dem", MOTIVOS["capa-no-es-dem"].mensaje, 409)
    if modo.es_terreno:
        sin = _sin_gdaldem()
        if sin is not None:
            return None, sin
    return modo, None


@login_required
@require_GET
def tesela(request, z: int, x: int, y: int):
    """La tesela `z/x/y` en PNG de 256 × 256, EPSG:3857, cortada del archivo.

    `ETag` y `Cache-Control: private`: la tesela es de quien tiene permiso sobre el archivo y no se
    guarda en cachés compartidas. Con `If-None-Match` que coincida, 304 sin cortar nada.
    """
    if not mercator.es_valida(z, x, y):
        return _error("tesela-fuera-de-la-cuadricula", "Esa tesela no existe.", 404)
    sin_gdal = _con_gdal()
    if sin_gdal is not None:
        return sin_gdal
    origen, error = _origen(request)
    if error is not None:
        return error

    try:
        clave = cache.clave_de(origen.ruta)
    except OSError:
        return _error("origen-no-legible", "Ese archivo ya no está.", 404)
    candidatas = [t.strip() for t in request.headers.get("If-None-Match", "").split(",")]

    def no_modificada(etiqueta: str):
        if etiqueta not in candidatas:
            return None
        respuesta = HttpResponseNotModified()
        respuesta["ETag"] = etiqueta
        respuesta["Cache-Control"] = CACHE_CONTROL
        return respuesta

    # La imagen en grises (lo de siempre) se resuelve sin abrir la ficha; el terreno necesita la
    # ficha para saber **qué** pide (la huella de sus parámetros entra en el `ETag`).
    etiqueta = _etiqueta(clave, z, x, y)
    if request.GET.get("modo", "gris") == "gris":
        igual = no_modificada(etiqueta)
        if igual is not None:
            return igual

    try:
        ficha = capa_mod.con_cache(origen.ruta, clave)
        if not ficha.dibujable:
            mensaje = MOTIVOS[ficha.motivo].mensaje if ficha.motivo in MOTIVOS else ficha.detalle
            return _error(ficha.motivo, mensaje, 409)
        modo, error = _modo_o_error(request, ficha)
        if error is not None:
            return error
        etiqueta = _etiqueta(clave, z, x, y, modo.sufijo)
        igual = no_modificada(etiqueta)
        if igual is not None:
            return igual
        if z > ficha.zoom_maximo + NIVELES_DE_SOBRE_ACERCAMIENTO:
            return _error("tesela-fuera-de-la-cuadricula", "Más cerca no hay más detalle.", 404)
        if modo.es_terreno:
            contenido = terreno.tesela(origen.ruta, ficha, clave, modo, z, x, y)
        else:
            contenido = teselas.tesela(origen.ruta, ficha, clave, z, x, y)
    except motor.ErrorDeGdal as fallo:
        estado = 504 if fallo.codigo == "tardo-demasiado" else 502
        return _error(fallo.codigo, str(fallo), estado)
    except OSError as fallo:
        return _de_disco(fallo)

    respuesta = HttpResponse(contenido, content_type="image/png")
    respuesta["ETag"] = etiqueta
    respuesta["Cache-Control"] = CACHE_CONTROL
    return respuesta


def _numero(texto: str | None) -> float | None:
    try:
        valor = float((texto or "").replace(",", "."))
    except ValueError:
        return None
    return valor if math.isfinite(valor) else None


@login_required
@require_GET
def punto(request):
    """Dónde cae un punto del mapa en el archivo, y con `valor=1` qué hay en ese píxel."""
    sin_gdal = _con_gdal()
    if sin_gdal is not None:
        return sin_gdal
    origen, error = _origen(request)
    if error is not None:
        return error

    lon, lat = _numero(request.GET.get("lon")), _numero(request.GET.get("lat"))
    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return _error("coordenadas-no-validas", "Longitud o latitud fuera de rango.", 400)

    try:
        clave = cache.clave_de(origen.ruta)
    except OSError:
        return _error("origen-no-legible", "Ese archivo ya no está.", 404)
    try:
        ficha = capa_mod.con_cache(origen.ruta, clave)
        if not ficha.dibujable:
            return _error(ficha.motivo, ficha.detalle, 409)
        encontrado = punto_mod.localizar(ficha, lon, lat)
        if request.GET.get("valor") == "1":
            encontrado = punto_mod.con_valores(origen.ruta, ficha, encontrado)
    except motor.ErrorDeGdal as fallo:
        return _error(fallo.codigo, str(fallo), 502)
    except OSError as fallo:
        return _de_disco(fallo)

    def cifra(valor: float) -> float | None:
        return round(valor, 4) if math.isfinite(valor) else None

    respuesta = JsonResponse(
        {
            "lon": lon,
            "lat": lat,
            "sistema": ficha.sistema,
            "epsg": ficha.epsg,
            "unidad": ficha.unidad,
            "x": cifra(encontrado.x),
            "y": cifra(encontrado.y),
            "columna": cifra(encontrado.columna),
            "fila": cifra(encontrado.fila),
            "dentro": encontrado.dentro,
            "valores": list(encontrado.valores),
        },
        json_dumps_params={"ensure_ascii": False},
    )
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@login_required
@require_GET
def perfil(request):
    """El perfil de un DEM entre dos puntos: JSON, o `formato=csv` para descargarlo.

    Los dos puntos van en EPSG:4326 (`lon1`, `lat1`, `lon2`, `lat2`) y `n` es el número de
    muestras.
    Sin valores por omisión para los puntos. Lo que cae fuera del modelo o en «sin dato» sale como
    hueco (`null` o celda vacía), nunca como cero.
    """
    sin_gdal = _con_gdal()
    if sin_gdal is not None:
        return sin_gdal
    origen, error = _origen(request)
    if error is not None:
        return error

    try:
        extremos = terreno.extremos_de(request.GET)
        n = terreno.muestras_de_de(request.GET)
    except terreno.ParametrosNoValidos as fallo:
        return _error("parametros-no-validos", str(fallo), 400)
    formato = (request.GET.get("formato") or "json").strip().lower()
    if formato not in ("json", "csv"):
        return _error("parametros-no-validos", "El formato del perfil es json o csv.", 400)

    try:
        clave = cache.clave_de(origen.ruta)
    except OSError:
        return _error("origen-no-legible", "Ese archivo ya no está.", 404)
    try:
        ficha = capa_mod.con_cache(origen.ruta, clave)
        if not ficha.dibujable:
            return _error(ficha.motivo, ficha.detalle, 409)
        resultado = terreno.perfil(origen.ruta, ficha, extremos, n)
    except terreno.CapaNoEsDem:
        return _error("capa-no-es-dem", MOTIVOS["capa-no-es-dem"].mensaje, 409)
    except terreno.ParametrosNoValidos as fallo:
        return _error("parametros-no-validos", str(fallo), 400)
    except motor.ErrorDeGdal as fallo:
        return _error(fallo.codigo, str(fallo), 502)
    except OSError as fallo:
        return _de_disco(fallo)

    if formato == "csv":
        respuesta = HttpResponse(
            terreno.csv_del_perfil(resultado), content_type="text/csv; charset=utf-8"
        )
        nombre = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(origen.nombre).stem).strip("-") or "modelo"
        respuesta["Content-Disposition"] = content_disposition_header(
            True, f"perfil-{nombre[:60]}.csv"
        )
    else:
        respuesta = JsonResponse(
            terreno.a_dict(resultado), json_dumps_params={"ensure_ascii": False}
        )
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
