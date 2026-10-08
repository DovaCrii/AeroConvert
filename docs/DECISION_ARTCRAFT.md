# Decisión: ArtCraft (storytold/artcraft) — no se adopta ni se porta

**Fecha:** 2026-10-08. **Qué es:** una aplicación de escritorio en Rust para creación con IA
generativa (imagen, video, mallas 3D), que enruta a unos 62 modelos de terceros (Midjourney, Sora,
Grok…). No es una librería.

**Por qué no entra en AeroConvert**

1. **Licencia.** Es la «ArtCraft License (WIP)», *fair source*, **no** de código abierto: prohíbe
   venderla y usarla para un producto competidor. `AGENTS.md` exige que el repositorio siga siendo MIT
   y solo permite portar código MIT, BSD o Apache. No se copia ni se enlaza nada.
2. **Otra clase de producto.** AeroConvert convierte y entrega archivos de ingeniería sin salir de la
   oficina («lo que conviertes lo ve todo el equipo»). Generar imágenes con IA enviaría datos a
   proveedores externos y crearía contenido que no existía, lo contrario de «el original no se toca».
3. **Lo útil ya está en el plan con herramientas propias:** quitar fondo (F14.15, `rembg` como extra
   opcional, local) y, si hiciera falta una composición en capas, se evalúa aparte.

**Qué se reevalúa si cambia algo:** que la licencia pase a MIT/Apache, o que la persona pida
explícitamente edición con IA en local (sin proveedores externos). Hasta entonces, sin fila en el plan.
