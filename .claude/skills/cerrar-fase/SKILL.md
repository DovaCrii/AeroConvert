---
name: cerrar-fase
description: Cierra una fila del plan de AeroConvert (p. ej. F9.4) como manda AGENTS.md - oráculo, fila con fecha, CHANGELOG y HANDOFF.
disable-model-invocation: true
argument-hint: "<código de fila, p. ej. F9.4>"
---

# Cerrar `$ARGUMENTS`

1. `python scripts/claude/plan_fila.py $ARGUMENTS --seccion` — lee la fila y su sección. No abras
   `MASTER_PLAN.md` entero.
2. **Oráculo.** Mira la tabla de la regla 2 de `AGENTS.md`. Si tocaste un motor o un formato,
   ejecuta `/oraculo`. Si no hay oráculo posible, escribe el procedimiento manual con cifras
   **fechadas** en `docs/PRUEBAS_CON_ORACULO.md`. Una aserción reflexiva que da verde no cuenta.
   Sin oráculo cumplido, no marques ✅: deja 🔶 o ◐ y di qué falta y quién lo cierra.
3. `/verificar todo` en verde.
4. **Las tres cosas que exige `AGENTS.md`:**
   - fila ✅ **con fecha** en `MASTER_PLAN.md` (edita solo esa fila, por su número de línea);
   - entrada en `CHANGELOG.md` en «Sin publicar» (Keep a Changelog 1.1.0 es-ES);
   - `HANDOFF.md` actualizado: reescribe estado y pendientes, no apiles historia (≤100 líneas).
5. Si la fila deja un cabo con fecha (p. ej. «retirar `Resultado` un día después de desplegar»),
   anótalo en `HANDOFF.md` con su fecha.
6. Commit en español, imperativo y con ámbito (`feat(raster): …`, `docs: …`). La rama, el PR y la
   fusión siguen `/abrir-pr`.
7. Termina con: qué se cerró, con qué medida y qué queda abierto.
