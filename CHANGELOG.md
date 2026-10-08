# Registro de cambios

Sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]


### Cambiado — transiciones de estado y entrada suave (F13.13)

- **Botones, campos, baldosas y enlaces del lateral** cambian de color, fondo, borde y opacidad en 160 ms al pasar, enfocar o desactivarse; **nada se desplaza, no hay sombras ni degradados** (F13.7 sigue en pie). Cada página y lo que htmx pinta (resultados, ficha, lo reconocido) **aparece** en 220 ms por opacidad. Con `prefers-reduced-motion` todo es instantáneo. Cinco pruebas nuevas en `test_plano.py`: ninguna transición `all`, nada de `transform` al pasar o enfocar, solo propiedades de estado, la animación solo cambia la opacidad y no deja un contexto de apilado (`backwards`), y el bloque de movimiento reducido. Visto en el navegador, en claro a 375 px y en oscuro a 1280 px, sin desborde.


### Añadido — plano DXF a lámina PDF o SVG (F14.16, primera parte)

- **«Plano DXF a PDF»**: dibuja un DXF (líneas, polilíneas con arcos, círculos, arcos, elipses, splines, textos y puntos; bloques y cotas expandidos) en una lámina de **A4 a A0**, apaisada o vertical según el plano, **centrada y con margen fijo de 10 mm**, con el color de sus capas (el blanco sale negro). **La escala solo se dice si el plano declara sus unidades** (`$INSUNITS`): si no, sale ajustado al papel y no se inventa un «1:500». Las capas apagadas no se dibujan y **lo que no se puede dibujar** (sombreados, imágenes…) **se cuenta por tipo**. Un DWG se rechaza con su camino (pasarlo antes a DXF). Se lee con `ezdxf` (MIT, dependencia nueva) y se dibuja con `reportlab`. Oráculo: PDFium lee la lámina y comprueba que el dibujo toca el margen en el eje que manda y queda centrado en el otro. Queda pendiente el SVG a PDF o PNG, que exige Inkscape.
- Decisión: `docs/DECISION_ARTCRAFT.md` (ArtCraft no se adopta: licencia *fair source* y producto de IA generativa en la nube).

### Añadido — limpiar fotos de dron (F14.14)

- **«Limpiar fotos de dron»**: las fotos de un vuelo (JPG, hasta quinientas) a **un zip con una foto por cada una**. La posición se **conserva** (la foto pasa byte por byte) o se **quita a propósito**: el bloque GPS del EXIF se pone a cero en su sitio y se retira el XMP, que en los DJI repite latitud, longitud y altura. **No se recodifica**: los datos de imagen salen idénticos byte por byte, y no se reescribe el EXIF porque las notas del fabricante guardan desplazamientos que un reescrito rompería (esas notas no se tocan, y la pantalla lo dice). Aparte, saca **dónde se tomó cada foto** a un **KMZ** o un **GeoJSON** (aunque se les quite la posición), y renombra por **fecha y hora** o por **orden de toma**; una foto sin fecha impide renombrar por fecha, con su nombre, en vez de inventar uno. Las fotos sin posición no entran al archivo y se cuentan. El verificador del trabajo relee con Pillow cada foto «sin posición» y cuenta las marcas del KMZ o GeoJSON. Oráculos: `exifread` (nueva dependencia de desarrollo, BSD) y `ogrinfo`.

### Interno — agentes, skills y un hook para no repetir los fallos de esta tanda

- **Puerta rápida con `bandit`** (`verificar.py rapido`) y un **hook `PreToolUse`** que la corre antes de cada `git push` y lo bloquea si falla (`scripts/claude/antes_de_push.py`): el CI había cazado dos veces lo que el gate local habría visto en segundos.
- **`scripts/claude/fusionar_main.py`**: fusiona `main` y resuelve solo los choques de «los dos añadieron» (dos herramientas nuevas en el mismo registro), **validando** con `ast` (sin claves repetidas) y XML; lo que no sabe resolver, y las tablas de estado de `MASTER_PLAN.md` y `SEGUIMIENTO.md`, lo deja con sus marcas.
- **Skill `/nueva-herramienta`** y una prueba (`test_herramientas_completas.py`) que recorre las piezas de cada herramienta de documentos: campos, icono, grupo, cola, tarea, pantalla con y sin sesión y prueba de su pantalla.
- **Agentes del proyecto** en `.claude/agents/`: `revisor-de-reglas` (solo lectura, contra las cinco reglas de `AGENTS.md`) y `fusionador-de-pr` (solo `gh`: espera el CI y fusiona en verde).
- `/avanzar` y `/abrir-pr` recogen lo aprendido: bandit antes de subir, reintento cuando GitHub falla al fusionar, y subir de uno en uno los PR que añaden herramientas.

### Añadido — convertir imágenes por lote y la traza de un video de dron (F14.13, F14.18)

- **«Convertir imágenes»**: varias fotos a la vez a **JPG, PNG, WebP o TIFF**, con tamaño (lado mayor, sin agrandar nunca), giro (según la orientación de la foto, por omisión, o fijo), recorte centrado a 1:1, 4:3, 3:2 o 16:9 y calidad. Se entrega **un zip con una imagen por cada una que entró**, conservando fecha, perfil de color y **GPS** (en TIFF, sin comprimir: libtiff rechaza toda compresión con EXIF, medido). **HEIC** solo si el servidor trae `pillow-heif`, y si no, se dice por foto antes de encolar; el lote es todo o nada. La verificación del trabajo reabre cada imagen con Pillow y compara formato y medidas con lo que se dijo.
- **«Traza de un video de dron»**: el `.SRT` que graba un DJI junto al video (una posición por fotograma, en el formato nuevo `[latitude: …]` y en el antiguo `GPS(lon,lat,alt)`) a **GPX** (QGIS) o **KML** (Google Earth), con todos los puntos o uno por segundo o cada cinco. Un fotograma sin posición (`0, 0`) se descarta y se cuenta. **La hora solo se escribe si se dice cuántas horas se aparta la cámara de UTC**: el SRT la trae sin zona y ponerla como UTC correría la traza respecto de sus fotos.

### Añadido — la portada de J.E.J. desde sus plantillas Word (F14.19)

- **«Portada de J.E.J.»**: rellena las dos plantillas de la empresa —«Portada Documentos» (código `JEJ-…`, título del procedimiento y autor) y «Portada Ofertas y Planes Licitaciones» (servicio y plan)— y entrega un `.docx` con el logotipo y el diseño intactos. El PDF es un clic más: «Seguir con este archivo» → «Office a PDF».
- **Las plantillas no están en el repositorio** (llevan el logotipo): viven en la carpeta que dice `AEROCONVERT_PLANTILLAS_JEJ`. Sin ella, o sin alguno de los dos archivos, la herramienta sale apagada con su motivo (`sin-plantillas`); no se sustituye por una portada inventada.
- Se rellena por la **posición** de los marcadores (`XXXX`) en cuerpo, encabezado y pie, y se cambia también `dc:creator`, a lo que está enlazado el pie. Si la plantilla cambió y un campo no tiene dónde ir, **falla diciendo cuál** en vez de entregar una portada con `XXXXXX`; y la verificación del trabajo lo vuelve a comprobar leyendo el zip.
- Un Word terminado ahora ofrece seguir a PDF, como ya hacía un PDF con las demás herramientas.

### Añadido — reparar un PDF dañado y pasar una página web a PDF (F14.20)

- **«Reparar un PDF dañado»**: recupera las páginas que se puedan leer de un PDF que no abre (una descarga cortada, un adjunto truncado). PDFium reconstruye el índice leyendo el archivo entero y se escribe de nuevo, válido; dice cuántas páginas se recuperaron. A diferencia de las demás pantallas, **no lee la cabecera antes**: justo ese es el archivo que se quiere arreglar. No inventa lo que ya no está.
- **«Página web a PDF»**: el texto, los títulos, las listas y las tablas de una página guardada (`.html`). **No es un navegador**: no respeta el diseño, no baja imágenes ni hojas de estilo y no ejecuta programas; la pantalla lo dice antes. Pasa por los dos convertidores que ya existían (HTML a Markdown, Markdown a PDF).

### Añadido — redactar de verdad un PDF (F14.8)

- **«Redactar: tachar de verdad»**: tacha textos (un nombre, un RUT; sin distinguir mayúsculas) y áreas (en milímetros, para una foto o un sello) de modo que **ya no existan en el archivo**. Un rectángulo negro encima deja el texto debajo, donde se copia; aquí las páginas afectadas se convierten en imagen con lo tachado ya puesto y el documento se escribe nuevo, así que del original no pasa nada de esa página (ni texto, ni imágenes de debajo, ni el `Info`).
- **El precio, dicho en pantalla**: la página redactada ya no tiene texto que buscar ni copiar, y pierde marcadores y anotaciones. Las demás pasan tal cual; para recuperar la búsqueda, «Reconocer texto (OCR)».
- **Los textos a tachar no se guardan**: salen de la pantalla al trabajo por el mismo camino cifrado que la contraseña de «Proteger», y el informe cuenta cuántas veces apareció cada uno sin decir cuál era. Si nada aparece y no hay áreas, termina «hecho» sin archivo (`nada-que-redactar`).

### Añadido — recortar y cambiar el tamaño de un PDF, y compararlo con otra versión (F14.6, F14.7)

- **«Recortar y cambiar el tamaño»**: tres modos. **Al contenido**: cada hoja queda del tamaño de lo que tiene dibujado más un margen (se mide dibujándola con PDFium; una hoja en blanco se deja como está). **A mano**: tantos milímetros de cada lado, de lo que se ve. **A otra hoja** (A0 a A4, Carta, Oficio): el contenido se escala sin deformarse y queda centrado; una lámina apaisada sigue apaisada. Funciona también con páginas giradas. Recortar no es borrar: lo que queda fuera sigue en el archivo, y la pantalla lo dice.
- **«Comparar dos PDF»**: se pide el antes y el después y se dibujan y restan, así que se compara **lo que se ve**, no el archivo. El informe trae solo las páginas que difieren, con tres columnas (antes, después y las diferencias en rojo); una página que sobra o cambió de tamaño se informa aparte. Si no cambia nada no hay archivo: el desenlace `sin-diferencias` lo explica.

