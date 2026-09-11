# HANDOFF — dónde retomar

**Última sesión: 2026-09-11.** Léelo antes que `MASTER_PLAN.md`.

---

## En una frase

**Ráster, nubes de puntos, libretas de puntos, LandXML y las herramientas de PDF funcionan de
punta a punta, con interfaz.** Casi todo lo que queda en el terreno geoespacial **no espera
código: espera algo de fuera** — un puesto con Civil 3D para dar por buena la salida LandXML,
un LandXML de verdad para poder leer sus superficies, el conversor de ODA para DWG, la SDK de
Hexagon para ECW. Lo único pendiente que solo depende de escribirlo es F2.6 (3D Tiles), F4
(BIM y malla) y lo que falta de PDF (§ *PDF: lo que queda*).

## Lo que se cerró

| Fase | Qué |
| --- | --- |
| F0 | Andamiaje, identidad, gate, CI verde sin GDAL, vendorizado con SRI |
| F1 | Ráster completo: catálogo, detección, motores, trabajos, la mesa, el recibo, retención |
| F1.7 | Preajustes, formulario generado desde `opciones()`, estimación previa, reintentar |
| F2 | Nubes: lector LAS propio, LAS/LAZ → COPC, diezmado, reproyección, RCS/RCP declarados |
| F3.1 | OGR vectorial: SHP, GPKG, GeoJSON, KML/KMZ, DXF entre sí |
| F3.3 | **Libretas de puntos PNEZD/PENZD/NEZ/ENZ**, con detección del orden por rango UTM y vista previa dibujada antes de convertir |
| F3.5 | **LandXML**: se escribe (CgPoints con número, descripción y epsgCode) y se lee (qué trae dentro; los puntos además se convierten) |
| F5 | **PDF**: leer, unir con miniaturas y giro, dividir, imágenes ↔ PDF, numerar, marca de agua, proteger y desproteger |

**883 pruebas**, 93,6 % de cobertura, verdes **sin GDAL ni PDAL instalados**.

### Lo verificado sobre archivos reales

| Entrada | Salida | Tiempo | Verificado por |
| --- | --- | ---: | --- |
| Ortofoto 466,2 MB BigTIFF | GeoTIFF clásico 285 MB | 7 s | `gdalinfo` |
| La misma | JPEG 2000 60 MB | 9 s | `gdalinfo` |
| Nube 278,9 MB LAS 1.2 | COPC 76,4 MB, 9.618.692 puntos intactos | 50 s | `pdal info` |
| Libreta `puntos control cruce minero.csv` | GPKG · SHP · KML · DXF, 5 puntos cada uno | < 1 s | `ogrinfo` |
| La misma | LandXML con 5 `CgPoint`, grupo nombrado y `epsgCode` | < 1 s | sin oráculo: ver abajo |
| Ese LandXML | de vuelta a SHP · GPKG · KML, 5 entidades y las mismas coordenadas | < 1 s | `ogrinfo` |
| KMZ del cruce | GPKG y DXF en UTM, ida y vuelta exacta al milímetro | < 1 s | `ogrinfo` |

Y en todos el veredicto se invierte, que es el objetivo del producto.

**La libreta de puntos, con detalle**, porque es el caso donde el fallo es silencioso: se
detecta **PNEZD por el rango UTM** —7.318.729 no cabe como este de una zona, así que es
norte— y las cuatro salidas traen los cinco puntos con la extensión exacta del original,
161,5 × 192,0 m. El KML sale reproyectado a EPSG:4326 en **−69,046° / −24,244°**, que es la
Región de Antofagasta: si el orden se hubiera leído al revés, caería a 9.650 km de ahí.

**LandXML no tiene oráculo y no se finge que sí.** OGR no lo lee, así que no hay una segunda
herramienta a la que preguntarle, y comprobarlo con nuestro propio lector sería el código
dándose la razón. Lo que se comprueba automáticamente es lo comprobable: que el XML esté bien
formado —lo dice el analizador de la biblioteca estándar— y que traiga tantos `<CgPoint>`
como puntos tenía la libreta. **La aceptación de verdad es abrirlo en Civil 3D**, y está
pendiente de hacerse en un puesto con licencia; es un procedimiento manual, igual que ECW.

