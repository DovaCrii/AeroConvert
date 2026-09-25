"""El proceso hijo que ejecuta una herramienta de documentos desde la cola.

## Por qué las herramientas de PDF pasan por la cola

Hasta la fase 9 corrían **dentro de la petición**. Eso tenía cuatro consecuencias, todas
invisibles hasta que se sufrían:

- gunicorn mata la petición a los 120 s, así que un OCR de cuarenta páginas moría a medias
  sin decir nada;
- trece de las veinte no dejaban descargar el resultado de un archivo subido;
- no había progreso, ni historial, ni «seguir donde lo dejaste»;
- y su uso no dejaba rastro: el servidor decía «0 trabajos» sin poder distinguir «nadie ha
  usado esto» de «se ha usado mucho, pero no aquí».

La cola ya tenía todo eso —progreso, bitácora, descarga con dueño, reintentar, cancelar—
para las conversiones geoespaciales. Esto es la pieza que faltaba para que lo usen también.

## El contrato con el corredor

    python -m apps.documents.tarea <herramienta> <encargo.json> <parcial> <informe.json>

- **El encargo** trae las entradas y las opciones. Va en un archivo y no en el argv porque
  una receta de «Unir» con veinte archivos pasa del límite de 32 k de Windows, y porque el
  argv queda escrito en la bitácora.
- **El parcial** es donde se escribe la salida. El corredor la verifica y la pone en su sitio.
- **El informe** es lo que el hijo cuenta de vuelta: un desenlace si terminó sin archivo,
  avisos, detalles para el recibo, y el código si falló.
- **El progreso** sale por la salida estándar en líneas `PROGRESO 0.42`, con `flush`: sin él,
  todo llegaría junto al final y el detector de atasco mataría un trabajo sano.

## Lo que el hijo no hace nunca

**No arranca Django**, igual que `apps/vector/desde_cad.py`. Leer una cadena de ajustes no
justifica levantar la base de datos, y las sondas que sí la necesitan —si hay Office, si hay
Tesseract— las hace el padre antes de lanzar esto.

**No recibe la contraseña de «Proteger» por el argv ni por el encargo**, sino por la variable
de entorno `AEROCONVERT_CONTRASENA`: el argv se registra en la bitácora, y el encargo es un
archivo en disco.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Se ejecuta como proceso hijo, así que no puede dar por hecho que la raíz del repositorio
# esté en `sys.path`. Igual que `desde_landxml` y `desde_cad`.
if __package__ in (None, ""):  # pragma: no cover - solo en el arranque del hijo
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class FalloDeTarea(Exception):
    """Un fallo con su código estable, para que el corredor no tenga que adivinarlo."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


class SinArchivo(Exception):
    """Terminó bien y **no hay archivo que entregar**. Lleva el desenlace que lo explica."""

    def __init__(self, desenlace: str, detalles: dict | None = None) -> None:
        super().__init__(desenlace)
        self.desenlace = desenlace
        self.detalles = detalles or {}


def progreso(fraccion: float) -> None:
    """Una línea que entiende `analizador_de_progreso`. **Con `flush`**, o no llega a tiempo."""
    print(f"PROGRESO {max(0.0, min(1.0, fraccion)):.3f}", flush=True)


# --- Las tareas --------------------------------------------------------------
#
# Cada una recibe las entradas, las opciones y el parcial, escribe la salida y devuelve los
# detalles para el recibo. Los errores de la herramienta llegan como `ComposicionInvalida`, y
# `main` los traduce a su código.


def _numerar(entradas: list[dict], opciones: dict, parcial: Path) -> dict:
    from apps.documents import marcas

    hecho = marcas.numerar(
        entradas[0]["ruta"],
        parcial,
        posicion=opciones.get("posicion", "pie-derecha"),
        formato=opciones.get("formato", "{n} / {total}"),
        desde=int(opciones.get("desde", 1)),
        empezar_en=int(opciones.get("empezar_en", 1)),
    )
    return {"paginas": hecho.paginas, "marcadas": hecho.marcadas}


def _marca(entradas: list[dict], opciones: dict, parcial: Path) -> dict:
    from apps.documents import marcas

    hecho = marcas.marca_de_agua(
        entradas[0]["ruta"],
        parcial,
        opciones.get("texto", ""),
        opacidad=opciones.get("opacidad", "normal"),
        diagonal=opciones.get("orientacion", "diagonal") == "diagonal",
    )
    return {"paginas": hecho.paginas, "marcadas": hecho.marcadas}


