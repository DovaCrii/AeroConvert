# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia está en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-09 · **Versión:** `0.13.0` · **Último PR fusionado:** #113

## Quién hace qué

**Claude hace todo lo de git**: ramas `codex/…`, PR con `--body-file`, fusiones **solo con el CI
verde** (el agente `fusionador-de-pr` espera el CI). **Usted despliega en p340.** Si el CI cae con
`not acquired by Runner`, es la infraestructura: `gh run rerun <id>`.

## Dónde está

- **Desplegado en p340:** hasta el #98 (`4321107`). **En `main` sin desplegar: #99 a #113.**
- **Dirección visual (D8):** «Plan de vuelo» en toda la app (`docs/DISENO_PLAN_DE_VUELO.md`, F13.14).
  **Los vuelos de dron viven en `apps/vuelos/`** (F18.13); la cola, la entrada y las URL `documents:…`
  siguen en `apps/documents/` (`test_independencia.py` vigila).
- **«Ver en el mapa» (`/mapa/`, `apps/visor/`):** teselas, terreno, varias capas con orden y
  transparencia, vuelos propios y mapa base de la casa (F19.1 a F19.5). Abierto: F19.6 (contrato con
  AeroBim) y los puntos de control, que «Corregir un vuelo» aún no escribe (F18.14).
- También en esta tanda: alturas con geoide declarado (F15.2), escanear con el teléfono (F14.12), libro
  EPUB (F14.22), vuelos RTK y ficha EXIF (F18.8 a F18.10), PPK desde RINEX (F18.7), `runner.py` partido
  (F11.8) y `original-modificado` (regla 5). 42 herramientas de documentos; más de 4.400 pruebas.

