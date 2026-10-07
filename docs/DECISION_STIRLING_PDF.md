# Decisión: el reparto entre lo que se hace en casa y Stirling-PDF (F14.0, D4)

**Aprobada por la persona el 2026-10-07** («sí, como se propone»).

## La decisión

1. **Lo que se usa a diario se hace dentro de AeroConvert**, con las bibliotecas que ya usa o
   sondea (`pypdf`, `pikepdf`, PDFium, `pyHanko`, OCRmyPDF, Ghostscript). Son las filas F14.1 a
   F14.9, F14.11 y F14.20 de `MASTER_PLAN.md`: organizar, extraer, metadatos, formularios, firma
   visible, firma digital PAdES, recortar y cambiar el tamaño, comparar, redactar, PDF/A, visor y
   anotaciones, HTML a PDF y reparar. Cada una pasa por la cola, con su oráculo, su motivo cuando
   falta algo y el original intacto.
2. **La cola larga se delega en Stirling-PDF**, instalado **localmente en `p340`** y **sondeado**
   como Tesseract u ODA: AeroConvert no lo importa, no copia su código y no lo trae como
   dependencia. Si no está o no responde, sus herramientas salen **apagadas, con el motivo y una
   alternativa** (regla 4 de `AGENTS.md`); no se ocultan ni se sustituyen en silencio.
3. **Nada sale del equipo.** Stirling escucha solo en `127.0.0.1` y AeroConvert le habla por
   HTTP local. No se usa ningún servicio alojado de terceros.

## Qué va a cada lado

| En casa (F14) | En Stirling-PDF (cola larga) |
| --- | --- |
| Unir, dividir, organizar, extraer | Aplanar un PDF a imagen |
| Metadatos, formularios, firma visible | Extraer imágenes en lote con reglas |
| Firma digital PAdES y verificación | Dividir por código QR o por capítulos |
| Recortar y cambiar el tamaño | Quitar anotaciones o JavaScript |
| Comparar, redactar | Escala de grises y ajustes de color |
| PDF/A, reparar, HTML a PDF | Adjuntar y extraer archivos incrustados |
| Visor y anotaciones | Otras transformaciones sueltas que pida el uso |

La segunda columna **no se promete entera**: se agrega una herramienta de Stirling solo cuando
alguien la pide, y entra por la misma cola que las demás.

## Cómo se integra

- **Sonda:** una consulta de estado a `http://127.0.0.1:<puerto>` con tiempo máximo, en
  `apps/engines/sondas.py`; sin ejecutar ninguna conversión (regla de motores: una sonda no
  convierte). La variable es `AEROCONVERT_STIRLING_URL`; vacía significa «no instalado».
- **Llamada:** desde el proceso hijo de la cola, con tiempo máximo y sin pasar nada del usuario
  por una línea de órdenes. La salida se escribe a `<destino>.parcial` y se renombra con
  `os.replace()` solo tras verificarla con **otro lector** (PDFium o `pypdf`); el código de
  respuesta HTTP no es la prueba (regla 1).
- **El original no se toca** (regla 5): Stirling recibe una copia en memoria o un archivo
  temporal que se borra.
- **Motivos estables** en `apps/jobs/motivos.py`: `sin-stirling` (no hay servicio),
  `stirling-no-responde` (hay servicio pero no contesta a tiempo).

## Licencia

Stirling-PDF se ejecuta **como programa externo**, igual que Ghostscript, FFmpeg o Inkscape
(decisión D1, fila de la tabla de `AGENTS.md`). **No se importa ni se copia nada suyo.** Antes de
instalarlo en `p340` se comprueba su licencia vigente en la versión elegida: si alguna parte fuera
de pago o con condiciones que no encajen, esa parte no se usa.

## Instalación (la hace la persona, al final)

Los pasos exactos —descargar, usuario de servicio, puerto en `127.0.0.1` y la línea del `.env`—
se dejan en `despliegue/SERVIDOR.md` y en `HANDOFF.md` al cerrar el bloque B10. **Hasta que se
instale, AeroConvert funciona completo** y la cola larga se muestra apagada con su motivo.

## Qué cambia si se arrepiente

Basta dejar `AEROCONVERT_STIRLING_URL` vacía: todo lo de la primera columna sigue igual y la
segunda queda apagada. No hay nada que desinstalar del código.
