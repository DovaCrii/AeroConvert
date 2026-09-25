"""Sacar el contenido de un archivo y dejarlo en Markdown.

## Por qué Markdown y no «texto»

Un informe de terreno, una tabla de coordenadas o un acta acaban copiándose a mano a un correo,
a una ficha de AeroControl o a un tablero. Markdown es el formato que atraviesa todo eso **sin
perder la tabla ni los títulos**, y no necesita programa para leerse: abierto en el Bloc de
notas sigue entendiéndose, que es más de lo que puede decir un `.docx`.

## De dónde sale la lista de formatos

De `markitdown` de Microsoft, cuyo inventario se estudió entero. **El paquete no entra** —las
razones, con cifras, están en `pyproject.toml`— pero su catálogo es bueno y su conversor de
EPUB demuestra algo útil: que un EPUB es un ZIP con XHTML dentro y no hace falta ninguna
librería para leerlo.

## La regla que gobierna todo este módulo

**Si no hay nada que sacar, se dice; no se entrega un archivo vacío.**

Es el caso del PDF escaneado, que es una imagen de un texto y no tiene texto: `pypdf` devuelve
cadenas vacías sin quejarse, y escribir ese `.md` de cero bytes sería la peor respuesta posible
—parece que funcionó—. Lo mismo con un Excel cuyas fórmulas nunca se calcularon.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from .composicion import ComposicionInvalida

#: Lo que se sabe leer, y con qué. El orden es el de la pantalla.
ORIGENES = {
    ".xlsx": "Hoja de cálculo",
    ".xlsm": "Hoja de cálculo",
    ".csv": "Tabla separada por comas",
    ".docx": "Documento de Word",
    ".pdf": "PDF",
    ".epub": "Libro EPUB",
    ".html": "Página web",
    ".htm": "Página web",
}

#: Tope de lo que se saca de un ZIP —EPUB— ya descomprimido.
#:
#: Un ZIP de un megabyte puede contener gigabytes de ceros: es la «bomba zip», y leerla entera
#: en memoria tumba el proceso. Sesenta megabytes de texto son un libro enorme.
TOPE_DESCOMPRIMIDO = 60 * 1_048_576

#: Cuántas filas y columnas se leen como máximo de una hoja.
#:
#: Una hoja de Excel admite un millón de filas, y una tabla de Markdown de un millón de filas
#: no la abre nada ni la lee nadie. Cortar y **decirlo** es mejor que colgar la máquina.
TOPE_FILAS = 5_000
TOPE_COLUMNAS = 100


class SinTextoQueSacar(ComposicionInvalida):
    """El archivo se abrió bien y no tiene nada que convertir.

    Es su propia clase porque **no es un error de la persona ni del archivo**: un PDF escaneado
    es un PDF perfectamente válido. Lo que cambia es el consejo que hay que dar, y la pantalla
    lo distingue para ofrecer el camino que sí sirve.
    """


# --- Las piezas compartidas ------------------------------------------------


def _celda(valor) -> str:
    """Una celda, lista para meter en una tabla de Markdown.

    **La barra vertical se escapa.** Es el separador de columnas: un texto que la contenga
    —«Ancho | Alto», una ruta de Windows escrita a mano— parte la fila en dos y descuadra la
    tabla entera a partir de ahí. Y los saltos de línea se vuelven espacios, porque una celda
    de Markdown es de una sola línea y un salto la rompe igual.
    """
    if valor is None:
        return ""
    texto = str(valor).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(texto.split())


def _tabla(filas: list[list], *, encabezado: bool = True) -> list[str]:
    """Una tabla de Markdown con su fila de guiones.

    **Las filas desiguales se rellenan.** Una hoja de cálculo no garantiza que todas las filas
    tengan las mismas celdas —la última suele ser más corta—, y en Markdown una fila con menos
    columnas que el encabezado se pinta mal en unos visores y se descarta en otros.
    """
    if not filas:
        return []

    ancho = max(len(fila) for fila in filas)
    if ancho == 0:
        return []

    def linea(fila) -> str:
        celdas = [_celda(v) for v in fila] + [""] * (ancho - len(fila))
        return "| " + " | ".join(celdas) + " |"

    if encabezado:
        cabeza, resto = filas[0], filas[1:]
    else:
        # Sin encabezado propio, uno vacío: Markdown **exige** la fila de guiones, y sin ella
        # lo que se escribe no es una tabla sino un párrafo lleno de barras.
        cabeza, resto = [""] * ancho, filas

    return [linea(cabeza), "|" + "|".join([" --- "] * ancho) + "|", *(linea(f) for f in resto)]


def _recortar(filas: list[list]) -> tuple[list[list], str]:
    """Quita las filas y columnas vacías del borde, y avisa si hubo que cortar por tamaño.

    Una hoja «de la A1 a la Z500» con datos en tres columnas trae veintitrés columnas de
    `None`: convertirlas produce una tabla con veintitrés columnas en blanco que no ayuda a
    nadie a leer las tres que importan.
    """
    aviso = ""
    if len(filas) > TOPE_FILAS:
        filas = filas[:TOPE_FILAS]
        aviso = f"Se cortó en {TOPE_FILAS} filas: la hoja tenía más."

    # Por abajo y por la derecha: lo de arriba y lo de la izquierda puede ser deliberado.
    while filas and all(v is None or str(v).strip() == "" for v in filas[-1]):
        filas.pop()

    if not filas:
        return [], aviso

    ultima = 0
    for fila in filas:
        for i, valor in enumerate(fila):
            if valor is not None and str(valor).strip() != "":
                ultima = max(ultima, i)

    tope = min(ultima + 1, TOPE_COLUMNAS)
    if ultima + 1 > TOPE_COLUMNAS:
        aviso = (aviso + " " if aviso else "") + f"Se cortó en {TOPE_COLUMNAS} columnas."

    return [list(fila[:tope]) for fila in filas], aviso


# --- Hoja de cálculo -------------------------------------------------------


def de_excel(origen: str | Path) -> str:
    """Un libro de Excel, una hoja por sección.

    ## `data_only=True`, y lo que eso significa de verdad

    Pide **el último valor calculado** de cada fórmula, que es lo que Excel dejó guardado la
    última vez que abrió el archivo. Es lo correcto: nadie quiere leer `=SUMA(B2:B40)` en un
    correo, quiere leer `1.240`.

    Pero un libro que se generó con un programa y **nunca se abrió con Excel no tiene ese
    caché**, y entonces `openpyxl` devuelve `None` en todas las celdas con fórmula. Sin
    comprobarlo, la entrega sería una tabla perfecta llena de huecos, sin una sola pista de por
    qué. Así que si no sale nada se vuelve a abrir mirando las fórmulas y **se dice**.
    """
    import openpyxl

    origen = Path(origen)
    try:
        libro = openpyxl.load_workbook(origen, data_only=True, read_only=True)
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    partes: list[str] = [f"# {origen.stem}", ""]
    con_algo = False

    try:
        for hoja in libro.worksheets:
            filas = [list(fila) for fila in hoja.iter_rows(values_only=True)]
            filas, aviso = _recortar(filas)

            # **El título de la hoja va siempre**, tenga datos o no: que un libro traiga una
            # hoja vacía es información, y borrarla del resultado hace pensar que se perdió.
            partes.append(f"## {hoja.title}")
            partes.append("")

            if not filas:
                partes.extend(["*(hoja vacía)*", ""])
                continue

            con_algo = True
            partes.extend(_tabla(filas))
            if aviso:
                partes.extend(["", f"> {aviso}"])
            partes.append("")
    finally:
        libro.close()

    if not con_algo and _tiene_formulas(origen):
        raise SinTextoQueSacar(
            f"{origen.name} tiene fórmulas pero ningún resultado guardado, así que todas las "
            "celdas saldrían vacías. Ábrelo con Excel y vuelve a guardarlo: al guardar, Excel "
            "deja dentro el valor de cada fórmula."
        )

    return "\n".join(partes).rstrip() + "\n"


def _tiene_formulas(origen: Path) -> bool:
    """Si el libro trae fórmulas, mirando esta vez las fórmulas y no sus resultados.

    Solo se llama cuando ya se sabe que no salió nada: abrir el libro dos veces cuesta, y
    hacerlo siempre para una comprobación que casi nunca hace falta sería pagarlo siempre.
    """
    import openpyxl

    try:
        libro = openpyxl.load_workbook(origen, data_only=False, read_only=True)
    except Exception:
        return False
    try:
        for hoja in libro.worksheets:
            for fila in hoja.iter_rows(values_only=True):
                if any(isinstance(v, str) and v.startswith("=") for v in fila):
                    return True
    finally:
        libro.close()
    return False


# --- CSV -------------------------------------------------------------------


def de_csv(origen: str | Path) -> str:
    """Una tabla separada por lo que sea que la separe.

    **El separador se detecta, no se supone.** Un CSV exportado por un Excel en español usa
    `;`, porque la coma ya es el separador decimal; uno exportado por casi cualquier otra cosa
    usa `,`. Dar por hecho uno de los dos convierte la mitad de los archivos de esta oficina en
    una sola columna con todo el contenido dentro.
    """
    origen = Path(origen)
    crudo = _texto_de(origen)

    muestra = crudo[:8192]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        separador = dialecto.delimiter
    except csv.Error:
        # El olfateador falla con archivos de una sola columna, que no tienen separador que
        # detectar. Se cuenta a mano y se elige el que más aparezca; si no hay ninguno, da
        # igual cuál se use.
        separador = max(",;\t", key=muestra.count)

    filas = [list(f) for f in csv.reader(io.StringIO(crudo), delimiter=separador)]
    filas, aviso = _recortar(filas)
    if not filas:
        raise SinTextoQueSacar(f"{origen.name} no tiene ninguna fila con contenido.")

    partes = [f"# {origen.stem}", "", *_tabla(filas)]
    if aviso:
        partes.extend(["", f"> {aviso}"])
    return "\n".join(partes).rstrip() + "\n"


def _texto_de(origen: Path) -> str:
    """El contenido como texto, probando las codificaciones que salen por aquí.

    `utf-8-sig` primero porque el Excel en Windows escribe la marca de orden al principio, y
    leído como utf-8 a secas el primer encabezado sale con tres caracteres invisibles delante
    que nadie ve hasta que una búsqueda no encuentra la columna.
    """
    crudo = origen.read_bytes()
    for codificacion in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            continue
    # `latin-1` no falla nunca, así que esto es inalcanzable; queda por si cambia la lista.
    return crudo.decode("utf-8", errors="replace")


# --- HTML, que es también el motor del EPUB --------------------------------


def de_html(fuente: str | Path) -> str:
    """HTML a Markdown. Acepta una ruta o el propio HTML."""
    from markdownify import markdownify

    crudo = _texto_de(Path(fuente)) if isinstance(fuente, Path) else fuente
    # `ATX` es `# Título` y no el subrayado con guiones: es la forma que entiende todo, y la
    # única que funciona para los niveles del tres en adelante.
    texto = markdownify(crudo, heading_style="ATX", bullets="-")
    return _apretar(texto)


def _apretar(texto: str) -> str:
    """Deja como mucho una línea en blanco seguida.

    El HTML de un EPUB viene lleno de espacio entre etiquetas, y al convertirlo aparecen
    bloques de seis o siete líneas vacías que en un visor de Markdown se ven como agujeros.
    """
    lineas = [ln.rstrip() for ln in texto.splitlines()]
    salida: list[str] = []
    for linea in lineas:
        if not linea and salida and not salida[-1]:
            continue
        salida.append(linea)
    return "\n".join(salida).strip() + "\n"


# --- EPUB ------------------------------------------------------------------

#: Los espacios de nombres del formato. Son fijos por norma.
_NS_CONTENEDOR = "urn:oasis:names:tc:opendocument:xmlns:container"
_NS_OPF = "http://www.idpf.org/2007/opf"


def de_epub(origen: str | Path) -> str:
    """Un EPUB, en el orden en que se lee.

    Un EPUB es un ZIP con XHTML dentro, y **el orden importa**: los archivos dentro del ZIP
    están como al empaquetador le vino bien, y el orden de lectura lo dice el `spine` del
    manifiesto. Convertirlos en el orden del ZIP entrega los capítulos barajados.

    El XML se analiza con `defusedxml` y no con el de la biblioteca estándar: un EPUB es un
    archivo que llega de fuera, y el analizador de serie expande entidades —la «bomba de mil
    millones de risas»— sin pestañear.
    """
    from defusedxml import ElementTree as ET

    origen = Path(origen)
    try:
        with zipfile.ZipFile(origen) as zf:
            _vigilar_tamano(zf, origen.name)

            contenedor = ET.fromstring(zf.read("META-INF/container.xml"))
            nodo = contenedor.find(f".//{{{_NS_CONTENEDOR}}}rootfile")
            if nodo is None or not nodo.get("full-path"):
                raise ComposicionInvalida(f"{origen.name} no dice dónde está su índice.")

            ruta_opf = nodo.get("full-path")
            opf = ET.fromstring(zf.read(ruta_opf))
            base = Path(ruta_opf).parent

            # El manifiesto es «id → archivo»; el lomo es la lista de ids en orden de lectura.
            por_id = {
                elemento.get("id"): elemento.get("href")
                for elemento in opf.findall(f".//{{{_NS_OPF}}}manifest/{{{_NS_OPF}}}item")
            }
            orden = [
                elemento.get("idref")
                for elemento in opf.findall(f".//{{{_NS_OPF}}}spine/{{{_NS_OPF}}}itemref")
            ]

            titulo = _titulo_del_epub(opf) or origen.stem
            partes: list[str] = [f"# {titulo}", ""]

            for identificador in orden:
                href = por_id.get(identificador)
                if not href:
                    continue
                dentro = str((base / href).as_posix()).lstrip("./")
                try:
                    crudo = zf.read(dentro)
                except KeyError:
                    # Un capítulo que el índice nombra y el ZIP no trae. El libro sigue
                    # sirviendo: se salta y se sigue, que es mejor que no entregar nada.
                    continue
                trozo = de_html(crudo.decode("utf-8", errors="replace")).strip()
                if trozo:
                    partes.extend([trozo, ""])
    except zipfile.BadZipFile as fallo:
        raise ComposicionInvalida(f"{origen.name} no es un EPUB legible: {fallo}") from fallo
    except (KeyError, ET.ParseError) as fallo:
        raise ComposicionInvalida(f"{origen.name} no tiene la estructura de un EPUB.") from fallo

    texto = "\n".join(partes).strip()
    if texto == f"# {titulo}":
        raise SinTextoQueSacar(f"{origen.name} no trae ningún capítulo con texto.")
    return texto + "\n"


def _titulo_del_epub(opf) -> str:
    for etiqueta in ("{http://purl.org/dc/elements/1.1/}title",):
        nodo = opf.find(f".//{etiqueta}")
        if nodo is not None and (nodo.text or "").strip():
            return nodo.text.strip()
    return ""


def _vigilar_tamano(zf: zipfile.ZipFile, nombre: str) -> None:
    """Un ZIP de un megabyte puede traer gigabytes dentro. Se mira antes de leer nada."""
    total = sum(info.file_size for info in zf.infolist())
    if total > TOPE_DESCOMPRIMIDO:
        raise ComposicionInvalida(
            f"{nombre} contiene {total / 1_048_576:.0f} MB de texto descomprimido y el tope "
            f"son {TOPE_DESCOMPRIMIDO // 1_048_576} MB."
        )


# --- Word ------------------------------------------------------------------

#: Lo que sobrevive y lo que no, dicho en la pantalla antes de convertir.
NO_SOBREVIVE_DE_WORD = (
    "los cuadros de texto, las columnas, los encabezados y pies de página, "
    "las imágenes y el control de cambios"
)


def de_word(origen: str | Path) -> str:
    """Un `.docx`: títulos, listas, tablas y las negritas.

    **Se recorre el cuerpo en su orden**, y no primero los párrafos y luego las tablas. Es la
    diferencia entre un documento y sus trozos: `python-docx` ofrece `document.paragraphs` y
    `document.tables` por separado, y usarlos así entrega todas las tablas al final, fuera del
    apartado al que pertenecen.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    origen = Path(origen)
    try:
        documento = docx.Document(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    partes: list[str] = []
    for hijo in documento.element.body.iterchildren():
        etiqueta = hijo.tag.split("}")[-1]
        if etiqueta == "p":
            linea = _parrafo(Paragraph(hijo, documento))
            if linea is not None:
                # **Un renglón en blanco antes de cada título y de cada lista.**
                #
                # Markdown separa bloques por líneas vacías: un `## Resultados` pegado al
                # párrafo anterior lo entienden unos visores y otros no, y una lista pegada a
                # un párrafo se pinta como parte del párrafo en casi todos. Word no guarda
                # esas líneas porque para él la separación es el estilo, no el hueco.
                if _abre_bloque(linea) and partes and partes[-1]:
                    partes.append("")
                partes.append(linea)
        elif etiqueta == "tbl":
            tabla = Table(hijo, documento)
            filas = [[celda.text for celda in fila.cells] for fila in tabla.rows]
            if filas:
                partes.extend(["", *_tabla(filas), ""])

    texto = _apretar("\n".join(partes))
    if not texto.strip():
        raise SinTextoQueSacar(
            f"{origen.name} no tiene texto en el cuerpo. Si lo que ves está en cuadros de "
            "texto o en el encabezado, eso no se puede sacar."
        )
    return texto


def _abre_bloque(linea: str) -> bool:
    """Si esta línea empieza algo que en Markdown necesita un renglón en blanco delante."""
    return linea.startswith(("#", "- ", "1. ", "> "))


def _parrafo(parrafo) -> str | None:
    """Un párrafo con su forma. `None` si está vacío y no aporta nada."""
    texto = "".join(_trozo(t) for t in parrafo.runs).strip()
    estilo = (parrafo.style.name or "").lower()

    if not texto:
        # Un párrafo vacío es un salto deliberado. Se conserva uno; `_apretar` quita el resto.
        return ""

    if estilo.startswith("heading") or estilo.startswith("título") or estilo.startswith("titulo"):
        nivel = "".join(c for c in estilo if c.isdigit())
        return f"{'#' * min(int(nivel or 1), 6)} {texto}"
    if "list bullet" in estilo or "list paragraph" in estilo or "viñeta" in estilo:
        return f"- {texto}"
    if "list number" in estilo:
        return f"1. {texto}"
    if estilo.startswith("quote") or estilo.startswith("cita"):
        return f"> {texto}"
    return texto


def _trozo(run) -> str:
    """El texto de un fragmento con su negrita y su cursiva.

    Los asteriscos del texto original se escapan: un «3 * 4» dentro de una frase se comería el
    resto de la línea como si fuera el principio de una cursiva.

    **Y los espacios se quedan fuera de los asteriscos.** Word guarda muchísimo «Importante: »
    con el espacio dentro de la negrita, y `**Importante: **revisar` no es negrita en
    CommonMark: la norma exige que el cierre no venga precedido de un espacio, así que lo que
    se ve son cuatro asteriscos literales en mitad de la frase.
    """
    texto = run.text.replace("*", r"\*")
    nucleo = texto.strip()
    if not nucleo:
        return texto

    izquierda = texto[: len(texto) - len(texto.lstrip())]
    derecha = texto[len(texto.rstrip()) :]

    if run.bold and run.italic:
        marca = "***"
    elif run.bold:
        marca = "**"
    elif run.italic:
        marca = "*"
    else:
        return texto
    return f"{izquierda}{marca}{nucleo}{marca}{derecha}"


# --- PDF -------------------------------------------------------------------


def de_pdf(origen: str | Path) -> str:
    """El texto que el PDF ya tiene dentro. **Solo ese.**

    Un PDF escaneado es una imagen de un texto: no tiene texto, tiene píxeles. `pypdf` devuelve
    cadenas vacías sin quejarse, y escribir ese `.md` de cero bytes sería la peor respuesta
    posible porque parece que funcionó. Así que se cuenta lo que salió y, si no salió nada, se
    dice qué es lo que hace falta — que es OCR, y es otra herramienta.
    """
    from pypdf import PdfReader

    origen = Path(origen)
    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    if lector.is_encrypted:
        raise ComposicionInvalida(
            f"{origen.name} está protegido con contraseña. Quítasela primero con «Proteger PDF»."
        )

    partes: list[str] = [f"# {origen.stem}", ""]
    con_texto = 0
    for numero, hoja in enumerate(lector.pages, start=1):
        try:
            texto = (hoja.extract_text() or "").strip()
        except Exception:
            texto = ""
        if texto:
            con_texto += 1
            partes.extend([f"## Página {numero}", "", texto, ""])

    if not con_texto:
        # **Lo que sigue a «no se puede» importa más que el «no se puede».** Durante seis días
        # esto acabó en «que todavía no está», que es un callejón sin salida escrito en
        # pantalla. Ahora la salida existe, así que se nombra — y cuando en esta máquina no
        # esté Tesseract, se dice eso en vez de mandar a nadie a una pantalla apagada.
        from . import ocr

        # **Desde la cola esto corre en un proceso hijo sin Django**, y `sondar()` lee la
        # caché: sin ajustes cargados revienta con `ImproperlyConfigured`, y lo que tenía que
        # ser «es un escaneo» llegaba como un fallo del motor. Ahí se deja la frase general;
        # la del OCR la pone la pantalla, que sí sabe si Tesseract está.
        try:
            reconocimiento = ocr.sondar()
        except Exception:  # noqa: BLE001 - sin Django no hay caché que consultar
            reconocimiento = None

        if reconocimiento is None:
            salida = "Para sacarlo hace falta reconocer el texto primero."
        elif reconocimiento:
            salida = (
                "Pásalo antes por «Reconocer el texto de un escaneo» y vuelve con el PDF que salga."
            )
        else:
            salida = f"Para sacarlo hace falta reconocimiento óptico. {reconocimiento.motivo}"
        raise SinTextoQueSacar(
            f"{origen.name} no tiene texto: es un escaneo, o sea una imagen de un texto. {salida}"
        )

    salida = _apretar("\n".join(partes))
    if con_texto < len(lector.pages):
        mudas = len(lector.pages) - con_texto
        salida += f"\n> {mudas} de {len(lector.pages)} páginas no tenían texto y no salen aquí.\n"
    return salida


# --- La puerta -------------------------------------------------------------

_POR_EXTENSION = {
    ".xlsx": de_excel,
    ".xlsm": de_excel,
    ".csv": de_csv,
    ".docx": de_word,
    ".pdf": de_pdf,
    ".epub": de_epub,
    ".html": de_html,
    ".htm": de_html,
}


def a_markdown(origen: str | Path, *, destino: Path | None = None) -> Path:
    """Convierte lo que sea de `ORIGENES` y escribe el `.md` al lado.

    **La escritura es atómica**, como en el resto de la casa: se escribe un parcial y se
    renombra. Un fallo a mitad no deja un `.md` a medias con pinta de estar bien.
    """
    origen = Path(origen)
    convertir = _POR_EXTENSION.get(origen.suffix.lower())
    if convertir is None:
        conocidas = ", ".join(sorted(_POR_EXTENSION))
        raise ComposicionInvalida(
            f"De «{origen.suffix or origen.name}» no se saca Markdown. Se puede con: {conocidas}."
        )

    texto = convertir(origen)

    destino = Path(destino) if destino else origen.with_suffix(".md")
    parcial = destino.with_name(destino.name + ".parcial")
    parcial.write_text(texto, encoding="utf-8")
    parcial.replace(destino)
    return destino
