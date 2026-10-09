# Dirección visual «Plan de vuelo»

**Decisión D8 (2026-10-09), fila F13.14 de `MASTER_PLAN.md`.** La persona vio tres direcciones
sobre la misma pantalla y eligió **«A · Plan de vuelo» para toda la app**, con dos préstamos:

- de «C · Instrumento»: las **esquinas de encuadre** y las **cifras en monoespaciada** en
  Compatibilidad y en las lecturas (cifras, versiones, coordenadas);
- de «B · Mesa de luz»: las **curvas de nivel**, **solo** como textura de la zona de soltar.

Esto **sustituye al «plano con color» de F13.7** (sin degradados, sombras ni movimiento). Lo que
F13.7 decidía sobre el color de las baldosas de familia y sobre el contraste sigue vigente.

La maqueta que se miró vive fuera del repositorio. Lo que sigue es lo que quedó escrito en
`static/css/app.css` y lo que lo vigila.

## El concepto

El archivo hace un vuelo. **Soltar el archivo es el despegue**; los **pasos numerados son puntos
de ruta** unidos por una línea de trayectoria; **la verificación y la descarga son el aterrizaje**.
La metáfora ya existe en el producto (trayectoria, disparos, posiciones): la interfaz solo la hace
visible. Nada de esto cambia textos ni estructura de las pantallas: son clases y tokens.

## Los tokens

Todos en `:root`, redefinidos en oscuro bajo `@media (prefers-color-scheme: dark)` guardado por
`:root:not([data-theme="light"])` y en `:root[data-theme="dark"]`. **Los tres bloques los declaran**:
el del sistema es el que ve quien no ha tocado el interruptor, y ya se olvidó una vez.

| Token | Para qué | Claro | Oscuro |
| --- | --- | --- | --- |
| `--av-barra-fin` | Final del degradado de la barra (el principio es `--av-navy`) | violeta frío | el mismo |
| `--av-ruta` | La línea punteada entre pasos y la trayectoria de la zona de soltar | azul cielo oscuro | cielo claro |
| `--av-ruta-barra` | El cielo del filete de la barra | cielo claro | el mismo |
| `--av-halo` | El anillo luminoso del paso actual | rosa claro | magenta apagado |
| `--av-resplandor` | El fondo de la portada | rosa muy claro | ciruela muy oscuro |
| `--av-curvas` | El color de las curvas de nivel (se aplica con una máscara) | azul grisáceo | azul pizarra |
| `--av-realce` | La línea de luz de 1 px arriba de una superficie | blanco al 85 % | blanco al 9 % |
| `--av-sombra-corta`, `--av-sombra-larga` | Las dos sombras de la elevación | azul noche | negro |
| `--av-elev-0` … `--av-elev-3`, `--av-elev-hover`, `--av-elev-boton` | La elevación (ver abajo) | | |
| `--av-fuente-texto`, `--av-fuente-titulos`, `--av-fuente-cifras` | Las tres pilas de letra | | |

El **borde de un control** (campo, botón fantasma) sigue siendo `--av-border-control`, que llega a
3:1; el borde decorativo de una tarjeta es el anillo `--av-anillo`, que no. **No se mezclan.**

## Las capas: cuándo se usa cada cosa

| Capa | Qué es | Dónde |
| --- | --- | --- |
| Fondo | `--av-bg`, con el resplandor de la portada | la página |
| Vidrio | degradado de `--av-surface` a `--av-bg`, **sin** `backdrop-filter` | **solo** el lateral |
| `--av-elev-0` | solo el anillo | lo que se apoya y no flota |
| `--av-elev-1` | anillo, línea de luz y dos sombras largas | tarjetas, baldosas, pasos, mensajes |
| `--av-elev-2` | lo mismo, más marcado | lo que se levanta |
| `--av-elev-hover` | `-2` con el anillo en el color de acción | tarjeta o destino bajo el cursor o el foco |
| `--av-elev-boton` | el resplandor del color de acción | el botón principal (no el «suave») |
| `--av-elev-3` | la única sombra de lo que flota | menús y diálogos (hoy ninguno) |
| Barra | degradado de `--av-navy` a `--av-barra-fin`, y un filete magenta-cielo de 2 px | la cabecera |

**Una sombra con difuminado no se escribe a mano.** Se usa un token `--av-elev-*`. Los anillos sin
difuminado (`0 0 0 2px …`, el halo, el filo del campo) sí se pueden escribir.

## El movimiento

- **Entrada de la página y de lo que pinta htmx** (`#principal`, `#resultados`, `#reconocido`,
  `#ficha`): aparece y sube 8 px en 0,45 s. `backwards`, nunca `both`.
- **Al pasar el ratón o enfocar:** la tarjeta del catálogo sube **3 px**, el destino **2 px** y el
  botón **1 px**. Siempre con transición de **250 ms** del `transform` y de la sombra; la
  transición va en la regla base, no en `:hover`. Nada sube más de 3 px.
