# Que motores ve esta maquina, y por que faltan los que faltan.
#
# Solo un envoltorio: la logica esta en `scripts/sondear.py`, que ademas se puede llamar
# directo desde un servidor sin PowerShell.

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

uv run python scripts/sondear.py
