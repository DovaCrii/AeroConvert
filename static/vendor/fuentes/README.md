# Fuentes vendorizadas

Tres familias bajo la **SIL Open Font License 1.1** (F20.3, decisión D9; la persona autorizó la
descarga el 2026-10-13). Cada una trae su licencia al lado (`*-OFL.txt`). Se sirven del mismo origen,
sin CDN, con `font-display: swap` (los `@font-face` están en `static/css/app.css`).

| Archivo | Familia | Uso | Origen | Versión | `sha256` |
| --- | --- | --- | --- | --- | --- |
| `inter-latin-wght-normal.woff2` | Inter | texto | npm `@fontsource-variable/inter` | 5.3.0 | `3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62` |
| `space-grotesk-latin-wght-normal.woff2` | Space Grotesk | títulos | npm `@fontsource-variable/space-grotesk` | 5.3.0 | `0640890476fc1198ab4de571fb658de443c4d85b66466ec09534a8737ab1ce9d` |
| `jetbrains-mono-latin-wght-normal.woff2` | JetBrains Mono | cifras | npm `@fontsource-variable/jetbrains-mono` | 5.3.0 | `18be452724bfdc236c074ca94a249a7f41a86752c7d04ab258ce9ed5651f6a7e` |

Son **variables** (un archivo por familia cubre todos los pesos) y de **subconjunto latino**
(`U+0000-00FF`, `€`, comillas y rayas, entre otros): cubre el español completo. Lo que quede fuera
de ese subconjunto cae a la fuente del sistema.

## Cómo se actualiza

1. `npm pack @fontsource-variable/<familia>@<versión>` en una carpeta vacía; extraer el `.tgz`.
2. Copiar `files/<familia>-latin-wght-normal.woff2` y `LICENSE` (como `<familia>-OFL.txt`).
3. Actualizar versión y `sha256` (`Get-FileHash -Algorithm SHA256`) en esta tabla.
