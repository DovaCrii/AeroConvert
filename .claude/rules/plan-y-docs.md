---
paths:
  - "MASTER_PLAN.md"
  - "HANDOFF.md"
  - "CHANGELOG.md"
  - "docs/**"
---

# Plan, retome y documentación

- **`MASTER_PLAN.md` no se lee entero:** `python scripts/claude/plan_fila.py <código> [--seccion]` y,
  con el número de línea que imprime, lee un rango y edita solo esa fila.
- **Al cerrar una fase:** fila ✅ con fecha en `MASTER_PLAN.md`, entrada en `CHANGELOG.md` (Keep a
  Changelog 1.1.0 es-ES + SemVer) y `HANDOFF.md` actualizado. Las tres, o no se cerró.
- **`HANDOFF.md` es un resumen de estado, no una bitácora:** ≤100 líneas, con fecha y último PR.
  Se reescribe; lo que se retira va a `docs/historial/`. El documento que se lee primero no puede
  ser el más viejo (ya estuvo diez días desfasado).
- **La tabla «Deuda conocida» lleva estado comprobado contra el código**, no contra el plan.
- **Una afirmación sobre el código se comprueba contra el código** antes de escribirla: este repo
  tuvo «no hay ningún respaldo» repetido días y los timers existían.
- **Los PR van contra `main`, no apilados:** al fusionar el de abajo, los de arriba no llegan a `main`.
- Datos reales (ortofotos, nubes, entregables de cliente, claves de SDK) **nunca** entran al repo.
