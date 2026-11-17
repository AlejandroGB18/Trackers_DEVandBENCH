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

## Uso

```bash
pip install "trackeval==1.3.0" pyyaml          # + lo de los trackers (numpy, opencv, scipy, ultralytics)
cd benchmark
python pruebas_benchmark.py                    # debe terminar en "TODO OK"
python bench.py detectar                       # detecciones cacheadas de todas las secuencias
python bench.py ego                            # ego-movimiento de referencia
python bench.py moving                         # solo secuencias con GT: propone moving y lista qué revisar
python bench.py correr  --run v1               # los 4 trackers
python bench.py evaluar --run v1               # métricas
```

`--seq vigia_9 vigia_10` limita a algunas secuencias; `--rehacer` ignora las cachés.

## Qué sale en `runs/<run>/eval/`

| Archivo | Contenido |
|---|---|
| `metricas.csv` | Por protocolo × tracker × secuencia (y `COMBINADO`, solo split test): HOTA, DetA, AssA, LocA, DetRe/Pr, AssRe/Pr, HOTA(0.5), MOTA, MOTP, IDF1, IDP, IDR, IDSW, Frag, MT/PT/ML, FP, FN, IDs |
| `por_bin_ego.csv` | HOTA/DetA/AssA/LocA e IDSW (y por 1000 GT-dets) por bin de ego-movimiento: `estacionario`, `suave`, `rapido`, `H_no_fiable` |
| `decisor.csv` | `en_movimiento` vs GT `moving` sobre los TP (CLEAR α=0.5): TP/FP/FN/TN, precisión, recall, F1, especificidad, tasa de `paralaje` en quietos y móviles; global y por bin. Nivel track: falsa alarma y detección por track |
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

## El GT (cómo anotar un clip VIGIA)

1. **CVAT**, tarea con el clip; etiquetas `vehicle` e `ignored` (región). Atributos de `vehicle`: `visibility`.
2. Anotar cada 3 frames (≈10 fps a 30 fps) con interpolación entre keyframes, **sin** pre-anotar con ninguno de los 4
   trackers. Lo que no se pueda separar (estacionamientos densos, vehículos de pocos px) se cubre con `ignored`.
3. Exportar en **MOT 1.1** → `gt/gt.txt` (`frame,id,x,y,w,h,considerar,clase,visibilidad`). Asegurar que las clases
   queden como en `secuencias.yaml` (`1` = vehicle, `0` = región ignorada) y que **los frames sean los del video
   completo, base 1** (si la tarea de CVAT empieza en otro frame, sumar el desfase).
4. En `secuencias.yaml`: `gt:` con la ruta y `gt_frames: {inicio, fin, paso: 3}`.
5. `python bench.py ego` y `python bench.py moving` → revisar en CVAT los casos de `moving_revisar.csv`, corregir
   `moving_auto.csv` y guardarlo como `moving.csv`; ponerlo en `gt_moving:`. Sin `gt_moving` la evaluación usa la
   propuesta automática y lo avisa.
6. QA: otra persona revisa ~20 % de los frames.

## Cómo está validado (`pruebas_benchmark.py`)

- GT como predicción → HOTA = MOTA = IDF1 = 100; un cambio de ID → exactamente 1 IDSW y AssA 50, DetA 100.
- Las réplicas por frame (CLEAR y HOTA por bins) dan **los mismos números** que TrackEval.
- MOTA, IDF1 e IDSW coinciden con **py-motmetrics**.
- Regla de regiones ignoradas por área y los 4 protocolos sobre un caso construido a mano.
- `moving` derivado con paneo: un auto quieto sale 0 y uno que avanza sale 1.
- Video sintético con paneo (3 px/frame): `ego_px` = 2.25 (el valor exacto), los 4 trackers corren, se evalúan y son
  deterministas (mismos bytes en dos corridas).
- Sobre 120 frames reales de vigia_1: el `ego_px` de referencia y el de la H de los trackers tienen mediana
  0.22 vs 0.235 px y correlación 0.96 (miden lo mismo con estimadores distintos).

## Límites conocidos

- Sin GT anotado todavía: hoy solo salen `sin_gt.csv` y los tiempos. Todo lo demás se activa al poner `gt:`.
- `py-motmetrics 1.4.0` usa `np.asfarray` (NumPy < 2) en `iou_matrix`; las pruebas calculan la matriz de distancias
  por su cuenta.
- La latencia del decisor tiene la resolución de la anotación (con paso 3, 0.1 s).
- Pendientes (ver `DECISIONS.md`): bootstrap por bloques temporales, métricas por tamaño de objeto, VisDrone/UAVDT
  como conjunto de ajuste, baselines extra de BoxMOT/Roboflow.
