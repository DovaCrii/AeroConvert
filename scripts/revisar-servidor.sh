#!/usr/bin/env bash
#
# Los riesgos del servidor, preguntados a la maquina en vez de leidos en una lista.
#
# ## Por que esto es un guion y no un apartado de SERVIDOR.md
#
# Ya eran un apartado de SERVIDOR.md, y ahi llevaban semanas. Una lista de riesgos escrita
# **no dice cuales siguen abiertos**: hay que ir comprobandolos uno a uno, nadie lo hace, y
# la lista envejece hasta decir cosas falsas en las dos direcciones. Este proyecto ya se
# llevo ese golpe: «no hay respaldo automatico» estuvo escrito dias mientras el temporizador
# estaba en el repositorio y funcionando.
#
# Asi que se pregunta. Se corre en el servidor, no cambia nada, y contesta hoy.
#
#     ssh p340 'cd /opt/aeroconvert && sudo ./scripts/revisar-servidor.sh'
#
# ## Y no falla aunque haya cosas abiertas
#
# A proposito: no es una puerta de calidad, es un informe. Que devolviera error dejaria a
# alguien tentado de meterlo en un despliegue, y entonces el despliegue empezaria a fallar
# por algo que no es del despliegue. Lo que hace es **decir el estado de cada cosa y que
# hacer con ella**.
#
set -uo pipefail

AZUL='\033[0;36m'
VERDE='\033[0;32m'
AMBAR='\033[0;33m'
ROJO='\033[0;31m'
FIN='\033[0m'
abiertos=0

titulo() { printf '\n%b== %s%b\n' "$AZUL" "$1" "$FIN"; }
bien() { printf '  %b[hecho]%b %s\n' "$VERDE" "$FIN" "$1"; }
falta() {
    printf '  %b[falta]%b %s\n' "$AMBAR" "$FIN" "$1"
    abiertos=$((abiertos + 1))
}
grave() {
    printf '  %b[grave]%b %s\n' "$ROJO" "$FIN" "$1"
    abiertos=$((abiertos + 1))
}
nota() { printf '          %s\n' "$1"; }

# El mas reciente de un patron, sin analizar la salida de `ls`, que se rompe con nombres
# raros y que shellcheck marca con razon.
mas_reciente() {
    find "$1" -maxdepth 1 -name "$2" -printf '%T@ %p\n' 2>/dev/null |
        sort -rn | head -1 | cut -d' ' -f2-
}

printf 'Riesgos del servidor de AeroConvert — %s en %s\n' \
    "$(date '+%Y-%m-%d %H:%M')" "$(hostname)"

# --- E0 · El respaldo que ya existe ----------------------------------------
#
# Va primero porque es el que se dio por ausente sin comprobarlo.
titulo "Respaldo automatico de la base"

if systemctl list-timers --all 2>/dev/null | grep -q 'aeroconvert-respaldo'; then
    bien "el temporizador esta puesto"
    if ! systemctl is-enabled --quiet aeroconvert-respaldo.timer 2>/dev/null; then
        falta "...pero no esta habilitado: no sobrevive a un reinicio"
        nota "sudo systemctl enable --now aeroconvert-respaldo.timer"
    fi
else
    grave "no hay temporizador de respaldo"
    nota "sudo systemctl enable --now aeroconvert-respaldo.timer"
fi

ultimo=$(mas_reciente /var/backups/aeroconvert 'aeroconvert-*.sqlite3.gz')
if [ -n "$ultimo" ]; then
    edad_h=$((($(date +%s) - $(stat -c %Y "$ultimo")) / 3600))
    if [ "$edad_h" -le 48 ]; then
        bien "el ultimo respaldo es de hace ${edad_h} h ($(basename "$ultimo"))"
    else
        # **Lo peor que le puede pasar a un respaldo automatico**: que este configurado,
        # parezca correcto, y lleve semanas sin escribir. Nadie mira una carpeta que se
        # supone que se llena sola.
        grave "el ultimo respaldo es de hace ${edad_h} h — el temporizador no escribe"
        nota "journalctl -u aeroconvert-respaldo -n 50"
    fi
else
    grave "no hay ningun respaldo en /var/backups/aeroconvert"
fi

# --- E1.1 · La copia de fuera ----------------------------------------------
titulo "Copia del respaldo FUERA de esta maquina"
nota "Es el unico de la lista sin arreglo posible despues: los demas se corrigen el dia"
nota "que se descubren, y que se muera el disco no."

fuera=$(sudo -u aeroconvert grep -s '^AEROCONVERT_RESPALDOS_FUERA=' /opt/aeroconvert/.env |
    cut -d= -f2- | tr -d "\"'")
if [ -z "$fuera" ]; then
    grave "no hay segunda copia: respaldos y base viven en el mismo disco"
    nota "Decide donde -- unidad de red, disco externo -- y pon en .env:"
    nota "AEROCONVERT_RESPALDOS_FUERA=/mnt/loquesea/aeroconvert"
elif [ ! -d "$fuera" ]; then
    grave "AEROCONVERT_RESPALDOS_FUERA apunta a $fuera y ahi no hay nada"
else
    alla=$(mas_reciente "$fuera" 'aeroconvert-*.sqlite3.gz')
    if [ -n "$alla" ]; then
        bien "hay copia fuera, la ultima es $(basename "$alla")"
    else
        grave "$fuera esta configurado y vacio"
    fi
fi

# --- E1.2 · El limite de peticiones ----------------------------------------
titulo "Limite de peticiones sobre la pantalla de entrada"
nota "django-axes bloquea por usuario, que es otra cosa: no frena el chorro. Contra un"
nota "extremo publico, sin esto alguien prueba contrasenas tan rapido como aguante."

