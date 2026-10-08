"""Las pantallas de las treinta y nueve herramientas de documentos.

## Mirar aquí, hacer en la cola

Hasta la fase 9 esto decía por qué las herramientas **no** pasaban por la cola: componer se
escribe en menos de un segundo, y esperar a un proceso en segundo plano para reordenar tres
hojas parecía absurdo. El razonamiento era bueno para Unir y malo para todo lo demás, y costó
caro sin que se viera:

- gunicorn corta la petición a los 120 s, y el OCR de un escaneo de cuarenta páginas moría a
  medias sin decir nada;
- trece de las veinte no dejaban descargar lo que salía de un archivo subido;
- y el uso no dejaba rastro: el servidor decía «0 trabajos» sin distinguir «nadie ha usado
  esto» de «se ha usado mucho, pero no aquí».

Así que ahora se separan dos cosas que antes iban juntas. **Mirar se hace aquí**, síncrono y
barato: leer la cabecera, avisar de que es un escaneo, dejar que Unir ordene las páginas,
decir que la contraseña es corta. **Hacer va a la cola**, por `cola.encolar()`, y la ficha
del trabajo trae el progreso, el recibo, la descarga con dueño, reintentar y cancelar. Ver
`tarea.py` para el proceso hijo y `motor.py` para cómo se verifica lo que sale.

La regla para lo que queda aquí: **todo lo que se pueda comprobar sin abrir el documento
entero se comprueba antes de encolar**, con el formulario delante. Descubrirlo en la cola
manda a una ficha roja y de vuelta a esta pantalla con el formulario vacío.

## Sin estado en el servidor

La receta de Unir viaja en un campo oculto del propio formulario, así que no hay sesión que
caducar ni fila que limpiar, y dos personas pueden componer a la vez sin pisarse. Es la misma
cadena que se encola al generar. Ver `receta.py`.

## Lo que se conserva del resto de la aplicación

**La ruta se comprueba contra las raíces permitidas** igual que en la inspección, y **el
original no se toca**: el corredor compara su huella antes y después de cada intento.
"""

from __future__ import annotations

from ..herramientas import HERRAMIENTAS  # noqa: F401
from ._comun import (  # noqa: F401
    MAXIMO_ARCHIVOS,
    Fila,
    _agrupar,
    _contexto,
    _entero,
    _filas,
    _indice,
    _mirar_pdf,
    _origen_del_formulario,
    _origenes_pedidos,
    _ppp,
    _ruta_de_salida_de,
    estado_de_herramientas,
)
from .pantalla_catalogos import (  # noqa: F401
    catalogo_a_excel,
    excel_a_catalogo,
)
from .pantalla_comparar import (  # noqa: F401
    comparar_vista,
)
from .pantalla_comprimir import (  # noqa: F401
    comprimir,
    ocr_vista,
)
from .pantalla_dividir import (  # noqa: F401
    dividir_vista,
)
from .pantalla_dxf_lamina import (  # noqa: F401
    dxf_lamina_vista,
)
from .pantalla_firma_digital import (  # noqa: F401
    firmar_vista,
    verificar_firmas_vista,
)
from .pantalla_fotos_dron import (  # noqa: F401
    fotos_dron_vista,
)
from .pantalla_imagenes import (  # noqa: F401
    a_imagenes_vista,
    extraer_imagenes_vista,
    imagenes_vista,
)
from .pantalla_imagenes_lote import (  # noqa: F401
    imagenes_lote_vista,
)
from .pantalla_inicio import (  # noqa: F401
    inicio,
    texto,
    vuelos,
)
from .pantalla_markdown import (  # noqa: F401
    EXTENSIONES_DE_MARKDOWN,
    a_markdown,
    de_markdown,
)
from .pantalla_office import (  # noqa: F401
    a_word_vista,
    office_vista,
)
from .pantalla_paginas import (  # noqa: F401
    firma_visible_vista,
    formularios_vista,
    marca_vista,
    metadatos_vista,
    numerar_vista,
)
from .pantalla_pdfa import (  # noqa: F401
    pdf_a_vista,
)
from .pantalla_portada import (  # noqa: F401
    portada_vista,
)
from .pantalla_proteger import (  # noqa: F401
    _problema_de_proteger,
    proteger_vista,
)
from .pantalla_redactar import (  # noqa: F401
    redactar_vista,
)
from .pantalla_reparar import (  # noqa: F401
    html_a_pdf_vista,
    reparar_vista,
)
from .pantalla_tamano import (  # noqa: F401
    tamano_vista,
)
from .pantalla_telemetria import (  # noqa: F401
    telemetria_vista,
)
from .pantalla_unir import (  # noqa: F401
    _generar,
    _receta_inicial,
    componer_organizar_vista,
    componer_vista,
    miniatura,
    organizar,
    unir,
)
from .pantalla_vuelo import (  # noqa: F401
    vuelo_datos,
    vuelo_dron_vista,
    vuelo_miniatura,
    vuelo_ver,
)
