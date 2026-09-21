# El servidor Aero de la oficina

**Este documento es compartido por AeroControl, AeroConvert y AeroBim.** Las tres viven en la
misma máquina, así que cualquiera que vaya a tocarla debería leer esto antes, y actualizarlo
después.

Última revisión: **2026-09-14**.

---

## Qué es la máquina

Una VM de **Hyper-V** llamada `AeroControl-Prod` —el nombre se quedó del primer inquilino,
pero ya hospeda a las tres— sobre un anfitrión Windows.

| | |
| --- | --- |
| Anfitrión | `DSK0006CC210` · Intel **i7-10700** (8 núcleos, 16 hilos) · **48 GB** de RAM |
| Disco del anfitrión | un solo **NVMe Kingston SNV2S1000G**, 932 GB, SSD |
| Invitado | `p340` · **Ubuntu 26.04.1 LTS** (núcleo 7.0.0-31) |
| Red | LAN-External · `172.22.10.143` **por DHCP** · Tailscale `100.121.16.118` |

La dirección de la LAN **cambia sola**: era `.51` y hoy es `.143`. Como la puerta principal es
el nombre de Tailscale, que sí es estable, no rompe nada; pero conviene reservarla en el router
antes de que algo quede apuntando a la vieja.

### Lo que se cambió el 2026-09-14, y por qué

| Ajuste | Antes | Ahora | Motivo |
| --- | --- | --- | --- |
| Procesadores | 12 | **8** (`nproc` lo confirma dentro) | 12 dejaba solo 4 hilos al anfitrión. 8 le dejan la mitad de los 16 y dan margen a las tres aplicaciones a la vez. Subir de ahí no acelera nada: más vCPU de los que se usan solo cuesta planificación |
| Memoria | 8 GB | **24 GB** (el invitado ve 22 Gi) | Tres aplicaciones más PostgreSQL y MinIO. Sin memoria dinámica **a propósito**: con ella, un pico de PDAL puede quedarse sin servir y el núcleo mata el proceso |
| Disco virtual | 100 GB | **350 GB** (dinámico, ocupa 16) | Una nube de 20 GB necesita 40 para convertirse: el parcial y el definitivo conviven un instante |
| Volumen lógico | 96,9 GB | **342 GB**, 317 libres | El `.vhdx` mayor no toca ninguna de las cuatro capas de dentro: hubo que crecerlas a mano |
| Acción al detener | `Apagar` | **`Cerrar el sistema operativo invitado`** | `Apagar` es **corte de corriente**. Cada reinicio del anfitrión se lo hacía a PostgreSQL y a los SQLite en WAL |
| Ubicación | `C:\Users\ldigitales\Documents\...` | **`C:\VMs\AeroControl-Prod\`** | Estaba en un perfil de usuario, con OneDrive corriendo en la máquina. Hoy `Documents` no está redirigido, pero basta con que se active la copia de carpetas conocidas para que empiece a sincronizar un `.vhdx` de decenas de gigabytes |
| Antivirus | sin exclusión | **`C:\VMs` excluida** | Defender escaneando el `.vhdx` en tiempo real cuesta justo el recurso que es el cuello de botella: el disco |

**Hecho el 2026-09-14**, en caliente y sin desmontar nada. Ampliar el `.vhdx` desde Hyper-V no
toca ninguna de las cuatro capas de dentro —partición, volumen físico, volumen lógico, sistema
de archivos— y hay que crecerlas **en ese orden**:

```bash
sudo growpart /dev/sda 3 && sudo pvresize /dev/sda3 \
  && sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv \
  && sudo resize2fs /dev/ubuntu-vg/ubuntu-lv && df -h /
```

Queda anotado por si hay que repetirlo al volver a ampliar el `.vhdx`.

### Lo que se decidió **no** hacer

**La tarjeta gráfica no se pasa a la VM.** Tres motivos, y cualquiera de ellos basta:

1. El paso directo de GPU (DDA) **no existe en el Hyper-V de Windows cliente** — es de
   Windows Server. Y GPU-P solo soporta invitados Windows, no Linux.
2. **Ninguna de las tres aplicaciones usa la GPU.** GDAL, PDAL, pypdf, pypdfium2, Pillow e
   `ifcopenshell` son todo CPU y disco.
3. En AeroBim el 3D **se dibuja en el navegador de cada persona**, con su propia tarjeta. Una
   GPU en el servidor no cambiaría nada de lo que el equipo ve.

---

## Cómo se publica: Tailscale, no nginx

**No hay nginx, ni caddy, ni traefik.** Quien termina TLS y publica es **Tailscale**, con
**Funnel encendido**: el sitio es alcanzable **desde todo internet**, no solo desde la red
privada. Es una decisión tomada a propósito —acceso desde terreno— y tiene consecuencias.

Funnel admite **tres puertos: 443, 8443 y 10000**. Eso evita montar varias aplicaciones Django
bajo prefijos de ruta, que rompería todas las URL generadas:

El tailnet es **`tailccd107`**. Reparto comprobado el 2026-09-14 con `tailscale funnel status`:

| Aplicación | Interna | Pública |
| --- | --- | --- |
| **AeroControl** | `127.0.0.1:8000` | `https://p340.tailccd107.ts.net` |
| **AeroLink** | `127.0.0.1:8092` | `https://p340.tailccd107.ts.net/aerolink` |
| **AeroConvert** | `127.0.0.1:8001` | `https://p340.tailccd107.ts.net:8443` |
| **AeroBim** | `127.0.0.1:8002` | `https://p340.tailccd107.ts.net:10000` |

