# MVP: qué tiene que hacer la primera versión útil

El MVP está cerrado cuando **el entregable real del cruce minero de BHP se resuelve de punta
a punta desde la interfaz**, sin línea de comandos y sin que nadie tenga que saber qué es
BigTIFF.

---

## El recorrido completo, tal como lo vive quien lo usa

1. Suelta `Cruce Minero.tif` en la mesa.
2. **Antes de un segundo** aparece la ficha: BigTIFF · 14.526 × 14.443 px · 4 bandas con
   alfa · LZW · teselado 256 · 6 pirámides internas · EPSG:32719 · 2,56 cm/px · 372 × 369 m.
3. Debajo, la tira de veredictos: **Civil 3D en rojo, «es BigTIFF»**; QGIS y ArcGIS en verde.
4. Elige el destino **Civil 3D**. No elige formato ni opciones: eso lo pone el perfil.
5. Ve una línea honesta antes de encolar: *saldrá ≈ 283 MB · unos 2 min · hay 180 GB libres*.
6. El progreso avanza por etapas nombradas —huella, inspección, conversión, verificación— y
   se puede cancelar.
7. Al terminar, **el recibo**: tamaño antes y después, dimensiones y CRS sin cambio, el
   `sha256` del original, y la comprobación de que las estadísticas por banda coinciden.
8. El archivo abre en el Civil 3D de otro computador.

El paso 8 es el criterio real. Los siete anteriores son medios.

## Lo mínimo, y por qué cada cosa está dentro

| Tiene que estar | Por qué no se puede posponer |
| --- | --- |
| La ficha del archivo | Es la mitad del valor. Hoy no hay nada que te lo diga sin abrir QGIS y saber dónde mirar |
| Los veredictos por destino | Es lo que ninguna otra herramienta da, y el motivo por el que existe el producto |
| Destino por programa, no por extensión | Nadie quiere «un GeoTIFF con `BIGTIFF=NO`»: quiere que abra en el PC del proyectista |
| El recibo | Es lo que se le manda al cliente. Sin él, «lo convertí» es una afirmación sin respaldo |
| Cancelar | Una conversión de tres horas que no se puede parar es una máquina secuestrada |
| El original intacto | El original **es** el entregable. Tocarlo sería perder el trabajo de campo |
| La matriz de capacidades | Es la pantalla que se mira antes de escribir a soporte |

## Lo que el MVP deja fuera, a sabiendas

| Fuera | Por qué se puede esperar |
| --- | --- |
| Nubes de puntos, vectorial, BIM | Fases F2 a F4. El motor de trabajos es el mismo; solo cambian los motores |
| Lotes de muchos archivos | Repetir un trabajo con un clic cubre el 90 % del caso |
| ECW | Motor opcional desde el diseño. Sin clave, JP2 hace el trabajo mejor y gratis |
| El modo nube | El código está, pero el caso real es local: los archivos pesan gigabytes |
| Cuentas y roles finos | Una oficina, unas pocas personas. Login sí; jerarquía de permisos, no todavía |

## Los valores por omisión, que ya están decididos y medidos

No son preferencia: salen de medir sobre la ortofoto real (ver
[PRUEBAS_CON_ORACULO.md](PRUEBAS_CON_ORACULO.md) §2).

| Perfil | Formato | Por qué |
| --- | --- | --- |
| Civil 3D / AutoCAD | GeoTIFF clásico, DEFLATE-9, 3 bandas + máscara | Idéntico bit a bit, 61 % del peso, y 33 MB menos que LZW |
| Entrega al cliente | JPEG 2000 | 13 % del peso, error máximo de 4 sobre 255, georreferencia dentro |
| QGIS · visor web · AeroBim | COG, DEFLATE | Se sirve por rangos HTTP |
| ArcGIS Pro | GeoTIFF, `BIGTIFF=IF_SAFER` | Sí lee BigTIFF; no hay razón para forzar clásico |
| Google Earth | KMZ teselado, EPSG:4326 | Es lo único que lee |

## Cómo se sabe que está terminado

Los diez pasos de verificación de punta a punta, con el archivo real, y **el oráculo
externo**: `gdalinfo -json -stats` sobre entrada y salida coincidiendo en ancho, alto, CRS y
estadísticas por banda. No basta con que la aplicación diga que funcionó.
