# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia detallada vive en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-05 · **`main` en:** `1caa449` · **Último PR fusionado:** #12

## Quién hace qué

**Claude hace todo lo de git**: ramas, commits, push, PR y fusiones a `main`. **Usted despliega
en p340.** Sin commit ni push directo a `main`; cada PR va contra `main`, no apilado.

## Dónde está el proyecto

- Desplegado en `p340` (publicado por Tailscale Funnel): dos servicios y el temporizador de
  respaldo (03:15). F9.0 – F9.2 se desplegaron el 2026-09-25.
- **En `main` y sin desplegar:** F9.3 (contraste y foco), coordenadas locales para nubes, Tino
  apagado, dependencias parcheadas, CI sin GDAL y la **Fase 10 (GNSS, Trimble a RINEX)** completa
  salvo F10.5.
- Pruebas: 2.289 recogidas, 3 con oráculo deseleccionadas (2026-10-05, `pytest --collect-only`).
- Versión: README `v0.3.0-alpha`, `pyproject.toml` y CHANGELOG `0.1.0`. Está en la fila F11.4.

Para desplegar (dentro de p340; no hay migraciones nuevas):

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
```

## Filas abiertas (`python scripts/claude/plan_fila.py --abiertas`)

| Fila | Qué falta | Quién la cierra |
| --- | --- | --- |
| `F10.5` | Wine en p340: copiar el MSI (hay uno firmado 4.0.1.10 en `Downloads`, ya probado en Windows), `apt install wine xvfb`, `AEROCONVERT_TRIMBLE_RINEX` y `AEROCONVERT_WINEPREFIX`, y fechar la corrida | Usted (licencia de Trimble) |
| `F9.4` · `F9.5` · `F9.6` | Lo visual; paleta en OKLCH; `Incidente` y `resumen_de_uso` | Código |
| `F7.2c` | Tarjetas en la pantalla de convertir | Código |
| `F3.5` ◐ · `F3.4` | LandXML real; DWG/DGN con ODA instalado | Un archivo o un puesto con ODA |
| `F2.6` · `F4.1` · `F4.2` · `F10.6` | 3D Tiles; IFC y malla; AeroBim; `convbin` | Código |
| `F1.6` | ECW: no, hasta que alguien lo pida dos veces | Decisión |
| Fase 11 | Proceso de agentes y base de código (kit, gates, versión, auditoría, refactor) | Código y usted |

## Cabos con fecha

- Retirar el modelo `Resultado` (`apps/core/models.py:120`) y la vista `documents:descargar`
  (`apps/documents/urls.py:40`): siguen en el código; falta esperar a que caduquen sus filas.
- Pasada de teclado de F9.3, sin ratón, por la barra y un formulario, en los dos temas.
- En `p340`: subir un PDF a cada herramienta y descargarlo desde la ficha; confirmar que una
  contraseña no queda en `jobs_conversionjob`, `jobs_jobevent` ni `jobs_entradadetrabajo`.
- Propuestas para `AGENTS.md`, sin aplicar por ser regla suya: en la regla 3, que «coordenadas
  locales declaradas por una persona» es una respuesta y no un hueco; en la tabla de oráculos,
  una fila GNSS («sin oráculo externo para el crudo»).

## Lo que es suyo

- **Copia de respaldo fuera de la máquina:** el servicio escribe en el mismo NVMe que la base. Es
  lo único de la lista **sin arreglo posible después**.
- Office en el servidor (apagado con su motivo) · ECW · el correo no único en `auth.User`.
- Tino está apagado y sin rastro (404); `AEROCONVERT_TINO_VISIBLE=true` lo vuelve a encender.

## Trampas vigentes

- El código de salida de un motor no prueba nada; se verifica la salida.
- El CRS no se adivina; `check --deploy` se corre con el módulo de producción fijado.
- **El CI no tiene GDAL ni PDAL y la estación sí.** Para ver lo que ve el CI:
  `$env:AEROCONVERT_GDAL_BIN = ""; $env:AEROCONVERT_PDAL_BIN = ""; uv run pytest`.
- Hay tres gates (`verify.ps1`, `verificar.sh`, `ci.yml`) y no dicen lo mismo (fila F11.3).
- Seis pruebas dependen del equipo (Tesseract sin `spa`, poca RAM): fila F11.2.

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido      # segundos
uv run python scripts/claude/verificar.py todo        # lo que corre el CI
python scripts/claude/plan_fila.py --abiertas         # qué sigue
```

## Historial

- Hasta 2026-10-05: [`docs/historial/HANDOFF-hasta-2026-10-05.md`](docs/historial/HANDOFF-hasta-2026-10-05.md)
