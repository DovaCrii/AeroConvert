# HANDOFF — dónde retomar

**Última sesión: 2026-09-25.** Léelo antes que `MASTER_PLAN.md`.

## Punto exacto de retome — fase 9

| Etapa | Rama | Estado |
| --- | --- | --- |
| F9.0 – F9.2 | — | **En `main` y desplegadas en p340** el 2026-09-25 |
| F9.3 | `codex/fase-9-3-contraste` | Hecha, portón verde; PR contra `main`, esperando |
| F9.4 | — | **La siguiente**: lo visual (una acción principal, profundidad, radios, móvil) |

**Ninguno se fusiona sin tu permiso.** Y los PR van ahora **contra `main`**, no apilados: al
fusionar el #1, el #2 y el #3 entraron en sus ramas intermedias y no en `main`, porque GitHub
solo cambia la base de un PR apilado si se borra la rama de abajo. Hizo falta el #4 para
llevarlos.

**Verificado en p340 tras desplegar**: `/salud/` en `ok` con la migración `jobs/0002`
aplicada, y el OCR con el Tesseract de verdad por el camino del proceso hijo —
`PROGRESO 1.000`, una página verificada, `texto: True`—. En producción no hay pytest, y así
debe ser: la comprobación se hizo desde `manage.py shell`.

**Pendiente de F9.3**: la pasada de teclado sin ratón por la barra y un formulario, en los dos
temas. Las reglas están cargadas y los tokens se resuelven bien, pero el estado de foco no se
puede provocar desde el panel del navegador.

**F9.2 en una frase: las veinte herramientas de documentos pasan por la cola.** La pantalla
mira y comprueba; la acción final crea un trabajo, y la ficha trae progreso, recibo, descarga
con dueño, reintentar e historial. El proceso hijo es `apps/documents/tarea.py` (sin Django),
salvo Office, que es pwsh directamente. Hay dos carriles en el mismo obrero.

**Al desplegar F9.2** no hay que hacer nada a mano: `desplegar.sh` aplica la migración
`jobs/0002` y reinicia el obrero, que ya arranca los dos carriles. Y después, en p340:

1. **La prueba de extremo a extremo del OCR**, que aquí se salta porque no hay Tesseract:
   `uv run pytest apps/documents/test_ocr_en_cola.py -k DondeTesseractEsta`.
2. **Subir un PDF a cada herramienta y descargarlo desde la ficha.** Era lo que no
   funcionaba en trece de las veinte.
3. **Proteger un PDF y buscar la contraseña en la base**: no debe aparecer en
   `jobs_conversionjob`, `jobs_jobevent` ni `jobs_entradadetrabajo`. La prueba
   `test_la_contrasena_no_queda_en_ninguna_fila` lo hace sobre la base de pruebas.

**Pendiente de F9.2, con fecha**: retirar el modelo `Resultado` y la vista
`documents:descargar` **un día después de desplegar**, cuando hayan caducado las filas que
dejaron Unir e Imágenes. Ninguna herramienta crea ya filas nuevas; se mantiene la vista solo
para no romper un enlace de ayer.

**Lo que no se pudo correr aquí**: Office de verdad (se prueba con un Python en el sitio de
pwsh), un `.mdb` de verdad (no hay uno de prueba en el repositorio y crearlo exige el propio
ACE) y Tesseract. El procedimiento manual de los catálogos sigue en
`docs/PRUEBAS_CON_ORACULO.md`.

> **Aviso sobre este documento.** Estuvo fechado el 11 de septiembre hasta el 21, diez días y
> 262 pruebas después, mientras pedía en su primera línea que se leyera antes que nada. El
> documento que se lee primero no puede ser el más viejo: si retomas esto y algo de aquí no
> cuadra con el código, **gana el código** — y actualiza esta página antes de seguir.

---

## Lo que pasó entre el 11 y el 21 de septiembre

Diez días de trabajo que este documento no recogía:

