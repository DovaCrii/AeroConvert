---
paths:
  - "templates/**"
  - "static/css/**"
  - "static/js/**"
  - "locale/**"
  - "apps/dashboard/**"
  - "apps/core/**"
  - "apps/documents/views.py"
---

# Interfaz, textos y accesibilidad

- **Español neutral, de usted, sin voseo.** Los `msgid` de gettext van en **inglés** y el español
  vive en `locale/es/`. Un test falla con una sola tilde en un literal fuente. El `.mo` **se
  versiona** y `apps/core/test_traducciones.py` vigila que no quede atrás del `.po`.
- **_Sentence case_:** mayúscula inicial solo en la primera palabra (nombres propios, marcas y siglas
  aparte). Lo vigila `apps/core/test_estilo.py`; lee `docs/ESTILO.md` antes de tocar una pantalla.
- **Los títulos dicen qué hace la pantalla**, no cómo se llama por dentro. **Cada herramienta dice
  qué entrega** («uno o varios PDF»).
- **Permisos:** toda vista de lectura exige su permiso explícito y trae su **prueba de 403**. Nunca
  `fields = "__all__"`.
- **Front:** Bootstrap y htmx vendorizados en `static/vendor/` con SRI. CSP `'self'`, **cero CDN**,
  sin `'unsafe-inline'` en `script-src`. No leas `static/vendor/` (minificado); lee `static/css/app.css`
  (≈86 KB) por rangos o con `grep -n`.
- **Nada se esconde en hover:** prohibido `opacity-0 group-hover:opacity-100`.
- **El color nunca va solo:** severidad = color **+** forma de icono distinta **+** texto.
- **Contraste y foco se miden, no se opinan:** las pruebas leen la fórmula WCAG 2.1 del CSS. Un
  cambio visual que no pase esas pruebas no se entrega. Móvil: probar a 375 px.
- **Una acción principal por pantalla.** Los errores de htmx se ven (`aria-live`).
- Si cambias estilos, `/verificar pruebas apps/core apps/dashboard` y mira la pantalla en el navegador
  en los dos temas.
