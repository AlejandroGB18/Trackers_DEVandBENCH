# Diseño del benchmark de trackers (documento consolidado)

> **Fecha:** 2026-11-23 · **Rama:** `ucmc-barrido-camara` · **Qué es:** el estado actual del diseño, consolidado a partir del código de `benchmark/`, de `VD - Trackers To Real Implementation/` y de los cuatro informes de `docs/`. No agrega decisiones nuevas: lo que no está en el repo y viene del usuario se marca **[Usuario]**; lo que es una lectura propia del código se marca **[Observación]**; lo que los informes no pudieron comprobar queda **NO VERIFICADO**.
>
> **Cómo citar:** `ruta:línea` apunta al repo (rutas relativas a la raíz). Las afirmaciones externas (datasets, papers) se citan con el informe y la línea donde están verificadas; la fuente primaria está en la sección de fuentes de ese informe.

---

## 1. Resumen en 10 líneas

1. **Qué se compara:** 4 trackers (`propio_kf`, `bytetrack`, `botsort`, `ucmc`) con **las mismas detecciones cacheadas**, más 3 versiones de UCMC con la cámara elegida por "fuerza bruta" (`ucmc_grupo_train`, `ucmc_singt`, `ucmc_oraculo_seq`) (`benchmark/README.md:3-5`, `benchmark/DECISIONS.md:38`).
2. **Para qué:** dron multirrotor DJI, RGB, vehículos terrestres en entorno urbano; el sistema real tendrá telemetría completa y el tracker corre en tierra **[Usuario]**.
3. **Contra qué GT:** UAVDT (principal disponible, ego suave), VisDrone2019-MOT (segunda fuente) y DynUAV (ego fuerte, acceso por Baidu y permiso pendientes) **[Usuario]**; VIGIA queda fuera (solo fueron videos de prueba) (`docs/investigacion-gt-caso-real.md:5`).
4. **Juez:** métricas de `trackeval==1.3.0` (HOTA, CLEAR, Identity, Count) con preprocesado propio (D1, `benchmark/DECISIONS.md:10`).
5. **Métricas:** HOTA/DetA/AssA/LocA, IDF1, IDSW, MOTA…; DetA ≈ detector, AssA/IDF1/IDSW ≈ tracker (`benchmark/README.md:54-55`).
6. **Estratos:** por bin de ego-movimiento (`estacionario`/`suave`/`rapido`/`H_no_fiable`, D11) y por protocolo `todos`/`moviles`/`estaticos`/`e2e_moviles` (`benchmark/README.md:45-52`).
7. **Decisor `en_movimiento`:** precisión/recall/F1 y latencias contra una etiqueta `moving` **derivada con homografía y revisada a mano**, solo donde exista (`benchmark/gt.py:13-20`, `benchmark/evaluar.py:484-492`).
8. **Estadística:** combinado por suma de conteos solo en `test` (D14) y Δ pareado con IC 95 % por bootstrap de secuencias (`benchmark/estadistica.py:18-34`).
9. **Respuesta que da:** qué tracker mantiene mejor la identidad con el detector fijo, cuánto pierde cada uno al subir el ego-movimiento, y si UCMC gana cuando se conoce (o se estima) la cámara, con el oráculo como cota fuera del ranking (D17.5).
10. **Estado:** el harness está implementado y probado con sintéticos (`benchmark/README.md:106-119`); **faltan** los conversores de GT, el detector entrenado, las secuencias reales en `secuencias.yaml` (hoy lista VIGIA) y la rejilla por grupo de UAVDT.

---

## 2. Diseño actual

### 2.1 Caso de uso [Usuario]

| Aspecto | Valor | Consecuencia en el benchmark |
|---|---|---|
| Plataforma | Multirrotor tipo DJI | Las fuentes de multirrotor (UAVDT, VisDrone, DynUAV) son las pertinentes; el ala fija queda fuera (`docs/investigacion-gt-caso-real.md:226`) |
| Sensor | Cámara RGB | Sin térmico ni multiespectral |
| Clases | Solo vehículos terrestres | Clase evaluada única `vehicle` (D7, `benchmark/DECISIONS.md:16`) |
| Entorno | Urbano | UAVDT/VisDrone/DynUAV son urbanos o de carretera (`docs/investigacion-gt-caso-real.md:54-59`) |
| Telemetría | Completa en el sistema real (altitud, actitud, gimbal, FOV) | En producción UCMC recibe la cámara directamente (`benchmark/README.md:89-90`); en los datasets no existe, de ahí D17 |
| Dónde corre | En tierra | La latencia se reporta (`_tiempos.csv`, `benchmark/correr.py:14`) pero **no decide** |
| Uso | Investigación / tesis | Las licencias "research only" son aceptables para uso interno (`docs/investigacion-gt-existente.md:175`) |
| Vuelos propios | No por ahora | Se descarta la validación con objetivos GNSS propuesta en `docs/investigacion-gt-caso-real.md:157-176` |
| Sintético (SynDrone / CARLA) | Pospuesto | No hay verdad física de `moving` ni de pose (§3) |
| VIGIA | Solo de prueba; no se anota | `secuencias.yaml` debe reemplazarse (§4, paso 3) |

### 2.2 Trackers y versiones

Todos reciben las mismas detecciones (`benchmark/detecciones.py:1-6`), un tracker nuevo por secuencia, `use_proposals=False` forzado y semilla fija de OpenCV (`benchmark/correr.py:5-9`, `benchmark/correr.py:43`, D15). Política de salida común: solo tracks confirmados con detección en el frame (D6, `benchmark/correr.py:17`).

