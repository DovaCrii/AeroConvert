<div align="center">

<img src="assets/aeroconvert-mark.svg" width="140" height="105" alt="Logo de AeroConvert" />

# AeroConvert

**Conversor de formatos geoespaciales que te dice, además, por qué tu archivo no abre donde debería.**

[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-F15BB5.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-1B2A4A.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-6.1-1B2A4A.svg)](https://www.djangoproject.com/)
[![Estado](https://img.shields.io/badge/estado-v0.3.0--alpha-F15BB5.svg)](#estado-actual)

Aplicaciones hermanas: **[AeroBim](https://github.com/DovaCrii/AeroBim)** (visor y coordinación BIM) · **[AeroControl](https://github.com/DovaCrii/AeroControl)** (operaciones RPA) · **[AeroPlanner](https://github.com/DovaCrii/AeroPlanner)** (planificación de misiones) · **[AeroLink](https://github.com/DovaCrii/AeroLink)** (telemetría y evidencia) — funcionan por separado, se comunican cuando conviene

</div>

---

## Qué es

AeroConvert convierte ortofotos, nubes de puntos, cartografía y modelos entre formatos, y
corre **local**: la ortofoto del cliente no sale del disco.

Pero lo que lo separa de un conversor cualquiera es que **invierte la pregunta**. Todas las
herramientas del rubro —FME, Global Mapper, MyGeodata— parten de que ya sabes a qué formato
quieres ir. AeroConvert parte de dónde tiene que abrir el archivo:

```
        ┌─ sueltas el archivo ─┐
        │                      │
   qué tiene dentro      dónde abre y dónde no
   BigTIFF · LZW · 4 bandas    Civil 3D  ✗  es BigTIFF
   14.526 × 14.443 px          QGIS      ✓
   EPSG:32719 · 2,56 cm/px     ArcGIS    ✓
        │                      │
        └──── eliges destino ──┘
              Civil 3D → él elige formato y opciones
```

**Para quién.** Topografía, fotogrametría e ingeniería, donde el entregable tiene que abrir
en el computador de otro y hoy nadie te dice por qué no lo hace.

## El caso que lo originó

Una ortofoto de Metashape de un cruce minero abría en el equipo de quien la generó y no en
el de al lado. El archivo no estaba dañado ni le faltaba georreferencia:

| | |
| --- | --- |
| Variante TIFF | **BigTIFF** (marca de versión `43`, no `42`) |
| Dimensiones | 14.526 × 14.443 px · 209,8 Mpx · 4 bandas RGB+alfa |
| CRS | EPSG:32719 — incrustado, correcto |
| Sin comprimir | 0,84 GB |

**Era BigTIFF, y AutoCAD Civil 3D no lee BigTIFF** aunque comparta la extensión `.tif`. Y
no hacía falta: BigTIFF existe para pasar el techo de 4 GB, y esta imagen ocupa 0,84 GB sin
comprimir. Se escribió así porque la casilla estaba marcada.

Reescrito como TIFF clásico de tres bandas, con las mismas estadísticas por banda al décimo
decimal —verificado con `gdalinfo`—, abre en cualquier puesto.

## Qué resuelve

| Familia | Formatos |
| --- | --- |
| **Ráster** | GeoTIFF, **BigTIFF**, COG, JPEG 2000, ECW, MrSID (lectura), ERDAS IMAGINE, ASCII Grid, DEM, BIL/BIP/BSQ, PNG/JPEG/WebP con world file, NITF, netCDF, Zarr, MBTiles, VRT |
| **Nubes de puntos** | LAS, LAZ, **COPC**, E57, PLY, PCD, XYZ, 3D Tiles |
| **Vectorial, CAD y topografía** | SHP, GeoPackage, GeoJSON, KML/KMZ, GML, GPX, DXF, DWG y DGN (vía ODA), **archivos de puntos PNEZD/PENZD**, LandXML |
| **BIM y malla** | IFC, OBJ, glTF/GLB, 3D Tiles, STL, Collada |

Y sobre cada archivo: la **ficha** de lo que tiene dentro —leída de la cabecera, sin abrir
la imagen— y la **tira de veredictos** por programa de destino.

### Sobre ECW

Escribir ECW exige una clave OEM de pago de Hexagon; GDAL solo lee. AeroConvert lo trata
como **motor opcional**: si la clave está, ECW es un destino más; si no, la celda aparece
apagada **con su motivo escrito** y propone COG o JPEG 2000. Nunca se oculta la capacidad
ni se sustituye el formato en silencio.

Para el caso corriente —resolución intacta, georreferencia intacta, archivo pequeño, abre
en el equipo del cliente— **JPEG 2000 es el sustituto libre**: lo escribe GDAL sin licencia,
lleva la georreferencia dentro (cajas GeoJP2 y GMLJP2, sin `.j2w`), y Civil 3D con Raster
Design lo lee.

## Aplicaciones hermanas

```
   AeroPlanner        AeroControl        AeroLink         AeroBim        AeroConvert
   planifica     ←→   flota y          ←  telemetría   →  visor BIM  ←→  el formato
   la misión          cumplimiento        del vuelo        y nubes        que abre allá
```

AeroConvert es el que **traduce entre todas y hacia afuera**: entrega el COG que lee
AeroBim, el COPC de un levantamiento, el KMZ que se sube a un permiso, y el TIFF que abre
en el Civil 3D del cliente.

Las cinco comparten la marca —el mismo dron, un motivo distinto por aplicación— y nada
más: **ninguna comparte base de datos con otra**. Se comunican por archivo o por API.

## Estado actual

**`v0.3.0-alpha`** — ráster y nubes de puntos de punta a punta, con interfaz.
**394 pruebas**, 92 % de cobertura, verdes **sin GDAL ni PDAL instalados**, y el CI de
GitHub Actions en verde.

Sobre los entregables reales de un vuelo de BHP:

| Entrada | Destino | Tiempo | Salida | Verificado |
| --- | --- | ---: | ---: | --- |
| Ortofoto 466,2 MB **BigTIFF** | Civil 3D → GeoTIFF clásico | 7 s | 285 MB | `gdalinfo` |
| La misma | Entrega → JPEG 2000 | 9 s | 60 MB | `gdalinfo` |
| Nube 278,9 MB **LAS 1.2** | AeroBim → COPC | 50 s | 76,4 MB, 9.618.692 puntos intactos | `pdal info` |

Y en los tres el veredicto se invierte, que es de lo que trata el producto: la entrada dice
«no abre, y por esto» y la salida dice «abre tal cual».

Lo que **funciona hoy**:

- **La mesa.** Se pega una ruta y aparece, sin abrir el archivo, qué hay dentro y la tira de
  veredictos por programa. Se elige el destino y convierte.
- **Lectores propios de cabecera TIFF/BigTIFF y LAS/LAZ/COPC**, sin GDAL ni PDAL.
  Contrastados contra `gdalinfo` y `pdal info` sobre archivos de obra: **coinciden
  exactamente**. Distinguen lo que las herramientas no distinguen — un BigTIFF de un TIFF
  clásico, un COPC de un LAZ corriente — que es justo de lo que dependen los veredictos.
- **Motor ráster GDAL** entre GeoTIFF, BigTIFF, COG, JPEG 2000, IMG y ASCII Grid.
- **Motor de nubes PDAL**: LAS, LAZ y COPC, con diezmado por separación y reproyección.
- **Preajustes** con nombre propio y **modo experto generado desde lo que el motor declara**,
  así que no puede ofrecer un ajuste que el motor vaya a ignorar.
- **Estimación previa**: cuánto va a pesar, cuánto va a tardar y si cabe, con ratios medidos.
- **El original nunca se toca**, la salida se escribe atómica, y se puede cancelar de verdad.
- **Retención y presupuesto de disco**: en modo nube nada se acumula, y un trabajo que no
  cabe espera en la cola en vez de llenar el volumen.

Lo que **todavía no**: vectorial/CAD y BIM (fases F3 y F4), 3D Tiles, y **ECW**, que necesita
una instalación con la SDK de Hexagon para poder probarse. **E57** tampoco: los controladores
de PDAL se fijan al compilarlo y el que trae QGIS no lo incluye — la matriz lo dice con su
motivo. **RCS y RCP de ReCap no se van a poder nunca**: son binarios cerrados sin lector
abierto, y la aplicación lo dice con el remedio escrito en vez de fingir que no los conoce.

El trabajo pendiente vive en dos documentos, no en este README:

- **[MASTER_PLAN.md](MASTER_PLAN.md)** — las fases, con criterio de cierre por ítem.
- **[HANDOFF.md](HANDOFF.md)** — el punto exacto de retome.

## Puesta en marcha

Requisitos: Python 3.12, PowerShell 7+, Git y [uv](https://docs.astral.sh/uv/).
GDAL es **opcional** para desarrollar y obligatorio para convertir — ver [INSTALL.md](INSTALL.md).

```powershell
git clone https://github.com/DovaCrii/AeroConvert.git
Set-Location AeroConvert
Copy-Item .env.example .env    # y edita AEROCONVERT_RAICES_PERMITIDAS
uv sync --all-groups
uv run python manage.py migrate
uv run python manage.py createsuperuser
pwsh scripts/run.ps1
```

`run.ps1` levanta el servidor en modo taller y abre el navegador cuando `/salud/` responde.

### Comandos frecuentes

```powershell
pwsh scripts/verify.ps1
```

```powershell
uv run pytest apps/formats -q
```

```powershell
pwsh scripts/sondear.ps1
```

`sondear.ps1` imprime qué motores ve esta máquina y por qué faltan los que faltan — es lo
primero que hay que mirar cuando una conversión no aparece disponible.

Las pruebas con oráculo externo quedan fuera del gate a propósito, para que corra verde en
una máquina limpia. Se lanzan aparte:

```powershell
uv run pytest -m oraculo
```

## Los dos modos

Un solo código, dos políticas. Se elige con `AEROCONVERT_MODO`.

| | `taller` | `nube` |
| --- | --- | --- |
| Entrada | una ruta del disco; **el archivo no se copia** | subida, con tope |
| Tamaño | sin límite | `AEROCONVERT_TOPE_MB` |
| Salida | junto al origen | almacén con caducidad |
| Login | obligatorio | obligatorio |

El login se exige también en taller. En ese modo la ruta de origen es un primitivo de
lectura del disco, así que la puerta importa **más**, no menos — y por eso
`AEROCONVERT_RAICES_PERMITIDAS` es obligatoria y `manage.py check` falla sin ella.

## Seguridad y datos

- CSP `'self'`; Bootstrap y htmx vendorizados con SRI, sin CDN.
- La clave OEM de ECW viaja **solo** en el entorno del proceso hijo, y hay una prueba con
  clave centinela que la busca en los registros, los eventos y el HTML.
- **El original nunca se toca**: se abre en solo lectura, y se comprueba su `sha256` y su
  fecha antes y después de cada camino de fallo, no solo del feliz.
- La salida se escribe como `.parcial` y solo se renombra tras verificarla: nunca queda un
  archivo a medias que parece válido.
- Los datos reales —ortofotos, nubes, entregables de cliente— viven fuera del repositorio.

## Licencia

MIT. Ver [LICENSE](LICENSE).
