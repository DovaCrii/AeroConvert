# Cómo se escribe y cómo se arma una pantalla

Las decisiones de forma de AeroConvert. Están aquí porque se tomaron una por una, a lo largo de
varias tandas, y **aplicarlas pantalla a pantalla es exactamente como se pierden**: al auditar
las once de documentos aparecieron tres que seguían pidiendo una ruta escrita a mano, dos sin
tope de subida, y dos que filtraban por `.pdf` cuando lo que necesitaban era `.xlsx`.

Por eso cada regla de aquí dice **qué prueba la sostiene**. Un documento solo no impide nada:
la regla de las rutas ya estaba escrita cuando se saltaron tres pantallas.

---

## Cómo se escribe

### Mayúscula inicial solo en la primera palabra

«Marca de agua», no «Marca de Agua». «Sacar el contenido a Markdown», no «Sacar el Contenido a
Markdown». Vale para títulos, rótulos, botones y nombres de herramienta.

**Las excepciones son las de siempre, y son de verdad excepciones:**

- **Nombres propios y marcas**: Word, Excel, PowerPoint, Office, Markdown, QGIS, ArcGIS Pro,
  Civil 3D, AutoCAD, Google Earth, AeroBim, Tailscale, Windows.
- **Siglas y formatos**: PDF, DOCX, JPG, PNG, COG, GeoTIFF, LandXML, GeoPackage, COPC, EPUB…
- **La primera palabra de cada frase**, que es ortografía y no estilo: «Pone «3 / 56» en cada
  hoja. **S**in numerar la portada, si no quieres» es correcto.

> La vigila `apps/core/test_estilo.py`, que entiende las tres excepciones. Sin entenderlas
> daría cuarenta y ocho falsos positivos y acabaría desactivada, que es peor que no tenerla.

### Los títulos dicen qué hace la pantalla, no cómo se llama por dentro

«Compatibilidad», no «Motores». «Qué tiene dentro, y dónde va a abrir», no «Inspección». La
palabra correcta para quien programó casi nunca es la de quien llega con un archivo.

### Cada herramienta dice **qué entrega**

Es la pregunta de antes de pulsar y casi ninguna interfaz la contesta. «Dividir PDF» no dice si
salen varios archivos o uno con menos hojas; `sale: "uno o varios PDF"` sí.

### Lo que no se puede hacer se dice **una vez y en su sitio**

En el catálogo salen las herramientas apagadas con su motivo en una línea, porque esa pantalla
es el índice de todo. En el desplegable de la barra **no**, porque un menú es para ir a un
sitio y una entrada que no lleva a ninguna parte es un callejón. El párrafo entero vive en
Compatibilidad.

---

## Cómo se arma una pantalla que recibe un archivo

Cuatro reglas, y las cuatro salieron de un fallo real.

### 1. Nadie teclea una ruta

Dos vías y solo dos: **subir del propio equipo**, o **andar la carpeta compartida**. Nunca un
campo de texto con un ejemplo de `D:\obras\…`.

En el servidor, quien pega la ruta de su propio equipo recibe «esa ruta está fuera de las
carpetas permitidas» y no tiene forma de adivinar por qué: el archivo existe, lo está viendo en
su pantalla, y la aplicación dice que no. El campo puede seguir existiendo oculto —en «unir» y
en «imágenes» es donde el explorador acumula lo que se pincha— pero **pedirlo, no**.

### 2. Todo campo de archivo declara el tope

`data-tope-mb="{{ tope_mb }}"`, con el número que pone el servidor y nunca uno escrito a mano.

Sin esto el navegador manda el archivo entero y el servidor lo corta a mitad. Le pasó a una
ortofoto de 600 MB con el tope en 200: minutos de subida para recibir **«No llegó ningún
archivo»**, que además era falso — `StopUpload` descarta el cuerpo y la vista no podía
distinguirlo de no haber elegido nada.

### 3. Donde se sube, hay dónde pintar el avance

`<div data-avance-subida hidden>`. Lo rellena `static/js/subida.js` con porcentaje real —sale
de `htmx:xhr:progress`, son bytes entregados— y con el tiempo que falta **medido**, dividiendo
lo que queda entre la velocidad observada en esa misma subida.

Sin esto, un archivo grande deja la pantalla quieta durante minutos sin ninguna señal de que
siga viva.

### 4. Cada pantalla filtra por lo suyo

`accept` es un parámetro de `_origen.html`, con `.pdf` por omisión. Estaba fijo, y las dos
pantallas de Markdown lo heredaron: **el diálogo del sistema no dejaba elegir un `.xlsx`**. El
botón estaba, la pantalla estaba, y el archivo que hacía falta no se podía seleccionar. Se
reportó como «no funciona», que es exactamente lo que parecía.

> Las cuatro las vigila `apps/documents/test_criterio.py`, que recorre todas las pantallas.

---

## Cómo se arma una tarjeta

Icono con **color de familia**, nombre corto, una línea de qué hace, y «Sale: …». Las familias
y sus colores están en `app.css` como `--av-fam-*`, y hay que declararlas en **los tres**
bloques de tema — el claro, el de `[data-theme="dark"]` y el de `prefers-color-scheme`.

Olvidar el tercero no da error: hace que quien tiene el sistema en oscuro y no ha tocado el
interruptor herede los colores claros, o sea baldosas casi blancas sobre tarjetas oscuras. Pasó,
y duró meses.

Y **ningún color de familia se pinta con `#fff` fijo**. `.boton-icono` lo hacía porque nació
para la barra navy; cuando las filas de páginas de «unir» reutilizaron la clase dentro de una
tarjeta, en tema claro quedaron cuatro botones blancos sobre blanco: invisibles, pero ahí.

> `apps/core/test_paleta.py` calcula el contraste de cada pareja en los tres bloques.

---

## Lo que deliberadamente **no** es regla

- **Los comentarios del código no siguen la regla de mayúsculas.** Son para quien programa, no
  para quien usa, y ahí importa otra cosa: que digan **por qué**, y sobre todo qué pasó cuando
  no estaba así.
- **La longitud de los textos.** Un propósito de una línea y otro de tres están los dos bien si
  los dos dicen algo que no dice ninguna otra parte de la pantalla.
