# Benchmark de trackers para dron (harness propio + TrackEval)

Compara los 4 trackers de `VD - Trackers To Real Implementation/` (propio_kf, UCMC, ByteTrack, BoT-SORT) con
**las mismas detecciones**, puntuándolos con las métricas de **TrackEval** y con un análisis propio del caso dron:
¿cuánto se degradan cuando el dron se mueve? y ¿distinguen lo que se mueve de verdad?

El porqué de este diseño (y por qué no BoxMOT como juez) está en
[`docs/investigacion-benchmark-boxmot.md`](../docs/investigacion-benchmark-boxmot.md). Las decisiones que congelan
el protocolo están en [`DECISIONS.md`](DECISIONS.md).

```
secuencias.yaml ─┬─ detectar ──► cache/detecciones/<det>/<seq>.npz   (una pasada YOLO, umbral bajo, con firma)
                 ├─ ego ───────► cache/ego/<seq>.csv                  (H de referencia SIFT+MAGSAC, NO la de los trackers)
                 ├─ moving ────► <gt>/moving_auto.csv + moving_revisar.csv   (propuesta → revisión humana)
                 ├─ correr ────► runs/<run>/<tracker>/<seq>.txt (MOT) + _lateral.csv (en_movimiento) + _tiempos.csv
                 └─ evaluar ───► runs/<run>/eval/*.csv
```

## Uso (v1: UAVDT, ver [`docs/plan-benchmark-v1.md`](../docs/plan-benchmark-v1.md))

Los datos viven fuera del repo, bajo una raíz (`datos_raiz: ../datos` en `secuencias.yaml`, o la variable de entorno
`BENCH_DATOS` en el laboratorio):

```
<raíz>/UAVDT/UAV-benchmark-M/Mxxxx/img000001.jpg …     (zip oficial, 6.3 GB)
<raíz>/UAVDT/UAV-benchmark-MOTD_v1.0/GT/…             (zip oficial, GT y toolkit)
<raíz>/UAVDT/M_attr/{train,test}/Mxxxx_attr.txt        (zip oficial)
<raíz>/UAVDT/gt_benchmark/Mxxxx/gt.txt                 (lo genera adaptadores/uavdt.py)
<raíz>/detecciones/<detector>/{Mxxxx.txt, firma.json}  (lo genera detectar_lab.py)
```

En el laboratorio (Linux, conda, GPU):

```bash
conda env create -f benchmark/environment.yml && conda activate bench-trackers
export BENCH_DATOS=/ruta/a/datos
cd benchmark
python pruebas_benchmark.py                                   # debe terminar en "TODO OK"
python -m adaptadores.uavdt                                   # GT de UAVDT → gt_benchmark/ (secuencias.yaml ya viene generado)
python detectar_lab.py --frames $BENCH_DATOS/UAVDT/UAV-benchmark-M --pesos /ruta/yolo8x_best.pt \
                       --salida $BENCH_DATOS/detecciones/yolo8x --dispositivo 0
# AJUSTE (30 secuencias) → luego CONGELADO 1 en DECISIONS.md
python bench.py detectar --split ajuste
python bench.py ego      --split ajuste
python bench.py barrer   --split ajuste --run v1_ajuste
# TEST (20 secuencias), una sola vez y con todo congelado
python bench.py detectar --split test
python bench.py ego      --split test
python bench.py moving   --split test                         # propuesta → revisión humana → CONGELADO 2
python bench.py barrer   --run v1_ajuste                      # todas: lleva la cámara de ajuste a test (+ cota)
python bench.py correr   --split test --run v1
python bench.py evaluar  --split test --run v1
```

`--seq M0101 M0202` limita a algunas secuencias; `--detector yolo8n` usa otro detector del manifiesto (la prueba en la
Mac); `--rehacer` ignora las cachés.

## Qué sale en `runs/<run>/eval/`

| Archivo | Contenido |
|---|---|
| `metricas.csv` | Por protocolo × tracker × secuencia (y `COMBINADO`, solo split test; columnas `uso_gt` y `en_ranking`): HOTA, DetA, AssA, LocA, DetRe/Pr, AssRe/Pr, HOTA(0.5), MOTA, MOTP, IDF1, IDP, IDR, IDSW, Frag, MT/PT/ML, FP, FN, IDs |
| `por_bin_ego.csv` | Solo split test. HOTA/DetA/AssA/LocA e IDSW (y por 1000 GT-dets) por bin de ego-movimiento: `estacionario`, `suave`, `rapido`, `H_no_fiable` |
| `decisor.csv` | Solo split test. `en_movimiento` vs GT `moving` sobre los TP (CLEAR α=0.5): TP/FP/FN/TN, precisión, recall, F1, especificidad, tasa de `paralaje` en quietos y móviles; global y por bin. Nivel track: falsa alarma y detección por track |
| `latencias.csv` | Encendido (GT empieza a moverse → decisor lo marca) y apagado: % detectado, mediana y p90 en s |
| `sin_gt.csv` | Las métricas de la v13 (tracks, vida media, tracks por objeto, IDs/min…), para todas las secuencias |
| `comparaciones.csv` | Δ pareado entre trackers (HOTA, AssA, IDF1) con IC 95 % por bootstrap de secuencias y "gana en k/n" |

**Protocolos** (columna `protocolo`):

