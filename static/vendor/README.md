# Librerías vendorizadas

Aquí viven las librerías de terceros que usa la interfaz, **como archivos del repositorio y
no como enlaces a un CDN**.

## Por qué vendorizadas

Tres razones, y la primera basta:

1. **La CSP es `'self'`.** No hay ningún origen externo permitido, ni para scripts ni para
   estilos. Un `<script src="https://cdn...">` simplemente no cargaría.
2. **Modo taller.** La aplicación corre en una estación de trabajo que puede no tener
   salida a internet, o tenerla filtrada. Una interfaz que se rompe sin red no sirve.
3. **Reproducibilidad.** Un CDN puede cambiar lo que sirve bajo la misma URL. Aquí lo que
   se probó es lo que se despliega.

## Qué hay, y su hash

Los `integrity` van en las etiquetas aunque los archivos sean del mismo origen: protegen de
un archivo corrompido o alterado en el disco del servidor, que es un caso que existe.

| Archivo | Versión | Licencia | `integrity` |
| --- | --- | --- | --- |
| `bootstrap.min.css` | 5.3.3 | MIT | `sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH` |
| `bootstrap.bundle.min.js` | 5.3.3 | MIT | `sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz` |
| `htmx.min.js` | 2.0.10 | BSD-2 | `sha384-H5SrcfygHmAuTDZphMHqBJLc3FhssKjG7w/CeCpFReSfwBWDTKpkzPP8c+cLsK+V` |

## Cómo se actualiza

1. Descargar el archivo nuevo de jsDelivr o de la web del proyecto.
2. Recalcular el hash:

```powershell
$b = [IO.File]::ReadAllBytes("static\vendor\htmx.min.js")
"sha384-" + [Convert]::ToBase64String([Security.Cryptography.SHA384]::Create().ComputeHash($b))
```

3. Actualizar la tabla de arriba **y** el `integrity` de `templates/base.html`. Si se olvida
   el segundo, el navegador rechaza el archivo y la interfaz deja de funcionar entera — lo
   cual es molesto pero correcto: es justo lo que el `integrity` existe para hacer.

Hay una prueba que compara los hashes del disco con los de las plantillas, así que
olvidarse no llega a producción.
