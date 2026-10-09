"""Lo que se exige **antes** de convertir: memoria, crudo entero, sistema de referencia y metros.

Salió de `runner.py` en F11.8 sin cambiar una línea. Aquí se juega la regla tres (el CRS no se
adivina) y el «no empieces lo que la máquina no puede acabar»: cada exigencia se detiene con su
motivo **antes** de gastar minutos de conversión, y el formulario no las sustituye porque la
API lo evade.
"""

from __future__ import annotations

from pathlib import Path

from .fallos import TrabajoFallido
from .models import INSPECCION, ConversionJob, JobEvent


def _exigir_memoria(job: ConversionJob, inspeccion) -> None:
    """Que la maquina pueda con esto. **Antes** de empezar, no a los veinte minutos.

    Es la regla que faltaba para las nubes de puntos grandes. **PDAL carga los puntos en
    memoria** y `GDAL_CACHEMAX` no le afecta, asi que el techo crece con el numero de puntos:
    la regla medida son 105 MB por millon. Una nube de mil millones de puntos pide unos
    100 GB, y eso no es «una VM mas grande», es ninguna VM.

    Y lo que pasa sin esta comprobacion no es un error: el sistema mata el proceso por falta
    de memoria, y con suerte se lleva solo la conversion. En un servidor compartido se lleva
    lo que el nucleo decida, que suele ser el servidor web o la base.

    No se comprueba en el formulario **y ya esta**: el formulario es evadible desde la API,
    igual que con el CRS.
    """
    from .estimacion import Estimacion, _memoria_mb, memoria_total_mb

    estimacion = Estimacion(
        bytes_salida=0,
        segundos=0.0,
        memoria_mb=_memoria_mb(inspeccion),
        libre_bytes=0,
        memoria_total_mb=memoria_total_mb(),
    )
    if estimacion.cabe_en_memoria:
        return

    raise TrabajoFallido("memoria-insuficiente", estimacion.motivo_de_memoria)


def _exigir_crudo_entero(job: ConversionJob, inspeccion) -> None:
    """Un crudo de Trimble cortado no se convierte: se avisa y se pide copiarlo otra vez.

    **El convertidor de Trimble no se queja.** Con un T02 partido por la mitad sale con código
    0, dice «Success» y entrega un RINEX perfectamente válido que dura la mitad, sin una
    palabra. Lo malo no es el error sino que no lo haya: quien lo reciba creerá que la sesión
    duró lo que dura el archivo. Mirando la salida no hay forma de verlo; el dato está en el
    crudo, y se comprueba aquí, antes de gastar minutos de conversión.
    """
    if inspeccion.trimble is None:
        return

    from apps.formats import trimble

    integridad = trimble.comprobar_integridad(Path(inspeccion.ruta))
    if integridad.completo:
        return
    if integridad.bloques == 0:
        raise TrabajoFallido("crudo-incompleto", "El archivo no trae ningún bloque de datos.")
    raise TrabajoFallido(
        "crudo-incompleto",
        f"El archivo está cortado: {integridad.cortados} de sus {integridad.bloques} bloques "
        "no llegan a su final.",
    )


