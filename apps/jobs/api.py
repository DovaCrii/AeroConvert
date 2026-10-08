"""La API de conversión (F16.4): encolar, consultar y descargar, con las reglas de la pantalla.

    POST /api/v1/trabajos/             {"ruta", "formato" | "perfil", "opciones", "crs_declarado"}
    GET  /api/v1/trabajos/                 los últimos 50 de quien pregunta
    GET  /api/v1/trabajos/<id>/            estado, avance, motivo y verificación
    GET  /api/v1/trabajos/<id>/descarga/   la salida, si está hecha

**Las mismas reglas que la pantalla de convertir, no otras:** la ruta pasa por `entrada.resolver`
(raíces permitidas o una subida propia), el formato lo detecta el inspector, las opciones las valida
el motor (`formulario.leer`) y el CRS **no se adivina**: si el archivo no lo trae, se acepta el
declarado (validado contra PROJ) o el trabajo se encola sin él y el corredor lo detiene con
`crs-ausente` si hace falta. Lo de otra persona es un 404, que no confirma que exista.
"""

from __future__ import annotations

from pathlib import Path

from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api_auth import PuedeUsarLaApi

from .models import HECHO, ConversionJob

MAXIMO_EN_LA_LISTA = 50


class _QueryDictDeLaApi(dict):
    """`formulario.leer` pide un `.get()` y un `in`: un dict los tiene."""


def _describir(trabajo: ConversionJob, request) -> dict:
    datos = {
        "id": str(trabajo.pk),
        "estado": trabajo.status,
        "origen": trabajo.source_name,
        "formato_origen": trabajo.source_format_code,
        "formato_destino": trabajo.target_format_code,
        "perfil": trabajo.target_profile_id,
        "crs_origen": (
            f"{trabajo.source_crs_authority}:{trabajo.source_crs_code}"
            if trabajo.source_crs_code
            else ""
        ),
        "avance_por_ciento": trabajo.progress_percent,
        "avance_que": trabajo.progress_label,
        "motivo": trabajo.reason_code,
        "motivo_detalle": trabajo.reason_detail,
        "motor": trabajo.engine_id,
        "version_del_motor": trabajo.engine_version,
        "verificacion": trabajo.verification or {},
        "encolado": trabajo.queued_at.isoformat() if trabajo.queued_at else None,
        "terminado": trabajo.finished_at.isoformat() if trabajo.finished_at else None,
        "ficha": request.build_absolute_uri(reverse("jobs:ficha", args=[trabajo.pk])),
    }
    if trabajo.status == HECHO and trabajo.output_path:
        datos["descarga"] = request.build_absolute_uri(
            reverse("api-trabajo-descarga", args=[trabajo.pk])
        )
    return datos


