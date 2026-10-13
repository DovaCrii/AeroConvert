---
name: revision-privacidad
description: Revisa que un cambio no exponga secretos, datos de clientes ni datos personales antes de abrir un PR en un repositorio público. Usar antes de cada commit grande, de cada PR y al agregar archivos, ejemplos o datos de prueba.
---

# Revisión de privacidad (repositorio público)

1. **Mira el diff completo**: `git diff --stat` y `git diff` (incluye archivos nuevos con `git status`).
2. **Busca, en lo que se agrega:**
   - claves y tokens (`nvapi-`, `sk-`, `AKIA`, `ghp_`, bloques `PRIVATE KEY`), contraseñas, `.env`, certificados, `.pem`, `.pfx`;
   - correos reales, RUT, teléfonos, direcciones, nombres de clientes o de personas;
   - datos de proyectos de clientes (nubes de puntos, planos, bases de datos, exportaciones);
   - capturas con barras de URL, nombres de usuario o rutas personales.
3. **Corre** `python tools/kit/privacy_scan.py`. Un hallazgo se corrige quitando el dato, no relajando la regla.
   Solo un falso positivo claro se agrega a `.privacy-scan.json` (dominio ficticio o ruta de pruebas), con la razón en el PR.
4. **Dónde va lo sensible:** en `private/` (ignorado por git), variables de entorno o un gestor de secretos. Los ejemplos
   usan datos inventados (`persona@example.com`).
5. **Si algo ya se subió:** avisa a la persona de inmediato. Borrar el archivo en un commit nuevo no lo saca del historial;
   hay que rotar la clave y decidir cómo limpiar el historial. No reescribas ramas compartidas por tu cuenta.
6. **Informa** con una lista corta: qué revisaste, qué encontraste, qué corregiste.