| Etiqueta | Qué es | Cámara de UCMC | `uso_gt` | ¿Entra al ranking? |
|---|---|---|---|---|
| `propio_kf` | Estabilización con H + Kalman + IoU (`VD - Trackers To Real Implementation/README.md:95-110`) | — | `no` | Sí |
| `bytetrack` | ByteTrack de Ultralytics 8.4.x, sin compensación de cámara (D5; `VD - Trackers To Real Implementation/README.md:206-211`) | — | `no` | Sí |
| `botsort` | BoT-SORT de Ultralytics con GMC `sparseOptFlow`, sin ReID (`VD - Trackers To Real Implementation/README.md:210`) | — | `no` | Sí |
| `ucmc` (auto) | UCMC con calibración automática en línea de pitch y altura; hfov como dato (`VD - Trackers To Real Implementation/README.md:129-140`) | La de `secuencias.yaml → ucmc` de cada secuencia (`benchmark/correr.py:82-91`) | `no` | Sí ("¿sirve UCMC sin conocer la cámara?", `docs/investigacion-ucmc-fuerza-bruta.md:285`) |
| `ucmc_grupo_train` | Manual: mejor (pitch, altura) de la rejilla en las secuencias de **ajuste** del grupo, aplicada a test (`benchmark/barrido.py:250-265`) | `seleccion.csv`, `version: grupo_train` | `train` (`benchmark/correr.py:60`) | **Sí, número principal** de UCMC con cámara (`benchmark/barrido.py:10-11`) |
| `ucmc_singt` | Manual: por secuencia, mínimo del criterio sin GT (pendiente de tamaño, escala, velocidades implausibles) (`benchmark/barrido.py:22-27`, `benchmark/barrido.py:241-244`) | `seleccion.csv`, `version: singt` | `no` | Solo si el Spearman con HOTA en ajuste es ≤ −0.6 (D17.6). Automático desde 2026-11-23 (`en_ranking`, I1 corregido) |
| `ucmc_oraculo_seq` | Manual: mejor de la rejilla en cada secuencia de test, mirando su GT (`benchmark/barrido.py:245-249`) | `seleccion.csv`, `version: oraculo_seq` | `test` | **No**: sale como `COMBINADO_COTA` y fuera de `comparaciones.csv` (D17.5; `benchmark/evaluar.py:494-502`, `benchmark/evaluar.py:512`) |

Configuración común (D4): defaults de los `.py`, `conf_high` 0.35, `conf_low` 0.10, `min_hits` 4, `max_miss_sec` 1.0 (`benchmark/secuencias.yaml:25-30`). Los otros 3 trackers no se ajustan (D16, D17.8). En la rejilla de UCMC se barre **solo pitch × altura** con hfov fijo por dataset (D17.1) y punto de apoyo fijado por grupo (D17.3), porque la altura equivale a reescalar wx, wy, vmax y `a` (`docs/investigacion-ucmc-fuerza-bruta.md:117-124`).

Cómo se declaran en `secuencias.yaml` (`benchmark/README.md:76-84`):

```yaml
trackers:
  - propio_kf
  - ucmc
  - {nombre: ucmc, etiqueta: ucmc_grupo_train, seleccion: runs/b1/barrido/seleccion.csv, version: grupo_train}
  - {nombre: ucmc, etiqueta: ucmc_singt,       seleccion: runs/b1/barrido/seleccion.csv, version: singt}
  - {nombre: ucmc, etiqueta: ucmc_oraculo_seq, seleccion: runs/b1/barrido/seleccion.csv, version: oraculo_seq}
  - bytetrack
  - botsort
```

(La línea de `ucmc_singt` sigue el mismo formato que las otras; el ejemplo del README no la incluye.)

### 2.3 GT y splits por dataset

Formato interno del GT: MOT 1.1 `frame,id,x,y,w,h,considerar,clase,visibilidad`, frames del video en base 1; clase `1` = vehicle, `0` = región ignorada (`benchmark/gt.py:5-11`, `benchmark/secuencias.yaml:33-36`). Regla de ignorados: se descarta la predicción con ≥ 50 % de su área dentro (D8, regla del toolkit de VisDrone). Cada secuencia lleva `split` (`ajuste` | `test`; las de ajuste nunca se reportan) y `grupo` (`benchmark/comunes.py:49-56`).

| Dataset | Papel | Ego-movimiento | Split disponible | Uso propuesto en el benchmark | Estado |
|---|---|---|---|---|---|
| **UAVDT** | GT principal disponible [Usuario] | Suave: "hovering or slow cruising" (`docs/investigacion-gt-caso-real.md:42`) | MOT: 30 train / 20 test (`docs/investigacion-ucmc-fuerza-bruta.md:139`) | train → entrenamiento del detector y `split: ajuste` (selección `grupo_train`, validación de `singt`); test → `split: test` (`docs/investigacion-ucmc-fuerza-bruta.md:276`, `docs/investigacion-ucmc-fuerza-bruta.md:307`). Grupos por `M_attr`: altitud (baja 10–30, media 30–70, alta > 70 m) × vista (cenital / oblicua = frontal o lateral) (`docs/investigacion-ucmc-fuerza-bruta.md:137-138`, `docs/investigacion-ucmc-fuerza-bruta.md:274`) | Descarga directa en Google Drive, "research purpose only" (`docs/investigacion-gt-existente.md:61`). **Conversor pendiente** |
| **VisDrone2019-MOT** | Segunda fuente [Usuario] | Suave (`docs/investigacion-gt-existente.md:69`) | 56 train / 7 val / 17 test-dev / 16 test-challenge (sin GT) (`docs/investigacion-gt-existente.md:67-68`) | train → detector y `ajuste`; test-dev → `test` (test-challenge no tiene GT). Grupo cenital/oblicua **etiquetado a mano sin GT** (no trae altitud ni vista, `docs/investigacion-ucmc-fuerza-bruta.md:151-153`). El uso de `val` no está fijado (§5) | Descarga directa; licencia no declarada (`docs/investigacion-gt-existente.md:68`). **Conversor pendiente** |
| **DynUAV** | Ego fuerte [Usuario] | Fuerte: rotación, zoom, órbitas, velocidad variable (`docs/investigacion-gt-existente.md:75`) | 30/5/7 (`docs/investigacion-gt-existente.md:76`) | train → `ajuste`; test → `test`; altura por banda 80–120 m, hfov 70° (`docs/investigacion-ucmc-fuerza-bruta.md:167`, `docs/investigacion-ucmc-fuerza-bruta.md:273`) | Solo Baidu, sin licencia de datos → pedir permiso (`docs/investigacion-gt-existente.md:77-78`). **Acceso pendiente** |