def _error(mensaje: str, codigo: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": mensaje, "codigo": codigo}, status=http)


class Trabajos(APIView):
    permission_classes = [PuedeUsarLaApi]

    def get(self, request):
        trabajos = ConversionJob.objects.filter(owner=request.user)[:MAXIMO_EN_LA_LISTA]
        return Response({"trabajos": [_describir(t, request) for t in trabajos]})

    def post(self, request):
        from apps.core import entrada as entrada_mod
        from apps.core import modo as modo_mod
        from apps.dashboard.views import _ruta_de_salida
        from apps.engines import formulario as formulario_mod
        from apps.engines import registry
        from apps.engines.base import ParDeFormatos
        from apps.formats import catalogo, deteccion
        from apps.formats import crs as crs_mod
        from apps.targets import perfiles as perfiles_mod

        datos = request.data if isinstance(request.data, dict) else {}
        crudo = datos.get("ruta")
        if crudo is not None and not isinstance(crudo, str):
            return _error("«ruta» tiene que ser una cadena.", "origen-no-legible")
        ruta = (crudo or "").strip()
        if not ruta:
            return _error("Falta «ruta»: el archivo de origen.", "origen-no-legible")
        try:
            origen = entrada_mod.resolver(ruta, usuario=request.user)
            inspeccion = deteccion.inspeccionar(origen.ruta)
        except modo_mod.RutaNoPermitida as fallo:
            return _error(str(fallo), getattr(fallo, "codigo", "") or "ruta-no-permitida")
        except deteccion.OrigenIlegible as fallo:
            return _error(str(fallo), getattr(fallo, "codigo", "") or "origen-no-legible")

        # --- El destino: un perfil o un formato con sus opciones -----------------------------
        perfil_id = str(datos.get("perfil") or "").strip()
        if perfil_id:
            perfil = perfiles_mod.PERFILES.get(perfil_id)
            if perfil is None:
                return _error(f"No hay ningún perfil «{perfil_id}».", "par-no-soportado")
            formato = perfil.destino_para(inspeccion.familia)
            opciones = dict(perfil.opciones)
        else:
            formato = str(datos.get("formato") or "").strip()
            if formato not in catalogo.FORMATOS:
                return _error("Falta «formato», o no es uno del catálogo.", "par-no-soportado")
            opciones = None
        par = ParDeFormatos(inspeccion.codigo_formato, formato)
        motor = registry.motor_para(par)
        if motor is None:
            celda = registry.celda(par)
            return _error(
                celda.mensaje or "Ningún motor sabe hacer esa conversión.",
                celda.codigo_motivo or "sin-motor",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if opciones is None:
            crudas = datos.get("opciones") or {}
            if not isinstance(crudas, dict) or any(
                not isinstance(v, (str, int, float, bool)) for v in crudas.values()
            ):
                return _error(
                    "«opciones» tiene que ser un objeto de valores simples.", "opcion-invalida"
                )
            crudas = {
                k: ("on" if v is True else str(v)) for k, v in crudas.items() if v is not False
            }
            try:
                opciones = formulario_mod.leer(motor, par, _QueryDictDeLaApi(crudas))
            except formulario_mod.OpcionInvalida as fallo:
                return _error(fallo.mensaje, "opcion-invalida")

        # --- El CRS: el del archivo, o el declarado. Nunca uno supuesto ------------------------
        crs = inspeccion.crs
        declarado = str(datos.get("crs_declarado") or "").strip()
        if datos.get("crs_local") is True:
            # «Son coordenadas locales» es una respuesta, no un hueco: las mismas condiciones que
            # en la pantalla (solo nubes, nunca junto a un EPSG, nunca encima de uno incrustado).
            if declarado or crs.conocido:
                return _error(
                    "Coordenadas locales o un EPSG, no las dos; y nunca encima del que trae.",
                    "crs-invalido",
                )
            if inspeccion.familia != catalogo.NUBE:
                return _error("Las coordenadas locales solo se admiten en nubes.", "crs-invalido")
            crs = crs_mod.LOCAL_DECLARADO
        elif declarado and crs.conocido:
            return _error(
                "El archivo ya trae su sistema de referencia: no se acepta otro encima.",
                "crs-invalido",
            )
        if declarado:
            try:
                crs = crs_mod.validar_declarado(declarado)
            except crs_mod.CrsInvalido as fallo:
                return _error(str(fallo), "crs-invalido")

        ruta_origen = Path(inspeccion.ruta)
        trabajo = ConversionJob.objects.create(
            owner=request.user,
            source_path=str(ruta_origen),
            source_name=origen.nombre,
            source_size_bytes=inspeccion.bytes_totales,
            source_format_code=inspeccion.codigo_formato,
            source_format_confidence=inspeccion.confianza,
            source_crs_authority=crs.autoridad,
            source_crs_code=crs.codigo,
            source_crs_origin=crs.origen,
            target_format_code=formato,
            target_profile_id=perfil_id,
            options=opciones,
            output_path=str(_ruta_de_salida(ruta_origen, formato, perfil_id)),
        )
        if crs is crs_mod.LOCAL_DECLARADO:
            trabajo.registrar(
                f"{request.user.get_username()} declaró por la API que son coordenadas locales, "
                "sin sistema de referencia."
            )
        if declarado:
            trabajo.registrar(
                f"{request.user.get_username()} declaró por la API el sistema de referencia "
                f"{crs.autoridad}:{crs.codigo}. El archivo no lo traía dentro."
            )
        trabajo.registrar(f"Encolado por la API hacia {formato}.")
        return Response(_describir(trabajo, request), status=status.HTTP_201_CREATED)


class Trabajo(APIView):
    permission_classes = [PuedeUsarLaApi]

    def get(self, request, pk):
        trabajo = get_object_or_404(ConversionJob, pk=pk, owner=request.user)
        return Response(_describir(trabajo, request))


class Descarga(APIView):
    """La salida, con **las mismas reglas que la descarga de la pantalla** (`jobs.views.descargar`):
    410 si se fue (barrida por la retención, desaparecida o reemplazada después de verificarla), y
    la retención efímera se aplica igual: entregada entera, se consume.
    """

    permission_classes = [PuedeUsarLaApi]

    def get(self, request, pk):
        from .views import RespuestaQueConsume

        trabajo = get_object_or_404(ConversionJob, pk=pk, owner=request.user)
        if trabajo.status != HECHO:
            return _error("El trabajo todavía no está hecho.", "sin-salida", 409)
        if not trabajo.output_path:
            return _error("La salida ya no está: la retención se la llevó.", "sin-salida", 410)
        ruta = Path(trabajo.output_path)
        if not ruta.is_file():
            return _error("La salida ya no está en su sitio.", "sin-salida", 410)
        if trabajo.output_size_bytes and ruta.stat().st_size != trabajo.output_size_bytes:
            return _error(
                "La salida cambió desde que se verificó: no se entrega.", "salida-invalida", 410
            )
        respuesta = RespuestaQueConsume(
            open(ruta, "rb"),  # noqa: SIM115 - FileResponse lo cierra
            as_attachment=True,
            filename=ruta.name,
            job=trabajo,
        )
        respuesta._completada = True
        return respuesta
