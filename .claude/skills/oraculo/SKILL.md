---
name: oraculo
description: Corre las pruebas con oráculo externo de AeroConvert (GDAL, PDAL) y anota el resultado con fecha en docs/PRUEBAS_CON_ORACULO.md, sin sustituirlas por aserciones reflexivas.
disable-model-invocation: true
argument-hint: "[ruta o expresión -k]"
---

# Oráculo externo

La regla 2 de `AGENTS.md`: un test que compara nuestra salida con nuestra propia lectura no prueba
nada. Esta skill corre las que sí.

1. **Qué hay en esta máquina.** `uv run python scripts/sondear.py` (o `pwsh scripts/sondear.ps1`).
   Si falta GDAL, PDAL, Office, Tesseract o ODA, **dilo y detente** en lo que dependa de ello. No
   saltes la prueba en silencio ni la sustituyas por otra.
2. **Corre.** `uv run pytest -m oraculo $ARGUMENTS`. Solo corre en una máquina con GDAL/PDAL; el
   gate normal las deselecciona a propósito. El CI las corre los lunes a las 06:00 (`oraculo.yml`).
3. **Anota.** En `docs/PRUEBAS_CON_ORACULO.md`, una sección nueva con la **fecha**, la herramienta y
   su versión, el archivo de prueba y **cifras** (no «pasó»): bandas, estadísticas, puntos, sha256.
4. **El original quedó intacto:** confirma `sha256` y `mtime` antes y después, también tras un fallo.
5. **Si no hay oráculo posible** (ECW exige clave OEM), documenta el procedimiento manual con cifras
   fechadas. No lo inventes.
6. Informa: qué se corrió, versión del oráculo, cifras y qué no se pudo correr aquí.