def _a_markdown(entradas: list[dict], opciones: dict, parcial: Path) -> dict:
    from apps.documents import a_markdown

    try:
        escrito = a_markdown.a_markdown(entradas[0]["ruta"], destino=parcial)
    except a_markdown.SinTextoQueSacar as nada:
        # **No es un fallo: es la respuesta.** Un escaneo no tiene texto, y un `.md` vacío
        # sería la peor forma de decirlo porque parece que funcionó.
        raise SinArchivo("sin-texto-que-sacar", {"motivo": str(nada)}) from nada
    return {"bytes": Path(escrito).stat().st_size}


def _comprimir(entradas: list[dict], opciones: dict, parcial: Path) -> dict:
    from apps.documents import comprimir

    escrito, resultado = comprimir.comprimir(
        entradas[0]["ruta"],
        ppp=int(opciones.get("ppp", 200)),
        destino=parcial,
        progreso=progreso,
    )
    detalles = {
        "origen_bytes": resultado.origen_bytes,
        "salida_bytes": resultado.salida_bytes,
        "reduccion_pct": resultado.reduccion_pct,
        "imagenes_tocadas": resultado.imagenes_tocadas,
        "paginas": resultado.paginas,
    }
    if escrito is None:
        # **La única herramienta donde la respuesta correcta puede ser «no hagas nada».**
        # Recomprimir un PDF ya optimizado lo engordaría, y entregar eso sería peor que nada.
        raise SinArchivo("no-valio-la-pena", detalles)
    return detalles


def _markdown_a_pdf(entradas: list[dict], opciones: dict, parcial: Path) -> dict:
    from apps.documents import desde_markdown

    desde_markdown.markdown_a_pdf(entradas[0]["ruta"], destino=parcial)
    return {}


#: Qué función hace cada herramienta. **Solo las que ya pasan por la cola**: las demás siguen
#: en su pantalla hasta que les toque su lote, y un id que no esté aquí es un error del
#: corredor, no de la persona.
TAREAS = {
    "numerar": _numerar,
    "marca": _marca,
    "md_excel": _a_markdown,
    "md_csv": _a_markdown,
    "md_word": _a_markdown,
    "md_pdf": _a_markdown,
    "md_epub": _a_markdown,
    "md_html": _a_markdown,
    "md_a_pdf": _markdown_a_pdf,
    "comprimir": _comprimir,
}


def _escribir_informe(ruta: Path, informe: dict) -> None:
    ruta.write_text(json.dumps(informe, ensure_ascii=False), encoding="utf-8")


def ejecutar(herramienta: str, encargo: dict, parcial: Path) -> dict:
    """Corre la tarea y devuelve el informe. **No levanta**: el fallo va dentro del informe."""
    from apps.documents.composicion import ComposicionInvalida

    tarea = TAREAS.get(herramienta)
    if tarea is None:
        return {"codigo": "sin-motor", "mensaje": f"«{herramienta}» no se ejecuta desde la cola."}

    try:
        detalles = tarea(encargo.get("entradas") or [], encargo.get("opciones") or {}, parcial)
    except SinArchivo as sin:
        return {"desenlace": sin.desenlace, "detalles": sin.detalles}
    except FalloDeTarea as fallo:
        return {"codigo": fallo.codigo, "mensaje": fallo.mensaje}
    except ComposicionInvalida as fallo:
        return {
            "codigo": getattr(fallo, "codigo", "") or "documento-invalido",
            "mensaje": str(fallo),
        }
    return {"detalles": detalles or {}}


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("uso: python -m apps.documents.tarea <herramienta> <encargo> <parcial> <informe>")
        return 2

    herramienta, ruta_encargo, parcial, ruta_informe = argv
    encargo = json.loads(Path(ruta_encargo).read_text(encoding="utf-8"))
    informe = ejecutar(herramienta, encargo, Path(parcial))
    _escribir_informe(Path(ruta_informe), informe)

    if informe.get("codigo"):
        # La última línea con «ERROR» es la que el corredor enseña si no hubiera informe.
        print(f"ERROR: {informe.get('mensaje', '')}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - lo ejerce el proceso hijo
    raise SystemExit(main(sys.argv[1:]))
