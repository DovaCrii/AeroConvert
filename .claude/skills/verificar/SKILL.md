---
name: verificar
description: Corre la verificación de AeroConvert (check, check --deploy, migraciones, pytest, ruff, bandit, pip-audit) y devuelve un resumen corto. Úsala antes de dar algo por terminado o de abrir un PR.
allowed-tools: Bash(uv run python scripts/claude/*), Bash(python scripts/claude/*)
---

# Verificar

1. Elige el alcance:
   - `rapido`: check, makemigrations, ruff check y ruff format. Segundos. Úsalo mientras iteras.
   - `pruebas apps/<área>`: solo pytest sobre esa ruta, sin cobertura. Úsalo tras tocar un área.
   - `todo`: los mismos pasos que el CI. Antes de cerrar, de abrir un PR o de tocar `pyproject.toml`.
2. Ejecuta `uv run python scripts/claude/verificar.py <alcance>`. **No** ejecutes `pytest --cov`
   completo a pelo: la suite es larga (más de 2.200 pruebas) y vuelca miles de líneas.
3. Verde: informa en una línea (pasos y cifras de pruebas que imprime).
4. Si falla: lee solo «Lo que falló» y «Final de la salida»; abre el log
   (`.claude/tmp/verificar/<paso>.log`) por rangos si hace falta. Arregla la causa, no el síntoma, y
   repite **solo** el alcance que falló.
5. Nunca digas «en verde» sin haber visto la salida de este comando en esta sesión.

Notas:

- `pip-audit` y `uv` necesitan red; `--sin-red` salta pip-audit.
- Esto resume la puerta de calidad; no la reemplaza. Los tres gates (`verify.ps1`, `verificar.sh`,
  `ci.yml`) deben decir lo mismo; si notas una diferencia, anótala.
- Pasar la suite no cumple el oráculo externo de `AGENTS.md`: si tocaste un motor, `/oraculo`.
- `fail_under = 83` no se baja nunca para que pase una corrida roja.