## Lo siguiente, y de qué depende cada cosa

**Lo que espera a alguien, no a código:**

1. **Abrir el LandXML en Civil 3D.** Es la aceptación de verdad y no se puede hacer desde
   aquí. Cinco minutos en un puesto con licencia; el procedimiento está en
   `docs/PRUEBAS_CON_ORACULO.md` con los cuatro puntos que pueden fallar sin dar error.
2. **Conseguir un LandXML de verdad** —de Civil 3D, de un proyectista, de donde sea— para
   poder hacer el lector de superficies y alineamientos. Hoy se cuentan y se identifican,
   pero no se traducen: sin un archivo con el que contrastar, un triangulado mal leído da una
   superficie plausible y equivocada.
3. **Instalar ODA File Converter** (gratuito, de la Open Design Alliance) y apuntar
   `AEROCONVERT_ODA_CONVERTER`. Con eso se abre DWG y DGN v8. La sonda ya está escrita y hoy
   responde `sin-conversor`.
4. **La SDK de Hexagon** para ECW. El motor está escrito y la clave ya viaja solo en el
   entorno del hijo, con su prueba centinela.

**Lo que solo espera a que alguien lo escriba:**

5. **F2.6 — 3D Tiles y Potree** con `py3dtiles`, para el visor web. Habría que añadir la
   dependencia.
6. **F4 — BIM y malla** con `ifcopenshell`. Tampoco está instalada.

## PDF: lo que queda

Lo hecho está arriba. Lo que falta, con lo que cuesta cada cosa de verdad:

- **PDF → Word.** Se puede hacer, pero **hay que decir en la pantalla lo que se va a
  recibir**: un PDF no guarda párrafos, guarda posiciones de letras. Lo que sale es editable
  y *no* es el documento original. Prometerlo sin el aviso es lo que hace que estas
  herramientas tengan mala fama.
- **Comprimir PDF.** Requiere volver a codificar las imágenes de dentro; en un plano
  escaneado la diferencia entre útil e ilegible es de un paso de calidad, así que necesita
  vista previa antes de escribir.
- **OCR.** Depende de Tesseract instalado fuera, como GDAL. Se sondea, no se declara.

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
- **Un Shapefile son cinco archivos, y el renombrado movía uno.** La verificación corre
  sobre el parcial, cuando los hermanos todavía se llaman `salida.parcial.shx`, así que
  pasaba; después quedaba un `.shp` huérfano que **no abre en ninguna parte**. Lo mueve
  `_renombrar_con_acompanantes()`, y quién acompaña a quién lo dice el catálogo. Si añades un
  formato multiarchivo, sus acompañantes van ahí.
- **Un DXF en grados es un dibujo de dos milésimas de unidad.** No guarda sistema de
  referencia: guarda números. Un KMZ viene siempre en EPSG:4326, así que llevarlo a DXF sin
  reproyectar «funciona» y entrega algo invisible en Civil 3D. Lo para `_exigir_metros` en el
  runner, **antes** de convertir: mirando la salida no hay forma de saberlo, el dato solo
  existe en el origen. Se declara con la opción `crs_destino`.
- **KML y KMZ son EPSG:4326 por norma**, así que la inspección se lo pone con el origen
  `por-norma` — ni incrustado ni declarado por nadie. De eso depende el aviso anterior.
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
- **En un PDF, la orientación no es la caja: es la caja más `/Rotate`.** Una lámina con
  `MediaBox` 594 × 841 —vertical— y `/Rotate 270` **se ve apaisada**, y lo que importa es lo
  que se ve. Lo resuelve `_milimetros()` en `apps/formats/pdf.py` intercambiando los lados
  cuando el giro es 90 o 270. Mi propia prueba nació al revés por esto. Hay un archivo real
  con el caso exacto: las bitácoras de vuelo escaneadas, caja 593 × 764 pt y `/Rotate 270`.
