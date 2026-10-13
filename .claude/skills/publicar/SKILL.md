---
name: publicar
description: Lleva una rama terminada de AeroConvert hasta main - trae main, resuelve los choques del plan, marca la fila, corre la suite completa, abre el PR con su cuerpo y lo deja en manos del fusionador. Úsala cuando un agente entrega una rama o cuando termina una fila propia.
disable-model-invocation: true
argument-hint: "<rama codex/..., p. ej. codex/f20-1-y-2-topografia>"
---

# Publicar `$ARGUMENTS`

Sustituye a `abrir-pr` y a `cerrar-fase`. Reglas de `AGENTS.md` que no se negocian: nunca commit ni push
directo a `main`; rama `codex/<área>`; el PR va contra `main`, no apilado; **fusión solo con el CI verde y
sin conflictos**; nunca `push --force`; y la persona es quien despliega.

Trabaje **dentro del worktree de la rama** (los agentes dejan el suyo en `.claude/worktrees/`). Rutas
absolutas en los scripts de una sola vez: `[IO.File]` resuelve desde el directorio del proceso.

1. **Traer `main`.** `git fetch` y `uv run python scripts/claude/fusionar_main.py`. Resuelve solo los choques
   de «los dos añadieron» y las filas de tabla del plan y del tablero; **se niega a lo demás** y deja la lista.
   Lo que quede se resuelve a mano **sin perder ninguna de las dos mitades**; se comprueba que no queden
   marcas `<<<<<<<` y se confirma.
2. **La fila.** `python scripts/claude/plan_fila.py <código>` y marque la fila con fecha en
   `MASTER_PLAN.md`: ✅ si el oráculo se cumplió, ⚠ con el motivo y quién lo cierra si no. Una fila ✅ sin
   oráculo no vale (regla 2). La misma marca va en su bloque de `docs/planes/SEGUIMIENTO.md`.
3. **Documentos.** `CHANGELOG.md` bajo `## [Sin publicar]` (Keep a Changelog 1.1.0 es-ES);
   `HANDOFF.md` solo si cambia algo que deba saber quien retome (**≤ 100 líneas**; lo que se retira va a
   `docs/historial/`). Si hay pedidos nuevos a la persona, a `SEGUIMIENTO.md`.
4. **La suite completa, en segundo plano**, sobre el commit final y sin cambiar de rama mientras corre:
   `$env:AEROCONVERT_GDAL_BIN=""; $env:AEROCONVERT_PDAL_BIN=""; uv run pytest -q --no-cov -p no:cacheprovider`
   más `uv run ruff format --check .` y `uv run ruff check .`. `/verificar rapido` mientras se itera. **Lo que
   pasa en Windows tiene que pasar en Linux** (el CI y p340): archivos de prueba con `newline="\n"` y rutas
   partidas por `\` y `/`. Si toca un motor, `/oraculo`; si toca una firma, datos sensibles o permisos, el
   diff pasa por `revisor-de-reglas` **antes**.
5. **El cuerpo del PR**, en un archivo (`--body-file`): qué cambia; el oráculo con **cifras** y fecha; lo que
   se revisó y se corrigió; lo que **no** se pudo comprobar aquí y queda para `p340`; las filas del plan. En
   español, de usted.
6. **Abrir.** `git push -u origin <rama>` y `gh pr create --base main --head <rama>`. El hook
   `antes_de_push.py` corre solo la puerta rápida.
7. **Fusionar.** Lance `fusionador-de-pr` (Haiku) con el número del PR. **Espera el CI del commit de cabeza**
   y fusiona solo si pasa y está `MERGEABLE`. Si responde conflicto (otro PR entró primero), vuelva al paso 1 y
   suba el commit nuevo: el fusionador espera el CI de ese commit, no del anterior. **Un PR por vez** cuando
   comparten plan, tablero o `CHANGELOG.md`: fusione uno, traiga `main` al siguiente.
8. Al terminar, diga qué se fusionó y qué queda, y recuerde el comando de despliegue de `HANDOFF.md`: lo corre
   la persona.
