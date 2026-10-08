# HANDOFF — AeroConvert

> **Resumen de estado, no bitácora.** ≤100 líneas. La historia está en
> [`docs/historial/`](docs/historial/) y en `git log`. Si algo de aquí no cuadra con el código,
> **gana el código**: actualice esta página antes de seguir.

**Estado al:** 2026-10-08 · **`main` en:** `996dbf2` · **Último PR fusionado:** #87

## Quién hace qué

**Claude hace todo lo de git**: ramas `codex/…`, commits, push, PR con `--body-file` y fusiones a
`main` **solo con el CI verde** (`/abrir-pr`; el agente `fusionador-de-pr` espera el CI).
**Usted despliega en p340, al final.** Si el CI cae con `The job was not acquired by Runner`, es
la infraestructura: `gh run rerun <id>`.

## Dónde está el proyecto

- **Desplegado (2026-10-05):** hasta el #20. **En `main` sin desplegar: #21 a #87.**
- Versión `0.11.0` (cierra F13). 38 herramientas de documentos en nueve grupos (el noveno, «Vuelos
  de dron»). ~4.260 pruebas verdes sin GDAL ni PDAL.
- Lo último: vuelos de dron con PPK y el visor (#81 a #85), curvas de nivel (#86), paquetes de entrega
  y lotes (#87).

## Desplegar (lo hace usted)

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
```

`desplegar.sh` ya hace `uv sync`, `migrate`, `collectstatic` y `sembrar_preajustes`. **Lo que este
despliegue trae de nuevo:**

- **Seis migraciones** que se aplican solas: `core.0002` y `0003`, `engines.0001`, `jobs.0003`
  (etiqueta de avance), `jobs.0004` (lotes) y `presets.0002` (paquetes).
- **Variables nuevas del `.env`** (todas opcionales; sin ellas la función sale apagada con su
  motivo): `AEROCONVERT_PLANTILLAS_JEJ` (carpeta de las dos portadas Word, fuera del repo),
  `AEROCONVERT_CUOTA_DE_SUBIDAS_MB`, `AEROCONVERT_RAICES_DE_CONFIANZA` (certificados para verificar
  firmas), `AEROCONVERT_RTKLIB_RNX2RTKP` (PPK) y `AEROCONVERT_LOG_LEVEL`.
- **Programas externos** (apagados con motivo si faltan): RTKLIB `rnx2rtkp` para el PPK; ODA y el
  convertidor de Trimble siguen siendo suyos (P7, P10). Ver `docs/PUESTA_EN_MARCHA_DE_LO_APAGADO.md`.
- **Después:** `sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py resumen_de_uso
  --dias 7`, y repetirlo 2 o 3 semanas: con esas cifras se ordena lo que viene.

## El plan

`MASTER_PLAN.md` por filas (`python scripts/claude/plan_fila.py --abiertas`) y el tablero con **lo que
se le pide a usted** en `docs/planes/SEGUIMIENTO.md`. Claude avanza con `/avanzar`.

| Abierto | Qué falta | Quién |
| --- | --- | --- |
| F17.1 a F17.4 | Office con LibreOffice, Access con `mdbtools`, pantalla «cómo dejar listo el equipo», `instalar_faltantes.sh` | Claude |
| F14.9 · F14.12 · F14.15 · F14.16 (SVG) · F14.17 | PDF/A, escanear, quitar fondo, SVG con Inkscape, video con FFmpeg | Claude (programas externos sondeados, D1) |
| F14.11 | Visor PDF.js | Espera P11 (permiso para vendorizarlo) |
| F16.4 · F16.5 | API con token; integración con AeroBim | Claude |
| F15.1 a F15.3 · F15.4 · F15.8 | Datums y calibración; perfiles mineros; DWG con ODA | Esperan P5, P6, P7 |
| F15.6 ◐ | Curvas a DWG | Espera ODA (P7) |
| F18.3 ⚠ · F18.7 | Corrida PPK real con RTKLIB | Esperan P15 (base) y P16 |
| F10.5 | Trimble bajo Wine en p340 | Usted (pasos en el historial del 2026-10-07) |
| F1.6 · F2.6 · F4.1 · F4.2 · F11.8 | ECW, 3D Tiles, IFC, AeroBim por archivo, partir `runner.py` | Sin fecha |

## Lo que es suyo

- Pedidos P5 a P16 en `SEGUIMIENTO.md` (puntos de control, ODA, repo público, respaldo fuera de la
  máquina, PDF.js, ECW, sello de tiempo, base del vuelo, RTKLIB).
- **Copia de respaldo fuera de la máquina:** lo único sin arreglo posible después de un fallo.
- **¿El repositorio sigue público?** Este archivo y `SERVIDOR.md` dicen rutas y puerto de p340.

## Trampas vigentes

- El código de salida no prueba nada; se verifica la salida con otro lector. El CRS no se adivina.
- **El CI no tiene GDAL ni PDAL y la estación sí:** `$env:AEROCONVERT_GDAL_BIN = "";
  $env:AEROCONVERT_PDAL_BIN = ""; uv run pytest -q --no-cov` — **completa antes de cada push**, en
  segundo plano (~15 min).
- Las pruebas con GDAL real llevan `@pytest.mark.oraculo` (fuera del CI); con QGIS 4.0.2 en el PATH.
- `gdal_contour -f DXF -3d` escribe el DXF **sin la cota**: por eso pasa por un GeoPackage 3D.
- `runserver --noreload` no recarga plantillas. La herramienta de PowerShell bloquea por falso
  positivo textos con `/T` o rutas de sistema: textos largos con `Write` y un script de Python.
- `Select-Object -First N` sobre un servidor en marcha **lo mata** al cerrar la tubería.

## Cómo retomar

```powershell
uv run python scripts/claude/verificar.py rapido      # segundos
python scripts/claude/plan_fila.py --abiertas         # qué sigue
```

Historial: [`docs/historial/HANDOFF-hasta-2026-10-07.md`](docs/historial/HANDOFF-hasta-2026-10-07.md)
