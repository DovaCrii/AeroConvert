# HANDOFF — dónde retomar

**Última sesión: 2026-09-09.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

**Ráster, nubes de puntos y libretas de puntos topográficos funcionan de punta a punta, con
interfaz.** Lo que queda es el resto de la familia vectorial/CAD (LandXML, KML/KMZ, DWG por
ODA), BIM/malla (F4), y ECW, que necesita una licencia para poder probarse.

## Lo que se cerró

| Fase | Qué |
| --- | --- |
| F0 | Andamiaje, identidad, gate, CI verde sin GDAL, vendorizado con SRI |
| F1 | Ráster completo: catálogo, detección, motores, trabajos, la mesa, el recibo, retención |
| F1.7 | Preajustes, formulario generado desde `opciones()`, estimación previa, reintentar |
| F2 | Nubes: lector LAS propio, LAS/LAZ → COPC, diezmado, reproyección, RCS/RCP declarados |
| F3.1 | OGR vectorial: SHP, GPKG, GeoJSON, KML/KMZ, DXF entre sí |
| F3.3 | **Libretas de puntos PNEZD/PENZD/NEZ/ENZ**, con detección del orden por rango UTM y vista previa dibujada antes de convertir |

**514 pruebas**, 92,6 % de cobertura, verdes **sin GDAL ni PDAL instalados**.

### Lo verificado sobre archivos reales

| Entrada | Salida | Tiempo | Verificado por |
| --- | --- | ---: | --- |
| Ortofoto 466,2 MB BigTIFF | GeoTIFF clásico 285 MB | 7 s | `gdalinfo` |
| La misma | JPEG 2000 60 MB | 9 s | `gdalinfo` |
| Nube 278,9 MB LAS 1.2 | COPC 76,4 MB, 9.618.692 puntos intactos | 50 s | `pdal info` |
| Libreta `puntos control cruce minero.csv` | GPKG · SHP · KML · DXF, 5 puntos cada uno | < 1 s | `ogrinfo` |

Y en los cuatro el veredicto se invierte, que es el objetivo del producto.

**La libreta de puntos, con detalle**, porque es el caso donde el fallo es silencioso: se
detecta **PNEZD por el rango UTM** —7.318.729 no cabe como este de una zona, así que es
norte— y las cuatro salidas traen los cinco puntos con la extensión exacta del original,
161,5 × 192,0 m. El KML sale reproyectado a EPSG:4326 en **−69,046° / −24,244°**, que es la
Región de Antofagasta: si el orden se hubiera leído al revés, caería a 9.650 km de ahí.

## Lo siguiente, en orden

1. **F3 — lo que queda.** Las libretas de puntos ya están hechas y verificadas sobre el
   archivo real (ver abajo). Falta el resto de la fase: **LandXML** —la entrada natural a
   Civil 3D para superficies y alineamientos—, el parser KML/KMZ endurecido de
   `AeroControl/apps/geo/kml/parse.py` para leer lo que llega de Google Earth, y **DWG/DGN
   por el motor ODA**, que ya tiene su sonda escrita.
2. **F2.6 — 3D Tiles y Potree** con `py3dtiles`, para el visor web.
3. **F1.6 — ECW.** El motor está escrito y la clave ya viaja solo en el entorno del hijo,
   con su prueba centinela. Falta la SDK de Hexagon para probarlo.
4. **F4 — BIM y malla.**

## Ideas anotadas, sin decidir

Cosas que se han pensado y **no** se han hecho. Están aquí para que no se vuelvan a pensar
desde cero, no como compromiso.