**AeroBim pasó a Funnel el 2026-09-15.** Estuvo un tiempo en `tailnet only` —alcanzable solo
dentro de la red privada— y ahora está en internet abierto como las otras dos. Eso convierte
en real el aviso de más abajo sobre el bloqueo por intentos fallidos: mientras era privado,
equivocarse ocho veces solo lo podía hacer alguien de la oficina.

Cada una montada en `/`, sin `FORCE_SCRIPT_NAME` y sin reescribir estáticos.

```bash
tailscale funnel --bg --https=8443 http://127.0.0.1:8001
tailscale funnel status
```

### Lo que **toda** aplicación de esta máquina tiene que saber

**La dirección de quien llama no es `REMOTE_ADDR`.** Con Tailscale delante, `REMOTE_ADDR` es
`127.0.0.1` para todo el mundo. La de verdad viene en `X-Forwarded-For`, y hay que tomar **la
última** de la lista.

Esto no es cosmético: si el bloqueo por intentos fallidos de django-axes se configura por IP
sin resolver esto, **ocho equivocaciones de cualquiera dejan fuera a toda la oficina**. Es el
fallo operativo más probable del primer día.

AeroConvert lo resuelve en `apps/core/ip.py` con `AXES_CLIENT_IP_CALLABLE`, y bloquea por la
**pareja usuario + IP**. Ojo: los ajustes `AXES_IPWARE_*` que salen al buscar **no hacen
nada** — axes solo los mira si `django-ipware` está instalado, y no lo está.

> **AeroControl y AeroBim: revisad esto.** Si alguna bloquea solo por IP, hoy es una
> denegación de servicio a un clic de distancia, y está publicada en internet. Para AeroBim
> esto dejó de ser hipotético el **2026-09-15**, cuando pasó de `tailnet only` a Funnel.

### Cuando «se cayeron las tres» y no se había caído ninguna

Pasó el **2026-09-15**, durante los cambios de AeroBim: las tres aplicaciones dejaron de
abrirse a la vez, con `ERR_NAME_NOT_RESOLVED`. La causa no estaba en el servidor.

```
# Health check:
#   - Tailscale failed to set the DNS configuration of your device:
#     El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso.
```

**Era el cliente**, y en concreto una **regla NRPT atascada**.

Tailscale instala en Windows una regla que intercepta todo `.ts.net` y lo manda a su propio
resolutor. Cuando no consigue escribir la configuración de DNS, esa regla se queda puesta
apuntando a un resolutor que no contesta: **ni la usa ni la suelta**. Windows deja de preguntar
al DNS público y devuelve «el nombre no existe» para un nombre que existe.

Que fallen las tres a la vez es justamente la pista de que **no es ninguna de las tres**:
comparten el nombre.

Dos cosas que se probaron y **no** sirvieron, para no repetirlas:

- `tailscale down; tailscale up` — reconecta el túnel, que nunca estuvo caído.
- `tailscale up --accept-dns=false` — debería retirar la regla, pero retirarla es escribir la
  configuración de DNS, que es justo lo que está bloqueado.

Lo que sí sirvió, en PowerShell **como administrador**:

```powershell
Get-DnsClientNrptRule | Where-Object { $_.Namespace -like "*ts.net*" } | Remove-DnsClientNrptRule -Force
ipconfig /flushdns
```

Si la orden se queja del bloqueo, un reinicio del equipo lo suelta.

Cómo distinguirlo en treinta segundos, antes de tocar nada:

| Qué mirar, desde el cliente | Si sale esto, el servidor está bien |
| --- | --- |
| `Test-NetConnection 100.121.16.118 -Port 8443` | `TcpTestSucceeded : True` — **el más rápido y el más concluyente** |
| `Resolve-DnsName p340.tailccd107.ts.net -Server 1.1.1.1` | devuelve direcciones: el nombre **sí** está publicado |
| `tailscale status` | la línea de `p340` dice `active; direct …` con tráfico |