| Protocolo | Se evalúa | Pregunta |
|---|---|---|
| `todos` | Todo vehículo del GT | Tracking estándar |
| `moviles` | Solo GT `moving=1`; quietos y dudosos son distractores | ¿Sigue bien lo que se mueve? |
| `estaticos` | Solo GT `moving=0` | ¿Mantiene el ID de lo quieto mientras el dron se mueve? |
| `e2e_moviles` | GT `moving=1` contra predicciones con `en_movimiento=1` | Sistema completo: tracker + decisor |

Cómo leerlo: **DetA** es sobre todo el detector (igual para los 4), **AssA / IDF1 / IDSW** son el tracker, y el salto de
AssA entre `estacionario` y `rapido` es la robustez al movimiento del dron.

## Cámara de UCMC sin telemetría: `bench.py barrer` (D17)

Los datasets públicos no traen la cámara, así que se busca en una rejilla de **pitch × altura** (hfov fijo por
dataset) definida por grupo de vuelo en `secuencias.yaml → barrido.grupos`. Cada secuencia lleva `split`
(`ajuste` / `test`) y `grupo` (o su `toma`).

```bash
python bench.py barrer --run b1                     # rejilla en todas las secuencias → runs/b1/barrido/
```

| Archivo | Contenido |
|---|---|
| `resultados.csv` | Cada cámara de la rejilla × secuencia: HOTA, DetA, AssA, IDF1, IDSW, `n_fuera` y el criterio sin GT (pendiente de tamaño, escala, velocidades implausibles) — es la curva de sensibilidad |
| `seleccion.csv` | La cámara elegida por secuencia en cada versión: `grupo_train`, `singt`, `oraculo_seq` |
| `validacion_singt.csv` | Spearman entre el criterio sin GT y HOTA en las secuencias de ajuste |
| `fraccion_rejilla_gana.csv` | Con `--contra RUN`: fracción de la rejilla en la que UCMC supera a cada rival |

Después, se corren las versiones elegidas como trackers normales:

```yaml
trackers:
  - propio_kf
  - ucmc                                             # calibración automática en línea
  - {nombre: ucmc, etiqueta: ucmc_grupo_train, seleccion: runs/b1/barrido/seleccion.csv, version: grupo_train}
  - {nombre: ucmc, etiqueta: ucmc_oraculo_seq, seleccion: runs/b1/barrido/seleccion.csv, version: oraculo_seq}
  - bytetrack
  - botsort
```

`ucmc_oraculo_seq` sale en `metricas.csv` como `COMBINADO_COTA` (columna `uso_gt = test`) y no entra en
`COMBINADO` ni en `comparaciones.csv`. `ucmc_singt` solo entra si el criterio sin GT se validó en ajuste (D17.6,
columna `valido` de `seleccion.csv`); si no, sale como `COMBINADO_NO_VALIDADO` (`en_ranking = false`). Un tracker
marcado `en_ranking: false` a mano (la referencia `ucmc`, D23) sale como `COMBINADO_REFERENCIA`. Cada prueba de la rejilla corre solo el núcleo de UCMC sobre la H y las
detecciones guardadas en `cache/entrada/` (sin decodificar el video); una prueba comprueba que da exactamente lo
mismo que el tracker completo. Con telemetría real, la cámara se pasa directamente:
`{nombre: ucmc, etiqueta: ucmc_telemetria, camara: {...}, config: {ucmc_calibrar_pitch: false, ucmc_calibrar_altura: false}}`.

## Cómo está validado (`pruebas_benchmark.py`)

- GT como predicción → HOTA = MOTA = IDF1 = 100; un cambio de ID → exactamente 1 IDSW y AssA 50, DetA 100.
- Las réplicas por frame (CLEAR y HOTA por bins) dan **los mismos números** que TrackEval.
- MOTA, IDF1 e IDSW coinciden con **py-motmetrics**.
- Regla de regiones ignoradas por área y los 4 protocolos sobre un caso construido a mano.
- `moving` derivado con paneo: un auto quieto sale 0 y uno que avanza sale 1.
- Video sintético con paneo (3 px/frame): `ego_px` = 2.25 (el valor exacto), los 4 trackers corren, se evalúan y son
  deterministas (mismos bytes en dos corridas).
- El núcleo de UCMC sobre la H cacheada da las mismas cajas que el tracker completo.
- Integración con archivos reales (video, GT, ego, `moving`): barrido → selección D17 → correr → `evaluar_run`;
  el oráculo queda solo en `COMBINADO_COTA`, el `singt` no validado en `COMBINADO_NO_VALIDADO`, ambos fuera de las
  comparaciones, y los bins y el decisor no incluyen las secuencias de ajuste.
- Adaptador de UAVDT sobre un árbol mínimo con el formato real; carpetas de frames; detecciones externas (`.txt` →
  caché, rango y clases) y rutas portables (`datos_raiz`, `BENCH_DATOS`).
- Sobre 120 frames reales de vigia_1: el `ego_px` de referencia y el de la H de los trackers tienen mediana
  0.22 vs 0.235 px y correlación 0.96 (miden lo mismo con estimadores distintos).

## Límites conocidos

- `py-motmetrics 1.4.0` usa `np.asfarray` (NumPy < 2) en `iou_matrix`; las pruebas calculan la matriz de distancias
  por su cuenta.
- La latencia del decisor tiene la resolución de la anotación (con paso 3, 0.1 s).
- Pendientes (ver `DECISIONS.md`): bootstrap por bloques temporales, métricas por tamaño de objeto, VisDrone/UAVDT
  como conjunto de ajuste, baselines extra de BoxMOT/Roboflow.
