# Seguimiento del plan F13 a F16

> **El tablero.** Lo actualiza la skill `/avanzar` con cada PR fusionado. Plan completo:
> [`PLAN_2026-10-07.md`](PLAN_2026-10-07.md). Filas y oráculos: `MASTER_PLAN.md`.
> Quién hace qué: **Claude** hace ramas, PR, revisión y fusiones; **la persona solo despliega en la
> VM, al final de todo**.

**Actualizado:** 2026-10-09 · **`main` en:** versión `0.12.0` · **PR sin desplegar:** #21 a #97

## Pedidos a la persona

Lo que Claude necesita para avanzar y no tiene. **Sin él, la fila espera (⏸) y se sigue con otra.**

| # | Qué se necesita | Para qué fila | Forma | Si no llega |
| ---: | --- | --- | --- | --- |
| P1 | ~~Aprobar la tabla de renombres~~ **Resuelto el 2026-10-07**: programa como título y propósito debajo, y los siete renombres | F13.2 | — | — |
| P2 | ~~Confirmar el cierre de las ramas de prueba~~ **Resuelto el 2026-10-07**: `-b` y `-c` no existían; se borró `prueba-diseno-resultado` | F13.12 | — | — |
| P3 | ~~Aprobar el reparto con Stirling-PDF~~ **Resuelto el 2026-10-07: sí, como se propuso** (~12 de uso diario en casa; Stirling-PDF local sondeado para la cola larga, apagado con motivo si falta) | F14.0 | — | — |
| P4 | ~~La plantilla de J.E.J.~~ **Resuelto el 2026-10-07**: dos plantillas Word (`Portada Documentos` y `Portada Ofertas y Planes Licitaciones`, en OneDrive, **fuera del repositorio**; llevan el logo). Salida **Word y PDF**, desde **una pantalla que genera la portada sola**. Campos: código `JEJ-…`, título del procedimiento, servicio, plan y autor | F14.19 | — | — |
| P5 | **Puntos de control con coordenadas publicadas** (PSAD56, SAD69, SIRGAS-Chile) | F15.1 a F15.3 | CSV fuera del repositorio | F15.1 a F15.3 ⏸ |
| P6 | **Un archivo real de Deswik, Vulcan, Surpac y Datamine**, abierto en su programa | F15.4 | Archivos + fecha de la prueba manual | F15.4 queda ⚠ sin validar |
| P7 | **Instalar ODA en `p340`** | F15.8 (y F3.4) | Instalación + `AEROCONVERT_ODA` en el `.env` | F15.8 ⏸ |
| P8 | **Decidir si el repositorio sigue público** | HANDOFF (rutas y puerto de `p340`) | Un sí o no | Se dejan como están |
| P9 | **Copia de respaldo fuera de la máquina** | — | Dónde va | Lo único sin arreglo posible después de un fallo |
| P11 | **Permiso para descargar PDF.js** y vendorizarlo con SRI | F14.11 | Un sí | F14.11 ⏸ |
| P12 | **GDAL con ECW** en el equipo que ejecuta (lectura) | Pantalla de compatibilidad | Instalación | ECW sigue apagado; sirven COG y JP2 |
| P13 | **Clave OEM de ECW** (escritura) | Pantalla de compatibilidad | `AEROCONVERT_ECW_ENCODE_KEY` y `…_COMPANY` en el `.env`, nunca en el repo | Sin escritura ECW |
| P14 | **URL de una autoridad de sello de tiempo (TSA)** y, si hay, sus credenciales | F14.5 (sello de tiempo opcional) | Una URL en el `.env` (`AEROCONVERT_TSA_URL`) | Las firmas salen sin sello de tiempo: valen, pero la fecha es la que dice el firmante |
| P15 | **Parcial: llegó un vuelo (Matrice 3E, Baquedano, 2025-12-29) con la trayectoria y las posiciones de Trimble; faltan la coordenada de la base y el RINEX de la base.** Un vuelo de verdad con PPK: RINEX del dron y de la base, el `.MRK` (o la lista de disparos) y unas fotos, fuera del repositorio, más la **coordenada conocida de la base y su sistema** | F18.3 y F18.4 | Archivos en OneDrive + la coordenada | F18.3 queda ⚠: se prueba todo menos la corrida real de RTKLIB |
| P16 | **Permiso para bajar RTKLIB** (BSD-2) a esta estación y poder correr `rnx2rtkp` aquí | F18.3 | Un sí | La corrida real solo se mide en `p340` |
| P10 | **Terminar F10.5** (Trimble bajo Wine) | F10.5 | Pasos de `HANDOFF.md` | Sigue abierta |
| P17 | **Permiso para bajar EPUBCheck** (W3C, BSD-3; Java 11 ya está en la estación) | F14.22 | Un sí | El EPUB se comprueba con `zipfile` y `defusedxml`; F14.22 queda ⚠ |
| P18 | **La altura elipsoidal de la base `AUX_01`** del vuelo de Baquedano. Los datos llegaron (2026-10-09): RINEX del dron, `.MRK`, el `.T04` de la base (R12i, 15:34–16:56 GPST, antena 1,374 m) y `Baquedano_PC.csv` con `AUX_01` en UTM, pero con altura **ortométrica** (1037,918; 35,6 m bajo la elipsoidal). RTKLIB pide la elipsoidal | F18.3 (corrida real) y F18.7 | Latitud, longitud y altura elipsoidal de `AUX_01` exportadas de TBC, o el nombre del modelo de geoide del proyecto | La pantalla de PPK se hace igual (con pruebas de RTKLIB falso); la comparación real contra TBC espera. **Dato informativo, no es la altura de la base** (F15.2, 2026-10-09, `manage.py convertir_altura`, `AUX_01` E 414790,476 N 7418959,900 UTM 19S, H = 1037,918): con **EGM96** N = 31,820 m, o sea 1069,738 m elipsoidal; con **EGM2008** no se pudo calcular (falta `us_nga_egm08_25.tif` en esta máquina). Los «35,6 m» de arriba no cuadran con EGM96 (3,8 m de diferencia), lo que sugiere otro modelo: **qué modelo usó TBC lo tiene que confirmar la persona** |
| P19 | **Un archivo DC** (calibración local de Trimble) de un proyecto real | F18.11 (coordenadas locales, como UAS Sync 4.1) | Archivo en OneDrive | F18.12 ⏸ |
| P20 | **Un vuelo RTK real**: las fotos de un vuelo con RTK en el aire (bandera 34 o 50) y su exportación de UAS Sync o de TBC, fuera del repositorio | F18.8 (vuelos RTK) | Carpeta en OneDrive | F18.8 queda ⚠: la bandera 16 se vio en un vuelo PPK; 50 y 34 son las que publica DJI, sin contrastar |

