"""Convertir: soltar un archivo, ver qué tiene dentro y qué abre dónde.

La pantalla se llamaba «la mesa». Era una metáfora que a quien la escribió le parecía
evidente y que a nadie más le decía nada — «Mesa» en un menú no anuncia lo que hay detrás.
Ahora se llama por lo que hace, y el nombre interno va con el visible: tenerlos distintos
obliga a traducir mentalmente cada vez que se lee un error.
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import entrada as entrada_mod
from apps.core import manejador as manejador_mod
from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod
from apps.dashboard import acciones as acciones_mod
from apps.dashboard import vista_previa as vista_previa_mod
from apps.engines import formulario as formulario_mod
from apps.engines import registry
from apps.engines.base import ParDeFormatos
from apps.formats import catalogo, deteccion
from apps.formats import crs as crs_mod
from apps.jobs import estimacion as estimacion_mod
from apps.jobs.models import ConversionJob
from apps.presets.models import ConversionPreset
from apps.targets import perfiles as perfiles_mod


@dataclass(frozen=True)
class DestinoOfrecido:
    """Un perfil y si esta máquina puede cumplirlo ahora mismo.

    Se calcula contra la matriz de capacidades, no contra una lista fija: si falta la clave
    de ECW, el botón aparece **apagado con su motivo escrito y su alternativa**, no
    desaparece. Ocultarlo haría parecer que ese destino nunca existió.
    """

    perfil: perfiles_mod.PerfilDeDestino
    se_puede: bool
    nombre_destino: str = ""
    motivo: str = ""
    alternativas: tuple[str, ...] = ()
    estimacion: estimacion_mod.Estimacion | None = None


def _destinos_para(inspeccion) -> tuple[DestinoOfrecido, ...]:
    ofrecidos = []
    for perfil in perfiles_mod.PERFILES.values():
        # Los que no tienen nada que decir de esta familia no salen. Un PDF no tiene
        # «programa de destino»: seis botones apagados diciendo que no se puede convertir a
        # GeoTIFF son una respuesta correcta a una pregunta que nadie hizo.
        if not perfil.aplica_a(inspeccion.familia):
            continue

        # Por familia: un perfil es «dónde tiene que abrir», no «a qué formato». Civil 3D
        # quiere un GeoTIFF si le llega una ortofoto y un LandXML si le llega una libreta.
        destino = perfil.destino_para(inspeccion.familia)
        formato = catalogo.FORMATOS.get(destino)
        celda = registry.celda(ParDeFormatos(inspeccion.codigo_formato, destino))

        estimada = None
        if celda.se_puede:
            estimada = estimacion_mod.estimar(
                inspeccion=inspeccion,
                formato_destino=destino,
                opciones=perfil.opciones,
            )

        ofrecidos.append(
            DestinoOfrecido(
                perfil=perfil,
                se_puede=celda.se_puede,
                nombre_destino=formato.nombre if formato else destino,
                motivo=celda.mensaje,
                alternativas=tuple(
                    catalogo.FORMATOS[a].nombre
                    for a in celda.alternativas
                    if a in catalogo.FORMATOS
                ),
                estimacion=estimada,
            )
        )
    return tuple(ofrecidos)


def _hay_algun_destino(inspeccion, escribibles) -> bool:
    """`True` si algún motor sabe llevar este archivo a algún sitio.

    Se pregunta a la matriz de capacidades, que es la única que lo sabe: el catálogo dice
    qué formatos existen, no cuáles se pueden alcanzar desde aquí y con lo que hay
    instalado.
    """
    return any(
        registry.celda(ParDeFormatos(inspeccion.codigo_formato, formato.codigo)).se_puede
        for formato in escribibles
    )


def _formulario_experto(inspeccion, formato: str, valores: dict | None = None):
    """Los campos que el motor del par declara, o `None` si no hay motor.

    Se construye desde `opciones()` y no a mano: así el formulario no puede ofrecer un
    ajuste que el motor vaya a ignorar, que es exactamente el fallo silencioso que ya tuvo
    este proyecto con los perfiles de destino.
    """
    par = ParDeFormatos(inspeccion.codigo_formato, formato)
    motor = registry.motor_para(par)
    if motor is None:
        return None, None
    return motor, formulario_mod.construir(motor, par, valores)


@login_required
def convertir(request):
    """Soltar un archivo y ver qué se puede hacer con él.

    Acepta `?destino=<id de perfil>` para llegar con la elección ya hecha, que es lo que
    manda la tarjeta «Llevarlo a QGIS» del catálogo. **Un destino que no existe se ignora en
    silencio**: es una cadena de consulta, la escribe cualquiera, y la pantalla sin destino
    preferido funciona igual — no hay nada que avisar.
    """
    preferido = (request.GET.get("destino") or "").strip()
    perfil = perfiles_mod.PERFILES.get(preferido)

    # Y el otro camino: `?formato=jp2`, que es donde deja el buscador a quien escribió
    # «tif a jp2». No es un perfil —no hay programa de destino— es el formato a secas.
    pedido = (request.GET.get("formato") or "").strip()
    formato = catalogo.FORMATOS.get(pedido) if pedido else None

    return render(
        request,
        "dashboard/convertir.html",
        {
            "seccion": "convertir",
            "etiqueta_seccion": "Convertir",
            "destino_preferido": perfil.id if perfil else "",
            "nombre_preferido": perfil.nombre if perfil else "",
            "formato_preferido": pedido if formato else "",
            "nombre_formato": str(formato.nombre) if formato else "",
            "titulo_pagina": "Qué tiene dentro, y dónde va a abrir",
            # Corto, y **diciendo algo que no dice ningún otro sitio de la pantalla**.
            #
            # Antes explicaba el funcionamiento con casi las mismas palabras que los tres
            # pasos de debajo: leer dos veces la misma explicación no aclara, cansa. Los
            # pasos dicen cómo funciona; el título dice qué hace; esto dice **cuándo
            # echar mano de ello**, que es la pregunta que trae aquí a alguien la primera
            # vez. Y es literalmente el caso que originó la aplicación.
            "proposito": "Para cuando un archivo abre en un equipo y en otro no.",
            "recientes": ConversionJob.objects.filter(owner=request.user)[:5],
        },
    )


@login_required
def que_puedo_hacer(request):
    """Todo lo que sabe hacer la aplicación, por categorías y con buscador.

    La puerta que faltaba. Las capacidades vivían en tres pantallas que no se hablan, y quien
    llega con un archivo y una intención tenía que saber de antemano en cuál mirar.

    **El filtro se hace en el servidor y no en el navegador.** Son unas veinte acciones: el
    viaje de ida y vuelta es más barato que el JavaScript que haría falta para filtrar bien
    —acentos, sinónimos, varias palabras— y además funciona igual sin JavaScript.
    """
    busqueda = (request.GET.get("q") or "").strip()
    grupos = acciones_mod.por_categoria(busqueda)
    # **La respuesta directa, cuando lo escrito nombra dos formatos.** «tif a jp2» no
    # encontraba nada: el catálogo está ordenado por intención y quien ya sabe los formatos no
    # pregunta por intención. Ver `conversion_pedida`.
    conversion = acciones_mod.conversion_pedida(busqueda)

    contexto = {
        "grupos": grupos,
        "q": busqueda,
        "conversion": conversion,
        # **La explicación solo mientras hace falta**, y sin guardar nada.
        #
        # Una pantalla de «cómo funciona» separada se lee una vez y después es un clic de más
        # todos los días. Una tira fija encima del catálogo es peor: ocupa el sitio de lo que
        # se viene a hacer. Lo que hace falta es que esté **la primera vez** y desaparezca
        # sola.
        #
        # El disparador es no haber convertido nada todavía, que es el dato que ya existe y
        # que además es la definición exacta de «primera vez». Ni cookie, ni ajuste, ni un
        # botón de «no volver a mostrar» que alguien pulsa sin querer y no sabe deshacer.
        "primera_vez": not busqueda
        and not ConversionJob.objects.filter(owner=request.user).exists(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "dashboard/_acciones.html", contexto)

    return render(
        request,
        "dashboard/que_puedo_hacer.html",
        {
            **contexto,
            "seccion": "acciones",
            # **Ni «Todo» ni «TODO».** El CSS pone este rótulo en mayúsculas, y «TODO» a
            # secas se lee como el marcador de pendiente que dejamos los programadores en el
            # código — justo en una aplicación cuyo público sabe lo que es.
            "etiqueta_seccion": "Todas las herramientas",
            "titulo_pagina": "¿Qué necesitas hacer?",
            "proposito": (
                "Escribe lo que quieres conseguir —«juntar planos», «quitar la contraseña», "
                "«pasar a Excel»— y sale con qué hacerlo."
            ),
        },
    )


@login_required
def inspeccionar(request):
    """Inspecciona la ruta enviada y devuelve la ficha con sus veredictos.

    Responde un fragmento, no una página: htmx lo inserta bajo la zona de soltar. Y es una
    petición aparte de la conversión a propósito — inspeccionar es barato y no cambia nada,
    así que puede pasar mientras la persona todavía decide.
    """
    return _ficha(
        request,
        (request.GET.get("ruta") or "").strip(),
        (request.GET.get("formato") or "").strip(),
    )


def _destino_preferido(request) -> str:
    """El perfil que venía elegido del catálogo, si sigue existiendo.

    Se comprueba contra `PERFILES` y no se devuelve tal cual: llega de una cadena de consulta
    o de un campo escondido, o sea de fuera, y acaba comparándose en la plantilla para marcar
    un botón. Un identificador inventado no marca nada, que es lo correcto.
    """
    crudo = (request.POST.get("destino") or request.GET.get("destino") or "").strip()
    return crudo if crudo in perfiles_mod.PERFILES else ""


def _ficha(request, token_pedido: str, formato_pedido: str = ""):
    """El fragmento de la ficha, ya con el origen resuelto.

    Vive aparte de `inspeccionar` porque `subir` necesita lo mismo y no tiene el token en la
    cadena de consulta: lo acaba de crear.
    """
    if not token_pedido:
        return render(request, "dashboard/_ficha.html", {})

    inspeccion, origen, error = _inspeccionar(token_pedido, usuario=request.user)
    if error:
        return render(request, "dashboard/_ficha.html", error)

    escribibles = catalogo.escribibles(inspeccion.familia or catalogo.RASTER)
    experto = formato_pedido
    if experto not in {f.codigo for f in escribibles}:
        experto = escribibles[0].codigo if escribibles else ""

    _, campos = _formulario_experto(inspeccion, experto) if experto else (None, None)

    return render(
        request,
        "dashboard/_ficha.html",
        {
            "i": inspeccion,
            # **Lo que viaja al formulario, y nunca `i.ruta`.** Para una subida es su
            # identificador; para una ruta, la ruta. Es la única línea de esta vista donde
            # equivocarse sería una fuga.
            "token": origen.token,
            "nombre": origen.nombre,
            # El dibujo de la libreta, cuando lo es. Es lo que convierte «elige el orden de
            # columnas» en una decisión que se toma mirando.
            "dibujo": (
                vista_previa_mod.dibujo_de_puntos(inspeccion.puntos) if inspeccion.puntos else None
            ),
            "veredictos": perfiles_mod.veredictos(inspeccion),
            "perfiles": _destinos_para(inspeccion),
            # **La elección que se hizo en el catálogo, traída hasta aquí.**
            #
            # Se lee del propio pedido —y no de un parámetro— porque los dos caminos que
            # acaban en esta ficha, subir y explorar, mandan formularios distintos: uno por
            # POST y otro por GET. Lo que comparten es llevar el campo escondido.
            "destino_preferido": _destino_preferido(request),
            "escribibles": escribibles,
            "formato_experto": experto,
            "campos": campos,
            # **Si no hay a dónde convertir, no se enseña el formulario.**
            #
            # Pasa con un PDF y con un IFC: la familia existe en el catálogo pero ningún
            # motor declara todavía un par que salga de ahí. Pintar el selector y el botón
            # de «convertir con estos ajustes» ofrece un camino que termina en «ningún
            # motor sabe hacer esa conversión» — un callejón sin salida con forma de
            # botón, que es peor que no ofrecer nada.
            "hay_conversion": _hay_algun_destino(inspeccion, escribibles),
            # **Solo los propios, y «propios» quiere decir de quien mira.** Los de fábrica
            # salen de los perfiles, y los perfiles ya están arriba como botones de destino:
            # enseñarlos otra vez era una segunda fila de botones con los mismos nombres
            # haciendo lo mismo.
            #
            # El comentario decía «solo los propios» desde el principio y la consulta solo
            # excluía los de fábrica: en una máquina de una persona las dos cosas coinciden,
            # y en el servidor compartido ya no.
            "preajustes": ConversionPreset.propios_de(request.user).filter(
                target_format_code__in=[f.codigo for f in escribibles]
            )[:12],
        },
    )


@login_required
@require_POST
def subir(request):
    """Un archivo del equipo de quien lo manda, y su ficha de vuelta.

    Es la vía que faltaba. La otra —pegar una ruta— solo sirve para lo que el **servidor**
    ve, y en la instalación compartida eso es la carpeta de la obra y nada más. Un archivo
    que está en el portátil de alguien no tiene forma de llegar si no es subiéndolo.

    Devuelve el mismo fragmento que `inspeccionar`, así que la pantalla se comporta igual
    venga de donde venga el archivo. La diferencia queda dentro: el formulario lleva un
    identificador en vez de una ruta.
    """
    archivo = request.FILES.get("archivo")
    if archivo is None:
        # **Dos casos que se veían idénticos, y uno de ellos mentía.**
        #
        # Cuando la subida se pasa del tope, `SubidaConTope` la corta con `StopUpload`, que
        # descarta el cuerpo entero: aquí llega un `request.FILES` vacío, igual que si nadie
        # hubiera elegido nada. Quien subía 600 MB con el tope en 200 leía «No llegó ningún
        # archivo» y un código `ruta-no-permitida` — las dos cosas falsas.
        if getattr(request, manejador_mod.MARCA_DE_CORTE, False):
            return render(
                request,
                "dashboard/_ficha.html",
                {
                    "error": (
                        f"El archivo pasa de {settings.TOPE_MB} MB, que es el tope de subida "
                        f"por el navegador. Déjalo en la carpeta compartida: por ahí no hay "
                        f"tope, y copiar con el Explorador se reanuda si se corta."
                    ),
                    "codigo_error": "pasa-del-tope",
                },
            )
        return render(
            request,
            "dashboard/_ficha.html",
            {"error": "No llegó ningún archivo.", "codigo_error": "ruta-no-permitida"},
        )

    try:
        subida = subidas_mod.guardar(archivo, usuario=request.user)
    except ValidationError as fallo:
        # El tope de tamaño. El mensaje sale del modelo y dice cuántos megas caben, que es
        # lo único accionable: reintentar con el mismo archivo no va a funcionar.
        return render(
            request,
            "dashboard/_ficha.html",
            {"error": "; ".join(fallo.messages), "codigo_error": "ruta-no-permitida"},
        )

    # El formato pedido viaja igual que el destino: quien llegó desde «tif a jp2» lo eligió
    # antes de subir, y perderlo aquí obligaría a elegirlo otra vez con el archivo ya dentro.
    return _ficha(
        request,
        f"{entrada_mod.PREFIJO}{subida.pk}",
        (request.POST.get("formato") or "").strip(),
    )


@login_required
def explorar(request):
    """La carpeta compartida, para andarla en vez de teclearla.

    **Escribir una ruta a mano es la peor forma de elegir un archivo**: hay que saberla,
    copiarla sin el salto de línea, y en Windows viene con comillas. Y para la carpeta de la
    obra —que es de donde salen las ortofotos y las nubes— no hay ninguna razón para
    teclear: el servidor la ve entera y puede enseñarla.

    Solo lista **dentro de las raíces permitidas**: la comprobación es la misma de siempre,
    `comprobar_ruta`, así que este explorador no abre ni un milímetro más que lo que ya
    estaba abierto.
    """
    raices = modo_mod.raices_permitidas()
    pedida = (request.GET.get("en") or "").strip()

    if not pedida:
        # Sin nada pedido, la primera raíz. Si hay varias, se ofrecen todas.
        if not raices:
            return render(request, "dashboard/_explorador.html", {"sin_raices": True})
        actual = raices[0]
    else:
        try:
            actual = modo_mod.comprobar_ruta(pedida)
        except modo_mod.RutaNoPermitida as fallo:
            return render(request, "dashboard/_explorador.html", {"error": str(fallo)})

    if not actual.is_dir():
        return render(request, "dashboard/_explorador.html", {"error": "Eso no es una carpeta."})

    carpetas, archivos = _listar(actual)
    return render(
        request,
        "dashboard/_explorador.html",
        {
            "actual": str(actual),
            "migas": _migas(actual, raices),
            "carpetas": carpetas,
            "archivos": archivos,
            "raices": [str(r) for r in raices],
            "vacia": not carpetas and not archivos,
        },
    )


#: Cuantas entradas se pintan por carpeta. Una carpeta de obra con dos mil fotos convertiria
#: la pagina en una lista infinita que no ayuda a nadie a encontrar nada.
TOPE_DE_ENTRADAS = 300


def _listar(carpeta: Path):
    """Las subcarpetas y los archivos que la aplicación sabe abrir.

    Lo que no reconoce **no se lista**: un `.docx` o un `.zip` en medio de la obra solo son
    ruido cuando lo que se busca es la ortofoto. La extensión aquí es un filtro para mirar,
    no un veredicto — el veredicto lo sigue dando la inspección, que abre el archivo.
    """
    conocidas = {e.lower() for f in catalogo.FORMATOS.values() for e in f.extensiones}
    carpetas, archivos = [], []
    try:
        entradas = sorted(carpeta.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return [], []

    for entrada in entradas[:TOPE_DE_ENTRADAS]:
        try:
            if entrada.is_dir():
                carpetas.append({"nombre": entrada.name, "ruta": str(entrada)})
            elif entrada.suffix.lower() in conocidas:
                archivos.append(
                    {
                        "nombre": entrada.name,
                        "ruta": str(entrada),
                        "bytes": entrada.stat().st_size,
                    }
                )
        except OSError:  # pragma: no cover -- un enlace roto, o permisos
            continue
    return carpetas, archivos


def _migas(actual: Path, raices) -> list[dict]:
    """El rastro desde la raíz permitida hasta aquí, para poder volver atrás.

    **No se sube por encima de la raíz**, ni siquiera visualmente: un `..` que lleva a un
    sitio donde luego se recibe un «fuera de las carpetas permitidas» es peor que no tenerlo.
    """
    for raiz in raices:
        try:
            relativa = actual.relative_to(raiz)
        except ValueError:
            continue
        # **La raíz se nombra por lo que es, no por cómo se llama la carpeta.**
        #
        # En el servidor esa carpeta se llama `entregas`, así que la primera miga era la
        # palabra «entregas» suelta y en minúscula encabezando la pantalla: parece el nombre
        # de algo que se está entregando, no el sitio donde se busca. Y si mañana la carpeta
        # se llama `obras_2026`, el rótulo vuelve a ser jerga del sistema de archivos.
        #
        # Con varias raíces sí hace falta distinguirlas, y ahí el nombre de la carpeta es lo
        # único que las distingue.
        etiqueta = "Carpeta compartida" if len(raices) == 1 else (raiz.name or str(raiz))
        migas = [{"nombre": etiqueta, "ruta": str(raiz)}]
        acumulada = raiz
        for parte in relativa.parts:
            acumulada = acumulada / parte
            migas.append({"nombre": parte, "ruta": str(acumulada)})
        return migas
    return []


@login_required
def ajustes(request):
    """Los campos del modo experto para el formato elegido.

    Endpoint propio porque cambiar el formato de destino cambia los ajustes: JP2 tiene
    calidad y GeoTIFF tiene tamaño de tesela. htmx lo pide al cambiar el `<select>`.
    """
    inspeccion, _origen, error = _inspeccionar(request.GET.get("ruta") or "", usuario=request.user)
    if error:
        return render(request, "dashboard/_ajustes.html", {})

    formato = (request.GET.get("formato") or "").strip()
    if formato not in catalogo.FORMATOS:
        return render(request, "dashboard/_ajustes.html", {})

    _, campos = _formulario_experto(inspeccion, formato)
    return render(
        request,
        "dashboard/_ajustes.html",
        {"campos": campos, "formato_experto": formato, "i": inspeccion},
    )


def _inspeccionar(crudo: str, *, usuario):
    """El archivo del que se parte, venga de una ruta o de una subida.

    **Antes solo aceptaba rutas**, y en el servidor eso era una trampa: la pantalla invitaba
    a pegar la ruta del Explorador, alguien pegaba `C:\\Users\\...\\OF-220kv.tif` desde su
    equipo, y la aplicación contestaba que esa ruta está fuera de las carpetas permitidas.
    El mensaje era cierto y completamente inútil: el servidor no ve el disco de nadie.

    Ahora pasa por `entrada.resolver`, que es la puerta que ya usaban las pantallas de PDF y
    que distingue las dos vías por un prefijo en vez de adivinarlas.

    Devuelve tambien el `Origen`, porque lo que va al formulario es su `token` y **nunca** la
    ruta: para una subida, devolver la ruta del servidor dejaría que el POST siguiente la
    usara como si fuera una ruta del disco.
    """
    try:
        origen = entrada_mod.resolver(crudo, usuario=usuario)
    except modo_mod.RutaNoPermitida as fallo:
        return None, None, {"error": str(fallo), "codigo_error": fallo.codigo}

    try:
        return deteccion.inspeccionar(origen.ruta), origen, None
    except deteccion.OrigenIlegible as fallo:
        return None, None, {"error": str(fallo), "codigo_error": fallo.codigo}


@login_required
@require_POST
def encolar(request):
    """Encola el trabajo y lleva a su ficha.

    No convierte aquí: encola. La conversión la hace el despachador en un proceso hijo, y
    esta vista tiene que devolver en milisegundos — si esperara, el navegador agotaría el
    tiempo en cualquier archivo de verdad.
    """
    inspeccion, origen, error = _inspeccionar(request.POST.get("ruta") or "", usuario=request.user)
    if error:
        messages.error(request, error["error"])
        return redirect("dashboard:convertir")

    try:
        formato, opciones, perfil_id, preajuste = _destino_pedido(request, inspeccion)
    except formulario_mod.OpcionInvalida as fallo:
        messages.error(request, fallo.mensaje)
        return redirect("dashboard:convertir")
    except ValueError as fallo:
        messages.error(request, str(fallo))
        return redirect("dashboard:convertir")

    try:
        crs = _crs_del_trabajo(request, inspeccion)
    except ValueError as fallo:
        messages.error(request, str(fallo))
        return redirect("dashboard:convertir")

    ruta_origen = Path(inspeccion.ruta)
    job = ConversionJob.objects.create(
        owner=request.user,
        source_path=str(ruta_origen),
        # **El nombre que la persona reconoce, no el que quedó en el servidor.** Para una
        # subida son distintos: en el disco vive con un nombre que no eligió nadie, y ver ese
        # en el historial sería no reconocer el propio trabajo.
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

    if crs.es_declarado:
        # **La traza del día en que alguien puso la obra en otro país.**
        #
        # Va con el nombre de quien lo declaró, y va en la bitácora del trabajo, que es
        # append-only. Sin esta línea, «lo declaró una persona» no se puede sostener seis
        # meses después, cuando alguien pregunte por qué el entregable está donde está.
        job.registrar(
            f"{request.user.get_username()} declaró el sistema de referencia "
            f"{crs.autoridad}:{crs.codigo}. El archivo no lo traía dentro."
        )

    if preajuste is not None:
        preajuste.usar()
        job.registrar(f"Encolado con el preajuste «{preajuste.nombre}».")
    elif perfil_id:
        job.registrar(f"Encolado hacia {formato}. Perfil: {perfil_id}.")
    else:
        job.registrar(f"Encolado hacia {formato} con ajustes a mano.")

    return redirect("jobs:ficha", pk=job.pk)


def _crs_del_trabajo(request, inspeccion):
    """El CRS con el que se encola: el del archivo, o el que alguien declaró.

    Cuando el archivo lo trae dentro, no se admite nada más: dejar que un campo del
    formulario sobrescriba un CRS incrustado sería regalar una forma silenciosa de mover la
    obra de sitio.

    Y cuando no lo trae -- una libreta de puntos **nunca** lo trae -- se acepta lo declarado,
    validado contra pyproj. Sin valor por omisión y sin sugerir «el más probable»: la regla
    de la familia es que adivinarlo es peor que no tenerlo, y un desplegable que ya viene
    con EPSG:32719 puesto es una forma de adivinar con la firma de otro.
    """
    if inspeccion.crs.conocido:
        return inspeccion.crs

    declarado = (request.POST.get("crs_declarado") or "").strip()
    if not declarado:
        return inspeccion.crs

    try:
        return crs_mod.validar_declarado(declarado)
    except crs_mod.CrsInvalido as fallo:
        raise ValueError(str(fallo)) from fallo


def _destino_pedido(request, inspeccion):
    """Qué conversión se pidió: por preajuste, por perfil, o a mano.

    Los tres caminos acaban en lo mismo -- un formato y un diccionario de opciones -- y se
    resuelven aquí para que la vista no tenga tres ramas con el mismo `create()` al final.
    """
    slug = (request.POST.get("preajuste") or "").strip()
    if slug:
        preajuste = ConversionPreset.objects.filter(slug=slug).first()
        if preajuste is None:
            raise ValueError("Ese preajuste ya no existe.")
        return (
            preajuste.target_format_code,
            dict(preajuste.options),
            preajuste.target_profile_id,
            preajuste,
        )

    identificador = (request.POST.get("perfil") or "").strip()
    perfil = perfiles_mod.PERFILES.get(identificador)
    if perfil is not None:
        # El mismo destino por familia que se ofreció en el botón. Tenerlo en dos sitios con
        # criterios distintos haría que el botón dijera «LandXML» y encolara un GeoTIFF.
        return (
            perfil.destino_para(inspeccion.familia),
            dict(perfil.opciones),
            identificador,
            None,
        )

    formato = (request.POST.get("formato") or "").strip()
    if formato not in catalogo.FORMATOS:
        raise ValueError("Ese formato de destino no existe.")

    par = ParDeFormatos(inspeccion.codigo_formato, formato)
    motor = registry.motor_para(par)
    if motor is None:
        celda = registry.celda(par)
        raise ValueError(celda.mensaje or "Ningún motor sabe hacer esa conversión.")

    return formato, formulario_mod.leer(motor, par, request.POST), "", None


def _ruta_de_salida(origen: Path, formato: str, perfil_id: str) -> Path:
    """Dónde se escribe el resultado.

    En taller, junto al original y con un sufijo que dice para qué es. Se prefiere eso a una
    carpeta aparte porque quien convierte una ortofoto la quiere al lado de su entregable,
    no perdida en un directorio de la aplicación.
    """
    definicion = catalogo.FORMATOS.get(formato)
    extension = sorted(definicion.extensiones)[0] if definicion else ".out"
    sufijo = perfil_id or formato
    if modo_mod.es_taller():
        return origen.with_name(f"{origen.stem}_{sufijo}{extension}")

    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{origen.stem}_{sufijo}{extension}"
