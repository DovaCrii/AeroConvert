# Registro de cambios

Sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido — nubes de puntos (fase F2)

- **LAS y LAZ → COPC**, con diezmado y reproyección. Sobre la nube real de BHP: 278,9 MB y
  9.618.692 puntos → **76,4 MB en 50 s, con los 9.618.692 puntos intactos** y verificados
  contra el original. El veredicto se invierte igual que con el ráster: la entrada dice
  «AeroBim: solo lee COPC, y esta no lo es» y la salida dice «abre».
- **Lector propio de cabecera LAS, LAZ y COPC, sin PDAL.** Contrastado contra `pdal info`
  sobre el archivo real: coincide en versión, cuenta, formato de punto, límites y EPSG.
  Reutiliza el parser de geoclaves del GeoTIFF, porque LAS 1.0–1.3 guarda el CRS **con el
  mismo registro 34735**.
- El aviso de precisión de AeroBim, ahora automático: sobre la nube real detecta que
  `float32` perdería unos 20 cm y lo dice en la ficha.
- **RCS y RCP de Autodesk ReCap entran al catálogo para poder decir que no se pueden.** No
  hay lector abierto y no lo va a haber, así que su celda queda en «no soportado» —no en
  «instalable»— con el remedio escrito: exportar a E57 o LAS desde ReCap.

### Añadido — preajustes y pulido (fase F1.7)

- **El formulario del modo experto se genera desde `opciones()`.** Hasta ahora el motor
  declaraba los ajustes y la interfaz los ignoraba: había dos listas de lo que se puede
  pedir, y ya se habían desincronizado una vez.
- `ConversionPreset`, con sembrado idempotente por `slug` que **deriva de los perfiles**, no
  los copia: si mañana un perfil corrige una opción, el preajuste la hereda.
- **La estimación previa**: cuánto va a pesar, cuánto va a tardar y si cabe, con ratios
  medidos sobre la ortofoto real y anclados al tamaño sin comprimir. Cuando no hay medida
  para esa combinación, se marca en vez de fingir precisión.
- Botones de reintentar y de reencolar hacia una alternativa, en la ficha del trabajo. La
  vista existía y no había forma de llegar a ella.

### Añadido — la interfaz

- **La mesa.** Se suelta o se pega una ruta y aparece, sin abrir la imagen: la ficha de lo
  que hay dentro, la tira de veredictos por programa de destino, y los botones de destino.
  El selector primario es **un programa, no una extensión** — es la idea del producto.
- La ficha del trabajo con progreso por *polling* de htmx y **el recibo**: tamaño antes y
  después, dimensiones y CRS sin cambio, motor con su versión, y el `sha256` del original.
- El historial y la pantalla de motores, con la matriz origen × destino en tres estados.
- Identidad completa: tokens `--av-*` medidos, tema claro y oscuro siguiendo
  `prefers-color-scheme`, y el interruptor en un archivo aparte porque la CSP no admite
  `'unsafe-inline'`.
- Bootstrap 5.3.3 y htmx 2.0.10 **vendorizados con SRI**. La CSP es `'self'`: un CDN no
  cargaría, y en modo taller puede no haber red.

### Añadido — retención y disco

- Tres políticas (`efimera`, `temporal`, `permanente`) con el valor por omisión que
  corresponde al modo. Las entradas subidas se borran **siempre** al terminar.
- **Presupuesto de disco con cola.** Es lo que de verdad protege el servidor: borrar al
  terminar no impide que tres conversiones simultáneas llenen el volumen. Un trabajo que no
  cabe espera en vez de arrancar, y no falla — el disco se libera solo.
- Barrido de caducados, entradas y huérfanos, al arrancar y cada cinco minutos.
- La descarga borra el archivo al completarse, **no al empezar**: con archivos de cientos
  de megabytes la descarga se corta, y hay que poder reintentarla.

### Añadido

- **AeroConvert convierte.** Se cierran las fases F1.2 (modelo de trabajo) y F1.5 (motor
  ráster GDAL). El entregable real de BHP —466,2 MB en BigTIFF— pasa de punta a punta por
  la aplicación: 7 s a GeoTIFF clásico DEFLATE de 3 bandas con pirámides, y 9 s a JPEG 2000
  de 60 MB. En los dos casos `gdalinfo` confirma 14.526 × 14.443 px y EPSG:32719, y el
  original queda intacto.