Clases: todo vehículo se fusiona en `vehicle` (D7); lo que el detector no puede ver por diseño se trata como ignorado, no como FN (`docs/investigacion-gt-existente.md:167`). Frames evaluados: solo los anotados (D9); si `gt_frames` no se declara, se toman todos los frames entre el primero y el último del GT con paso 1 (`benchmark/gt.py:28-37`).

### 2.4 Detector

- **Principio (implementado):** una sola pasada por secuencia, caché con firma (hash de pesos, imgsz, clases, versión de Ultralytics), umbral de caché 0.05 y entrada al tracker ≥ `conf_entrada` 0.10 (D2; `benchmark/detecciones.py:1-12`, `benchmark/detecciones.py:33-49`). El mismo detector para todos los trackers.
- **Detector previsto (pendiente):** YOLO entrenado en el train de UAVDT/VisDrone, igual para los 4 trackers [Usuario]; coste estimado 0.5–1 día de GPU (`docs/investigacion-gt-existente.md:173`, `docs/investigacion-gt-existente.md:206`).
- **Detector configurado hoy:** `yolo11n-obb` (DOTA) para cenitales y `yolo11n` (COCO) para oblicuas, a imgsz 1280 (D3; `benchmark/secuencias.yaml:5-15`). Con objetos de pocos píxeles a 80–120 m su DetA sería muy bajo y el ranking quedaría dominado por FN (`docs/investigacion-gt-existente.md:173`). D3 queda obsoleta para los datasets nuevos.

### 2.5 Métricas

**Salidas de `bench.py evaluar`** (`benchmark/README.md:34-43`):

| Archivo | Contenido | Dónde se calcula |
|---|---|---|
| `metricas.csv` | HOTA, DetA, AssA, LocA, DetRe/Pr, AssRe/Pr, HOTA(0.5), MOTA, MOTP, IDF1, IDP, IDR, IDSW, Frag, MT/PT/ML, FP, FN, IDs; por protocolo × tracker × secuencia, más `COMBINADO` (solo test) y `COMBINADO_COTA` | `benchmark/evaluar.py:191-200`, `benchmark/evaluar.py:494-502` |
| `por_bin_ego.csv` | HOTA/DetA/AssA/LocA, IDSW e IDSW por 1000 GT-dets por bin de ego (solo protocolo `todos`) | `benchmark/evaluar.py:474-483`, `benchmark/evaluar.py:235-301` |
| `decisor.csv` | `en_movimiento` vs `moving` sobre los TP de CLEAR α = 0.5: TP/FP/FN/TN, precisión, recall, F1, especificidad, `paralaje` en quietos y móviles; global, por bin y por track | `benchmark/evaluar.py:320-362` |
| `latencias.csv` | Encendido/apagado: % detectado, mediana y p90 en s | `benchmark/evaluar.py:365-401` |
| `sin_gt.csv` | Métricas de la v13 (tracks, vida media, IDs/min…) | `benchmark/evaluar.py:407-425` |
| `comparaciones.csv` | Δ pareado HOTA/AssA/IDF1 con IC 95 % y "gana en k/n" (solo protocolo `todos`, solo test, sin oráculos) | `benchmark/evaluar.py:511-516` |

**Protocolos** (`benchmark/evaluar.py:17-21`): `todos` (tracking estándar); `moviles` (solo GT `moving=1`, quietos y dudosos como distractores); `estaticos` (solo `moving=0`); `e2e_moviles` (GT `moving=1` contra predicciones con `en_movimiento=1`; los quietos **no** son distractores, así que un quieto marcado móvil es FP).

**Bins de ego-movimiento (D11):** `ego_px` = desplazamiento medio de una rejilla 3×3 bajo la H de referencia, en px a 960 de ancho, con mediana centrada de 0.5 s; < 0.5 estacionario, < 3 suave, ≥ 3 rápido; `H_no_fiable` si falla la H (`benchmark/ego.py:179-189`). La H de referencia es SIFT a 1920 px + USAC_MAGSAC + comprobación ida-vuelta, con cajas enmascaradas, **independiente** del `Estabilizador` de los trackers (D10; `benchmark/ego.py:11-16`). HOTA por bin usa la alineación global de toda la secuencia y solo agrega por frames del bin (`benchmark/evaluar.py:236-238`).

**Etiqueta `moving` (D12, D13):** punto de apoyo (base en oblicuas, centro en cenitales) estabilizado con la H de referencia en una ventana centrada de 1 s; móvil si d ≥ 0.30·L y ≥ 3 px@960; quieto si d ≤ 0.10·L; dudoso en medio, si la ventana cruza una H no fiable o si el track es corto (`benchmark/gt.py:16-20`, `benchmark/gt.py:68-98`). `bench.py moving` escribe la propuesta y la lista de revisión (`benchmark/bench.py:39-54`); sin `gt_moving` revisado se usa la propuesta automática y se avisa (`benchmark/gt.py:115-123`). **El decisor solo se evalúa donde haya `moving`**: si no hay ego cacheado ni `gt_moving`, los protocolos distintos de `todos` y el decisor se omiten (`benchmark/evaluar.py:456`, `benchmark/evaluar.py:465-466`, `benchmark/evaluar.py:484`).

**Estadística:**
- Combinado: suma de conteos como TrackEval, no promedio de HOTA, solo split `test` (D14; `benchmark/evaluar.py:183-188`, `benchmark/evaluar.py:496`).
- Bootstrap pareado por secuencias, recombinando por conteos en cada réplica; `bootstrap_n` = 2000 (`benchmark/estadistica.py:18-34`, `benchmark/secuencias.yaml:39`). Requiere ≥ 2 secuencias de test comunes (`benchmark/evaluar.py:514`).
- Barrido: Spearman entre el criterio sin GT y HOTA en las secuencias de ajuste (`benchmark/barrido.py:229-237`); fracción de la rejilla en la que UCMC supera a cada rival (`benchmark/barrido.py:279-288`).
- `kendall_tau` existe para validar métricas sin GT contra las de GT (`benchmark/estadistica.py:37-41`), pero **no se llama** desde `evaluar_run` [Observación].