### Añadido — rellenar formularios PDF y poner una firma visible (F14.3, F14.4)

- **«Rellenar un formulario PDF»**: lista los campos del documento y escribe en los de **texto y casillas**; las listas, opciones y firmas se muestran pero no se editan, y la pantalla lo dice. Con **«Aplanar al terminar»** lo escrito pasa a la página y los campos desaparecen (PDFium aplana y se reescribe sin `AcroForm`): ya no se puede cambiar. Siempre una copia.
- **«Poner una firma en un PDF»**: estampa una imagen de firma (PNG o JPG), con la fecha de hoy y un texto debajo si se quiere, en la página que se elija, en una de las seis posiciones de la numeración y en tres tamaños; funciona también en páginas giradas. **No es una firma digital** (la pantalla lo dice antes que nada): no prueba quién firmó ni detecta cambios posteriores. La imagen sube con el trabajo y se borra sola al día.

### Añadido — ver, editar y limpiar los metadatos de un PDF (F14.2)

- **«Ver y limpiar metadatos»**, en «Revisar, firmar y proteger»: dice quién figura como autor, con qué programa se hizo y cuándo —el `Info` del documento y su copia en XMP—, y permite **cambiar campos** o **limpiar todo** antes de entregarlo. Siempre se entrega una copia; el original no se toca.
- **Limpiar de verdad:** el documento se escribe nuevo con las páginas del original, porque borrar solo el `/Metadata` de la raíz deja el flujo XMP suelto dentro del archivo, con el nombre del autor en los bytes (lo midió la prueba). Al editar, el XMP se retira para que no contradiga lo nuevo.
- Lo que no promete: los datos propios de una fotografía incrustada (EXIF) no son del documento y no se tocan; la pantalla lo dice.
- Para las pruebas entra `pikepdf` (MPL-2.0) **solo como dependencia de desarrollo**, el otro lector con el que se comprueba lo escrito por `pypdf`.

### Añadido — extraer las imágenes de un PDF (F14.1)

- **«Extraer imágenes de un PDF»**, en «Convertir documentos»: saca las fotos y los logotipos incrustados **con la resolución con que entraron**, sin dibujar las páginas (para eso sigue «PDF a imágenes»). Cada imagen **una sola vez** aunque se repita en cien páginas, sin las diminutas (filetes y viñetas, menos de 32 px), siempre en un zip.
- Un PDF sin imágenes no falla: termina «hecho» sin archivo y lo explica (`sin-imagenes`).
- Extraer páginas ya lo hace «Dividir PDF» con rangos; esta fila cierra F14.1.

### Documentación — el reparto con Stirling-PDF (F14.0)

- [`docs/DECISION_STIRLING_PDF.md`](docs/DECISION_STIRLING_PDF.md): las herramientas de PDF de uso diario se hacen dentro de AeroConvert; la cola larga se delega en Stirling-PDF **local y sondeado** (`AEROCONVERT_STIRLING_URL`), apagada con motivo y alternativa si falta. Nada sale del equipo y no se importa ni se copia nada suyo.

## [0.11.0] — 2026-10-07

Cierra la fase 13: una interfaz con un solo árbol de herramientas, nombres por utilidad, trato de
usted, iconos y color coherentes, plana pero con color, y una portada que empieza por el archivo.

### Añadido — buscar el sistema de referencia por nombre, sin saber el EPSG

- En la ficha de un archivo sin sistema declarado, **sobre el campo «Código EPSG»**, hay un buscador: «UTM 19 sur», «SIRGAS Chile», «PSAD56», «wgs84» o el número. La lista sale de la base de PROJ que ya trae `pyproj` (nada nuevo que instalar ni copiar): sistemas vigentes, proyectados y geográficos, con su zona de uso.
- **No adivina** (regla 3): con la caja vacía no ofrece ninguno, el orden depende solo de lo escrito y nada viene elegido. Pulsar uno lo escribe en el campo EPSG y dice cuál se eligió; el servidor lo valida igual que si se hubiera tecleado, y queda en la bitácora con su nombre.
- Pruebas: `test_crs_busqueda.py` (cada resultado se abre con `pyproj` con el mismo nombre) y `test_buscar_crs.py`.

### Añadido — la portada empieza por el archivo (F13.8)

- **Arriba, la zona de soltar** (la misma de Convertir, ahora un componente compartido); el buscador y el catálogo quedan debajo para quien trae una intención y no un archivo.
- **Pista antes de que termine la subida:** al elegir o soltar un archivo, el navegador manda solo sus primeros 4 MiB (`File.slice()`) a `reconocer/`, que dice qué parece (por la cabecera, o solo por la extensión, y lo declara) y **qué herramientas aplican a ese archivo**, con las apagadas y su motivo. Para los formatos con el índice al final (TIFF, KMZ, PDF) avisa de que lo de dentro se confirma al terminar de subir. Si la pista falla no se muestra error: queda la ficha de siempre.
- La ficha completa (veredictos, destinos) llega por el camino de antes, con el archivo entero.

### Cambiado — la barra superior en tres zonas (F13.9)

- **La explicación del modo** («los archivos no salen de este equipo»…) pasa al pie del lateral, siempre visible; la chapa sigue en la barra. Sin sesión (pantalla de entrada), que no tiene lateral, se queda en la barra.
- **El buscador de la barra no baja de 160 px** y ya no desaparece en pantallas estrechas: a 375 px pasa a una segunda fila, junto a la cuenta, y mide 248 px (antes 136 por un ancho fijo, y oculto por debajo de 1000 px).

### Añadido — la huella del archivo sobre una retícula de coordenadas (F13.11)

- En la ficha, **«Dónde está»**: un dibujo de la huella sobre meridianos y paralelos con su valor, **sin mapa base** (decisión D5) y sin biblioteca de mapas: es un SVG que hace el servidor, así que no hay nada que vendorizar y nada sale del equipo. Más una tabla con las cuatro esquinas en longitud y latitud, que es lo que lee un lector de pantalla.
- Sale de la cabecera (origen y escala de un GeoTIFF, mínimos y máximos de un LAS) y **solo con sistema de referencia conocido**: sin él no hay huella, porque unas coordenadas sin sistema no dicen dónde está nada. Una imagen girada tampoco se dibuja.
- Oráculo: las esquinas coinciden con `gdalinfo -json` (`wgs84Extent`) con error ≤ 1e-7° en EPSG:32719, 5361 (SIRGAS-Chile 2002 / 19S) y 24879 (PSAD56 / 19S).

### Cambiado — el lateral reducido muestra un icono por grupo, con su cuenta

- Reducido, el lateral ya no esconde los ocho grupos: cada uno es **un icono con la cantidad de herramientas como insignia** y su nombre en el `title`; pulsarlo lleva al grupo de la portada, que se abre aunque se hubiera dejado cerrado (`#grupo-…`).
- Con el lateral ancho, cada grupo lleva ahora su símbolo delante del nombre.

### Cambiado — la interfaz plana, pero con color (F13.7)

- **Fuera los degradados** (eran 8: el velo del fondo, la barra, el lateral y las baldosas) y **las sombras con difuminado**: las superficies se apoyan en un anillo de 1 px (`--av-elev-0` a `-2` son ahora el mismo) y se distinguen por el cambio de superficie y por el color. `--av-elev-3` queda como **la única sombra**, para lo que flote encima de lo demás (hoy nada).
- **Pasar el ratón cambia el color, no mueve nada:** las tarjetas ya no suben un píxel ni la baldosa crece; el aro se marca con el color de la tarjeta.
- **Las baldosas siguen con color, también en oscuro**, pero de relleno **sólido**: el fondo de su familia con un 16 % de su propio color. Sustituye al resplandor con degradado del cambio anterior. El icono se lee sobre ese relleno mezclado con más de 4,5:1 en las nueve familias y en los dos temas oscuros.
- `test_plano.py` falla con un degradado, con una sombra con difuminado fuera de lo que flota, o con un `transform` al pasar el ratón.

### Cambiado — iconos sin conflictos, una sola familia y tres colores de familia nuevos (F13.4 a F13.6)

- **Un icono, un significado.** «Todas las herramientas» ya no usa el de QGIS (`icon-todas`), Tino ya no comparte el del mensaje informativo (`icon-tino`), CSV a Markdown deja el de Excel (`icon-texto-csv`), `icon-pdf-a-pdf` pasa a llamarse `icon-imagen-a-pdf` y la flecha de los grupos del lateral, que estaba dibujada suelta en `base.html`, entra al sprite (`icon-chevron`).
- **Una familia de trazo:** los 51 símbolos del sprite usan **un solo grosor, 1,75**, sobre 24 × 24 con extremos redondeados. Había nueve grosores distintos (de 1,5 a 2,4) y los iconos no parecían de la misma mano.
- **Color por familia también fuera de PDF:** GNSS (celeste), planta (oliva) e imagen (orquídea), puestos en los huecos de matiz que dejan las seis familias y los tres estados (rojo, ámbar y verde siguen siendo solo de los estados). El de GNSS y los catálogos de Plant 3D ya no comparten color con el resto.
- **Pruebas:** `test_iconos.py` falla con dos significados para un icono, con un trazo distinto o con un SVG dibujado suelto en una plantilla; `test_paleta.py` mide el contraste de las tres familias nuevas en los tres temas y exige 20° de separación de matiz con todo lo demás.

### Cambiado — nombres con una convención (F13.2)

