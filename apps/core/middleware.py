"""Politica de seguridad de contenido.

`'self'` y nada mas: Bootstrap y htmx estan vendorizados en `static/vendor/`, no vienen de
un CDN. Sin `'unsafe-inline'` en `script-src`, que es lo que obliga a que el interruptor de
tema sea un archivo y no una etiqueta suelta en el `<head>`.
"""

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # Bootstrap trae estilos en linea en algunos componentes propios, y las barras de
        # progreso llevan su ancho como atributo `style`. Es la unica concesion.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", CSP)
        response.setdefault("Referrer-Policy", "same-origin")
        return response


class LimiteDeCuerpoMiddleware:
    """Corta un cuerpo enorme **antes** de que Django lo lea.

    A-01 de la auditoría de seguridad del 2026-10-05. `CsrfViewMiddleware` lee `request.POST` para
    buscar el token, y eso analiza el cuerpo multipart entero con nuestro manejador, que lo
    escribe a un temporal hasta cortarlo en `TOPE_MB`. Un anónimo —sin sesión, sin siquiera
    CSRF válido— podía así hacer que el servidor recibiera y escribiera 2 GB por petición contra
    cualquier ruta que acepte POST, varias a la vez, antes de que nadie mirara el login.

    Va **después de `AuthenticationMiddleware`** (para saber quién es) y por tanto antes de que
    el CSRF abra la boca, porque este mira el cuerpo en `process_view` y no en `process_request`.
    La decisión usa solo la cabecera `Content-Length`, que no cuesta leer nada:

    - **Anónimo:** como mucho `LIMITE_DE_CUERPO_ANONIMO_BYTES` (1 MiB; un formulario de entrada
      pesa unos cientos de bytes).
    - **Con sesión:** como mucho `TOPE_MB` más un margen para el resto del formulario. El
      manejador ya cortaba, pero después de escribir; esto lo evita.

    Responde 413 sin cuerpo. Una petición sin `Content-Length` (troceada) no se juzga aquí: la
    sigue cortando el manejador.
    """

    MARGEN_BYTES = 10 * 1_048_576

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("POST", "PUT", "PATCH") and self._es_demasiado(request):
            from django.http import HttpResponse

            return HttpResponse(status=413)
        return self.get_response(request)

    def _es_demasiado(self, request) -> bool:
        from django.conf import settings

        try:
            largo = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return True  # una cabecera que no es un número no es una petición legítima
        if largo <= 0:
            return False

        if request.user.is_authenticated:
            tope = int(getattr(settings, "TOPE_MB", 0)) * 1_048_576
            return bool(tope) and largo > tope + self.MARGEN_BYTES

        return largo > int(getattr(settings, "LIMITE_DE_CUERPO_ANONIMO_BYTES", 1_048_576))