### 2.6 Pregunta del benchmark → fuente → métrica → estado

"Código" = el harness lo calcula; "Datos" = hay GT y detecciones para hacerlo con los datasets acordados.

| Pregunta | Fuente | Métrica / archivo | Código | Datos |
|---|---|---|---|---|
| ¿Qué tracker mantiene mejor la identidad con el detector fijo? | UAVDT test, VisDrone test-dev, DynUAV test | AssA, IDF1, IDSW en `metricas.csv` (`todos`, `COMBINADO`); Δ con IC en `comparaciones.csv` | Implementado | Pendiente (conversores + detector) |
| ¿Cuánto se degrada con el ego-movimiento? | UAVDT/VisDrone (bins estacionario/suave); DynUAV (rápido) | `por_bin_ego.csv`: salto de AssA entre `estacionario` y `rapido` (`benchmark/README.md:54-55`) | Implementado | Pendiente; el bin `rapido` depende de DynUAV |
| ¿Sigue bien lo que se mueve y mantiene el ID de lo quieto? | Los tres, con `moving` derivado y revisado | `metricas.csv` con `moviles` / `estaticos` | Implementado | Pendiente (+ revisión de `moving_revisar.csv`) |
| ¿El decisor separa lo que se mueve de verdad? | Donde haya `moving` | `decisor.csv`, `latencias.csv`, protocolo `e2e_moviles` | Implementado | Pendiente; **sin verdad física** (§3.1, L1) |
| ¿Sirve UCMC sin conocer la cámara? | Los tres | `ucmc` (auto) en `metricas.csv` | Implementado | Pendiente; depende de A7 (hfov) |
| ¿Gana UCMC si conoce la "clase de vuelo"? | Ajuste + test por grupo | `ucmc_grupo_train`; `seleccion.csv` | Implementado | Pendiente: rejilla por grupo UAVDT en `secuencias.yaml` y secuencias `ajuste` con GT |
| ¿Se puede elegir la cámara sin GT? | Ajuste (validación) → test | `ucmc_singt`; `validacion_singt.csv` | Implementado (D17.6 automática, I1 corregido) | Pendiente |
| ¿Cuál es el techo de UCMC con la cámara "perfecta-para-HOTA"? | Test | `ucmc_oraculo_seq` → `COMBINADO_COTA` | Implementado | Pendiente |
| ¿En qué fracción de cámaras gana UCMC a cada rival? | Test | `fraccion_rejilla_gana.csv` (`bench.py barrer --contra RUN`) | Implementado | Pendiente |
| ¿Cuánto depende UCMC del hfov de ficha? | — | `ucmc_auto_hfov±` propuesto (`docs/investigacion-ucmc-fuerza-bruta.md:286`) | **No implementado** (hfov fijo en la rejilla) | — |
| ¿Estima bien UCMC el pitch y la altura? | Requiere pose/telemetría | Error de pitch/altura contra la verdad (`docs/investigacion-gt-caso-real.md:208`) | No implementado | **Sin fuente**: sintético pospuesto; los datasets no traen telemetría |
| ¿Sirven las métricas sin GT de la v13? | Clips con GT | `sin_gt.csv` vs `metricas.csv`, Kendall τ (`docs/investigacion-benchmark-boxmot.md:243-259`) | Parcial: `sin_gt.csv` sí; τ no se calcula en el run | Pendiente |
| ¿Cuánto tarda cada tracker? | Cualquiera | `<seq>_tiempos.csv` (ms por etapa) | Implementado | Se reporta, no decide [Usuario] |
| ¿Cambia el ranking con el tamaño de objeto? | Los tres | Estratos por área (A5) | No implementado | — |

---

## 3. Limitaciones

### 3.1 Del diseño (datos y dominio)

