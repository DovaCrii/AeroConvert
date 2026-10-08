#!/usr/bin/env bash
#
# Instala por apt los programas externos que AeroConvert sondea y que **no piden licencia ni
# registro** (F17.4). Lo que falte sale apagado en /compatibilidad/ con su motivo; esto lo enciende.
#
#     cd /opt/aeroconvert && sudo despliegue/instalar_faltantes.sh          # instala
#     cd /opt/aeroconvert && sudo despliegue/instalar_faltantes.sh --ver    # solo dice que haria
#
# ## Lo que instala, y para que
#
# | Paquete            | Programa      | Para que (en AeroConvert)                                  |
# | ------------------ | ------------- | ---------------------------------------------------------- |
# | tesseract-ocr(-spa)| tesseract     | OCR de PDF escaneados                                      |
# | rtklib             | rnx2rtkp      | PPK de un vuelo de dron (BSD-2)                            |
# | xvfb               | xvfb-run      | ODA y Wine necesitan un servidor grafico aunque no dibujen |
# | ffmpeg             | ffmpeg        | video (F14.17), la traza de un video de dron               |
# | ghostscript        | gs            | PDF/A y compresion de PDF (F14.9)                          |
# | inkscape           | inkscape      | SVG a PDF o PNG (F14.16)                                   |
# | mdbtools           | mdb-tables    | leer catalogos .accdb/.mdb sin Access (F17.2)              |
# | libreoffice-*      | soffice       | Office a PDF, rotulado «puede variar» (F17.1)              |
#
# FFmpeg, Ghostscript e Inkscape son GPL/AGPL: **se ejecutan aparte y se sondean**, nunca se
# importan ni se copian (decision D1 de AGENTS.md). Lo que **no** esta aqui, porque pide licencia o
# registro, es de la persona: ODA File Converter, el convertidor de Trimble, la clave de ECW.
#
# ## Por que no falla si un paquete no existe
#
# Ubuntu cambia nombres entre versiones (PDAL dejo de estar en 26.04). Un paquete que la
# distribucion no tiene se **dice** y se sigue con el resto: instalar siete de ocho es mejor que
# ninguno, y el que falta sigue apagado con su motivo en la pantalla.
#
set -euo pipefail

PAQUETES=(
    tesseract-ocr
    tesseract-ocr-spa
    tesseract-ocr-eng
    rtklib
    xvfb
    ffmpeg
    ghostscript
    inkscape
    mdbtools
    libreoffice-writer-nogui
    libreoffice-calc-nogui
    libreoffice-impress-nogui
)

# Programa que cada uno deja en el PATH, para comprobar despues que de verdad quedo.
declare -A PROGRAMA=(
    [tesseract-ocr]=tesseract
    [rtklib]=rnx2rtkp
    [xvfb]=xvfb-run
    [ffmpeg]=ffmpeg
    [ghostscript]=gs
    [inkscape]=inkscape
    [mdbtools]=mdb-tables
    [libreoffice-writer-nogui]=soffice
)

solo_ver=0
for argumento in "$@"; do
    case "$argumento" in
        --ver | -n) solo_ver=1 ;;
        -h | --help)
            sed -n '2,8p' "$0"
            exit 0
            ;;
        *)
            echo "Argumento desconocido: $argumento (use --ver para ver sin instalar)." >&2
            exit 2
            ;;
    esac
done

if [ "$solo_ver" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "Hace falta sudo para instalar. Para ver sin instalar: $0 --ver" >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Esta maquina no tiene apt-get: el guion es para Ubuntu/Debian." >&2
    exit 1
fi

disponibles=()
ausentes=()
for paquete in "${PAQUETES[@]}"; do
    # `apt-cache policy` sin candidato dice «Candidate: (none)» o no dice nada.
    candidato="$(apt-cache policy "$paquete" 2>/dev/null | awk '/Candidate:/ {print $2}')"
    if [ -n "$candidato" ] && [ "$candidato" != "(none)" ]; then
        disponibles+=("$paquete")
    else
        ausentes+=("$paquete")
    fi
done

if [ "${#ausentes[@]}" -gt 0 ]; then
    echo "No estan en los repositorios de esta version (seguiran apagados con su motivo):"
    printf '  - %s\n' "${ausentes[@]}"
fi

if [ "${#disponibles[@]}" -eq 0 ]; then
    echo "Nada que instalar."
    exit 0
fi

if [ "$solo_ver" -eq 1 ]; then
    echo "Se instalaria:"
    printf '  - %s\n' "${disponibles[@]}"
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends "${disponibles[@]}"

echo
echo "Comprobacion (lo que de verdad quedo en el PATH):"
faltan=0
for paquete in "${disponibles[@]}"; do
    programa="${PROGRAMA[$paquete]:-}"
    [ -z "$programa" ] && continue
    if ruta="$(command -v "$programa")"; then
        echo "  [hecho] $programa -> $ruta"
    else
        echo "  [falta] $programa (el paquete $paquete se instalo y el programa no aparece)"
        faltan=$((faltan + 1))
    fi
done

echo
echo "Despues: reinicie el servicio para que las sondas vuelvan a mirar,"
echo "  sudo systemctl restart aeroconvert aeroconvert-obrero"
echo "y abra /compatibilidad/ para ver lo que se encendio."
if [ -n "$(command -v rnx2rtkp || true)" ]; then
    echo "RTKLIB quedo en $(command -v rnx2rtkp): no hace falta AEROCONVERT_RTKLIB_RNX2RTKP en el .env."
fi
exit "$faltan"
