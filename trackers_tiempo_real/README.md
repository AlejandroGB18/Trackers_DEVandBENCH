# Trackers para tiempo real — detección de movimiento desde dron

Cada tracker de la comparativa (v9–v14) vive en su propio archivo. Cada uno es una sola clase que se usa igual que las demás. Están pensados para llevarse a otro entorno donde **ya hay un detector**. El tracker recibe el frame y las detecciones, y devuelve los tracks.

```python
from tracker_propio import TrackerPropio            # o TrackerUCMC, TrackerByteTrack, TrackerBoTSORT

tracker = TrackerPropio(fps=30, nombres_clases={2: "car", 7: "truck"})
for frame in camara:                                # frame BGR a resolución ORIGINAL
    dets = mi_detector(frame)                       # Nx6 [x1, y1, x2, y2, conf, clase], píxeles del frame
    tracks = tracker.actualizar(frame, dets)        # lista de TrackSalida
    for t in tracks:
        t.id, t.caja, t.clase, t.en_movimiento      # caja en píxeles originales
```

Todo es **causal**: cada frame usa solo el actual y los anteriores. No hay pasadas previas por el video, así que sirve en tiempo real.

---

## Archivos

| Archivo | Qué contiene | Se lleva al otro entorno |
|---|---|---|
| `comun.py` | Lo que va **antes y después** del tracker, igual para todos: escala, estabilización (H), entrada de detecciones, `Track`, decisión de movimiento y salida | Siempre |
| `tracker_propio.py` | **Tracker propio**: estabilización con H + Kalman + IoU (el `propio_kf` de la comparativa) | Si se usa |
| `tracker_ucmc.py` | **UCMCTrack** + **calibración automática en línea** de la cámara | Si se usa |
| `tracker_bytetrack.py` | ByteTrack de Ultralytics (referencia sin compensación de cámara) | Si se usa (+ `adaptador_ultralytics.py`) |
| `tracker_botsort.py` | BoT-SORT de Ultralytics con su GMC | Si se usa (+ `adaptador_ultralytics.py`) |
| `adaptador_ultralytics.py` | Absorbe los cambios de API de Ultralytics entre versiones | Solo con ByteTrack / BoT-SORT |
| `pruebas.py` | Self-tests de todo: `python pruebas.py` | Recomendado |
| `../tiempo_real_propio.ipynb`, `../tiempo_real_ucmc.ipynb`, `../tiempo_real_bytetrack.ipynb`, `../tiempo_real_botsort.ipynb` | Un notebook **autocontenido** por tracker (no importa los `.py`: lleva el mismo código, celda por celda, con su explicación). Pruebas, video, tiempos y, en UCMC, la cámara estimada | No (es para estudiar / probar cada uno) |
| `../demo_tiempo_real.ipynb` | Junto a las comparativas. Procesa un video frame a frame con YOLO como "detector externo", mide ms por etapa, guarda el video y los tracks en formato MOT | No (es la demo) |

**Dependencias:**
- `numpy`, `opencv-python` y `scipy` para el propio y UCMC.
- `ultralytics` solo para ByteTrack y BoT-SORT.

---

## Contrato de entrada y salida (igual en los 4)

**Entra en cada frame:**
- `frame`: imagen BGR (`uint8`, H×W×3) a resolución **original**. El tracker la reduce a `work_width` (960 px).
- `detecciones`: `Nx6` = `[x1, y1, x2, y2, conf, clase]` en píxeles del frame **original**. `clase` es un id entero ≥ 0.
  - Si el detector devuelve `[x, y, ancho, alto]` hay que pasarlas a esquinas. `EntradaDetecciones.revisar` avisa si llegan al revés.
  - Si el detector usa cajas orientadas (OBB), se pasa su caja horizontal.
  - Para no perder detecciones débiles, el umbral de confianza del detector debe estar **por debajo de** `conf_low` (0.10). Los trackers hacen una segunda ronda con ellas.
- `fps` (al crear el tracker): fps **real** del stream. Las ventanas en segundos (pérdida, movimiento, calibración) se convierten a frames con él.
- `nombres_clases` (opcional): `{id: "car", ...}`. Las clases de vehículo (`parallax_skip`) no pasan por el filtro de paralaje.

