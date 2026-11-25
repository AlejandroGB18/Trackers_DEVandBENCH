# Plan del benchmark v1 (UAVDT, 1 semana)

Plan acordado en la sesión de *grilling* del 2026-11-23. Reemplaza el esbozo de [`diseno-benchmark.md`](diseno-benchmark.md) como plan de ejecución. Ese documento se conserva como antecedente y lista de limitaciones.

- **Vocabulario:** [`GLOSSARY.md`](../GLOSSARY.md).
- **Decisiones congeladas:** [`benchmark/DECISIONS.md`](../benchmark/DECISIONS.md) (D18–D31).
- **Decisiones con alternativas descartadas:** [`docs/adr/`](adr/).
- **Datos de UAVDT:** [`investigacion-uavdt.md`](investigacion-uavdt.md).

## 1. Objetivo

Comparar 4 trackers de vehículos para dron en una base pública común y reproducible, con dos preguntas principales:

| | Pregunta | Métrica principal |
|---|---|---|
| **P1** | ¿Cuánto se degrada la identidad de cada tracker al subir el ego-movimiento? | ΔAssA = AssA(alto) − AssA(bajo) por tramo de ego, más IDSW por cada 1000 detecciones del GT |
| **P2** | ¿El decisor `en_movimiento` distingue el movimiento real del aparente? | Precisión, recall y F1 de la decisión de movimiento contra el movimiento real, más latencias de encendido y apagado |

**Análisis secundarios** (descriptivos, sin estadística fuerte):
- valor de conocer la cámara en UCMC (automático < `grupo_train` < cota);
- costo en ms por frame (relativo);
- resultados por grupo de vuelo y por iluminación.

**Fuera de la v1:**
- otras fuentes de GT (VisDrone, DynUAV, SynDrone, vuelos propios);
- comparación de detectores y ajuste de hiperparámetros con el mismo presupuesto para todos;
- `ucmc_singt`;
- ego-movimiento sintético.

## 2. Alcance congelado

| Tema | Decisión | Ref. |
|---|---|---|
| GT | Solo **UAVDT-MOT**: 30 secuencias de ajuste (train oficial) y 20 de test | D18, [ADR 0001](adr/0001-uavdt-unica-fuente-de-gt.md) |
| Frames | Todos (UAVDT anota cada frame, 30 fps) | D19 |
| Cajas del GT | Todas las de vehículo (car, truck y bus fusionadas). Solo se descartan predicciones dentro de las regiones ignoradas (≥ 50 % del área); sin filtrar por oclusión ni por fuera de vista | D7, D8, D19 |
| Detector | **Un solo YOLOv8x (`yolo8x_best.pt`)**, entrenado en un subconjunto curado de VisDrone (~1700 imágenes, solo vehículos), sin reentrenar. Detecciones generadas una vez, en el laboratorio, con umbral 0.05 | D20, [ADR 0002](adr/0002-detector-visdrone-sin-reentrenar.md) |
| Umbrales del detector | `conf_high` en el punto de mejor F1 del detector y `conf_low` donde su precisión cae al ~50 %, medidos en ajuste; iguales para los 4 trackers | D21 |
| Trackers | Defaults (D4, D16); solo la cámara de UCMC se elige, en ajuste (D17) | D22 |
| Ranking | Una entrada por tracker: **propio_kf, ByteTrack, BoT-SORT y `ucmc_grupo_train`** | D23 |
| Referencia y cota | `ucmc` automático (referencia) y `ucmc_oraculo_seq` (cota), fuera del ranking | D23 |
| Grupos de vuelo | cenital, oblicua_baja y oblicua_alta (§3) | D24 |
| Exclusión | Estrato (grupo de vuelo o iluminación) con DetA < 20 en ajuste: sale del ranking completo, decidido antes de test | D25 |
| Tramos de ego | Percentiles 33 y 67 de `ego_px` en ajuste dan bajo, medio y alto. Si el alto no cumple el mínimo de datos, dos tramos cortando en la mediana | D26 |
| Movimiento real | Etiqueta automática (D12), más revisión humana por track en test: dudosos, cambios de estado y una muestra del 10 % de los seguros. Umbrales ajustables solo con la revisión y antes de ver los trackers | D27 |
| Estadística | Unidad = secuencia; bootstrap pareado con IC 95 %; "gana" solo si el IC excluye 0; mínimo de datos por tramo: ≥ 2000 detecciones del GT y ≥ 5 secuencias | D28 |
| Ejecución | Desarrollo y prueba con una muestra aquí; ejecución completa en el laboratorio (Linux, conda), por etapas, congelando entre ajuste y test | D29 |
| Arquitectura | v1 enfocada: adaptador de UAVDT y lectura de detecciones externas como módulos separados; el núcleo no se toca | D30 |
| Entregable | `docs/resultados-v1.md` con figuras PNG reproducibles desde `eval/` | D31 |

