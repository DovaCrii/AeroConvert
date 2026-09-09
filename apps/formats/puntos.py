"""Archivos de puntos topográficos: PNEZD, PENZD y sus variantes.

Es el formato nativo de puntos de Civil 3D y el que llega por correo todas las semanas:
texto delimitado, una línea por punto, sin cabecera y sin CRS.

    P1,7318729.036,495279.406,3042.641,pr

## El fallo que este módulo existe para impedir

**El orden de las columnas no se declara en ninguna parte.** Cambia entre equipos de
topografía, entre oficinas y entre versiones de la misma libreta. Y las dos variantes más
comunes se diferencian en que dos columnas están intercambiadas:

- **PNEZD** — Punto, **N**orte, **E**ste, Cota, Descripción
- **PENZD** — Punto, **E**ste, **N**orte, Cota, Descripción

Leer un PNEZD como si fuera PENZD **no da error**. Da un archivo que se abre, que dibuja, y
en el que los puntos están a millones de metros de donde van. Con el archivo de arriba, esa
lectura los manda al Pacífico, a unos 6.800 km de la obra. Nadie se entera hasta que alguien
replantea sobre ese plano.

## Por qué esto se puede decidir y no hay que adivinarlo

Porque UTM acota los dos valores, y los acota de forma **distinta**:

- El **este** de una zona UTM va de 166.000 a 834.000 m. Una zona tiene 6° de ancho y su
  meridiano central está en el falso este de 500.000; fuera de esa banda no hay zona.
- El **norte** llega hasta 10.000.000 m, y en el hemisferio sur es justo donde vive: el
  falso norte de 10.000.000 pone a Chile en torno a los 6–7 millones.

Así que un valor de 7.318.729 **no puede ser un este**. No es que sea improbable: no cabe.
Eso convierte la detección en una medida y no en una corazonada, y es lo que permite decir
«tu archivo es PNEZD» con la cara seria.

Cuando las dos columnas caen dentro del rango de estes -- que pasa, y en el hemisferio norte
pasa a menudo -- **no se decide**. Se marca ambiguo y se pregunta. La regla de la familia es
la de `AeroBim/docs/NUBES_DE_PUNTOS.md`: adivinarlo es peor que no tenerlo.

## Y por qué el lector es nuestro y no de OGR

OGR lee CSV, pero para leerlo hay que decirle **ya** qué columna es la X y cuál la Y. Es
decir, hay que haber resuelto antes justo el problema difícil. Esta lectura ocurre en la
inspección, que es antes de elegir destino y antes de tocar nada.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

#: Límites del este de una zona UTM, en metros. Es el valor que decide el orden.
#:
#: Se redondean hacia fuera respecto de los 166.000–834.000 teóricos para no rechazar un
#: punto legítimo justo en el borde de la zona.
ESTE_MINIMO_M = 100_000.0
ESTE_MAXIMO_M = 900_000.0

#: El norte llega a 10.000.000 en el hemisferio sur por el falso norte.
NORTE_MAXIMO_M = 10_000_000.0

#: Cuántos puntos se guardan para la vista previa. El archivo puede traer millones y la
#: previsualización es un dibujo de 600 px: más puntos no se ven y sí se pagan.
MUESTRA_MAXIMA = 3_000

#: Cuántas filas se miran para deducir la estructura. Con 50 sobra, y evita recorrer dos
#: veces un archivo de un millón de líneas.
FILAS_PARA_DEDUCIR = 50

#: Delimitadores que se prueban.
DELIMITADORES = (",", ";", "\t", " ")

# --- Órdenes de columna ------------------------------------------------------
#: Qué papel juega cada columna. `p` punto, `n` norte, `e` este, `z` cota, `d` descripción.
ORDENES: dict[str, tuple[str, ...]] = {
    "pnezd": ("p", "n", "e", "z", "d"),
    "penzd": ("p", "e", "n", "z", "d"),
    "pnez": ("p", "n", "e", "z"),
    "penz": ("p", "e", "n", "z"),
    "nezd": ("n", "e", "z", "d"),
    "enzd": ("e", "n", "z", "d"),
    "nez": ("n", "e", "z"),
    "enz": ("e", "n", "z"),
}

NOMBRES_DE_ORDEN = {
    "pnezd": "PNEZD — punto, norte, este, cota, descripción",
    "penzd": "PENZD — punto, este, norte, cota, descripción",
    "pnez": "PNEZ — punto, norte, este, cota",
    "penz": "PENZ — punto, este, norte, cota",
    "nezd": "NEZD — norte, este, cota, descripción",
    "enzd": "ENZD — este, norte, cota, descripción",
    "nez": "NEZ — norte, este, cota",
    "enz": "ENZ — este, norte, cota",
}

#: Cómo se decidió el orden.
CERTEZA_RANGO = "rango-utm"
CERTEZA_DECLARADA = "declarado"
CERTEZA_AMBIGUA = "ambiguo"

ETIQUETAS_CERTEZA = {
    CERTEZA_RANGO: "deducido del rango UTM de las coordenadas",
    CERTEZA_DECLARADA: "elegido a mano",
    CERTEZA_AMBIGUA: "no se puede deducir: hay que elegirlo a mano",
}


class NoEsArchivoDePuntos(Exception):
    """No se parece a un archivo de puntos delimitado."""


@dataclass(frozen=True)
class Punto:
    identificador: str
    norte_m: float
    este_m: float
    cota_m: float
    descripcion: str = ""


@dataclass(frozen=True)
class CabeceraPuntos:
    """Lo que se sabe del archivo tras leerlo. Aquí sí se lee entero: es texto."""

    orden: str
    certeza: str
    delimitador: str
    columnas: int
    tiene_encabezado: bool
    puntos_leidos: int
    #: Líneas que no se pudieron interpretar. Que sean pocas es normal; que sean muchas
    #: significa que el orden elegido no es el del archivo.
    lineas_ignoradas: int
    #: (norte, este, cota)
    minimo: tuple[float, float, float]
    maximo: tuple[float, float, float]
    #: Una muestra para dibujar, no el archivo entero. Ver `MUESTRA_MAXIMA`.
    muestra: tuple[Punto, ...]
    #: El otro orden posible, cuando las dos columnas caben en el rango de estes.
    orden_alternativo: str = ""

    @property
    def nombre_del_orden(self) -> str:
        return NOMBRES_DE_ORDEN.get(self.orden, self.orden.upper())

    @property
    def nombre_del_alternativo(self) -> str:
        return NOMBRES_DE_ORDEN.get(self.orden_alternativo, "")

    @property
    def etiqueta_certeza(self) -> str:
        return ETIQUETAS_CERTEZA[self.certeza]

    @property
    def hay_que_preguntar(self) -> bool:
        return self.certeza == CERTEZA_AMBIGUA

    @property
    def extension_m(self) -> tuple[float, float, float]:
        return (
            self.maximo[0] - self.minimo[0],
            self.maximo[1] - self.minimo[1],
            self.maximo[2] - self.minimo[2],
        )

    @property
    def centro(self) -> tuple[float, float]:
        """(norte, este) del centro de la nube de puntos."""
        return (
            (self.minimo[0] + self.maximo[0]) / 2,
            (self.minimo[1] + self.maximo[1]) / 2,
        )

    @property
    def distancia_si_se_invierte_m(self) -> float:
        """A qué distancia caerían los puntos leyendo norte y este al revés.

        Es la cifra que hace entender el problema sin explicarlo: con el archivo del cruce
        minero son 9.649 km. Un «revisa el orden de columnas» no mueve a nadie; un «si te
        equivocas, esto acaba fuera del continente» sí.
        """
        norte, este = self.centro
        return math.hypot(este - norte, norte - este)


# --- Lectura -----------------------------------------------------------------


def _a_numero(texto: str) -> float | None:
    """El valor de la celda, o `None` si no es un número.

    Acepta la coma decimal: un Excel en español la escribe así, y entonces el delimitador
    del archivo es el punto y coma. Solo se sustituye cuando **no** hay punto, para no
    destrozar un `1,234.56`.
    """
    texto = texto.strip().strip('"').replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _partir(linea: str, delimitador: str) -> list[str]:
    if delimitador == " ":
        return linea.split()
    return [celda.strip() for celda in linea.split(delimitador)]


def _elegir_delimitador(lineas: list[str]) -> str:
    """El delimitador que parte las líneas de forma **consistente y en varias columnas**.

    Se puntúa por consistencia y no por frecuencia. Una descripción con espacios --
    `pr control 3` -- hace que el espacio gane por número de apariciones y parta cada línea
    en un número distinto de trozos, que es exactamente la señal de que no es el bueno.
    """
    mejor, mejor_puntos = "", -1.0
    for delimitador in DELIMITADORES:
        cuentas = [len(_partir(linea, delimitador)) for linea in lineas]
        moda = max(set(cuentas), key=cuentas.count)
        if moda < 3:
            continue
        consistencia = cuentas.count(moda) / len(cuentas)
        # La consistencia manda; a igualdad, más columnas es mejor lectura.
        puntos = consistencia * 100 + moda
        if puntos > mejor_puntos:
            mejor, mejor_puntos = delimitador, puntos

    if not mejor:
        raise NoEsArchivoDePuntos(
            "Ninguna forma de partir las líneas da tres columnas o más. Esto no parece un "
            "archivo de puntos delimitado."
        )
    return mejor


def _es_encabezado(celdas: list[str]) -> bool:
    """`True` si la fila no trae ni dos números: entonces son rótulos."""
    return sum(1 for celda in celdas if _a_numero(celda) is not None) < 2


def _fila_utilizable(fila: list[str]) -> bool:
    """`True` si la fila tiene pinta de traer un punto: tres columnas y tres números.

    Filtrar por filas **antes** de mirar las columnas no es un detalle. Exigir que una
    columna sea numérica en todas las filas es lo correcto —una descripción donde alguien
    escribió `3` una vez no es una coordenada— pero aplicado sobre filas rotas convierte una
    sola línea mala en «este archivo no tiene columnas numéricas», y el archivo entero deja
    de leerse. Un `P6,esto,no,son,numeros` al final de la libreta es de lo más normal.
    """
    return len(fila) >= 3 and sum(1 for celda in fila if _a_numero(celda) is not None) >= 3


def _columnas_numericas(filas: list[list[str]]) -> list[int]:
    """Los índices de columna que son numéricos en **todas** las filas utilizables."""
    ancho = min(len(fila) for fila in filas)
    return [
        indice
        for indice in range(ancho)
        if all(_a_numero(fila[indice]) is not None for fila in filas)
    ]


@dataclass(frozen=True)
class _Estructura:
    """Qué columna es qué, antes de saber cuál de las dos coordenadas es el norte."""

    hay_punto: bool
    hay_descripcion: bool
    #: Las tres columnas de coordenadas, en el orden en que aparecen en el archivo.
    coordenadas: tuple[int, int, int]
    columna_punto: int | None
    columna_descripcion: int | None


def _estructura(filas: list[list[str]], numericas: list[int]) -> _Estructura:
    """Separa identificador, coordenadas y descripción.

    La regla que lo decide es de conteo, y por eso no falla: **las coordenadas son tres**.
    Una cuarta columna numérica no puede ser una coordenada, así que es el número de punto.
    Mirar la magnitud en vez del conteo se rompe cerca del ecuador, donde un norte legítimo
    puede valer 50.000 y parecer un identificador.
    """
    if len(numericas) < 3:
        raise NoEsArchivoDePuntos(
            f"Solo {len(numericas)} columna(s) son numéricas en todas las filas, y hacen "
            "falta tres: dos coordenadas y una cota."
        )

    ancho = min(len(fila) for fila in filas)
    columna_punto: int | None = None

    if 0 not in numericas:
        # `P1`, `EST-4`: no es un número, así que es el identificador.
        columna_punto = 0
    elif len(numericas) >= 4:
        # Hay una numérica de más, y las coordenadas son tres.
        columna_punto = 0

    coordenadas = [i for i in numericas if i != columna_punto][:3]

    columna_descripcion = None
    if ancho - 1 not in numericas and (ancho - 1) != columna_punto:
        columna_descripcion = ancho - 1

    return _Estructura(
        hay_punto=columna_punto is not None,
        hay_descripcion=columna_descripcion is not None,
        coordenadas=(coordenadas[0], coordenadas[1], coordenadas[2]),
        columna_punto=columna_punto,
        columna_descripcion=columna_descripcion,
    )


def _puede_ser_este(valores: list[float]) -> bool:
    return all(ESTE_MINIMO_M <= abs(valor) <= ESTE_MAXIMO_M for valor in valores)


def _codigo_de_orden(primero: str, estructura: _Estructura) -> str:
    segundo = "e" if primero == "n" else "n"
    partes = (["p"] if estructura.hay_punto else []) + [primero, segundo, "z"]
    if estructura.hay_descripcion:
        partes.append("d")
    return "".join(partes)


def _decidir_orden(filas: list[list[str]], estructura: _Estructura) -> tuple[str, str, str]:
    """Devuelve `(orden, certeza, orden_alternativo)`.

    El razonamiento está en el docstring del módulo: manda el rango del este, porque es el
    que UTM acota por los dos lados.
    """
    columna_a, columna_b = estructura.coordenadas[0], estructura.coordenadas[1]
    valores_a = [_a_numero(fila[columna_a]) or 0.0 for fila in filas]
    valores_b = [_a_numero(fila[columna_b]) or 0.0 for fila in filas]

    a_cabe_como_este = _puede_ser_este(valores_a)
    b_cabe_como_este = _puede_ser_este(valores_b)

    if b_cabe_como_este and not a_cabe_como_este:
        # A no cabe como este, luego A es el norte. Es el caso del cruce minero.
        return _codigo_de_orden("n", estructura), CERTEZA_RANGO, ""
    if a_cabe_como_este and not b_cabe_como_este:
        return _codigo_de_orden("e", estructura), CERTEZA_RANGO, ""

    # Las dos caben, o ninguna. No se decide: se pregunta, y se dice cuál es la otra opción.
    return (
        _codigo_de_orden("n", estructura),
        CERTEZA_AMBIGUA,
        _codigo_de_orden("e", estructura),
    )


def iterar(ruta: str | Path, *, orden: str = "") -> Iterator[Punto]:
    """Recorre **todos** los puntos, uno a uno, sin quedarse con ninguno.

    `leer()` guarda solo `muestra`, que está recortada a `MUESTRA_MAXIMA` para poder
    dibujarla. Quien tiene que **escribir** el archivo entero necesita esto: una libreta de
    obra grande trae cientos de miles de puntos, y materializarlos todos en una lista de
    dataclasses para copiarlos a un XML es gastar memoria en algo que se usa una vez.

    La detección se hace con las primeras líneas y luego se recorre el archivo desde el
    principio, así que el archivo se abre dos veces y no se carga entero nunca.
    """
    ruta = Path(ruta)
    if orden and orden not in ORDENES:
        raise NoEsArchivoDePuntos(f"«{orden}» no es un orden conocido.")

    cabeza = _primeras_lineas(ruta, FILAS_PARA_DEDUCIR + 1)
    if not cabeza:
        raise NoEsArchivoDePuntos("El archivo no tiene ninguna línea con contenido.")

    delimitador = _elegir_delimitador(cabeza)
    filas = [_partir(linea, delimitador) for linea in cabeza]
    tiene_encabezado = len(filas) > 1 and _es_encabezado(filas[0])
    cuerpo = filas[1:] if tiene_encabezado else filas

    para_deducir = [fila for fila in cuerpo if _fila_utilizable(fila)]
    if not para_deducir:
        raise NoEsArchivoDePuntos("Ninguna línea trae tres columnas numéricas.")

    estructura = _estructura(para_deducir, _columnas_numericas(para_deducir))
    if orden:
        codigo = orden
        estructura = _con_orden_declarado(estructura, orden)
    else:
        codigo, _certeza, _alternativo = _decidir_orden(para_deducir, estructura)

    columna = _columnas_de(codigo, estructura)

    with open(ruta, encoding="utf-8-sig", errors="replace") as archivo:
        # Se cuentan las líneas **con contenido**, no las del archivo: si empieza con una
        # línea en blanco, el encabezado no está en la posición cero y saltarla por número
        # de línea dejaría el rótulo dentro de los datos.
        con_contenido = 0
        for linea in archivo:
            if not linea.strip():
                continue
            con_contenido += 1
            if tiene_encabezado and con_contenido == 1:
                continue
            punto = _punto_de(_partir(linea.rstrip("\n"), delimitador), columna, estructura)
            if punto is not None:
                yield punto


def _primeras_lineas(ruta: Path, cuantas: int) -> list[str]:
    """Las primeras líneas con contenido, sin leer el archivo entero."""
    try:
        with open(ruta, encoding="utf-8-sig", errors="replace") as archivo:
            recogidas = []
            for linea in archivo:
                if linea.strip():
                    recogidas.append(linea.rstrip("\n"))
                if len(recogidas) >= cuantas:
                    break
            return recogidas
    except OSError as fallo:  # pragma: no cover - lo filtra la inspección antes
        raise NoEsArchivoDePuntos(str(fallo)) from fallo


def leer(ruta: str | Path, *, orden: str = "") -> CabeceraPuntos:
    """Lee el archivo y deduce su estructura.

    `orden` fuerza uno de `ORDENES` y salta la deducción. Es lo que se usa cuando la
    detección salió ambigua y alguien lo eligió a mano.
    """
    ruta = Path(ruta)
    if orden and orden not in ORDENES:
        raise NoEsArchivoDePuntos(f"«{orden}» no es un orden conocido.")

    try:
        texto = ruta.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as fallo:  # pragma: no cover - lo filtra la inspección antes
        raise NoEsArchivoDePuntos(str(fallo)) from fallo

    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    if not lineas:
        raise NoEsArchivoDePuntos("El archivo no tiene ninguna línea con contenido.")

    delimitador = _elegir_delimitador(lineas)
    filas = [_partir(linea, delimitador) for linea in lineas]

    tiene_encabezado = len(filas) > 1 and _es_encabezado(filas[0])
    if tiene_encabezado:
        filas = filas[1:]

    para_deducir = [fila for fila in filas[:FILAS_PARA_DEDUCIR] if _fila_utilizable(fila)]
    if not para_deducir:
        raise NoEsArchivoDePuntos(
            "Ninguna de las primeras líneas trae tres columnas numéricas. Esto no parece "
            "un archivo de puntos."
        )

    estructura = _estructura(para_deducir, _columnas_numericas(para_deducir))

    if orden:
        codigo, certeza, alternativo = orden, CERTEZA_DECLARADA, ""
        estructura = _con_orden_declarado(estructura, orden)
    else:
        codigo, certeza, alternativo = _decidir_orden(para_deducir, estructura)

    puntos, ignoradas, muestra = _extraer(filas, codigo, estructura)
    if not puntos:
        raise NoEsArchivoDePuntos(
            f"Con el orden {codigo.upper()} no se pudo interpretar ninguna línea."
        )

    return CabeceraPuntos(
        orden=codigo,
        certeza=certeza,
        delimitador=delimitador,
        columnas=len(ORDENES[codigo]),
        tiene_encabezado=tiene_encabezado,
        puntos_leidos=len(puntos),
        lineas_ignoradas=ignoradas,
        minimo=(
            min(p.norte_m for p in puntos),
            min(p.este_m for p in puntos),
            min(p.cota_m for p in puntos),
        ),
        maximo=(
            max(p.norte_m for p in puntos),
            max(p.este_m for p in puntos),
            max(p.cota_m for p in puntos),
        ),
        muestra=muestra,
        orden_alternativo=alternativo,
    )


def _con_orden_declarado(estructura: _Estructura, orden: str) -> _Estructura:
    """Ajusta la estructura a lo que dice un orden elegido a mano.

    Quien elige `nez` sobre un archivo que parecía traer identificador está diciendo que la
    primera columna es una coordenada, y hay que hacerle caso: es la salida cuando la
    deducción se equivoca.
    """
    papeles = ORDENES[orden]
    hay_punto = "p" in papeles
    if hay_punto == estructura.hay_punto:
        return estructura

    if hay_punto:
        coordenadas = tuple(i + 1 for i in estructura.coordenadas[:3])
        columna_punto: int | None = 0
    else:
        coordenadas = (0, *estructura.coordenadas[:2])
        columna_punto = None

    return _Estructura(
        hay_punto=hay_punto,
        hay_descripcion="d" in papeles,
        coordenadas=coordenadas,  # type: ignore[arg-type]
        columna_punto=columna_punto,
        columna_descripcion=estructura.columna_descripcion,
    )


@dataclass(frozen=True)
class CamposOgr:
    """Cómo se le explica este archivo a OGR, sin leerlo entero.

    El controlador CSV de OGR construye la geometría con `X_POSSIBLE_NAMES` y
    `Y_POSSIBLE_NAMES`, y para eso hay que darle **nombres de campo**. Con `HEADERS=NO` los
    nombres son `field_1`, `field_2`... y con encabezado son los rótulos del archivo.

    Existe aparte de `CabeceraPuntos` porque el motor la necesita al construir el comando y
    ahí no hace falta haber leído el millón de líneas: con las primeras cincuenta se sabe
    todo lo que el `argv` tiene que decir.
    """

    delimitador: str
    tiene_encabezado: bool
    orden: str
    campo_este: str
    campo_norte: str
    campo_cota: str
    campo_punto: str = ""
    campo_descripcion: str = ""

    @property
    def separador_ogr(self) -> str:
        """El valor de `-oo SEPARATOR=`. OGR los nombra, no los toma literales."""
        return {",": "COMMA", ";": "SEMICOLON", "\t": "TAB", " ": "SPACE"}[self.delimitador]

    @property
    def puede_renombrar(self) -> bool:
        """Solo con `HEADERS=NO`, donde los nombres son nuestros y no del archivo.

        Con encabezado los rótulos ya los puso quien hizo el archivo, y renombrarlos sería
        cambiarle los nombres a los datos de otro.
        """
        return not self.tiene_encabezado


def campos_ogr(ruta: str | Path, *, orden: str = "") -> CamposOgr:
    """Traduce la estructura del archivo a nombres de campo de OGR."""
    ruta = Path(ruta)
    if orden and orden not in ORDENES:
        raise NoEsArchivoDePuntos(f"«{orden}» no es un orden conocido.")

    try:
        texto = ruta.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as fallo:
        raise NoEsArchivoDePuntos(str(fallo)) from fallo

    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    if not lineas:
        raise NoEsArchivoDePuntos("El archivo no tiene ninguna línea con contenido.")

    delimitador = _elegir_delimitador(lineas[: FILAS_PARA_DEDUCIR + 1])
    filas = [_partir(linea, delimitador) for linea in lineas]

    tiene_encabezado = len(filas) > 1 and _es_encabezado(filas[0])
    rotulos = filas[0] if tiene_encabezado else []
    cuerpo = filas[1:] if tiene_encabezado else filas

    para_deducir = [fila for fila in cuerpo[:FILAS_PARA_DEDUCIR] if _fila_utilizable(fila)]
    if not para_deducir:
        raise NoEsArchivoDePuntos("Ninguna línea trae tres columnas numéricas.")

    estructura = _estructura(para_deducir, _columnas_numericas(para_deducir))
    if orden:
        estructura = _con_orden_declarado(estructura, orden)
        codigo = orden
    else:
        codigo, _certeza, _alternativo = _decidir_orden(para_deducir, estructura)

    papeles = ORDENES[codigo]
    solo_coordenadas = [papel for papel in papeles if papel in ("n", "e", "z")]
    indice = {
        papel: estructura.coordenadas[posicion] for posicion, papel in enumerate(solo_coordenadas)
    }

    def nombre(columna: int) -> str:
        if tiene_encabezado and columna < len(rotulos) and rotulos[columna].strip():
            return rotulos[columna].strip()
        return f"field_{columna + 1}"

    return CamposOgr(
        delimitador=delimitador,
        tiene_encabezado=tiene_encabezado,
        orden=codigo,
        campo_este=nombre(indice["e"]),
        campo_norte=nombre(indice["n"]),
        campo_cota=nombre(indice["z"]),
        campo_punto=(
            nombre(estructura.columna_punto) if estructura.columna_punto is not None else ""
        ),
        campo_descripcion=(
            nombre(estructura.columna_descripcion)
            if estructura.columna_descripcion is not None
            else ""
        ),
    )


def _columnas_de(orden: str, estructura: _Estructura) -> dict[str, int]:
    """Qué columna del archivo lleva el norte, el este y la cota, para ese orden."""
    solo_coordenadas = [papel for papel in ORDENES[orden] if papel in ("n", "e", "z")]
    return {
        papel: estructura.coordenadas[posicion] for posicion, papel in enumerate(solo_coordenadas)
    }


def _punto_de(fila: list[str], columna: dict[str, int], estructura: _Estructura) -> Punto | None:
    """Una fila convertida en punto, o `None` si no se pudo interpretar.

    Vive suelta porque la usan los dos caminos —`leer()`, que se queda con todo para poder
    dar mínimos y máximos, e `iterar()`, que no se queda con nada— y tener el criterio de
    «qué es una fila válida» escrito dos veces es como se desincronizan.
    """
    if max(columna.values()) >= len(fila):
        return None

    norte = _a_numero(fila[columna["n"]])
    este = _a_numero(fila[columna["e"]])
    cota = _a_numero(fila[columna["z"]])
    if norte is None or este is None or cota is None:
        return None

    identificador = ""
    if estructura.columna_punto is not None and estructura.columna_punto < len(fila):
        identificador = fila[estructura.columna_punto].strip()

    descripcion = ""
    if estructura.columna_descripcion is not None and estructura.columna_descripcion < len(fila):
        descripcion = fila[estructura.columna_descripcion].strip()

    return Punto(
        identificador=identificador,
        norte_m=norte,
        este_m=este,
        cota_m=cota,
        descripcion=descripcion,
    )


def _extraer(
    filas: list[list[str]], orden: str, estructura: _Estructura
) -> tuple[list[Punto], int, tuple[Punto, ...]]:
    """Convierte las filas en puntos. Devuelve `(puntos, ignoradas, muestra)`."""
    columna = _columnas_de(orden, estructura)

    puntos: list[Punto] = []
    ignoradas = 0

    for fila in filas:
        punto = _punto_de(fila, columna, estructura)
        if punto is None:
            ignoradas += 1
            continue
        puntos.append(punto)

    # La muestra se toma repartida por todo el archivo y no de la cabeza: los primeros 3.000
    # puntos de un levantamiento son una esquina de la obra, y dibujarlos daría una vista
    # previa que parece correcta y no representa nada.
    paso = math.ceil(len(puntos) / MUESTRA_MAXIMA) if len(puntos) > MUESTRA_MAXIMA else 1
    return puntos, ignoradas, tuple(puntos[::paso][:MUESTRA_MAXIMA])
