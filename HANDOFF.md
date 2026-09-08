# HANDOFF — dónde retomar

**Última sesión: 2026-09-08.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

**AeroConvert ya convierte, y está verificado sobre el archivo real de BHP.** Lo que falta
es la interfaz: hoy la conversión solo se lanza desde el shell.

## Lo que se cerró

| Fase | Qué |
| --- | --- |
| F0 | Andamiaje, identidad, gate, CI verde en GitHub Actions sin GDAL |
| F1.0 | Catálogo, lector propio de TIFF/BigTIFF, detección, CRS con procedencia |
| F1.1 | Contrato de motor, registro, matriz, sondas (falta `RegistroDeSonda`) |
| F1.2 | `ConversionJob`, `JobEvent`, runner, despachador |
| F1.3 | Perfiles de destino y veredictos |
| F1.5 | Motor GDAL ráster, con verificación por `gdalinfo` |

**214 pruebas**, 87,6 % de cobertura, verdes **sin GDAL instalado**.

### La prueba que importa

El entregable real —`Cruce Minero.tif`, 466,2 MB en BigTIFF— pasa entero por la aplicación:

| Destino | Tiempo | Salida | Verificado |
| --- | ---: | ---: | --- |
| GeoTIFF clásico, DEFLATE, 3 bandas | 7,1 s | 285 MB | 14.526 × 14.443, EPSG:32719 |
| JPEG 2000, calidad 25 | 9,4 s | 60 MB | 14.526 × 14.443, EPSG:32719 |

Y el veredicto se invierte, que es el objetivo del producto: la entrada dice **«Civil 3D: no
abre, es BigTIFF»** y la salida dice **«Civil 3D: abre tal cual»**.

## Lo siguiente, en orden

1. **F1.4 — la mesa.** Es lo único que separa esto de un producto usable. Hace falta:
   `templates/base.html`, la zona de soltar, la ficha, la tira de veredictos, el selector de
   destino por programa, el progreso por *polling* de htmx y el recibo. Las vistas de
   `apps/dashboard/views.py` ya están escritas y esperando plantilla.
2. **F0.6 — vendorizar** Bootstrap 5.3.3 y htmx 2.0.10 con SRI en `static/vendor/`. Va antes
   que F1.4 en la práctica: la CSP es `'self'` y no hay CDN.
3. **F1.6 — ECW.** El motor está escrito y la clave ya viaja solo en el entorno del hijo,
   con su prueba centinela. Falta una instalación con la SDK para poder probarlo de verdad.
4. **F1.7 — preajustes** y el resto del pulido.

## Cosas que te van a morder

- **`uv run pytest` necesita un `.env`.** Está en `.gitignore`; copia `.env.example`. Sin
  `AEROCONVERT_RAICES_PERMITIDAS`, `manage.py check` falla a propósito en modo taller.
- **En esta máquina GDAL ya está**, dentro de QGIS 4.0.2: `C:\Program Files\QGIS 4.0.2\bin`,
  con GDAL 3.12.4 y PDAL 2.10.0. **No trae ECW**, ni de lectura.
- **Nunca le pases `-q` a GDAL en el comando principal.** Silenciarlo deja la barra quieta
  y, peor, deja sin señales al detector de atasco: un motor sano se mataría solo en
  cualquier ráster que tarde más que `AEROCONVERT_SILENCIO_MAXIMO_S`. Hay una prueba que lo
  vigila.
- **GDAL no escribe líneas mientras convierte**, escribe una línea que crece. `_leer_salida`
  lee por trozos con `os.read` justo por eso. Si alguien lo «simplifica» a `for linea in
  stdout`, el progreso vuelve a desaparecer y las pruebas no lo notarán: hay que probarlo
  contra un archivo grande de verdad.
- **En BigTIFF los tres anchos de campo valen 8** y en el TIFF clásico valen 2, 4 y 4. Un
  error ahí funciona con BigTIFF y revienta con el clásico. Hay una prueba que compara las
  dos variantes campo a campo.
- **`_coincide_con_epsg()` en `crs.py` parece de más y no lo es.** pyproj no identifica el
  `.prj` que escribe Metashape ni con confianza 20, así que se lee el `AUTHORITY` que el WKT
  declara **y se verifica**. Hay una prueba que falla si algún día pyproj lo resuelve solo,
  para que se pueda quitar.
- **Las pruebas con oráculo no corren en el gate**: `pytest.ini` lleva
  `addopts = -m "not oraculo"`. Se lanzan con `uv run pytest -m oraculo`.

## Cómo convertir hoy, sin interfaz

```powershell
uv run python manage.py shell
```

```python
from django.contrib.auth import get_user_model
from apps.jobs.models import ConversionJob
from apps.jobs import runner

job = ConversionJob.objects.create(
    owner=get_user_model().objects.first(),
    source_path=r"D:\ruta\al\archivo.tif",
    source_name="archivo.tif",
    target_format_code="geotiff",          # o "cog", "jp2", "img", "asc"
    options={"compresion": "DEFLATE", "solo_rgb": True},
    output_path=r"D:\salida\convertido.tif",
)
runner.ejecutar(job)
```

## Sobre el archivo que originó todo

`D:\OneDrive - J.E.J. Ingeniería S.A\CC 716 - BHP\CC 716 NEHVTI BHP\Entrega\Vuelo cruce minero\Metashape\Cruce Minero.tif`

**No está en el repositorio y no debe estarlo.** Sus cifras están en
`docs/PRUEBAS_CON_ORACULO.md`; las pruebas reconstruyen un equivalente de 400 bytes en
`apps/formats/tests/constructor.py`.
