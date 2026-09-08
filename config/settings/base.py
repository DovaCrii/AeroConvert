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

# Solo aplica en modo nube.
TOPE_MB = config("AEROCONVERT_TOPE_MB", default=2048, cast=int)

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
CONVERSION_DISPATCHER_ENABLED = False

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
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:mesa"
LOGOUT_REDIRECT_URL = "login"

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
AXES_LOCKOUT_PARAMETERS = ["ip_address"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aeroconvert",
    }
}
