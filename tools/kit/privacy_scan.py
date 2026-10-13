#!/usr/bin/env python3
"""Revisión de privacidad para repos públicos (solo biblioteca estándar).

Uso local o en CI, desde la raíz del repo:

    python tools/kit/privacy_scan.py [--config .privacy-scan.json] [--root .]

Examina los archivos versionados (``git ls-files``) y falla (código 1) si encuentra:
carpeta ``private/``, ``.env`` (salvo ``.env.example``), claves (``nvapi-``, ``sk-``, ``AKIA``),
bloques de llave privada, correos de dominios reales, RUT chilenos y archivos basura cuyo
nombre empieza con ``--``.

Configuración opcional (JSON, por defecto ``.privacy-scan.json`` en la raíz):
- ``allow_email_domains``: dominios de correo aceptados además de los de ejemplo.
- ``allow_paths``: globs de rutas que no se examinan.
- ``allow_rules``: {"glob": ["email", "rut"]} reglas ignoradas solo en esas rutas.
Las excepciones son para falsos positivos legítimos; no se debilitan las reglas.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

DEFAULT_ALLOW_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "localhost",
    "users.noreply.github.com",
    "noreply.github.com",
    "anthropic.com",
}
MAX_BYTES = 2_000_000

CONTENT_RULES = {
    "nvapi": re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}"),
    "sk": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "aws": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private-key": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY"),
    "rut": re.compile(r"(?<![\w.])\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b"),
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def check_path(path: str) -> list[str]:
    """Reglas que dependen solo del nombre del archivo."""
    parts = PurePosixPath(path).parts
    name = parts[-1]
    found = []
    if parts[0] == "private":
        found.append("private-dir: contenido de private/ versionado")
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        found.append("env-file: archivo .env versionado")
    if name.startswith("--"):
        found.append("junk-name: nombre de archivo basura que empieza con --")
    return found


def check_text(path: str, text: str, allow_domains: set[str], skip_rules=()) -> list[str]:
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rule, rx in CONTENT_RULES.items():
            if rule not in skip_rules and rx.search(line):
                found.append(f"{rule}: {path}:{lineno}")
        if "email" not in skip_rules:
            for m in EMAIL_RE.finditer(line):
                domain = m.group(1).lower()
                if domain not in allow_domains and not domain.endswith(".example"):
                    found.append(f"email: {path}:{lineno} (dominio {domain})")
    return found


def scan(root: Path, config: dict | None = None, files: list[str] | None = None) -> list[str]:
    config = config or {}
    allow_domains = DEFAULT_ALLOW_DOMAINS | {
        d.lower() for d in config.get("allow_email_domains", [])
    }
    allow_paths = config.get("allow_paths", [])
    allow_rules = config.get("allow_rules", {})
    problems = []
    for path in files if files is not None else tracked_files(root):
        if any(fnmatch.fnmatch(path, p) for p in allow_paths):
            continue
        problems += [f"{m} ({path})" for m in check_path(path)]
        full = root / path
        if not full.is_file() or full.stat().st_size > MAX_BYTES:
            continue
        data = full.read_bytes()
        if b"\0" in data:
            continue
        skip = {
            r for pat, rules in allow_rules.items() if fnmatch.fnmatch(path, pat) for r in rules
        }
        problems += check_text(path, data.decode("utf-8", "replace"), allow_domains, skip)
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Revisión de privacidad de archivos versionados")
    ap.add_argument("--root", default=".")
    ap.add_argument("--config", default=None, help="JSON de excepciones (def. .privacy-scan.json)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    cfg_path = Path(args.config) if args.config else root / ".privacy-scan.json"
    config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    problems = scan(root, config)
    if problems:
        print("Revisión de privacidad: FALLÓ")
        for p in problems:
            print("  -", p)
        return 1
    print("Revisión de privacidad: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
