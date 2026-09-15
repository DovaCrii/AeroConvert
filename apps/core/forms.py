"""El formulario de entrada.

Existe solo para vestir los campos. El `AuthenticationForm` de Django los renderiza sin
clase ninguna, así que salían como dos recuadros grises de anchos distintos — uno en línea
con su etiqueta y el otro debajo. Se veía descuidado justo en la primera pantalla, que es
donde alguien decide si la herramienta parece seria.

No se toca la lógica de autenticación: eso lo hace Django, y `django-axes` frena el tanteo.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm


class FormularioDeEntrada(AuthenticationForm):
    """El campo sigue llamándose `username` por dentro, y pide el correo por fuera.

    **El nombre del campo no se toca.** `AuthenticationForm` lo espera así, y django-axes
    cuenta los intentos fallidos por lo que venga en él: renombrarlo dejaría el bloqueo por
    tanteo contando otra cosa, o nada. Quien resuelve el correo es
    `apps.core.autenticacion.PorCorreo`.

    La etiqueta dice «Correo» y no «Correo o usuario» a propósito: el segundo es más exacto y
    obliga a decidir a quien solo quiere entrar. El nombre de usuario sigue funcionando para
    quien lo tenga — la cuenta de administración del servidor, sobre todo — pero no es lo que
    se anuncia.
    """

    username = forms.CharField(
        label="Correo",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autofocus": True,
                # `email` y no `username`: es lo que hace que el gestor de contraseñas y el
                # autorrelleno del móvil ofrezcan lo correcto.
                "autocomplete": "email",
                "inputmode": "email",
                "placeholder": "tu.nombre@jej.cl",
            }
        ),
    )
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "••••••••",
            }
        ),
    )
