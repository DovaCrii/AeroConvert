# HANDOFF — dónde retomar

**Última sesión: 2026-09-09.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

**Ráster y nubes de puntos funcionan de punta a punta, con interfaz.** Lo que queda son las
familias vectorial/CAD (F3) y BIM/malla (F4), y ECW, que necesita una licencia para poder
probarse.

## Lo que se cerró

| Fase | Qué |
| --- | --- |
| F0 | Andamiaje, identidad, gate, CI verde sin GDAL, vendorizado con SRI |
| F1 | Ráster completo: catálogo, detección, motores, trabajos, la mesa, el recibo, retención |
| F1.7 | Preajustes, formulario generado desde `opciones()`, estimación previa, reintentar |
| F2 | Nubes: lector LAS propio, LAS/LAZ → COPC, diezmado, reproyección, RCS/RCP declarados |

**394 pruebas**, 91,9 % de cobertura, verdes **sin GDAL ni PDAL instalados**.

### Lo verificado sobre archivos reales

| Entrada | Salida | Tiempo | Verificado por |
| --- | --- | ---: | --- |
| Ortofoto 466,2 MB BigTIFF | GeoTIFF clásico 285 MB | 7 s | `gdalinfo` |
| La misma | JPEG 2000 60 MB | 9 s | `gdalinfo` |
| Nube 278,9 MB LAS 1.2 | COPC 76,4 MB, 9.618.692 puntos intactos | 50 s | `pdal info` |

Y en los tres el veredicto se invierte, que es el objetivo del producto.

## Lo siguiente, en orden

1. **F3 — vectorial, CAD y topografía.** `apps/vector/motores.py` está vacío esperando. OGR
   ya está disponible (viene con el mismo GDAL). Lo de más valor inmediato son **los
   archivos de puntos PNEZD/PENZD con vista previa en mapa**: `puntos control cruce
   minero.csv` es exactamente ese caso, y PNEZD leído como PENZD deja el punto a 6,8
   millones de metros de donde va, en silencio.
2. **F2.6 — 3D Tiles y Potree** con `py3dtiles`, para el visor web.
3. **F1.6 — ECW.** El motor está escrito y la clave ya viaja solo en el entorno del hijo,
   con su prueba centinela. Falta la SDK de Hexagon para probarlo.
4. **F4 — BIM y malla.**

## Cosas que te van a morder

- **`uv run pytest` necesita un `.env`.** Está en `.gitignore`; copia `.env.example`.
- **En esta máquina GDAL y PDAL ya están**, dentro de QGIS 4.0.2. **No traen ECW ni E57.**
- **El archivo temporal conserva la extensión**: `nube.parcial.copc.laz`, no
  `nube.copc.laz.parcial`. Media herramienta geoespacial deduce el formato de la extensión,
  y con el nombre viejo PDAL no escribía ni leía. El nombre lo construye `ruta_parcial()` en
  `apps/engines/base.py`, y **la usan el runner y los motores**: tenerla en dos sitios fue lo
  que permitió que se desincronizaran.
- **Nunca le pases `-q` a GDAL en el comando principal.** Deja la barra quieta y, peor, deja
  sin señales al detector de atasco.
- **PDAL no habla mientras trabaja**, así que su plan declara `emite_progreso=False` y el
  detector de atasco se apaga para él. Sin eso mataría trabajos sanos.
- **Las opciones de un perfil o un preajuste se escriben con el vocabulario del motor**, no
  con el de GDAL o PDAL. Escribir `COMPRESS` en vez de `compresion` no da error: el perfil
  simplemente no fija nada. Hay una prueba que compara ambos vocabularios.
- **El nombre del escritor en un argumento de PDAL tiene que ser el que se pasó en `-w`.**
  `--writers.las.forward` con el escritor `writers.copc` no se ignora: PDAL responde
  «Argument references invalid/unused stage» y no escribe nada.
- **Un CRS compuesto se resuelve por su componente horizontal.** PDAL escribe `COMPD_CS`, y
  la heurística del `AUTHORITY` declarado tomaba el del metro del componente vertical.
- **En BigTIFF los tres anchos de campo valen 8** y en el TIFF clásico valen 2, 4 y 4.
- **En LAS, el bit alto del formato de punto marca la compresión.** Leerlo sin la máscara da
  134 en vez de 6. Y los límites van alternados: max, min, max, min, max, min.
- **No corras un reemplazo automático de acentos sobre el código.** Se intentó y acentuó
  claves de opción, códigos de motivo estables y el flag `--version` de GDAL.
- **Las pruebas con oráculo no corren en el gate**: `uv run pytest -m oraculo`.

## Cómo levantarlo

```powershell
pwsh scripts/run.ps1
```

En modo `dev` el despachador está apagado a propósito; los trabajos se procesan con:

```powershell
uv run python manage.py procesar_trabajos --una-vez
```

## Sobre los archivos que originaron todo

`D:\OneDrive - J.E.J. Ingeniería S.A\CC 716 - BHP\CC 716 NEHVTI BHP\Entrega\Vuelo cruce minero\`

**No están en el repositorio y no deben estarlo.** Sus cifras están en
`docs/PRUEBAS_CON_ORACULO.md`; las pruebas reconstruyen equivalentes de 400 bytes en
`apps/formats/tests/constructor.py`, tanto TIFF como LAS.
