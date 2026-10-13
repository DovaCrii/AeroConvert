# Plantilla de encargo a un agente

Un encargo corto: lo repetido ya está en `implementador.md`, `disenador.md` y en las skills. Copie, rellene lo
que está entre `<>` y borre lo que no aplique.

```text
**Tu rol**: lee primero `D:\I+D\AeroConvert\.claude\agents\<implementador|disenador>.md` y síguelo.
Rama `codex/<fila>` desde `origin/main` (haz `git fetch`), commits pequeños, **sin push, sin PR**.

## Fila <F00.0>: <título>
<Qué se entrega, en uno o dos párrafos con el porqué (qué pidió la persona y qué decidió).>
<Reglas de la fila: CRS que no se adivina, qué no sale de la máquina, qué no se toca.>

## Oráculo (regla 2)
<Qué otro lector comprueba la salida y con qué datos sintéticos. Qué queda ⚠ si no se puede correr aquí.>

## Piezas y herramientas
<Skills que aplican: /nuevo-motor, /nueva-herramienta, /refactor-seguro, /mirar-pantalla.>
<Archivos clave y qué reutilizar (rutas).>

## Otras ramas abiertas (no las toques)
<codex/...: qué tocan, por si chocan.>

## Devuelve
Commits, archivos, pruebas nuevas con su oráculo y cifras, resultado de la suite, lo que quedó ⚠ y por qué.
```

Cada encargo, además:

- `effort: "medium"` e `isolation: "worktree"` si escribe código.
- Si algo necesita **descargar** (bibliotecas, fuentes, datos), dilo en el encargo con el permiso de la
  persona; sin él, el agente no descarga.
- Si se conoce un dato que el agente no debe copiar (una clave, una ruta de cliente), se dice que **no** lo
  copie.