| | |
| --- | --- |
| **Desplegado en el servidor de la oficina** | `p340`, publicado en internet por Tailscale Funnel. Fase 6 cerrada entera |
| **Entrar con el correo** | Y cada aplicación con su propia cookie: saltar entre AeroControl y AeroConvert cerraba la sesión |
| **El catálogo con buscador, y es la portada** | Entiende sinónimos («juntar» encuentra «Unir PDF»), pares de formato («tif a jp2») y acentos |
| **La barra**, de siete entradas planas a cuatro y un desplegable | Con el buscador siempre visible |
| **Markdown** (F7.1) | Excel, CSV, Word, PDF, EPUB y página web → Markdown, y la vuelta a PDF |
| **Catálogos de tubería** (F7.6) | `.mdb` de Plant 3D ↔ Excel, probado contra un catálogo real de 481 filas |
| **La subida funcionaba mal** | En cinco pantallas nunca había funcionado, y el tope de 200 MB decía «No llegó ningún archivo» en vez de decir el tope. Hoy son 2 GB y hay barra de avance con porcentaje real |
| **`docs/ESTILO.md`** | Las reglas de forma, con la prueba que las sostiene |

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
| F5 | **PDF**: leer, unir con miniaturas y giro, dividir, imágenes ↔ PDF, numerar, marca de agua, proteger, y Office ↔ PDF en los dos sentidos |

| F6 | **Desplegado**: systemd, dos servicios, respaldo con temporizador, publicado por Funnel |
| F7.1 | **Markdown** en los dos sentidos, desde seis formatos |
| F7.6 | **Catálogos de tubería** de Plant 3D ↔ Excel |
| F5.10 / F7.3a | **Comprimir PDF**, y negarse cuando comprimir empeoraría el archivo |
| F5.11 / F7.3d | **Reconocer el texto de un escaneo**, verificado sobre un escaneo real |
| F3.4 | **DWG y DGN v8** por ODA ⚠ falta correrlo con el conversor puesto |
| F7.4 | **Tino**, que contesta desde esta máquina y con la puerta de fuera cerrada |

**1.843 pruebas** en 74 ficheros, verdes **sin GDAL, sin PDAL, sin Office, sin Tesseract y
sin el conversor de ODA instalados** (2026-09-21). Nueve se saltan solas diciendo cuál de
esos programas les falta, y eso es exactamente lo que se quiere: **una capacidad ausente se
apaga con su motivo, no revienta**.

**El servidor sí tiene Tesseract** desde el 2026-09-21 (5.5.0, con `spa`, `eng` y `osd`), y
la conversión se corrió allí sobre un escaneo de verdad: `antes tiene texto: False` →
`despues: True` → `'ACTA DE RECEPCION'`, sin una errata. Las pruebas de extremo a extremo se
saltan **en esta estación**, no en el servidor.

La ⚠ que queda es lo contrario de una queja: es lo único de esta tanda cuyo camino completo
**no se ha podido correr**, porque el conversor de ODA no está en ninguna de las dos
máquinas. El comando, las negativas y el criterio sí se comprueban.

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
   `AEROCONVERT_ODA_CONVERTER`. **En Linux, además `sudo apt install xvfb`**: ODA está hecho
   con Qt y no arranca sin servidor gráfico aunque no dibuje nada. Con eso se abre DWG y DGN
   v8 hacia los seis destinos vectoriales — el motor y las pruebas del comando están desde el
   2026-09-21, y lo único que falta es el programa. Hoy la sonda responde `sin-conversor` y la
   herramienta sale apagada ofreciendo «Guardar como DXF», que hace el mismo primer paso.
4. **Decidir dónde vive la copia del respaldo fuera de la máquina**, y ponerla en `.env`
   como `AEROCONVERT_RESPALDOS_FUERA`. Es el único riesgo del servidor **sin arreglo posible
   después**; el mecanismo ya está y la decisión no es técnica.
5. **Decidir si Tino pregunta fuera, y a quién.** Hoy contesta desde esta máquina y la
   puerta de fuera nace cerrada. Abrirla es una decisión sobre los datos de la oficina en una
   aplicación publicada en internet abierto, así que no se ha tomado en el código.
6. **La SDK de Hexagon** para ECW. El motor está escrito y la clave ya viaja solo en el
   entorno del hijo, con su prueba centinela.