| # | Limitación | Detalle y fuente |
|---|---|---|
| L1 | **No hay verdad física de `moving` sin el sintético** | `moving` se deriva con la H de referencia y se revisa a mano. En oblicuas, los objetos elevados o cercanos parecen moverse tras estabilizar, así que el GT derivado **hereda el paralaje** que se quiere medir (`docs/investigacion-gt-existente.md:154`). La única verdad física sería SynDrone/CARLA (`docs/investigacion-gt-caso-real.md:203`), hoy pospuestos. El decisor se mide contra una etiqueta de fiabilidad "media" en cenital y "baja" donde falla la H |
| L2 | **UCMC no se evalúa como en producción** | En producción recibe la cámara por telemetría (`benchmark/README.md:89-90`); en los datasets se evalúa con calibración automática o con la cámara de la rejilla (D17). Los datasets no dan hfov + pitch + altitud por frame (`docs/investigacion-gt-existente.md:174`) |
| L3 | **Ego-movimiento suave en la fuente disponible** | UAVDT y VisDrone son "hovering or slow cruising" (`docs/investigacion-gt-caso-real.md:14`); el bin `rapido` puede quedar casi vacío. DynUAV, la única fuente con ego fuerte y GT humano, tiene acceso incierto (Baidu) y **sin licencia de datos** (`docs/investigacion-gt-existente.md:77-78`) |
| L4 | **Dominio distinto al real** | UAVDT es 1080×540 a 30 fps (`docs/investigacion-gt-existente.md:62`), con altitudes por bandas; VisDrone mezcla resoluciones; DynUAV vuela a 80–120 m. El dron real (DJI, urbano) no tiene GT propio y no se puede volar por ahora [Usuario]. Los resultados son **por dataset**, nunca promediados entre fuentes (`docs/investigacion-gt-caso-real.md:206`) |
| L5 | **El detector actual no sirve** | COCO/DOTA preentrenados (D3) darían DetA muy bajo en objetos de pocos px; hay que entrenar en el train de UAVDT/VisDrone (`docs/investigacion-gt-existente.md:173`). Hasta entonces ningún número con GT es interpretable |
| L6 | **Licencias research-only** | UAVDT "research purpose only"; VisDrone y DynUAV sin licencia declarada; uso interno, sin redistribuir datos ni GT convertido; pedir permiso escrito a DynUAV antes de publicar (`docs/investigacion-gt-existente.md:175`, `docs/investigacion-gt-existente.md:78`) |
| L7 | **Pocas secuencias → IC anchos** | El bootstrap es por secuencia (`benchmark/estadistica.py:9-10`); con 20 secuencias de test de UAVDT y 7 de DynUAV los IC pueden ser anchos. El bootstrap por bloques temporales sigue pendiente (A4) |
| L8 | **La latencia del decisor está limitada por la anotación** | Tiene la resolución de los frames anotados (`benchmark/README.md:126`); UAVDT se anotó con VATIC, con interpolación (`docs/investigacion-gt-existente.md:169`), así que las transiciones de `moving` heredan esa interpolación. No interpretar latencias por debajo de esa resolución |
| L9 | **hfov 82° por defecto, probablemente diagonal (A7)** | `CamaraUCMC.hfov_deg = 82.0` (`VD - Trackers To Real Implementation/tracker_ucmc.py:109`); las fichas DJI dan el FOV diagonal y el horizontal en 16:9 sería ~70–74° (`docs/investigacion-ucmc-fuerza-bruta.md:169`). El pitch automático depende de él (vigia_8: 52° con hfov 60, 63° con 82; `VD - Trackers To Real Implementation/README.md:143`) |
| L10 | **El sintético de las pruebas no prueba la sensibilidad de cámara** | El video de `pruebas_benchmark.py` es un paneo plano de 3 px/frame (`benchmark/README.md:113`); la integración del barrido usa una rejilla de 2×2 en cenital y solo comprueba la mecánica de selección y que el oráculo quede fuera del ranking (`benchmark/pruebas_benchmark.py:272-321`). No comprueba que la rejilla recupere una cámara conocida |
| L11 | **UAVDT: geometría de cámara incierta** | Dron DJI Inspire 2, cámara no declarada; 1080×540 es 2:1 y no se sabe si es recorte o reescalado anamórfico (NO VERIFICADO; `docs/investigacion-ucmc-fuerza-bruta.md:134-136`). El parámetro `aspecto` existe pero está sin verificar (`VD - Trackers To Real Implementation/README.md:201`) |
| L12 | **UAVDT: la vista cambia dentro de la secuencia** | Frontal y lateral pueden convivir (`docs/investigacion-ucmc-fuerza-bruta.md:137`), pero `toma` (punto de apoyo de `moving` y de UCMC) y `grupo` son uno por secuencia (`benchmark/comunes.py:54-55`) |
| L13 | **DynUAV rompe el supuesto de cámara fija por secuencia** | Zoom digital 1–4×: ningún hfov fijo es correcto; en oblicua el zoom puro no encaja en la descomposición del `CalibradorCamara` (NO VERIFICADO su efecto); la CMC no rota la velocidad del Kalman en giros (`docs/investigacion-ucmc-fuerza-bruta.md:186-194`). Ahí el número relevante es `ucmc` auto (`docs/investigacion-ucmc-fuerza-bruta.md:193`) |
| L14 | **Supuestos de UCMC** | Suelo plano, sin alabeo, y que el dron se desplace de vez en cuando (en hover puro usa `pitch_respaldo_deg`) (`VD - Trackers To Real Implementation/README.md:171-174`); el pitch automático va ~1 s atrasado (`VD - Trackers To Real Implementation/README.md:167-169`) |
| L15 | **El detector se entrena en el mismo train que se usa como ajuste** [Observación] | Si el train de UAVDT/VisDrone sirve a la vez para entrenar el detector y como `split: ajuste` de la rejilla, las detecciones en ajuste serán mejores que en test, y la cámara elegida (`grupo_train`) y la validación de `singt` se harían con un detector sobreajustado. Ningún informe lo trata; queda como decisión abierta (§5.2) |

### 3.2 Del código (supuestos, huecos e inconsistencias) [Observación]

