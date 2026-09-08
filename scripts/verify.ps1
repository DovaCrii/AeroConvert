# La puerta de calidad. Ningun cambio se sube sin esta corrida completa en verde.
#
# Tiene que pasar en una maquina SIN GDAL: las pruebas con oraculo externo llevan
# `@pytest.mark.oraculo` y `pytest.ini` las deselecciona. Se corren aparte con
# `uv run pytest -m oraculo`, y su resultado se anota con fecha en
# `docs/PRUEBAS_CON_ORACULO.md`.

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { $Uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $Uv)) { throw "uv es necesario. Instalalo desde https://docs.astral.sh/uv/" }

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "verify.ps1: fallo el paso ($Name), codigo $LASTEXITCODE"
    }
}

Invoke-Step "manage.py check" @("run", "python", "manage.py", "check")
Invoke-Step "manage.py check --deploy" @("run", "python", "manage.py", "check", "--deploy")
Invoke-Step "makemigrations --check" @("run", "python", "manage.py", "makemigrations", "--check", "--dry-run")
Invoke-Step "pytest" @("run", "pytest", "--cov=apps", "--cov-report=term-missing")
Invoke-Step "ruff check" @("run", "ruff", "check", ".")
# El segundo paso de ruff no es redundante: olvidarlo dejo el CI de AeroControl rojo
# durante dias, porque `check` no mira el formato.
Invoke-Step "ruff format --check" @("run", "ruff", "format", "--check", ".")
Invoke-Step "bandit" @("run", "bandit", "-q", "-c", "pyproject.toml", "-r", "apps", "config")
Invoke-Step "pip-audit" @("run", "pip-audit")

Write-Host "verify.ps1: todo en verde" -ForegroundColor Green
