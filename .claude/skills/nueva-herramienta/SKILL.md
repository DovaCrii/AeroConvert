---
name: nueva-herramienta
description: Añade una herramienta de documentos a AeroConvert sin olvidar ninguna de sus catorce piezas (registro, taxonomía, sinónimos, cola, tarea, pantalla, plantilla, ruta, icono, motivos, pruebas, cifras, documentos). Úsala antes de escribir una herramienta nueva o al revisar una.
argument-hint: "<id de la herramienta, p. ej. portada>"
---

# Añadir la herramienta `$ARGUMENTS`

Cada herramienta nueva ya dejó un CI en rojo por una pieza olvidada. La lista está **hecha ejecutable**
en `apps/documents/test_herramientas_completas.py`: córrela al terminar y te dice qué falta y en
cuál. Esta skill es el orden en que conviene hacerlo y las trampas que ya costaron.

## 0. Antes de escribir

- **¿Hay oráculo?** Dile primero **qué otro lector** comprueba la salida (regla 2 de `AGENTS.md`).
  Sin oráculo posible, la fila se marca ⚠ con su procedimiento manual; no se escribe una prueba que
  se da la razón a sí misma. Mira cómo lo hicieron los vecinos: `test_redactar.py` (tres lectores),
  `test_tamano.py` (PDFium y geometría conocida), `test_telemetria.py` (`ogrinfo`).
- **¿Depende de un programa de fuera?** Entonces se **sondea** y sale apagada con motivo
  (`motivos.py`), nunca se oculta ni se sustituye (regla 4). Mira `ocr.py` o `portadas.py`.
- Parte de **datos de resultado conocido**: un PDF con un rectángulo en un sitio sabido, un SRT
  escrito a mano. Una prueba que compara con `f(entrada)` no prueba nada.

## 1. Las piezas, en este orden

1. **El módulo** `apps/documents/<modulo>.py`: lógica pura, sin Django, `ComposicionInvalida` con
   el motivo dicho para una persona. Todo o nada: si falla, no deja piezas a medias.
2. **`herramientas.py`**: la entrada de `HERRAMIENTAS` con `id`, `icono`, `sale`, `familia`, `url`,
   `nombre`, `que_hace` (y `exige_*` si depende de algo de fuera).
   - **El nombre empieza por un verbo o es «X a Y»**, sin punto, **≤ 28 caracteres**
     (`test_nombres.py`). Nada de siglas con puntos («J.E.J.»).
   - **Sentence case**: una mayúscula suelta como «WebP» en `que_hace` la caza `test_estilo.py`.
3. **`apps/dashboard/taxonomia.py`**: el grupo en `DE_DOCUMENTOS`. Si es el primero de un grupo,
   revisa `test_taxonomia.py` (un grupo con una sola herramienta es una anomalía).
4. **`apps/dashboard/acciones.py`**: sinónimos en `_de_los_documentos()` y, si acepta archivos por
   extensión, `HERRAMIENTAS_POR_EXTENSION`.
   - **Un sinónimo suelto le quita la pregunta a otra herramienta** y Tino deja de contestar
     (ya pasó con «quitar» y con «carta»). Frases con dos o tres palabras, y corre `apps/tino` y
     `test_organizar.py`.
5. **`motor.py`**: su `Especificacion` (carril, `timeout_s`, `emite_progreso`, `salida_opcional`,
   `con_secreto`, `exige`).
6. **`tarea.py`**: `_<id>` y su entrada en `TAREAS`. El hijo **no tiene Django**: no importes nada
   que lo traiga. Un resultado «sin archivo» se levanta como `SinArchivo("<desenlace>")`.
7. **`apps/jobs/motivos.py`**: el desenlace o motivo nuevo (código en kebab-case). Un test cierra el
   catálogo.
8. **La pantalla** `views/pantalla_<x>.py` + su reexportación en `views/__init__.py`.
   - Dos pasos (mirar, hacer) con `_mirar_pdf`; una sola entrada con `_origen_del_formulario`.
   - **Lo que lleva datos sensibles va por `secretos`**, nunca por `options`.
9. **La plantilla** `templates/documents/<x>.html` con `{% include "documents/_origen.html" %}`.
   Todo campo de archivo lleva `data-tope-mb`, y debe haber un `data-avance-subida`
   (`test_criterio.py`). Si la pantalla **no recibe archivo**, añádela a `SIN_ARCHIVO` allí.
10. **`urls.py`**: la ruta.
11. **El icono** en `static/img/icons.svg`: trazo 1,75, 24 × 24, **un significado por icono**
    (`test_iconos.py`). No reutilices el de otra herramienta.
12. **Las pruebas** `apps/documents/test_<x>.py`: módulo, tarea, pantalla (302 sin sesión, rechazos,
    y de extremo a extremo con `despachador.procesar_una_vez()`), **original intacto por `sha256` y
    `mtime`**. Lo que depende del entorno (Access, Office, GDAL) se fuerza **en los dos casos** con
    `monkeypatch`: el CI no tiene esos programas.
13. **Las cifras**: `README.md` de `despliegue/`, `SERVIDOR.md`, `views/__init__.py`, `HANDOFF.md` y
    `EN_LETRA` de `test_cuenta.py` hablan de «las N herramientas»; todas con la misma cifra.
14. **Los documentos**: fila ✅ con fecha en `MASTER_PLAN.md`, `CHANGELOG.md` y `SEGUIMIENTO.md`.

## 2. Al terminar

```powershell
uv run python scripts/claude/verificar.py rapido     # check, migraciones, ruff, formato y bandit
$env:AEROCONVERT_GDAL_BIN=""; $env:AEROCONVERT_PDAL_BIN=""; uv run pytest -q --no-cov
```

La segunda, **en segundo plano** y esperando su aviso. Y antes de subir, si hay una rama hermana
abierta, `uv run python scripts/claude/fusionar_main.py`: resuelve sola los choques de «los dos
añadieron» y se niega a lo demás.

## Trampas que ya costaron un CI en rojo

- `bandit` **B110** (`try/except/pass`) y **B406** (`xml.sax.saxutils.escape`: usa `html.escape`).
- Una cifra en letra compuesta («treinta y una») que `test_cuenta.py` confundía con «treinta».
- En PowerShell, `R` es un alias (`Invoke-History`): no lo uses de función.
- Un cambio con `git stash` o `checkout` sobre un árbol con una suite corriendo la invalida.
