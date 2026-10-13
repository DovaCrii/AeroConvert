"""`manage.py tino_probar`: lista los modelos que la clave ve y hace una pregunta de prueba.

Sirve para elegir `AEROCONVERT_TINO_MODELO` en p340. Sin clave dice que falta y no llama a
nadie. **Nunca imprime la clave**; la pregunta de prueba es fija y no lleva datos de nadie.
"""

from urllib.parse import urlparse

from django.core.management.base import BaseCommand

from apps.tino import fuera


class Command(BaseCommand):
    help = "Lista los modelos disponibles con la clave de Tino y hace una pregunta de prueba."

    def handle(self, *args, **opciones):
        if not fuera._clave():
            self.stdout.write("Falta AEROCONVERT_TINO_API_KEY en el .env: no se llama a nadie.")
            return
        destino = urlparse(fuera._base())  # solo esquema y servidor: la ruta puede llevar datos
        self.stdout.write(f"Base: {destino.scheme}://{destino.hostname}")
        try:
            nombres = fuera.listar_modelos()
        except fuera._Rechazo as rechazo:
            self.stdout.write(f"No se pudo listar los modelos ({rechazo}).")
        else:
            self.stdout.write(f"{len(nombres)} modelos:")
            for nombre in nombres:
                self.stdout.write(f"  {nombre}")
        self.stdout.write(f"Se probaría, en orden: {', '.join(fuera.modelos())}")
        consulta = fuera.consultar("¿Qué es un GeoTIFF en una frase?")
        if consulta:
            self.stdout.write(f"Respuesta de {consulta.modelo}: {consulta.texto}")
        else:
            self.stdout.write(f"Sin respuesta ({consulta.codigo}).")
