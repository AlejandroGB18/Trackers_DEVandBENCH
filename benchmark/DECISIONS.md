# Decisiones del benchmark

Regla: estas decisiones se fijan **antes** de ver resultados con GT. Si una cambia después, se anota aquí con fecha y
motivo, y los resultados anteriores dejan de ser comparables con los nuevos.

## Fijadas (2026-11-17)

| # | Decisión | Valor | Por qué |
|---|---|---|---|
| D1 | Juez | Métricas de `trackeval==1.3.0` (HOTA, CLEAR, Identity, Count) con preprocesado propio | Implementación de referencia de HOTA; el fork de PyPI corrige `np.float`. BoxMOT ya no usa TrackEval y trata distinto las regiones ignoradas |
| D2 | Detecciones | Una caché por secuencia, umbral 0.05; entra al tracker lo ≥ `conf_entrada` = 0.10 | Mismas cajas para los 4; los trackers hacen una 2.ª ronda con débiles (`conf_low` 0.10) |
| D3 | ~~Detectores~~ | ~~`yolo11n-obb` / `yolo11n`, imgsz 1280~~ — **reemplazada por D20 (2026-11-23)** | Eran para VIGIA |
| D4 | Config de trackers | Los defaults de los `.py`, `use_proposals=False`, `min_hits=4`, `max_miss_sec=1.0` | Las propuestas sin clase serían FP en un benchmark de clases conocidas |
| D5 | Implementación de ByteTrack / BoT-SORT | Las de Ultralytics 8.4.x (vía `adaptador_ultralytics.py`) | Continuidad con v9–v14; las de BoxMOT tienen otros defaults y no son intercambiables |
| D6 | Política de salida | Solo tracks confirmados con detección en el frame (igual en los 4) | Emitir predicciones sin detección cambia DetA |
| D7 | Clase evaluada | `vehicle` (todas las de vehículo fusionadas); evaluación agnóstica de clase en las predicciones | Evita IDSW falsos por oscilación car↔truck |
| D8 | Regiones ignoradas | Se descarta la predicción con ≥ 50 % de su área dentro | Regla del toolkit oficial de VisDrone |
| D9 | Frames evaluados | Solo los anotados (`gt_frames`); en UAVDT son **todos** (D19) | CLEAR/Identity/HOTA emparejan por frame |
| D10 | H de referencia | SIFT a 1920 px, cajas enmascaradas, USAC_MAGSAC 1 px, ida-vuelta ≤ 1 px, ≥ 40 inliers | Independiente de `comun.Estabilizador` (LK+RANSAC a 960), para no heredar sus errores |
| D11 | Bins de ego-movimiento | `ego_px` (rejilla 3×3, px a 960) con mediana centrada de 0.5 s. ~~Umbrales fijos 0.5 / 3~~: **los cortes los fija D26** | La medida se mantiene; los umbrales de VIGIA no aplican a UAVDT |
| D12 | `moving` del GT | Ventana centrada 1 s, punto de apoyo (base en oblicuas, centro en cenitales); móvil si d ≥ 0.30·L y ≥ 3 px@960; quieto si d ≤ 0.10·L; resto dudoso; **revisión humana** de dudosos y cambios | Criterio semántico (≈1.35 m/s para 4.5 m), distinto del decisor para no premiar su configuración |
| D13 | Dudosos | Distractores en `moviles`/`estaticos`/`e2e_moviles`; fuera de la confusión del decisor | No castigar ni premiar lo ambiguo |
| D14 | Combinado | Suma de conteos (como TrackEval), solo split `test` | Promediar HOTA por secuencia pesa igual clips de 5 y de 80 objetos |
| D15 | Determinismo | `cv2.setRNGSeed(0)` antes de cada secuencia | El RANSAC del Estabilizador es aleatorio |
| D16 | Ajuste de hiperparámetros | Ninguno por ahora: se reportan defaults. Los ruidos del Kalman no se ajustan nunca con datos de evaluación | Regla ya vigente en el proyecto |

