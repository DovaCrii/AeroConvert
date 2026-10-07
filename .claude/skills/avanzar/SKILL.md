---
name: avanzar
description: Avanza el plan F13 a F16 de AeroConvert por bloques - elige la siguiente fila sin bloqueo, la hace con su oráculo, corre la suite completa, abre el PR, espera el CI, fusiona y deja el seguimiento al día. Lo que necesita de la persona lo anota y sigue con lo que sí puede. Despliegue solo al final.
disable-model-invocation: true
argument-hint: "[bloque o fila, p. ej. B1, F13.10; vacío = lo siguiente sin bloqueo]"
---

# Avanzar el plan por bloques

El plan está en `docs/planes/PLAN_2026-10-07.md` y sus filas en `MASTER_PLAN.md` (F13 a F16). **El
estado por bloques y lo que se le pide a la persona viven en `docs/planes/SEGUIMIENTO.md`**: ese
archivo es el tablero. `HANDOFF.md` solo lo apunta.

**Quién hace qué (decidido el 2026-10-07):** Claude hace ramas, commits, push, PR, revisión y
fusiones con el CI verde. **La persona solo despliega en la VM `p340`, y lo hace al final de todo**
(o cuando ella lo diga). Esta skill **nunca** despliega ni toca el servidor.

## El ciclo

1. **Ponerse al día.** Leer `HANDOFF.md` y `docs/planes/SEGUIMIENTO.md`; `git checkout main && git
   pull`; `gh pr list` (no dejar un PR propio abierto sin motivo). Si el árbol tiene cambios que no
   son suyos, **parar y preguntar**.
2. **Elegir.** Con argumento: ese bloque o esa fila. Sin argumento: el primer bloque no terminado
   cuya siguiente fila **no esté bloqueada** por una decisión o un dato de la persona. Detalle de una
   fila: `python scripts/claude/plan_fila.py F13.10 --seccion`.
3. **Rama** `codex/<fila-o-bloque>` contra `main`, **nunca apilada**. Una fila por PR; filas
   mellizas del mismo bloque pueden ir juntas si el plan lo dice.
4. **Hacer la fila con su oráculo.** El oráculo es **otro lector** distinto del que escribió la salida
   (reglas 1 y 2 de `AGENTS.md`). Si no se puede correr aquí, la fila se marca ⚠ con el motivo y el
   procedimiento manual; no se sustituye por una prueba que se da la razón a sí misma. Cada fila deja
   **una prueba que impide volver atrás**.
5. **Si toca una pantalla:** verla en el navegador en claro y oscuro, a 1440 y a 375 px, sin
   desborde horizontal (`scrollWidth == innerWidth`). Servidor con `DB_PATH` y
   `AEROCONVERT_RAICES_PERMITIDAS` apuntando a la carpeta temporal de la sesión.
6. **Antes de subir: la suite completa**, no solo lo tocado (`$env:AEROCONVERT_GDAL_BIN="";
   $env:AEROCONVERT_PDAL_BIN=""; uv run pytest -q --no-cov`), **en segundo plano**, y esperar el aviso
   de que terminó. **Nada de `sleep` largos.** Más `ruff format --check .` y `ruff check .`. Añadir
   una herramienta ya dejó un PR en rojo porque un sinónimo le quitó la pregunta a otra y Tino dejó de
   contestar: por eso la suite entera.
7. **Documentar al cerrar la fila:** fila ✅ con fecha en `MASTER_PLAN.md`, entrada en
   `CHANGELOG.md`, la fila del bloque en `SEGUIMIENTO.md`, y `HANDOFF.md` solo si cambia algo que
   deba saber quien retome (≤100 líneas).
8. **PR, revisión y fusión:** seguir `/abrir-pr`. El cuerpo va en un archivo (`--body-file`). Esperar
   con `gh pr checks <n> --watch`; fusionar con `gh pr merge <n> --merge` **solo con el CI verde**.
   Si falla, leer `gh run view <id> --log-failed`, arreglar y volver a subir; si es la
   infraestructura de GitHub (`not acquired by Runner`), `gh run rerun`. **Nunca** `push --force`,
   nunca fusionar en rojo, nunca bajar `fail_under`.
