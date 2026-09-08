# Referencias, con su licencia

Antes de portar código de cualquier proyecto, la tabla de siempre:

| Licencia | Qué se puede hacer |
| --- | --- |
| MIT · BSD · Apache-2.0 | Portar código, citando el origen |
| LGPL | **Enlazar** como librería. Nunca copiar código dentro |
| GPL · AGPL | Solo referencia conceptual. Copiar contagiaría el proyecto entero |

AeroConvert es MIT y debe seguir siéndolo.

---

## Herramientas externas que se sondean

| Proyecto | Licencia | Para qué | ¿Se distribuye con nosotros? |
| --- | --- | --- | --- |
| [GDAL](https://gdal.org/) | MIT | Ráster y vectorial. El caballo de tiro | No: herramienta externa |
| [PROJ](https://proj.org/) | MIT | Reproyección y base de datos EPSG | No |
| [PDAL](https://pdal.io/) | BSD-3 | Nubes de puntos (fase F2) | No |
| [OpenJPEG](https://www.openjpeg.org/) | BSD-2 | JPEG 2000. Va dentro de GDAL | No |
| ERDAS ECW/JP2 SDK (Hexagon) | **Comercial** | Escribir ECW | **No, y no se puede** |
| ODA File Converter | Gratuito, EULA propia | DWG y DGN → DXF | No: se instala aparte |
| LizardTech / Extensis MrSID SDK | **Comercial** | MrSID | No. Por eso MrSID es solo lectura |

## Bibliotecas de Python

| Paquete | Licencia | Para qué |
| --- | --- | --- |
| [Django](https://www.djangoproject.com/) | BSD-3 | El armazón |
| [Django REST framework](https://www.django-rest-framework.org/) | BSD-3 | La API de capacidades |
| [htmx](https://htmx.org/) | BSD-2 | Progreso sin escribir JavaScript |
| [Bootstrap](https://getbootstrap.com/) | MIT | La interfaz |
| [pyproj](https://pyproj4.github.io/pyproj/) | MIT | Validar un EPSG declarado, sin depender de GDAL |
| [django-axes](https://github.com/jazzband/django-axes) | MIT | Frenar el tanteo de contraseñas |
| [WhiteNoise](https://whitenoise.readthedocs.io/) | MIT | Servir estáticos |

`ifcopenshell` (**LGPL-3**) llegará en la fase F4: se enlaza, no se copia. Es el mismo
tratamiento que le da AeroBim.

## Las aplicaciones hermanas

Son de **solo lectura** desde aquí. Se leen para aprender el patrón, no se modifican.

| De dónde | Qué se toma |
| --- | --- |
| `AeroBim/services/api/apps/documents/conversion.py` | El patrón entero de motor opcional: sonda que no ejecuta, motivos con código estable, no creer al código de salida, y el conversor de mentira para probarlo sin el binario |
| `AeroBim/docs/FORMATOS.md` · `NUBES_DE_PUNTOS.md` | Las decisiones de licencia y de CRS ya tomadas. No se reabren |
| `AeroBim/apps/web/scripts/a-copc.py` | El motor de la fase F2, ya escrito y medido: lectura por trozos, octree y verificación posterior |
| `AeroBim/packages/bim-core/src/nubes/precision.ts` | El hallazgo de que `float32` pierde 200 mm en el norte UTM |
| `AeroControl/config/settings/base.py` | La plantilla de ajustes: SQLite en WAL con `busy_timeout`, CSP, DRF, registro |
| `AeroControl/scripts/verify.ps1` · `pyproject.toml` | El gate y los umbrales, copiados tal cual |
| `AeroControl/apps/core/jobs.py` | La contabilidad de trabajos y la lección del trabajo atascado |
| `AeroControl/apps/geo/kml/parse.py` | Parser KML/KMZ endurecido con lxml, para la fase F3 |
| `AeroBim/docs/DESIGN_SYSTEM.md` | La identidad que se hereda, y el oráculo de contraste |

## Documentos de especificación consultados

- [Especificación BigTIFF](https://www.awaresystems.be/imaging/tiff/bigtiff.html) — la
  diferencia de anchos de campo entre las dos variantes, que es donde se rompe todo.
- [OGC GeoTIFF 1.1](https://docs.ogc.org/is/19-008r4/19-008r4.html) — las geoclaves.
- [COPC 1.0](https://copc.io/) — para la fase F2.
- [Cloud Optimized GeoTIFF](https://cogeo.org/).
- [WCAG 2.1](https://www.w3.org/TR/WCAG21/) — la fórmula de contraste, implementada y
  probada, no copiada de una tabla.