## D17 · Cámara de UCMC sin telemetría ("fuerza bruta") — fijada 2026-11-21

Contexto: el caso real tiene telemetría completa, pero los datasets públicos no. Por ahora no se usa el sintético
(SynDrone), así que la cámara de UCMC se busca en una rejilla (`bench.py barrer`). Detalle y fuentes en
[`docs/investigacion-ucmc-fuerza-bruta.md`](../docs/investigacion-ucmc-fuerza-bruta.md).

| # | Regla | Por qué |
|---|---|---|
| D17.1 | Se barren solo **pitch × altura**; el **hfov se fija por dataset** con la ficha (≈74° para DJI 24 mm eq. en 16:9) | En UCMC la altura es una escala global y hfov y pitch son casi colineales: 2 grados de libertad reales |
| D17.2 | La altura solo se mueve **dentro de la banda física del grupo** (p. ej. atributos de altitud de UAVDT) | Barrer la altura libremente = ajustar wx, wy, vmax y `a` de UCMC (choca con D16) |
| D17.3 | **Punto de apoyo fijado por grupo** (cenital = centro, oblicua = base), no por el pitch barrido | El modo "auto" cambia de punto a los 30°, en mitad de la rejilla |
| D17.4 | Versiones reportadas: `ucmc` (auto, en línea), `ucmc_grupo_train` (mejor de la rejilla en las secuencias de **ajuste** del grupo, aplicada a test), `ucmc_singt` (criterio sin GT) y `ucmc_oraculo_seq` (mejor por secuencia de test) | Separar "conocer la clase de vuelo" de "conocer la cámara perfecta" |
| D17.5 | `ucmc_oraculo_seq` (`uso_gt=test`) **no entra al ranking**: sale en `COMBINADO_COTA` y fuera de `comparaciones.csv` | Elegir con el GT de test es un oráculo (regla de MOTChallenge) |
| D17.6 | `ucmc_singt` solo entra al ranking si su Spearman con HOTA en ajuste es ≤ −0.6 (`validacion_singt.csv`). Automático: `seleccion.csv → valido`; si es falso, `en_ranking = false` y sale como `COMBINADO_NO_VALIDADO` | Un criterio sin GT no validado no debe decidir |
| D17.7 | Objetivo de la selección: HOTA combinado (suma de conteos), AssA como desempate; se reporta DetA y `n_fuera` | La cámara cambia qué detecciones caen sobre el horizonte |
| D17.8 | Los otros 3 trackers se quedan con defaults (D4/D16) | La búsqueda de UCMC es de **cámara** (lo que en producción da la telemetría), acotada por física y elegida en ajuste |

## v1 con UAVDT — fijadas 2026-11-23

Acordadas en el *grilling* del 2026-11-23. Plan de ejecución: [`docs/plan-benchmark-v1.md`](../docs/plan-benchmark-v1.md).
Vocabulario: [`GLOSSARY.md`](../GLOSSARY.md).