- `ConversionJob` y `JobEvent`, con reclamo atómico, latido, cancelación cooperativa,
  escritura atómica en `.parcial` y bitácora de solo anexar.
- Despachador en hilo, sin broker ni segundo proceso, con las cuatro guardas: `RUN_MAIN`,
  `UPDATE` atómico, apagado en pruebas y recogida de obreros muertos.
- `MotorGdalRaster` y `MotorEcw`: construcción del `argv`, opciones declarativas de las que
  se generará el formulario, pirámides como paso posterior y verificación con `gdalinfo`.
- `MotorDeMentira`, que lanza un proceso real para probar el runner entero sin GDAL.

### Corregido

- **El progreso no llegaba.** GDAL escribe `0...10...20...` en una sola línea que va
  creciendo, sin salto, así que leer por líneas no devolvía nada hasta el final. Sobre el
  archivo de 466 MB eran 3 tics; ahora son 33. No era solo cosmético: sin señales, **el
  detector de atasco habría matado un motor sano** en cualquier ráster que tardase más que
  el umbral de silencio.
- Se quitó el `-q` que silenciaba a GDAL, por la misma razón.
- **La reserva del destino no detectaba nada.** `open(destino, "ab")` funciona en Windows
  aunque otro programa tenga el archivo abierto, porque Python abre con uso compartido: la
  comprobación daba verde siempre y el fallo real aparecía 23 s después, al renombrar —
  justo lo que esa comprobación existe para evitar. Ahora se intenta la misma operación que
  se hará al final, renombrar, y se deja el archivo como estaba.
- Cancelar dejaba el trabajo en `error`. Ahora queda en `cancelled`: mezclar «esto se
  rompió» con «cambié de idea» hacía inservible el historial.
- **Los perfiles de destino no fijaban nada.** Estaban escritos con las claves de GDAL
  —`COMPRESS`, `BLOCKXSIZE`— y el motor lee `compresion` y `tamano_tesela`, así que el
  trabajo salía con los valores por omisión: **el perfil de Civil 3D prometía descartar la
  banda alfa y no lo hacía.** Es justo el fallo que la regla de «las opciones las declara el
  motor» existe para impedir; ahora hay una prueba que compara ambos vocabularios.
- **`gdaladdo` dejaba un `.ovr` de 360 MB junto a cada JP2.** Solo escribe las pirámides
  dentro del archivo cuando el controlador admite abrirlo para actualizar; con JP2, ECW o
  ASC deja un GeoTIFF de pirámides al lado. Sobre la ortofoto real eran 360 MB pegados a un
  archivo de 63 MB — rompía las dos promesas a la vez: un solo archivo autocontenido, y no
  llenar el disco. Ahora solo se piden donde caben dentro.
- El runner borra los acompañantes que el motor cuelga del nombre del parcial. GDAL escribe
  un `.aux.xml` que quedaba huérfano en cuanto el archivo se renombraba.
- Un comentario de plantilla escrito como `{# … #}` en varias líneas se imprimía literal en
  el recibo: esa forma es de una sola línea.
- **El nombre del archivo temporal destruía la extensión.** Se llamaba
  `nube.copc.laz.parcial`, y media herramienta geoespacial deduce el formato de la
  extensión: PDAL no lo escribía y `pdal info` no lo leía. Se descubrió convirtiendo la nube
  de verdad, después de 37 segundos de trabajo tirados. Ahora es `nube.parcial.copc.laz`, y
  el nombre lo construye una sola función que usan el runner y los motores.
- **El detector de atasco habría matado los trabajos de PDAL.** PDAL no dice nada mientras
  trabaja, así que el silencio es su estado normal; el plan ahora lo declara con
  `emite_progreso=False` y el detector se apaga para esos motores.
- **Un CRS compuesto se reportaba como desconocido.** PDAL escribe las nubes con un
  `COMPD_CS` —UTM más un vertical sin datum—, y la heurística del `AUTHORITY` declarado
  tomaba el **último** del texto: el del metro del componente vertical, `EPSG:9001`. Una
  nube perfectamente georreferenciada salía sin CRS. Ahora se resuelve por el componente
  horizontal.
- El lector LAS confundía el «identificador de sistema» con el «software generador». Son
  dos campos distintos y muchos programas rellenan los dos, así que pasaba desapercibido.

### Añadido (documentación)