## Bloques

Estados: ✅ hecho · 🟨 en curso · ⬜ por hacer · ⏸ espera un pedido · ⚠ hecho sin poder comprobar todo.

| Bloque | Filas | Estado | PR | Depende de |
| --- | --- | --- | --- | --- |
| **B0 · Cierre** | #54 organizar y encadenar (F14.1 organizar, F14.10); plan a `main` | ✅ 2026-10-07 | #54, #55 | — |
| **B1 · Lenguaje y limpieza** | F13.3 usted ✅ · F13.10 estilos en línea ✅ | ✅ 2026-10-07 | #56, #58 | — |
| **B2 · Taxonomía y nombres** | F13.1 taxonomía ✅ · F13.2 nombres ✅ | ✅ 2026-10-07 | #59, #60 | P1 resuelto |
| **B3 · Iconos y color** | F13.4 ✅ · F13.5 ✅ · F13.6 ✅ | ✅ 2026-10-07 | #61 | — |
| **B4 · Plano con color** | F13.7 ✅ | ✅ 2026-10-07 | #62 | — |
| **B5 · Barra, portada y mapa** | F13.9 ✅ · F13.8 ✅ · F13.11 ✅ · F13.12 ✅ · F13.13 ✅ (cierra F13; versión `0.11.0`) | ✅ 2026-10-07 | #63, #64 | — |
| **B6 · Suite PDF** | F14.0 ✅ · F14.1 ✅ · F14.2 ✅ · F14.3 ✅ · F14.4 ✅ · F14.5 ✅ · F14.6 ✅ · F14.7 ✅ · F14.8 ✅ · F14.9 ⚠ (sin veraPDF) · F14.11 ⏸ · F14.20 ✅ | 🟨 | #65 a #71, #78, #93 | P11 para F14.11 |
| **B7 · Imagen, dron, video y vector** | F14.12 ⚠ (Tesseract real en `p340`) · F14.13 ✅ · F14.14 ✅ · F14.15 · F14.16 🟨 (falta SVG, Inkscape) · F14.17 ⚠ (FFmpeg real en `p340`) · F14.18 ✅ · F14.19 ✅ | 🟨 | #72, #73, #75, #76, #94 | D1 (Inkscape) |
| **B8 · Geoespacial** | F15.1 ⏸ · F15.2 ⚠ (EGM96 medido; EGM2008 espera su grilla) · F15.3 ⏸ · F15.4 ⏸ · F15.5 · F15.6 ◐ (falta DWG) · F15.7 · F15.8 ⏸ | 🟨 | #86 | P5 · P6 · P7 |
| **B9 · Plataforma** | F16.1 ✅ · F16.2 ✅ · F16.3 ✅ · F16.4 ✅ · F16.5 · F16.6 ✅ | 🟨 | #79, #80, #87, #92 | F16.5 necesita a AeroBim |
| **B11 · Poner en marcha lo apagado** | F17.1 ⚠ · F17.2 ⚠ · F17.3 ✅ · F17.4 ✅ (`docs/PUESTA_EN_MARCHA_DE_LO_APAGADO.md`) | ✅ en código; los ⚠ se miden en `p340` | #89, #90, #91, #95 | P7 · P10 · P11 · P12 · P13 para lo que es de la persona |
| **B12 · Vuelos de dron: PPK y sincronía** | F18.1 ✅ · F18.2 ✅ · F18.3 ⚠ · F18.4 ✅ · F18.5 ✅ · F18.6 ✅ · F18.7 ⏸ (`docs/VUELOS_DE_DRON_Y_PPK.md`) | 🟨 | #81 a #85 | P15 y P16 para la corrida real |
| **B13 · Pedidos tras el despliegue (2026-10-09)** | Lateral que cuenta lo que enseña, chapa y Compatibilidad ✅ #100 · PDF restringido y «ver en grande» ✅ #101 · F14.22 EPUB ⚠ (P17) · F18.7 PPK desde RINEX en pantalla · F18.8 vuelos RTK ⚠ 2026-10-09 (P20) · F18.9 ficha EXIF por foto en el visor ✅ 2026-10-09 · F18.10 orientación de cámara en el CSV ✅ 2026-10-09 · F18.11 coordenadas locales con DC ⏸ (P19) · F18.12 aspecto propio de la sección de drones · F18.13 mover los vuelos a `apps/vuelos/` (después de F18.7 y D8) | 🟨 | #100, #101 | P17 · P18 · P19 · P20 |
| **B14 · Visor geoespacial (D7)** | F19.1 ✅ · F19.2 ✅ (2026-10-09, `/mapa/`, `apps/visor/`) · F19.3 capas · F19.4 terreno · F19.5 mapa base propio · F19.6 contrato con AeroBim. Ortofotos, imágenes, mapas base propios y terreno aquí; el 2D de planos sigue en AeroBim | 🟨 | — | F19.6 necesita a AeroBim · medir una ortofoto real de varios GB en `p340` |
| **B10 · Cierre y despliegue** | Versión `0.12.0` ✅, `HANDOFF.md` con los pasos de la VM ✅ | ✅ 2026-10-08 · **falta desplegar (la persona)** | #97 | — |

**Orden de trabajo:** B1 → B2 → B3 → B4 → B5 (esto cierra F13 y la versión `0.11.0`); B6 con
las firmas (`0.12.0`); B7 y B8 según los pedidos que lleguen; B9; B10. Un bloque con un pedido
pendiente **no frena** a los demás: se pasa al siguiente que se pueda.

## Para el despliegue final (lo hace la persona)

```bash
cd /opt/aeroconvert && sudo -u aeroconvert git pull && sudo scripts/desplegar.sh
```

La lista exacta de cada despliegue (migraciones, variables del `.env`, programas por instalar) la
deja Claude en `HANDOFF.md` al cerrar B10. Después, `resumen_de_uso --dias 7` y repetirlo 2 o 3
semanas: con esas cifras se decide el orden de lo que venga.
