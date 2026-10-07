@AGENTS.md

## Claude Code en este repositorio

- **Retomar:** lee `HANDOFF.md` (corto, ≤100 líneas). Su historia está en `docs/historial/` y en
  `git log`. Si algo de `HANDOFF.md` no cuadra con el código, gana el código.
- **`MASTER_PLAN.md` por filas, no entero:** `python scripts/claude/plan_fila.py F9.4 [--seccion]`
  y `python scripts/claude/plan_fila.py --abiertas`.
- **Verificar:** `/verificar` o `uv run python scripts/claude/verificar.py [rapido|pruebas RUTA|todo]`.
  No pegues salidas largas de pytest en la conversación: el resumen y el log en
  `.claude/tmp/verificar/` bastan. La suite completa tarda; para iterar usa `rapido` o `pruebas RUTA`.
- **Skills del proyecto:** `/verificar`, `/cerrar-fase F9.4`, `/abrir-pr`, `/oraculo`,
  `/refactor-seguro <archivo>` y **`/avanzar [bloque o fila]`**, que recorre el plan F13 a F16 por
  bloques (tablero en `docs/planes/SEGUIMIENTO.md`).
- Responde en español, de usted y sin voseo. Commits en español, imperativo y con ámbito
  (`feat(raster): …`).
- Lo que choque con `AGENTS.md` se resuelve a favor de `AGENTS.md`.
