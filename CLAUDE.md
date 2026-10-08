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
  `/refactor-seguro <archivo>`, **`/nueva-herramienta <id>`** (las catorce piezas de una herramienta
  de documentos) y **`/avanzar [bloque o fila]`**, que recorre el plan F13 a F16 por bloques
  (tablero en `docs/planes/SEGUIMIENTO.md`).
- **Agentes del proyecto** (`.claude/agents/`): `revisor-de-reglas` (solo lectura: revisa un diff
  contra las cinco reglas de `AGENTS.md`; para filas que tocan motores, firmas o datos sensibles) y
  `fusionador-de-pr` (solo `gh`: espera el CI de un PR y lo fusiona en verde).
- **Antes de un `git push`** corre solo la puerta rápida (`scripts/claude/antes_de_push.py`, hook en
  `.claude/settings.json`) y lo bloquea si falla. **Dos PR que añaden herramientas chocan siempre en
  los mismos archivos:** `scripts/claude/fusionar_main.py` resuelve «los dos añadieron» validando.
- Responde en español, de usted y sin voseo. Commits en español, imperativo y con ámbito
  (`feat(raster): …`).
- Lo que choque con `AGENTS.md` se resuelve a favor de `AGENTS.md`.
