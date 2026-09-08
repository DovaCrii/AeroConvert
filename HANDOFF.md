# HANDOFF — dónde retomar

**Última sesión: 2026-09-08.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

El andamiaje y el núcleo de detección están cerrados y probados. **AeroConvert diagnostica
pero todavía no convierte**: falta el modelo de trabajo, el que ejecuta, y la interfaz.

## Lo que se cerró

- **`apps/formats/tiff.py`** — lector propio de cabecera TIFF y BigTIFF, sin GDAL.
  Contrastado contra `gdalinfo` sobre tres archivos de obra: coincide en todo, incluido el
  conteo de pirámides.
- **`apps/formats/catalogo.py`, `deteccion.py`, `crs.py`** — catálogo, inspección por firma
  y CRS con procedencia.
- **`apps/targets/perfiles.py`** — seis perfiles de destino y la tira de veredictos.
- **`apps/engines/`** — contrato de motor, registro, matriz y sondas reales.
- **`apps/jobs/motivos.py`** — el catálogo de motivos con código estable.
- **73 pruebas** verdes sin GDAL instalado.

## Lo siguiente, en orden

1. **F0.5 y F0.6** — `scripts/verify.ps1`, `run.ps1`, `sondear.ps1`, vendorizar Bootstrap y
   htmx con SRI, y el workflow de CI. Es lo que falta para que la fase 0 esté completa.
2. **F1.2 — el modelo de trabajo.** `ConversionJob` y `JobEvent` en `apps/jobs/models.py`,
   el runner y el despachador. Es el cuello de botella: nada de lo demás avanza sin esto.
   El diseño está en el plan; los campos y los estados también.
3. **F1.5 — `MotorGdalRaster.plan()`.** Hoy levanta `NotImplementedError`. Los valores por
   omisión ya están decididos **y medidos** (`docs/PRUEBAS_CON_ORACULO.md` §2): DEFLATE-9
   para maestro, JPEG 2000 para entrega.
4. **F1.4 — la mesa.** Ya existe `apps/dashboard/views.py` con la vista de inspección
   escrita; **faltan las plantillas y el CSS**, así que la vista todavía no se puede abrir.

## Cosas que te van a morder

- **`uv run pytest` necesita un `.env`.** Está en `.gitignore`; copia `.env.example`. Sin
  `AEROCONVERT_RAICES_PERMITIDAS`, `manage.py check` falla a propósito en modo taller.
- **En esta máquina GDAL ya está**, dentro de QGIS 4.0.2:
  `C:\Program Files\QGIS 4.0.2\bin`. Trae GDAL 3.12.4 y PDAL 2.10.0. `AEROCONVERT_GDAL_BIN`
  apunta ahí en el `.env` de ejemplo. **No trae ECW**, ni de lectura.
- **Las pruebas con oráculo no corren en el gate.** `pytest.ini` lleva
  `addopts = -m "not oraculo"`. Es deliberado.
- **En BigTIFF los tres anchos de campo valen 8** y en el TIFF clásico valen 2, 4 y 4. Un
  error ahí funciona con BigTIFF y revienta con el clásico. Ya pasó una vez; hay una prueba
  que compara las dos variantes campo a campo para que no vuelva a pasar.
- **`_coincide_con_epsg()` en `crs.py` parece de más y no lo es.** pyproj no identifica el
  `.prj` que escribe Metashape ni con confianza 20 — devuelve cero candidatos —, así que el
  código lee el `AUTHORITY` que el propio WKT declara **y lo verifica** contra la definición
  canónica. Hay una prueba que falla si algún día pyproj empieza a resolverlo solo, para que
  se pueda quitar.

## Sobre el archivo que originó todo

`D:\OneDrive - J.E.J. Ingeniería S.A\CC 716 - BHP\CC 716 NEHVTI BHP\Entrega\Vuelo cruce minero\Metashape\Cruce Minero.tif`

Es BigTIFF y por eso no abre en Civil 3D. **No está en el repositorio y no debe estarlo.**
Sus cifras están en `docs/PRUEBAS_CON_ORACULO.md`; las pruebas reconstruyen un equivalente
de 400 bytes en `apps/formats/tests/constructor.py`.
