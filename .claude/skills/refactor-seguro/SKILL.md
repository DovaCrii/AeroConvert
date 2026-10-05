---
name: refactor-seguro
description: Refactor de AeroConvert sin cambio de comportamiento - línea base, pruebas de caracterización, movimiento mecánico con re-exportación y comparación antes/después.
disable-model-invocation: true
argument-hint: "<archivo o módulo a dividir>"
---

# Refactor seguro: `$ARGUMENTS`

La aplicación está desplegada y funciona. Un refactor cambia estructura, nunca comportamiento. Si ves
un defecto, **anótalo aparte**; no lo arregles en el mismo cambio.

1. **Alcance.** Qué mueves y por qué, en tres líneas. Si toca `apps/jobs/runner.py`, un motor, la
   verificación de salidas o el manejo de CRS, **detente y pregunta**: ahí se juega la regla 1, 3 y 5.
2. **Línea base.** `/verificar todo` en verde. Anota: pruebas recogidas y pasadas (hoy ≈2.265), cobertura
   total, líneas por archivo y la lista de URL resueltas (un script con `get_resolver`, guardada fuera
   del repo).
3. **Red de seguridad.** Si lo que mueves no tiene pruebas que lo cubran, escribe **primero** pruebas
   de caracterización y confirma que pasan sobre el código intacto.
4. **Movimiento mecánico.** Un movimiento por commit; sin renombrar ni «mejorar». **Re-exporta** desde
   el lugar original (`__init__.py`) para que ningún importador ni URL cambie.
5. **Tras cada movimiento:** `/verificar pruebas apps/<área>`. El número de pruebas **no baja**, la
   cobertura **no baja** (`fail_under = 83` es un piso) y la lista de URL es idéntica.
6. **No** añadas `# pragma: no cover` para salvar un número.
7. **Pruebas de «original intacto»** (`sha256`/`mtime` por camino de fallo) siguen verdes y no se
   debilitan.
8. **PR pequeño, contra `main`,** con números antes/después y la lista de defectos que viste y **no**
   tocaste. No fusiones.