Y en p340, si aun así hay dudas: `sudo tailscale funnel status` con los puertos en
`(Funnel on)`, `systemctl is-active aeroconvert`, y un `curl` a `127.0.0.1:<puerto>`.

**Las dos primeras filas cierran el caso en veinte segundos.** Si el puerto acepta conexión
por la interfaz de Tailscale y el nombre resuelve desde un DNS de fuera, no hay absolutamente
nada que arreglar en el servidor — y todo el tiempo que se gaste ahí es tiempo perdido.

Si urge entrar antes de arreglar el cliente, una línea en el archivo de hosts apuntando el
nombre a la dirección **de Tailscale** —`100.121.16.118`, no la de la LAN— mantiene el
certificado válido. Hay que quitarla después, o el día que esa dirección cambie alguien se
quedará fuera sin saber por qué.

**La lección que sí es del servidor:** las órdenes de `tailscale funnel` y `tailscale serve`
**no son de una aplicación, son de la máquina**. Una sin puerto, o un `serve reset`, rehace el
reparto de las tres. Quien configure una aplicación nueva usa siempre `--https=<su puerto>`.

**Y se puede saber si una petición vino de internet o de la red privada.** Tailscale manda la
cabecera `Tailscale-Funnel-Request` solo en las de Funnel. Llegan por el mismo puerto, así que
es la única forma de distinguirlas. AeroConvert la usa para dejarlo escrito en el registro de
cada entrada y cada intento fallido.

---

## Quién corre cómo, y dónde vive

Conviven **dos patrones**, y conviene saberlo antes de añadir el tercero:

| | Patrón | Dónde |
| --- | --- | --- |
| **AeroControl** | systemd + `uv run gunicorn`, 3 obreros | `/opt/aerocontrol`, entorno en `/etc/aerocontrol.env` |
| **AeroLink** | Docker compose — API, dos pilotos, **PostgreSQL 16**, **MinIO** | contenedores |
| **AeroConvert** | systemd + `uv run gunicorn` *(previsto)* | `/opt/aeroconvert` |

Puertos ocupados: `8000, 8081, 8090, 8092, 9000, 9001`. **Libres para lo siguiente: 8001,
8002.**

`uv` está en `/home/levdigital01/.local/bin/uv`. **Ubuntu 26.04 solo trae Python 3.14**, y
AeroConvert pide `>=3.12,<3.13`, así que el intérprete lo pone `uv` — pero **en `/opt/python`,
no en `/home`**: las unidades llevan `ProtectHome=yes` y para el usuario de servicio `/home`
no existe. Un entorno virtual apuntando al Python de `/home` arranca a mano y falla como
servicio, con un error que no menciona `/home` por ningún lado.

**PDAL no está empaquetado en 26.04** (`apt-cache policy pdal` no devuelve nada). Sin él las
nubes de puntos salen apagadas con su motivo, igual que las dos herramientas de Office; el
ráster, el vectorial y LandXML funcionan. No bloquea nada.

De las **veinte de documentos**, en este servidor funcionan **quince**. Las cinco
apagadas no son un fallo del montaje y no hay que buscarles arreglo: dos piden Office, dos
piden el motor de Access —los dos son de Microsoft y en Linux no existen— y la de reconocer
texto pide **Tesseract**, que sí se puede poner:

```bash
sudo apt install tesseract-ocr tesseract-ocr-spa
```

Cada una dice en pantalla cuál le falta. `/motores/` las lista todas con su motivo.

---

## Qué separa a una aplicación de las otras

Tres aplicaciones en una máquina comparten cuatro cosas —CPU, memoria, disco y red— y cada una
es una forma distinta de que el fallo de una se lleve a las demás. Esto es lo que hay puesto,
y lo que cada aplicación nueva debería copiar.

| Recurso | Cómo se separa | Qué pasaría sin ello |
| --- | --- | --- |
| **Usuario** | Cada una corre como el suyo, de sistema y con `nologin`. `/opt/<app>` es de solo lectura para ella misma (`ProtectSystem=strict` + `ReadWritePaths` explícitos) | Un fallo de ruta en una escribiría en los datos de otra. Y el código no puede modificarse a sí mismo |
| **Memoria** | `MemoryMax=` en cada unidad, y `MemorySwapMax=0` en el obrero | **Es el riesgo real de esta máquina.** Una nube de puntos grande sin techo hace que el matador del núcleo elija víctima, y suele elegir al servidor web o a PostgreSQL — o sea, a un vecino |
| **CPU y disco** | `Nice=5` e `IOSchedulingPriority=6` en el obrero | Una conversión de media hora dejaría la interfaz de las otras dos a tirones |
| **Procesos hijos** | `KillMode=control-group` | Al parar el obrero, un `gdal_translate` huérfano seguiría escribiendo un parcial que ya no reclama nadie |
| **Puerto** | Cada una en `127.0.0.1:<suyo>`, **nunca en `0.0.0.0`** | Una segunda puerta sin TLS por la red de la oficina, esquivando Funnel |
| **Publicación** | Un puerto de Funnel por aplicación | Bajar una tiraría a las otras. Así, `tailscale funnel --https=8443 off` solo apaga AeroConvert |
| **Base de datos** | AeroConvert lleva su propio SQLite en `/var/lib/aeroconvert` | Compartir el PostgreSQL de AeroLink haría que su mantenimiento fuera parada de las tres |
| **Reinicio** | `Restart=always` con `RestartSec` | Un cuelgue exigiría que alguien se dé cuenta |