## Desplegar en p340 (lo hace usted)

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
sudo systemctl restart aeroconvert aeroconvert-obrero
```

- **Migración nueva:** `apps/jobs/migrations/0006_papeles_del_ppk.py` (la aplica `desplegar.sh`).
- **Apps nuevas:** `apps.vuelos` (los vuelos, movidos desde `apps/documents`, mismas URL) y
  `apps.visor` (`/mapa/`). No piden nada aparte.
- **Variables nuevas del `.env`, todas opcionales:**
  `AEROCONVERT_VISOR_CACHE` (carpeta de la caché de teselas; vacío: `cache-visor/` junto al código),
  `AEROCONVERT_VISOR_CACHE_MAX_MB=512`, `AEROCONVERT_VISOR_MAPA_BASE` (rutas `.tif` de la casa dentro
  de las raíces, `Nombre=ruta;…`; vacío: retícula) y `AEROCONVERT_PROJ_GRILLAS` (carpeta con
  `us_nga_egm08_25.tif` y `us_nga_egm96_15.tif`; sin ellas, las alturas salen apagadas con su motivo).
- **Programas que se sondean:** `gdalwarp`, `gdaldem` y `gdallocationinfo` (vienen con GDAL, ya en
  p340); `rnx2rtkp` (RTKLIB, instalado el 2026-10-09 con `instalar_faltantes.sh`); las grillas de
  geoide, que **no se descargan solas**.

**Después de desplegar:**
1. Abrir `/motores/equipo/` (dice qué quedó apagado y el paso exacto) y `/mapa/`.
2. Aceptación a mano desde la interfaz (el `.venv` de p340 va con `--no-dev`: no trae pytest, y no se
   le instala). Lo que aquí no se pudo medir con el programa real: **Escanear** (Tesseract), un
   **vuelo con RTKLIB real**, un `.docx` a PDF (LibreOffice), un video corto a fotogramas (FFmpeg) y
   un `.mdb` a CSV (mdbtools). Procedimientos en `docs/PRUEBAS_CON_ORACULO.md`.
   veraPDF no está en apt: PDF/A sale sin validar hasta instalarlo a mano.
3. La API (`jobs.usar_api` y `manage.py emitir_token_api <usuario>`, ver `docs/API.md`) y
   `resumen_de_uso --dias 7` durante 2 o 3 semanas: con esas cifras se ordena lo que viene.

**Aviso de CI:** `ubuntu-latest` pasa a Ubuntu 26 el 2026-10-19 (p340 ya lo es): revise la primera corrida.

## El plan

`python scripts/claude/plan_fila.py --abiertas` y el tablero en `docs/planes/SEGUIMIENTO.md`.

| Abierto | Qué falta | Quién |
| --- | --- | --- |
| F14.9 ⚠ · F14.12 ⚠ · F14.17 ⚠ · F17.1 ⚠ · F17.2 ⚠ | Hechos; se miden en p340 con el programa real | Usted despliega; Claude anota |
| F14.22 ⚠ · F14.11 | EPUB sin EPUBCheck · visor PDF.js | Esperan P17 y P11 |
| F14.15 · F14.16 (SVG) | Quitar fondo, SVG con Inkscape | Claude |
| F15.1 a F15.4 · F15.8 · F15.6 (DWG) | Datums, calibración, perfiles mineros, ODA | Esperan P5, P6, P7 |
| F15.2 ⚠ · F15.5 · F15.7 · F16.5 | EGM2008 sin su grilla, más perfiles, TIN, AeroBim | Claude (F16.5 con AeroBim) |
| F18.3 ⚠ · F18.7 ⚠ · F18.8 ⚠ | PPK y RTK reales | Esperan P18 (altura elipsoidal de `AUX_01`) y P20 (vuelo RTK) |
| F18.11 · F18.12 · F18.14 | Coordenadas con DC, aspecto de vuelos, puntos de control en `vuelo.json` | F18.11 espera P19; las otras, Claude |
| F19.6 · F11.8 (resto) · F10.5 · F1.6 · F2.6 · F4.1 · F4.2 | Contrato con AeroBim, `dashboard/acciones`, Trimble bajo Wine, ECW, 3D Tiles, IFC | Sin fecha |

## Lo que es suyo

Pedidos P5 a P21 en `SEGUIMIENTO.md`; los vigentes: **P18** (altura elipsoidal de `AUX_01`), **P19**
(archivo DC), **P20** (vuelo RTK real), **P17** (EPUBCheck), **P21** (grilla EGM2008), **P11**
(PDF.js), **P7** (ODA), **P5** y **P6** (puntos de control y archivos mineros). **Copia de respaldo
fuera de la máquina** y **¿el repositorio sigue público?** (este archivo dice rutas de p340).

## Trampas vigentes

- El código de salida no prueba nada; se verifica la salida con otro lector. El CRS no se adivina.
- **Suite completa antes de cada push** con `$env:AEROCONVERT_GDAL_BIN = ""; $env:AEROCONVERT_PDAL_BIN
  = ""; uv run pytest -q --no-cov`, en segundo plano (~14 min). Pruebas con GDAL real:
  `@pytest.mark.oraculo`, con QGIS 4.0.2 en el PATH.
- **La configuración del `.env` no llega sola a un proceso hijo** (`python-decouple` no la copia a
  `os.environ`, y los servicios no tienen `EnvironmentFile`): el padre la lee de `settings` y la pasa.
- **`fusionar_main.py` resuelve «los dos añadieron»**; después de usarlo, `manage.py check` y la
  suite. Un archivo con bytes nulos es «binario» para git: `test_changelog.py` lo vigila.
- `gdal_contour -f DXF -3d` escribe sin cota (pasa por un GeoPackage 3D). `runserver --noreload` no recarga plantillas; `Select-Object -First N` sobre un servidor lo mata.

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido
python scripts/claude/plan_fila.py --abiertas
```

Historial: [`docs/historial/HANDOFF-hasta-2026-10-09.md`](docs/historial/HANDOFF-hasta-2026-10-09.md)
