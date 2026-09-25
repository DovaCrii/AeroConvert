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
    # Al carril pesado: un juego de doscientas láminas escaneadas tarda minutos, y en el
    # ligero dejaría esperando a un «numerar» de un segundo.
    "comprimir": Especificacion(
        carril=PESADO, timeout_s=1800, emite_progreso=True, salida_opcional=True
    ),
    "dividir": Especificacion(emite_progreso=True),
    # Dibujar doscientas láminas a 300 ppp no cabe en cinco minutos, y sigue siendo del
    # carril ligero: avanza hoja a hoja y lo dice, así que no bloquea sin que se vea.
    "a_imagenes": Especificacion(timeout_s=900, emite_progreso=True),
    "unir": Especificacion(),
    "imagenes": Especificacion(),
    # La contraseña llega por `secretos`, nunca por el encargo. Ver `plan()`.
    "proteger": Especificacion(con_secreto=True),
    # Al pesado: quinientas páginas son unos cuarenta minutos. El plazo crece con ellas; ver
    # `ocr.plazo_s`, que es quien sabe cuánto tarda una.
    "ocr": Especificacion(carril=PESADO, emite_progreso=True, exige="tesseract"),
}


def especificacion(herramienta: str) -> Especificacion | None:
    return ESPECIFICACIONES.get(herramienta)


def va_por_la_cola(herramienta: str) -> bool:
    """Si esta herramienta ya se ejecuta en la cola. Las demás siguen en su pantalla."""
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


def disponibilidad(herramienta: str) -> Disponibilidad:
    """Si esta máquina puede ejecutarla **ahora**. Lo mira el padre, que sí tiene Django."""
    espec = ESPECIFICACIONES.get(herramienta)
    if espec is None:
        return Disponibilidad.no("sin-motor", f"«{herramienta}» no se ejecuta desde la cola.")
    if not espec.exige:
        return Disponibilidad.si(f"documentos:{herramienta}")

    from . import catalogos, ocr, office

    sondas = {
        "office": (office.sondar, "sin-office"),
        "access": (catalogos.sondar, "sin-access"),
        "tesseract": (ocr.sondar, "sin-tesseract"),
    }
    sondar, codigo = sondas[espec.exige]
    estado = sondar()
    if not estado:
        return Disponibilidad.no(codigo, estado.motivo, sugerencia=estado.sugerencia)
    return Disponibilidad.si(f"documentos:{herramienta}")


_PROGRESO = re.compile(r"^PROGRESO\s+([0-9.]+)\s*$")


def _analizar_progreso(linea: str) -> float | None:
    encontrado = _PROGRESO.match(linea.strip())
    return float(encontrado.group(1)) if encontrado else None


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


def _paginas_con_pdfium(fuente) -> int:
    """Cuántas páginas ve PDFium. `fuente` es una ruta o los bytes de un PDF dentro del zip."""
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(fuente) if isinstance(fuente, Path) else fuente)
    try:
        return len(documento)
    finally:
        documento.close()


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
                else:
                    _comprobar_imagen(datos)
                    lectores.add("Pillow")
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