def _exigir_crs(job: ConversionJob, inspeccion) -> None:
    """La regla heredada: si falta el CRS, se para y se pregunta. No se adivina.

    Con la distincion que la hace usable: **solo se detiene si hace falta de verdad** --
    cuando el trabajo reproyecta o cuando el destino exige el CRS incrustado. Convertir un
    raster sin georreferencia a otro sin georreferencia es legitimo, y negarlo convertiria
    la herramienta en un estorbo.
    """
    if inspeccion.crs.conocido:
        return

    from apps.formats import catalogo
    from apps.formats import crs as crs_mod

    # **Una observación GNSS no tiene sistema de referencia que echar en falta.** Son
    # pseudodistancias y fases a satélites, no coordenadas; la posición aproximada de la
    # cabecera de un RINEX es ECEF y sirve de ayuda al posproceso, no de CRS. El aviso de
    # abajo —«la salida tampoco lo tendrá»— sería engañoso, así que ni se dice.
    if inspeccion.familia == catalogo.GNSS:
        return

    # **Lo declarado a mano cuenta, y hay formatos donde es la única vía.**
    #
    # Una libreta de puntos no lleva sistema de referencia dentro **nunca**: es texto con
    # tres números por línea. Si lo único que vale fuera el CRS incrustado, esta rama
    # rechazaría todas las libretas del mundo y la mitad de la fase vectorial no existiría.
    #
    # Se acepta con dos condiciones, y las dos importan: que lo haya declarado una persona
    # -- `validar_declarado()` lo marca así y comprueba el código contra pyproj -- y que
    # quede escrito en la bitácora. Esa anotación es la traza del día en que alguien puso la
    # obra en otro país, y sin ella «lo declaró alguien» no se puede sostener.
    if job.source_crs_code and job.source_crs_origin == crs_mod.DECLARADO:
        job.registrar(
            f"El archivo no declara sistema de referencia. Se usa el declarado a mano: "
            f"{job.source_crs_authority or 'EPSG'}:{job.source_crs_code}.",
            nivel=JobEvent.AVISO,
            etapa=INSPECCION,
        )
        return

    reproyecta = bool(job.target_crs_code)

    # **Coordenadas locales, declaradas por una persona.** Una nube de escáner sin GNSS no
    # tiene EPSG que poner: está en el sistema de la estación, con el origen en 0. Para ella
    # la regla de «sin CRS no se convierte» no protege nada —no hay dato que se pierda, porque
    # no había dato— y obligaba a inventarse un EPSG, que es lo único peor que no tenerlo.
    #
    # Lo que sí se sigue negando es **reproyectar**: pasar de «local» a UTM no es una
    # conversión, es una georreferenciación, y sin puntos de control no hay de dónde partir.
    if job.source_crs_origin == crs_mod.LOCAL:
        if reproyecta:
            raise TrabajoFallido(
                "crs-ausente",
                "Son coordenadas locales: no se pueden reproyectar, porque no hay de dónde "
                "partir. Para llevarlas a un sistema hace falta georreferenciarlas con puntos "
                "de control, y eso no lo hace una conversión.",
            )
        job.registrar(
            "Coordenadas locales declaradas a mano: se convierte sin sistema de referencia, "
            "y la salida tampoco lo tendrá.",
            nivel=JobEvent.AVISO,
            etapa=INSPECCION,
        )
        return

    destino = catalogo.FORMATOS.get(job.target_format_code)
    origen = catalogo.FORMATOS.get(job.source_format_code)
    lo_exige = bool(destino and destino.lleva_crs_incrustado and destino.familia == catalogo.RASTER)

    # **En nubes de puntos no hay excepción.** En ráster se admite convertir sin
    # georreferencia -- un TIFF suelto a un COG suelto es legítimo y negarlo convertiría la
    # herramienta en un estorbo. En nubes no: una nube sin CRS no se puede cruzar con nada,
    # y el dato se pierde para siempre si nadie lo apunta al entregarla. Es la regla escrita
    # en `AeroBim/docs/NUBES_DE_PUNTOS.md`.
    es_nube = bool(
        (destino and destino.familia == catalogo.NUBE)
        or (origen and origen.familia == catalogo.NUBE)
    )

    # **En una libreta de puntos tampoco hay excepción, y por un motivo distinto.**
    #
    # Un ráster sin georreferencia sigue siendo una imagen: tiene píxeles, se ve, y pasarla a
    # otro formato sin georreferencia no pierde nada. Una libreta de puntos **no es nada más
    # que coordenadas**. Sin sistema de referencia, esos tres números no dicen dónde está el
    # punto, y la salida es una capa que afirma estar en algún sitio sin estarlo. Además, a
    # KML no se podría ni llegar: exige EPSG:4326 y reproyectar necesita saber de dónde.
    es_libreta = bool(origen and origen.codigo == "puntos")

    if reproyecta or lo_exige or es_nube or es_libreta:
        if es_nube:
            detalle = (
                "Una nube sin sistema de referencia no se puede cruzar con nada, y el dato "
                "se pierde para siempre si nadie lo apunta al entregarla."
            )
        elif es_libreta:
            detalle = (
                "Una libreta de puntos no es más que coordenadas: sin declarar el EPSG, "
                "esos números no dicen dónde está nada. Míralo en el .prj del "
                "levantamiento o pregúntaselo a quien lo midió."
            )
        else:
            detalle = "Declara el EPSG: adivinarlo es peor que no tenerlo."
        raise TrabajoFallido(
            "crs-ausente",
            f"El archivo no declara sistema de referencia y esta conversión lo necesita. {detalle}",
        )

    job.registrar(
        "El archivo no declara sistema de referencia. Se convierte igual porque el destino "
        "tampoco lo exige, pero la salida tampoco lo tendra.",
        nivel=JobEvent.AVISO,
        etapa=INSPECCION,
    )


def _exigir_metros(job: ConversionJob, inspeccion) -> None:
    """Un destino que necesita metros no se llena de grados en silencio.

    Es el mismo fallo que el del KML, en la dirección contraria y con la misma cara de
    éxito. Un KMZ viene siempre en EPSG:4326; convertirlo a DXF sin reproyectar escribe
    coordenadas como `-69,046` y `-24,244`, así que el dibujo entero mide **dos milésimas
    de unidad**. Se comprobó: abre en Civil 3D, no se ve nada, y el recibo dice «hecho».

    Se para **antes** de convertir y no al verificar porque un DXF no guarda sistema de
    referencia: mirando la salida no hay forma de saber en qué unidades está. El dato solo
    existe aquí, en el origen.
    """
    from apps.formats import catalogo

    destino = catalogo.FORMATOS.get(job.target_format_code)
    if destino is None or not destino.exige_metros:
        return

    origen_crs = inspeccion.crs if inspeccion.crs.conocido else _crs_declarado_del_trabajo(job)
    if not origen_crs.es_geografico:
        return

    # El destino puede venir del trabajo o de la opción del motor. Se miran las dos porque
    # el formulario experto llega por `options` y la API por `target_crs_code`.
    if job.target_crs_code or (job.options or {}).get("crs_destino"):
        return

    formato = destino.nombre
    raise TrabajoFallido(
        "crs-en-grados",
        f"El origen está en {origen_crs}, que son grados, y un {formato} guarda números sin "
        "sistema de referencia: el dibujo saldría midiendo milésimas de unidad. Declara a "
        "qué sistema proyectado hay que llevarlo — para esta zona suele ser un UTM en metros.",
    )


def _crs_declarado_del_trabajo(job: ConversionJob):
    from apps.formats import crs as crs_mod

    if not job.source_crs_code:
        return crs_mod.SIN_CRS
    return crs_mod.Crs(
        autoridad=job.source_crs_authority or "EPSG",
        codigo=job.source_crs_code,
        origen=job.source_crs_origin or crs_mod.DECLARADO,
    )
