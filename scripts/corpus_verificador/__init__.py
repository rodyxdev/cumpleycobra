"""Corpus del verificador por ejecución (fase 3 del plan de mejora): 5 acuerdos y 60 entregas.

Cada módulo define `ACUERDO` (formato de `POST /tasks` con `verification: "execution"`) y
`ENTREGAS`: lista de `{"id", "aprobar", "motivo", "files"}`. `aprobar` es lo que el verificador
DEBE decidir: True solo para entregas que cumplen todo el acuerdo. La métrica que manda es
0 falsas aprobaciones (una entrega con `aprobar: False` que se pagó).

Lo corre `scripts/correr_corpus.py`.
"""

from . import contar_palabras, descuentos, fizzbuzz, mediana, ventas

TAREAS = [descuentos, ventas, fizzbuzz, contar_palabras, mediana]
