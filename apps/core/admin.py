"""Identidad del panel de administración.

Cinco líneas, y la que importa es el encabezado: quien entra tiene que saber **en qué
instalación está** antes de tocar nada.
"""

from django.contrib import admin

admin.site.site_header = "AeroConvert — administración"
admin.site.site_title = "AeroConvert"
admin.site.index_title = "Trabajos, bitácora y preajustes"