## 3. Datos: UAVDT por grupo de vuelo

Asignación desde `M_attr` (vista cenital → cenital; frontal o lateral con altitud baja → oblicua_baja; frontal o lateral con altitud media o alta → oblicua_alta):

| Grupo | Rejilla de cámara de UCMC | Ajuste | Test |
|---|---|---|---|
| **cenital** | pitch 0–25°, altura 15–100 m, punto = centro | M0210, M0603, M0702, M0703, M0901, M1008, M1102 (7) | M0203, M0701, M0801, M1009 (4) |
| **oblicua_baja** | pitch 25–70°, altura 10–30 m, punto = base | M0202, M0204, M0604, M0605, M1005, M1006, M1202, M1304, M1306 (9) | M0205, M0209, M0802, M1101, M1303, M1401 (6) |
| **oblicua_alta** | pitch 25–70°, altura 30–100 m, punto = base | M0101, M0201, M0206, M0207, M0301, M0401, M0402, M0501, M0704, M0902, M1002, M1003, M1201, M1305 (14) | M0208, M0403, M0601, M0602, M0606, M1001, M1004, M1007, M1301, M1302 (10) |

- **Iluminación:** ajuste = 17 de día, 8 de noche y 5 con niebla; test = 12 de día, 5 de noche y 3 con niebla.
- **hfov:** se fija con la ficha del DJI Inspire 2 y la resolución real, que se mide al descargar (probablemente 1024×540, no 1080×540).
- **Archivos:**
  - `M_attr.zip` (9.5 KB): ya descargado;
  - `UAV-benchmark-MOTD_v1.0.zip` (234 MB, GT y toolkit);
  - `UAV-benchmark-M.zip` (6.3 GB, frames).

  Todos vienen del Drive enlazado en la página oficial y son solo para investigación, con cita.

## 4. Flujo por etapas

Los comandos de `bench.py` se corren en el laboratorio. Hay dos puntos de **congelado**, y test se corre una sola vez.

```text
datos_raiz/UAVDT  +  datos_raiz/detecciones/yolov8_visdrone
        │
  ── AJUSTE (30 secuencias) ─────────────────────────────────────────────
  detectar   (lab, GPU)   YOLOv8 → det/<seq>.txt para las 50, una sola vez
  ego                     H de referencia → cache/ego/<seq>.csv
  det-eval                DetA del detector por estrato · curva conf → conf_high/conf_low
  barrer                  rejilla pitch × altura por grupo → barrido/seleccion.csv
        │
  ═══ CONGELADO 1 ══ detector · conf · exclusiones · cortes de tramo · cámaras → DECISIONS.md
        │
  ── TEST (20 secuencias) ───────────────────────────────────────────────
  moving     automático → página de revisión → moving.csv revisado
        │
  ═══ CONGELADO 2 ══ umbrales de moving (calibrados con la revisión, sin ver trackers)
        │
  correr                  4 trackers + referencia + cota (una sola vez)
  evaluar                 métricas, por tramo, decisor, latencias, comparaciones
  reporte                 figuras PNG + docs/resultados-v1.md
```

## 5. Trabajo de código (día 1, aquí)

