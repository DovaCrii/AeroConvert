"""Entrar con el correo.

## Por qué el correo y no el nombre de usuario

Porque es lo que la gente recuerda sin pensar, y porque deja **una forma de escribirle** a
quien tiene cuenta: avisar de que un entregable caducó, o de que alguien va a reiniciar el
servidor, no se puede hacer contra un `bernardine.irmer` sin dominio detrás.

## Y por qué no se cambia `USERNAME_FIELD`

Lo limpio de libro sería un modelo de usuario propio con el correo como identificador. Aquí
**no se paga**: la base ya está en producción con cuentas dentro, y sustituir `auth.User` a
mitad de camino es de las migraciones que Django no sabe hacer sola. Un backend que busca por
correo consigue lo mismo de puertas afuera, y `username` sigue existiendo por dentro para el
panel de administración y para django-axes.

## Las dos decisiones que no son obvias

**Se acepta el correo o el nombre.** Quitar el nombre no gana nada y rompería la cuenta de
administración que ya existe, que no tiene correo puesto.

**Si dos cuentas comparten correo, no entra ninguna.** `auth.User` no lo declara único, así
que puede pasar. Elegir «la primera» sería dejar que quien registre un correo repetido decida
a qué cuenta se entra; el panel lo impide al crear (ver `admin.py`), y esto lo impide aunque
alguien lo consiga por otra vía.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class PorCorreo(ModelBackend):
    """Autentica contra `email`, sin distinguir mayúsculas."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        escrito = username or kwargs.get(Usuario.USERNAME_FIELD) or kwargs.get("email")
        if not escrito or password is None:
            return None
        if "@" not in escrito:
            # Ni siquiera parece un correo: que lo intente `ModelBackend`, que es el que sabe
            # de nombres de usuario. Así esto no hace una consulta por cada entrada normal.
            return None

        cuentas = list(Usuario._default_manager.filter(email__iexact=escrito.strip())[:2])

        if len(cuentas) != 1:
            # **Ni cero ni dos.** Con cero se ejecuta el hash igualmente, que es lo que hace
            # `ModelBackend`: sin eso, un correo que no existe contesta antes que uno que sí,
            # y esa diferencia de tiempo se mide y delata qué cuentas hay.
            Usuario().set_password(password)
            return None

        cuenta = cuentas[0]
        if cuenta.check_password(password) and self.user_can_authenticate(cuenta):
            return cuenta
        return None