- **Los seis programas de destino son el programa, con su propósito debajo**: «Civil 3D / AutoCAD» y «Para dibujar y diseñar», «QGIS» y «Para analizar y hacer mapas», «ArcGIS Pro», «Google Earth», «Visor web» y «AeroBim». Se acabó «Llevarlo a QGIS». El propósito sale bajo el nombre en la tarjeta de la portada y en el lateral.
- **Siete renombres aprobados:** «Datos de un receptor GNSS a RINEX» → «T02, T04 y crudos a RINEX»; «Word, Excel o PowerPoint a PDF» → «Office a PDF»; «Reconocer el texto de un escaneo» → «Reconocer texto (OCR)»; «Marca de agua» → «Poner marca de agua»; «Proteger PDF» → «Proteger o desbloquear PDF» (también quita la contraseña y el nombre no lo decía); y los catálogos pasan de «de tubería» a «Plant 3D».
- **Una convención con prueba** (`test_nombres.py`): una conversión es «Origen a destino», una operación empieza por un verbo en infinitivo, y ningún nombre pasa de 28 caracteres. **Quien recuerde un nombre viejo lo sigue encontrando:** el buscador halla las herramientas por los doce nombres anteriores.
- El historial guarda el id de la herramienta y no su nombre, así que los trabajos viejos muestran el nombre nuevo sin migrar nada.

### Cambiado — una sola taxonomía de herramientas (F13.1)

- **Ocho grupos, un solo árbol** (`apps/dashboard/taxonomia.py`): Entregar a un programa · Coordenadas y datos GNSS · Organizar PDF · Convertir documentos · Optimizar y reconocer · Revisar, firmar y proteger · Texto, tablas y Markdown · Imagen, video y planta. La portada, el lateral y los dos índices de `/documentos/` lo leen de aquí y **ya no se contradicen**: antes había dos clasificaciones distintas (`CATEGORIAS` y `GRUPOS`) y la misma herramienta vivía en dos grupos según la pantalla.
- Los **catálogos de Plant 3D** dejan «Sacar texto» y pasan a «Imagen, video y planta»; «Markdown a PDF» se queda en «Texto, tablas y Markdown». Una herramienta nueva **sin grupo hace fallar la prueba**, en vez de caer en uno por omisión.
- **Lo que cada persona dejó abierto se recuerda por el id del grupo, no por su título**: renombrar un grupo ya no lo borra. Efecto de este cambio, una sola vez: los grupos que alguien dejó abiertos o cerrados con las claves viejas vuelven a su estado de fábrica.
- `test_taxonomia.py`: toda herramienta en exactamente un grupo, las pantallas leen el mismo orden, y renombrar un grupo no cambia su clave.

### Cambiado — los estilos en línea pasan a clases (F13.10)

- **182 de los 183 `style="..."`** de 32 plantillas pasan a clases: las utilidades de Bootstrap, que ya estaba vendorizado (`d-flex`, `fw-semibold`, `text-center`…), y unas `av-*` nuevas (`av-mt-3`, `av-fs-sm`, `av-mw-22`…) escritas con la escala de `--av-s-*` y `--av-fs-*`. Lo que no tenía peldaño (10, 14 o 18 px) se redondeó al más cercano, así que algún margen cambia 2 px.
- Las `av-*` llevan `!important`, como las de Bootstrap: el atributo `style` ganaba a cualquier regla de la hoja y tienen que seguir ganando.
- **Queda un solo `style`**, el ancho calculado de la barra de avance (`{{ trabajo.progress_percent }}%`), que es un valor y no una decisión de estilo.
- `test_escala_visual.py` falla si vuelve un `style="..."` fijo en una plantilla, y si una plantilla usa una `av-*` que la hoja no define (una clase inexistente no falla: no hace nada). Revisadas a 375 y 1440 px, sin desborde.

### Añadido — la skill `/avanzar` y el tablero del plan

- **`/avanzar [bloque o fila]`** (`.claude/skills/avanzar/SKILL.md`): recorre el plan F13 a F16 por bloques. Elige la siguiente fila que no esté bloqueada, la hace con su oráculo, corre la suite completa en segundo plano, abre el PR, espera el CI, fusiona y deja el tablero al día. Lo que necesita de la persona lo anota y **sigue con lo que sí puede**. No despliega nunca.
- **`docs/planes/SEGUIMIENTO.md`**: el tablero, con los bloques B0 a B10, su estado y la tabla «Pedidos a la persona» (P1 a P10): qué se necesita, para qué fila, en qué forma y qué pasa si no llega.
- La persona despliega **una sola vez, al final** (B10), con la lista exacta que deja `HANDOFF.md`.

### Cambiado — la interfaz habla de usted (F13.3)

- Unas 60 frases que tuteaban pasan a trato de usted, en plantillas, mensajes de las vistas, mensajes del navegador (`respuestas.js`) y descripciones de las herramientas: «Desde su equipo», «Elija el archivo», «Suelte cualquier archivo», «Seguir donde lo dejó», «¿Qué necesita hacer?», «Su cuenta no puede hacer esto». Donde el texto describe lo que hace la aplicación se dice en tercera persona («Se elige el destino, no el formato»).
- **Una prueba lo vigila** (`apps/core/test_trato.py`): mira solo lo que una persona puede leer —texto visible de las plantillas sin sus comentarios, cadenas de Python sin docstrings, cadenas de `static/js/` y los `msgstr` de `locale/es/`— y distingue las palabras que solo existen en tú («tu», «eliges», «quieres»…) de los imperativos de tú **al abrir una frase**, para no marcar «hojas sueltas» ni «lo mira y escribe». La instrucción que se le da al modelo de Tino (`apps/tino/fuera.py`) está exenta: no llega a ninguna pantalla.
- Los `msgstr` de `locale/es/` hoy son solo la cabecera, así que esa parte de la prueba protege lo que se traduzca en adelante.

### Añadido — el plan F13 a F16 y sus decisiones

- **Cuatro fases nuevas en `MASTER_PLAN.md`**: F13 interfaz (una taxonomía, nombres, usted, iconos, plano con color, portada «archivo primero», mapa), F14 suite documental y creativa libre, F15 datums de Chile y calibración, F16 lotes, informe y API. El plan completo, con el diagnóstico y las equivalencias libres de Adobe, está en `docs/planes/PLAN_2026-10-07.md`. La Fase 12 queda como cabecera que remite a la 14.
- **Decisiones de la persona (2026-10-07):** ejecuta Claude; diseño **plano con color**; D1 sí a programas externos GPL/AGPL **solo sondeados** (fila nueva en la tabla de licencias de `AGENTS.md`); D2 a D6 según la recomendación. Todas con fecha en «Lo que solo podías decidir tú».
- `HANDOFF.md` recoge lo que era de la persona y se había perdido: copia de respaldo, despliegue, línea base de `resumen_de_uso` y si el repositorio sigue público; y la regla de correr la suite completa antes de cada push.

### Añadido — «Organizar páginas» y seguir con el resultado (F12.1 y F12.10)

- **Organizar páginas:** una herramienta nueva para **un solo PDF**: se ve cada página en miniatura y se puede girar, subir, bajar, quitar y **repetir**, y se genera el PDF organizado (`<nombre>_organizado.pdf`). Hasta ahora se podía con «Unir PDF» y con un solo archivo, pero no se encontraba; el buscador la halla por «girar», «reordenar», «duplicar» o «borrar páginas». Es la misma máquina que «Unir» —mismo hijo en la cola, misma receta— con otra pantalla, y «Unir» gana el botón de repetir.
- **Seguir con este archivo:** al terminar una herramienta que deja un PDF, la ficha ofrece las siguientes (organizar, dividir, numerar, marca de agua, reconocer texto, comprimir, proteger, unir) **sin descargarlo y volver a subirlo**. El enlace lleva `resultado:<id>`, que la puerta única resuelve solo para quien pidió el trabajo y solo si terminó; nunca lleva la ruta del servidor. El intermedio no se toca: encadenar no sobrescribe el paso anterior.
- Son **21** las herramientas de documentos (`test_cuenta.py` hizo actualizar el README y el manual del servidor).

### Cambiado — nombres que dicen para qué sirve, ancho del lateral y baldosas con color en oscuro

- **Nombres por utilidad, no por programa.** «Llevarlo a Civil 3D» pasa a «Diseño y planos · Civil 3D / AutoCAD», «Llevarlo a QGIS» a «Análisis y mapas · QGIS», y así las seis. Los grupos: «Ortofotos, mapas y nubes», «Datos GNSS a RINEX», «Trabajar con PDF» y «Sacar texto y tablas», cada uno con una frase de para qué sirve.
- **El lateral se agranda y se reduce a mano:** un asa en su borde (arrastre, flechas, Inicio y Fin, doble clic para restablecer), entre 13 y 26 rem, recordada en este navegador. Convive con el modo de iconos solos.
- **Secciones más claras en el lateral:** filete y rótulo entre «Herramientas» y «Más», contador de herramientas por grupo, guía a la izquierda de las herramientas de un grupo abierto y un degradado muy tenue de fondo.
- **Baldosas con color en el tema oscuro:** se tiñen con el de su familia, con aro más marcado y un resplandor suave. Los colores de los tokens no cambian.
- **Plan (F12):** una suite de documentos práctica, en la línea de ONLYOFFICE, con once filas; la última, editar en el navegador, queda a su decisión.

### Añadido — el lateral en modo de iconos solos

- El botón de la barra ya no oculta el lateral: lo **reduce a una columna de iconos** (4,25 rem) y lo vuelve a ampliar, como el lateral colapsado de AeroControl. Se acuerda en este navegador; una elección guardada con la versión anterior («oculto») se respeta como reducido.
- Reducido, cada enlace lleva su `title` y su palabra sigue en el HTML para el lector de pantalla (recorte, no `display: none`); los grupos, que no caben en una columna de iconos, se sustituyen por un enlace «Todas las herramientas» al catálogo. En pantallas estrechas no cambia nada: el lateral sigue saliendo entero encima del contenido.

### Cambiado — la navegación al estilo de AeroControl: un lateral fijo