7. **Volver a enseñarle la aplicación al equipo**, y esto no es una tarea de código —es la
   que más rinde de la lista. Medido el 2026-09-21 en el servidor: **seis cuentas, nueve
   entradas correctas, cuatro personas que entraron alguna vez, dos que no entraron nunca, y
   cero conversiones geoespaciales.** La última entrada de cualquiera fue el **15 de
   septiembre**, la fecha de la caída de AeroBim y del `accept=".pdf"` heredado que el equipo
   reportó como «no funciona».

   **Corregido el 2026-09-25**: aquí ponía que «la aplicación lleva seis días funcionando para
   nadie», y el dato no da para tanto. **Las herramientas de PDF no crean `ConversionJob`**, así
   que ese cero no cuenta si alguien usó Unir o Comprimir: esas no dejan rastro. Lo que sí se
   sabe es que nadie ha convertido nada geoespacial, y que desde el 15 nadie ha vuelto a
   entrar. **Desde F9.2 las herramientas de PDF sí crean trabajos**, así que a partir del
   despliegue ese número ya cuenta todo el uso.

Y lo que se contesta solo, sin leer nada:

```bash
ssh p340 'cd /opt/aeroconvert && sudo ./scripts/revisar-servidor.sh'
```

**Lo que solo espera a que alguien lo escriba:**

8. **F2.6 — 3D Tiles y Potree** con `py3dtiles`, para el visor web. Habría que añadir la
   dependencia.
9. **F4 — BIM y malla** con `ifcopenshell`. Tampoco está instalada.

## PDF: lo que queda

Lo hecho está arriba, y **comprimir y OCR ya no están aquí**: se hicieron el 2026-09-21.
Lo que falta, con lo que cuesta cada cosa de verdad:

- **Firmar PDF.** El caso real es el acta firmada, y es el único de la cola larga que
  alguien ha pedido de verdad. Firma dibujada primero; la digital con certificado es otra
  cosa y otra fase.
- **Ordenar, eliminar y extraer páginas sueltas.** Medio hecho: la receta de «unir» ya sabe
  hacerlo, falta la pantalla de una sola entrada.
- **La cola larga** —comparar, censurar, recortar, PDF/A, formularios—. Cada una entra
  cuando alguien la pida dos veces.

## Poner esto en una VM: cómo se hace

**Comprobado el 2026-09-11 y listo salvo la máquina.** El despliegue es
`DJANGO_SETTINGS_MODULE=config.settings.prod` **con `AEROCONVERT_MODO=taller`** y las raíces
apuntando a la carpeta Samba. El procedimiento entero está en `despliegue/README.md`; los
ficheros que se copian a `/etc`, en `despliegue/`.

**No uses `config.settings.nube`**: es el modo de las subidas, la subida no está escrita, y
`manage.py check` se niega a arrancar con él.

Lo que se arregló para poder hacerlo, y por qué ninguno daba un error:

- **Dos personas podían acabar con la misma ruta de salida**, y la segunda descarga servía el
  archivo de la primera. Ahora `_destino_libre()` en el runner pregunta «¿lo reclama el
  trabajo de otro?» —pisar lo tuyo sigue permitido— y la descarga comprueba que el archivo
  siga teniendo el tamaño que produjo ese trabajo.
- **Ocho intentos fallidos de cualquiera bloqueaban a todo el equipo**, porque detrás de
  nginx comparten la IP del proxy. Ahora es por la pareja usuario + IP, con
  `AXES_CLIENT_IP_CALLABLE` propio (`apps/core/ip.py`) — los `AXES_IPWARE_*` **no harían
  nada**: axes solo los mira si `django-ipware` está instalado, y no lo está.
- **Un 500 no dejaba rastro en ninguna parte.** Ahora hay `LOGGING`, a la salida de error y
  no a un fichero: con cuatro procesos escribiendo, `RotatingFileHandler` corrompe la
  rotación y se pierde justo el tramo con más actividad.
- **El tope de ruta eran 255 caracteres también en Linux**, donde son 4096. Una carpeta de
  obra pasa de 255 sin esfuerzo: era un bloqueante silencioso.
- **`verify.ps1` corría `check --deploy` sobre `config.settings.dev`** desde el primer día,
  porque no fijaba `DJANGO_SETTINGS_MODULE`. Arreglado, y añadido al CI.

## Lo que queda

Comprobado el **2026-09-11**. Resumen en una frase: **el modo taller está terminado y en uso;
el modo nube arranca y no convierte nada.** El detalle está en `docs/DEPLOY.md`, que hasta
hoy afirmaba cosas que no existían.

Lo que sí funciona ya, medido y no supuesto:

- `config.settings.nube` carga; `manage.py check --deploy` solo se queja de `ALLOWED_HOSTS`
  vacío, que es una variable de entorno.
- `manage.py migrate` sobre una base vacía aplica las 25 migraciones sin un error.
- Whitenoise está listo y con su almacén propio.
- El dimensionado de la VM está medido y fechado en `docs/DEPLOY.md` — **4 vCPU, 4 GB,
  80 GB SSD** para lo normal.

Lo que queda, en orden:

1. **Instalar en la VM.** Es lo único que separa esto de estar en uso, y solo depende de que
   exista la máquina. Procedimiento en `despliegue/README.md`. **El paseo de aceptación ya
   está hecho** sobre una instalación limpia —base vacía, `collectstatic`, usuario nuevo,
   subir dos PDF por HTTP, componerlos y bajarse el resultado—; las cifras están en
   `docs/PRUEBAS_CON_ORACULO.md`, corrida del 2026-09-14.
2. **Medir una nube real** con `pdal info --summary` sobre un archivo en disco local. La regla
   de 105 MB por millón está medida sobre **un** archivo de 9,6 M puntos; extrapolarla a mil
   millones es aritmética, no medición, y de eso depende si hace falta otro motor.

**SQLite se queda, y ya no es una pregunta abierta:** con el despachador en su propia unidad
hay un solo escritor pesado, y WAL con `busy_timeout=20000` cubre de sobra a 4-5 personas
sondeando. Se cambia el día que aparezca `database is locked` en el registro, no antes.

## Ideas anotadas, sin decidir

Cosas que se han pensado y **no** se han hecho. Están aquí para que no se vuelvan a pensar
desde cero, no como compromiso.

- ~~**Abrir el taller al resto de la oficina.**~~ **Resuelto el 2026-09-11**, y la respuesta
  fue la que se apuntaba aquí: no se abre `run.ps1` en red, se despliega en la VM con
  `config.settings.prod` y las raíces apuntando a la carpeta compartida. La preocupación
  original —«una ruta es lectura del disco entero»— la cubre ahora `manage.py check`, que
  rechaza una raíz demasiado ancha **cuando la máquina es compartida**, y la chapa detecta lo
  mismo y deja de prometer que los archivos no salen de ahí. Se deja el texto original debajo
  porque explica el razonamiento.

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
- **`500.html` no puede extender `base.html` ni usar `{% static %}`.** Django la renderiza
  con `loader.get_template(...).render()`, **sin `request` y sin procesadores de contexto**.
  Y la causa número uno de un 500 en todas las páginas es un `staticfiles.json` ausente, así
  que una `500.html` que dependiera de `{% static %}` reventaría justo en ese escenario y lo
  que llegaría sería el texto plano de Django. La marca va incrustada; hay una prueba que lo
  vigila. Las otras tres sí extienden la base, porque esas sí se renderizan con `request`.
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
- **Word abre lo que le eches y lo guarda como `.docx` con código cero.** Un archivo de texto
  con la extensión cambiada a `.pdf` pasa sin quejarse. Por eso `mirar_pdf()` comprueba la
  firma **en Python** antes de lanzar el hijo; la extensión no es el formato.
- **Y un PDF escaneado «se convierte» a Word perfectamente**: medio mega de fotos pegadas,
  cero palabras editables, código de salida cero. Medido: cero caracteres extraíbles. Se
  detecta antes con `mirar_pdf()` y la pantalla no ofrece el botón.
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

- **El cliente de pruebas de Django manda siempre multipart.** Un formulario sin
  `enctype="multipart/form-data"` pasa todas las pruebas de subida y en un navegador de
  verdad no manda el archivo. Le pasó a Proteger; lo vigila `test_subir_en_pdf.py`.
- **`tarea.py` no puede importar nada que traiga Django**, ni las sondas: guardan en la
  caché. Lo que el hijo necesita saber —la ruta de Tesseract, el controlador de Access, la
  contraseña— se lo pasa el padre por el entorno. Ver `motor.plan()`.
- **`ruff check --fix` quita un import que solo se reexporta.** Le pasó a
  `secretos.VARIABLE`; por eso ahí es una asignación y no un `import ... as`.
- **La base local de desarrollo no se migra sola.** Tras traer una rama con migraciones,
  `uv run python manage.py migrate` antes de abrir la pantalla, o el primer POST da
  `no such column`.

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



