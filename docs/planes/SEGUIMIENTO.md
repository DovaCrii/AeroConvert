# Seguimiento del plan F13 a F16

> **El tablero.** Lo actualiza la skill `/avanzar` con cada PR fusionado. Plan completo:
> [`PLAN_2026-10-07.md`](PLAN_2026-10-07.md). Filas y oráculos: `MASTER_PLAN.md`.
> Quién hace qué: **Claude** hace ramas, PR, revisión y fusiones; **la persona solo despliega en la
> VM, al final de todo**.

**Actualizado:** 2026-10-07 · **`main` en:** `c551dcd` · **PR sin desplegar:** #21 a #56

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
| P14 | **URL de una autoridad de sello de tiempo (TSA)** y, si hay, sus credenciales | F14.5 (sello de tiempo opcional) | Una URL en el `.env` | Las firmas salen sin sello de tiempo: valen, pero la fecha es la que dice el firmante |
| P15 | **Parcial: llegó un vuelo (Matrice 3E, Baquedano, 2025-12-29) con la trayectoria y las posiciones de Trimble; faltan la coordenada de la base y el RINEX de la base.** Un vuelo de verdad con PPK: RINEX del dron y de la base, el `.MRK` (o la lista de disparos) y unas fotos, fuera del repositorio, más la **coordenada conocida de la base y su sistema** | F18.3 y F18.4 | Archivos en OneDrive + la coordenada | F18.3 queda ⚠: se prueba todo menos la corrida real de RTKLIB |
| P16 | **Permiso para bajar RTKLIB** (BSD-2) a esta estación y poder correr `rnx2rtkp` aquí | F18.3 | Un sí | La corrida real solo se mide en `p340` |
| P10 | **Terminar F10.5** (Trimble bajo Wine) | F10.5 | Pasos de `HANDOFF.md` | Sigue abierta |

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
| **B6 · Suite PDF** | F14.0 ✅ · F14.1 ✅ · F14.2 ✅ · F14.3 ✅ · F14.4 ✅ · F14.5 ✅ · F14.6 ✅ · F14.7 ✅ · F14.8 ✅ · F14.9 · F14.11 · F14.20 ✅ | 🟨 | #65, #66, #67, #68, #69, #70, #71 | — |
| **B7 · Imagen, dron, video y vector** | F14.12 · F14.13 ✅ · F14.14 ✅ · F14.15 · F14.16 🟨 · F14.17 · F14.18 ✅ · F14.19 ✅ | ⬜ | — | D1 (FFmpeg) |
| **B8 · Geoespacial** | F15.1 a F15.8 | ⬜ | — | P5 · P6 · P7 |
| **B9 · Plataforma** | F16.1 · F16.2 · F16.3 ✅ · F16.4 · F16.5 · F16.6 ✅ | ⬜ | — | B7 · B8 para los lotes |
| **B11 · Poner en marcha lo apagado** | F17.1 a F17.4 (`docs/PUESTA_EN_MARCHA_DE_LO_APAGADO.md`) | ⬜ | — | P7 · P10 · P11 · P12 · P13 para lo que es de la persona |
| **B12 · Vuelos de dron: PPK y sincronía** | F18.1 ✅ · F18.2 ✅ · F18.3 ⚠ · F18.4 ✅ · F18.5 · F18.6 ✅ · F18.7 (`docs/VUELOS_DE_DRON_Y_PPK.md`) | 🟨 | — | P15 para la corrida real |
| **B10 · Cierre y despliegue** | Versión (`0.11.0` al cerrar F13, `0.12.0` con las firmas), `HANDOFF.md` con los pasos de la VM, lista para desplegar | ⬜ | — | Todo lo anterior |

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
