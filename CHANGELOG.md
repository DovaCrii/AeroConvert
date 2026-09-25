# Registro de cambios

Sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

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