| # | Decisión | Valor | Por qué |
|---|---|---|---|
| D18 | Fuente de GT | Solo **UAVDT-MOT**: train oficial (30) = ajuste, test oficial (20) = test | Única fuente con vehículos, entorno urbano, DJI y atributos de altitud y vista ([ADR 0001](../docs/adr/0001-uavdt-unica-fuente-de-gt.md)) |
| D19 | Frames y cajas | Todos los frames; todas las cajas de vehículo (car, truck y bus → `vehicle`); solo se aplican las regiones ignoradas de UAVDT (D8), sin filtrar por oclusión ni por fuera de vista | UAVDT anota cada frame; filtrar por oclusión sería una elección más que justificar |
| D20 | Detector | Un solo **YOLOv8x del laboratorio (`yolo8x_best.pt`)**, entrenado en un subconjunto curado de VisDrone (~1700 imágenes; car, truck, van, bus y freight car → `vehicle`; imgsz 640), sin reentrenar; detecciones generadas una vez con umbral 0.05 y leídas desde archivo. Prueba en la Mac con `yolo8n_best.pt` (no reportable) | Sin fuga de datos, sin partir el train, ahorra ~medio día ([ADR 0002](../docs/adr/0002-detector-visdrone-sin-reentrenar.md)) |
| D21 | Umbrales del detector | `conf_high` en el punto de mejor F1 del detector y `conf_low` = el umbral más bajo con precisión ≥ 0.5 (no baja de 0.05, el de la caché), medidos en ajuste con `bench.py ajuste`; `conf_entrada` = `conf_low`; iguales para los 4 trackers | Los defaults venían de otra escala de confianza; se calibra el detector, no los trackers |
| D22 | Hiperparámetros | Defaults en los 4 trackers (D4, D16); solo la cámara de UCMC se elige en ajuste (D17) | La cámara es una entrada física (telemetría en producción), no un hiperparámetro de asociación |
| D23 | Ranking | Una entrada por tracker: propio_kf, ByteTrack, BoT-SORT y `ucmc_grupo_train`. `ucmc` automático = referencia (`en_ranking: false`); `ucmc_oraculo_seq` = cota. `ucmc_singt` fuera de la v1 | Dos versiones de UCMC en el ranking serían dos oportunidades de ganar |
| D24 | Grupos de vuelo | cenital (vista cenital), oblicua_baja (frontal o lateral con altitud de 10–30 m) y oblicua_alta (frontal o lateral, > 30 m), con la rejilla de cámara de UCMC dentro de esas bandas de altura | Cruzar altitud × vista deja celdas con 0–1 secuencias de ajuste |
| D25 | Exclusión | Un estrato (grupo de vuelo o iluminación) con DetA < 20 en ajuste sale completo del ranking, para los 4 trackers; se decide y se escribe antes de test | Si el detector falla, la asociación no es evaluable; decidir después sesgaría |
| D26 | Tramos de ego | Cortes en los percentiles 33 y 67 de `ego_px` en ajuste → bajo, medio y alto. Si el alto no cumple D28 en ajuste, se pasa a **dos tramos cortando en la mediana** (corregido 2026-11-25: "bajo < P33 contra alto ≥ P67" no agregaba datos al tramo alto). Se reportan los px por frame de cada corte; los cortes se congelan en `evaluacion.tramos_ego` | UAVDT no trae movimiento de cámara; P1 se mide sobre el ego que existe, sin sintético |
| D27 | Movimiento real | Etiqueta automática (D12), más revisión humana por track en test: dudosos, cambios de estado y el 10 % de los seguros. Los umbrales de D12 se pueden recalibrar con la revisión, antes de ver los trackers. Se reporta el acuerdo entre la etiqueta automática y la humana | Revisar frame por frame no cabe; se calibra la etiqueta, no el resultado |
| D28 | Estadística | Unidad = secuencia; bootstrap pareado con IC 95 %; "gana" solo si el IC excluye 0, si no es empate técnico; P1 = ΔAssA entre tramos, P2 = F1 del decisor; un tramo con < 2000 detecciones del GT o < 5 secuencias es solo indicativo | 20 secuencias de test; frames de un mismo video no son independientes |
| D29 | Ejecución | Desarrollo y prueba con una muestra aquí; ejecución completa en el laboratorio (Linux, conda), por etapas, congelando entre ajuste y test; test se corre una vez | Los modelos y datos viven en el laboratorio |
| D30 | Arquitectura | v1 enfocada: adaptador de UAVDT y lectura de detecciones externas como módulos separados; el núcleo no se toca para crecer | Horizonte de una semana; sin cerrar la puerta a VisDrone o a la v2 |
| D31 | Entregable | `docs/resultados-v1.md` con figuras PNG reproducibles desde `eval/` | Pasa casi directo a la tesis |

## Congelado 1 — 2026-11-25

Con la corrida de ajuste del laboratorio (`runs/v1_ajuste`, código = `main` 909f53b, igual a 741a4f3 en `benchmark/`;
"+cambios" solo por `logs/` sin rastrear). Detector `yolo8x`, 30 secuencias, 23 829 frames, 422 911 cajas del GT.
Nada de test se ha mirado. Valores escritos en `secuencias.yaml`.

