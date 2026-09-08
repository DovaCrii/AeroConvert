# Arquitectura

Tres decisiones fijan todo lo demás. Si algo del código parece raro, casi siempre se explica
por una de ellas.

---

## 1. Los motores no ejecutan nada

Un motor **describe** una conversión: qué pares de formatos sabe hacer, si está disponible
en esta máquina, qué opciones acepta y qué comando habría que lanzar. Quien lanza es un
único *runner* en `apps.jobs`.

```
Motor.pares()          →  qué sé hacer, esté o no instalado
Motor.disponibilidad() →  ¿puedo hacerlo aquí? si no, por qué y qué sirve en su lugar
Motor.opciones(par)    →  los ajustes, en forma declarativa
Motor.plan(trabajo)    →  argv, env, cwd, timeout, analizador de progreso
Motor.verificar(...)   →  ¿la salida sirve?
```

Parece ceremonia y no lo es: **es lo que hace que toda la capa se pueda probar sin GDAL
instalado**. Una prueba compara el `argv` construido contra el esperado, y eso atrapa el
error que de verdad ocurre. El precedente es literal — `AeroBim/services/api/apps/documents/conversion.py`
le pasa a ODA File Converter seis argumentos **posicionales y sin nombre**: equivocarse de
orden no da error, da una conversión a otra versión, y nadie se entera hasta que el cliente
abre el archivo.

De aquí sale también que `opciones()` sea declarativo: **el formulario se genera desde ahí**,
así que no puede ofrecer un ajuste que el motor no sepa traducir a un argumento.

## 2. La conversión corre en un proceso hijo

No en un hilo. GDAL con un ráster que agota la memoria no lanza una excepción: **mata el
proceso**. Si ese proceso es Django, se pierde la aplicación entera y los demás trabajos.
Un hilo de Python tampoco se puede cancelar; un hijo sí, con `terminate()`.

## 3. Una capacidad ausente se muestra apagada, con motivo y alternativa

Nunca se oculta y nunca se sustituye en silencio. Ocultar ECW cuando falta la clave hace
parecer que ECW nunca existió; entregar un COG donde pidieron un ECW es entregar un archivo
que nadie pidió.

Por eso la matriz tiene **tres** estados y no dos:

| Estado | Significa | Qué muestra |
| --- | --- | --- |
| `disponible` | funciona ahora | el motor y su versión |
| `instalable` | funcionaría con algo | **qué falta** y qué sirve mientras tanto |
| `no-soportado` | nadie sabe hacerlo | nada más que decir |

---

## Las capas

```
apps/formats    ¿qué es este archivo?      catálogo · firmas · CRS · acompañantes
      ↓
apps/targets    ¿dónde va a abrir?         perfiles de destino · veredictos
      ↓
apps/engines    ¿puedo hacerlo aquí?       contrato · registro · sondas · matriz
      ↓
apps/jobs       hazlo y demuéstralo        trabajo · runner · despachador · bitácora
      ↓
apps/{raster,pointcloud,vector,mesh}       los motores de cada familia
```

`apps/formats` no importa Django y no sabe nada de motores: es dominio puro, igual que
`packages/bim-core` en AeroBim. Se puede usar desde un script sin levantar nada.

`apps/pointcloud`, `apps/vector` y `apps/mesh` están **vacías a propósito** desde la fase 0
— solo `apps.py` y un `motores.py` que registra cero motores. Así la fase que las llene no
toca `INSTALLED_APPS`, y existe desde el primer día una prueba de que el registro tolera una
familia sin motores. Un registro que revienta con una lista vacía se descubre el día que se
añade la familia, con prisa.

## El registro es explícito

Cada familia llama a `registrar()` desde el `ready()` de su `AppConfig`. Nada de escanear
módulos buscando subclases: los efectos secundarios de import rompen `makemigrations
--check` de formas que cuestan una tarde entera de encontrar.

## Detección: del más barato al más caro

`inspeccionar()` lee 64 KiB y **no abre la imagen**.

1. **Por firma** — microsegundos. Es lo único que distingue un BigTIFF de un TIFF clásico,
   que comparten extensión y son formatos distintos para quien los abre.
2. **Por extensión** — solo cuando la firma calla: ASC, XYZ y DEM son texto plano. La
   confianza baja a `extension`, y eso se muestra.
3. **Por GDAL** — autoritativo y **opcional**: su ausencia baja la confianza, nunca hace
   fallar la inspección.

Una discrepancia entre firma y extensión no es un error: **gana la firma** y se avisa. Un
`.tif` que por dentro es un JP2 renombrado existe y pasa.

### Por qué hay un lector de TIFF propio si GDAL ya sabe leer TIFF

Porque **GDAL no distingue lo que aquí importa**. `gdalinfo` dice `Driver: GTiff` tanto para
un TIFF clásico como para un BigTIFF — son el mismo controlador. Pero uno abre en Civil 3D y
el otro no, y ese es exactamente el diagnóstico que la aplicación existe para dar. Hay que
leer el byte de versión.

Además es barato y funciona sin GDAL, que es lo que permite que la ficha del archivo aparezca
mientras la persona todavía está soltando el ratón.

## El CRS no se adivina

Regla heredada de `AeroBim/docs/NUBES_DE_PUNTOS.md`. Con una distinción que la hace usable:

- **Se detiene** si el trabajo reproyecta o si el destino exige CRS incrustado.
- **Es solo un aviso** si no hay reproyección y el destino tampoco lo exige. Convertir un
  TIFF sin georreferencia a un COG sin georreferencia es legítimo, y negarlo convertiría la
  herramienta en un estorbo.

`Crs` guarda su **procedencia** (`incrustado`, `sidecar-prj`, `declarado`, `desconocido`):
no es lo mismo un EPSG que venía en el archivo que uno que alguien tecleó a las siete de la
tarde. Y `PuntoConCrs` existe para que **ninguna función acepte un `(x, y)` pelado**.

## Los dos modos

Un solo código, dos políticas de entrada y salida. `AEROCONVERT_MODO` se lee en `base.py`.

| | `taller` | `nube` |
| --- | --- | --- |
| Entrada | ruta del disco; **el archivo no se copia** | subida con tope |
| Salida | junto al origen | almacén con caducidad |
| Raíces permitidas | obligatorias | no aplica |
| Login | obligatorio | obligatorio |

El login se exige también en taller. En ese modo la ruta de origen es un primitivo de
lectura del disco, así que la puerta importa **más**, no menos.

## Invariantes del trabajo (fase F1.2)

- **El original no se toca.** Se abre en solo lectura y se comprueba su `sha256` y su fecha
  antes y después de **cada camino de fallo**, no solo del feliz.
- **Escritura atómica.** Se escribe `<destino>.parcial` y solo tras verificar se hace
  `os.replace()`. Nunca queda un archivo a medias que parece válido.
- **Reintentar crea una fila nueva** con `retry_of`, no un contador que borra la historia.
- **La bitácora es de solo anexar.** Una bitácora que se puede editar no es una bitácora.
