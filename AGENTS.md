# AGENTS.md — cómo se trabaja en AeroConvert

Este archivo manda. Si algo aquí contradice a otro documento, gana esto.

**Precedencia documental:** `AGENTS.md` > `MASTER_PLAN.md` > `docs/ARCHITECTURE.md` >
`docs/MVP.md` > `docs/MOTORES.md` > `docs/FORMATOS.md` > `README.md`.

**Antes de tocar nada, lee [HANDOFF.md](HANDOFF.md).** Dice el punto exacto de retome.

---

## Las cinco reglas que definen este proyecto

### 1. El código de salida del motor no es la prueba de que funcionó

ODA File Converter devuelve `0` aunque no convierta nada. GDAL devuelve `0` tras dejar un
archivo vacío si el controlador falló al cerrar. **Lo que se comprueba es que la salida
exista y verifique.** Cualquier motor que se apoye en `returncode == 0` está mal escrito.

### 2. Un test que compara nuestra salida con nuestra propia lectura no prueba nada

Cada capacidad necesita un **oráculo externo**:

| Familia | Oráculo |
| --- | --- |
| Ráster | `gdalinfo -json -stats` y `python -m osgeo_utils.gdalcompare` |
| Nubes de puntos | `pdal info --summary`, y CloudCompare para la aceptación manual |
| Vectorial | `ogrinfo` |
| Contraste de color | la fórmula WCAG 2.1 leída del CSS, no un número copiado |

Si no hay oráculo posible —ECW, porque exige la clave OEM— **se dice y se documenta el
procedimiento manual con cifras fechadas** en `docs/PRUEBAS_CON_ORACULO.md`. No se
sustituye por una aserción reflexiva que da verde.

### 3. El CRS no se adivina

Regla heredada de `AeroBim/docs/NUBES_DE_PUNTOS.md`: *si viene vacío, la conversión para y
se le pregunta al topógrafo; adivinarlo es peor que no tenerlo*. Con una distinción:

- **Se detiene** si el trabajo reproyecta o si el destino exige CRS incrustado.
- **Es solo un aviso** si no hay reproyección y el destino tampoco lo exige.

Cuando se detiene, el campo no lleva valor por omisión ni sugerencia de «el más probable».
La declaración queda en la bitácora con su actor.

Y en los tipos: **ninguna función acepta un `(x, y)` pelado.** Existe `PuntoConCrs`.

### 4. Una capacidad ausente se muestra apagada, con motivo y alternativa

Nunca se oculta y nunca se sustituye en silencio. Ocultar ECW cuando falta la clave hace
parecer que ECW nunca existió; entregar un COG donde pidieron un ECW es entregar un archivo
que nadie pidió. Los motivos llevan **código estable en kebab-case** (`sin-clave-ecw`,
`crs-ausente`, `salida-bloqueada`) además del mensaje traducible: el mensaje cambia, el
código no. Están en `apps/jobs/motivos.py` y hay un test que cierra el catálogo.

### 5. El original no se toca

Se abre en solo lectura. Un test compara `sha256` y `mtime` antes y después de **cada
camino de fallo**, no solo del feliz. La salida se escribe como `<destino>.parcial` y solo
se renombra con `os.replace()` tras verificarla.

---

## Convenciones

**Idioma.** Documentación y comentarios en **español**, neutral, sin voseo, trato de usted.
Los `msgid` de gettext se escriben en **inglés** y el español vive en `locale/es/`; hay un
test que falla con una sola tilde en un literal fuente. Texto de interfaz en *sentence
case*; las siglas se mantienen (ECW, COG, LAZ, IFC, CRS, GSD, EPSG).

**Unidades en el nombre.** `gsd_cm`, `pixel_size_m`, `bytes_totales`, `timeout_s`. SI
internamente.

**Ramas.** `codex/<área-o-fase>`. No `feat/` ni `fix/`. Nunca commit ni push directo a
`main`. **Nunca fusionar un PR sin permiso explícito** — «dale» significa implementar y
empujar, no fusionar.

**Commits.** Español, imperativo, con ámbito: `feat(raster): …`, `fix(formats): …`,
`docs: …`. Un PR por fase; no mezclar fases en un commit.

**Al cerrar una fase.** Fila ✅ en `MASTER_PLAN.md`, entrada en `CHANGELOG.md`
(Keep a Changelog 1.1.0 es-ES + SemVer) y `HANDOFF.md` actualizado.

**Permisos.** Toda vista de lectura exige su permiso explícito. **Prueba de 403 por vista
nueva.** Nunca `fields = "__all__"`.

**Front.** Bootstrap y htmx vendorizados en `static/vendor/` con SRI. CSP `'self'`, cero
CDN, sin `'unsafe-inline'` en `script-src`.

**Nada se esconde en hover.** El patrón `opacity-0 group-hover:opacity-100` está prohibido
en toda la familia: no existe para teclado ni para táctil.

**Color nunca solo.** Severidad = color **+** forma de icono distinta **+** texto.

---

## La puerta de calidad

```powershell
pwsh scripts/verify.ps1
```

Corre `manage.py check`, `check --deploy`, `makemigrations --check`, `pytest --cov` con
`fail_under = 83`, `ruff check`, **`ruff format --check`** (olvidar el segundo dejó el CI de
AeroControl rojo durante días), `bandit` y `pip-audit`.

**El gate tiene que ser verde en una máquina sin GDAL.** Por eso las pruebas con oráculo
llevan `@pytest.mark.oraculo` y quedan deseleccionadas en `pytest.ini`.

`fail_under = 83` es un piso, no un objetivo. Nunca se baja para que pase una corrida roja.
Y **ningún módulo lleva `# pragma: no cover` entero**: así es como el número deja de
significar algo.

---

## Dependencias y licencias

**GDAL, PDAL, el SDK de ECW y ODA File Converter no son dependencias del paquete.** Son
herramientas externas que se sondean en tiempo de ejecución. Declararlas obligaría a
tenerlas para correr `pytest`.

Antes de portar código de otro proyecto, la tabla de siempre:

| Licencia | Qué se puede |
| --- | --- |
| MIT · BSD · Apache-2.0 | portar código |
| LGPL | enlazar como librería, **nunca copiar** (`ifcopenshell` está aquí) |
| GPL · AGPL | solo referencia conceptual — **LibreDWG es GPL-3 y contagiaría el proyecto entero** |

Este repositorio es MIT y debe seguir siéndolo.

**Los datos reales quedan fuera del repositorio**: ortofotos, nubes, DEM, entregables de
cliente y cualquier clave de SDK.

---

## Los repos hermanos son de solo lectura

`AeroBim`, `AeroControl`, `AeroPlanner` y `AeroLink` se leen para aprender el patrón, no se
modifican desde aquí. La comunicación es **por archivo o por API, nunca por base de datos
compartida**.

Referencias que conviene tener abiertas:

| Archivo | Para qué |
| --- | --- |
| `AeroBim/services/api/apps/documents/conversion.py` | el patrón entero de motor opcional |
| `AeroControl/config/settings/base.py` | plantilla de ajustes, SQLite en WAL |
| `AeroControl/scripts/verify.ps1` | el gate que aquí se copia |
| `AeroBim/apps/web/scripts/a-copc.py` | el motor de la fase F2, ya medido |
| `AeroControl/apps/geo/kml/parse.py` | parser KML endurecido para la fase F3 |