- **Un lateral a la izquierda** en todas las pantallas con sesión, como en AeroControl, para que las dos aplicaciones se naveguen igual: Inicio, Convertir e Historial arriba; los cuatro grupos de herramientas como grupos plegables (recuerdan en este navegador cuáles se dejaron abiertos), y debajo Compatibilidad, Preajustes y Tino.
- **La barra se queda corta**: el botón para mostrar u ocultar el lateral, la marca, el modo, y a la derecha el tema, las cuentas y salir. Desaparece el desplegable «Herramientas» de tres columnas y, con él, menu.js.
- **Sin JavaScript sigue funcionando**: los grupos son details; lateral.js solo oculta y muestra (y lo recuerda en pantallas anchas). En móvil nace plegado y el botón de la barra lo saca; Escape y seguir un enlace lo cierran.
- La portada pierde su panel propio —el lateral ya hace de índice— y «Seguir donde lo dejaste» vuelve a su sitio sobre el catálogo. Iconos nuevos de casa y de menú. A 900 px la pantalla de Compatibilidad ya no desborda la página.

### Corregido — una hoja vacía dejaba las filas viejas del catálogo

- **Hallazgo de las pruebas nuevas de cobertura:** en «Excel a catálogo», una hoja de Excel **sin ninguna celda** se saltaba antes de vaciar su tabla, así que la tabla conservaba en silencio las filas de la plantilla: dos catálogos mezclados en uno. Ahora la tabla se vacía y se avisa («la hoja venía vacía»).
- **Cobertura de la cola, medida y subida:** catalogos.py 50 % a 100 %, 	area.py 49 % a 89 % y el despachador con pruebas de su bucle, su arranque y su parada. catalogos se prueba con un ODBC falso que guarda las tablas en un archivo: prueba la lógica de nuestro código, **no** que Access acepte lo escrito (eso sigue en la estación de trabajo).

### Corregido — el panel lateral de la portada

- El panel tenía una barra de desplazamiento propia que cortaba «Seguir donde lo dejaste»: ya no la tiene (solo la lista de lo reciente se acota, a 22 rem).
- El botón «Convertir un archivo» queda centrado y con la altura de los demás controles.
- El saludo usa el nombre de pila y, si no lo hay, se omite: «Hola, aeroconvert» saludaba al usuario de la cuenta, que no es un nombre.

### Cambiado — la portada con panel lateral y saludo

- **Un panel a la izquierda** (desde 56 rem; en pantallas estrechas pasa encima): el botón «Convertir un archivo», el **índice de grupos** con su recuento —cada enlace abre el grupo y salta a él— y «Seguir donde lo dejaste» en una columna. El catálogo ocupa el resto.
- **Saludo** («Hola, carla.») bajo el título, y la tira «Cómo funciona esto» de la primera vez pasa a la columna del catálogo, junto al panel y no debajo.
- Buscando, el índice solo trae los grupos con resultados. 375 px sin desborde.

### Corregido — un VRT disfrazado de .asc o .tif (B-04)

- **Medido en p340 (GDAL 3.12.2, 2026-10-06):** gdalinfo falso.asc con un VRT dentro responde Driver: VRT y nombra el archivo fuente; la inspección lo daba por «Arc/Info ASCII Grid». GDAL elige el controlador por el contenido, y un VRT apunta a otros archivos del disco.
- inspeccionar ya no reconoce un VRT con otra extensión (avisa y lo deja como desconocido), y el motor ráster abre un .asc con -if AAIGrid. Comprobado con el gdal_translate de QGIS 4.0.2: sin -if abre el VRT; con -if, lo rechaza.

### Cambiado — iconos que dicen lo que hacen (F9.4)

- Los datos de un receptor GNSS dejan la diana genérica por un **satélite**; «PDF a Markdown» y
  «Página web a Markdown» dejan el icono compartido de «renglones» por una hoja y un globo, cada
  uno con su flecha de salida. `test_iconos.py` falla si el código nombra un icono que el sprite
  no tiene.

### Cambiado — tipografía y radios desde la escala (F9.4)

- Los 14 tamaños de letra escritos a mano ( .82rem,  .9rem, 1.02rem, 11px…) y los radios 3px, 4px, 6px y 999px pasan a --av-fs-* y --av-radius-* (nuevo --av-radius-xs). Los textos se acercan al peldaño más próximo, así que alguno cambia una fracción de rem.
- 	est_escala_visual.py falla si vuelve a aparecer un tamaño de letra o un radio fuera de la escala.
### Cambiado — la paleta en OKLCH, sin cambiar lo que se ve (F9.5)

- Los 95 tokens de color de `static/css/app.css` (claro, oscuro y oscuro del sistema) pasan de
  `#rrggbb` a `oklch(L C H)`. Una variante nueva de una familia es ahora tocar la luminosidad, no
  adivinar tres canales.
- **Nada cambia a la vista:** el navegador pinta el mismo byte en los 95 (oráculo de canvas,
  `docs/PRUEBAS_CON_ORACULO.md`). `apps/core/oklch.py` convierte en los dos sentidos; las pruebas de
  contraste WCAG siguen midiendo sobre sRGB, y `test_oklch.py` guarda la paleta anterior como foto.

### Corregido — pruebas que dependían del orden de ejecución

- **Causa encontrada:** `apps/raster/test_lectura_propietaria.py` sembraba solo los motores
  raster y terminaba con `registry.limpiar()`, dejando el registro **vacío** para toda prueba
  posterior. Una de GNSS y 21 del dashboard fallaban así, pero solo en un orden distinto del del
  CI: verde donde se mira y rojo donde no.
- **Arreglo de raíz:** una fixture automática en `conftest.py` guarda el registro antes de cada
  prueba y lo devuelve como estaba. Una prueba nueva (`test_aislamiento_del_registro.py`) vacía el
  registro a propósito y comprueba que la siguiente lo encuentra intacto; falla sin la fixture.

### Cambiado — los destinos de la pantalla de convertir, como tarjetas (F7.2c)

- Cada destino lleva ahora la **baldosa** con el icono de su perfil —el mismo de la portada y del
  menú—, su nombre, **«Sale: GeoTIFF clásico»** y la estimación de tamaño y tiempo. Un destino
  apagado conserva la baldosa y su motivo, y no promete un «Sale:».
- **Corregido: marco blanco en relieve.** Los botones de destino salían con el borde `2px outset`
  que el navegador pone a cualquier `<button>`, porque la regla nunca lo quitaba; se veía en el
  tema oscuro. Ahora el marco es solo el anillo de la sombra, y el apagado lleva su guion de 1 px.

### Añadido — saber si algo mejoró: incidentes y resumen de uso (F9.6)

- **Nuevo modelo `Incidente`** (con migración `core/0003`, que `desplegar.sh` aplica sola). Cada
  500 del servidor deja una fila, y el navegador avisa de los fallos de htmx por `POST /incidentes/`
  (con sesión y con el token de CSRF). Guarda dónde, el código y la **clase** de la excepción:
  nunca el mensaje, ni nombres de archivo, ni la consulta de la dirección. Tope de 500 por hora.
- **`manage.py resumen_de_uso [--dias N]`:** trabajos, tasa de éxito, destinos y orígenes más
  vistos, motivos de fallo, rutas con más incidentes. Es lo que permite comparar un periodo con
  otro después de un cambio: hasta ahora el servidor decía «0 trabajos» sin distinguir «nadie lo
  usa» de «se usa y falla».
- Los incidentes se ven (sin editarlos) en el panel de administración.

### Retirado — el modelo `Resultado` y la vista `documents:descargar` (cabo de F9.2)

- Desde la fase 9 todas las herramientas de documentos pasan por la cola y se bajan por la ficha
  del trabajo. El modelo viejo y su vista se mantuvieron hasta que caducaran las últimas filas (72
  horas desde el 25 de septiembre) y hoy ya no queda ninguna. **Lleva una migración**
  (`core/0002_retirar_resultado`, borra una tabla): `desplegar.sh` la aplica sola. También se
  van su panel de administración, el conteo «enlaces de descarga» del barrido y `anotar_resultado`.

### Corregido — un anónimo ya no puede hacer que el servidor reciba 2 GB (A-01 de la auditoría)

- **Nuevo `LimiteDeCuerpoMiddleware`**, antes de que el CSRF lea el cuerpo. Sin sesión, un POST de
  más de 1 MiB recibe **413 sin leerse** (`LIMITE_DE_CUERPO_ANONIMO_BYTES`); con sesión, más de
  `TOPE_MB` más 10 MiB de margen. Decide solo con `Content-Length`. Antes, el CSRF analizaba el
  cuerpo entero y el manejador lo escribía hasta el tope, contra cualquier ruta con POST y varias
  a la vez, antes del login.
- **nginx (opcional, no desplegado):** 1 MB para todo el sitio y 2.100 MB solo en `/subir/` y
  `/documentos/`.

### Corregido — la cola y los procesos (B-07 y B-08 de la auditoría de seguridad)

- **Cancelar o agotar el plazo ya mata a todo el árbol de procesos**, no solo al hijo directo.
  ODA, Wine, `Xvfb`, Word, Excel y PowerPoint lanzan nietos que seguían vivos con el archivo
  bloqueado y la memoria ocupada. Cada motor arranca como cabeza de su propio grupo (en Windows,
  `taskkill /T`), y los pasos posteriores, como `gdaladdo`, también.
- **Un trabajo vivo ya no se marca «interrumpido».** El PID guardado era el del motor y no el del
  obrero: al terminar el motor, un paso posterior largo parecía un trabajo muerto, y «reintentar»
  habría dejado dos procesos escribiendo el mismo parcial. Ahora se conserva el del obrero.

### Cambiado — la portada deja de ser una pared (F9.4)

- **Cada grupo de herramientas se pliega, y solo el primero nace abierto.** Eran veintiséis
  tarjetas con descripción y «Sale:» a la vez (unos 2.000 px); ahora la portada mide unos 1.010 px
  con un grupo abierto. Cada grupo muestra cuántas herramientas trae. Es un `<details>` nativo,
  con teclado y táctil; `plegable.js` recuerda en el navegador lo que cada persona abrió o cerró.
