@AGENTS.md

## Claude Code en este repositorio

- **Retomar:** lee `HANDOFF.md` (corto, ≤100 líneas). Su historia está en `docs/historial/` y en
  `git log`. Si algo de `HANDOFF.md` no cuadra con el código, gana el código.
- **`MASTER_PLAN.md` por filas, no entero:** `python scripts/claude/plan_fila.py F9.4 [--seccion]`
  y `python scripts/claude/plan_fila.py --abiertas`.
- **Verificar:** `/verificar` o `uv run python scripts/claude/verificar.py [rapido|pruebas RUTA|todo]`.
  No pegues salidas largas de pytest en la conversación: el resumen y el log en
  `.claude/tmp/verificar/` bastan. La suite completa tarda; para iterar usa `rapido` o `pruebas RUTA`.
- **Skills del proyecto:** `/avanzar [bloque o fila]` (el bucle del plan: elige filas, las encarga a los
  agentes y las publica; tablero en `docs/planes/SEGUIMIENTO.md`), **`/publicar <rama>`** (de una rama
  terminada a `main`: trae `main`, marca la fila, suite, PR y fusión; sustituye a `abrir-pr` y
  `cerrar-fase`), `/verificar`, `/oraculo`, `/refactor-seguro <archivo>`, **`/nuevo-motor <familia/formato>`**
  (las piezas de un motor geoespacial), **`/nueva-herramienta <id>`** (las catorce piezas de una herramienta
  de documentos) y **`/mirar-pantalla <nombre=/ruta/>`** (ver una pantalla sin crear cuentas). La plantilla de
  encargo a un agente está en `.claude/agents/ENCARGO.md`.
- **Agentes del proyecto** (`.claude/agents/`; reparto en `/avanzar`): Opus coordina con esfuerzo
  medio; `explorador` (Haiku, solo lectura: dónde vive algo y qué pruebas lo fijan), `investigador`
  (Sonnet, web con fuentes), `implementador` (Sonnet, una fila en su worktree, sin push),
  `disenador` (Sonnet, tokens, contraste e ilustraciones), `revisor-de-reglas` (Sonnet, solo lectura:
  revisa un diff contra las cinco reglas de `AGENTS.md`) y `fusionador-de-pr` (Haiku, solo `gh`:
  espera el CI del commit de cabeza y fusiona en verde).
- **Antes de un `git push`** corre solo la puerta rápida (`scripts/claude/antes_de_push.py`, hook en
  `.claude/settings.json`) y lo bloquea si falla; **es una ayuda, no una garantía** (solo mira ciertas
  formas de `git push` desde Bash o PowerShell): la protección de rama y el CI son los que mandan. **Dos PR que añaden herramientas chocan siempre en
  los mismos archivos:** `scripts/claude/fusionar_main.py` resuelve «los dos añadieron» validando.
- Responde en español, de usted y sin voseo. Commits en español, imperativo y con ámbito
  (`feat(raster): …`).
- Lo que choque con `AGENTS.md` se resuelve a favor de `AGENTS.md`.

## Cómo trabajamos (resumen del estándar; completo en `docs/ESTANDAR_TRABAJO.md` de AeroAcademy)

- **Plan primero.** Antes de cambiar algo no trivial, proponga un plan corto (qué, en qué archivos, cómo se prueba).
- **Bloques pequeños.** Una rama y un PR por cambio acotado (`codex/<área-o-fase>`). Nunca directo sobre `main`.
- **Pruebas.** Antes de entregar: `uv run pytest` (o `scripts/claude/verificar.py`) y `uv run ruff check . && uv run ruff format --check .`.
- **Privacidad (repositorio público).** Sin claves, `.env`, datos de clientes ni datos personales (usuarios, correos) en git, logs ni pruebas. Corra `python tools/kit/privacy_scan.py`.
- **No tocar** `despliegue/`, `.env*` ni los flujos de despliegue sin que se pida explícitamente.