if [ -e /etc/nginx/sites-enabled/aeroconvert ]; then
    if grep -qs 'limit_req_zone' /etc/nginx/sites-enabled/aeroconvert; then
        bien "nginx montado y con limite de peticiones"
    else
        falta "nginx montado pero sin limit_req_zone"
    fi
    if tailscale status --json 2>/dev/null | grep -qs '8080'; then
        bien "Funnel apunta a nginx"
    else
        falta "nginx esta montado pero Funnel quiza siga apuntando a gunicorn"
        nota "tailscale funnel --bg --https=8443 http://127.0.0.1:8080"
    fi
else
    falta "nginx no esta montado: el acceso publico no tiene freno"
    nota "sudo cp despliegue/aeroconvert.nginx.conf /etc/nginx/sites-available/aeroconvert"
    nota "sudo ln -s /etc/nginx/sites-available/aeroconvert /etc/nginx/sites-enabled/"
    nota "sudo nginx -t && sudo systemctl reload nginx"
    nota "tailscale funnel --bg --https=8443 http://127.0.0.1:8080"
fi

# --- E1.3 · SSH ------------------------------------------------------------
titulo "SSH solo con clave"
nota "Lo mas barato de la lista. Hoy esta abierto a toda la red de oficina."

if sshd -T 2>/dev/null | grep -qi '^passwordauthentication no'; then
    bien "la autenticacion por contrasena esta desactivada"
else
    falta "se puede entrar por SSH con contrasena"
    nota "Antes de tocar nada, comprueba desde OTRA terminal que tu clave entra."
    nota "Luego: PasswordAuthentication no  en /etc/ssh/sshd_config.d/10-aeroconvert.conf"
fi

# --- E1.4 · Como se llega a esta maquina -----------------------------------
titulo "Como se llega a esta maquina desde la oficina"

ip4=$(hostname -I 2>/dev/null | awk '{print $1}')
tarjeta=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
mac=$(cat "/sys/class/net/${tarjeta:-lo}/address" 2>/dev/null)
puerta=$(ip route show default 2>/dev/null | awk '{print $3; exit}')

# **El consejo que este guion daba antes era falso en esta maquina**, y costo una mañana.
#
# Decia «pon una reserva en el router por MAC». Con la MAC empezando en `00:15:5d` esto es
# una maquina virtual de Hyper-V, y si ademas la puerta de enlace es el `.1` de su propia
# `/24` privada, la red es el **Default Switch**: una NAT interna del anfitrion, con su
# propio DHCP. El router de la oficina no la ve, no la reparte y **no puede reservar nada
# en ella**.
#
# Y lo que de verdad importa: esa direccion **no es alcanzable desde ningun otro equipo de
# la oficina**. Solo existe dentro del anfitrion. Quien entra desde un puesto lo hace por
# el nombre de Tailscale, que no depende de esto.
es_hyperv=""
case "$mac" in
00:15:5d:*) es_hyperv=1 ;;
esac

if [ -n "$es_hyperv" ] && [ "${puerta%.*}" = "${ip4%.*}" ]; then
    grave "esta direccion (${ip4:-?}) es de una NAT interna de Hyper-V"
    nota "NO es alcanzable desde otros equipos de la oficina, y nunca lo fue."
    nota "Una reserva en el router no arregla esto: quien reparte es el anfitrion."
    nota "Desde los puestos se entra por el nombre de Tailscale, que no depende de la LAN."
    nota "Si algun dia hace falta llegar por IP de oficina, hay que mover la maquina"
    nota "virtual a un conmutador EXTERNO y entonces si reservar por MAC en el router."
elif grep -qs 'dhcp4: *false' /etc/netplan/*.yaml; then
    bien "la maquina tiene direccion estatica (${ip4:-?})"
else
    falta "la direccion (${ip4:-?}) la da el DHCP y puede cambiar"
    nota "Reserva en el router por MAC ${mac:-?} (${tarjeta:-?})."
fi

# **La via que de verdad usa la gente.** Es la unica que funciona desde un puesto, asi que
# es la que hay que mirar -- y es la que se cayo el 2026-09-24 sin que el servidor tuviera
# nada: era una regla NRPT pegada en el PC de quien lo intentaba.
if command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
    bien "Tailscale levantado: es asi como se entra desde los puestos"
    tailscale funnel status 2>/dev/null | sed 's/^/          /' || true
else
    grave "Tailscale no responde: nadie puede entrar desde ningun puesto"
fi

# --- E1.5 · Las otras dos aplicaciones -------------------------------------
titulo "Respaldo de AeroControl y AeroBim"
nota "AeroConvert es la unica de las tres que tiene el comando."

for hermana in aerocontrol aerobim; do
    if [ ! -d "/opt/$hermana" ]; then
        nota "$hermana no esta en esta maquina"
    elif systemctl list-timers --all 2>/dev/null | grep -q "$hermana-respaldo"; then
        bien "$hermana tiene temporizador de respaldo"
    else
        falta "$hermana no respalda su base"
        nota "El de AeroConvert es portable: apps/core/management/commands/respaldar.py"
    fi
done

# --- El resumen ------------------------------------------------------------
printf '\n'
if [ "$abiertos" -eq 0 ]; then
    printf '%bNada abierto.%b\n' "$VERDE" "$FIN"
else
    printf '%b%s cosas abiertas.%b Ninguna impide que la aplicacion funcione hoy;\n' \
        "$AMBAR" "$abiertos" "$FIN"
    printf 'la de la copia fuera es la unica que no se puede arreglar despues.\n'
fi
exit 0
