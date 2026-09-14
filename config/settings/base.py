"""Ajustes comunes a los cuatro entornos: `dev`, `prod`, `taller` y `nube`.

Los dos modos de AeroConvert -- `taller` y `nube` -- **no son dos productos**: son el mismo
codigo con una politica distinta de entrada y salida. `MODO` se lee aca y lo consultan el
formulario de alta, el runner y un procesador de contexto que pinta la chapa en todas las
pantallas.
"""

from pathlib import Path

from decouple import config
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# --- Modo de operacion -----------------------------------------------------

MODO_TALLER = "taller"
MODO_NUBE = "nube"
MODO = config("AEROCONVERT_MODO", default=MODO_TALLER)

# En modo taller la ruta de origen la teclea una persona, asi que sin esta lista la
# aplicacion seria un primitivo de lectura del disco entero. Se valida en `apps.core.modo`
# al arrancar, no aca, para poder dar un mensaje que se entienda.
RAICES_PERMITIDAS = config("AEROCONVERT_RAICES_PERMITIDAS", default="")

# El tope de lo que se sube por el navegador. **Los archivos grandes no suben**: llegan por
# la carpeta compartida, que es reanudable y no pasa por HTTP. Esto es para los PDF y poco
# mas, asi que 200 MB y no dos gigas: un tope bajo hace que una subida desbocada no pueda
# importar.
#
# Se comprueba en tres sitios, y solo el ultimo es inevadible: `client_max_body_size` en
# nginx, `apps/core/manejador.py` mientras llega, y `ArchivoSubido.clean()`.
TOPE_MB = config("AEROCONVERT_TOPE_MB", default=200, cast=int)

# El nuestro, que cuenta lo que llega y corta. Ver `apps/core/manejador.py`.
FILE_UPLOAD_HANDLERS = ["apps.core.manejador.SubidaConTope"]

# --- Retencion y disco -----------------------------------------------------
# GDAL necesita un archivo de verdad, con acceso aleatorio: **algo toca disco siempre**. Lo
# que se elige aqui es cuanto sobrevive y cuanto se deja gastar.

#: `efimera` | `temporal` | `permanente`. Vacio = `permanente` en taller (la salida vive
#: junto al original, en el disco de la persona) y `efimera` en nube.
RETENCION = config("AEROCONVERT_RETENCION", default="")
#: Donde viven las salidas mientras esperan a ser descargadas. Carpeta propia y no el
#: temporal del sistema: asi el presupuesto se puede medir y el barrido sabe donde mirar.
CARPETA_DE_TRABAJO = config("AEROCONVERT_CARPETA_DE_TRABAJO", default="")
#: Cuanto tiempo sobrevive una salida efimera que nadie llego a descargar.
EFIMERA_MINUTOS = config("AEROCONVERT_EFIMERA_MINUTOS", default=30, cast=int)
#: Cuanto sobrevive con politica `temporal`.
RETENCION_HORAS = config("AEROCONVERT_RETENCION_HORAS", default=24, cast=int)
#: **Lo que de verdad protege el disco.** Un trabajo que no cabe espera en la cola en vez
#: de llenar el volumen. Un servidor sin disco no da un error: deja de funcionar entero.
PRESUPUESTO_GB = config("AEROCONVERT_PRESUPUESTO_GB", default=20, cast=int)

#: Donde van las copias de la base, y cuantos dias se guardan. Fuera del arbol de codigo en
#: la VM, y **con al menos una copia fuera de la maquina**: un respaldo en el mismo disco
#: que la base no protege del escenario que mas importa, que es que se muera el disco.
CARPETA_DE_RESPALDOS = config("AEROCONVERT_RESPALDOS", default="")
RESPALDOS_DIAS = config("AEROCONVERT_RESPALDOS_DIAS", default=14, cast=int)

# --- Motores externos ------------------------------------------------------
# Ninguno es dependencia del paquete: se sondean en tiempo de ejecucion y su ausencia
# apaga una fila de la matriz de capacidades, no rompe la aplicacion.

GDAL_BIN = config("AEROCONVERT_GDAL_BIN", default="")
PDAL_BIN = config("AEROCONVERT_PDAL_BIN", default="")
ECW_ENCODE_KEY = config("AEROCONVERT_ECW_ENCODE_KEY", default="")
ECW_ENCODE_COMPANY = config("AEROCONVERT_ECW_ENCODE_COMPANY", default="")
ECW_BIN = config("AEROCONVERT_ECW_BIN", default="")
ODA_CONVERTER = config("AEROCONVERT_ODA_CONVERTER", default="")

# --- Ejecucion -------------------------------------------------------------

# Por omision uno. GDAL ya usa todos los nucleos con `GDAL_NUM_THREADS=ALL_CPUS`, y dos
# conversiones compitiendo por el mismo disco es mas lento, no mas rapido.
TRABAJOS_SIMULTANEOS = config("AEROCONVERT_TRABAJOS_SIMULTANEOS", default=1, cast=int)
SEGUNDOS_POR_GB = config("AEROCONVERT_SEGUNDOS_POR_GB", default=900, cast=int)
SILENCIO_MAXIMO_S = config("AEROCONVERT_SILENCIO_MAXIMO_S", default=600, cast=int)