- **Estado:** 160 ms en color, fondo, borde y opacidad (F13.13).
- **La trayectoria de la zona de soltar** avanza despacio (14 s por vuelta). Es adorno: `aria-hidden`.
- **`prefers-reduced-motion: reduce` lo apaga todo:** transiciones y animaciones a 0,01 ms, las
  animaciones infinitas cortadas en una vuelta y nada se levanta al pasar.

## La tipografía

**No se ha descargado nada** (descargar exige el permiso de la persona). Las pilas son del sistema,
con el nombre de la familia libre por delante:

| Uso | Pila |
| --- | --- |
| Texto | `Inter`, `Segoe UI Variable Text`, `Segoe UI`, `system-ui`… |
| Titulares | `Space Grotesk`, `Bahnschrift`, `Segoe UI Variable Display`, `Segoe UI`, `system-ui`… |
| Cifras | `JetBrains Mono`, `ui-monospace`, `Cascadia Mono`, `Consolas`, `monospace` |

**Space Grotesk, Inter y JetBrains Mono son OFL 1.1.** Cuando la persona lo autorice se
vendorizarían en WOFF2 (una variable por familia, unos 140 KB en total) en `static/vendor/` con SRI,
y bastaría un `@font-face`: las pilas ya los nombran primero. Hasta entonces `test_plano.py` falla
si aparece un `@font-face`, un `@import` o una dirección de fuera en la hoja.

Las **cifras en monoespaciada** son las de las lecturas: la cifra de cada tira de Compatibilidad,
las versiones de los motores, las fichas, los recibos, el avance de una subida, el número de cada
paso y las cabeceras de la matriz.

## Las piezas de la dirección

- **Barra.** Degradado frío y filete magenta-cielo debajo. El texto blanco, el foco magenta y el
  borde del buscador se miden contra **los dos extremos** del degradado.
- **Lateral.** Es el único «vidrio»: un degradado de la superficie al fondo, sin desenfoque.
- **Portada.** Resplandor radial en el fondo; la zona de soltar lleva las **curvas de nivel**
  (`static/img/curvas-de-nivel.svg` como máscara, pintada con `--av-curvas`, así que sigue al
  tema) y la **trayectoria punteada** (un `<svg class="soltar-ruta">` con `aria-hidden`).
- **Pasos de una herramienta como puntos de ruta.** Una línea punteada baja por detrás de las
  tarjetas, a la altura del centro de cada número, y se ve en los huecos. **El paso actual** (el
  primero que aún no tiene lo que pide) lleva el halo, **y además** el número en el color de
  acción y el borde: el halo nunca es el único indicador. **El paso hecho** lleva su número en
  verde **y** una insignia con ✓ (forma, no solo color). Se calcula con CSS (`:has`), sin tocar la
  plantilla; sin soporte de `:has`, los pasos quedan sin halo y sin marca, pero con su línea.
- **Compatibilidad, lecturas y recibos.** Esquinas de encuadre (dos ángulos de 10 px en el color
  de acción, arriba a la izquierda y abajo a la derecha) y cifras en monoespaciada.
- **Botones, campos, píldoras y mensajes.** El botón principal lleva su resplandor; el campo, un
  filo de sombra arriba como un hueco; el mensaje, `--av-elev-1`.

## Lo que no cambia

- Contraste **WCAG 2.1 AA medido desde el CSS** (`test_paleta.py`): 4,5:1 para texto y 3:1 para
  controles, en los tres bloques de tema.
- El color nunca va solo (color + forma + texto); nada escondido en hover; una acción principal
  por pantalla; foco visible.
- CSP `'self'`, cero CDN, sin `unsafe-inline` en `script-src`.

## Qué lo vigila

| Prueba | Qué impide |
| --- | --- |
| `apps/core/test_plano.py` | degradados fuera de barra, lateral y fondo de portada; una sombra con difuminado escrita a mano; un `transform` al pasar que no sea `translateY(-3px)` como máximo; subir sin transición de 150 a 300 ms; una transición de `transform` fuera de lo que se levanta o gira; una animación infinita sin corte con `prefers-reduced-motion`; un `@font-face` o una descarga; las curvas de nivel como SVG inválido |
| `apps/core/test_paleta.py` | texto, foco y borde del buscador bajo su piso sobre cualquiera de los dos extremos de la barra; la ruta, la marca de paso hecho y el anillo del número bajo 3:1 o 4,5:1 |
| `apps/core/test_escalas.py` | el anillo deja de ir primero en cada nivel de elevación |
| `apps/core/test_escala_visual.py` | tamaños de letra y radios fuera de la escala |

## Cómo se revisa una pantalla

Claro y oscuro, a 1440 y a 375 px, **sin desborde horizontal** (`scrollWidth == innerWidth`), con
`prefers-reduced-motion` activado una vez para comprobar que nada se mueve.
