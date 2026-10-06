"""Una prueba que vacía el registro de motores no puede dejarlo vacío para las demás.

`apps/raster/test_lectura_propietaria.py` terminaba con `registry.limpiar()` y una de GNSS y 21
del dashboard fallaban solo en un orden de ejecución distinto del del CI. La fixture
`registro_de_motores_intacto` (en el `conftest.py` de la raíz) lo impide; estas dos pruebas lo
comprueban: la primera vacía el registro a propósito y la segunda, que corre después, tiene que
encontrarlo como estaba. Van en una clase para que el orden sea el de escritura.
"""

from __future__ import annotations

from apps.engines import registry

#: Motores que registran las aplicaciones al arrancar (`apps.py::ready`), no las pruebas.
QUE_DEBE_HABER = {"trimble-rinex", "rtklib-convbin"}


class TestElRegistroSobrevive:
    def test_primero_una_prueba_lo_vacia_a_proposito(self):
        assert QUE_DEBE_HABER <= {m.id for m in registry.todos()}
        registry.limpiar()
        assert not registry.todos()

    def test_despues_la_siguiente_lo_encuentra_como_estaba(self):
        presentes = {m.id for m in registry.todos()}
        assert QUE_DEBE_HABER <= presentes, f"el registro quedó vacío o a medias: {presentes}"
