# Cómo es y cómo será el inicio y el lateral

Este es el diseño **acordado** (F13, 2026-10-07 y 2026-10-08). Quien toque la portada o el lateral
parte de aquí y no lo cambia sin que la persona lo pida. Lo que se ve hoy en `p340` es la interfaz
**anterior a F13** (todavía dice «¿Qué necesitas…?», sin zona de soltar y con el lateral largo):
se actualiza en el despliegue final. La implementación vive en `templates/dashboard/que_puedo_hacer.html`,
`templates/base.html`, `static/css/app.css`, `static/js/{reconocer,plegable,lateral}.js` y
`apps/dashboard/taxonomia.py`.

## Inicio («archivo primero»)

1. **Arriba, una sola acción principal: soltar un archivo.** La zona de soltar es lo primero de la
   página. Al soltarlo se lee su cabecera (sin esperar a que termine de subir) y debajo aparece
   **qué es**, su **ficha** con los veredictos (CRS, tamaño, avisos) y **solo las herramientas que
   aplican a ese archivo**.
2. **Debajo, para quien trae una intención y no un archivo:** el buscador («juntar planos, quitar
   contraseña, pasar a Excel…»), con el atajo `/` enseñado al lado y ejemplos pulsables
   («tif a jp2», «excel»). Entiende la palabra de quien busca, pares de formato y contenido.
3. **Después, el catálogo por grupos**, los mismos nueve del lateral y en el mismo orden, cada uno
   con su icono, su frase y la cifra de herramientas. Las baldosas dicen **qué entregan**
   («Sale: un PDF») y llevan el color de su familia.
4. **Trato de usted** en todo el texto («¿Qué necesita hacer?»).
5. **Diseño plano con color:** sin degradados, sin sombras, sin movimiento al pasar; borde y
   superficie. Las baldosas conservan un color de familia fuerte, también en oscuro (no gris).
6. Sin nada que solo aparezca al pasar el ratón; el color nunca va solo (icono + texto).

## Lateral

1. **Arriba, tres destinos fijos:** Inicio, Convertir, Historial.
2. **Debajo, «Herramientas» en nueve grupos** (una sola taxonomía, `taxonomia.py`): cada grupo es un
   `details` con su **icono**, su nombre y **la cifra de herramientas**. Cada persona deja abiertos
   los que quiera y el sistema lo **recuerda** (por id estable del grupo, no por su título).
3. Dentro del grupo, cada herramienta con su icono de familia y su nombre en verbo o «X a Y».
4. **Reducido a iconos** (botón de hamburguesa): se ve una columna de iconos de grupo con su
   **insignia de cantidad** y un acceso a «Todas las herramientas»; en pantallas estrechas el
   lateral sale encima del contenido.
5. **La explicación del modo** («Los archivos salen de la carpeta compartida…») vive en el lateral
   y no en la barra de arriba, que queda en tres zonas: marca · buscador · cuenta.
6. Mismo comportamiento y mismos tokens que AeroControl, para que las apps hermanas se sientan una.

## Lo que se mide

`test_plano` (0 degradados), `test_trato`, `test_estilo`, `test_iconos`, `test_taxonomia`,
`test_lateral_compacto`, `test_portada_archivo` y el contraste WCAG de cada familia en los dos
temas. Una pantalla nueva se mira en claro y oscuro, a 1440 y a 375 px, sin desborde horizontal.

## Referencia visual mirada (no adoptada todavía): ArtCraft

Se miró su sitio y sus capturas el 2026-10-08 (solo como referencia de diseño; el código no se
usa, ver `DECISION_ARTCRAFT.md`). Lo que se ve y lo que sirve:

- **Oscuro neutro y plano, un solo acento azul, un solo botón blanco de acción** («Launch app»).
  AeroConvert ya va por ahí (plano con color, una acción principal por pantalla).
- **Barra flotante de herramientas sobre el lienzo** (Mover · Girar · Escalar, con icono y texto) y
  **un panel de acción abajo** con las opciones en fichas pequeñas y un único botón principal.
  Candidato para las pantallas de herramientas: las opciones en una fila de fichas junto al botón
  principal, en vez de tarjetas largas de formulario.
- **Etiquetas de navegación en mayúsculas con tipografía monoespaciada**, muy pequeñas: da
  carácter técnico. Candidato para los rótulos del lateral («Herramientas») si se quiere.
- Lo que **no** conviene copiar: el mosaico animado de miniaturas y el degradado de la portada
  (F13.7 prohíbe degradados y movimiento al pasar).

**Lo que la persona dijo que le gusta (2026-10-08):** el diseño, la página, **las transiciones y el
estilo oscuro**. Dirección acordada, compatible con F13.7 (plano, sin degradados, sin sombras, sin
movimiento al pasar el cursor):

- **Oscuro primero:** tema oscuro neutro (casi negro, gris frío) como el que se ve por omisión, con
  un solo acento y un solo botón principal por pantalla. El claro sigue existiendo.
- **Transiciones sí, pero de estado, no de movimiento:** 150 a 200 ms en color, borde, fondo y
  opacidad; entrada suave de la página y de los paneles (aparecer, no desplazarse). **Sin**
  `transform` al pasar, **sin** sombras y **sin** degradados.
- **Respeta `prefers-reduced-motion`:** con esa preferencia, todo es instantáneo.
- **Opciones en fichas junto al botón principal** y rótulos técnicos en mayúscula pequeña.

Entra como **F13.13** (`MASTER_PLAN.md`), con prueba: transiciones declaradas solo sobre
propiedades de estado, ninguna `transform` en `:hover`, y bloque `prefers-reduced-motion`.

## El grupo «Vuelos de dron» y el visor del vuelo (2026-10-08)

Los vuelos tienen **su propio grupo**, como GNSS (la traza de un video, las fotos del dron y el
proceso que corrige su posición), con su índice en `/documentos/vuelos/`. La pantalla **«Corregir
un vuelo de dron»** sigue la disposición de Emlid Studio: a la izquierda los pasos en orden
(trayectoria, disparos, posiciones de Trimble, carpeta de fotos y cómo procesar) y a la derecha
qué va a pasar y qué sale. Al terminar, la ficha del trabajo ofrece **«Ver el vuelo en el mapa»**:
el recorrido, un punto por foto coloreado por su calidad, la retícula con el Este y el Norte reales
del sistema **medido** (que se dice arriba, con su EPSG), y la foto elegida con sus datos. Sin mapa
base ni bibliotecas: un `<canvas>` con lo que hay en `vuelo.json`. Mientras corre, la barra dice el
porcentaje **y qué se está haciendo** («Sincronizando las fotos con la trayectoria»).