| # | Hallazgo | Dónde |
|---|---|---|
| I1 | **Corregido 2026-11-23.** **D17.6 no se aplica automáticamente.** `seleccion.csv` marca `valido` para `singt` (`benchmark/barrido.py:237`, `benchmark/barrido.py:243`), pero `camara_de_seleccion` no lo mira (`benchmark/barrido.py:269-276`) y `ucmc_singt` tiene `uso_gt = no` (`benchmark/correr.py:60`), así que entra en `COMBINADO` y en `comparaciones.csv` aunque el criterio no se haya validado. Hoy hay que quitarlo a mano del manifiesto | `benchmark/barrido.py`, `benchmark/correr.py`, `benchmark/evaluar.py:512` |
| I2 | **Corregido 2026-11-23.** **Los combinados por bin y del decisor incluyen las secuencias de ajuste.** `bins_comb` se llena sin filtrar por split (`benchmark/evaluar.py:483`) y el `COMBINADO` de `por_bin_ego.csv` suma todas (`benchmark/evaluar.py:503-509`); `decisor.csv` y `latencias.csv` también se escriben para las de ajuste. Choca con D14 ("solo split `test`") y con "los de ajuste NUNCA se reportan" (`benchmark/comunes.py:49`) | `benchmark/evaluar.py` |
| I3 | **Corregido 2026-11-23.** **`ucmc` auto y la rejilla usan hfov distintos.** Las secuencias declaran `hfov_deg: 82` (`benchmark/secuencias.yaml:64`) y la rejilla usa 74 (`benchmark/secuencias.yaml:47`); la diferencia `ucmc` vs `ucmc_grupo_train` mezcla cámara elegida y hfov. Al dar de alta los datasets, `ucmc.hfov_deg` debe ser el mismo del grupo | `benchmark/secuencias.yaml` |
| I4 | **La rejilla de altura no es la banda física del grupo.** `altura: [30, 50, 80]` en `cenital` y `oblicua` (`benchmark/secuencias.yaml:46`, `:51`), mientras D17.2 pide la banda del grupo; el informe proponía alturas centrales 20/50/100 m × {0.6, 1, 1.6} por altitud de UAVDT (`docs/investigacion-ucmc-fuerza-bruta.md:143-147`). La banda baja de UAVDT (10–30 m) no queda cubierta | `benchmark/secuencias.yaml:41-55` |
| I5 | **hfov por dataset no está en el manifiesto.** El informe fija UAVDT 74°, VisDrone 74° y DynUAV 70° (`docs/investigacion-ucmc-fuerza-bruta.md:273`), pero los grupos son solo `cenital`/`oblicua` con 74°. Hacen falta grupos con prefijo de dataset | `benchmark/secuencias.yaml:43-55` |
| I6 | **`bench.py todo` no incluye `moving` ni `barrer`** (`benchmark/bench.py:105-106`): la etiqueta `moving` y la rejilla hay que correrlas a mano y en orden (§4) | `benchmark/bench.py` |
| I7 | **La derivación automática de respaldo no filtra clases.** `bench.py moving` pasa `clases_evaluadas` (`benchmark/bench.py:47-48`), pero `cargar_moving` sin `gt_moving` llama a `derivar_moving` sin `clases` (`benchmark/gt.py:123`). Efecto menor (las regiones ignoradas se quitan después en `preparar`) | `benchmark/gt.py` |
| I8 | **El harness lee video con `cv2.VideoCapture`** (`benchmark/comunes.py:112-150`) y, si el archivo no declara fps, usa 30 (`benchmark/comunes.py:117`). Si UAVDT/VisDrone se distribuyen como carpetas de imágenes (NO VERIFICADO en los informes), el conversor tendrá que empaquetarlas o usar un patrón, y declarar `fps:` por secuencia (`benchmark/comunes.py:48`) | `benchmark/comunes.py` |
| I9 | **Doble confirmación en UCMC (no es un error, es un supuesto).** El núcleo de UCMC confirma tras 3 detecciones (`VD - Trackers To Real Implementation/tracker_ucmc.py:519`), y después su salida pasa por `LibroTracks` (`VD - Trackers To Real Implementation/tracker_ucmc.py:602`), que solo emite tracks con `hits ≥ min_hits` = 4 y detección en el frame (`VD - Trackers To Real Implementation/comun.py:400`). La política D6 queda igual en la salida, pero UCMC tiene un umbral de confirmación interno propio para asociar | `tracker_ucmc.py`, `comun.py` |
| I10 | **`ucmc_altura_defecto_m` = 100 m en silencio** si `altura_m` es `None` y la altura no se calibra (`VD - Trackers To Real Implementation/tracker_ucmc.py:89`, `:209`; `docs/investigacion-ucmc-fuerza-bruta.md:81`). La rejilla siempre pasa `altura_m`, así que solo afecta a configuraciones a mano | `tracker_ucmc.py` |
| I11 | **Rutas de VIGIA con mayúscula** (`/Users/Alex/...`, `benchmark/secuencias.yaml:61`) frente al usuario `alex`; funciona en macOS por no distinguir mayúsculas, pero no es portable. Desaparece al reemplazar VIGIA | `benchmark/secuencias.yaml` |
| I12 | Lo que el informe proponía y **no se implementó**: refinamiento coarse-to-fine alrededor del mejor pitch, sensibilidad de hfov ±1 valor, `ucmc_oraculo_cruzado` y `ucmc_rejilla_{mediana,peor}` (`docs/investigacion-ucmc-fuerza-bruta.md:248-251`, `:286-291`). La rejilla actual es completa y fija | `benchmark/barrido.py:171-177` |

---

## 4. Flujo de trabajo

Todos los comandos se corren desde `benchmark/` (`benchmark/README.md:21-30`). `--seq A B` limita a algunas secuencias y `--rehacer` ignora las cachés (`benchmark/README.md:32`). Leyenda: **[I]** implementado · **[P]** pendiente · **[M]** manual (fuera del código).

