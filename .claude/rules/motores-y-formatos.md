---
paths:
  - "apps/engines/**"
  - "apps/raster/**"
  - "apps/vector/**"
  - "apps/pointcloud/**"
  - "apps/gnss/**"
  - "apps/formats/**"
  - "apps/jobs/**"
  - "apps/documents/ocr.py"
  - "apps/documents/office.py"
  - "apps/documents/tarea.py"
---

# Motores, formatos y trabajos

Las cinco reglas de `AGENTS.md`, en la forma en que se rompen:

1. **El código de salida no es la prueba.** ODA devuelve `0` sin convertir; GDAL deja un archivo
   vacío con `0`. Comprueba que la salida **exista y verifique**. Nada de `returncode == 0` solo.
2. **Oráculo externo, no tu propia lectura.** Ráster: `gdalinfo -json -stats` y `gdalcompare`.
   Nubes: `pdal info --summary`. Vectorial: `ogrinfo`. Si no hay oráculo posible (ECW), se dice y se
   documenta el procedimiento manual con cifras fechadas en `docs/PRUEBAS_CON_ORACULO.md`. Las
   pruebas con oráculo llevan `@pytest.mark.oraculo` y el gate sigue verde sin GDAL.
3. **El CRS no se adivina.** Se detiene si el trabajo reproyecta o el destino exige CRS incrustado;
   es aviso si no. Sin valor por omisión ni «el más probable». Ninguna función acepta un `(x, y)`
   pelado: usa `PuntoConCrs`.
4. **Capacidad ausente = apagada con motivo y alternativa**, nunca oculta ni sustituida. El motivo
   lleva código estable en kebab-case en `apps/jobs/motivos.py` y el test del catálogo lo cierra.
5. **El original no se toca.** Se abre en solo lectura; un test compara `sha256` y `mtime` antes y
   después de **cada camino de fallo**. La salida va a `<destino>.parcial` y solo se renombra con
   `os.replace()` tras verificarla.

Además:

- **Una sonda no ejecuta una conversión** y, a ser posible, no lanza el programa.
- **Que el controlador esté no significa que sepa escribir** (ECW lee siempre; escribir pide SDK y
  clave OEM). Mira las banderas de capacidad, no solo la presencia.
- **No mezcles el GDAL de una instalación con el `proj` de otra** (`proj-descolocado`).
- **GDAL, PDAL, ECW y ODA no son dependencias del paquete:** se sondean en tiempo de ejecución.
- **Todo subproceso:** lista de argumentos, nunca `shell=True`, con tiempo máximo y sin pasar nada del
  usuario por una línea de órdenes. Una contraseña no queda en ninguna fila de la base ni en un log.
- **Unidades en el nombre:** `gsd_cm`, `pixel_size_m`, `bytes_totales`, `timeout_s`.
- Antes de dar algo por hecho: `/verificar pruebas apps/<área>` y, si toca un motor, `/oraculo`.