| # | Pieza | Qué hace |
|---|---|---|
| C1 | `adaptadores/uavdt.py` | Lee `gt_whole.txt` (clases 1–3 → `vehicle`), `gt_ignore.txt` (→ regiones ignoradas) y `M_attr` (→ grupo de vuelo, iluminación y split), y genera las entradas de `secuencias.yaml` |
| C2 | Lectura de carpetas de frames | `leer_frames` acepta `img%06d.jpg` además de video (cierra I8) |
| C3 | Detecciones externas | `CacheDetecciones` lee un `.txt` MOT por secuencia (`frame, x, y, w, h, conf, clase`) con la firma del modelo en un `.json` al lado |
| C4 | `scripts/detectar_lab.py` | Para el laboratorio: carpeta de frames y pesos de Ultralytics → `.txt` por secuencia, con umbral 0.05 y firma |
| C5 | Rutas portables | `datos_raiz` en el manifiesto o en la variable de entorno `BENCH_DATOS`; sin rutas absolutas. Fuera VIGIA de `secuencias.yaml` y del README |
| C6 | `bench.py det-eval` | DetA, precisión y recall del detector por estrato en ajuste, y la curva de confianza → propuesta de `conf_high`/`conf_low` |
| C7 | Tramos relativos | `bins_ego` con cortes por percentil calculados en ajuste (D26) y la regla de mínimo de datos |
| C8 | Página de revisión de `moving` | HTML por track: trayectoria estabilizada, miniaturas y etiqueta propuesta; teclas para confirmar o corregir, exportación a CSV; tabla de cuántos tracks cambian con cada umbral |
| C9 | `requirements.txt` y `environment.yml` | Versiones fijas (Ultralytics 8.4.x, trackeval 1.3.0, numpy 2.x, opencv) |
| C10 | `bench.py reporte` | Figuras (AssA por tramo con IC, F1 del decisor, valor de la cámara) y tablas en Markdown desde `eval/` |
| C11 | Pruebas | Las actuales, más el adaptador de UAVDT sobre una muestra real y la lectura de detecciones externas; todo debe terminar en `TODO OK` |

Prueba de punta a punta aquí con el GT y 3 secuencias (2 de ajuste y 1 de test) antes de pasar al laboratorio.

## 6. Calendario

| Día | Aquí (Claude) | Laboratorio (tú) | Sale |
|---|---|---|---|
| 1 | C1–C5, C9 y C11; prueba de punta a punta con la muestra | Descargar UAVDT al laboratorio; crear el entorno conda | PR del código |
| 2 | C6–C8 y C10 | `git clone`, `pruebas_benchmark.py` → `TODO OK`; `detectar` (50 secuencias), `ego`, `det-eval` y `barrer` sobre ajuste | CSV de ajuste |
| 3 | Análisis de ajuste → **congelado 1** en `DECISIONS.md` | `moving` sobre test; empezar la revisión (~6–8 h, días 3–4) | `DECISIONS.md` congelado |
| 4 | Calibrar los umbrales de `moving` con tu revisión → **congelado 2** | Terminar la revisión; correr `correr` y `evaluar` sobre test **una vez** | `eval/` de test |
| 5 | `reporte`: ranking, P1, P2, referencias y limitaciones | Leer y decidir qué va a la tesis | `docs/resultados-v1.md` |

## 7. Recursos

- **Personas:** una (tú), ~15 h en la semana, repartidas entre descarga y entorno (~3 h), revisión de `moving` (~6–8 h) y lectura y decisiones (~4 h).
- **Cómputo:**
  - laboratorio (Linux, conda, GPU) para todo;
  - esta Mac (M4, sin aceleración en PyTorch) solo para el desarrollo y la muestra.
- **Datos:** ~6.6 GB de UAVDT, más las detecciones (texto, pocos cientos de MB).

## 8. Riesgos y respuesta

| Riesgo | Señal | Respuesta |
|---|---|---|
| El entorno del laboratorio no reproduce los resultados | `pruebas_benchmark.py` no da `TODO OK` | Día 2 por la mañana; corregir antes de correr nada |
| UAVDT tiene poco ego-movimiento | El tramo alto no cumple el mínimo de datos | Dos tramos (bajo contra alto); P1 se reporta como relativa al ego de UAVDT (D26) |
| El detector de VisDrone falla de noche o con niebla | DetA < 20 en ajuste para ese estrato | Exclusión del estrato (D25), reportado aparte |
| La revisión de `moving` no cabe en el tiempo | Más de ~1500 tracks para revisar | Revisar dudosos y cambios completos y reducir la muestra de seguros; reportar el tamaño |
| La resolución real difiere de la del artículo | La medición al descargar | Ficha de cámara (hfov y aspecto) con la resolución medida |

## 9. Después de la v1

- **v2, detector × tracker:** `yolo11x_best.pt` y RT-DETR del laboratorio, con las mismas piezas (D20).
- **Segunda fuente de GT:** VisDrone-MOT, y DynUAV si llega el acceso.
- **Más trackers:** OC-SORT o BoostTrack como baselines extra (A6).
- **Más análisis:** ajuste con el mismo presupuesto para todos (A2) y bootstrap por bloques temporales (A4).

## 10. Pendiente de ti antes del día 2

- La ruta de `yolo8x_best.pt` en el laboratorio (decidido: YOLOv8x; en la Mac, `yolo8n_best.pt` para la prueba).
- La **descarga de UAVDT** al laboratorio. Aquí descargo el GT y 3 secuencias para la prueba.
