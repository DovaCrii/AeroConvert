# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia detallada vive en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-05 · **`main` en:** `b36a395` · **Último PR fusionado:** #28

## Quién hace qué

**Claude hace todo lo de git**: ramas, commits, push, PR y fusiones a `main` con el CI verde
(`/abrir-pr`, igual que en AeroBim). **Usted despliega en p340.** Sin commit ni push directo a
`main`; cada PR va contra `main`, no apilado.

**Una cosa que solo usted puede hacer:** el agente no puede concederse a sí mismo el permiso de
`gh pr merge`. Cree `.claude/settings.local.json` (ya está en `.gitignore`) con
`{"permissions": {"allow": ["PowerShell(gh pr merge *)", "Bash(gh pr merge:*)"]}}`, como en
AeroBim. Hasta entonces las fusiones funcionaron pidiendo el permiso en cada sesión.

**El CI de GitHub falla a veces con `The job was not acquired by Runner`**: es la infraestructura,
no el código. Se relanza con `gh run rerun <id>` y se espera; no se fusiona con el CI en rojo.

## Dónde está el proyecto

- Desplegado en `p340` (publicado por Tailscale Funnel): dos servicios y el temporizador de
  respaldo (03:15). F9.0 – F9.2 se desplegaron el 2026-09-25.
- **Desplegado el 2026-10-05 a las 15:01:** hasta el #20 (GNSS con RTKLIB, calidad de RINEX y
  RINEX a otra versión, todo menos lo que sigue).
- **En `main` y sin desplegar:** la versión `0.10.0`, «Seguir donde lo dejaste» plegable, el
  arreglo del motor RTKLIB (**sin él `rtklib-convbin` falla con un trabajo real**: desplegar),
  los cierres de la auditoría (F11.9 y casi todo F11.10) y `documents/views/` en paquete.
- Pruebas: 2.360 aprox. verdes sin GDAL ni PDAL (2026-10-05, última corrida completa 2.349 antes
  de F11.10).
- Versión: `0.10.0` en `pyproject.toml`, README y CHANGELOG (F11.4, 2026-10-05).

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
| `F10.6` – `F10.8` ✅ | `convbin`, calidad de RINEX y RINEX a otra versión: hechos. Falta medir un flujo real UBX, SBF o RT17 en p340 | Usted + un archivo |
| `F11.10` 🟨 | Faltan A-05 (cuota de subidas por usuario) y A-01 (cuerpo anónimo de 2 GB, toca nginx) | Código y usted |
| `F11.11` | En p340: la prueba de `X-Forwarded-For` ante Funnel, el valor de `AEROCONVERT_RAICES_PERMITIDAS`, y un VRT `.asc` ante la GDAL desplegada (B-04) | Usted |
| `F11.6` | Prueba de diseño de tres brazos antes de F9.4: pide descargar `ui-ux-pro-max`, Ponytail e `impeccable` | Su sí a las descargas |
| `F2.6` · `F4.1` · `F4.2` | 3D Tiles; IFC y malla; AeroBim | Código |
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
