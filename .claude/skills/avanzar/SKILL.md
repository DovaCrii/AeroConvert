---
name: avanzar
description: Avanza el plan de AeroConvert por bloques - elige filas sin bloqueo, las encarga en paralelo a los agentes según el modelo que toque, revisa lo que vuelve y lo publica con /publicar. Lo que necesita de la persona lo anota y sigue con lo que sí puede. Despliegue solo al final.
disable-model-invocation: true
argument-hint: "[bloque o fila, p. ej. B16, F21.5; vacío = lo siguiente sin bloqueo]"
---

# Avanzar el plan

El plan está en `MASTER_PLAN.md` (por filas: `python scripts/claude/plan_fila.py F21.5 --seccion` y
`--abiertas`) y **el estado por bloques y lo que se le pide a la persona viven en
`docs/planes/SEGUIMIENTO.md`**. `HANDOFF.md` solo lo apunta.

**Quién hace qué:** Claude hace ramas, commits, push, PR, revisión y fusiones con el CI verde. **La persona
solo despliega en `p340`**, al final o cuando lo diga. Esta skill **nunca** despliega ni toca el servidor.

## Reparto de modelos

**Coordina Opus con esfuerzo medio** (o el modelo que la persona fije): elige la fila, escribe el encargo,
revisa lo que vuelve, resuelve las fusiones con `main` y habla con la persona. **No implementa filas grandes
él mismo.** Cada agente se lanza con `effort: "medium"` y, si escribe código, con `isolation: "worktree"`.

| Agente (`.claude/agents/`) | Modelo | Cuándo |
| --- | --- | --- |
| `explorador` | Haiku | Antes de planificar o renombrar: dónde vive algo y qué pruebas lo fijan |
| `investigador` | Sonnet | Antes de adoptar una biblioteca, un servicio o el flujo de otro producto |
| `implementador` | Sonnet | Cada fila de código, en su rama y worktree; deja commit sin push |
| `disenador` | Sonnet | Tokens, contraste, tipografía, ilustraciones y maquetas |
| `revisor-de-reglas` | Sonnet | Filas que tocan motores, firmas, datos sensibles, permisos o **salida de datos** |
| `fusionador-de-pr` | Haiku | Esperar el CI **del commit de cabeza** y fusionar en verde |

## El ciclo

1. **Ponerse al día.** `HANDOFF.md`, `SEGUIMIENTO.md`, `git checkout main && git pull`, `gh pr list` y los
   worktrees de `.claude/worktrees/` (ramas terminadas sin PR). Si el árbol tiene cambios que no son suyos,
   **parar y preguntar**.
2. **Elegir** las filas cuya siguiente tarea **no esté bloqueada** por un dato o una decisión de la persona.
   Varias independientes van **en paralelo**; las que tocan los mismos archivos, una tras otra.
3. **Encargar.** Un agente por fila, con la plantilla de `.claude/agents/ENCARGO.md` (rol, rama
   `codex/<fila>` desde `origin/main`, la fila y su oráculo, qué devolver). Las piezas repetidas están en
   skills: `/nuevo-motor`, `/nueva-herramienta`, `/refactor-seguro`, `/mirar-pantalla`.
4. **Revisar lo que vuelve.** Lea el resumen **y** el diff; lo que los agentes dan por hecho se comprueba
   (suite, pantallas, oráculo). Si toca motores, datos sensibles o salida a internet:
   `revisor-de-reglas`, y lo que encuentre vuelve al mismo agente.
5. **Publicar** con `/publicar <rama>`: trae `main`, marca la fila, suite completa, PR y `fusionador-de-pr`.
6. **Seguir.** Al terminar un bloque, el informe corto: filas cerradas con su PR, **pedidos a la persona
   arriba**, lo que no se pudo comprobar aquí (queda para `p340`), y los PR sin desplegar.

## Cuando hace falta algo de la persona

**No se detiene el avance por eso.** Se anota en «Pedidos a la persona» de `SEGUIMIENTO.md` (qué, para qué
fila, en qué forma y qué pasa si no llega), la fila queda ⏸ con su motivo, y se sigue con la siguiente que
sí se puede. No se inventa el dato ni se elige por ella lo que es suyo. Lo que cambia lo que se hace después
se consulta con `AskUserQuestion`.

## El final de todo

Subir la versión, dejar `HANDOFF.md` con los pasos exactos de la VM (migraciones, variables del `.env`,
programas por instalar) y **entregar la lista para desplegar**. Ella la ejecuta; después, `resumen_de_uso`.

## Trampas de esta máquina (ya costaron tiempo)

- PowerShell bloquea por falso positivo comandos con ciertos textos: los textos largos se escriben con
  `Write` a un archivo y se aplican con un script de Python o con `Edit`, no con `-replace` en una línea.
  **Cambios en código y pruebas con `Edit`** o un script que compruebe que cada reemplazo casa.
- `[IO.File]::ReadAllText("ruta/relativa")` resuelve desde el directorio del **proceso**, no desde
  `Push-Location`: en un worktree, rutas absolutas. `R` es un alias de PowerShell.
- **Lo que pasa en Windows tiene que pasar en Linux** (CI y `p340`): tres PR quedaron en rojo por una ruta de
  Windows que `os.path.basename` no parte y por archivos de prueba con CRLF. `newline="\n"`; rutas por `\` y `/`.
- El CI no tiene GDAL, PDAL, Access, Office ni Tesseract: variables vacías al correr `pytest` y **los dos casos
  forzados con `monkeypatch`** en toda prueba que mire lo que se ve en pantalla.
- Un PR que **añade herramientas** o toca el plan choca con el siguiente: `fusionar_main.py` y subir **de uno
  en uno**. GitHub a veces falla al fusionar (`HTTP 500`): reintentar a los 60 s; `gh pr checks --watch`
  dice «no checks reported» antes de que el CI se registre: esperar 30 s.
- El puerto 8765 a veces lo ocupa otro proyecto (AeroAcademy): `/mirar-pantalla` usa otro puerto.
- `ruff` y `bandit` miran cosas distintas: `try/except/pass` (B110) y `xml.sax.saxutils` (B406) los caza
  solo `bandit`. `.claude/rules/` recoge las reglas de interfaz, motores y plan: léalas antes de tocar una
  pantalla o un motor.

## Lo que esta skill no hace

No despliega, no toca `p340`, no cambia `AGENTS.md` salvo lo que la persona ya decidió, no instala programas
del sistema, no sube datos reales ni claves al repositorio y no decide por la persona lo que está en «Lo que
solo podías decidir tú».