- **Buscando, todo abierto y sin recordar nada:** lo que se encontró no queda tras un grupo
  cerrado.
- **Tarjetas más compactas:** menos aire, más columnas, descripción a dos líneas como mucho y sin
  la raya sobre «Sale:». El texto entero de cada herramienta sigue en su propia pantalla.
- **La línea bajo el título** pasa de dos renglones a uno («Escriba lo que necesita conseguir, o
  abra un grupo»): los ejemplos ya están en el campo y en las etiquetas.
- `plegable.js` guarda ahora los dos estados, abierto y cerrado, porque unos bloques nacen abiertos
  y otros cerrados.

### Añadido — cuota de subidas por persona (A-05 de la auditoría de seguridad)

- Cada persona puede tener subidos a la vez hasta **8.192 MB** (`AEROCONVERT_CUOTA_DE_SUBIDAS_MB`,
  0 la apaga), sin usar o en un trabajo en curso. El tope de 2.048 MB es por archivo y no impedía
  subir veinte seguidos. Se rechaza **antes de escribir**, con un mensaje que dice cuánto hay y
  qué hacer (la carpeta compartida). Borrar una subida libera cuota.

### Cambiado — el menú «Herramientas», el límite de subida y las rejillas, a 375 px (F9.4)

- **El panel «Herramientas» ya no se sale de la pantalla.** Colgaba de la izquierda del botón,
  que está hacia la derecha de la barra: en una ventana de 1.874 px se cortaba «Reconocer el
  texto» y aparecía una barra de desplazamiento. Ahora cuelga de la barra entera, pegado a su
  borde derecho (medido a 1.440, 900 y 375 px).
- **Las columnas del panel salen parejas.** Cuatro grupos de 6, 1, 7 y 8 entradas caían en tres
  columnas desiguales y una bajo la primera; ahora el navegador los reparte (7, 10 y 9 en esta
  máquina, que tiene Office; 7, 8 y 7 en el servidor) y un grupo nuevo se acomoda solo.
- **En teléfono el menú abre justo debajo de la barra**; antes su `top` se calculaba contra la
  ventana entera.
- **El límite de subida se ve, sin gritar:** una etiqueta pequeña de contorno fino, «Límite por
  archivo: **2048 MB**», con solo la cifra en negrita, en las cinco pantallas que suben archivos.
- **`/convertir/` y `/motores/` dejan de desbordar a 375 px.** Sus rejillas pedían columnas de
  24 y 26 rem (384 y 416 px) con 351 útiles; ahora `min(…, 100%)`.

### Cambiado — el resultado de una conversión y la barra, a 375 px (primera pieza de F9.4)

- **Una sola acción principal por estado** en el resultado de una conversión: antes salían dos
  botones «Descargar»; en un error, «Reintentar» es el principal y las alternativas pasan a
  secundarias; un trabajo cancelado ofrece «Volver a encolar». El recibo cabe en una columna
  en pantalla estrecha, y motor, huella y piezas del zip van en un «Datos técnicos» plegable.
  La pantalla mide 1.728 px de alto a 375 px, frente a los 2.456 de antes. Los 10 estilos en
  línea de la plantilla pasaron a clases.
- **La página entera ya no se desplaza de lado en un teléfono.** A 375 px la marca, la chapa y
  la navegación sumaban 615 px; ahora la navegación pasa a su propia fila (solo hasta 480 px).
  Medido en el navegador: portada, historial, documentos y resultado en 375 px exactos.
- «Listo, ya puede descargarlo»: el trato de usted que pide `AGENTS.md`.

### Cambiado — `apps/documents/views.py` pasa a ser un paquete

- Las 1.436 líneas de `views.py` se reparten en `views/`: un módulo por pantalla
  (`pantalla_unir`, `pantalla_dividir`...) más `_comun`, y `__init__.py` reexporta los mismos
  nombres. **No cambia el comportamiento**: el mapa de URL es idéntico antes y después, y el
  cuerpo de ninguna función se tocó (el corte fue mecánico).

### Añadido — «Seguir donde lo dejaste» se puede plegar

- La franja de la portada es ahora un `<details>` nativo: se pliega y se abre con el ratón, el
  teclado (Enter y espacio) o el dedo, sin JavaScript. Abre por omisión. `static/js/plegable.js`
  recuerda en el navegador si se dejó cerrado. El chevron gira: la forma cambia, no solo el color.

## [0.10.0] — 2026-10-05

Primera versión desde la 0.1.0: reúne las fases 1 a 10. La numeración antigua del README
(`v0.3.0-alpha`) quedó atrás de lo que ya está desplegado y se retira.

### Añadido — un RINEX que ya existe se pasa a otra versión (fase 10.8)

- Nuevo origen `rinex_obs`: un RINEX de observación (`.rnx`, `.obs`, `.23o`, `.24o`…) se
  reescribe en 2.11, 3.03, 3.04 o 3.05 con `convbin -r rinex`, y el recibo trae su calidad. La
  extensión no basta: se abre la cabecera y, si no es un RINEX de observación, el archivo queda
  como desconocido con el motivo. La navegación (`.23n`) no se convierte sola.
- Medido a mano con el `convbin` de Trimble Business Center: RINEX 3.04 del T02 a 2.11, 3.600
  épocas (ver `docs/PRUEBAS_CON_ORACULO.md`, sección 6).

### Añadido — calidad de un RINEX, al estilo de lo que se pedía de TEQC (fase 10.7)

- El recibo de toda conversión GNSS trae ahora la **calidad**: satélites por época (mínimo,
  media, máximo), cuántos distintos hubo, qué porcentaje de las observaciones posibles está
  presente por constelación (RINEX 3) y los satélites que aparecen en menos del 90 % de las
  épocas, nombrados. Código propio en `apps/formats/rinex_calidad.py`, en una pasada y con
  memoria acotada. TEQC no se usa: murió en 2019 y no es de código abierto.
- **Lo que no mide**, y el recibo lo dice: multitrayecto, saltos de ciclo, elevación y acimut.
- Medido sobre el RINEX del T02 (3.600 épocas): la suma de épocas de los satélites GPS (25.635)
  coincide con un recuento independiente de las líneas `G` del cuerpo.

### Añadido — RTKLIB como segundo motor GNSS (fase 10.6)

- **Siete formatos de receptor más, a RINEX, con RTKLIB `convbin`** (BSD-2, nativo, sin
  Wine): RT17 de Trimble, u-blox UBX, Septentrio SBF, NovAtel, RTCM 3, BINEX y Javad GREIS. Se
  reconocen por la extensión —no tienen firma de archivo que sirva— y lo que decide si sirvió
  es lo que sale: el mismo verificador que el motor de Trimble abre el RINEX y cuenta épocas.
- Sonda `sondar_rtklib()` con su motivo `sin-rtklib`; variable `AEROCONVERT_RTKLIB_CONVBIN`.
  Apagado, el botón se queda con su motivo.
- Medido con el `convbin` que trae Trimble Business Center, sobre un RINEX real (la ruta de
  flujos reales no se pudo medir: no hay uno en la máquina): ver `docs/PRUEBAS_CON_ORACULO.md`.

### Añadido — datos GNSS: del receptor Trimble a RINEX (fase 10)

- **Un T01, T02 o T04 de Trimble se convierte a RINEX** con el convertidor oficial, y se
  entrega en un zip con las observaciones y la navegación. La ficha reconoce el archivo por su
  contenido y dice de qué receptor viene (`TRIMBLE NETR9, serie …`) sin convertir nada.
- **No se fía del convertidor, y con razón.** Medido sobre un T02 de un NetR9 y un T04 de un
  R12i: sale con código 0 y escribe «Success» con un archivo vacío, con basura y con un T02
  **cortado por la mitad**, que entrega un RINEX válido más corto sin avisar. Un crudo cortado
  se detiene antes de convertir; y lo que sale se abre y se cuentan sus épocas (3.600 y 8.727,
  sin huecos, coherentes con la cabecera).
- **El recibo dice lo que se comprobó**: épocas, intervalo, de cuándo a cuándo, receptor,
  antena, constelaciones por nombre, archivos y avisos.
- **Una observación GNSS no pregunta por sistema de referencia**: son pseudodistancias, no
  coordenadas.
- **Si falta el convertidor, la ficha dice por qué**, a la vista, en vez de un remedio sin
  botón. Vale para cualquier destino que no se pueda ofrecer.
- **Es un programa de Windows con licencia de Trimble y no se distribuye**: se sondea. En Linux
  corre bajo Wine, que **todavía no se ha probado en el servidor**.

### Corregido — el CI llevaba rojo desde el 24 de septiembre

- **13 pruebas pasaban en la estación y fallaban en CI**, que no tiene GDAL ni servidor
  gráfico. La puerta local daba verde y nadie lo veía. Una fixture compartida finge GDAL, y se
  puede reproducir con `AEROCONVERT_GDAL_BIN= AEROCONVERT_PDAL_BIN= pytest`.
- Django 6.1.1, pypdf 6.19 y urllib3 2.8, por diez avisos nuevos de `pip-audit`.

### Cambiado — Tino, apagado y sin rastro

- **Tino ya no se ve en ninguna parte.** Su pantalla da 404 (no «no disponible», que confirmaría
  que hubo algo) y se quitaron los dos enlaces que llevaban a ella: el del pie del menú y el de
  una búsqueda sin resultados. No se borró código: `AEROCONVERT_TINO_VISIBLE=true` lo vuelve a
  encender. Decisión del 2026-10-05: de momento el equipo no lo necesita.

### Añadido — coordenadas locales para nubes de puntos

- **Una nube de escáner sin GNSS ya se puede convertir.** Está en el sistema de la estación,
  con el origen en 0, y pedirle un EPSG obligaba a inventarlo, que es justo lo que la regla del
  proyecto prohíbe. Ahora la ficha ofrece una casilla «Son coordenadas locales», **desmarcada
  por omisión**, solo para nubes, excluyente con el campo de EPSG, y anotada en la bitácora con
  el nombre de quien la marcó. Lo que sigue prohibido es **reproyectarlas**: pasar de local a
  UTM es georreferenciar, y sin puntos de control no hay de dónde partir.

