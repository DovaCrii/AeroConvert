---
name: nuevo-motor
description: Añade un motor o un formato geoespacial a AeroConvert (ráster, nube, vector, GNSS) con todas sus piezas - clase del motor, catálogo, sonda, motivo con su paso de instalación, oráculo externo y original intacto. Úsala antes de escribir un motor nuevo o al revisar uno.
argument-hint: "<familia y formato, p. ej. vector/geoparquet>"
---

# Añadir el motor `$ARGUMENTS`

Un motor **no es una dependencia del paquete**: GDAL, PDAL, RTKLIB, ODA o lo que sea se **sondean** en tiempo
de ejecución y se ejecutan aparte. Lea `.claude/rules/motores-y-formatos.md` antes de empezar: las cinco
reglas de `AGENTS.md` se rompen justo aquí.

## 0. Antes de escribir

- ¿Qué **otro lector** comprueba la salida? (`gdalinfo -json`, `ogrinfo -json -features`, `pdal info --summary`,
  `pdal`/`rnx2rtkp` sobre un caso sintético.) Sin oráculo posible, la fila queda ⚠ con su procedimiento
  manual en `docs/PRUEBAS_CON_ORACULO.md`.
- ¿Depende de un programa de fuera, de una versión mínima o de un controlador que **lee pero no escribe**
  (ECW)? Mire las banderas de capacidad, no solo la presencia.
- ¿Licencia? GPL y AGPL **solo como programa externo** sondeado (`AGENTS.md`).
- Datos de prueba **sintéticos y de resultado conocido**; nunca datos reales en el repositorio.

## 1. Las piezas, en este orden

1. **El motor**: clase en `apps/<familia>/motores.py` (`raster`, `pointcloud`, `vector`, `gnss`, `mesh`). El
   subproceso con **lista de argumentos, sin shell, con plazo**; opciones que **declara el motor** (el perfil las
   toma de ahí). **El código de salida no es la prueba**: se comprueba que la salida exista y se lea.
2. **El catálogo**: el formato y sus pares en `apps/formats/catalogo.py` (código, extensiones, familia) y, si
   tiene apodos de búsqueda, en `APODOS` de `apps/dashboard/acciones.py`.
3. **La sonda**: en `apps/engines/sondas.py` (no ejecuta una conversión). Apagado con **motivo de código estable**
   y alternativa, nunca oculto ni sustituido en silencio (regla 4).
4. **El motivo**: en `apps/jobs/motivos.py` (kebab-case) y, si es `sin-…`, su **paso de instalación** en
   `apps/engines/equipo.py` (`test_equipo.py` lo exige). Un test cierra el catálogo.
5. **El CRS no se adivina** (regla 3): vacío y con reproyección, se detiene y se pregunta; sin valor por
   omisión. Nada acepta un `(x, y)` pelado: use `PuntoConCrs`.
6. **El original no se toca** (regla 5): solo lectura, salida a `<destino>.parcial` y `os.replace` tras
   verificar; un test compara `sha256` y `mtime` **en cada camino de fallo**.
7. **Perfiles de destino**: si algún programa (`apps/targets/perfiles.py`) debe recibirlo, su destino por
   familia.
8. **Pruebas**: el motor sin el programa (el CI no tiene GDAL ni PDAL: variables vacías), **el caso apagado y
   el encendido forzados con `monkeypatch`**, y las `@pytest.mark.oraculo` contra GDAL o PDAL de verdad
   (QGIS en `C:\Program Files\QGIS 4.0.2\bin`). Archivos de prueba con `newline="\n"`.
9. **Documentos**: fila con fecha en `MASTER_PLAN.md`, `CHANGELOG.md`, cifras en
   `docs/PRUEBAS_CON_ORACULO.md`, `docs/FORMATOS.md` si cambia lo soportado.

## 2. Al terminar

`/verificar rapido`, la suite completa en segundo plano y `/oraculo apps/<familia>`; para publicar,
`/publicar`.

## Trampas que ya costaron

- «El GDAL de una instalación con el `proj` de otra» (`proj-descolocado`).
- Que el controlador esté **no significa que sepa escribir**.
- Un motor que se apoya en `returncode == 0` está mal escrito.
- Una ruta de Windows que `os.path.basename` no parte en Linux: parta por `\` y `/`.
