# Benchmark de trackers para dron

El benchmark compara trackers de vehículos en video de dron con ego-movimiento. Responde dos preguntas: qué tan estable es la identidad cuando el dron se mueve, y si el decisor distingue lo que de verdad se mueve en el mundo.

## Datos y particiones

**Secuencia de ajuste**:
Secuencia del train de UAVDT. Solo sirve para elegir y calibrar (detector, umbrales, cámara de UCMC, exclusiones y tramos de ego); nunca se reporta como resultado.
_Avoid_: train, validación

**Secuencia de test**:
Secuencia del test de UAVDT. Es la única que se reporta, y se corre una sola vez, con todo congelado.
_Avoid_: evaluación (a secas)

**Congelar**:
Dejar una decisión por escrito antes de correr test. Después ya no se cambia.

**Grupo de vuelo**:
Clase de vuelo según los atributos de vista y altitud de UAVDT: cenital, oblicua_baja u oblicua_alta.
_Avoid_: toma, categoría

**Estrato excluido**:
Grupo de vuelo o condición de iluminación que sale del ranking porque el detector rinde demasiado poco en ajuste.

## Movimiento

**Ego-movimiento**:
Movimiento aparente de la imagen causado por el dron.
_Avoid_: movimiento de cámara

**Tramo de ego**:
Intervalo de frames clasificado por su ego-movimiento, relativo al que existe en UAVDT: bajo, medio o alto (o solo bajo y alto si no alcanzan los datos), más H no fiable.
_Avoid_: bin, estacionario/suave/rápido (implican valores absolutos)

**Movimiento real**:
Etiqueta del GT (`moving`) que indica si el vehículo se desplaza en el mundo.
_Avoid_: móvil, dinámico

**Decisión de movimiento**:
Lo que afirma el decisor de un tracker (`en_movimiento`). Se compara contra el movimiento real.
_Avoid_: detección de movimiento

## Resultados

**Ranking**:
La comparación principal. Tiene una entrada por tracker: propio_kf, ByteTrack, BoT-SORT y `ucmc_grupo_train`.

**Referencia**:
Resultado que se reporta fuera del ranking, como insight; por ejemplo, `ucmc` automático.

**Cota**:
Referencia que usa información de test, como la cámara oráculo de UCMC. Muestra el máximo alcanzable y nunca compite.
_Avoid_: oráculo (como sinónimo de "mejor versión")
