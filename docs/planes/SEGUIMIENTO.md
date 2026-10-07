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
| P2 | **Confirmar el cierre** de las ramas `codex/prueba-diseno-b` y `-c` | F13.12 | Un sí | Se dejan abiertas, sin coste |
| P3 | **Aprobar el reparto con Stirling-PDF** (documento de decisión) | F14.0 | Un sí o ajustes | Todo se hace en casa, sin Stirling |
| P4 | **La plantilla de J.E.J.** (portada, encabezado y pie) | F14.19 | Un archivo fuera del repositorio | F14.19 ⏸ |
| P5 | **Puntos de control con coordenadas publicadas** (PSAD56, SAD69, SIRGAS-Chile) | F15.1 a F15.3 | CSV fuera del repositorio | F15.1 a F15.3 ⏸ |
| P6 | **Un archivo real de Deswik, Vulcan, Surpac y Datamine**, abierto en su programa | F15.4 | Archivos + fecha de la prueba manual | F15.4 queda ⚠ sin validar |
| P7 | **Instalar ODA en `p340`** | F15.8 (y F3.4) | Instalación + `AEROCONVERT_ODA` en el `.env` | F15.8 ⏸ |
| P8 | **Decidir si el repositorio sigue público** | HANDOFF (rutas y puerto de `p340`) | Un sí o no | Se dejan como están |
| P9 | **Copia de respaldo fuera de la máquina** | — | Dónde va | Lo único sin arreglo posible después de un fallo |
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
| **B5 · Barra, portada y mapa** | F13.9 · F13.8 · F13.11 · F13.12 | ⬜ | — | B4 · P2 (F13.12) |
| **B6 · Suite PDF** | F14.0 · extraer (F14.1) · F14.2 · F14.3 · F14.4 · F14.5 · F14.6 · F14.7 · F14.8 · F14.9 · F14.11 · F14.20 | ⬜ | — | P3 (F14.0) |
| **B7 · Imagen, dron, video y vector** | F14.12 · F14.13 · F14.14 · F14.15 · F14.16 · F14.17 · F14.18 · F14.19 | ⬜ | — | D1 (FFmpeg) · P4 (F14.19) |
| **B8 · Geoespacial** | F15.1 a F15.8 | ⬜ | — | P5 · P6 · P7 |
| **B9 · Plataforma** | F16.1 a F16.6 | ⬜ | — | B7 · B8 para los lotes |
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
