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
| H1 | **Compuerta de clase** | Una detección de otra clase no puede continuar el track | Asocian sin mirar la clase | Si el detector duda car ↔ van, nace un segundo track encima del mismo vehículo y los dos se turnan la identidad. Principal sospechoso antes de la ablación; **resultó secundario** (§6) |
| H2 | Umbral de la ronda débil | IoU ≥ 0.20, igual que la fuerte | IoU ≥ 0.5 | Con 0.20, una detección débil de un vecino puede "robarle" el track a otro vehículo |
| H3 | Confianza en la asociación | Solo IoU | IoU × confianza (`fuse_score`) | Ante empates de IoU, gana la detección más confiable |
| H4 | Tracks sin confirmar | Compiten con los confirmados en la 1.ª ronda y sobreviven 1 s sin detección | Van aparte, solo con las fuertes sobrantes, y mueren al primer fallo | Un track tentativo puede quitarle la detección a uno establecido. **Causa principal según la ablación** (§6) |
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

Se corre en el laboratorio junto con la v1.1: [`guia-laboratorio-v1_1.md`](guia-laboratorio-v1_1.md).
`bench.py` rechaza este manifiesto con cualquier split que no sea `ajuste`.

## 5. Relación con la v1.1 (D35)

H1 no es solo un hallazgo de la ablación. Es un error de implementación de D7, que se decidió antes de ver test: la
clase no debía influir. Por eso H1, y solo H1, se corrige en test como v1.1, declarada como desviación del protocolo
([`benchmark/DECISIONS.md`, D35](../benchmark/DECISIONS.md)). H2–H5 se eligen en ajuste y quedan para la v2.

## 6. Resultado de la ablación en ajuste

Corrida en el laboratorio el 2026-11-27 (`runs/diag_v2`). Combinado de las 30 secuencias de ajuste, protocolo `todos`.
Δ contra `propio_v1` con bootstrap pareado (D28) y 2 000 réplicas. Script: `benchmark/analisis/ablacion.py`. Tablas:
[`diagnostico-propio-kf/ablacion.csv`](diagnostico-propio-kf/ablacion.csv) y
[`metricas_ajuste.csv`](diagnostico-propio-kf/metricas_ajuste.csv) (por secuencia).

| Variante | Cambios | HOTA | AssA | IDF1 | IDSW | ΔHOTA vs v1 [IC 95 %] | ΔAssA vs v1 [IC 95 %] | ΔHOTA vs BoT-SORT [IC 95 %] |
|---|---|---|---|---|---|---|---|---|
| `propio_v1` | — | 58.2 | 63.7 | 74.3 | 2 954 | | | −2.9 [−4.1, −1.5] |
| `propio_A1_sin_clase` | H1 | 58.4 | 64.2 | 75.0 | 2 603 | +0.2 [−0.1, +0.7] | +0.5 [−0.1, +1.4] | −2.7 [−3.9, −1.3] |
| `propio_A2_debil05` | H1+H2 | 58.6 | 64.2 | 75.1 | 2 564 | +0.4 [+0.1, +0.8] | +0.5 [−0.1, +1.5] | −2.5 [−3.7, −1.1] |
| `propio_A3_fusion` | H1+H2+H3 | 56.4 | 60.0 | 70.1 | 4 230 | **−1.8 [−3.3, −0.8]** | **−3.7 [−6.6, −1.8]** | −4.6 [−5.8, −3.6] |
| `propio_A4_tentativos` | H1+H2+H3+H4 | **60.7** | **68.0** | **79.1** | **477** | **+2.5 [+1.6, +3.4]** | **+4.3 [+2.7, +6.2]** | **−0.4 [−1.0, +0.3]** |
| `propio_A5_sin_pad` | H1+H5 | 58.4 | 64.2 | 74.9 | 2 658 | +0.2 [−0.1, +0.7] | +0.5 [−0.2, +1.4] | −2.6 [−3.8, −1.2] |
| `bytetrack` | referencia | 60.1 | 67.2 | 78.1 | 452 | | | |
| `botsort` | referencia | 61.1 | 68.5 | 79.0 | 366 | | | |

Lectura:

- **H1 (compuerta de clase) aporta poco:** −12 % de IDSW, sin cambio significativo en HOTA ni AssA. En test pasó lo
  mismo (v1.1: −12 % de IDSW, [`resultados-v1_1.md`](resultados-v1_1.md)). H2 y H5 tampoco mueven nada que importe.
- **H3 (fusionar la confianza) empeora** de forma clara: duplica los IDs (5 473) y los IDSW suben a 4 230.
- **H4 (tentativos aparte, que mueran al primer fallo) es la causa principal.** Con H4, los IDSW caen de 2 954 a 477
  (−84 %), el AssA sube 4.3 puntos y `propio_kf` **empata con BoT-SORT** en ajuste (−0.4 [−1.0, +0.3]). Además, supera
  a ByteTrack en HOTA (60.7 contra 60.1).
- La lectura coherente con §1: el cambio de clase hacía que naciera un track tentativo encima de un vehículo ya seguido.
  En la v1, ese tentativo podía quitarle detecciones al track establecido en la primera ronda y sobrevivía 1 s sin
  detección. Así se producía la ida y vuelta. Sin la compuerta (H1) siguen naciendo duplicados por otras causas; con
  H4 ya no sobreviven.

**Aplicación del criterio fijado** (mayor AssA, HOTA no menor que la v1 con IC, menos cambios si hay empate):
**`propio_A4_tentativos`** gana. Ninguna otra variante se le acerca en AssA, así que no hay empate que desempatar.

**Salvedad.** La ablación fue acumulativa, y A4 incluye H3, que por sí solo empeora. No se probó H1+H2+H4 sin H3, y es
posible que sea igual o mejor que A4 con un cambio menos. Por eso se corre una ablación complementaria, solo en ajuste
(A6 = H1+H2+H4, A7 = H1+H4, A8 = H4), con la regla de elección fijada antes en
[`DECISIONS.md`, D36.1](../benchmark/DECISIONS.md). Guía: [`guia-laboratorio-v2b.md`](guia-laboratorio-v2b.md).
