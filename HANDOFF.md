# HANDOFF — dónde retomar

**Última sesión: 2026-09-08.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

**AeroConvert está usable de punta a punta**: se abre en el navegador, se suelta una ruta,
dice qué hay dentro y dónde abre, se elige el programa de destino, convierte y entrega el
recibo. Verificado sobre el entregable real de BHP.

## Lo que se cerró

| Fase | Qué |
| --- | --- |
| F0 | Andamiaje, identidad, gate, CI verde sin GDAL, vendorizado con SRI |
| F1.0 | Catálogo, lector propio de TIFF/BigTIFF, detección, CRS con procedencia |
| F1.1 | Contrato de motor, registro, matriz, sondas (falta `RegistroDeSonda`) |
| F1.2 | `ConversionJob`, `JobEvent`, runner, despachador |
| F1.3 | Perfiles de destino y veredictos |
| F1.4 | La mesa, la ficha del trabajo, el recibo, el historial, la matriz |
| F1.5 | Motor GDAL ráster, con verificación por `gdalinfo` |
| F1.8 | Retención, presupuesto de disco y barrido |

**290 pruebas**, 91,4 % de cobertura, verdes **sin GDAL instalado**.

### El recorrido, medido

`Cruce Minero.tif` — 466,2 MB en BigTIFF, 4 bandas con alfa, EPSG:32719:

| Destino | Tiempo | Salida | Verificado por `gdalinfo` |
| --- | ---: | ---: | --- |
| Civil 3D → GeoTIFF clásico DEFLATE, 3 bandas, 5 pirámides | 7 s | 285 MB | 14.526 × 14.443 · EPSG:32719 |
| Entrega → JPEG 2000 calidad 25 | 9 s | 60 MB | 14.526 × 14.443 · EPSG:32719 |

Y el veredicto se invierte, que es el objetivo: la entrada dice **«Civil 3D: no abre, es
BigTIFF»** y la salida dice **«Civil 3D: abre tal cual»**.

## Lo siguiente, en orden

1. **F1.6 — ECW.** El motor está escrito y la clave ya viaja solo en el entorno del hijo,
   con su prueba centinela. Falta una instalación con la SDK de Hexagon para probarlo.
2. **F1.7 — preajustes y pulido.** El modo experto solo elige formato; las opciones del
   motor ya son declarativas y solo falta desplegarlas en el formulario. También las
   traducciones: los nombres de formato salen en inglés porque son sus `msgid`.
3. **F2 — nubes de puntos.** `apps/pointcloud/motores.py` está vacío y esperando; el motor
   ya existe escrito y medido en `AeroBim/apps/web/scripts/a-copc.py`.

## Cosas que te van a morder

- **`uv run pytest` necesita un `.env`.** Está en `.gitignore`; copia `.env.example`. Sin
  `AEROCONVERT_RAICES_PERMITIDAS`, `manage.py check` falla a propósito en modo taller.
- **En esta máquina GDAL ya está**, dentro de QGIS 4.0.2: `C:\Program Files\QGIS 4.0.2\bin`,
  con GDAL 3.12.4 y PDAL 2.10.0. **No trae ECW**, ni de lectura.
- **Nunca le pases `-q` a GDAL en el comando principal.** Silenciarlo deja la barra quieta
  y, peor, deja sin señales al detector de atasco: un motor sano se mataría solo en
  cualquier ráster que tarde más que `AEROCONVERT_SILENCIO_MAXIMO_S`.
- **GDAL no escribe líneas mientras convierte**, escribe una línea que crece. `_leer_salida`
  lee por trozos con `os.read` justo por eso. Si alguien lo «simplifica» a `for linea in
  stdout`, el progreso desaparece y las pruebas no lo notarán: hay que probarlo contra un
  archivo grande de verdad.
- **`gdaladdo` solo mete las pirámides dentro del archivo en unos pocos formatos.** Con JP2,
  ECW o ASC deja un `.ovr` al lado — sobre la ortofoto real, **360 MB pegados a un archivo
  de 63 MB**. Por eso existe `DESTINOS_CON_PIRAMIDES` y la lista es corta.
- **Las opciones de un perfil se escriben con el vocabulario del motor, no con el de GDAL.**
  Escribir `COMPRESS` en vez de `compresion` no da error: el perfil simplemente no fija
  nada. Hay una prueba que compara ambos vocabularios.
- **En BigTIFF los tres anchos de campo valen 8** y en el TIFF clásico valen 2, 4 y 4. Un
  error ahí funciona con BigTIFF y revienta con el clásico.
- **`_coincide_con_epsg()` en `crs.py` parece de más y no lo es.** pyproj no identifica el
  `.prj` de Metashape ni con confianza 20, así que se lee el `AUTHORITY` que el WKT declara
  **y se verifica**. Hay una prueba que falla si pyproj lo resuelve solo, para poder quitarlo.
- **No corras un reemplazo automático de acentos sobre el código.** Se intentó y acentuó
  claves de opción, códigos de motivo estables y hasta el flag `--version` de GDAL. Lo
  cazaron tres pruebas, pero podría no haberlo hecho.
- **Las pruebas con oráculo no corren en el gate**: `pytest.ini` lleva
  `addopts = -m "not oraculo"`. Se lanzan con `uv run pytest -m oraculo`.

## Cómo levantarlo

```powershell
pwsh scripts/run.ps1
```

Abre `http://127.0.0.1:8420/`. En modo `dev` el despachador está apagado a propósito, así
que los trabajos se quedan encolados; se procesan con:

```powershell
uv run python manage.py procesar_trabajos --una-vez
```

En modo `taller` —el que levanta `run.ps1`— el despachador sí corre solo.

## Sobre el archivo que originó todo

`D:\OneDrive - J.E.J. Ingeniería S.A\CC 716 - BHP\CC 716 NEHVTI BHP\Entrega\Vuelo cruce minero\Metashape\Cruce Minero.tif`

**No está en el repositorio y no debe estarlo.** Sus cifras están en
`docs/PRUEBAS_CON_ORACULO.md`; las pruebas reconstruyen un equivalente de 400 bytes en
`apps/formats/tests/constructor.py`.