| # | Qué | Valor congelado | Evidencia (ajuste) |
|---|---|---|---|
| D32.1 | Umbrales (D21) | `conf_high` **0.20**, `conf_low` **0.05**, `conf_entrada` **0.05**, iguales para los 4 | F1 máximo 0.808 en 0.20 (P 0.87, R 0.76); en 0.05 la precisión es 0.78 ≥ 0.5, así que `conf_low` queda en el piso de la caché |
| D32.2 | Exclusión (D25) | **Ninguna**: entran los 3 grupos y las 3 iluminaciones | DetA global 54.0; cenital 71.0, oblicua_alta 46.0, oblicua_baja 41.8; día 58.7, noche 54.1, niebla 36.7 (todos ≥ 20) |
| D32.3 | Tramos de ego (D26) | **Tres**: bajo < 0.328 ≤ medio < 1.241 ≤ alto (px/frame a 960) | P33 0.328, P50 0.75, P67 1.241, P90 2.68, máx 17.6. Tramo alto: 7 729 frames, 97 165 cajas del GT, 22 secuencias (cumple D28). H no fiable en 408 frames (1.7 %) |
| D32.4 | Cámara de UCMC (D17) | Rejillas y regla de selección **sin cambios**. El valor de `ucmc_grupo_train` sale del `barrer` de todas las secuencias que se corre ya con estos umbrales (paso del README antes de `correr`), y solo usa filas de ajuste | El barrido del día 2 se corrió con los umbrales anteriores (0.35/0.10), no con los congelados. Selección provisional: cenital pitch 0 / 50 m (HOTA 74.4), oblicua_alta 40 / 60 m (54.6), oblicua_baja 65 / 30 m (48.8). Si el definitivo cambia, se anota aquí antes de evaluar |
| D32.5 | `ucmc_singt` (D17.6, D23) | Fuera: **no validado** | Spearman medio con HOTA = −0.15 (hace falta ≤ −0.6) |

Observaciones (no cambian nada, van a limitaciones):
- Tres secuencias de ajuste tienen DetA < 20 por sí solas: M0207 (9.6; precisión 0.10, probablemente autos sin anotar
  en el GT), M0902 (7.6, noche) y M0501 (19.7, niebla). D25 excluye por estrato, no por secuencia, así que se quedan.
- Dos cámaras provisionales caen en el borde de su rejilla (cenital pitch 0; oblicua_baja 30 m, el tope de la banda).
  El borde de pitch 0 es físico; el de 30 m se revisa con el barrido definitivo.

## D33 · Correcciones al GT oficial de UAVDT (test) — 2026-11-26

La revisión humana de `moving` encontró errores en el `_gt.txt` oficial, confirmados contra los archivos y las
imágenes. Se corrigen **antes de correr cualquier tracker en test**, mirando solo GT e imágenes, y por igual para los
cuatro. Detalle y motivo por secuencia en [`adaptadores/correcciones_uavdt.yaml`](adaptadores/correcciones_uavdt.yaml),
que aplica `python -m adaptadores.uavdt`.

| Error | Secuencias | Corrección |
|---|---|---|
| Frame con cajas desplazadas (copiadas de otro frame) | M0601 (320–322), M1101 (322) | M0601: se evalúa y se corre solo 1–319. M1101: el frame 322 sale de la evaluación (`gt_frames.excluir`) |
| Anotación incompleta al final | M0601 (323–372: 9 cajas por frame con muchos autos visibles) | Cubierto por el fin en 319 |
| Caja de vehículo sobre fondo | M0606 (68, 69, 71, 112), M1007 (36), M1101 (7), M1401 (42, 66) | Pasan a región ignorada (clase 0, regla D8) |

Efecto: test pasa de 1227 a 1218 tracks evaluables. Ajuste no se tocó: el patrón de frames rotos no aparece ahí
(búsqueda en las 50 secuencias), y ~8 tracks de ajuste con caja > 4× la mediana quedan sin revisar; solo sirvieron
para umbrales (D32.1) y cámara (D32.4), donde su efecto es despreciable. Va a limitaciones, junto con autos
estacionados sin anotar.

