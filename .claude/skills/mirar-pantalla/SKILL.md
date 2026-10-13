---
name: mirar-pantalla
description: Ver una pantalla de AeroConvert con sesión sin crear cuentas ni teclear contraseñas - la pinta con el cliente de pruebas a un HTML estático, la abre en el navegador del panel en claro y oscuro a 1440 y 375 px y comprueba que no desborda. Úsala para toda fila que toca una pantalla.
disable-model-invocation: true
argument-hint: "<nombre=/ruta/ [otra=/ruta/]>"
---

# Mirar una pantalla: `$ARGUMENTS`

**Nunca** cree una cuenta, teclee una contraseña ni inyecte una cookie en el navegador: la pantalla con sesión
se pinta con el cliente de pruebas de Django (`force_login` de un usuario sintético en una base de prueba).

1. **Pintar.** `uv run python scripts/claude/instantanea.py nombre=/ruta/ [otra=/ruta/]` escribe
   `static/_vista_previa/<nombre>.html` (para un POST con archivo, `--post`). Sale distinto de 0 si una
   respuesta no es 200. `static/_vista_previa/` **no se confirma** (está en `.gitignore`).
2. **Servir.** Si el 8765 está libre, `preview_start` con `aeroconvert`. A veces lo ocupa otro proyecto
   (AeroAcademy): añada **temporalmente** una configuración con otro puerto en `.claude/launch.json` y
   **no la confirme**. Un servidor con `--noreload` no recarga plantillas: reinícielo.
3. **Mirar.** Abra `http://localhost:<puerto>/static/_vista_previa/<nombre>.html` y comprueba, para
   **claro y oscuro** (`resize_window` con `colorScheme`) a **1440 px y a 375 px**:
   - sin desborde horizontal: `document.documentElement.scrollWidth == innerWidth`;
   - la consola sin errores (`read_console_messages`), y con la política de contenido real (CSP `'self'`);
   - lo que dice la fila: marcas, textos, foco visible, el color nunca solo, nada que dependa del hover.
   Si el CSS parece viejo, fuerce la recarga (`link.href += '?r=' + Date.now()`).
4. **Medir, no opinar.** El contraste lo miden `apps/core/test_paleta.py` y `test_plano.py`; si cambió
   estilos, `/verificar pruebas apps/core apps/dashboard`.
5. **Limpiar.** `uv run python scripts/claude/instantanea.py --limpiar`; devuelva el viewport con
   `resize_window preset=desktop`; pare el servidor y restaure `.claude/launch.json`.

Una captura que no se pudo tomar (la pestaña dice «no terminó de renderizar») se repite una vez; si sigue
fallando, use `read_page`, `get_page_text` o JavaScript de solo lectura y dígalo.
