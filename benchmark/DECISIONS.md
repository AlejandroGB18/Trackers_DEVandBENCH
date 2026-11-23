# Decisiones del benchmark

Regla: estas decisiones se fijan **antes** de ver resultados con GT. Si una cambia después, se anota aquí con fecha y
motivo, y los resultados anteriores dejan de ser comparables con los nuevos.

## Fijadas (2026-11-17)

| # | Decisión | Valor | Por qué |
|---|---|---|---|
| D1 | Juez | Métricas de `trackeval==1.3.0` (HOTA, CLEAR, Identity, Count) con preprocesado propio | Implementación de referencia de HOTA; el fork de PyPI corrige `np.float`. BoxMOT ya no usa TrackEval y trata distinto las regiones ignoradas |
| D2 | Detecciones | Una caché por secuencia, umbral 0.05; entra al tracker lo ≥ `conf_entrada` = 0.10 | Mismas cajas para los 4; los trackers hacen una 2.ª ronda con débiles (`conf_low` 0.10) |
| D3 | Detectores | `yolo11n-obb` (cenitales, small/large vehicle), `yolo11n` (oblicuas, car/truck/bus/motorcycle), imgsz 1280 | Los de la v13. Preentrenados en DOTA/COCO, sin VIGIA → sin leakage en VIGIA |
| D4 | Config de trackers | Los defaults de los `.py`, `use_proposals=False`, `min_hits=4`, `max_miss_sec=1.0` | Las propuestas sin clase serían FP en un benchmark de clases conocidas |
| D5 | Implementación de ByteTrack / BoT-SORT | Las de Ultralytics 8.4.x (vía `adaptador_ultralytics.py`) | Continuidad con v9–v14; las de BoxMOT tienen otros defaults y no son intercambiables |
| D6 | Política de salida | Solo tracks confirmados con detección en el frame (igual en los 4) | Emitir predicciones sin detección cambia DetA |
| D7 | Clase evaluada | `vehicle` (todas las de vehículo fusionadas); evaluación agnóstica de clase en las predicciones | Evita IDSW falsos por oscilación car↔truck |
| D8 | Regiones ignoradas | Se descarta la predicción con ≥ 50 % de su área dentro | Regla del toolkit oficial de VisDrone |
| D9 | Frames evaluados | Solo los anotados (`gt_frames`, paso 3 ≈ 10 fps); los trackers corren a fps completo | Costo de anotación; CLEAR/Identity/HOTA emparejan por frame |
| D10 | H de referencia | SIFT a 1920 px, cajas enmascaradas, USAC_MAGSAC 1 px, ida-vuelta ≤ 1 px, ≥ 40 inliers | Independiente de `comun.Estabilizador` (LK+RANSAC a 960), para no heredar sus errores |
| D11 | Bins de ego-movimiento | `ego_px` (rejilla 3×3, px a 960) con mediana centrada de 0.5 s: < 0.5 estacionario, < 3 suave, ≥ 3 rápido | Mismos umbrales que `tipo_toma` de la v13, pero por frame |
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

## Abiertas (decidir antes de anotar / reportar)

| # | Pregunta | Opciones |
|---|---|---|
| A1 | ¿Qué clips/tramos anotar? | Propuesta del informe: vigia_4 (rápido), tramo de vigia_1 (suave), tramo de vigia_9 o 10 (oblicuo), vigia_5 (estacionario) |
| A2 | ¿Ajustar hiperparámetros? | (a) solo defaults; (b) mismo presupuesto (p. ej. 100 pruebas Optuna) para los 4 en VisDrone/UAVDT `val` o en clips VIGIA reservados que no se reportan |
| A3 | ¿Agregar VisDrone-MOT / UAVDT? | Necesitan un conversor a este formato de GT (clases 0/11 → ignoradas) y un detector entrenado en VisDrone |
| A4 | Incertidumbre con pocos clips | Bootstrap por bloques temporales (5–10 s) dentro de cada clip (pendiente de implementar) |
| A5 | Tamaño de objeto | Estratificar por área de caja (<16², 16–32², 32–64², >64² px) — pendiente |
| A6 | Baselines extra | OC-SORT / BoostTrack de BoxMOT o Roboflow `trackers`, etiquetados como baselines y con la misma política de salida |
| A7 | hfov por dron | Hoy 82° por defecto en `CamaraUCMC`, probablemente el FOV **diagonal** de la ficha DJI; el horizontal en 16:9 sería ~70–74°. El barrido usa 74° (D17.1) y desde 2026-11-23 `secuencias.yaml` también (`ucmc.hfov_deg: 74`), para que `ucmc` y `ucmc_grupo_train` solo difieran en la cámara elegida; falta decidir si se corrige el default del `.py` |
| A8 | fps real de VIGIA | Se toma el del archivo; confirmar que no hay frames duplicados/variables |