| # | Paso | Comando / acción | Produce | Estado | Esfuerzo (fuente) |
|---|---|---|---|---|---|
| 0 | Comprobar el harness | `python pruebas_benchmark.py` → debe terminar en `TODO OK` | — | [I] (`benchmark/pruebas_benchmark.py:331-339`) | Minutos |
| 1 | Conseguir los datos | Descargar UAVDT (Google Drive, sin registro) y VisDrone2019-MOT (directo); **pedir acceso y permiso a DynUAV** (Baidu) | Carpetas locales (no se redistribuyen) | [M] | UAVDT/VisDrone: descarga; DynUAV: "acceso incierto, pedir permiso de uso" (`docs/investigacion-gt-existente.md:210`) |
| 2 | **Conversores** UAVDT/VisDrone(/DynUAV) → formato del harness | Script nuevo: `gt.txt` MOT 1.1 (`vehicle` = 1; ignorados → clase 0; VisDrone 0/11 → 0), video legible por OpenCV, `fps`, y **`grupo` desde `M_attr/*_attr.txt`** (altitud × vista) en UAVDT; grupo cenital/oblicua a mano en VisDrone/DynUAV | `gt.txt` por secuencia + entradas para `secuencias.yaml` | [P] (no hay código; `docs/investigacion-ucmc-fuerza-bruta.md:308`) | UAVDT ≈ 1 día; VisDrone ≈ 0.5 día; DynUAV ≈ 0.5 día (`docs/investigacion-gt-existente.md:206`, `:209`, `:210`) |
| 3 | **Reescribir `secuencias.yaml`** | Quitar VIGIA; dar de alta cada secuencia con `split` (`ajuste` = train, `test`), `grupo`, `toma`, `ucmc: {hfov_deg, pitch_respaldo_deg}`, `camara_fuente: ficha`, `gt`; **rejilla por grupo** en `barrido.grupos` con hfov por dataset (I3–I5) y alturas dentro de la banda; `evaluacion.clases_*` según el conversor | Manifiesto nuevo | [P] (hoy lista vigia_4/1/5/9/10, `benchmark/secuencias.yaml:57-96`) | Sin estimación en los informes |
| 4 | **Entrenar el detector** | YOLO en el train de UAVDT/VisDrone; perfil nuevo en `detectores:` (pesos, imgsz, clases, `conf_cache` 0.05) | Pesos `.pt` | [P] | 0.5–1 día de GPU (`docs/investigacion-gt-existente.md:206`) |
| 5 | Detecciones cacheadas | `python bench.py detectar [--dispositivo mps]` | `cache/detecciones/<det>/<seq>.npz` + `.json` con firma | [I] (`benchmark/detecciones.py:39-79`) | Cómputo |
| 6 | Ego-movimiento de referencia | `python bench.py ego` | `cache/ego/<seq>.csv` (H, `ego_px`, `ego_rot_deg`, `ego_scale`, `H_ok`, `ego_px_1s`) | [I] (`benchmark/ego.py:144-166`) | Cómputo |
| 7 | Etiqueta `moving` | `python bench.py moving` → revisar `moving_revisar.csv` (dudosos y cambios de estado), corregir y guardar `moving.csv`; ponerlo en `gt_moving:` | `<gt>/moving_auto.csv`, `<gt>/moving_revisar.csv`, `moving.csv` revisado | Código [I] (`benchmark/bench.py:39-54`); revisión [M] | Revisar solo la lista, no todo (`docs/investigacion-gt-existente.md:158`); horas sin estimar |
| 8 | Rejilla de cámara de UCMC (D17) | `python bench.py barrer --run b1` | `runs/b1/barrido/resultados.csv`, `seleccion.csv`, `validacion_singt.csv`, `barrido.json`; caché `cache/entrada/<seq>.npz` | [I] (`benchmark/barrido.py:180-219`) | ~20–60 pruebas por secuencia, ~1 000 corridas del núcleo con 20 secuencias de test (`docs/investigacion-ucmc-fuerza-bruta.md:252`); costo por prueba NO VERIFICADO (`docs/investigacion-ucmc-fuerza-bruta.md:246`) |
| 9 | Revisar la validación de `singt` | Leer `validacion_singt.csv`; si la ρ media no es ≤ −0.6, `ucmc_singt` sale solo en `COMBINADO_NO_VALIDADO` (I1 corregido) | — | [M] | Minutos |
| 10 | Correr los trackers | Añadir las versiones de UCMC en `trackers:` (§2.2) y `python bench.py correr --run v1` | `runs/v1/<tracker>/<seq>.txt`, `_lateral.csv`, `_tiempos.csv`, `runs/v1/run.json` | [I] (`benchmark/correr.py:132-149`) | Cómputo |
| 11 | Evaluar | `python bench.py evaluar --run v1` | `runs/v1/eval/metricas.csv`, `por_bin_ego.csv`, `decisor.csv`, `latencias.csv`, `sin_gt.csv`, `comparaciones.csv` | [I] (`benchmark/evaluar.py:431-526`) | Cómputo |
| 12 | Fracción de rejilla que gana | `python bench.py barrer --run b1 --contra v1` | `runs/b1/barrido/fraccion_rejilla_gana.csv` | [I] (`benchmark/bench.py:83-88`) | Cómputo (repite la rejilla) |
| 13 | Informe por dataset | Tablas y curvas de sensibilidad por grupo, auto/grupo_train/oráculo, Δ con IC (`docs/investigacion-ucmc-fuerza-bruta.md:261-266`) | — | [P] | Sin estimación |

Notas:
- Pasos 5–7 y 10–11 se pueden encadenar con `python bench.py todo --run v1`, que hace detectar → ego → correr → evaluar, **sin** `moving` ni `barrer` (I6).
- El orden importa: `barrer` (8) necesita detecciones (5) y, para elegir `grupo_train` y validar `singt`, secuencias `ajuste` con GT (`benchmark/barrido.py:251-256`); `correr` (10) necesita `seleccion.csv` para las versiones elegidas.
- **Coste total de ingeniería** del informe anterior: ~5–7 días-persona (conversores y detector) (`docs/investigacion-gt-existente.md:217`); incluía el conversor de SynDrone (2–3 días, `docs/investigacion-gt-existente.md:207`), hoy pospuesto, así que lo pendiente para UAVDT + VisDrone + DynUAV queda en torno a 2–3 días de conversores más 0.5–1 día de GPU [Derivado de las cifras citadas].

---

## 5. Decisiones abiertas y siguiente paso

### 5.1 A1–A8 de `DECISIONS.md`, actualizadas al nuevo caso de uso

| # | Pregunta original (`benchmark/DECISIONS.md:44-55`) | Estado con el caso de uso actual |
|---|---|---|
| A1 | ¿Qué clips/tramos de VIGIA anotar? | **Obsoleta.** VIGIA no se anota [Usuario]. La pregunta pasa a ser qué secuencias de UAVDT/VisDrone/DynUAV entran y con qué grupos |
| A2 | ¿Ajustar hiperparámetros? | **Sigue abierta.** Hoy: defaults (D16). Si se quisiera la opción (b), los 3 rivales reciben el mismo presupuesto en train que la rejilla de UCMC (`docs/investigacion-ucmc-fuerza-bruta.md:234-237`). Con D17.2 (altura acotada por física) basta declararlo y dejar los rivales en defaults |
| A3 | ¿Agregar VisDrone-MOT / UAVDT? | **Resuelta: sí**, son las fuentes principales [Usuario]. La implementación (conversor, detector entrenado) sigue pendiente (§4, pasos 2 y 4) |
| A4 | Incertidumbre con pocos clips: bootstrap por bloques | **Sigue abierta**, con menos urgencia: con 20 secuencias de test en UAVDT el bootstrap por secuencia es más usable que con 4–5 clips; DynUAV (7 de test) sigue siendo corto |
| A5 | Estratificar por tamaño de objeto | **Sigue abierta y gana peso:** a 80–120 m los objetos son de pocos px y el IoU 0.5 se rompe con 3 px de error en una caja de 16×16 (`docs/investigacion-benchmark-boxmot.md:226`) |
| A6 | Baselines extra (OC-SORT, BoostTrack…) | **Sigue abierta**, opcional |
| A7 | hfov por dron (82° por defecto, probablemente diagonal) | **Sigue abierta y bloquea** la interpretación de `ucmc` auto (I3, L9). El barrido ya usa 74° (D17.1); falta decidir si se corrige el default y fijar `ucmc.hfov_deg` por dataset (UAVDT 74, VisDrone 74, DynUAV 70; `docs/investigacion-ucmc-fuerza-bruta.md:273`). Para el dron real, el FOV vendrá de telemetría [Usuario] |
| A8 | fps real de VIGIA | **Obsoleta.** Se reemplaza por: declarar `fps` de cada secuencia de los datasets (UAVDT 30 fps; DynUAV fps NO VERIFICADO, `docs/investigacion-gt-existente.md:76`) (I8) |