- **Abrir el taller al resto de la oficina.** Hoy `run.ps1` escucha solo en `127.0.0.1` y
  `ALLOWED_HOSTS` son `localhost` y `127.0.0.1`: desde otro PC da un 400, a propósito.
  Abrirlo pide tres cosas —escuchar en `0.0.0.0`, el host o la IP en `ALLOWED_HOSTS`, y
  `CSRF_TRUSTED_ORIGINS`— y **una decisión que no es técnica**: en taller la ruta de origen
  es un primitivo de lectura del disco entero de esta máquina, así que abrirlo en red
  convierte la sesión de cualquiera en lectura de este disco. Si se hace, el camino honesto
  es el modo `nube` con subida y tope, no taller con la puerta abierta. Surgió al intentar
  abrir la aplicación por IP desde otro PC (2026-09-09).

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
- **`taller` no arranca sin `collectstatic`, y el síntoma no se parece a la causa.** Corre con
  `DEBUG=False` y almacén con manifiesto: sin `staticfiles.json`, la primera etiqueta
  `{% static %}` revienta y **todas** las páginas devuelven 500. Lo que se llegaba a ver era
  la aplicación cayendo de vuelta a `dev` —`manage.py` la tiene por omisión y `.env` trae
  `DEBUG=True`—, y ahí los estáticos van **sin huella y sin `Cache-Control`**, solo con
  `Last-Modified`: el navegador reutiliza su copia y pinta el HTML nuevo con la hoja vieja.
  Se lee como un error de diseño y no lo es. `run.ps1` ya recolecta, y `test_arranque.py` lo
  vigila.
- **El manifiesto persigue los `sourceMappingURL` y aborta si falta el `.map`.** Vendorizamos
  los minificados sin sus mapas, así que `collectstatic` moría en
  `bootstrap.bundle.min.js.map`. **No se arregla borrando el comentario del minificado**: el
  `integrity` se calcula sobre los bytes exactos y el navegador descartaría la hoja entera —
  el arreglo causaría el fallo que intenta arreglar. Se arregla en el almacén,
  `apps/core/estaticos.py`.
- **Un `integrity` desparejado no da error visible**: el navegador descarta el recurso y la
  página sale sin estilos. Si re-vendorizas algo, actualiza el hash en `base.html`;
  `test_estaticos.py` compara los dos.
- **`GDAL_DATA` no se deduce con una regla, y sin ella hay controladores que no arrancan.**
  El de DXF busca la plantilla `header.dxf` y, al no encontrarla, responde `DXF driver
  failed to create ...`. En QGIS 4.0.2 conviven dos diseños: los binarios en `bin`, los
  datos de GDAL en `apps\gdal\share\gdal` y los de PROJ en `share\proj`. Se busca por
  **archivo testigo** en `apps/engines/entorno.py`, que es de donde sacan el entorno los dos
  motores; una carpeta `share/gdal` vacía existe y no sirve de nada.
- **`-a_srs` y `-t_srs` de `ogr2ogr` son mutuamente excluyentes.** Uno etiqueta y el otro
  mueve los números. Para reproyectar hacen falta `-s_srs` **y** `-t_srs`.
- **KML y GeoJSON exigen EPSG:4326 y el controlador no avisa.** Escribe las coordenadas tal
  cual se le den: un KML con estes y nortes UTM dentro es válido, abre en Google Earth y
  pone la obra fuera del planeta. El motor añade la reproyección él, no es una opción del
  formulario.
- **El nombre corto de un controlador puede llevar espacios.** `ESRI Shapefile`,
  `MapInfo File`. `PATRON_FORMATO` de `sondas.py` los perdía con `(\S+)` y SHP salía como no
  escribible — una celda apagada por una expresión regular.
- **`ogrinfo --formats` lista los controladores vectoriales y `gdalinfo --formats` los
  ráster.** Son listas distintas; por eso hay `sondar_ogr()` además de `sondar_gdal()`.
- **Una libreta de puntos nunca trae CRS dentro**, así que `_exigir_crs` acepta el declarado
  a mano —validado contra pyproj y anotado en la bitácora con el nombre de quien lo
  declaró—. Sin eso, la fase vectorial no podría convertir nada.
- **El formulario de la ficha envía a `dashboard:encolar`, no a `dashboard:convertir`.** La
  segunda solo pinta la pantalla, y apuntar ahí deja el botón de convertir sin hacer nada y
  sin dar ningún error. Pasó al renombrar «Mesa» a «Convertir». Lo vigila
  `apps/dashboard/test_libretas.py::TestElFormularioLlegaADondeConvierte`.

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

