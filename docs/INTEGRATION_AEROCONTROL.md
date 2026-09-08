# Integración con AeroControl

**Por archivo o por API, nunca por base de datos compartida.**

---

## Dónde se tocan

AeroControl gestiona los planes de vuelo geoespaciales: importa y versiona KMZ/KML, los
edita en un mapa y produce la hoja de campo para transcribir a SIGO.

| AeroControl necesita | AeroConvert entrega |
| --- | --- |
| **KMZ / KML** de un polígono o una ruta | Desde SHP, GeoJSON, GPKG, DXF o un archivo de puntos — fase F3 |
| Un plan que llegó en **DWG** o **SHP** | Convertido a KMZ, en EPSG:4326 |

Y en sentido contrario:

| AeroControl produce | AeroConvert convierte a |
| --- | --- |
| KMZ del plan aprobado | SHP o GPKG para el SIG del cliente, DXF para el proyectista |

## Lo que se reutiliza

**`apps/geo/kml/parse.py`** — el parser KML/KMZ de AeroControl, endurecido con `lxml`
(`lxml>=6.1` está declarado explícitamente en su `pyproject.toml` justo por esto). Tiene
pruebas contra anillos de Trimble, círculo envolvente y ubicación administrativa.

No se reescribe. Cuando llegue la fase F3, se porta con sus pruebas.

## La trampa de KML, que hay que respetar

**KML es siempre EPSG:4326, y longitud antes que latitud.** Convertir un SHP en UTM 19S a
KML sin reproyectar produce un archivo sintácticamente válido que coloca la obra en mitad
del Atlántico, cerca de la isla Nula. Es el fallo silencioso clásico.

Por eso el perfil `google-earth` fija `reproyectar_a: EPSG:4326` y no lo deja a criterio de
nadie, y por eso un origen sin CRS **detiene** la conversión en vez de avisar: aquí sí hay
reproyección, y sin saber de dónde se parte no se puede reproyectar.

## Archivos de puntos: el dolor semanal

`AeroControl` no los maneja, pero la oficina sí, todo el tiempo. Un archivo de puntos de
control se ve así:

```
P1,7318729.036,495279.406,3042.641,pr
```

Es **PNEZD** —Punto, Norte, Este, Cota, Descripción—, el formato nativo de Civil 3D. Pero el
orden de columnas cambia entre equipos y entre oficinas, y **PNEZD leído como PENZD deja el
punto a 6,8 millones de metros de donde va, en silencio**.

Por eso la fase F3 no se limita a convertir: **muestra los puntos sobre un mapa antes de
convertir**. Si aparecen en el Pacífico, el orden está mal, y se ve de un vistazo.