**Y la pieza que cierra el círculo:** `memoria_total_mb()` (`apps/jobs/estimacion.py`) lee el
techo del **grupo de control**, no la RAM de la máquina. Sin eso, la comprobación previa miraba
los 22 GB físicos y aceptaba un trabajo que `MemoryMax=8G` mata a media conversión — veinte
minutos después y sin motivo escrito. Con eso, cambiar el número en la unidad basta: la
aplicación se entera sola y rechaza por adelantado lo que no cabe, diciendo por qué.

> **AeroBim, cuando entre:** copia la tabla. Lo único que no es opcional es `MemoryMax=`.

---

## Lo que falta, y es común a las tres

1. **El respaldo — y una corrección de este documento.**

   Este punto decía «no hay ningún respaldo automático», y esa frase se repitió durante días
   sin comprobarla. **AeroConvert trae el suyo montado**: `manage.py respaldar` —que verifica
   la copia abriéndola y falla ruidosamente si no cuadra—, más
   `aeroconvert-respaldo.service` y `aeroconvert-respaldo.timer` (03:15, `Persistent=true`),
   que el paso 4 del README habilita. Comprobarlo lleva treinta segundos:

   ```bash
   systemctl list-timers aeroconvert-respaldo.timer; ls -lh /var/backups/aeroconvert/ | tail -5
   ```

   Lo que **sí falta con certeza**, y es lo que de verdad importa:

   - **Una copia fuera de la máquina.** El servicio escribe en `/var/backups/aeroconvert`, el
     mismo NVMe que la base. Un fallo de ese disco se lleva base, entregables y respaldos a la
     vez — que es exactamente el escenario del que un respaldo existe para proteger.
   - **El equivalente para AeroControl y AeroBim**, que no tienen ni el comando. Y AeroLink
     arrastra PostgreSQL y MinIO, que piden otra cosa.

2. **No hay límite de peticiones.** Contra un extremo público, alguien puede probar
   contraseñas tan rápido como aguante la máquina. El bloqueo de axes es por usuario: no frena
   el chorro. Se resuelve con un nginx local entre Tailscale y las aplicaciones —hay una
   configuración lista en `aeroconvert.nginx.conf`, con la trampa de `real_ip` explicada.

3. **SSH admite contraseña.** No lo expone Funnel, pero sí está abierto a toda la red de la
   oficina. Pasar a claves es lo más barato que se puede hacer aquí.

4. **Segundo factor para entrar.** No urgente, pero anotado: con entregables de clientes
   detrás de una contraseña en internet, es la diferencia entre «alguien acertó una
   contraseña» y «no pasó nada».

5. **Los puntos de control no son un respaldo.** Están en «solo producción», que es lo
   correcto, pero viven en el mismo disco y crecen. Hoy no hay ninguno colgando.

6. **La dirección de la LAN es DHCP y ya cambió una vez** (`.51` → `.143`). Una reserva en el
   router cuesta un minuto y evita perseguirla el día que algo la tenga escrita.

---

## Aritmética de capacidad, para cuando entre AeroBim

Con 8 vCPU, 24 GB y 342 GB de disco —**317 libres**— hay sitio para las tres. Los dos límites
reales:

- **Disco.** Los 350 GB de la VM salen de los 494 libres del anfitrión. Si la VM los llenara,
  a Windows le quedarían 144. Y si la carpeta compartida con ortofotos y nubes vive dentro,
  se consume rápido: **una nube de 20 GB necesita 40 para convertirse**.
- **Memoria en las nubes de puntos.** PDAL las carga en memoria: **105 MB por millón de
  puntos**, medido. Mil millones de puntos piden unos 100 GB, que no es «una VM más grande»:
  no es ninguna VM. AeroConvert lo comprueba **antes** de empezar y lo rechaza con su motivo,
  en vez de dejar que el núcleo mate el proceso.
