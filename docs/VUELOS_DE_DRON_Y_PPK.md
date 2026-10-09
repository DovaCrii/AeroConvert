# Vuelos de dron: del dato crudo a las fotos con la posición corregida (PPK)

Decisión y diseño del 2026-10-08, a partir de `DovaCrii/geoforge-studio` y del flujo que hace un
programa de «sincronía de fotos» (UAS sync) en un levantamiento con dron.

## Qué se encontró en GeoForge Studio

`geoforge-studio` es una aplicación de escritorio (mapa 2D, importación de DXF y KMZ, volúmenes por
TIN, ayuda) con licencia **Apache-2.0**, así que su código se puede portar. Pero su parte GNSS, que
es la que interesa aquí, **es un marcador de posición**:

- `src/services/ppk_service.py` devuelve un vector de línea base fijo `(10.0, 20.0, 5.0)` y un
  residuo `0.5`, con el comentario `TODO: Implement actual PPK algorithm`.
- `gnss-core/src/ppk.rs` hace lo mismo en Rust: «Placeholder baseline computation».
- Su propio `README` lo dice: «GNSS / PPK core: in progress, not production-grade».

**No hay algoritmo que portar, y portar números inventados sería lo contrario de las reglas 1 y 2
de `AGENTS.md`.** Lo que sí aporta son sus especificaciones (`openspec/specs/ppk-engine`,
`rinex-reader`), que se adoptan como criterio de aceptación: línea base única, época sin solución
dicha con su motivo, calidad fijo/flotante por época, salida en el CRS pedido, archivo corrupto o
parcial que se informa sin caerse.

## Cómo se hace de verdad

1. **El motor de PPK es RTKLIB `rnx2rtkp`** (BSD-2), un programa externo y probado. Se **sondea y se
   ejecuta aparte**, como `convbin` hoy (decisión D1). En `p340` ya está el paquete `rtklib`
   (`convbin` aparece como listo en la pantalla de compatibilidad), que trae `rnx2rtkp`.
2. **Lo que se escribe aquí es lo que hace falta alrededor**, y es lo que se puede probar con otro
   lector:
   - leer el `.pos` que sale de RTKLIB y resumir su calidad (F18.1);
   - **la sincronía**: la posición de cada foto, interpolada en la trayectoria corregida con la marca
     de tiempo de su disparo, sin extrapolar y diciendo la calidad de cada una (F18.2);
   - la orden de RTKLIB con sus parámetros y la verificación de lo que sale (F18.3);
   - la pantalla que lo une y sus entregables (F18.4).
3. **La regla 3 manda en la base.** Las coordenadas de la estación base **se declaran con su sistema**
   (ITRF/SIRGAS/WGS84 y su época); no se toman en silencio del `APPROX POSITION` del RINEX, que es
   aproximado a metros y arruinaría la corrección. La pantalla lo muestra y pide confirmarlo.

## La línea completa

| Paso | Qué entra | Qué sale | Fila |
| --- | --- | --- | --- |
| 1 | Datos crudos del receptor del dron o de la base (UBX, RT17, T02…) | RINEX | ya existe: «Datos de un receptor GNSS a RINEX» |
| 2 | RINEX del dron + RINEX de la base + efemérides + coordenadas de la base | `.pos` (trayectoria corregida) | F18.3 |
| 3 | `.pos` + marcas de disparo de las fotos (`.MRK` de DJI o lista de tiempos) | posición de cada foto | F18.2 |
| 4 | lo anterior + las fotos | zip: CSV para Pix4D/Metashape, GeoJSON, KMZ, informe de calidad y, si se pide, las fotos con la posición corregida | F18.4, F18.5 |

Y se junta todo en un grupo propio del lateral, **«Vuelos de dron»**, como «Datos de receptores
GNSS» pero para el vuelo: la traza de un video, las fotos del dron y este proceso, juntos.

## Lo que enseñó el primer vuelo real (2026-10-08)

Llegó un vuelo de un Matrice 3E con lo que sacó Trimble Business Center (su UAS sync). Cifras en
`docs/PRUEBAS_CON_ORACULO.md`. Lo que cambió:

- **El desfase de la antena se aplica.** Se había dejado sin sumar por no conocer el signo; con las
  2 505 fotos y Trimble de oráculo quedó medido: norte y este suman, `V` es positivo hacia abajo.
  Con eso la posición de cada foto coincide con la de Trimble a 0,9 mm como máximo.
- **El sistema se mide.** Trimble exporta Este y Norte sin decir en qué sistema; con el archivo
  ampliado (trae latitud y longitud) se prueba cada candidato y se dice cuál coincide.
- **La altura de Trimble no es la elipsoidal** del `.MRK` (35 m de diferencia): se dice de qué altura
  se trata y no se llama elipsoidal.
- **El flujo de Trimble es una segunda entrada**, además de RTKLIB: quien ya procesó el PPK en
  Trimble sube su trayectoria y el `.MRK`, y obtiene lo mismo que haría el UAS sync.

## Cómo se usa la segunda entrada: PPK con RTKLIB (F18.7)

En «Corregir un vuelo de dron», el primer paso pregunta **¿De dónde sale la posición precisa?** (desde
F18.8 tiene tres respuestas; la tercera, más abajo).

1. **«Calcularla aquí con RTKLIB (PPK)».** Si en la máquina no está `rnx2rtkp`, la opción sale
   apagada con su motivo (`sin-rnx2rtkp`) y cómo instalarlo (`sudo apt install rtklib`, o
   `AEROCONVERT_RTKLIB_RNX2RTKP`); la de Trimble sigue funcionando.
