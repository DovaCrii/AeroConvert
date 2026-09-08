# Levanta AeroConvert en modo taller y abre el navegador.
#
# Se espera a que `/salud/` responda en vez de dormir unos segundos y cruzar los dedos: en
# un arranque frio Django tarda mas, y abrir el navegador antes de tiempo da una pagina de
# error que parece un fallo de la aplicacion.

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$Puerto = if ($env:AEROCONVERT_PUERTO) { $env:AEROCONVERT_PUERTO } else { "8420" }
$Url = "http://127.0.0.1:$Puerto/"

if (-not (Test-Path ".env")) {
    throw "Falta .env. Copia .env.example y ajusta AEROCONVERT_RAICES_PERMITIDAS."
}

$env:DJANGO_SETTINGS_MODULE = "config.settings.taller"

# `--noreload` no es un detalle: con el recargador, `runserver` son DOS procesos y
# arrancarian dos despachadores compitiendo por el mismo trabajo.
$servidor = Start-Process -PassThru -NoNewWindow -FilePath "uv" `
    -ArgumentList @("run", "python", "manage.py", "runserver", "--noreload", "127.0.0.1:$Puerto")

Write-Host "Arrancando AeroConvert en $Url ..." -ForegroundColor Cyan

$listo = $false
foreach ($intento in 1..60) {
    Start-Sleep -Milliseconds 500
    if ($servidor.HasExited) {
        throw "El servidor termino con codigo $($servidor.ExitCode). Revisa la salida de arriba."
    }
    try {
        $respuesta = Invoke-WebRequest -Uri "$($Url)salud/" -UseBasicParsing -TimeoutSec 2
        if ($respuesta.StatusCode -eq 200) { $listo = $true; break }
    } catch {
        continue
    }
}

if (-not $listo) {
    throw "El servidor no respondio en 30 segundos."
}

Write-Host "Listo. Abriendo el navegador." -ForegroundColor Green
Start-Process $Url
Write-Host "Ctrl+C para detener." -ForegroundColor DarkGray
Wait-Process -Id $servidor.Id