### Corregido — contraste y foco, medidos (fase 9.3, 2026-09-25)

Siete pares estaban por debajo de WCAG 2.1 AA y ninguna prueba los miraba.

- **El foco de teclado no se veía en la barra**: 1,97:1 sobre el navy. Ahora es magenta, 4,5.
- **Enfocar un campo solo cambiaba el color del borde**, a 2,09:1 del anterior. Ahora lleva
  el anillo de 2 px del resto de la aplicación.
- **Los enlaces usaban el azul de Bootstrap**, a 3,39:1 en oscuro. Ahora tienen su token.
- **El rojo sobre su fondo, las píldoras de «hecho», «error» y «cancelado», y el texto
  atenuado sobre el fondo del menú** estaban entre 4,19 y 4,35. Los tonos bajan lo justo
  para pasar de 4,5 con margen.
- **El borde del buscador de la barra** daba 2,02 y no se veía como caja. Ahora pasa de 3.
- **Las migas del explorador, los ejemplos del buscador y el botón pequeño** medían entre 20
  y 22 px de alto; ahora al menos 24 (WCAG 2.5.8).
- **La página de error 500** llevaba un tema oscuro desviado de la paleta, y la cabecera del
  CSS prometía 8,9:1 donde se miden 8,3. Los dos se comprueban ahora.

### Cambiado — las veinte herramientas de documentos, por la cola (fase 9.2, 2026-09-25)

Hasta ahora corrían dentro de la petición. Ahora la pantalla mira y comprueba, y la acción
final crea un trabajo: la ficha trae progreso, recibo, descarga con dueño, reintentar,
cancelar e historial, como cualquier conversión.

- **Trece de las veinte no dejaban descargar lo que salía de un archivo subido.** Ahora todas
  se descargan desde la ficha del trabajo, y ninguna escribe ya dentro de la carpeta de
  subidas.
- **El reconocimiento de texto moría a los 120 s** que gunicorn da a una petición. En la cola
  va por el carril pesado con 60 s por página, progreso página a página, y el tope sube de
  100 a 500 páginas. La pantalla estima cuánto tardará antes de pulsar.
- **Dos carriles** en el mismo obrero: un «numerar» de un segundo ya no espera detrás de una
  ortofoto de tres horas.
- **Varias salidas, en un zip**: Dividir y PDF a imágenes. Una sola pieza sale suelta.
- **Terminar bien sin archivo** tiene su propio desenlace, ni verde ni rojo: comprimir un PDF
  que ya venía comprimido, o sacar texto de un escaneo que no lo tiene.
- **La contraseña de Proteger no toca la base, el argv ni el encargo.** Viaja cifrada a un
  archivo del trabajo que el obrero lee y borra en un paso, caduca a la hora, y reintentar
  vuelve a pedirla. El resultado se verifica con PDFium: sin la clave no abre, y es AES-256.
- **Lo que sale se verifica con otro lector que el que lo escribió**: PDFium para los PDF y
  cada pieza de un zip, la estructura del zip para `.docx` y `.xlsx`, la firma para `.mdb`.

### Corregido — fase 9.2

- **El formulario de Proteger no llevaba `enctype` multipart**: en un navegador de verdad la
  subida nunca llegaba. Las pruebas no lo veían porque el cliente de Django siempre manda
  multipart; ahora hay una que mira la plantilla.
- **«Sin tocar las imágenes» comprimía a 200 ppp**: el formulario convertía el 0 en el valor
  por omisión.
- **Dividir con un trozo repetido** pisaba el primero sin avisar.
- **El recibo enseñaba la ruta del servidor** para lo que salía de una subida, y un
  porcentaje con dos signos («−-5 %») cuando la salida pesaba más que el original.

### Corregido — lo que impedía terminar una conversión (fase 9.1, 2026-09-25)

Ninguno de estos daba un error: la pantalla se quedaba quieta, o hacía otra cosa.

- **Arrastrar y soltar no hacía nada.** Escribía el nombre en un campo oculto y solo enviaba
  si llevaba una barra, que un nombre soltado nunca tiene. Ahora el archivo entra en el campo
  de subida y se sube; la zona es la tarjeta entera, y soltarlo fuera ya no abre el archivo
  en el navegador.
- **Ningún error de htmx se veía.** Una subida que fallaba se quedaba en «Mirando qué es…».
  Ahora se pinta el motivo con `role="alert"`, y el código técnico va plegado.
- **La ficha aparecía fuera de la pantalla**, sin foco ni aviso. Ahora se desplaza, se
  enfoca y se anuncia por una región `aria-live`, que antes no había en ninguna parte.
- **Un EPSG mal escrito devolvía la pantalla vacía** y hacía elegir el archivo otra vez.
  Ahora vuelve la ficha con el error junto al campo y lo escrito conservado.
- **Los mensajes de éxito salían en el ámbar de «cuidado».** Cada nivel lleva ahora su
  color, su icono y su palabra.
- **Textos que se contradecían**: «no se sube» junto a un botón de subir, «sin límite de
  tamaño» con un tope de 2.048 MB.

### Añadido — cerrar riesgos, arreglar los cimientos y crecer (fase 8, 2026-09-21 a 24)

- **Comprimir PDF**, que se niega cuando comprimir engordaría el archivo. Medido sobre un
  escaneo real: 7,2 MB → 1,19 MB.
- **Reconocer el texto de un escaneo** con Tesseract, sondeado y no declarado. Verificado en el
  servidor sobre un escaneo real (`ACTA DE RECEPCION`, sin erratas).
- **DWG y DGN v8** por el ODA File Converter, con `xvfb-run` en Linux. Sin verificar de extremo
  a extremo: el conversor no está en ninguna máquina.
- **«Seguir donde lo dejaste»** en la portada, por destino y no por archivo, y los atajos `/` y
  Escape, enseñados junto al campo.
- **Tino**, que contesta desde esta máquina con la matriz y los catálogos. La puerta hacia un
  modelo de fuera nace cerrada y sin proveedor elegido.
- **`respaldar --copiar-a`**, para la segunda copia fuera de la máquina, y
  **`scripts/revisar-servidor.sh`**, que pregunta los riesgos a la máquina en vez de leerlos.
- **Tres escalas de diseño** —espaciado, tipografía, elevación— y una prueba que impide
  declarar tokens sin usarlos.

### Corregido — fase 8

- **El respaldo automático nunca había escrito nada.** El servicio no pasaba `--carpeta` y
  caía en `/opt`, que `ProtectSystem=strict` deja en solo lectura; y la carpeta de destino no
  se creaba en ningún paso. Ahora la crea el despliegue y lo dice al terminar.
- **El buscador no reconocía un formato seguido de un signo** («¿tif a jp2?») y daba puntos
  gratis por «la», «de» y «un», así que las frases naturales empataban con todo.
- **`SERVIDOR.md` y el comprobador proponían una reserva DHCP en el router** para una dirección
  que es la NAT interna de Hyper-V y que ningún puesto de la oficina alcanza.
- **Bandit fallaba desde la entrada de Comprimir** y se dio el portón por verde sin volver a
  correrlo.
- **La cifra de herramientas estaba desfasada** en el README y en `SERVIDOR.md`. Ahora la
  comprueba `test_cuenta.py`.
- **Deuda verificada contra el código**: dos filas estaban pagadas desde hacía semanas; la de
  remuestreo es peor de lo que decía (se lee una opción que nadie puede poner).

### Añadido y corregido — para que lo use un equipo en una VM (fase F6)

Tres de estos **no son funcionalidad que faltara: son defectos**, y ninguno da un error. Solo
aparecen cuando hay más de una persona, que es por lo que llevaban ahí desde siempre.

- **Un usuario podía descargarse el archivo de otro.** La ruta de salida se construye de
  forma determinista, así que en una carpeta compartida dos personas que convirtieran cada
  una su `ortofoto.tif` con el mismo perfil producían **la misma ruta**: la segunda pisaba a
  la primera y la descarga servía lo que hubiera. La pregunta ahora no es «¿existe el
  archivo?» sino «¿lo reclama el trabajo de otro?» — pisar lo tuyo sigue permitido, porque
  reconvertir y encontrar el resultado donde estaba es lo que uno espera. Y la descarga
  comprueba además que el archivo siga teniendo el tamaño que produjo ese trabajo.
- **Un bloqueo de sesión dejaba fuera a todo el equipo**, porque detrás de nginx todos
  comparten la IP del proxy. Ahora es por la pareja usuario + IP.
- **Un error 500 no dejaba rastro en ninguna parte.** El manejador de consola de Django lleva
  `require_debug_true`, así que con `DEBUG=False` no escribía nada, y `django.request` iba a
  `mail_admins` sin `ADMINS` definido.
- **El tope de ruta eran 255 caracteres también en Linux**, donde el límite son 4096. Una
  carpeta de obra pasa de 255 sin esfuerzo, y el mensaje decía «mueve el archivo» sobre una
  carpeta compartida que nadie puede mover.
- **El despachador sale del proceso web** a su propia unidad de systemd. Con varios obreros de
  gunicorn arrancaban varios despachadores, y el tope de trabajos simultáneos se comprueba con
  un `count()` que no es atómico.
- **El techo de memoria de las nubes de puntos, dicho antes de empezar.** PDAL carga los
  puntos en memoria: la regla medida son 105 MB por millón, así que una nube de mil millones
  pide unos 100 GB. Sin comprobarlo, el sistema mata el proceso y en un servidor se lleva lo
  que el núcleo decida.
- **`/salud/` deja de decir «ok» sin mirar nada.** Ahora mira la base, el obrero, el disco, el
  manifiesto de estáticos y —la que de verdad va a fallar— **si la carpeta compartida sigue
  montada**: un CIFS caído deja un directorio vacío en su sitio y la aplicación empieza a
  decir «ya no hay ningún archivo en …» sobre rutas que la persona tiene delante.