9. **Seguir, sin parar a consultar** (la persona lo pidió el 2026-10-07: «sin consultar, cuando
   termines un bloque, hasta finalizar todo»). Al cerrar una fila o un bloque **no se detiene ni se
   pregunta**: se vuelve al paso 1 con lo siguiente. El informe corto de abajo **se entrega una sola
   vez, al terminar todo** (o cuando no quede ninguna fila sin bloqueo); entre bloques basta una
   línea de estado. Lo que falte de la persona se anota como pedido y se sigue con otra fila.

## Cuando hace falta algo de la persona

**No se detiene el avance por eso.** Se hace esto, en este orden:

1. Escribir el pedido en la tabla «Pedidos a la persona» de `SEGUIMIENTO.md`: **qué** se necesita,
   **para qué fila**, **en qué forma** (archivo, decisión, dato) y **qué pasa si no llega**.
2. Marcar la fila ⏸ (espera) con el motivo; no inventar el dato ni elegir por ella lo que es suyo.
3. **Continuar con la siguiente fila que sí se puede.** Si no queda ninguna, parar y entregar el
   informe con los pedidos arriba del todo.

Casos conocidos: aprobar la tabla de renombres (F13.2); aprobar el reparto con Stirling (F14.0);
plantilla J.E.J. (F14.19); puntos de control (F15.1); archivos de Deswik/Vulcan/Surpac (F15.4);
instalar ODA (F15.8); confirmar el cierre de las ramas de F11.6 (F13.12). **No se consulta durante el
avance**: una decisión que solo es de la persona se anota como pedido y la fila queda en espera; si
la decisión era razonable con la recomendación del plan, se aplica **la recomendación** y se deja
escrito en el PR que fue por omisión y cómo deshacerla.

## El informe al terminar un bloque (corto)

- Filas cerradas, con PR y fecha.
- **Pedidos a la persona**, arriba y con su fila.
- Lo que no se pudo comprobar aquí (GDAL, Office, Tesseract, ODA, FFmpeg) y queda para `p340`.
- Cuántos PR llevan sin desplegar y el comando de despliegue de `HANDOFF.md`.

## El final de todo (bloque B10)

Cuando el tablero esté completo: subir la versión (`0.11.0` al cerrar F13, `0.12.0` con las firmas),
dejar `HANDOFF.md` con los pasos exactos de la VM (migraciones nuevas, variables de `.env`,
programas externos por instalar: FFmpeg, Ghostscript, Inkscape, veraPDF, según lo que se haya
usado), y **entregarle a la persona la lista para desplegar**. Ella la ejecuta; después se corre
`resumen_de_uso` y se anotan las primeras cifras.

## Trampas de esta máquina (ya costaron tiempo)

- La herramienta de PowerShell bloquea por falso positivo comandos con ciertos textos (`/*`, `/T`,
  rutas que parecen de sistema). Los textos largos se escriben **con `Write` a un archivo** y se
  aplican con un script de Python o con `Edit`; no con `-replace` en una línea.
- `R` es un alias de PowerShell (`Invoke-History`): no se nombra así una función.
- Un arreglo con PowerShell sobre archivos de prueba dañó tres de ellos: **cambios en código y
  pruebas, con `Edit`** o con un script que compruebe que cada reemplazo casa.
- El CI no tiene GDAL ni PDAL y la estación sí: variables vacías al correr `pytest`. **Tampoco tiene
  Access** (los catálogos salen apagados) ni Office ni Tesseract: una prueba que mira lo que se ve
  en pantalla debe **forzar los dos casos** con `monkeypatch`, no suponer que el CI es como la
  estación (ya costó un PR en rojo, F13.1).
- Una plantilla servida por `runserver --noreload` no se recarga: reiniciar el servidor.
- `.claude/rules/` ya recoge las reglas de interfaz, de motores y de plan; léalas antes de tocar
  una pantalla o un motor.

## Lo que esta skill no hace

No despliega, no toca `p340`, no cambia `AGENTS.md` salvo lo que la persona ya decidió (D1), no
instala programas del sistema, no sube datos reales (ortofotos, nubes, claves) al repositorio y no
decide por la persona lo que está en «Lo que solo podías decidir tú».
