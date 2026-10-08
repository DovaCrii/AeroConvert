"""El motor de las herramientas de documentos, del lado del corredor.

Describe qué hay que ejecutar y comprueba lo que salió; ejecutar lo hace `runner.py`, como
con cualquier otro motor. Lo que lo distingue de los geoespaciales:

## No se registra en `engines.registry`

A propósito. El registro alimenta la matriz de compatibilidad, la API y el formulario de
convertir, y todos suponen «formato de origen → formato de destino». Una herramienta de PDF
no es un par de formatos: «Numerar páginas» va de PDF a PDF. Registrarla habría llenado la
matriz de filas PDF → PDF que no significan nada. El corredor la encuentra por
`job.herramienta`, no por el par.

## La verificación la hace otra biblioteca

Las herramientas escriben con **pypdf**. Contar las páginas de la salida con pypdf sería el
código dándose la razón, que es justo lo que la regla 2 de `AGENTS.md` prohíbe. Aquí se
cuentan con **PDFium** —`pypdfium2`, el motor de PDF de Chrome—, que es otro analizador
escrito por otra gente: si pypdf escribiera un PDF que solo pypdf sabe leer, esto lo diría.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.engines.base import Disponibilidad, PlanDeEjecucion, Verificacion, ruta_parcial


@dataclass(frozen=True)
class Especificacion:
    """Lo que el corredor necesita saber de una herramienta para ejecutarla."""

    #: `ligero` o `pesado`. Ver `apps/jobs/despachador.py`: sin carriles, un «numerar» de un
    #: segundo esperaría detrás de una ortofoto de tres horas.
    carril: str = "ligero"
    timeout_s: int = 300
    #: Solo las que escriben líneas `PROGRESO`. Con las mudas, el detector de atasco mataría
    #: un trabajo sano por no decir nada.
    emite_progreso: bool = False
    #: Las que pueden terminar bien **sin archivo**, con un desenlace que lo explica.
    salida_opcional: bool = False
    #: Qué programa de fuera hace falta, si alguno: `office`, `access` o `tesseract`.
    exige: str = ""
    #: Si necesita una contraseña que la pantalla dejó en `secretos`.
    con_secreto: bool = False


LIGERO = "ligero"
PESADO = "pesado"

ESPECIFICACIONES: dict[str, Especificacion] = {
    "numerar": Especificacion(),
    "marca": Especificacion(),
    # Un escaneo no tiene texto que sacar, y eso no es un fallo: es la respuesta.
    "md_excel": Especificacion(salida_opcional=True),
    "md_csv": Especificacion(salida_opcional=True),
    "md_word": Especificacion(salida_opcional=True),
    "md_pdf": Especificacion(salida_opcional=True),
    "md_epub": Especificacion(salida_opcional=True),
    "md_html": Especificacion(salida_opcional=True),
    "md_a_pdf": Especificacion(),
    "telemetria": Especificacion(),
    "portada": Especificacion(exige="plantillas"),
    "html_a_pdf": Especificacion(),
    "reparar": Especificacion(timeout_s=600),
    # Al carril pesado: un juego de doscientas láminas escaneadas tarda minutos, y en el
    # ligero dejaría esperando a un «numerar» de un segundo.
    "comprimir": Especificacion(
        carril=PESADO, timeout_s=1800, emite_progreso=True, salida_opcional=True
    ),
    "dividir": Especificacion(emite_progreso=True),
    # Recortar al contenido dibuja cada hoja con PDFium: un juego de cien láminas A1 tarda.
    "tamano": Especificacion(timeout_s=900),
    # Dibuja las dos hojas de cada par y las resta; sin diferencias no hay archivo, y eso es la
    # respuesta, no un fallo.
    "comparar": Especificacion(
        carril=PESADO, timeout_s=1800, emite_progreso=True, salida_opcional=True
    ),
    # Dibujar doscientas láminas a 300 ppp no cabe en cinco minutos, y sigue siendo del
    # carril ligero: avanza hoja a hoja y lo dice, así que no bloquea sin que se vea.
    "a_imagenes": Especificacion(timeout_s=900, emite_progreso=True),
    "metadatos": Especificacion(),
    # Avanza página a página y lo dice; un PDF sin imágenes no es un fallo, es la respuesta.
    "extraer_imagenes": Especificacion(timeout_s=900, emite_progreso=True, salida_opcional=True),
    "formularios": Especificacion(),
    "firma_visible": Especificacion(),
    "firmar": Especificacion(con_secreto=True),
    "verificar_firmas": Especificacion(),
    "unir": Especificacion(),
    # Es la misma receta que «unir» con un solo archivo: otra pantalla, el mismo hijo.
    "organizar": Especificacion(),
    "imagenes": Especificacion(),
    "imagenes_lote": Especificacion(timeout_s=1800, emite_progreso=True),
    "fotos_dron": Especificacion(timeout_s=1800, emite_progreso=True),
    "vuelo_dron": Especificacion(carril=PESADO, timeout_s=1800, emite_progreso=True),
    "dxf_lamina": Especificacion(timeout_s=600),
    # La contraseña llega por `secretos`, nunca por el encargo. Ver `plan()`.
    "proteger": Especificacion(con_secreto=True),
    # Los términos a tachar llegan por el mismo camino que la contraseña: son justo lo que se
    # tapa, y no pueden quedar en la base. Dibuja cada página afectada: puede tardar.
    "redactar": Especificacion(
        carril=PESADO, timeout_s=1800, emite_progreso=True, con_secreto=True
    ),
    # Al pesado: quinientas páginas son unos cuarenta minutos. El plazo crece con ellas; ver
    # `ocr.plazo_s`, que es quien sabe cuánto tarda una.
    "ocr": Especificacion(carril=PESADO, emite_progreso=True, exige="tesseract"),
    # Office ya se ejecuta en un proceso aparte —pwsh hablando COM—, así que el hijo es ese
    # y no `tarea.py`. Ver `plan()`. Cinco minutos: un informe de doscientas páginas con
    # imágenes tarda de verdad, y más que eso es Word esperando una respuesta que no llegará.
    "office": Especificacion(timeout_s=300, exige="office"),
    "a_word": Especificacion(timeout_s=300, exige="office"),
    "catalogo_excel": Especificacion(timeout_s=900, exige="access"),
    "excel_catalogo": Especificacion(timeout_s=900, exige="access"),
}


def especificacion(herramienta: str) -> Especificacion | None:
    return ESPECIFICACIONES.get(herramienta)


def va_por_la_cola(herramienta: str) -> bool:
    """Si esta herramienta se ejecuta en la cola. Desde la fase 9, las veinte."""
    return herramienta in ESPECIFICACIONES


def carril_de(herramienta: str) -> str:
    """El carril de un trabajo. **Lo geoespacial es siempre pesado**: puede tardar horas."""
    espec = ESPECIFICACIONES.get(herramienta or "")
    return espec.carril if espec else PESADO


# --- Los archivos que acompañan al parcial ------------------------------------
#
# Llevan `.parcial.` en el nombre a propósito: es la marca que busca el barrido de huérfanos,
# así que si el obrero muere a mitad no se quedan para siempre en la carpeta de trabajo.


def _auxiliar(job, cual: str) -> Path:
    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{job.pk}.parcial.{cual}.json"


def ruta_del_encargo(job) -> Path:
    return _auxiliar(job, "encargo")


def ruta_del_informe(job) -> Path:
    return _auxiliar(job, "informe")


def leer_informe(job) -> dict:
    try:
        return json.loads(ruta_del_informe(job).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def borrar_auxiliares(job) -> None:
    for ruta in (ruta_del_encargo(job), ruta_del_informe(job)):
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            pass
    # Las piezas de Dividir y PDF a imágenes. El hijo las borra al terminar, pero si lo mata
    # el plazo o un «Cancelar» no llega a hacerlo, y quedarían junto al original de alguien.
    if job.output_path:
        from .tarea import carpeta_de_piezas

        shutil.rmtree(carpeta_de_piezas(ruta_parcial(Path(job.output_path))), ignore_errors=True)
    # Normalmente ya no está —`plan()` la toma y la borra—, pero si el trabajo falló antes de
    # llegar ahí seguiría en disco hasta el barrido.
    from . import secretos

    secretos.olvidar(job)


# --- Disponibilidad, plan y verificación --------------------------------------


def disponibilidad(herramienta: str, opciones: dict | None = None) -> Disponibilidad:
    """Si esta máquina puede ejecutarla **ahora**, y con qué. Lo mira el padre, que sí tiene Django.

    `opciones` son las del trabajo: «Office a PDF» con LibreOffice solo cuenta si el trabajo lo
    pidió (`con_libreoffice`). Así el recibo dice con qué se convirtió de verdad, y una vía que no
    puede aceptar la advertencia (un lote, la API) ve la herramienta apagada en vez de fallar tarde.
    """
    espec = ESPECIFICACIONES.get(herramienta)
    if espec is None:
        return Disponibilidad.no("sin-motor", f"«{herramienta}» no se ejecuta desde la cola.")
    if not espec.exige:
        return Disponibilidad.si(f"documentos:{herramienta}")

    from . import catalogos, ocr, office, portadas

    sondas = {
        "plantillas": (portadas.sondar, "sin-plantillas"),
        "office": (office.sondar, "sin-office"),
        "access": (catalogos.sondar, "sin-access"),
        "tesseract": (ocr.sondar, "sin-tesseract"),
    }
    if herramienta == "office" and (opciones or {}).get("con_libreoffice"):
        if office.sondar_libreoffice():
            return Disponibilidad.si(ROTULO_LIBREOFFICE)
        return Disponibilidad.no(
            "sin-office",
            "Se pidió convertir con LibreOffice y en esta máquina ya no está.",
            sugerencia="sudo despliegue/instalar_faltantes.sh",
        )
    sondar, codigo = sondas[espec.exige]
    estado = sondar()
    if not estado:
        return Disponibilidad.no(codigo, estado.motivo, sugerencia=estado.sugerencia)
    return Disponibilidad.si(f"documentos:{herramienta}")


#: Lo que queda en el recibo (`engine_version`) cuando se convirtió con LibreOffice.
ROTULO_LIBREOFFICE = "documentos:office con LibreOffice (el PDF puede variar respecto del original)"


_PROGRESO = re.compile(r"^PROGRESO\s+([0-9.]+)(?:\s+(.+?))?\s*$")


def _analizar_progreso(linea: str) -> float | tuple[float, str] | None:
    encontrado = _PROGRESO.match(linea.strip())
    if not encontrado:
        return None
    fraccion = float(encontrado.group(1))
    return (fraccion, encontrado.group(2)) if encontrado.group(2) else fraccion


def plan(job) -> PlanDeEjecucion:
    """Escribe el encargo y describe el proceso hijo. **Sin la contraseña**: ver `secretos`."""
    espec = ESPECIFICACIONES[job.herramienta]
    destino = Path(job.output_path)
    parcial = ruta_parcial(destino)

    entradas = [
        {"ruta": e.ruta, "nombre": e.nombre, "papel": e.papel} for e in job.entradas.all()
    ] or [{"ruta": job.source_path, "nombre": job.source_name, "papel": ""}]

    entorno = {
        # Sin esto el progreso llega todo junto al final: Python guarda la salida en un
        # búfer cuando no escribe en una terminal.
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    # Lo que el hijo lee de su entorno y vive en el `.env`: se lo pasa el padre, que sí lo leyó.
    from .firma_digital import VARIABLE_RAICES, VARIABLE_TSA

    for variable, valor in (
        (VARIABLE_RAICES, getattr(settings, "RAICES_DE_CONFIANZA", "")),
        (VARIABLE_TSA, getattr(settings, "TSA_URL", "")),
    ):
        if valor:
            entorno[variable] = valor
    if espec.con_secreto:
        from . import secretos

        # **Se toma antes de escribir nada**: si ya no está, el trabajo falla sin haber
        # tocado el disco. Levanta `secretos.SinSecreto`, que el corredor traduce.
        entorno[secretos.VARIABLE] = secretos.tomar(job)

    plazo_s = espec.timeout_s
    if job.herramienta == "ocr":
        from . import ocr
        from .tarea import VARIABLE_TESSERACT

        # El padre ya sondeó para decidir si estaba disponible; el hijo no puede, porque la
        # sonda guarda en la caché de Django. Así que se le da la ruta hecha.
        entorno[VARIABLE_TESSERACT] = ocr.sondar().programa
        plazo_s = ocr.plazo_s(_paginas_del_trabajo(job, entradas))
    if espec.exige == "access":
        from . import catalogos
        from .tarea import VARIABLE_ACCESS

        entorno[VARIABLE_ACCESS] = catalogos.sondar().controlador

    if espec.exige == "office":
        return _plan_de_office(job, espec, entradas[0], destino, parcial, entorno)

    encargo = ruta_del_encargo(job)
    encargo.parent.mkdir(parents=True, exist_ok=True)
    encargo.write_text(
        json.dumps({"entradas": entradas, "opciones": dict(job.options or {})}, ensure_ascii=False),
        encoding="utf-8",
    )

    return PlanDeEjecucion(
        argv=(
            sys.executable,
            "-m",
            "apps.documents.tarea",
            job.herramienta,
            str(encargo),
            str(parcial),
            str(ruta_del_informe(job)),
        ),
        ruta_de_salida=destino,
        env=entorno,
        cwd=Path(settings.BASE_DIR),
        timeout_s=plazo_s,
        analizador_de_progreso=_analizar_progreso,
        emite_progreso=espec.emite_progreso,
        salida_opcional=espec.salida_opcional,
    )


def _plan_de_office(job, espec, entrada: dict, destino, parcial, entorno) -> PlanDeEjecucion:
    """**El hijo es pwsh**, con el mismo guion que usaba la pantalla.

    Pasarlo por `tarea.py` sería un proceso de Python que solo lanza otro proceso, y además
    no podría: `office.convertir` sondea con la caché de Django. El argv sale de
    `office.plan()`, que ya existía para poder probarlo sin Office.

    Lo que Office no hace es contar lo que escribió, así que no hay informe: el corredor
    comprueba que el parcial exista y lo verifica por su extensión, como con GDAL.
    """
    from . import office

    origen = Path(entrada["ruta"])
    if job.herramienta == "a_word":
        argv = office.plan(origen, parcial, office.PDF_A_WORD)
    elif (job.options or {}).get("con_libreoffice"):
        # La disponibilidad ya se comprobó con estas opciones (`disponibilidad`): aquí está.
        office.programa_de(origen)  # valida la extensión: la misma lista que con Office
        argv = office.plan_libreoffice(origen, parcial, office.sondar_libreoffice())
    else:
        argv = office.plan(
            origen,
            parcial,
            office.programa_de(origen),
            ajustar_ancho=bool((job.options or {}).get("ajustar_ancho")),
        )
    return PlanDeEjecucion(
        argv=tuple(argv),
        ruta_de_salida=destino,
        env=entorno,
        cwd=Path(settings.BASE_DIR),
        timeout_s=espec.timeout_s,
        emite_progreso=False,
    )


def _paginas_del_trabajo(job, entradas: list[dict]) -> int:
    """Las que contó la pantalla al mirar; si no vinieran, se cuentan aquí."""
    paginas = int((job.options or {}).get("paginas") or 0)
    if paginas:
        return paginas
    from apps.formats import pdf as lectura_pdf

    try:
        return lectura_pdf.leer_cabecera(entradas[0]["ruta"]).cuantas
    except lectura_pdf.NoEsPdf:
        return 1  # el hijo lo dirá mejor: no es un PDF


def verificar(parcial: Path, informe: dict, plan: PlanDeEjecucion | None = None) -> Verificacion:
    """Comprueba la salida **con un lector distinto del que la escribió**.

    Lo que se comprueba lo decide la extensión, no la herramienta: cualquier PDF que salga
    se abre con PDFium, cualquier `.md` se decodifica, cualquier zip se recorre. Así una
    herramienta nueva hereda la verificación sin que nadie se acuerde de escribirla.
    """
    if not parcial.exists():
        return Verificacion(False, "No hay archivo que verificar.", "sin-salida")
    tamano = parcial.stat().st_size
    if tamano == 0:
        return Verificacion(False, "El archivo salió vacío.", "salida-invalida")

    detalles = dict(informe.get("detalles") or {})
    detalles["bytes"] = tamano
    extension = parcial.suffix.lower()

    if extension == ".pdf" and detalles.get("accion") == "firmar":
        return _verificar_firmado(parcial, detalles)
    if extension == ".pdf" and detalles.get("accion") == "proteger":
        from . import secretos

        contrasena = (plan.env if plan else {}).get(secretos.VARIABLE, "")
        return _verificar_protegido(parcial, detalles, contrasena)
    if extension == ".pdf":
        veredicto = _verificar_pdf(parcial, detalles)
        if veredicto.correcta and detalles.get("accion") == "quitar":
            # PDFium acaba de abrirlo sin contraseña, que es justo lo que se pidió.
            veredicto.detalles["cifrado"] = "ninguno"
        return veredicto
    if extension == ".zip":
        return _verificar_zip(parcial, detalles)
    if extension in _PARTE_PRINCIPAL:
        return _verificar_ooxml(parcial, detalles, _PARTE_PRINCIPAL[extension])
    if extension == ".mdb":
        return _verificar_mdb(parcial, detalles)
    if extension in (".gpx", ".kml"):
        return _verificar_traza(parcial, detalles)
    if extension == ".svg":
        return _verificar_svg(parcial, detalles)
    if extension in _IMAGENES:
        try:
            _comprobar_imagen(parcial.read_bytes())
        except Exception as fallo:  # noqa: BLE001 - lo que falle al leerla es lo que se mide
            return Verificacion(False, f"La imagen no se deja leer: {fallo}", "salida-invalida")
        detalles["verificado_con"] = "Pillow"
        return Verificacion(True, detalles=detalles)
    if extension == ".md":
        try:
            texto = parcial.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as fallo:
            return Verificacion(
                False, f"El Markdown no se lee como UTF-8: {fallo}", "salida-invalida"
            )
        if not texto.strip():
            return Verificacion(False, "El Markdown salió sin texto.", "salida-invalida")
        detalles["lineas"] = texto.count("\n") + 1
        return Verificacion(True, detalles=detalles)

    return Verificacion(True, detalles=detalles)


_IMAGENES = frozenset({".png", ".jpg", ".jpeg"})

#: La parte sin la que un documento de Office no es nada. Un `.docx` es un zip, y un zip
#: íntegro sin `word/document.xml` se abre en Word como «el archivo está dañado».
_PARTE_PRINCIPAL = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml"}

#: Lo que llevan en el byte 4 las bases de Access: Jet para `.mdb`, ACE para `.accdb`.
_FIRMAS_DE_ACCESS = (b"Standard Jet DB", b"Standard ACE DB")


def _verificar_ooxml(parcial: Path, detalles: dict, parte: str) -> Verificacion:
    try:
        with zipfile.ZipFile(parcial) as paquete:
            rota = paquete.testzip()
            nombres = set(paquete.namelist())
            hojas = sum(1 for n in nombres if n.startswith("xl/worksheets/sheet"))
    except zipfile.BadZipFile as fallo:
        return Verificacion(
            False, f"El documento escrito no se deja abrir: {fallo}", "salida-invalida"
        )
    if rota is not None:
        return Verificacion(False, f"{rota} está dañado dentro del documento.", "salida-invalida")
    if parte not in nombres:
        return Verificacion(False, f"Al documento le falta {parte}.", "salida-invalida")

    # Catálogo a Excel: **una hoja por tabla**, y si falta una es que se perdió una tabla.
    tablas = detalles.get("tablas") or []
    if tablas and hojas != len(tablas):
        return Verificacion(
            False,
            f"El catálogo tiene {len(tablas)} tablas y el Excel salió con {hojas} hojas.",
            "salida-invalida",
        )
    if detalles.get("portada"):
        # Una portada con un `XXXXXX` sin cambiar sale impresa en una oferta: se lee el texto de
        # cada parte con un lector que no escribió el documento (el zip y una expresión).
        sobrantes = _marcadores_sin_cambiar(parcial)
        if sobrantes:
            return Verificacion(
                False,
                f"La portada salió con marcadores de relleno sin cambiar ({sobrantes}).",
                "salida-invalida",
            )
    detalles["verificado_con"] = "zipfile"
    return Verificacion(True, detalles=detalles)


def _verificar_traza(parcial: Path, detalles: dict) -> Verificacion:
    """Que el XML se lea y que lleve **los puntos que se dijo que llevaba**.

    Con un analizador de XML, que no es el código que lo escribió; la comprobación contra GDAL
    (`ogrinfo`) es la prueba con oráculo, que no entra en la puerta.
    """
    from defusedxml import ElementTree

    try:
        raiz = ElementTree.parse(str(parcial)).getroot()
    except Exception as fallo:  # noqa: BLE001 - lo que falle al leerlo es lo que se mide
        return Verificacion(False, f"La traza no es un XML válido: {fallo}", "salida-invalida")

    if parcial.suffix.lower() == ".gpx":
        puntos = sum(1 for e in raiz.iter() if e.tag.endswith("trkpt"))
    else:
        puntos = 0
        for e in raiz.iter():
            if e.tag.endswith("LineString"):
                coordenadas = next((c for c in e.iter() if c.tag.endswith("coordinates")), None)
                puntos += len((coordenadas.text or "").split()) if coordenadas is not None else 0

    esperados = detalles.get("puntos")
    if esperados is not None and puntos != esperados:
        return Verificacion(
            False,
            f"La traza salió con {puntos} puntos y debía llevar {esperados}.",
            "salida-invalida",
        )
    detalles["puntos_leidos"] = puntos
    detalles["verificado_con"] = "un analizador de XML"
    return Verificacion(True, detalles=detalles)


def _marcadores_sin_cambiar(ruta: Path) -> int:
    import re

    cuantos = 0
    with zipfile.ZipFile(ruta) as paquete:
        for nombre in paquete.namelist():
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nombre):
                xml = paquete.read(nombre).decode("utf-8", errors="replace")
                for texto in re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml):
                    if re.fullmatch(r"\s*(PLAN DE\s+)?X{3,}x?\s*", texto):
                        cuantos += 1
    return cuantos


def _verificar_mdb(parcial: Path, detalles: dict) -> Verificacion:
    """Por la firma. Abrirla exigiría el mismo controlador que la escribió."""
    with open(parcial, "rb") as base:
        cabecera = base.read(32)
    if cabecera[4:19] not in _FIRMAS_DE_ACCESS:
        return Verificacion(False, "Lo escrito no es una base de Access.", "salida-invalida")
    detalles["verificado_con"] = "la firma del archivo"
    return Verificacion(True, detalles=detalles)


def _paginas_con_pdfium(fuente) -> int:
    """Cuántas páginas ve PDFium. `fuente` es una ruta o los bytes de un PDF dentro del zip."""
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(fuente) if isinstance(fuente, Path) else fuente)
    try:
        return len(documento)
    finally:
        documento.close()


def _comparar_con_lo_dicho(nombre: str, datos: bytes, pieza: dict) -> Verificacion | None:
    """Las dimensiones y el formato **que Pillow lee** frente a los que la herramienta declaró.

    Para un lote de imágenes: lo que se escribió se reabre y se mide, no se da por bueno lo que
    la propia función cuenta. `None` si coincide.
    """
    from PIL import Image

    with Image.open(io.BytesIO(datos)) as imagen:
        medido = (imagen.size[0], imagen.size[1], (imagen.format or "").lower())
    dicho = (int(pieza["ancho"]), int(pieza["alto"]), str(pieza.get("formato", "")).lower())
    if dicho[2] and medido != dicho:
        return Verificacion(
            False,
            f"{nombre} debía medir {dicho[0]}×{dicho[1]} en {dicho[2].upper()} y mide "
            f"{medido[0]}×{medido[1]} en {medido[2].upper()}.",
            "salida-invalida",
        )
    if not dicho[2] and medido[:2] != dicho[:2]:
        return Verificacion(
            False,
            f"{nombre} debía medir {dicho[0]}×{dicho[1]} y mide {medido[0]}×{medido[1]}.",
            "salida-invalida",
        )
    return None


def _comprobar_imagen(datos: bytes) -> None:
    """Que la imagen se deje leer entera.

    **Aquí el lector es el mismo que la escribió** —Pillow— y conviene decirlo: no hay en el
    proyecto otro que lea PNG y JPEG. Lo que sí caza es lo que se ve en la práctica: una
    imagen cortada por un disco lleno, o un PNG con el CRC roto. Las dimensiones no se
    comparan con nada porque saldrían de la misma cuenta que las produjo.
    """
    from PIL import Image

    with Image.open(io.BytesIO(datos)) as imagen:
        imagen.verify()


def _verificar_firmado(parcial: Path, detalles: dict) -> Verificacion:
    """El PDF firmado abre con PDFium y la firma nueva cuadra **calculada a mano** (no por pyHanko).

    Es el otro lector: resumen con `hashlib`, CMS con `asn1crypto` y firma con `cryptography`.
    Las firmas que ya traía siguen con su resumen intacto, y la nueva cubre hasta el último byte.
    """
    from . import firma_comprobar

    base = _verificar_pdf(parcial, detalles)
    if not base.correcta:
        return base
    try:
        hechas = firma_comprobar.comprobar(parcial.read_bytes())
    except Exception as fallo:  # noqa: BLE001 - un CMS que no se lee es una firma que no vale
        return Verificacion(False, f"La firma no se deja leer: {fallo}", "salida-invalida")
    esperadas = int(detalles.get("firmas_previas", 0)) + 1
    if len(hechas) != esperadas:
        return Verificacion(
            False,
            f"Debía haber {esperadas} firma(s) y hay {len(hechas)}.",
            "salida-invalida",
        )
    if not all(h.resumen_cuadra for h in hechas):
        return Verificacion(False, "El resumen de una firma no cuadra.", "salida-invalida")
    ultima = hechas[-1]
    if detalles.get("firmante") and ultima.firmante != detalles["firmante"]:
        return Verificacion(
            False,
            f"La última firma es de «{ultima.firmante}» y debía ser de «{detalles['firmante']}».",
            "salida-invalida",
        )
    n = detalles.get("bytes_original")
    if n and hashlib.sha256(parcial.read_bytes()[: int(n)]).hexdigest() != detalles.get(
        "sha256_original"
    ):
        return Verificacion(
            False,
            "El PDF firmado no empieza por el original: no es una firma incremental.",
            "salida-invalida",
        )
    if ultima.firma_cuadra is not True or not ultima.cubre_el_archivo:
        return Verificacion(
            False, "La firma nueva no se verifica o no cubre el archivo entero.", "salida-invalida"
        )
    base.detalles["verificado_con"] = "PDFium, hashlib y cryptography"
    return base


def _verificar_svg(parcial: Path, detalles: dict) -> Verificacion:
    """Un SVG cerrado y con tantas trayectorias como se dijo (sin analizar XML ajeno)."""
    import re

    try:
        texto = parcial.read_text(encoding="utf-8")
    except UnicodeDecodeError as fallo:
        return Verificacion(False, f"El SVG no se decodifica: {fallo}", "salida-invalida")
    if "<svg" not in texto[:400] or not texto.rstrip().endswith("</svg>"):
        return Verificacion(False, "El SVG no está completo.", "salida-invalida")
    dicho = detalles.get("trazos")
    hay = len(re.findall(r"<path ", texto))
    if dicho is not None and int(dicho) != hay:
        return Verificacion(
            False, f"El SVG debía traer {dicho} trayectorias y trae {hay}.", "salida-invalida"
        )
    detalles["verificado_con"] = "lectura del SVG"
    return Verificacion(True, detalles=detalles)


def _conserva_gps(datos: bytes) -> bool:
    """Si Pillow (que no escribió esos bytes) todavía lee una posición, o queda el XMP del dron."""
    from PIL import Image

    with Image.open(io.BytesIO(datos)) as imagen:
        gps = imagen.getexif().get_ifd(0x8825)
    return bool(gps) or b"GpsLatitude" in datos


def _problema_en_la_posicion(nombre: str, datos: bytes, pieza: dict) -> str:
    """La foto corregida dice, leída por Pillow, la posición que se le quiso poner.

    Pillow no escribió esos bytes (los escribió `vuelo_exif`). Vacío si está bien.
    """
    from PIL import Image

    from apps.documents import fotos_dron

    lat, lon = pieza["lat"], pieza["lon"]
    with Image.open(io.BytesIO(datos)) as imagen:
        gps = imagen.getexif().get_ifd(0x8825)
    leida_lat = fotos_dron._grados(gps.get(2), gps.get(1)) if gps.get(2) is not None else None
    leida_lon = fotos_dron._grados(gps.get(4), gps.get(3)) if gps.get(4) is not None else None
    if leida_lat is None or leida_lon is None:
        return f"{nombre} debía traer la posición corregida y no la trae."
    if pieza.get("alt") is not None:
        alt = gps.get(6)
        if alt is None or abs(float(alt) - pieza["alt"]) > 1e-3:
            return f"{nombre} debía traer la altura {pieza['alt']:.3f} y trae {alt}."
    elif gps.get(6) is not None:
        return f"{nombre} trae una altura que no se le quiso escribir."
    if pieza.get("datum") and str(gps.get(18, "")).strip("\x00 ") != pieza["datum"]:
        return f"{nombre} debía declarar el datum {pieza['datum']} y declara {gps.get(18)}."
    if abs(leida_lat - lat) > 1e-8 or abs(leida_lon - lon) > 1e-8:
        return f"{nombre} trae {leida_lat:.8f}, {leida_lon:.8f} y debía traer {lat:.8f}, {lon:.8f}."
    return ""


def _problema_en_texto(nombre: str, datos: bytes, pieza: dict) -> str:
    """Una pieza de texto del zip abre, y trae tantas filas, puntos o fotos como se dijo.

    Se lee con `csv` y `json` de la biblioteca estándar, que no escribieron la pieza. Vacío si
    está bien.
    """
    import csv
    import json
    import re

    try:
        texto = datos.decode("utf-8")
    except UnicodeDecodeError as fallo:
        return f"{nombre} no se decodifica como texto: {fallo}"
    if not texto.strip():
        return f"{nombre} salió vacío."
    minuscula = nombre.lower()
    if minuscula.endswith(".csv"):
        filas = list(csv.reader(io.StringIO(texto)))
        cuerpo = len(filas) - 1
        dicho = pieza.get("filas")
        if dicho is not None and int(dicho) != cuerpo:
            return f"{nombre} debía traer {dicho} fila(s) y trae {cuerpo}."
    elif minuscula.endswith(".json"):
        try:
            contenido = json.loads(texto)
        except ValueError as fallo:
            return f"{nombre} no es un JSON válido: {fallo}"
        dicho = pieza.get("fotos")
        if dicho is not None and len(contenido.get("fotos", [])) != int(dicho):
            return f"{nombre} debía traer {dicho} foto(s) y trae {len(contenido.get('fotos', []))}."
    elif minuscula.endswith(".kml"):
        if not texto.rstrip().endswith("</kml>"):
            return f"{nombre} no está completo."
        cuantas = len(re.findall(r"<Placemark>", texto))
        dicho = pieza.get("puntos")
        if dicho is not None and int(dicho) != cuantas:
            return f"{nombre} debía traer {dicho} punto(s) y trae {cuantas}."
    return ""


def _problema_en_posiciones(nombre: str, datos: bytes, pieza: dict) -> str:
    """El archivo de posiciones abre y trae tantas como se dijo. Vacío si está bien."""
    import json
    import re

    esperadas = pieza.get("puntos")
    if nombre.lower().endswith(".geojson"):
        rasgos = json.loads(datos.decode("utf-8")).get("features", [])
        cuantas = len(rasgos)
    else:
        with zipfile.ZipFile(io.BytesIO(datos)) as kmz:
            kml = kmz.read("doc.kml").decode("utf-8")
        cuantas = len(re.findall(r"<Placemark>", kml))
    if not cuantas or (esperadas is not None and int(esperadas) != cuantas):
        return f"{nombre} debía traer {esperadas} posición(es) y trae {cuantas}."
    return ""


def _verificar_zip(parcial: Path, detalles: dict) -> Verificacion:
    """Cada pieza, abierta por separado. Un zip íntegro con un PDF roto dentro sigue roto."""
    try:
        paquete = zipfile.ZipFile(parcial)
    except zipfile.BadZipFile as fallo:
        return Verificacion(False, f"El zip escrito no se deja abrir: {fallo}", "salida-invalida")

    with paquete:
        rota = paquete.testzip()
        if rota is not None:
            return Verificacion(False, f"{rota} está dañado dentro del zip.", "salida-invalida")

        nombres = paquete.namelist()
        esperadas = {p["nombre"]: p for p in detalles.get("piezas") or []}
        if esperadas and sorted(nombres) != sorted(esperadas):
            return Verificacion(
                False,
                f"La herramienta dice que escribió {len(esperadas)} piezas y el zip trae "
                f"{len(nombres)}.",
                "salida-invalida",
            )
        if not nombres:
            return Verificacion(False, "El zip salió vacío.", "salida-invalida")

        lectores = set()
        for nombre in nombres:
            datos = paquete.read(nombre)
            try:
                if nombre.lower().endswith(".pdf"):
                    paginas = _paginas_con_pdfium(datos)
                    lectores.add("PDFium")
                    pedidas = (esperadas.get(nombre) or {}).get("paginas")
                    if not paginas or (pedidas and int(pedidas) != paginas):
                        return Verificacion(
                            False,
                            f"{nombre} debía tener {pedidas} página(s) y tiene {paginas}.",
                            "salida-invalida",
                        )
                elif nombre.lower().endswith((".csv", ".json", ".kml", ".md")):
                    problema = _problema_en_texto(nombre, datos, esperadas.get(nombre) or {})
                    if problema:
                        return Verificacion(False, problema, "salida-invalida")
                    lectores.add("lectura del texto")
                elif nombre.lower().endswith((".geojson", ".kmz")):
                    problema = _problema_en_posiciones(nombre, datos, esperadas.get(nombre) or {})
                    if problema:
                        return Verificacion(False, problema, "salida-invalida")
                    lectores.add("JSON y KML")
                else:
                    _comprobar_imagen(datos)
                    lectores.add("Pillow")
                    pieza = esperadas.get(nombre) or {}
                    if pieza.get("sin_gps") and _conserva_gps(datos):
                        return Verificacion(
                            False,
                            f"{nombre} debía salir sin posición y todavía la trae.",
                            "salida-invalida",
                        )
                    if pieza.get("lat") is not None:
                        problema = _problema_en_la_posicion(nombre, datos, pieza)
                        if problema:
                            return Verificacion(False, problema, "salida-invalida")
                    if pieza.get("ancho"):
                        veredicto = _comparar_con_lo_dicho(nombre, datos, pieza)
                        if veredicto is not None:
                            return veredicto
            except Exception as fallo:  # noqa: BLE001 - la pieza no se lee, y eso se mide
                return Verificacion(False, f"{nombre} no se deja abrir: {fallo}", "salida-invalida")

    detalles["piezas_verificadas"] = len(nombres)
    detalles["verificado_con"] = " y ".join(sorted(lectores))
    return Verificacion(True, detalles=detalles)


def _verificar_protegido(parcial: Path, detalles: dict, contrasena: str) -> Verificacion:
    """Tres cosas, y las tres con PDFium, no con pypdf, que es quien cifró.

    1. **Que sin la contraseña no abra.** Es lo único que promete «proteger», y un error que
       dejara el PDF en claro sería invisible: se abriría bien y parecería que funcionó.
    2. **Que con ella sí**, y con las páginas que tenía.
    3. **Que sea AES-256**: revisión 6 del gestor de seguridad estándar. RC4 lleva veinte años
       roto, y un PDF cifrado así da una seguridad que no existe. Ver `seguridad.py`.
    """
    import pypdfium2
    import pypdfium2.raw as pdfium_c

    try:
        _paginas_con_pdfium(parcial)
    except pypdfium2.PdfiumError:
        pass  # lo esperado: pide contraseña
    else:
        return Verificacion(False, "El PDF «protegido» se abre sin contraseña.", "salida-invalida")

    if not contrasena:
        return Verificacion(
            False, "No hay contraseña con la que comprobar el resultado.", "falta-la-contrasena"
        )
    try:
        documento = pypdfium2.PdfDocument(str(parcial), password=contrasena)
    except pypdfium2.PdfiumError as fallo:
        return Verificacion(
            False,
            f"La contraseña no abre el PDF que se acaba de cifrar: {fallo}",
            "salida-invalida",
        )
    try:
        paginas = len(documento)
        revision = pdfium_c.FPDF_GetSecurityHandlerRevision(documento.raw)
    finally:
        documento.close()

    if revision < 6:
        return Verificacion(
            False, f"El cifrado no es AES-256 (revisión {revision}).", "salida-invalida"
        )
    esperadas = detalles.get("paginas")
    if not paginas or (esperadas and int(esperadas) != paginas):
        return Verificacion(
            False,
            f"La herramienta dice que escribió {esperadas} páginas y el PDF tiene {paginas}.",
            "salida-invalida",
        )

    detalles["paginas_verificadas"] = paginas
    detalles["verificado_con"] = "PDFium"
    detalles["cifrado"] = "AES-256"
    return Verificacion(True, detalles=detalles)


def _verificar_pdf(parcial: Path, detalles: dict) -> Verificacion:
    try:
        paginas = _paginas_con_pdfium(parcial)
    except Exception as fallo:  # noqa: BLE001 - PDFium no lo abre, y eso es lo que se mide
        return Verificacion(False, f"El PDF escrito no se deja abrir: {fallo}", "salida-invalida")

    if paginas == 0:
        return Verificacion(False, "El PDF salió sin páginas.", "salida-invalida")

    esperadas = detalles.get("paginas")
    if esperadas and int(esperadas) != paginas:
        return Verificacion(
            False,
            f"La herramienta dice que escribió {esperadas} páginas y el PDF tiene {paginas}.",
            "salida-invalida",
        )

    detalles["paginas_verificadas"] = paginas
    detalles["verificado_con"] = "PDFium"
    return Verificacion(True, detalles=detalles)
