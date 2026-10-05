---
paths:
  - "scripts/**"
  - "pyproject.toml"
  - "pytest.ini"
  - ".github/**"
  - "conftest.py"
---

# Puerta de calidad

- **Hay tres gates que deben decir lo mismo:** `scripts/verify.ps1`, `scripts/verificar.sh` y
  `.github/workflows/ci.yml`. Si añades, quitas o cambias un paso en uno, cámbialo en los tres (o
  anota por qué no). Dos gates que comprueban cosas distintas dan la peor respuesta: «pasa aquí y
  falla allá».
- **`fail_under = 83` es un piso, no un objetivo.** Nunca se baja para que pase una corrida roja.
  Ningún módulo lleva `# pragma: no cover` entero.
- **El gate verde en una máquina sin GDAL:** las pruebas con oráculo llevan `@pytest.mark.oraculo` y
  `pytest.ini` las deselecciona. Se corren con `uv run pytest -m oraculo`.
- **`ruff format --check` no es redundante con `ruff check`.** Olvidarlo dejó rojo el CI de
  AeroControl durante días.
- **`check --deploy` se corre con `DJANGO_SETTINGS_MODULE=config.settings.prod` fijado**; si no,
  mira el módulo equivocado y pasa siempre.
- Los scripts de `scripts/claude/` pasan por `ruff check` y `ruff format --check` como todo el repo.
