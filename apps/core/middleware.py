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
