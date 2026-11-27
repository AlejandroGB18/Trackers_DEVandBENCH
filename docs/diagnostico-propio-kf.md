# Diagnóstico de `propio_kf` (camino a la v2)

**Pregunta:** ¿por qué `propio_kf` comete 3–6 veces más cambios de identidad que los otros trackers
([`resultados-v1.md`](resultados-v1.md)), y qué hay que cambiarle?

**Regla:** test ya se usó una vez (D29). Todo cambio se **elige en ajuste** (30 secuencias). Los ejemplos de test solo
ilustran el problema; no se usan para escoger la corrección. Un número final "limpio" de la versión corregida necesita
otro conjunto de test (por ejemplo VisDrone-MOT); volver a medir en el test de UAVDT sería optimista y así se
reportaría.

## 1. Lo que muestran los datos de test (descriptivo)

En `propio_kf`, el 67 % de los cambios de identidad son de ida y vuelta entre dos tracks que ya existían, y el 79 %
coinciden con un cambio de clase del detector (car ↔ van, car ↔ truck). Ejemplos y tabla en
[`resultados-v1.md`, sección 2](resultados-v1.md#por-qué-propio_kf-cambia-de-identidad-ejemplos).

## 2. Diferencias con ByteTrack y BoT-SORT en el código

Los tres usan la misma idea: Kalman de velocidad constante, dos rondas de asociación (detecciones fuertes y luego
débiles) y los mismos umbrales de confianza. Lo que cambia:

| # | Diferencia | `propio_kf` (v1) | ByteTrack / BoT-SORT (Ultralytics) | Efecto esperado |
|---|---|---|---|---|
| H1 | **Compuerta de clase** | Una detección de otra clase no puede continuar el track | Asocian sin mirar la clase | Si el detector duda car ↔ van, nace un segundo track encima del mismo vehículo y los dos se turnan la identidad. **Principal sospechoso** |
| H2 | Umbral de la ronda débil | IoU ≥ 0.20, igual que la fuerte | IoU ≥ 0.5 | Con 0.20, una detección débil de un vecino puede "robarle" el track a otro vehículo |
| H3 | Confianza en la asociación | Solo IoU | IoU × confianza (`fuse_score`) | Ante empates de IoU, gana la detección más confiable |
| H4 | Tracks sin confirmar | Compiten con los confirmados en la 1.ª ronda y sobreviven 1 s sin detección | Van aparte, solo con las fuertes sobrantes, y mueren al primer fallo | Un track tentativo puede quitarle la detección a uno establecido |
| H5 | Cajas infladas | +3 px por lado para el IoU | Sin inflar | Ayuda con objetos chicos, pero aumenta el traslape con vecinos en tráfico denso |

Además, `propio_kf` estabiliza el Kalman con nuestra homografía, y BoT-SORT con su propio GMC. Esa es la idea central
del tracker y no se toca en este diagnóstico.

## 3. Cambios en el código (sin alterar la v1)

`VD - Trackers To Real Implementation/tracker_propio.py` tiene ahora cuatro parámetros nuevos en `ConfigPropio`.
**Sus valores por defecto reproducen la v1 exactamente**: con 300 frames y 40 objetos sintéticos, las salidas son
idénticas, cajas e IDs.

| Parámetro | v1 (defecto) | Como ByteTrack |
|---|---|---|
| `gate_clase` | `True` | `False` |
| `match_iou_debil` | `-1` (= `match_iou`, 0.20) | `0.5` |
| `fuse_score` | `False` | `True` |
| `confirmar_aparte` | `False` | `True` |
| `box_pad` (ya existía) | `3.0` | `0.0` |

La prueba propia (`python tracker_propio.py`) reproduce H1: un auto que alterna car/van recibe 2 identidades con
`gate_clase=True` y 1 sin él.

## 4. Ablación en ajuste

Manifiesto: [`benchmark/diagnostico_v2.yaml`](../benchmark/diagnostico_v2.yaml). Tiene las mismas secuencias, umbrales
y correcciones que la v1; solo cambia la lista de trackers. Los cambios se agregan uno a uno, para ver cuánto aporta
cada uno:

| Etiqueta | Cambios respecto a la v1 |
|---|---|
| `propio_v1` | ninguno (control) |
| `propio_A1_sin_clase` | H1 |
| `propio_A2_debil05` | H1 + H2 |
| `propio_A3_fusion` | H1 + H2 + H3 |
| `propio_A4_tentativos` | H1 + H2 + H3 + H4 |
| `propio_A5_sin_pad` | H1 + H5 (rama aparte) |
| `bytetrack`, `botsort` | referencias |

```bash
python bench.py detectar --split ajuste --manifiesto diagnostico_v2.yaml
python bench.py correr   --split ajuste --manifiesto diagnostico_v2.yaml --run diag_v2
python bench.py evaluar  --split ajuste --manifiesto diagnostico_v2.yaml --run diag_v2
```

**Criterio para elegir la v2,** fijado antes de ver los números: la variante con mayor AssA combinado en ajuste.
Además, su HOTA no puede quedar por debajo del de la v1 con IC 95 % (bootstrap pareado por secuencia, D28). Si dos
variantes empatan, se elige la de menos cambios. Se reportan todas.

**Lo que falta para correrla:** las detecciones de `yolo8x` de ajuste, que viven en el laboratorio
(`$BENCH_DATOS/detecciones/yolo8x/`). Con ellas, la ablación corre en la Mac.
