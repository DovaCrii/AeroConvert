#!/usr/bin/env bash
#
# La puerta de calidad, en Linux. Es `verify.ps1` paso por paso, **con un arreglo**:
# `verify.ps1` corre `check --deploy` sin fijar el modulo de ajustes, asi que cae en
# `config.settings.dev` -- con DEBUG=True -- y no comprueba nada de lo que importa. Aqui se
# fija de verdad.
#
set -euo pipefail
cd "$(dirname "$0")/.."

paso() {
    echo "==> $1"
    shift
    "$@"
}

paso "manage.py check"           uv run python manage.py check --fail-level WARNING

# El de produccion, con lo minimo para que arranque. Sin esto, `--deploy` mira el modulo
# equivocado y pasa siempre.
paso "manage.py check --deploy (produccion de verdad)" env \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    ALLOWED_HOSTS=verificacion.example.org \
    CSRF_TRUSTED_ORIGINS=https://verificacion.example.org \
    AEROCONVERT_MODO=taller \
    AEROCONVERT_RAICES_PERMITIDAS=/tmp \
    uv run python manage.py check --deploy --fail-level WARNING

paso "makemigrations --check"    uv run python manage.py makemigrations --check --dry-run
paso "pytest"                    uv run pytest --cov=apps --cov-report=term-missing
paso "ruff check"                uv run ruff check .
paso "ruff format --check"       uv run ruff format --check .
paso "bandit"                    uv run bandit -q -c pyproject.toml -r apps config
paso "pip-audit"                 uv run pip-audit

if command -v shellcheck >/dev/null 2>&1; then
    paso "shellcheck" shellcheck scripts/*.sh
else
    echo "==> shellcheck (no esta instalado, se salta)"
fi

echo "verificar.sh: todo en verde"