- **Y una capa superpuesta hay que dibujarla en el sistema de lo que se ve, no en el de la
  caja.** Es la misma trampa un paso más allá: `merge_page` pega la capa en el espacio sin
  girar, así que un pie de página dibujado «abajo» aparece **de canto en un lateral**. Lo
  resuelve `_encuadrar()` en `apps/documents/marcas.py` aplicándole al lienzo el giro
  contrario. Y la capa se dibuja **por página**, porque una entrega mezcla A4 con A1.
- **Las tres aplicaciones de Office exportan a PDF de tres maneras distintas.** Word
  `ExportAsFixedFormat(ruta, 17)`; Excel **invierte los argumentos**,
  `ExportAsFixedFormat(0, ruta)`; y PowerPoint no traga ninguno de los dos desde PowerShell
  —su firma tiene dieciséis parámetros opcionales y el enlace tardío no pasa el enum—, así
  que va con `SaveAs(ruta, 32)`. Escribir esto de memoria falla.
- **PowerPoint ignora `Visible = $false`.** La ventana se le abre en la cara a quien esté
  usando el equipo si no se pasa `WithWindow = $false` al abrir la presentación.
- **Hay que cerrar Office en un `finally`.** Un `WINWORD.EXE` huérfano se queda con el
  archivo bloqueado y el intento siguiente falla sin decir por qué.
- **`subprocess` con `text=True` decodifica con la página de códigos de Windows**, no con
  UTF-8. Un Office en español devuelve «el documento pide una contraseÃ±a» — y el mensaje que
  más falta hace es justo el que sale ilegible. Va con `encoding="utf-8", errors="replace"`.
- **Bandit lee lo que sigue a `# nosec` como nombres de prueba.** Un `# nosec B404 -- porque
  tal` suelta un aviso por cada palabra. La justificación va en la línea de arriba.
- **Una hoja de cálculo no tiene tamaño de papel.** Medido en este repositorio: el mismo
  libro sale en **68 páginas** sin ajustar y en **6** encajando cada hoja a lo ancho. No es
  un PDF peor, es inservible.
- **La posición de una marca solo se comprueba dibujándola.** Contrastarla con el mismo
  cálculo que la produjo no prueba nada. `test_marcas.py` pinta con PDFium y mira dónde cayó
  la tinta; y «tinta» es todo lo que no sea papel (umbral 250), no «negro»: una marca de agua
  al 8 % da un gris de 235 y con umbral 128 sale una página en blanco.
- **El giro que se pide al componer es relativo, no absoluto.** `pagina.rotate(90)` **suma**
  al que la página ya traía. Es lo correcto —así no se pierde nada y no se redibuja— pero
  significa que la etiqueta de la fila tiene que calcular la orientación resultante, no
  leerla del archivo.
- **pypdf avisa por `logging`, no por `warnings`.** Un `warnings.catch_warnings()` alrededor
  no recoge nada. Por eso existe `_RecogerQuejas(logging.Handler)` en `apps/formats/pdf.py`.
- **pypdf sin `cryptography` no cifra con AES: levanta `DependencyError`.** Y su alternativa
  es RC4, roto desde hace veinte años. La dependencia no es opcional, y su piso es la **50**
  por pip-audit; está razonado en `pyproject.toml`.
- **Un PNG con transparencia guardado tal cual en un PDF sale con el fondo negro**, y el
  JPEG no admite canal alfa en absoluto. Todo lo que entra o sale como imagen pasa por RGB
  sobre blanco antes.
- **Un PDF cifrado no se puede ni mirar**: ni miniatura, ni número de páginas, ni dividir.
  Por eso `_mirar_pdf()` en `apps/documents/views.py` se niega y manda a «Proteger PDF» en
  vez de dar un error genérico.
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