- **Panel de administración**, que no existía: quien administra no veía ni un trabajo. El
  recibo es de solo lectura entero; lo que se puede hacer son acciones.
- **`manage.py respaldar`**, que tampoco existía, y no es un `cp`: con WAL, copiar el fichero
  entrega la foto del último punto de control y le faltan las últimas horas sin decirlo. Usa
  la API de respaldo en línea de SQLite y **verifica la copia abriéndola**.
- **La infraestructura** en `despliegue/`: gunicorn, systemd, nginx, `desplegar.sh` y el
  manual de instalación y operación.
- **`manage.py check` se niega en modo nube**, que es el de las subidas y no está escrito, y
  avisa de una raíz demasiado ancha **cuando la máquina es compartida** — en una estación de
  trabajo, dar el disco entero es exactamente lo que se quiere.
- **Páginas de error propias**, que no había: con `DEBUG=False` salían las de texto plano de
  Django. La del 500 va **suelta**, sin extender la base y sin `{% static %}`, porque Django
  la renderiza sin `request` y porque la causa número uno de un 500 en todas las páginas es
  justamente un manifiesto de estáticos ausente — la página que anuncia el fallo no puede
  depender de lo que suele fallar. Y cada una habla de lo que va a pasar de verdad: la del
  400 nombra `ALLOWED_HOSTS`, que es el 400 de todo despliegue nuevo.
- **La descarga de una salida que ya no está pasa a 410, con su propia página.** Un 404 dice
  «esto nunca existió»; aquí existió, se verificó y desapareció por una razón que se sabe
  nombrar — barrida por retención, movida por alguien, o **reemplazada**, y entonces no se
  entrega porque sería dar otra cosa diciendo que es esta. La página enseña **el recibo
  entero** y ofrece rehacerla en un clic. Eso es lo que significa que el recibo sobreviva al
  archivo.
- **Subir archivos desde el equipo**, para lo pequeño. Los planos y las nubes siguen llegando
  por la carpeta compartida —reanudable y sin pasar por HTTP—, pero obligar a montar una
  unidad de red para juntar dos PDF del escritorio es fricción sin motivo. Las dos vías
  conviven en el mismo campo, y **cuál es cuál lo dice un prefijo, no una adivinanza**.
- **Y la pantalla de unir sigue sin estado en el servidor.** Un `<input type="file">` rompía
  esa invariante, porque el navegador no reenvía los bytes al pulsar «bajar». Lo que la
  arregla es que en la lista viajen identificadores en vez de rutas: `receta.py` —el módulo
  cuyo docstring entero trata de la ausencia de estado— **no ha tenido que cambiar ni una
  línea**.
- **El tope de tamaño ahora vale de verdad**, en tres sitios y solo uno inevadible.
  `DATA_UPLOAD_MAX_MEMORY_SIZE` no servía: limita los datos del formulario que *no* son
  archivos, así que un cuerpo de veinte gigabytes se escribía entero en el temporal del
  sistema antes de que nadie lo rechazara. Y baja de 2048 MB a **200**: lo grande no sube.
- **Descarga de los resultados**, que hacía falta **aunque haya carpeta compartida**: el
  navegador está en el equipo de la persona y el recurso está montado en la VM, así que la
  ruta que se enseñaba era la del servidor y como texto no servía para nada. Va por
  identificador y **nunca por ruta**: una vista con `?ruta=` convertiría una herramienta que
  escribe en lectura de todo el recurso compartido, por GET y sin testigo.
- **`check --deploy` miraba el módulo equivocado.** `verify.ps1` lo corría sin fijar
  `DJANGO_SETTINGS_MODULE`, así que caía en `dev` con `DEBUG=True` y no comprobaba nada.
  Corregido, y añadido al CI junto con `collectstatic`.

### Añadido — herramientas de PDF (fase F5)

Una familia nueva, y la razón de que exista está escrita en la propia pantalla: las páginas
que hacen esto en internet **suben tu archivo a su servidor**, y con un plano bajo acuerdo de
confidencialidad eso no es una molestia, es lo que no se puede hacer. Aquí todo pasa en el
equipo, el original nunca se toca, y la salida se escribe en un parcial que solo se pone en
su sitio cuando ya salió bien — las mismas tres promesas que el resto de la aplicación.

- **Leer un PDF sin abrirlo entero**: cuántas páginas, qué tamaño tiene cada una en
  milímetros, su formato normalizado (A4, A1…) y si está vertical o apaisada. La orientación
  tiene en cuenta el `/Rotate`, que es lo que la mayoría de las herramientas ignoran: una
  lámina con caja 594 × 841 y giro 270 **se ve apaisada**, aunque su caja diga lo contrario.
- **Unir PDF eligiendo qué páginas entran, en qué orden y cuáles van giradas.** Con
  miniaturas de verdad, porque ordenar cincuenta y seis filas de texto no es ordenar: hay que
  ver las hojas. El giro es **relativo y sin pérdida** — se suma al que la página ya traía y
  no se redibuja nada.
- **Sin estado en el servidor**: la receta de la composición viaja en un campo oculto del
  propio formulario. No hay sesión que caducar ni fila que limpiar, y dos personas pueden
  componer a la vez sin pisarse.
- **Miniaturas con caché del navegador, no nuestra.** Llevan un `ETag` que depende del
  archivo, la página, el giro y el ancho, así que al pulsar «bajar» las cincuenta y seis
  vuelven con un 304. Guardarlas en disco traería una carpeta que crece, que hay que barrer y
  que se queda obsoleta cuando el archivo cambia.
- **Dividir**, por rangos escritos como se dicen —`1-5, 8, 12-14`, con los dos extremos
  dentro— o en hojas sueltas. Lo que no se puede interpretar no se adivina: se dice **cuál**
  de los cinco falla, porque «rangos no válidos» obliga a mirarlos a ojo.
- **Imágenes a PDF** para monografías y anexos de fotos, en A4 —cada hoja toma la orientación
  de su foto— o al tamaño de la imagen, que es lo que se quiere de un escaneo y no remuestrea
  nada.
- **PDF a imágenes** (JPG o PNG) para meter una lámina donde un PDF no se pega. La decisión
  no es el formato sino la resolución, así que **no hay campo libre de ppp**: tres opciones
  con para qué sirve cada una, y un tope de 12.000 píxeles de lado comprobado *antes* de
  dibujar, porque un A1 a 300 ppp son casi 10.000 y varios cientos de megas de memoria.
- **Numerar las páginas**, distinguiendo dos cosas que se piden juntas y no son la misma:
  **desde qué hoja** se numera —una portada no lleva número— y **con qué número se empieza**
  —un anexo que continúa otro documento—. Y «de 56» es el último número que de verdad aparece
  impreso, no el de hojas del archivo.
- **Marca de agua** —«BORRADOR», «NO VÁLIDO PARA CONSTRUCCIÓN»— **encima** del contenido, que
  es donde tiene que ir: una marca que el dibujo del plano tapa no marca nada. Su intensidad
  son tres valores medidos y no un control deslizante, porque al 100 % tapa las cotas. El
  ángulo es el de la diagonal de la hoja y no 45° fijos, que en un A1 apaisado dejarían el
  texto cruzando por una esquina.
- **La capa se dibuja por página y en el sistema de coordenadas de lo que se ve.** Una entrega
  real mezcla A4 de memoria con A1 de planos, y una lámina con giro declarado pondría el
  número **de canto en el borde equivocado** si la capa se colocara en el espacio de la caja.
  Es un fallo que no da ningún error: el archivo abre, imprime, y está mal. Verificado sobre
  una lámina escaneada de verdad —caja 593 × 764 pt vertical, giro 270, que se ve apaisada— y
  sobre un documento de 59 páginas de tamaños mezclados.
- **Proteger y desproteger**, y **solo con AES-256**. pypdf sabe cifrar de tres maneras y dos
  de ellas —RC4 de 40 y de 128 bits— están rotas desde hace veinte años. Un PDF «protegido»
  así es **peor** que uno sin proteger, porque quien lo manda cree que va cerrado. La
  contraseña no se registra, no vuelve en la respuesta —ni cuando el intento falla, con
  prueba de centinela— y no viaja en la URL; y el aviso de que no se recupera está en la
  pantalla donde se decide, no en el recibo.
- **Word, Excel y PowerPoint a PDF**, con el Office instalado en el equipo. Es a propósito y
  no por comodidad: cualquier conversor propio reescribe el documento con sus propias
  métricas y su propio motor de saltos, y entrega algo plausible y distinto. **Un anexo de
  contrato que «se parece» al original no sirve.** Comprobado contra el PDF que alguien
  exportó desde Word a mano sobre el mismo documento: mismas páginas, mismo formato, y el
  texto idéntico salvo un espacio que el extractor infiere distinto.
- **Sin ninguna dependencia nueva, y siempre en un proceso hijo.** El trabajo lo hace
  PowerShell, que ya habla COM. Eso da de regalo lo que más importa: Word se cuelga de verdad
  —una macro, un vínculo a una plantilla que ya no está— y dentro de Django se llevaría el
  servidor por delante. Aquí se mata al hijo a los cinco minutos y se dice qué pasó.
- **Y para Excel, encajar cada hoja a lo ancho de una página**, porque una hoja de cálculo no
  tiene tamaño de papel. Medido sobre un libro real: **68 páginas sin ajustar, 6 ajustado**.
  Esa cifra está escrita en la propia pantalla, junto a la casilla.
- **Y PDF a Word**, el camino de vuelta, que también lo hace Word: abre el PDF y reconstruye
  párrafos y tablas a partir de las posiciones de las letras. **Con la cifra medida en la
  pantalla**: ida y vuelta sobre una minuta real, se conserva el 97,7 % de las palabras y las
  6 páginas se convierten en 8. Sirve para reaprovechar el texto, no para reemplazar al
  original, y eso se dice antes de convertir y siempre.