**Sale de cada frame:** una lista de `TrackSalida`, solo con los tracks **confirmados** (≥ `min_hits` detecciones) que tienen detección en este frame.

| Campo | Significado |
|---|---|
| `id` | ID del track |
| `caja` | `(x1, y1, x2, y2)` en píxeles originales |
| `conf` | Confianza de la última detección |
| `clase` / `nombre_clase` | Clase votada (-1 = desconocido / propuesta) |
| `en_movimiento` | ¿Se mueve de verdad?, con histéresis |
| `desplazamiento_px` | Desplazamiento neto en ~1 s, estabilizado, en px originales |
| `paralaje` | Parecía moverse pero es algo alto y quieto |

Para un benchmark MOT, `como_array(tracks)` da `Nx7 [x1, y1, x2, y2, id, conf, clase]`.

**Diagnóstico:** `tracker.tiempos_ms` da los ms de cada etapa del último frame. En UCMC, además, `tracker.calibrador.pitch / .altura / .fuente_pitch`.

> El tracker **no guarda estado entre videos**: un video o stream nuevo es un tracker nuevo. Si cambia la resolución del stream, también.

---

## Pipeline común

```
frame + detecciones
  │
  ├─ 1. Escala ............ frame original → 960 px (BGR + gris suavizado)          comun.Escala
  ├─ 2. Estabilización .... H: cómo se movió la cámara (LK + RANSAC, puntos en rejilla)   comun.Estabilizador
  ├─ 3. Entrada ........... detecciones a 960 px, sin cajas gigantes, + propuestas sin clase   comun.EntradaDetecciones
  │
  ├─ 4–6. TRACKER ......... lo único que cambia entre los 4 (ver abajo)
  │
  ├─ 7. ¿Se mueve? ........ desplazamiento estabilizado en 1 s + rectitud + paralaje + histéresis   comun.DecisorMovimiento
  └─ 8. Salida ............ TrackSalida en píxeles originales                       comun.a_salida
```

- **Propuestas:** son cajas sin clase (-1) donde la imagen cambia después de compensar la cámara, y sirven para objetos que el detector no conoce.
  - Se activan con `use_proposals`. Están activas por defecto porque así se evaluó la comparativa.
  - **Para un benchmark de MOT conviene apagarlas** (`Config(use_proposals=False)`): el benchmark solo evalúa clases conocidas y las contaría como falsos positivos.
- **La H se calcula en los 4 trackers:**
  - Aunque ByteTrack y BoT-SORT no la usan para asociar, el paso 7 mide el movimiento en coordenadas estabilizadas.
  - Así el "¿se mueve?" es idéntico en todos.

---

## Tracker propio (`tracker_propio.py`)

La clase principal `TrackerPropio` contiene **la estabilización y el Kalman**. Su `actualizar()` hace los 8 pasos en orden y `seguir()` hace los pasos 4–6:

```
4. Predicción ... para cada track:
                  historial → frame actual con H                    (para el paso 7)
                  Kalman    → frame actual con H                     KalmanXYAH.estabilizar   ← ESTABILIZACIÓN
                  Kalman    → un frame adelante                      KalmanXYAH.predecir      ← movimiento propio
5. Asociación ... IoU entre la caja PREDICHA y la detección (cajas infladas 3 px), húngaro, clase compatible
                  ronda 1: detecciones fuertes (≥ 0.35) · ronda 2: débiles (0.10–0.35) con los tracks sobrantes
6. Corrección ... Kalman corrige con la detección (el track guarda la caja filtrada)
                  nacen tracks solo con detecciones fuertes · mueren tras 1 s sin detección
```

**`KalmanXYAH.estabilizar` en una línea:** el centro del track se lleva con la H completa. La velocidad y la covarianza se llevan con su parte lineal `A`, y la altura de la caja se escala por `√|det A|` (zoom o cambio de altura del dron). Así el Kalman solo tiene que explicar lo que el objeto se mueve **por sí mismo**.

**Lo que se toca** está en `ConfigPropio`:
- `match_iou` y `box_pad`.
- Los ruidos del Kalman son los de ByteTrack y **no** se ajustan con los videos de evaluación.