# El despachador arranca un hilo. Queda apagado por omision y **las pruebas nunca lo
# encienden**: usan `manage.py procesar_trabajos --una-vez`, que corre el mismo bucle de
# forma determinista.
#
# En la estacion de trabajo se enciende: `run.ps1` arranca **un** proceso con `--noreload`,
# asi que hay un solo despachador y es lo comodo.
#
# **En la VM va apagado, tambien en el proceso web**, y ahi el despachador es una unidad de
# systemd propia con `manage.py procesar_trabajos`. Con varios obreros de gunicorn
# arrancarian varios despachadores, y aunque reclamar un trabajo si es atomico, el tope de
# `TRABAJOS_SIMULTANEOS` se comprueba con un `count()` que **no** lo es: dos obreros leen
# cero a la vez y arrancan dos conversiones. Dos nubes de puntos suman sus dos techos de
# memoria y se llevan la maquina.
#
# La guarda que hay dentro (`RUN_MAIN`) no protege de esto: es especifica del recargador de
# `runserver` y bajo gunicorn no vale nada.
CONVERSION_DISPATCHER_ENABLED = config("AEROCONVERT_DESPACHADOR", default=False, cast=bool)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crispy_forms",
    "crispy_bootstrap5",
    "rest_framework",
    "axes",
    "apps.core",
    "apps.formats",
    "apps.engines",
    "apps.jobs",
    "apps.targets",
    "apps.presets",
    # Las familias de motor. `pointcloud`, `vector` y `mesh` estan vacias a proposito
    # desde la fase 0: asi la fase que las llene no tiene que tocar `INSTALLED_APPS`, y el
    # registro se prueba desde el primer dia con una familia sin motores.
    "apps.raster",
    "apps.pointcloud",
    "apps.vector",
    "apps.mesh",
    "apps.documents",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
    # django-axes va al final para ver el request y el usuario ya resueltos.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # La chapa del modo va en `base.html`, o sea en todas las pantallas: saber
                # si los archivos salen del disco o no es lo primero que hay que ver.
                "apps.core.context_processors.modo",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": config("DB_PATH", default=str(BASE_DIR / "db.sqlite3")),
        # WAL no es opcional aca: el despachador escribe progreso cada pocos segundos
        # mientras el navegador sondea la misma base. Sin WAL, "database is locked".
        "OPTIONS": {
            "timeout": 20,
            "init_command": (
                "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;PRAGMA busy_timeout=20000;"
            ),
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LANGUAGE_CODE = "es"
LANGUAGES = [
    ("en", _("English")),
    ("es", _("Spanish")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = config("TIME_ZONE", default="America/Santiago")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Donde van los archivos que sube la gente. **Sin esto Django escribe relativo al directorio
# de trabajo del proceso**, que es la raiz del repositorio: `ConversionJob.source_upload`
# declara `upload_to="entradas/%Y/%m/"` y acababa creando `entradas/2026/09/` dentro del
# arbol de codigo. De ahi al commit hay un `git add .`.
#
# No hay `MEDIA_URL` a proposito: **nada de esto se sirve por URL**. Un archivo subido es de
# quien lo subio, y se entrega por una vista que comprueba el dueno, nunca por una ruta
# publica que solo depende de acertar el nombre.
MEDIA_ROOT = Path(config("AEROCONVERT_MEDIA", default=str(BASE_DIR / "entradas")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # El de whitenoise, pero sin perseguir los `.map` que no vendorizamos.
    # El motivo entero esta en `apps/core/estaticos.py`.
    "staticfiles": {"BACKEND": "apps.core.estaticos.AlmacenDeEstaticos"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:convertir"
LOGOUT_REDIRECT_URL = "login"

# --- Las cookies llevan apellido ------------------------------------------
#
# **Las cookies no distinguen el puerto.** En el servidor compartido, AeroControl vive en
# `p340.<tailnet>.ts.net` y AeroConvert en `p340.<tailnet>.ts.net:8443`: para el navegador es
# **el mismo sitio**. Con el nombre que Django trae de fabrica, las dos escriben `sessionid`
# y `csrftoken` y cada una borra la sesion de la otra -- entrar en una te echa de la otra, y
# el sintoma es «me pide entrar otra vez al cambiar de pantalla», que no se parece en nada a
# la causa.
#
# Lo mismo pasa en la estacion de trabajo con dos aplicaciones en `localhost:8000` y
# `localhost:8001`, asi que esto va en la configuracion comun y no solo en la del servidor.
SESSION_COOKIE_NAME = "aeroconvert_sesion"
CSRF_COOKIE_NAME = "aeroconvert_csrf"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

AXES_FAILURE_LIMIT = 8
AXES_COOLOFF_TIME = 1

# Se bloquea la **pareja** usuario + IP, y no una de las dos por separado. Los corchetes
# de dentro son los que lo dicen: axes trata una lista anidada como una combinacion.
#
# Ninguna de las dos opciones simples sirve en una oficina:
#
# - Solo por IP era lo que habia, y detras de nginx **todo el equipo comparte la IP del
#   proxy**. Ocho intentos fallidos de cualquiera dejaban a los demas fuera una hora.
# - Solo por usuario deja que alguien bloquee a otro a proposito, fallando ocho veces con
#   su nombre.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]

# Y para que «ip_address» signifique algo detras de nginx. Sin esto axes lee `REMOTE_ADDR`,
# que con un proxy delante es siempre la direccion del proxy: todos comparten IP y la
# pareja de arriba degenera otra vez en «solo usuario».
#
# **No se usan `AXES_IPWARE_*`**, aunque sea lo que sale al buscar: `axes/helpers.py:208`
# solo mira esos ajustes si `django-ipware` esta instalado, y no lo esta -- axes 8.3.1
# depende solo de `asgiref` y `django`. Ponerlos seria codigo muerto que ademas parece que
# funciona. Este gancho es el primero que consulta (`helpers.py:193`) y no pide nada nuevo.
AXES_CLIENT_IP_CALLABLE = "apps.core.ip.ip_del_cliente"

# Entrar bien borra la cuenta de fallos. Por omision es `False`, asi que siete
# equivocaciones repartidas en meses se acumulan y la octava, un dia cualquiera, bloquea.
AXES_RESET_ON_SUCCESS = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aeroconvert",
    }
}

# --- Bitacora --------------------------------------------------------------
# **Sin esto, un error 500 en produccion no deja rastro en ninguna parte.** No es una
# exageracion: el manejador de consola que trae Django por omision lleva el filtro
# `require_debug_true`, asi que con `DEBUG=False` no escribe nada; y `django.request` manda
# los 500 a `mail_admins`, con `ADMINS` sin definir. Igual se pierden los
# `registro.exception(...)` del despachador. La aplicacion falla en silencio.
#
# ## Va a la salida de error, no a un fichero
#
# Y no es por comodidad. El mismo fichero lo escribirian **cuatro procesos** -- dos obreros
# de gunicorn, el despachador, y los `manage.py` que se corran a mano --, y
# `RotatingFileHandler` no es seguro entre procesos: cuando dos cruzan el umbral a la vez,
# los dos renombran y una rotacion se lleva por delante el fichero de la otra. Se pierde
# justo el tramo con mas actividad, que es el que se iba a leer.
#
# Bajo systemd, la salida de error va a journald, que ya rota, ya es seguro con varios
# procesos, y ademas junta en una sola linea de tiempo lo de la aplicacion, lo de gunicorn,
# los reinicios del servicio y al matador por falta de memoria cuando se lleve a PDAL. Que
# es exactamente la correlacion que hace falta cuando una conversion muere.
#
# Si algun dia hace falta un fichero -- para mandarlo fuera --, el manejador correcto es
# `WatchedFileHandler` con logrotate en modo `copytruncate`, **no** el rotatorio.

NIVEL_DE_REGISTRO = config("AEROCONVERT_LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    # **No** se desactivan los de las bibliotecas: pypdf y pyproj avisan de cosas que luego
    # explican un resultado raro.
    "disable_existing_loggers": False,
    "formatters": {
        # El numero de proceso no es decoracion: con dos obreros y el despachador, «quien
        # escribio esto» se contesta con esa columna y con ninguna otra.
        "aeroconvert": {
            "format": "{asctime} {levelname:<7} {process:>6} {name} — {message}",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "style": "{",
        },
    },
    "handlers": {
        "consola": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "aeroconvert",
            "level": "DEBUG",
        },
    },
    "loggers": {
        # Todo lo nuestro de un golpe: los modulos usan `getLogger(__name__)`, que da
        # `apps.jobs.despachador`, `apps.jobs.runner`... Un solo logger los cubre.
        "apps": {"handlers": ["consola"], "level": NIVEL_DE_REGISTRO, "propagate": False},
        "django": {"handlers": ["consola"], "level": "INFO", "propagate": False},
        # ERROR y no WARNING **a proposito**: en WARNING, `django.request` escribe una linea
        # por cada 404, y aqui el 404 es un camino normal -- una salida que ya caduco. El
        # registro se llenaria de ruido justo donde hay que buscar la senal.
        "django.request": {"handlers": ["consola"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["consola"], "level": "WARNING", "propagate": False},
        # Entradas bloqueadas y desbloqueos: el registro que se lee el dia que alguien dice
        # «no puedo entrar».
        "axes": {"handlers": ["consola"], "level": "INFO", "propagate": False},
        # En DEBUG escupe una linea por consulta, y el despachador hace una cada dos segundos.
        "django.db.backends": {"handlers": ["consola"], "level": "WARNING", "propagate": False},
    },
}
