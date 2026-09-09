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
    username = forms.CharField(
        label="Usuario",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autofocus": True,
                "autocomplete": "username",
                "placeholder": "tu usuario",
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