### 5.2 Nuevas decisiones que el diseño necesita (todas aparecen en los informes o en el código; ninguna está fijada)

1. **Separación detector / ajuste (L15):** ¿qué parte del train entrena el detector y qué parte se usa como `split: ajuste`? ¿Se usa VisDrone `val` como ajuste?
2. **Grupos y rejilla por dataset (I4, I5):** alturas por banda de UAVDT y hfov por dataset en `barrido.grupos`.
3. ~~Aplicar D17.6 (I1) y filtrar el ajuste en bins y decisor (I2)~~ — hecho 2026-11-23.
4. **Aspecto de píxel de UAVDT (L11):** comprobarlo sin GT con autos horizontales y verticales en cenitales (`docs/investigacion-ucmc-fuerza-bruta.md:136`).
5. **DynUAV:** si llega el acceso, estratificar "con zoom / sin zoom" y tratar `ucmc` auto como el número relevante (`docs/investigacion-ucmc-fuerza-bruta.md:192-194`).
6. **Cuándo se retoma el sintético** (SynDrone/CARLA) para cerrar L1 y validar la calibración de UCMC (`docs/investigacion-gt-caso-real.md:202-203`).

### 5.3 Siguiente paso recomendado

Ordenado por lo que desbloquea más (todo sale del flujo de §4; no hay pasos nuevos):

1. **Pedir hoy el acceso y el permiso de DynUAV** (no bloquea nada y es lo de plazo más incierto).
2. **Cerrar A7 y la decisión 5.2.1** (hfov por dataset y separación detector/ajuste), y registrarlas en `DECISIONS.md` antes de mirar resultados con GT, como exige su regla (`benchmark/DECISIONS.md:3-4`).
3. **Escribir el conversor de UAVDT** con grupos desde `M_attr` y reescribir `secuencias.yaml` sin VIGIA, con la rejilla por grupo (pasos 2–3; ≈ 1 día).
4. **Entrenar el detector** (paso 4; 0.5–1 día de GPU) y correr la cadena completa en UAVDT (pasos 5–12).
5. Después, VisDrone (≈ 0.5 día) y DynUAV si llega el acceso.

---

## 6. Referencias

**Código del repo**
- `benchmark/bench.py` — punto de entrada y comandos.
- `benchmark/comunes.py` — manifiesto (`Secuencia`, `Manifiesto`), lectura de video y de MOT.
- `benchmark/detecciones.py` — detector fijo y caché con firma.
- `benchmark/ego.py` — H de referencia independiente y bins de ego.
- `benchmark/gt.py` — frames anotados y etiqueta `moving`.
- `benchmark/correr.py` — ejecución de trackers y versiones (`uso_gt`).
- `benchmark/evaluar.py` — preprocesado, TrackEval, bins, decisor, latencias, sin GT, combinados.
- `benchmark/estadistica.py` — bootstrap pareado y Kendall τ.
- `benchmark/barrido.py` — rejilla de cámara de UCMC y selección D17.
- `benchmark/pruebas_benchmark.py` — validación del harness.
- `benchmark/secuencias.yaml` — manifiesto (hoy con VIGIA).
- `benchmark/README.md`, `benchmark/DECISIONS.md` — uso y decisiones D1–D17, A1–A8.
- `VD - Trackers To Real Implementation/README.md`, `VD - Trackers To Real Implementation/tracker_ucmc.py` — contrato de los trackers, calibración de UCMC, `CamaraUCMC`, `ConfigUCMC`.

**Informes**
- `docs/investigacion-benchmark-boxmot.md` — por qué harness propio + TrackEval y no BoxMOT; métricas y protocolos P1/P1'/P2; derivación de `moving`.
- `docs/investigacion-gt-existente.md` — fichas de UAVDT, VisDrone, DynUAV y demás; riesgos (clases, licencias, detector); costos de conversores y detector.
- `docs/investigacion-gt-caso-real.md` — cambio de premisa (VIGIA fuera), DynUAV como ego fuerte, sintético y warps, estratos.
- `docs/investigacion-ucmc-fuerza-bruta.md` — protocolo D17, sensibilidad y redundancias de la cámara, rangos por dataset, justicia y leakage.

**Fuentes externas principales** (verificadas en los informes; URLs en sus secciones de fuentes)
- UAVDT — Du et al., ECCV 2018, arXiv 1804.00518 (`docs/investigacion-gt-existente.md:263`).
- VisDrone — Zhu et al., arXiv 2001.06303 (`docs/investigacion-ucmc-fuerza-bruta.md:326`).
- DynUAV — Ye et al., CVPR 2026, arXiv 2603.05970 (`docs/investigacion-gt-existente.md:265`).
- HOTA — Luiten et al., IJCV 2021, arXiv 2009.07736; MOTChallenge — Dendorfer et al., arXiv 2010.07548 (`docs/investigacion-ucmc-fuerza-bruta.md:329-330`).
- UCMCTrack — Yi et al., AAAI 2024, arXiv 2312.08952 (`docs/investigacion-ucmc-fuerza-bruta.md:324`).
- TrackEval fork 1.3.0 y comparación con BoxMOT (`docs/investigacion-benchmark-boxmot.md:50-52`).