2. **Los archivos:** el RINEX de observación del dron (`*_PPKOBS.obs`), el de navegación (`*_PPKNAV.nav`,
   `.25n`, `.25g`, `.25l`; hace falta uno y el segundo es opcional) y el RINEX de observación de la
   base. Los disparos (`.MRK`), las posiciones de Trimble (opcionales: miden el sistema del visor y
   contrastan el plano) y la carpeta de fotos son los mismos de siempre.
3. **La coordenada de la base**, declarada: latitud y longitud en grados decimales, **altura
   elipsoidal** en metros y el **sistema**. El selector no trae ninguno elegido (regla 3). La
   altura ortométrica o la sobre el nivel del mar **no sirve**: corre toda la trayectoria el valor
   de la ondulación del geoide (decenas de metros en Chile). Si la base declarada está a más de 1 km
   del `APPROX POSITION` de su RINEX, no se procesa.
4. **Opciones de RTKLIB** (plegadas, con su valor): modo cinemático, máscara de elevación de 15°,
   sistemas G, R, E y C, umbral de resolución de ambigüedades de 3.
5. **Se sigue en la ficha del trabajo.** La barra sale de la hora que va procesando RTKLIB entre la
   primera y la última observación del dron (`TIME OF FIRST OBS` y `TIME OF LAST OBS`); si el RINEX
   no trae la última, solo se dice dónde va. El tramo de RTKLIB es el 2 % al 70 % de la barra y el
   resto (sincronizar, contrastar, escribir) lo que queda.

**Qué entrega:** además de `fotos.csv`, `fotos.geojson`, `fotos.kml`, `calidad.md` y `vuelo.json`, el zip
trae `trayectoria.pos` (lo que escribió RTKLIB, sin tocar) y `trayectoria.md` (porcentaje de
posiciones fijas, flotantes y simples, huecos, y **lo declarado**: la base, su sistema y las
opciones, para poder repetir la corrida). La calidad de cada foto es la **peor de las dos épocas
vecinas** de su disparo; lo que no es fijo se avisa con la cuenta. La hora es GPST (la del `.pos` y
la del `.MRK`), así que no se pregunta.

**Qué comprueba y qué no:** lo que prueba que funcionó es el `.pos` leído (regla 1), no el código de
salida de `rnx2rtkp`. Con las posiciones de Trimble delante se contrasta solo el **plano**: la altura
de Trimble no es elipsoidal y diferiría decenas de metros sin que eso sea un error.

**Ver también:** la corrida real contra el vuelo de Baquedano espera la altura elipsoidal de la
base (P18); las pruebas de CI usan un `rnx2rtkp` de mentira que escribe un `.pos` de resultado
conocido (`apps/vuelos/test_vuelo_ppk_pantalla.py`).

## La tercera entrada: las fotos ya traen la posición RTK (F18.8 a F18.10)

Cuando el dron voló con RTK **no hay PPK que hacer**: la posición precisa está escrita en cada foto. La
tercera respuesta de la misma pantalla («Las fotos ya traen la posición RTK») la **lee** y entrega los
mismos archivos. Es la misma pantalla y no una herramienta aparte porque lo que sale es lo mismo y porque
la pregunta es la que se hace quien viene del vuelo; los pasos que sobran (trayectoria, posiciones de
Trimble, copias con la posición) se ocultan y se muestra el sistema del visor sin valor elegido.

1. **Hace falta la carpeta de fotos y el `.MRK`.** El `.MRK` es el otro lector: las fotos se emparejan con
   sus disparos por orden (solo con tantos como fotos) y la posición de cada foto se compara con la del
   disparo. Si alguna difiere más de 2 cm no se entrega nada.
2. **La posición** es la del XMP de DJI (`GpsLatitude`, `GpsLongitude`, `AbsoluteAltitude`); si no hay XMP,
   la del EXIF. Es la de la **antena**; con la casilla de la cámara se aplica el desfase del `.MRK`.
3. **La altura** se llama elipsoidal solo si coincide con la «Ellh» del `.MRK` a 5 mm. DJI la mide
   «elipsoidal» en el `.MRK`; el XMP solo dice `AltitudeType="RtkAlt"`.
4. **La calidad** sale de `RtkFlag` (50 fija, 34 flotante, 16 simple, 0 sin solución). `GpsStatus` no sirve:
   dice «RTK» aunque la bandera sea 16. Sin bandera, «no informada»; con un código que no se conoce,
   «no reconocida».
5. **Sin trayectoria**: el visor dibuja solo los puntos, y el sistema se declara (no se supone).

**Ficha de cada foto (F18.9).** En el visor, al elegir una foto aparece su ficha de cámara, GNSS y dron, leída
del archivo (solo la cabecera), o, si la foto no está en la carpeta, del `export_extended` de Trimble.
Funciona igual en los tres orígenes.

**Qué se comprobó:** cifras con las 2 505 fotos del vuelo de Baquedano en `docs/PRUEBAS_CON_ORACULO.md`
(2026-10-09). Ese vuelo fue PPK y no RTK: solo se vio la bandera 16; **las 50 y 34 esperan un vuelo RTK
real (P20)**.

## Qué falta de la persona

- **Un vuelo de verdad** (P15): RINEX del dron, RINEX de la base, el `.MRK`, y unas fotos, fuera del
  repositorio, y la **coordenada conocida de la base con su sistema**. Sin él, F18.3 queda ⚠: se
  prueba todo lo demás, pero la corrida real de RTKLIB contra datos reales no.
- **Un vuelo RTK real** (P20): las fotos de un vuelo con RTK en el aire y su exportación de UAS Sync o
  de TBC. Sin él, F18.8 queda ⚠: las banderas 50 y 34 no se han visto en un archivo real.
- **Permiso para bajar RTKLIB a esta estación** (P16), para poder correr `rnx2rtkp` aquí y no solo
  en `p340`. Sin él, lo real se mide en el servidor.