- La documentación que `AGENTS.md` declaraba en su cadena de precedencia y todavía no
  existía: `docs/ARCHITECTURE.md`, `docs/MVP.md`, `docs/MOTORES.md`, `docs/FORMATOS.md`,
  `docs/REFERENCES.md`, `docs/DEPLOY.md` y las dos de integración con AeroBim y AeroControl.
- Gate reproducible: `scripts/verify.ps1`, `scripts/run.ps1`, `scripts/sondear.ps1` y
  `scripts/sondear.py`.
- CI en GitHub Actions, **verde**, corriendo el gate completo en una máquina **sin GDAL**.
  Un segundo flujo `oraculo.yml` instala GDAL y PDAL desde conda-forge para las pruebas
  marcadas, semanalmente y sin bloquear ningún PR.

### Corregido

- El conteo de pirámides ya no incluye los IFD de la banda de máscara, que lo inflaban al
  doble en cualquier archivo con alfa convertido a máscara.
- `sondar_pdal()` ya no devuelve la fila de guiones del banner como número de versión.
- `desde_wkt()` resuelve el `.prj` que escribe Metashape. pyproj no lo identifica ni con
  confianza 20 — devuelve cero candidatos —, así que se lee el `AUTHORITY` que el propio WKT
  declara **y se verifica** contra la definición canónica comparando los parámetros de
  proyección. Leerlo sin verificar habría sido adivinar.

## [0.1.0] — 2026-09-08

Primera versión. Andamiaje al estándar de la familia Aero y el núcleo de detección, que es
lo que sostiene el diagnóstico: **saber qué tiene un archivo dentro y dónde va a abrir**.

### Añadido

- **Lector propio de cabecera TIFF y BigTIFF** (`apps/formats/tiff.py`), sin GDAL. Devuelve
  variante, dimensiones, bandas, banda alfa, compresión, teselado, pirámides, EPSG, GSD y
  extensión en terreno. Navega el archivo con desplazamientos, no leyendo un prefijo, y
  nunca lee un píxel.
- **Catálogo de formatos** (`apps/formats/catalogo.py`) con las cuatro familias. BigTIFF es
  una entrada propia y no una bandera de GeoTIFF: comparten extensión pero uno abre en
  Civil 3D y el otro no.
- **Detección** por firma → extensión → GDAL, con la confianza declarada en la respuesta.
  Una discrepancia entre firma y extensión no es un error: gana la firma y se avisa.
- **CRS con procedencia** (`apps/formats/crs.py`): `incrustado`, `sidecar-prj`, `declarado`
  o `desconocido`. `PuntoConCrs` impide que una coordenada viaje sin su sistema.
- **Perfiles de destino y veredictos** (`apps/targets/perfiles.py`) para Civil 3D, QGIS,
  ArcGIS Pro, Google Earth, visor web y AeroBim.
- **Contrato de motor, registro y matriz de capacidades** (`apps/engines/`), con tres
  estados por celda: disponible, instalable y no soportado.
- **Sondas** de GDAL, PROJ, PDAL, ECW y ODA. La de ECW distingue tres motivos —
  `sin-driver-ecw`, `sin-clave-ecw`, `sin-binario-ecw` — porque son tres arreglos distintos.
- **Catálogo de motivos** con código estable (`apps/jobs/motivos.py`), extendiendo el
  vocabulario que ya usa AeroBim.
- **Dos modos**, `taller` y `nube`, con la misma base de código. En taller
  `AEROCONVERT_RAICES_PERMITIDAS` es obligatoria y `manage.py check` falla sin ella.
- **Identidad visual**: quinto color de la familia, magenta `#F15BB5`, a 55° del violeta de
  AeroBim y 70° del ámbar de AeroPlanner. Marca y variante oscura en `assets/`.
- **73 pruebas**, verdes en una máquina sin GDAL, con TIFF de unos 400 bytes construidos
  byte a byte dentro de la propia prueba.

### Notas de verificación

El lector de cabecera se contrastó contra `gdalinfo` sobre archivos de obra reales y
coincide en variante, dimensiones, bandas, compresión, teselado, EPSG y **número de
pirámides**, incluido el caso en que hay banda de máscara y sus IFD inflarían la cuenta al
doble.

Un detalle que se descartó a propósito: un escritor puede dejar IFD más pequeños **sin**
`NewSubfileType`. Contarlos como pirámides parecía razonable, pero el oráculo dice que GDAL
no los expone como overviews —y por tanto QGIS tampoco los usa—, así que se cuentan aparte.
Prometer un zoom rápido que ningún programa va a dar sería peor que callarlo.