- **Un PDF escaneado se detecta y no se ofrece convertirlo.** No tiene texto dentro: son
  fotos. Word lo «convierte» igual —medio mega de imágenes pegadas y código de salida cero—,
  así que se mira antes y se manda a «PDF a imágenes», que hace eso mismo mejor.
- **Sin Office, la herramienta sale apagada y con el motivo**, nunca oculta — la misma regla
  que con ECW en la matriz de motores. Y en modo nube no existe, porque en un servidor no hay
  Office.
- **Una entrada en la barra, no seis.** La barra es de secciones, y las de PDF son varias
  cosas dentro de una. Hay un índice con una tarjeta por herramienta y lo que hace en una
  línea, porque «Dividir PDF» a secas no dice si parte por hojas o por rangos.

Todas las operaciones que escriben varios archivos son **todas o ninguna**: media entrega
repartida por la carpeta, con nombres correlativos que parecen correctos, es peor que un
error.

### Añadido — vectorial y libretas de puntos (fase F3, parcial)

- **Libretas de puntos topográficos PNEZD, PENZD, NEZ, ENZ y sus variantes**, a GPKG, SHP,
  GeoJSON, KML, KMZ y DXF. Sobre el archivo real de control del cruce minero de BHP: los
  cinco puntos en las cuatro salidas, con la extensión exacta del original —161,5 × 192,0 m—
  y verificados con `ogrinfo`.
- **El orden de columnas se deduce, no se adivina.** Es el fallo que este módulo existe para
  impedir: leer un PNEZD como PENZD no da ningún error, da un archivo que abre, dibuja, y
  tiene los puntos a miles de kilómetros. Se decide con una restricción del sistema de
  coordenadas y no con una heurística: **el este de una zona UTM va de 166.000 a 834.000 m**,
  así que un valor de 7.318.729 no cabe como este y solo puede ser norte. Cuando las dos
  columnas caben las dos —pasa en el hemisferio norte— **no se decide**: se marca ambiguo, se
  dibuja, y se pregunta diciendo la consecuencia («elegir mal deja los puntos a 9.650 km»).
- **Vista previa dibujada antes de convertir**, en SVG y sin pedir nada de fuera —la CSP es
  `'self'` y un mapa base serían teselas ajenas—. El norte va hacia arriba y la escala es la
  misma en los dos ejes, así que la forma que se ve es la del terreno; cada punto lleva sus
  coordenadas en un `<title>`, que es lo que lee un lector de pantalla.
- **Declarar el sistema de referencia a mano**, validado contra pyproj, sin valor por omisión
  y sin sugerir «el más probable». Queda anotado en la bitácora del trabajo con el nombre de
  quien lo declaró. Una libreta de puntos no lleva CRS dentro nunca, así que sin esto no
  había ninguna conversión posible.
- **Conversión vectorial general** entre SHP, GPKG, GeoJSON, KML, KMZ y DXF.
- **Salida a LandXML**, escrita por nosotros: OGR no trae controlador, ni de lectura ni de
  escritura. Es la forma en que Civil 3D importa puntos **de verdad** — un DXF entra como
  dibujo, con entidades sueltas, y un LandXML entra como grupo de puntos COGO con su número
  y su descripción. Se escribe en flujo, sin construir el árbol XML, porque una libreta de
  obra grande trae cientos de miles de puntos. **No tiene oráculo externo y no se finge que
  sí**: se comprueba que el XML esté bien formado y que traiga tantos `<CgPoint>` como
  puntos tenía la libreta; abrirlo en Civil 3D es un procedimiento manual, igual que ECW.
- **Los destinos ahora dependen de la familia del archivo.** Un perfil es «dónde tiene que
  abrir», no «a qué formato»: Civil 3D quiere un GeoTIFF si le llega una ortofoto y un
  LandXML si le llega una libreta. Antes, delante de un archivo vectorial, cuatro de los
  seis botones salían apagados diciendo «ningún motor sabe hacer esa conversión» — y el
  motor estaba, solo que el perfil pedía un ráster. Lo mismo con las nubes de puntos.
- `sondar_ogr()`, porque `ogrinfo --formats` y `gdalinfo --formats` listan cosas distintas.
- `puntos.iterar()`, que recorre la libreta entera sin materializarla. `leer()` guarda solo
  la muestra recortada para dibujar, y entregar ese recorte como si fuera el archivo sería
  el peor fallo posible del escritor.

### Corregido — el entregable

- **Un Shapefile son cinco archivos, y se entregaba uno.** Es el peor fallo que ha tenido el
  proyecto, porque entregaba algo inservible **con el recibo en verde**: la verificación corre
  sobre el parcial, cuando los hermanos todavía se llaman `salida.parcial.shx`, así que pasaba
  y anotaba «5 entidades, EPSG:32719»; después el renombrado movía solo el `.shp` y dejaba a
  los otros tres huérfanos. Comprobado sobre el archivo entregado: `ogrinfo` responde «Unable
  to open salida.shx» y no lo abre. Ahora se mueve el juego entero, y quién acompaña a quién
  lo dice el catálogo.

### Añadido — leer LandXML

- **La inspección dice qué trae dentro** un LandXML: puntos, superficies con sus vértices y
  caras, alineamientos con su longitud, el EPSG y hasta qué programa lo escribió. Contar
  `<Surface>` es inequívoco, así que se hace.
- **Los puntos se convierten** a GPKG, SHP, GeoJSON, KML, KMZ y DXF. En dos pasos, porque OGR
  no lee LandXML: un módulo nuestro los saca a un CSV intermedio y `ogr2ogr` hace el resto.
- **Las superficies y los alineamientos no se traducen todavía, y se dice.** No hay ningún
  LandXML real con el que contrastar un lector de triangulados —se buscó en la unidad entera—
  y una malla mal leída produce una superficie plausible y equivocada. Un archivo que solo
  traiga superficies lo explica en la ficha en vez de fallar de forma oscura.
- `defusedxml` pasa a ser dependencia declarada: el archivo lo escribió otro programa y lo
  mandó otra oficina, y `xml.etree` sigue siendo vulnerable a la expansión de entidades.

### Corregido — lo que se veía en pantalla

- **La interfaz salía en inglés.** La aplicación declara `LANGUAGE_CODE = "es"` y escribe los
  msgid en inglés, que es la convención de gettext, pero el catálogo español **nunca se
  creó**: no había carpeta `locale/` ni un solo `.po`. Sin catálogo Django cae al msgid, así
  que la píldora de un trabajo terminado decía `Done` y la etapa decía `Conversion`. También
  pasan por gettext los nombres **descriptivos** de formato —`Survey point file
  (PNEZD/PENZD)` era lo que leía quien soltaba una libreta—; los nombres propios como
  `GeoTIFF` o `Shapefile` se quedan como están.
- **Los veredictos decían que no abre lo que sí abre.** QGIS abre un PNEZD como texto
  delimitado y ArcGIS con «XY Table To Point»; lo que pasa es que los dos preguntan qué
  columna es la X y aceptan la respuesta equivocada sin decir nada. Eso no es «no abre», es
  «abre, y ahí está el problema».
- **Y remediaban con otra familia**: el veredicto de QGIS ante una libreta proponía
  «convertir a Cloud Optimized GeoTIFF» —un ráster, a partir de un archivo de texto— mientras
  el botón de al lado ofrecía GeoPackage.
- **Google Earth ahora dice sus tres condiciones** —KMZ, EPSG:4326 y teselar si la imagen es
  grande— en vez de solo la primera. Una ortofoto de 210 Mpx en una sola superposición se ve
  borrosa entera.
- **Un KMZ llevado a DXF salía en grados**, es decir un dibujo de dos milésimas de unidad que
  abre en Civil 3D sin enseñar nada, con el recibo en verde. Ahora se para antes de
  convertir, con motivo propio `crs-en-grados`, y se declara el sistema proyectado de
  destino. Verificado con el viaje de ida y vuelta: CSV → KML → DXF devuelve las coordenadas
  originales al milímetro.

### Corregido

- **El modo taller devolvía 500 en todas las páginas.** Corre con `DEBUG=False` y almacén con
  manifiesto, y `run.ps1` no ejecutaba `collectstatic`. Lo único que se llegaba a ver era la
  aplicación cayendo de vuelta a los ajustes de desarrollo, donde los estáticos van sin huella
  de contenido y sin `Cache-Control`: el navegador reutilizaba su copia y pintaba el HTML
  nuevo con la hoja de estilos vieja. El síntoma se leía como un error de diseño y no lo era.
- **`collectstatic` tampoco pasaba**: el manifiesto persigue los `sourceMappingURL` de los
  minificados vendorizados y aborta al no encontrar el `.map`. Se arregla en el almacén y no
  borrando el comentario, porque el hash SRI se calcula sobre los bytes exactos y editarlos
  haría que el navegador descartase la hoja entera.
- **El botón de convertir no convertía.** El formulario de la ficha enviaba a la vista que
  pinta la pantalla en vez de a la que encola, así que pulsar cualquier destino recargaba la
  página sin dar ningún error. Se colló al renombrar «Mesa» a «Convertir».
- **El techo de memoria de una nube crece con los puntos.** PDAL no respeta `GDAL_CACHEMAX`:
  medido, 966 MB de pico para 9.618.692 puntos, un 50 % por encima de lo que se anunciaba, y
  el error crecía con el tamaño de la nube.
- **`GDAL_DATA` no llegaba al proceso hijo**, y sin ella el controlador DXF no arranca: busca
  la plantilla `header.dxf`. La ruta no se puede deducir con una regla, así que se busca por
  archivo testigo.
- **`ESRI Shapefile` y `MapInfo File` no aparecían en la sonda.** Su nombre corto lleva un
  espacio y el patrón exigía que no lo llevara, así que SHP salía como no escribible.
- Un CRS declarado a mano no lo tenía en cuenta el runner, que exigía CRS incrustado.

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
