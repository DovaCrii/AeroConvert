# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia está en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-08 · **Versión:** `0.12.0` · **Último PR fusionado:** #97

## Quién hace qué

**Claude hace todo lo de git**: ramas `codex/…`, PR con `--body-file`, fusiones **solo con el CI
verde** (el agente `fusionador-de-pr` espera el CI). **Usted despliega en p340.** Si el CI cae con
`not acquired by Runner`, es la infraestructura: `gh run rerun <id>`.

## Dónde está

- **Desplegado (2026-10-05):** hasta el #20. **En `main` sin desplegar: #21 a #97.**
- 40 herramientas de documentos en nueve grupos; ~4.400 pruebas verdes sin GDAL ni PDAL.
- Lo de esta tanda: vuelos de dron con PPK y visor, curvas de nivel, paquetes y lotes, API con token,
  firma con sello de tiempo, PDF/A, video de dron, LibreOffice y `mdbtools` donde no hay Office ni
  Access, la pantalla «Cómo dejar listo el equipo» y `instalar_faltantes.sh`.

## Desplegar (lo hace usted, en este orden)

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
sudo despliegue/instalar_faltantes.sh --ver      # ver qué instalaría
sudo despliegue/instalar_faltantes.sh            # Tesseract, RTKLIB, FFmpeg, Ghostscript,
                                                 # Inkscape, mdbtools, LibreOffice, xvfb
sudo systemctl restart aeroconvert aeroconvert-obrero
```

`desplegar.sh` hace `uv sync`, **las ocho migraciones nuevas** (`core.0002` a `0004`,
`engines.0001`, `jobs.0003` a `0005`, `presets.0002`), `collectstatic` y `sembrar_preajustes`.

**Variables nuevas del `.env`, todas opcionales** (sin ellas, lo que dependa sale apagado con su
motivo; con `instalar_faltantes.sh` casi ninguna hace falta porque los programas quedan en el PATH):
`AEROCONVERT_PLANTILLAS_JEJ`, `AEROCONVERT_CUOTA_DE_SUBIDAS_MB`, `AEROCONVERT_RAICES_DE_CONFIANZA`,
`AEROCONVERT_TSA_URL`, `AEROCONVERT_RTKLIB_RNX2RTKP`, `AEROCONVERT_LIBREOFFICE`,
`AEROCONVERT_GHOSTSCRIPT`, `AEROCONVERT_VERAPDF`, `AEROCONVERT_FFMPEG`, `AEROCONVERT_MDBTOOLS`,
`AEROCONVERT_LOG_LEVEL`.

**Después de desplegar:**
1. Abrir `/motores/equipo/`: dice qué quedó apagado y el paso exacto de cada cosa.
2. Aceptación a mano (el `.venv` de p340 va con `--no-dev`: no trae pytest, y no se le instala):
   un `.docx` a PDF, un video corto a fotogramas y un `.mdb` a CSV desde la interfaz, y el
   procedimiento de catálogos de `docs/PRUEBAS_CON_ORACULO.md`. veraPDF no está en apt: PDF/A sale
   sin validar hasta instalarlo a mano. (2026-10-09: los ocho programas de apt quedaron en el PATH.)
3. La API: dar el permiso `jobs.usar_api` a quien la use y `manage.py emitir_token_api <usuario>`
   (ver `docs/API.md`).
4. `resumen_de_uso --dias 7` durante 2 o 3 semanas: con esas cifras se ordena lo que viene.

## El plan

`python scripts/claude/plan_fila.py --abiertas` y el tablero en `docs/planes/SEGUIMIENTO.md`.

| Abierto | Qué falta | Quién |
| --- | --- | --- |
| F14.9 ⚠ · F14.17 ⚠ · F17.1 ⚠ · F17.2 ⚠ | Hechos; se miden en `p340` con el programa real (veraPDF no está) | Usted despliega; Claude anota |
| F14.11 | Visor PDF.js | Espera P11 |
| F14.12 · F14.15 · F14.16 (SVG) | Escanear, quitar fondo, SVG con Inkscape | Claude |
| F15.1 a F15.4 · F15.8 · F15.6 (DWG) | Datums, calibración, perfiles mineros, ODA | Esperan P5, P6, P7 |
| F15.2 · F15.5 · F15.7 · F16.5 | Alturas con geoide, más perfiles, TIN, AeroBim | Claude (F16.5 con AeroBim) |
| F18.3 ⚠ · F18.7 | PPK real | Esperan P15 y P16 (RTKLIB ya lo instala el guion) |
| F10.5 | Trimble bajo Wine | Usted (pasos en `docs/historial/HANDOFF-hasta-2026-10-07.md`) |
| F1.6 · F2.6 · F4.1 · F4.2 · F11.8 | ECW, 3D Tiles, IFC, AeroBim por archivo, partir `runner.py` | Sin fecha |

## Lo que es suyo

Pedidos P5 a P16 en `SEGUIMIENTO.md`. **Copia de respaldo fuera de la máquina** (lo único sin
arreglo después de un fallo). **¿El repositorio sigue público?** (este archivo dice rutas de p340).

## Trampas vigentes

- El código de salida no prueba nada; se verifica la salida con otro lector. El CRS no se adivina.
- **Suite completa antes de cada push** con `$env:AEROCONVERT_GDAL_BIN = ""; $env:AEROCONVERT_PDAL_BIN
  = ""; uv run pytest -q --no-cov`, en segundo plano (~14 min). Pruebas con GDAL real:
  `@pytest.mark.oraculo`, con QGIS 4.0.2 en el PATH.
- **La configuración del `.env` no llega sola a un proceso hijo** (`python-decouple` no la copia a
  `os.environ` y los servicios no tienen `EnvironmentFile`): el padre la lee de `settings` y la pasa.
- **`fusionar_main.py` resuelve «los dos añadieron»** y desde #96 rechaza fundir o inventar piezas;
  igual, después de usarlo, `manage.py check` y la suite. Un archivo con bytes nulos es «binario» para
  git y choca entero: `test_changelog.py` lo vigila.
- `gdal_contour -f DXF -3d` escribe sin cota (por eso pasa por un GeoPackage 3D).
- El CI usa `ubuntu-latest`, que pasa a Ubuntu 26 el 2026-10-19 (como `p340`): si algo cambia ese
  día, es eso.
- `runserver --noreload` no recarga plantillas; `Select-Object -First N` sobre un servidor lo mata.

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido
python scripts/claude/plan_fila.py --abiertas
```

Historial: [`docs/historial/HANDOFF-hasta-2026-10-08.md`](docs/historial/HANDOFF-hasta-2026-10-08.md)