## Congelado 2 — 2026-11-26

Revisión humana de `moving` en las 20 secuencias de test: 623 tracks decididos (533 dudosos, 14 con cambio de
estado y 76 seguros de muestra), en [`revision/decisiones/`](revision/decisiones/). `moving.csv` final = etiqueta
automática + decisión humana por track (`bench.py aplicar-revision`), con el GT ya corregido (D33).

| # | Qué | Valor congelado | Evidencia |
|---|---|---|---|
| D34.1 | Umbrales de `moving` (D12, D27) | **Se quedan** `rel_mov` 0.30 y `rel_est` 0.10 | Acuerdo automático-humano en los seguros de muestra: **76/76 (100 %)**. En la rejilla (`calibracion.csv`, 613 tracks casi todos dudosos) el mejor par es 0.25/0.05 con 0.798 contra 0.742 de los actuales, pero esos tracks ya llevan la etiqueta humana, así que cambiar los umbrales solo movería los seguros no revisados (donde el acuerdo es 100 %) y subiría los frames sin decidir de 36 % a 41 % |
| D34.2 | Decisión D ("No se puede") | El track queda en −1 (fuera de móviles y quietos). Los 8 de fondo además van a región ignorada (D33); M0203 23 y M0802 23 solo quedan en −1 | Semántica de la página de revisión |
| D34.3 | Resultado | 1218 tracks: 1030 móviles, 186 quietos, 2 sin decidir (mayoría por frames); frames: 82.1 % móvil, 16.2 % quieto, 1.8 % −1 | `moving.csv` de test |

Nota de proceso: la guía oral describió mal las teclas (A = "Propuesta OK", D = "No se puede"); la página mostraba los
nombres correctos y las decisiones se tomaron con ellos.

## Abiertas (decidir antes de anotar / reportar)

| # | Pregunta | Opciones |
|---|---|---|
| A1 | ~~¿Qué clips/tramos anotar?~~ **Obsoleta (D18): no se anota, se usa UAVDT** | Propuesta del informe: vigia_4 (rápido), tramo de vigia_1 (suave), tramo de vigia_9 o 10 (oblicuo), vigia_5 (estacionario) |
| A2 | ¿Ajustar hiperparámetros? **v1: no (D22)**; abierta para después | (a) solo defaults; (b) mismo presupuesto (p. ej. 100 pruebas Optuna) para los 4 en VisDrone/UAVDT `val` o en clips VIGIA reservados que no se reportan |
| A3 | ~~¿Agregar VisDrone-MOT / UAVDT?~~ **Resuelta: UAVDT (D18); VisDrone después de la v1** | Necesitan un conversor a este formato de GT (clases 0/11 → ignoradas) y un detector entrenado en VisDrone |
| A4 | Incertidumbre con pocos clips | Bootstrap por bloques temporales (5–10 s) dentro de cada clip (pendiente de implementar) |
| A5 | Tamaño de objeto | Estratificar por área de caja (<16², 16–32², 32–64², >64² px) — pendiente |
| A6 | Baselines extra | OC-SORT / BoostTrack de BoxMOT o Roboflow `trackers`, etiquetados como baselines y con la misma política de salida |
| A7 | hfov por dron | Hoy 82° por defecto en `CamaraUCMC`, probablemente el FOV **diagonal** de la ficha DJI; el horizontal en 16:9 sería ~70–74°. El barrido usa 74° (D17.1) y desde 2026-11-23 `secuencias.yaml` también (`ucmc.hfov_deg: 74`), para que `ucmc` y `ucmc_grupo_train` solo difieran en la cámara elegida; falta decidir si se corrige el default del `.py` |
| A8 | ~~fps real de VIGIA~~ **Obsoleta: UAVDT es 30 fps** | Se toma el del archivo; confirmar que no hay frames duplicados/variables |
