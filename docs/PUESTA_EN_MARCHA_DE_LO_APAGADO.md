# Poner en marcha lo que hoy sale apagado

La pantalla «Qué se puede convertir en este equipo» (`/compatibilidad/`) y `/motores/` dicen qué falta
y por qué. Esto es lo que hay que hacer con cada cosa, **quién lo hace** y cómo se comprueba. Regla 4
de `AGENTS.md`: mientras falte, sigue apagada con su motivo y su alternativa; nada se sustituye en
silencio. Estado y pedidos en `docs/planes/SEGUIMIENTO.md` (bloque B11).

| Apagado | Motivo (código) | Qué falta | Quién | Cómo se comprueba |
| --- | --- | --- | --- | --- |
| **DWG/DXF** (`oda-cad`, 12 conversiones) | `sin-conversor` | ODA File Converter (gratuito, exige registro en el Open Design Alliance). En Linux corre bajo `xvfb-run`. | **Persona** (P7): descarga e instala; Claude deja el paso en `SERVIDOR.md` | `AEROCONVERT_ODA_CONVERTER=<ruta>` en el `.env`; `/motores/` la muestra lista |
| **Trimble T02/T04 a RINEX** (`trimble-rinex`) | `sin-conversor-trimble` (`sin-wine` en Linux) | `ConvertToRinex.exe` de Trimble (licencia propia). En Windows basta apuntarlo; en Linux hace falta Wine con su prefijo (F10.5) | **Persona** (P10) | `AEROCONVERT_TRIMBLE_RINEX`, y en Linux `AEROCONVERT_WINEPREFIX`; convertir los T02/T04 reales de OneDrive |
| **ECW, lectura** (`gdal-leer-ecw`, 8 conversiones) | `sin-driver-ecw` | GDAL con el controlador ECW. En Windows: `winget install GISInternals.GDAL.ECW`; la compilación de QGIS y la de conda-forge no lo traen | **Persona** instala; sin código nuestro | `gdalinfo --formats` lista ECW; `/motores/` en verde |
| **ECW, escritura** (`gdal-ecw`, 10 conversiones) | `sin-driver-ecw` · `sin-clave-ecw` | El controlador **con capacidad de escritura** y la clave OEM de Hexagon (`AEROCONVERT_ECW_ENCODE_KEY` y `…_COMPANY`) | **Persona** (la clave es suya y nunca entra al repositorio) | Sin oráculo posible: procedimiento manual con cifras en `docs/PRUEBAS_CON_ORACULO.md`. Mientras tanto sirven COG y JP2 |
| **MrSID** (`gdal-leer-mrsid`, 8) | `sin-driver-mrsid` | GDAL compilado con el SDK de LizardTech | **Persona**, solo si usan MrSID | Opcional: si nadie lo pide, se queda apagado con COG/JP2 como alternativa |
| **ReCap RCP/RCS** (`recap`, 8) | `formato-propietario` | Nada que instalar: Autodesk no publica lector. Se abre en ReCap Pro y se exporta a E57 o LAS | Nadie: **apagado por diseño**, con su alternativa | La pantalla ya dice cómo exportar |
| **Word, Excel y PowerPoint a PDF; PDF a Word** | `sin-office` | Microsoft Office en el equipo que ejecuta (hoy solo la estación Windows) | **Persona**, o ver F17.1 | `/compatibilidad/` |
| **Catálogos de tubería (Access)** | `sin-access` | El conector de bases de datos de Microsoft (solo Windows) | **Persona**, o ver F17.2 | `/compatibilidad/` |

## Lo que sí puede hacer Claude (filas nuevas)

- **F17.1 · Office a PDF con LibreOffice**, como opción **rotulada** («puede variar respecto del original»)
  y nunca en lugar de Office: LibreOffice es un programa externo (MPL), se sondea y se ejecuta aparte
  (D1). Así `p340` deja de tener cuatro herramientas apagadas. Oráculo: PDFium cuenta páginas y busca
  el texto conocido del documento de partida.
- **F17.2 · Leer catálogos `.accdb`/`.mdb` sin Access** con `mdbtools` (programa externo, sondeado).
  Oráculo: las nueve tablas con su número de filas, contadas por otro lector (`pyodbc` en la
  estación, que sí tiene Access). Escribir `.accdb` sigue pidiendo Windows.
- **F17.3 · Una pantalla de «cómo dejar listo el equipo»** que, para cada apagado, muestre el paso
  exacto de esta tabla y verifique la sonda en vivo (hoy cada tarjeta dice qué falta, pero no los pasos).
- **F17.4 · Un guion `despliegue/instalar_faltantes.sh`** que instale por `apt` lo que sí es
  instalable sin registro (FFmpeg, Ghostscript, Inkscape, mdbtools, LibreOffice, `xvfb`), con
  `shellcheck` en el CI y sin tocar nada que pida licencia.

Todo lo que dice «Persona» está en la tabla «Pedidos a la persona» con qué pasa si no llega.
