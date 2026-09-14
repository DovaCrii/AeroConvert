"""Los ficheros de `despliegue/` y `scripts/*.sh` también son código.

Se leen y se afirma lo que tienen dentro, con el mismo patrón que `test_arranque.py` usa
sobre `run.ps1`. No prueban que la VM funcione — eso solo lo dice la VM — pero sí impiden que
alguien «simplifique» una línea de la que depende algo que no se ve desde ahí.
"""

from pathlib import Path

import pytest
from django.conf import settings

DESPLIEGUE = Path(settings.BASE_DIR) / "despliegue"
GUIONES = Path(settings.BASE_DIR) / "scripts"


def _leer(ruta: Path) -> str:
    assert ruta.exists(), f"Falta {ruta}. Si cambió de sitio, actualiza esto."
    return ruta.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def web() -> str:
    return _leer(DESPLIEGUE / "aeroconvert.service")


@pytest.fixture(scope="module")
def obrero() -> str:
    return _leer(DESPLIEGUE / "aeroconvert-obrero.service")


@pytest.fixture(scope="module")
def nginx() -> str:
    """La configuración **sin los comentarios**.

    Los comentarios de este fichero explican precisamente lo que no hay que poner, así que
    buscar en ellos daría por presente justo lo que se quiere ausente.
    """
    crudo = _leer(DESPLIEGUE / "aeroconvert.nginx.conf")
    return "\n".join(linea for linea in crudo.splitlines() if not linea.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def desplegar() -> str:
    return _leer(GUIONES / "desplegar.sh")


class TestElServicioWeb:
    def test_no_arranca_el_despachador(self, web: str):
        """Con varios obreros de gunicorn arrancarían varios despachadores, y el tope de
        trabajos simultáneos se comprueba con un `count()` que no es atómico: dos leen cero
        a la vez y arrancan dos conversiones."""
        assert "AEROCONVERT_DESPACHADOR=0" in web

    def test_usa_gthread_y_no_sync(self, web: str):
        """El obrero `sync` solo avisa al árbitro **entre** peticiones, así que una descarga
        de varios gigabytes hace que gunicorn lo mate a mitad. El síntoma —«la descarga se
        corta sola»— no se parece en nada a la causa."""
        assert "--worker-class gthread" in web
        assert "--threads" in web

    def test_el_tiempo_maximo_es_explicito(self, web: str):
        assert "--timeout" in web

    def test_escucha_en_un_socket_unix(self, web: str):
        """**Es la premisa de seguridad de `apps/core/ip.py`.** Con un socket unix, la única
        forma de llegar a la aplicación es a través de nginx, y por eso se puede confiar en
        la cabecera que dice de dónde viene la petición. Con un puerto TCP, cualquiera en la
        red puede mandarla a mano y el bloqueo por intentos fallidos se vuelve evadible."""
        assert "--bind unix:" in web

    def test_fija_el_modulo_de_ajustes(self, web: str):
        assert "DJANGO_SETTINGS_MODULE=config.settings.prod" in web


class TestElObrero:
    def test_es_el_unico_que_despacha(self, obrero: str):
        assert "AEROCONVERT_DESPACHADOR=1" in obrero

    def test_barre_al_arrancar(self, obrero: str):
        """`_bucle()` **no** hace el barrido de arranque: ese vive en `arrancar()`, que el
        comando no llama. Y es el que importa — el único momento en que se sabe con certeza
        que ningún trabajo está corriendo."""
        assert "ExecStartPre" in obrero
        assert "barrer" in obrero

    def test_tiene_un_tope_de_memoria(self, obrero: str):
        """Para que el núcleo mate al hijo de PDAL **dentro de este grupo** en vez de dejar
        que el matador del sistema elija — y el sistema suele elegir al servidor web."""
        assert "MemoryMax=" in obrero

    def test_se_lleva_a_sus_hijos_al_parar(self, obrero: str):
        """Un motor huérfano seguiría escribiendo un parcial que ya no reclama nadie."""
        assert "KillMode=control-group" in obrero


class TestNginx:
    def test_recupera_la_direccion_de_verdad_antes_de_nada(self, nginx: str):
        """**La trampa de tener Tailscale delante, y ya se coló una vez.**

        `proxy_set_header X-Forwarded-For $remote_addr` es lo correcto cuando nginx es el
        primer salto. Aquí el primero es Tailscale, así que `$remote_addr` sería `127.0.0.1`
        para todo el mundo y el bloqueo por intentos fallidos volvería a ser «todos comparten
        una IP». `real_ip_header` es lo que lo arregla.
        """
        assert "real_ip_header" in nginx
        assert "set_real_ip_from" in nginx

    def test_reenvia_la_cabecera_de_origen(self, nginx: str):
        import re

        assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;", nginx)
        assert "$proxy_add_x_forwarded_for" not in nginx

    def test_frena_los_intentos_de_entrada(self, nginx: str):
        """Contra un extremo público, sin esto alguien prueba contraseñas tan rápido como
        aguante la máquina. django-axes bloquea por usuario, que es otra cosa: no frena el
        chorro."""
        assert "limit_req_zone" in nginx
        assert "limit_req zone=entrar" in nginx

    def test_el_tope_de_cuerpo_deja_pasar_una_subida(self, nginx: str):
        """Si va por debajo de `AEROCONVERT_TOPE_MB`, nginx corta antes y la persona ve un
        error del servidor en vez del mensaje que explica qué hacer."""
        import re

        from django.conf import settings

        hallado = re.search(r"client_max_body_size\s+(\d+)m", nginx)
        assert hallado, "falta client_max_body_size"
        assert int(hallado.group(1)) > settings.TOPE_MB

    def test_no_escucha_fuera_del_bucle_local(self, nginx: str):
        """Quien publica es Tailscale. Escuchar en 0.0.0.0 abriría una segunda puerta sin
        TLS por la red de la oficina."""
        assert "listen 127.0.0.1:" in nginx
        assert "listen 0.0.0.0" not in nginx

    def test_no_bufa_las_descargas(self, nginx: str):
        """Con el bufado por omisión, nginx escribe la respuesta entera en disco antes de
        mandar el primer byte: un archivo de 20 GB en el disco del sistema."""
        assert "proxy_buffering off" in nginx

    def test_no_sirve_los_estaticos_por_su_cuenta(self, nginx: str):
        """Los serviría sin el `Cache-Control: immutable` de whitenoise, y eso reabre el
        fallo de `test_arranque.py`: HTML nuevo con la hoja de estilos vieja."""
        assert "location /static/" not in nginx

    def test_ni_lo_que_sube_la_gente(self, nginx: str):
        """Si `MEDIA_ROOT` se sirviera por URL, la URL sería el permiso."""
        assert "location /media/" not in nginx


class TestElGuionDeDespliegue:
    def test_exige_un_env(self, desplegar: str):
        assert ".env" in desplegar

    def test_fija_el_modulo_de_ajustes(self, desplegar: str):
        assert "DJANGO_SETTINGS_MODULE=config.settings.prod" in desplegar

    def test_comprueba_antes_de_migrar(self, desplegar: str):
        """Un `.env` sin `ALLOWED_HOSTS` tiene que parar antes de tocar la base, no
        después."""
        assert desplegar.index("check --deploy") < desplegar.index("migrate")

    def test_recolecta_los_estaticos_antes_de_arrancar(self, desplegar: str):
        """Sin `collectstatic`, **todas** las páginas dan 500. Es el mismo invariante que
        `test_arranque.py` vigila en `run.ps1`."""
        assert desplegar.index("collectstatic") < desplegar.index("systemctl restart")

    def test_espera_a_la_sonda(self, desplegar: str):
        assert "/salud/" in desplegar

    def test_para_ante_el_primer_fallo(self, desplegar: str):
        assert "set -euo pipefail" in desplegar


class TestElEjemploDeConfiguracion:
    """Cierra el agujero de verdad: quien copie `.env.example` tiene que poder arrancar.

    `prod.py` lee `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` con omisión vacía, así que si el
    ejemplo no los menciona, el despliegue devuelve **400 a todo** y con `DEBUG=False` no
    dice por qué.
    """

    @pytest.fixture
    def ejemplo(self) -> str:
        return _leer(Path(settings.BASE_DIR) / ".env.example")

    @pytest.mark.parametrize(
        "variable",
        ["ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "SECRET_KEY", "AEROCONVERT_RAICES_PERMITIDAS"],
    )
    def test_estan_las_obligatorias(self, ejemplo: str, variable: str):
        assert variable in ejemplo

    def test_dice_que_el_modo_nube_no_sirve(self, ejemplo: str):
        assert "no esta escrita" in ejemplo

    def test_y_documenta_el_despachador(self, ejemplo: str):
        assert "AEROCONVERT_DESPACHADOR" in ejemplo


class TestGunicorn:
    def test_esta_declarado_y_fuera_de_las_dependencias_normales(self):
        """En un grupo aparte: la estación de trabajo corre con `runserver` y no tiene por
        qué bajarse un servidor WSGI."""
        crudo = (Path(settings.BASE_DIR) / "pyproject.toml").read_text(encoding="utf-8")
        assert "gunicorn" in crudo
        cabecera = crudo.index("[dependency-groups]")
        assert crudo.index("gunicorn") > cabecera, "gunicorn no puede estar en dependencies"
