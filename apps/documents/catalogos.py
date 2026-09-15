"""Catálogos de tubería: una base de Access y una hoja de cálculo, en los dos sentidos.

## Qué es esto de verdad, que no es «Excel a Access»

El archivo que originó esto —`HDPE_PE100_PN16.mdb`— es un **catálogo de especificación de
AutoCAD Plant 3D**: nueve tablas (`PIPE`, `ELBOW`, `TEE`, `FLANGE`, `REDUCER`, `CROSSES`,
`GASKET`, `BOLT`, `MISC_FIT`), 481 filas, y entre 28 y 52 columnas por tabla con nombres como
`EC_CLASS_NAME`, `PIECE_MARK`, `END_COND_1` o `SKT_DPTH_M`.

Un conversor genérico de hoja a base de datos **no sirve para esto**: produciría una tabla con
los nombres que traiga el Excel, y Plant 3D no abriría el resultado. Lo que hace falta es
rellenar **un esquema que ya existe**, y por eso la escritura pide siempre un `.mdb` de
plantilla.

## Por qué la exportación va primero

Porque **nadie escribe cincuenta y dos columnas desde cero**. El camino real es: sacar a Excel
el catálogo que ya se tiene, cambiar los diámetros o los espesores que hagan falta, y volver a
meterlo. La dirección Excel → `.mdb` sin un catálogo de partida es un caso que casi no existe.

## Solo en Windows, y dicho en vez de escondido

El trabajo lo hace **ACE**, el motor de bases de datos de Microsoft, a través de ODBC. En Linux
no existe, así que en el servidor estas dos herramientas salen **apagadas con su motivo**,
igual que Word y Excel a PDF. La regla de la casa: se sondea, no se declara.

Medido en la estación de trabajo el 2026-09-15: el controlador `Microsoft Access Driver
(*.mdb, *.accdb)` de 64 bits crea bases Jet 4, crea tablas e inserta filas. **No hace falta
licencia de Access**: ACE es un redistribuible gratuito.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from django.core.cache import cache

from .composicion import ComposicionInvalida

SEGUNDOS_DE_CACHE = 600
CLAVE_DE_CACHE = "documentos:catalogos"

#: Tope de filas por tabla. Un catálogo de tubería completo anda por las quinientas; diez mil
#: ya no es un catálogo y armar la hoja se lleva la memoria antes de escribir nada.
TOPE_FILAS = 10_000

#: Lo que Excel admite en el nombre de una hoja. Los cinco caracteres prohibidos son de Excel,
#: no nuestros, y una tabla de Access sí puede llevarlos.
PROHIBIDOS_EN_HOJA = re.compile(r"[\[\]:*?/\\]")

#: Un nombre de tabla o de columna que se puede meter en una consulta sin miedo.
#:
#: **No es paranoia de manual: el `.mdb` viene de fuera.** Los nombres salen del catálogo que
#: alguien sube, se interpolan entre corchetes —`SELECT * FROM [PIPE]`— y un corchete de cierre
#: dentro del nombre se sale del delimitador. Access no tiene consultas con parámetros para
#: identificadores, así que la única defensa es no dejar pasar el nombre.
NOMBRE_SEGURO = re.compile(r"^[A-Za-z_][A-Za-z0-9_ #$]{0,63}$")


def _seguro(nombre: str, que_es: str) -> str:
    """El nombre, si se puede meter en una consulta. Si no, se para aquí."""
    if not NOMBRE_SEGURO.match(nombre):
        raise ComposicionInvalida(
            f"El catálogo trae un{'a' if que_es == 'tabla' else ''} {que_es} con un nombre que "
            f"no se puede usar: «{nombre[:40]}»."
        )
    return nombre


@dataclass(frozen=True)
class Disponible:
    """Si esta máquina sabe abrir un `.mdb`. Con el motivo cuando no."""

    controlador: str = ""
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.controlador)


@dataclass(frozen=True)
class Columna:
    nombre: str
    #: El tipo tal y como lo declara ODBC, para poder recrearlo igual.
    tipo: str
    tamano: int = 0


@dataclass(frozen=True)
class Tabla:
    nombre: str
    columnas: tuple[Columna, ...] = field(default_factory=tuple)
    filas: int = 0


def sondar(*, recordar: bool = True) -> Disponible:
    """Si hay controlador de Access. Cacheado, como las demás sondas.

    **Se busca el de `.mdb` explícitamente.** Hay varios controladores de Microsoft con la
    palabra «Access» en el nombre —el de texto, el de dBASE— y ninguno de los dos abre una base
    de Access. Buscar por «Access» a secas daría disponible en una máquina donde no se puede
    hacer nada.
    """
    if recordar:
        guardado = cache.get(CLAVE_DE_CACHE)
        if guardado is not None:
            return guardado

    estado = _mirar()
    if recordar:
        cache.set(CLAVE_DE_CACHE, estado, SEGUNDOS_DE_CACHE)
    return estado


def _mirar() -> Disponible:
    try:
        import pyodbc
    except ImportError:
        return Disponible(
            motivo="Esta máquina no tiene el conector de bases de datos de Microsoft.",
            sugerencia=(
                "Los catálogos son bases de Access y solo se abren en Windows. Desde un puesto "
                "de trabajo sí se puede."
            ),
        )

    for nombre in pyodbc.drivers():
        if "Access Driver" in nombre and ".mdb" in nombre:
            return Disponible(controlador=nombre)

    return Disponible(
        motivo="No hay ningún controlador de Access instalado.",
        sugerencia=(
            "Se instala con «Microsoft Access Database Engine», que es gratuito y no necesita "
            "licencia de Access. Tiene que ser de la misma arquitectura que Python — aquí, 64 bits."
        ),
    )


def _cadena(ruta: Path, *, crear: bool = False) -> str:
    controlador = sondar().controlador
    if not controlador:
        raise ComposicionInvalida(sondar().motivo)
    if crear:
        return f"DRIVER={{{controlador}}};DBQ={ruta};"
    return f"DRIVER={{{controlador}}};DBQ={ruta};ReadOnly=1;"


def esquema(origen: str | Path) -> list[Tabla]:
    """Las tablas de usuario del catálogo, con sus columnas y cuántas filas tiene cada una.

    **Se saltan las tablas del sistema.** Access guarda las suyas con el prefijo `MSys`, y
    exportarlas entregaría cuatro hojas de tripas del motor entre las nueve que interesan.
    """
    import pyodbc

    origen = Path(origen)
    if not origen.exists():
        raise ComposicionInvalida(f"No está {origen.name}.")

    try:
        conexion = pyodbc.connect(_cadena(origen), autocommit=True)
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {_limpiar(fallo)}") from fallo

    tablas: list[Tabla] = []
    try:
        cursor = conexion.cursor()
        nombres = [
            fila.table_name
            for fila in cursor.tables(tableType="TABLE")
            if not fila.table_name.startswith("MSys")
        ]
        for nombre in nombres:
            columnas = tuple(
                Columna(nombre=c.column_name, tipo=c.type_name, tamano=c.column_size or 0)
                for c in conexion.cursor().columns(table=nombre)
            )
            seguro = _seguro(nombre, "tabla")
            conteo = conexion.cursor().execute(f"SELECT COUNT(*) FROM [{seguro}]").fetchone()[0]  # nosec B608
            tablas.append(Tabla(nombre=nombre, columnas=columnas, filas=conteo))
    finally:
        conexion.close()

    if not tablas:
        raise ComposicionInvalida(f"{origen.name} no tiene ninguna tabla que exportar.")
    return tablas


def a_excel(origen: str | Path, *, destino: Path | None = None) -> Path:
    """El catálogo entero a una hoja de cálculo, **una hoja por tabla**.

    Es la mitad que más se usa: se saca lo que ya hay, se edita cómodo, y se vuelve a meter con
    `desde_excel`. Una tabla vacía **se exporta igual, con sus encabezados**: es la plantilla
    para rellenarla, y omitirla obligaría a inventarse los nombres de las columnas.
    """
    import openpyxl

    origen = Path(origen)
    tablas = esquema(origen)
    destino = Path(destino) if destino else origen.with_suffix(".xlsx")

    import pyodbc

    conexion = pyodbc.connect(_cadena(origen), autocommit=True)
    libro = openpyxl.Workbook()
    libro.remove(libro.active)

    usados: set[str] = set()
    try:
        for tabla in tablas:
            hoja = libro.create_sheet(_nombre_de_hoja(tabla.nombre, usados))
            hoja.append([c.nombre for c in tabla.columnas])
            # La fila de encabezados fija, para que al desplazarse por 126 filas se siga
            # sabiendo qué columna es cuál. Con 52 columnas, esto no es un adorno.
            hoja.freeze_panes = "A2"

            cursor = conexion.cursor().execute(f"SELECT * FROM [{_seguro(tabla.nombre, 'tabla')}]")  # nosec B608
            for numero, fila in enumerate(cursor, start=1):
                if numero > TOPE_FILAS:
                    raise ComposicionInvalida(
                        f"La tabla {tabla.nombre} pasa de {TOPE_FILAS} filas. Eso ya no es un "
                        "catálogo de tubería."
                    )
                hoja.append([_a_celda(v) for v in fila])
    finally:
        conexion.close()

    parcial = destino.with_name(destino.name + ".parcial")
    libro.save(parcial)
    parcial.replace(destino)
    return destino


def _nombre_de_hoja(tabla: str, usados: set[str]) -> str:
    """El nombre de la tabla, adaptado a lo que Excel admite.

    Excel corta en 31 caracteres y prohíbe cinco, y Access no. Sin esto, dos tablas con un
    nombre largo y el mismo principio acabarían en la misma hoja — o `openpyxl` levantaría a
    mitad de la exportación, con el archivo ya medio escrito.
    """
    limpio = PROHIBIDOS_EN_HOJA.sub("_", tabla)[:31] or "Tabla"
    candidato, numero = limpio, 2
    while candidato.lower() in usados:
        sufijo = f"_{numero}"
        candidato = limpio[: 31 - len(sufijo)] + sufijo
        numero += 1
    usados.add(candidato.lower())
    return candidato


def _a_celda(valor):
    """Un valor de ODBC listo para una celda.

    Los `bytes` de un campo binario no los escribe `openpyxl`, y un catálogo no los lleva: se
    dice cuántos son en vez de reventar la exportación entera por una columna que nadie mira.
    """
    if isinstance(valor, (bytes, bytearray)):
        return f"<{len(valor)} bytes>"
    return valor


def desde_excel(
    hoja_de_calculo: str | Path,
    plantilla: str | Path,
    *,
    destino: Path | None = None,
) -> tuple[Path, list[str]]:
    """Una hoja de cálculo de vuelta a un catálogo. Devuelve la ruta y los avisos.

    ## Se **copia** la plantilla, no se crea una base nueva

    Es la decisión que sostiene todo el resto. Crear un `.mdb` desde cero con `CREATE TABLE`
    reproduce los nombres y los tipos de las columnas, y **pierde todo lo demás**: los índices,
    las claves y las propiedades que Plant 3D dejó puestas. El catálogo resultante se abre —el
    formato es correcto— y falla más tarde, que es la peor forma de fallar.

    Copiando el archivo y sustituyendo las filas, el esquema es **idéntico por construcción**,
    no por parecido. Y de paso obliga a partir siempre de un catálogo real, que es como se
    trabaja de verdad.

    ## Todo o nada

    Se escribe sobre una copia y solo al final se pone en su sitio. Un catálogo a medio llenar
    —con `PIPE` puesto y `ELBOW` vacío— es peor que ninguno: se abre igual.
    """
    import openpyxl
    import pyodbc

    hoja_de_calculo, plantilla = Path(hoja_de_calculo), Path(plantilla)
    if not plantilla.exists():
        raise ComposicionInvalida(f"No está la plantilla {plantilla.name}.")

    tablas = {t.nombre.lower(): t for t in esquema(plantilla)}
    libro = openpyxl.load_workbook(hoja_de_calculo, data_only=True, read_only=True)
    avisos: list[str] = []

    try:
        _comprobar(libro, tablas, avisos)

        destino = Path(destino) if destino else hoja_de_calculo.with_suffix(".mdb")
        parcial = destino.with_name(destino.name + ".parcial")
        shutil.copy2(plantilla, parcial)

        conexion = pyodbc.connect(_cadena(parcial, crear=True), autocommit=False)
        try:
            cursor = conexion.cursor()
            for nombre_hoja in libro.sheetnames:
                tabla = tablas[nombre_hoja.lower()]
                filas = libro[nombre_hoja].iter_rows(values_only=True)
                cabecera = next(filas, None)
                if cabecera is None:
                    continue

                # **La plantilla se vacía entera**, incluso las tablas que la hoja no trae.
                # Dejar las filas viejas de una tabla que ya no se editó mezcla dos catálogos
                # en uno, y nadie lo vería hasta usarlo.
                cursor.execute(f"DELETE FROM [{_seguro(tabla.nombre, 'tabla')}]")  # nosec B608
                _insertar(cursor, tabla, cabecera, filas, avisos)

            for sobrante in tablas:
                if sobrante not in {h.lower() for h in libro.sheetnames}:
                    cursor.execute(f"DELETE FROM [{_seguro(tablas[sobrante].nombre, 'tabla')}]")  # nosec B608
                    avisos.append(
                        f"La tabla {tablas[sobrante].nombre} no venía en el Excel y queda vacía."
                    )
            conexion.commit()
        except Exception:
            conexion.rollback()
            conexion.close()
            parcial.unlink(missing_ok=True)
            raise
        conexion.close()
    finally:
        libro.close()

    parcial.replace(destino)
    return destino, avisos


def _comprobar(libro, tablas: dict[str, Tabla], avisos: list[str]) -> None:
    """Que lo que trae el Excel quepa en el esquema, **antes** de escribir un solo byte.

    Una columna que la plantilla no tiene **para el trabajo**, no se descarta en silencio: si
    alguien añadió `DN_NOMINAL` a mano esperando que sirva de algo, tirarla sin decirlo entrega
    un catálogo que parece correcto y no lleva su dato.
    """
    desconocidas = [h for h in libro.sheetnames if h.lower() not in tablas]
    if desconocidas:
        raise ComposicionInvalida(
            f"El Excel trae hojas que la plantilla no tiene: {', '.join(desconocidas)}. "
            f"Las tablas del catálogo son: {', '.join(sorted(t.nombre for t in tablas.values()))}."
        )

    for nombre_hoja in libro.sheetnames:
        tabla = tablas[nombre_hoja.lower()]
        validas = {c.nombre.lower(): c.nombre for c in tabla.columnas}
        cabecera = next(libro[nombre_hoja].iter_rows(values_only=True), None) or ()

        sobran = [str(c) for c in cabecera if c and str(c).lower() not in validas]
        if sobran:
            raise ComposicionInvalida(
                f"En la hoja «{nombre_hoja}» hay columnas que la tabla {tabla.nombre} no tiene: "
                f"{', '.join(sobran)}."
            )

        presentes = {str(c).lower() for c in cabecera if c}
        faltan = [n for clave, n in validas.items() if clave not in presentes]
        if faltan:
            # Faltar sí se permite —quedan vacías— pero se dice: puede ser deliberado o puede
            # ser una columna borrada sin querer al reordenar la hoja.
            avisos.append(
                f"{tabla.nombre}: {len(faltan)} columna(s) sin datos en el Excel "
                f"({', '.join(faltan[:4])}{'…' if len(faltan) > 4 else ''})."
            )


def _insertar(cursor, tabla: Tabla, cabecera, filas, avisos: list[str]) -> None:
    por_nombre = {c.nombre.lower(): c for c in tabla.columnas}
    columnas = [por_nombre[str(c).lower()] for c in cabecera if c]
    posiciones = [i for i, c in enumerate(cabecera) if c]
    if not columnas:
        return

    # Los nombres de columna también salen del catálogo subido, así que pasan por la misma
    # puerta. **Los valores no se interpolan nunca**: van como parámetros, que es lo único que
    # ODBC sí sabe hacer con seguridad.
    campos = ", ".join(f"[{_seguro(c.nombre, 'columna')}]" for c in columnas)
    huecos = ", ".join("?" * len(columnas))
    orden = f"INSERT INTO [{_seguro(tabla.nombre, 'tabla')}] ({campos}) VALUES ({huecos})"  # nosec B608

    puestas = 0
    for numero, fila in enumerate(filas, start=2):
        valores = [fila[i] if i < len(fila) else None for i in posiciones]
        # Una fila entera en blanco no es un dato: es el hueco que deja Excel al final de la
        # hoja. Insertarla mete registros fantasma en el catálogo.
        if all(v is None or str(v).strip() == "" for v in valores):
            continue
        if puestas >= TOPE_FILAS:
            raise ComposicionInvalida(
                f"La hoja {tabla.nombre} pasa de {TOPE_FILAS} filas. Eso ya no es un catálogo."
            )
        try:
            cursor.execute(orden, valores)
        except Exception as fallo:
            raise ComposicionInvalida(
                f"{tabla.nombre}, fila {numero} del Excel: {_limpiar(fallo)}"
            ) from fallo
        puestas += 1

    if not puestas:
        avisos.append(f"{tabla.nombre}: la hoja no traía ninguna fila, la tabla queda vacía.")


def _limpiar(fallo: Exception) -> str:
    """El mensaje de ODBC sin la parte que no dice nada.

    Vienen como `('HY000', "[HY000] [Microsoft][Controlador ODBC…] texto útil (-1811)")`, y
    enseñar eso entero en una pantalla es pedirle a alguien que busque su frase dentro.
    """
    texto = str(fallo)
    trozos = re.findall(r"\](?:\[[^\]]+\])*\s*([^\[\]]+?)(?:\s*\(-?\d+\))?['\"]?\)?$", texto)
    return trozos[-1].strip() if trozos else texto
