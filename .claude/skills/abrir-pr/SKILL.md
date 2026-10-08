---
name: abrir-pr
description: Prepara, abre y fusiona un PR de AeroConvert siguiendo AGENTS.md - rama codex/..., contra main (no apilado), git fetch antes de empujar, sin force-push, fusión solo con el CI verde.
disable-model-invocation: true
argument-hint: "[área o fase, p. ej. fase-9-4-visual]"
---

# Abrir y fusionar un PR

Reglas de `AGENTS.md` (no se negocian): nunca commit ni push directo a `main`; rama
`codex/<área-o-fase>` (no `feat/` ni `fix/`); un PR por fase; **el agente fusiona sus PR con el
CI verde y sin conflictos, y la persona solo despliega en la VM** (decisión del 2026-10-05);
nunca `push --force`.

1. `git status` y `git fetch`. Si la rama divergió, **detente y pregunta**; no fuerces.
2. Si estás en `main`, crea `codex/$ARGUMENTS` antes de confirmar nada. **Comprueba con
   `git branch --show-current` que no sigues en `main` antes de hacer commit.**
3. `/verificar todo` en verde (o, con la suite aparte, `verificar.py rapido` —incluye bandit— más
   pytest completo). Si algo no se pudo correr (GDAL, Office, Tesseract, ODA), dilo en el PR.
4. **El PR va contra `main`, no apilado** sobre otra rama: al fusionar el de abajo, el de arriba no
   llega a `main` (ya pasó con F9.0–F9.2).
5. Commits en español, imperativo y con ámbito. No mezcles fases en un commit.
6. `git push -u origin <rama>`.
7. PR con `gh pr create` si está disponible; si no, entrega el texto. Cuerpo en español:
   - **Qué cambia**; **cómo se midió** (oráculo y cifras, con fecha); **filas del plan** tocadas;
   - **lo que no se pudo comprobar aquí** y queda para el servidor (`p340`);
   - si cambió `AGENTS.md`, dilo arriba y por qué.
8. **Fusión.** Espera al CI (`gh pr checks <n> --watch`). Con la comprobación en verde y
   `mergeStateStatus` en `CLEAN`, `gh pr merge <n> --merge`. Si el CI falla o hay conflicto, **no
   fusiones**: arregla (merge de `main` en la rama, nunca `push --force`) o dilo. Si el CI falla
   por la infraestructura de GitHub (`The job was not acquired by Runner`), relánzalo con
   `gh run rerun`; no lo des por verde ni por roto. Si la persona dijo de una entrega concreta
   «no la fusiones», se respeta.
   Si `gh pr merge` responde `HTTP 500` o «Something went wrong», es de GitHub: reintenta a los
   60 s (hasta cuatro veces) antes de dar nada por roto. Si `--watch` dice «no checks reported»,
   espera 30 s y repite. Con la rama en conflicto: `scripts/claude/fusionar_main.py`.
9. Después, dile a la persona el comando de despliegue de `HANDOFF.md`: ella lo ejecuta en la VM.