> Se probó cambiar el IoU por la MMD de UCMC (v14, v14b). Fragmentó más en 9 de 10 videos, así que el propio se queda con IoU.

---

## UCMCTrack con calibración automática (`tracker_ucmc.py`)

UCMC asocia **en el suelo**, en metros:
- cada detección se proyecta al plano del suelo;
- un Kalman de velocidad constante en metros predice;
- la asociación usa la distancia de Mahalanobis (MMD).

Para proyectar necesita la **cámara**: inclinación (pitch), campo de visión (hfov) y altura.

### De manual a automático

| | MANUAL (UCMCTrack original / v12) | AUTOMÁTICO (v13, aquí en línea) |
|---|---|---|
| **Pitch** | A ojo, uno para todo el video | **Se mide** cada 0.5 s descomponiendo la H del suelo |
| **Altura** | A ojo, o una vez con los vehículos | **Forma** con la H (cuánto sube o baja) + **escala** con el tamaño de los vehículos |
| **Cámara en el tiempo** | Fija | El mapa imagen↔suelo se rehace cuando cambian el pitch o la altura |
| **CMC** | Una sola cámara | Sale al frame anterior con la cámara anterior y vuelve al suelo con la nueva |
| **hfov** | Dato de la cámara | **Sigue siendo un dato de la cámara** (ficha técnica, 82° por defecto) |
| **Cuándo se calcula** | Antes de empezar | v13: una pasada previa por el video completo. **Aquí: frame a frame, solo con el pasado** |

**El hfov no se estima automáticamente.**
- Se probó estimarlo con el tamaño de los vehículos: un auto debe medir lo mismo en el suelo cerca y lejos.
- Solo fue fiable en vigia_8 (≈64°) y vigia_9 (≈55°). En vigia_1 y vigia_10 no converge, y en vigia_11 es ruido. Se decidió no incluirlo.
- Hay que ponerlo en `CamaraUCMC(hfov_deg=...)` con el dato del dron, porque el pitch estimado depende de él. En vigia_8 da 52° con hfov 60, 63° con 82 y 71° con 95.

### Cómo se mide la cámara (`CalibradorCamara`)

**Pitch, con la homografía del suelo.**
1. Cada 0.5 s se toma la H de la última ventana de 1 s y se descompone como `H = K (R + t·nᵀ/d) K⁻¹`.
   - `n` es la normal del suelo vista desde la cámara, y de ella sale el pitch: `pitch = atan2(n_y, n_z)`.
   - `H` da la normal al inicio de la ventana y `H⁻¹`, ahora.
2. Se descartan las soluciones imposibles:
   - suelo detrás de la cámara;
   - dron casi quieto (la normal no se puede medir);
   - alabeo > 25°;
   - pitch fuera de [-3°, 88°].
3. **Techo de horizonte:** con pitch θ el horizonte queda en `y = -cot θ`. Ningún vehículo puede apoyarse por encima, así que el 3er vehículo más alto limita θ.
4. Suelen quedar **2 soluciones** por muestra. Una **programación dinámica** sobre los últimos 5 s elige la secuencia más continua en el tiempo.
5. **Pitch de ahora** = mediana de las últimas 5 muestras de esa secuencia.
6. **Si hay pocas muestras válidas** (hover, H no fiable) se conserva el último pitch, o `pitch_respaldo_deg` si todavía no hubo ninguno.

**Altura: la forma con la H y la escala con los vehículos.**
7. La misma descomposición da cuánto cambió la distancia al suelo (`d_b/d_a = 1 + (R·n)·t/d`). Encadenando, se conoce `log(altura)` salvo una constante.
8. Cada vehículo cerca del centro da una altura: `f · 4.5 m / lado_px · cos(pitch)`.
   - La mediana de los últimos 10 s fija la constante.
   - Cada vehículo se corrige por lo que el dron subió o bajó desde que se vio.

**Costo de ser causal:** el pitch va **~1 s atrasado**.
- En la prueba sintética el gimbal gira 3°/s, y el error llega a ~4.5° mientras gira.
- En los videos VIGIA el pitch cambia mucho más despacio (entre 5° y 10° en todo el video).

