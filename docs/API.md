# La API de conversión (v1)

Para encolar conversiones desde un guion o desde otra aplicación (AeroBim, F16.5) sin pasar por la
pantalla. **Las reglas son las mismas que en la pantalla de convertir**: la ruta tiene que estar en
las carpetas permitidas, el formato lo detecta el inspector, las opciones las valida el motor y el
sistema de coordenadas **no se adivina**.

## Acceso

1. Un administrador da a la persona el permiso **`jobs.usar_api`** («Puede convertir por la API»).
2. Se emite su token, que **se muestra una sola vez** (en la base solo queda su huella SHA-256):

   ```bash
   sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py emitir_token_api ana --nombre "entregas"
   sudo -u aeroconvert /opt/aeroconvert/.venv/bin/python manage.py emitir_token_api --revocar <prefijo>
   ```

3. Cada petición lleva `Authorization: Bearer ac_<prefijo>_<secreto>`. Sin token, o con uno que no
   vale o está revocado: **401**. Con token y sin el permiso: **403**. Lo de otra persona: **404**.

## Extremos

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `POST` | `/api/v1/trabajos/` | Encola. Cuerpo JSON: `ruta` (en las carpetas permitidas), `formato` (código del catálogo: `cog`, `laz`, `dxf`…) **o** `perfil` (`civil3d`, `qgis`…), `opciones` (las del motor) y, si el archivo no trae sistema, `crs_declarado` (`EPSG:32719`) o, solo en nubes de puntos, `crs_local: true` (coordenadas locales, sin sistema). Contesta **201** con el trabajo. |
| `GET` | `/api/v1/trabajos/` | Los últimos 50 trabajos de quien pregunta. |
| `GET` | `/api/v1/trabajos/<id>/` | Estado (`queued`, `running`, `done`, `error`…), avance, motivo con su código estable y la verificación. Con `done`, trae `descarga`. |
| `GET` | `/api/v1/trabajos/<id>/descarga/` | La salida, con las reglas de la pantalla: **409** si aún no está hecha; **410** si se fue (la retención se la llevó, desapareció, o alguien la reemplazó después de verificarla). Con retención efímera, entregada entera se borra. |
| `GET` | `/api/v1/capacidades/` | Qué conversiones sabe hacer esta instalación. |

Cada token rechazado deja una línea en el registro `aeroconvert.api` con su prefijo y la IP (nunca
el token). Los tokens no caducan: se revocan con la orden de arriba.

Los errores vienen como `{"error": "...", "codigo": "..."}`; el código es el de
`apps/jobs/motivos.py` (no cambia aunque cambie el mensaje).

## Ejemplo

```python
import requests, time
base, cabecera = "https://aeroconvert.ejemplo", {"Authorization": "Bearer ac_..."}
t = requests.post(f"{base}/api/v1/trabajos/", headers=cabecera,
                  json={"ruta": "/mnt/entregas/orto.tif", "perfil": "civil3d"}).json()
while (t := requests.get(f"{base}/api/v1/trabajos/{t['id']}/", headers=cabecera).json())["estado"] in ("queued", "running"):
    time.sleep(5)
open("orto_civil3d.tif", "wb").write(requests.get(t["descarga"], headers=cabecera).content)
```
