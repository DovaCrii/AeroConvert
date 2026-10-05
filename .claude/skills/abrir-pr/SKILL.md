---
name: abrir-pr
description: Prepara y abre un PR de AeroConvert siguiendo AGENTS.md - rama codex/..., contra main (no apilado), git fetch antes de empujar, sin force-push, sin fusionar.
disable-model-invocation: true
argument-hint: "[área o fase, p. ej. fase-9-4-visual]"
---

# Abrir PR

Reglas de `AGENTS.md` (no se negocian): nunca commit ni push directo a `main`; rama
`codex/<área-o-fase>` (no `feat/` ni `fix/`); un PR por fase; **nunca fusionar sin permiso
explícito** («dale» significa implementar y empujar, no fusionar); nunca `push --force`.

1. `git status` y `git fetch`. Si la rama divergió, **detente y pregunta**.
2. Si estás en `main`, crea `codex/$ARGUMENTS` antes de confirmar nada.
3. `/verificar todo` en verde. Si algo no se pudo correr (GDAL, Office, Tesseract, ODA), dilo en el PR.
4. **El PR va contra `main`, no apilado** sobre otra rama: al fusionar el de abajo, el de arriba no
   llega a `main` (ya pasó con F9.0–F9.2).
5. Commits en español, imperativo y con ámbito. No mezcles fases en un commit.
6. `git push -u origin <rama>` (pedirá confirmación; es lo esperado).
7. PR con `gh pr create` si está disponible; si no, entrega el texto. Cuerpo en español:
   - **Qué cambia**; **cómo se midió** (oráculo y cifras, con fecha); **filas del plan** tocadas;
   - **lo que no se pudo comprobar aquí** y queda para el servidor (`p340`);
   - si cambió `AGENTS.md`, dilo arriba y por qué.
8. No ejecutes `gh pr merge`. Fusionar lo decide el usuario.
