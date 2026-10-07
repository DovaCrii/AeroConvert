# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia detallada vive en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-07 · **`main` en:** `c551dcd` · **Último PR fusionado:** #56

## Quién hace qué

**Claude hace todo lo de git**: ramas, commits, push, PR y fusiones a `main` con el CI verde
(`/abrir-pr`, igual que en AeroBim). **Usted despliega en p340.** Sin commit ni push directo a
`main`; cada PR va contra `main`, no apilado. El permiso de `gh pr merge` va en
`.claude/settings.local.json` (ya creado en su máquina; el agente no puede concedérselo).

**El CI de GitHub falla a veces con `The job was not acquired by Runner`**: es la infraestructura.
Se relanza con `gh run rerun <id>`; no se fusiona con el CI en rojo.

## Dónde está el proyecto

- **Desplegado el 2026-10-05:** hasta el #20 (GNSS con RTKLIB, calidad y versiones de RINEX).
- **En `main` sin desplegar** (#21 a #63): versión `0.11.0` (cierra F13); el lateral de navegación con modo de
  iconos y ancho a mano; nombres por utilidad; baldosas con color en oscuro; la portada con grupos
  plegables; «Organizar páginas» y «Seguir con este archivo» (#54); la paleta en OKLCH; tipografía,
  radios e iconos desde la escala; cierres de la auditoría y B-04 (VRT disfrazado); `Incidente` y
  `resumen_de_uso`; cobertura de la cola.
- **Dos migraciones nuevas** (`core/0002`, `core/0003`) que `desplegar.sh` aplica sola. Pruebas:
  ~2.780 verdes sin GDAL ni PDAL. 25 herramientas de documentos.

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
```

## El plan que se ejecuta ahora

**`docs/planes/PLAN_2026-10-07.md`** → `MASTER_PLAN.md` **F13 a F16** (decidido el 2026-10-07):
F13 interfaz, F14 suite documental, F15 datums de Chile, F16 lotes y API. **Ejecuta Claude** con
**`/avanzar`**; el tablero y **lo que se le pide a usted** están en `docs/planes/SEGUIMIENTO.md`.
Usted despliega **al final de todo**. Versión `0.11.0` al cerrar F13.

## Filas abiertas (`python scripts/claude/plan_fila.py --abiertas`)

| Fila | Qué falta | Quién |
| --- | --- | --- |
| `F13.1` a `F13.12` | La interfaz, en el orden del plan (§8) | Claude |
| `F14` (menos `F14.10`) · `F15` · `F16` | Suite, geoespacial y plataforma | Claude; la persona aporta plantilla J.E.J., puntos de control y archivos de Deswik/Vulcan |
| `F10.5` | Convertidor de Trimble bajo Wine en p340 (pasos abajo) | Usted |
| `F3.5` ◐ · `F3.4` | LandXML real; DWG/DGN con ODA instalado (= `F15.7`, `F15.8`) | Un archivo o un puesto con ODA |
| `F2.6` · `F4.1` | 3D Tiles; IFC y malla | Código |
| `F1.6` | ECW: no, hasta que alguien lo pida dos veces | Decisión |
| `F11.8` | `runner.py` e `inspeccionar`: bloqueada hasta que el uso lo pida | — |

## Pasos en p340 (suyos)

- **F10.5.** Copie el MSI (`convertToRinex_v4_0_1_10_sign.msi`, en `Downloads`) a `/tmp` y:
  `sudo apt install msitools` · `sudo mkdir -p /opt/trimble-rinex && sudo msiextract -C
  /opt/trimble-rinex /tmp/convertToRinex_v4_0_1_10_sign.msi` · `find /opt/trimble-rinex -name
  convertToRinex.exe`. En `.env`: `AEROCONVERT_TRIMBLE_RINEX=<esa ruta>` y
  `AEROCONVERT_WINEPREFIX=/var/lib/aeroconvert/wine`. Pruébelo con un T02 desde la web.
- **Después de desplegar:** `sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py
  resumen_de_uso --dias 7`, y **repetirlo durante 2 o 3 semanas**: con esas cifras se decide el
  orden de lo que viene después de F13 (sin despliegue no hay cifras que mirar).

## Cabos con fecha

- Pasada de teclado de F9.3, sin ratón, por la barra, el lateral y un formulario, en los dos temas.
- En `p340`: subir un PDF a cada herramienta; confirmar que una contraseña no queda en
  `jobs_conversionjob`, `jobs_jobevent` ni `jobs_entradadetrabajo`.
- Propuestas para `AGENTS.md`, sin aplicar (regla suya): regla 3 con coordenadas locales; fila GNSS.

## Lo que es suyo

- **Copia de respaldo fuera de la máquina:** lo único sin arreglo posible después.
- **Desplegar**: la lista de arriba crece con cada PR (#21 a #54 y subiendo).
- **¿El repositorio sigue público?** Este archivo expone rutas, puerto y la carpeta compartida de
  p340; si sigue público, esos datos pasan a un archivo fuera del repositorio.
- Office en el servidor (apagado con su motivo) · ECW · el correo no único en `auth.User`.
- Tino está apagado y sin rastro (404); `AEROCONVERT_TINO_VISIBLE=true` lo enciende.

## Trampas vigentes

- El código de salida de un motor no prueba nada; se verifica la salida. El CRS no se adivina.
- **El CI no tiene GDAL ni PDAL y la estación sí:** `$env:AEROCONVERT_GDAL_BIN = "";
  $env:AEROCONVERT_PDAL_BIN = ""; uv run pytest`.
- **Antes de cada push, la suite completa** (`uv run pytest -q --no-cov`, en segundo plano), no solo
  las apps tocadas: añadir una herramienta dejó el #54 en rojo porque un sinónimo le quitó la
  pregunta a otra y Tino (`apps/tino`) dejó de contestar. Sin esperas con `sleep`: el aviso llega solo.
- El registro de motores es global: una fixture automática (`conftest.py`) lo guarda y lo
  restaura alrededor de cada prueba (ver `test_aislamiento_del_registro.py`).
- `gh pr create` con `/T` o `/convertir/` en el texto lo bloquea la herramienta: `--body-file`.

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido      # segundos
uv run python scripts/claude/verificar.py todo        # lo que corre el CI
python scripts/claude/plan_fila.py --abiertas         # qué sigue
```

Historial: [`docs/historial/HANDOFF-hasta-2026-10-05.md`](docs/historial/HANDOFF-hasta-2026-10-05.md)