**Supuestos:**
- Suelo plano.
- Sin alabeo.
- Que el dron se desplace de vez en cuando: en hover puro se usa `pitch_respaldo_deg`.

### Pasos 4–6 de `TrackerUCMC`

```
4. Calibración ... pitch y altura de este frame → Mapa (imagen ↔ suelo)                    CalibradorCamara
5. UCMC .......... detecciones al suelo (base de la caja; centro si la toma es cenital)        NucleoUCMC
                   predicción en metros + CMC con nuestra H
                   1) fuertes ↔ confirmados  2) débiles ↔ resto  3) fuertes sobrantes ↔ tentativos
                   nace con fuerte; confirmado tras 3 detecciones; muere tras 1 s costeando
6. Libro ......... salida de UCMC → Track con historial estabilizado                         comun.LibroTracks
```

**Uso por tipo de toma:**

```python
TrackerUCMC(fps, CamaraUCMC(hfov_deg=82, pitch_respaldo_deg=0))     # cenital
TrackerUCMC(fps, CamaraUCMC(hfov_deg=82, pitch_respaldo_deg=50))    # oblicua: estimación a ojo, solo hasta la 1ª medida
TrackerUCMC(fps, CamaraUCMC(pitch_respaldo_deg=50, altura_m=80))    # altura conocida (telemetría): fija
TrackerUCMC(fps, CamaraUCMC(pitch_respaldo_deg=50), ConfigUCMC(ucmc_calibrar=False))   # modo MANUAL
```

- Si el dron da telemetría (altura, ángulo del gimbal), lo mejor es pasarla directamente en lugar de estimarla.
- `pitch_respaldo_deg` también decide el **punto de apoyo**: centro de la caja si es menor de 30°, base si no.

---

## ByteTrack y BoT-SORT

- **Son los de Ultralytics,** alimentados con nuestras detecciones y con los mismos umbrales comunes (`conf_high`, `conf_low`, `max_miss_sec`).
- **ByteTrack** no compensa la cámara.
- **BoT-SORT** usa su propio GMC (`sparseOptFlow`) sobre la imagen de trabajo, sin ReID.
- **`LibroTracks` (comun.py)** convierte su salida en `Track` para que el "¿se mueve?" sea el mismo.

---

## Cómo se comprobó

1. **`python pruebas.py`:** self-tests de cada pieza.
   - Kalman estabilizado.
   - Un objeto quieto con el dron en paneo conserva su ID.
   - Mapeo al suelo y asignación.
   - Calibración en línea con una cámara sintética que cambia de pitch y de altura.
2. **Mismos números que la comparativa:** los 4 pipelines se corrieron frame a frame (como en tiempo real) sobre
   3 videos VIGIA: vigia_4 (cenital, OBB), vigia_9 y vigia_10 (oblicuos, COCO). Mismo detector y umbrales que el v13.

   | Video | propio_kf | ByteTrack | BoT-SORT | UCMC (IDs nuevo / v13) | Pitch en línea vs v13 (mediana) | Altura en línea vs v13 |
   |---|---|---|---|---|---|---|
   | vigia_4 | idéntico | idéntico | idéntico | idéntico (13 / 13) | 4.0° vs 3.5° | 100 m vs 100 m |
   | vigia_9 | idéntico | idéntico | idéntico | 808 / 789 | 61.7° vs 61.9° | 44 m vs 51 m |
   | vigia_10 | idéntico | idéntico | idéntico | 493 / 454 | 28.6° vs 23.4° | 114 m vs 105 m |

   - **Idéntico** = las 8 métricas del v13 (IDs, tracks, vida media, tracks por objeto, IDs/min, …) coinciden al decimal.
   - **UCMC cambia un poco** porque la calibración ahora es **en línea** (solo pasado, ~1 s de retraso) y no sobre el
     video completo. Las métricas quedan cerca (vida media 1.30 vs 1.29 s en vigia_9; 1.64 vs 1.71 s en vigia_10).
   - **Tiempo del tracker** (sin detector), mediana por frame en un Mac con CPU, con 2 procesos en paralelo:
     ~25 ms en vigia_4 y ~60–80 ms en los oblicuos 4K. La mayor parte es la estabilización (LK + RANSAC) y las
     propuestas; con `use_proposals=False` baja bastante.
