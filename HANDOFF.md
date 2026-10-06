# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia detallada vive en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-06 · **`main` en:** `b82a35a` · **Último PR fusionado:** #40

## Quién hace qué

**Claude hace todo lo de git**: ramas, commits, push, PR y fusiones a `main` con el CI verde
(`/abrir-pr`, igual que en AeroBim). **Usted despliega en p340.** Sin commit ni push directo a
`main`; cada PR va contra `main`, no apilado. El permiso de `gh pr merge` va en
`.claude/settings.local.json` (ya creado en su máquina; el agente no puede concedérselo).

**El CI de GitHub falla a veces con `The job was not acquired by Runner`**: es la infraestructura.
Se relanza con `gh run rerun <id>`; no se fusiona con el CI en rojo.

## Dónde está el proyecto

- **Desplegado el 2026-10-05:** hasta el #20 (GNSS con RTKLIB, calidad y versiones de RINEX).
- **En `main` sin desplegar** (#21 a #40): versión `0.10.0`; los destinos de la ficha como tarjetas; **arreglo del motor RTKLIB** (sin él
  `rtklib-convbin` falla con un trabajo real); la portada con grupos plegables; el resultado de una
  conversión y la barra a 375 px; el menú «Herramientas» y el límite de subida; cierres de la
  auditoría (A-01, A-02, A-05, B-01, B-07, B-08, C-01, C-06, D-01, D-02, D-04, D-05); `views/` en
  paquete; `Incidente` y `resumen_de_uso`.
- **Dos migraciones nuevas** que `desplegar.sh` aplica sola: `core/0002` (borra la tabla
  `Resultado`) y `core/0003` (crea `Incidente`).
- Pruebas: ~2.400 verdes sin GDAL ni PDAL. Versión `0.10.0`.

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
```

## Filas abiertas (`python scripts/claude/plan_fila.py --abiertas`)

| Fila | Qué falta | Quién |
| --- | --- | --- |
| `F10.5` | Convertidor de Trimble bajo Wine en p340 (pasos abajo) y fechar la corrida | Usted |
| `F11.11` | Tres pruebas en p340: `X-Forwarded-For` ante Funnel, `AEROCONVERT_RAICES_PERMITIDAS`, VRT `.asc` (B-04) | Usted |
| `F9.4` | Faltan profundidad, radios, iconos y tipografía | Código |
| `F3.5` ◐ · `F3.4` | LandXML real; DWG/DGN con ODA instalado | Un archivo o un puesto con ODA |
| `F2.6` · `F4.1` · `F4.2` | 3D Tiles; IFC y malla; AeroBim | Código |
| `F1.6` | ECW: no, hasta que alguien lo pida dos veces | Decisión |
| `F11.8` | `runner.py` e `inspeccionar`: bloqueada hasta que el uso lo pida | — |

## Pasos en p340 (suyos)

- **F10.5.** Copie el MSI (`convertToRinex_v4_0_1_10_sign.msi`, en `Downloads`) a `/tmp` y:
  `sudo apt install msitools` · `sudo mkdir -p /opt/trimble-rinex && sudo msiextract -C
  /opt/trimble-rinex /tmp/convertToRinex_v4_0_1_10_sign.msi` · `find /opt/trimble-rinex -name
  convertToRinex.exe`. En `.env`: `AEROCONVERT_TRIMBLE_RINEX=<esa ruta>` y
  `AEROCONVERT_WINEPREFIX=/var/lib/aeroconvert/wine`. Pruébelo con un T02 desde la web.
- **F11.11.** `sudo grep AEROCONVERT_RAICES_PERMITIDAS /opt/aeroconvert/.env`; y las otras dos
  pruebas, que Claude le prepara cuando quiera.
- **Después de desplegar:** `sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py
  resumen_de_uso --dias 7` da la primera línea base del uso.

## Cabos con fecha

- Pasada de teclado de F9.3, sin ratón, por la barra y un formulario, en los dos temas.
- En `p340`: subir un PDF a cada herramienta; confirmar que una contraseña no queda en
  `jobs_conversionjob`, `jobs_jobevent` ni `jobs_entradadetrabajo`.
- Propuestas para `AGENTS.md`, sin aplicar por ser regla suya: la regla 3 (coordenadas locales
  declaradas por una persona son una respuesta) y una fila GNSS en la tabla de oráculos.

## Lo que es suyo

- **Copia de respaldo fuera de la máquina:** lo único sin arreglo posible después.
- Office en el servidor (apagado con su motivo) · ECW · el correo no único en `auth.User`.
- Tino está apagado y sin rastro (404); `AEROCONVERT_TINO_VISIBLE=true` lo enciende.

## Trampas vigentes

- El código de salida de un motor no prueba nada; se verifica la salida. El CRS no se adivina.
- **El CI no tiene GDAL ni PDAL y la estación sí:** `$env:AEROCONVERT_GDAL_BIN = "";
  $env:AEROCONVERT_PDAL_BIN = ""; uv run pytest`.
- El registro de motores es global: una fixture automática (`conftest.py`) lo guarda y lo
  restaura alrededor de cada prueba. Sin ella, una prueba que lo vaciaba contaminaba a las demás
  según el orden (resuelto el 2026-10-06; ver `test_aislamiento_del_registro.py`).
- Los comandos de `gh pr create` con `/T` o `/convertir/` en el texto los bloquea la herramienta:
  el cuerpo va en un archivo (`--body-file`).

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido      # segundos
uv run python scripts/claude/verificar.py todo        # lo que corre el CI
python scripts/claude/plan_fila.py --abiertas         # qué sigue
```

Historial: [`docs/historial/HANDOFF-hasta-2026-10-05.md`](docs/historial/HANDOFF-hasta-2026-10-05.md)
