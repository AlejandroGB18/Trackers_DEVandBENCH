# Investigación: "fuerza bruta" de los parámetros de cámara de UCMCTrack para el benchmark

> **Fecha:** 2026-11-21 · **Pregunta:** cómo barrer (pitch, altura, hfov…) de UCMCTrack en UAVDT, VisDrone2019-MOT y DynUAV, que no traen telemetría, para compararlo de forma justa con el propio, ByteTrack y BoT-SORT.
>
> **Contexto que no se repite aquí:** [`../VD - Trackers To Real Implementation/tracker_ucmc.py`](../VD%20-%20Trackers%20To%20Real%20Implementation/tracker_ucmc.py) (nuestro `Mapa` con K(hfov), pitch y altura; calibración en línea; `ucmc_calibrar=False` = manual), [`../benchmark/DECISIONS.md`](../benchmark/DECISIONS.md) (D1–D16, A2, A7), [`investigacion-gt-existente.md`](investigacion-gt-existente.md) e [`investigacion-gt-caso-real.md`](investigacion-gt-caso-real.md) (fichas de UAVDT, VisDrone y DynUAV).
>
> **Convención:** **[V]** = verificado en la fuente primaria citada (paper/arXiv, código con commit, ficha oficial) el 2026-11-21 · **NO VERIFICADO** = no se pudo comprobar · **[Derivado]** = cálculo propio a partir de cifras verificadas (el script está descrito en §2.4) · **[Propuesta]** = recomendación propia. No se descargó ningún dataset. Los repos se clonaron con `--depth 1` solo para leerlos.

---

## 0. Respuesta corta

1. **Los autores de UCMCTrack no tenían la cámara en ningún dataset salvo KITTI.** Ajustaron los parámetros **a mano**: una herramienta con sliders superpone una rejilla de suelo sobre **una sola imagen** de cada secuencia. Lo hicieron **por secuencia, también en las de test**. Es un criterio **visual, sin GT** [V]. El repo no dice si después retocaron la cámara mirando las métricas (NO VERIFICADO). Lo que sí está en el repo son **hiperparámetros distintos para cada secuencia de test** (wx, wy, a, vmax, umbral de confianza) [V], igual que en ByteTrack y BoT-SORT [V]. El paper solo trae una figura de sensibilidad: el error en guiñada (eje Y) importa poco y los errores en X y Z, mucho. No da números [V].
2. **Con nuestra parametrización, en la práctica hay 2 grados de libertad, no 3** [Derivado]:
   - **La altura es solo una escala global del suelo.** Equivale **exactamente** a reescalar los hiperparámetros métricos del Kalman y de la asociación (wx, wy, vmax, P0 y el umbral `a`). Barrer la altura es, de hecho, **ajustar los ruidos del Kalman**, y D16 lo prohíbe con datos de evaluación.
   - **En cenital, altura y hfov solo entran como h/f.** Son indistinguibles.
   - **En oblicua, un error de hfov se compensa casi del todo con el pitch.** La deformación residual baja de ×1.69 a ×1.10 con 10° de error de hfov.
   - Conclusión: hfov se **fija** con la ficha técnica, el **pitch** se barre y la altura se trata como **escala** con muy pocos valores (o se deja automática).
3. **Rangos verificables:**
   - **UAVDT:** altitud baja 10–30 m, media 30–70 m y alta >70 m; vista frontal, lateral o cenital. Las vistas frontal y lateral pueden convivir en una secuencia [V]. Los atributos están en `M_attr/{train,test}/Mxxxx_attr.txt`: una línea de 10 banderas 0/1 (según un loader de terceros, [V] en su código). Dron: DJI Inspire 2 [V]. La cámara no se declara (NO VERIFICADO).
   - **VisDrone-MOT:** **no** trae altitud ni vista; solo dice "varios DJI" [V].
   - **DynUAV:** DJI Mini 4 Pro a 80–120 m [V]. La ficha da **FOV 82.1°**, 24 mm equivalentes y zoom digital **1–4× en FHD** [V]. Casi seguro el 82.1° es **diagonal**: el hfov real en 16:9 estaría entre **~70° y ~74°** [Derivado; NO VERIFICADO cuál]. Nuestro valor por defecto (82°) probablemente sobra ~8–12°.
4. **Granularidad recomendada:** número principal **por grupo de atributos, elegido en train**. El **oráculo por secuencia en test** se reporta aparte, solo como **cota superior etiquetada**. En DynUAV, el zoom digital (hfov efectivo de ~70° a ~20°) hace que **ningún juego fijo por secuencia** sea correcto.
5. **Justicia:** usar el GT de test para elegir es lo que MOTChallenge prohíbe explícitamente [V]. Dar más búsqueda a un tracker sesga la comparación: en MOT, una HPO sistemática supera a los valores publicados por hasta 4.38 y 16.05 HOTA según el optimizador [V] ([arXiv 2609.12261][mfgcs]). Como barrer la altura equivale a ajustar ruidos, **o se acota la altura con física (banda de UAVDT o tamaño de vehículos), o los otros 3 reciben el mismo presupuesto de búsqueda en train**.
6. **Protocolo propuesto (§6):**
   - 4 configuraciones de UCMC en las tablas: **auto** (sin GT), **manual-elegido-en-train por grupo**, **manual-sin-GT** (criterio de consistencia métrica) y **oráculo por secuencia** (cota, fuera del ranking).
   - Detecciones **y H** cacheadas, para no reestabilizar en cada prueba.
   - Rejilla de ~25–60 puntos por secuencia, con refinamiento coarse-to-fine.

---

## 1. Cómo lo hicieron los autores de UCMCTrack

Repo oficial `corfyi/UCMCTrack`, commit **`7851a49078a6666725d1bda670f0046fcc0d715f`** (2024-03-26; es el mismo commit del que se adaptó nuestro `NucleoUCMC`). Paper: AAAI 2024, [arXiv 2312.08952][ucmc].

### 1.1 Qué parámetros, en qué formato [V]
- **Un archivo por secuencia** en `cam_para/{MOT17,MOT20,DanceTrack}/` (MOT17: 14 secuencias × 3 detectores, con contenido idéntico entre detectores; MOT20: 8; DanceTrack: 100). Cada archivo trae `RotationMatrices` (R 3×3), `TranslationVectors` (en **mm**) e `IntrinsicMatrix` (fx = fy = foco en px; centro óptico) [V] (`README.md` L127–L136; `detector/mapper.py` L49–L78, que divide T entre 1000).
- Los ficheros incluyen **secuencias de test**: MOT17-01, -03, -06, -07, -08, -12 y -14; MOT20-04 a -08. Algunos pares train/test con la misma cámara comparten archivo idéntico (MOT17-05/06, -11/12, -13/14) [V] (comparación directa de los archivos). Los demás de test tienen valores propios.
- Valores típicos de MOT17: foco de 663 a 2400 px, altura (T_z) de 1.2 a 6.9 m, inclinación pequeña [V] (lectura de los archivos).

### 1.2 Cómo se obtienen: manual e interactivo, sobre una imagen [V]
- `util/estimate_cam_para.py` (L120–L183) carga una imagen y un `cam_para` inicial, y abre **5 sliders**:
  - `theta_x` y `theta_y` en ±25° (paso 0.1°);
  - `theta_z` en ±100°;
  - `focal`, un incremento de −500 a +2000 px;
  - `Tz`, de −1.2 a +18.8 m.

  Las conversiones están en L57–L67 y los sliders en L131–L135.
- Las rotaciones se **componen** sobre la R inicial (L141–L153). La herramienta dibuja una rejilla de puntos del suelo de 10 m × 10 m cada 0.5 m (L158–L161) y el usuario **alinea la rejilla a ojo** con el suelo de la imagen. Al pulsar `q` se guarda (L170–L183).
- El README (L99–L123) indica empezar con el centro óptico en la mitad de la imagen y foco 1000, y ajustar hasta "align a virtual ground plane grid with the ground in the image". Añade que la estimación "might not be extremely precise" pero basta para UCMCTrack [V]. Nota: el README habla de `t_x`, pero el código ajusta **T_z** (L152) [V].
- El paper: "For MOT17, MOT20, and DanceTrack datasets, we manually estimated the camera parameters since they are not publicly accessible"; KITTI sí trae la calibración [V] ([arXiv 2312.08952][ucmc], §Implementation Details).
- **¿Ajustaron la cámara mirando el resultado?** Ni el paper ni el repo describen ningún bucle con métricas. La herramienta solo usa la imagen. **NO VERIFICADO** si hubo retoques posteriores.

### 1.3 Lo que sí está ajustado por secuencia (incluido test) [V]
- `run_mot17_test.bat` (L1–L7) y `run_mot20_test.bat` (L1–L4) corren **cada secuencia de test con wx, wy, a, cdt, conf_thresh, vmax y `--cmc` distintos**. Ejemplos: MOT17-06 usa `--wy 5.00 --a 19 --conf_thresh 0.40 --vmax 1.0`; MOT17-03 usa `--wx 0.45 --wy 0.55 --a 12 --conf_thresh 0.26` [V]. Cómo se eligieron: **NO VERIFICADO**.
- El paper lo justifica en la ablación del factor de compensación: el efecto es distinto en escenas dinámicas y estáticas, lo que "underscores the necessity of tailoring the compensation parameters separately for each scene type" [V] (§Ablation, Influence of Process Compensation Factor, Fig. 4a).
- No son los únicos. ByteTrack cambia `track_thresh` en MOT17-01, -06, -12 y -14 y en MOT20-06/-08 (`yolox/evaluators/mot_evaluator.py` L139–L155, commit `d1bf019`) [V]. BoT-SORT hace lo mismo con `track_high_thresh` y `track_buffer` (`tools/track.py` L336–L359, commit `2519854`) [V]. Es una práctica extendida, y conviene **no** copiarla.
- La demo de vehículos (`demo.py` L141–L144) usa wx = wy = 5, vmax = 10 y a = 100: son los valores que tomó nuestra `ConfigUCMC` [V].

### 1.4 Datasets sin calibración y sensibilidad según el paper [V]
- No se estima nada en línea. Hay **una cámara fija por video**: "UCMCTrack consistently applies the same compensation parameters throughout a video sequence" [V] ([arXiv 2312.08952][ucmc], abstract). El movimiento de cámara lo absorben la CMC (ECC, igual que StrongSORT) y el ruido de proceso.
- **Robustez a errores de cámara** (§Ablation, Fig. 4c): ablaciones separadas de error en los extrínsecos sobre los ejes X, Y y Z. El eje horizontal de la figura es "Error degree" y se grafican HOTA e IDF1 [V]. Texto:
  - el error en **Y (guiñada)** tiene impacto menor;
  - los errores en **X y Z** tienen efecto mayor, porque deforman el plano de suelo estimado;
  - con errores grandes el rendimiento "notably degrades" [V].

  Rango exacto y valores: **NO VERIFICADO** (no hay tabla y la figura no se pudo leer con precisión).
- Hay además una opción `--add_cam_noise` que alterna ±0.5° de rotación sobre z en cada frame (`detector/detector.py` L72–L82; `detector/mapper.py` L139–L157) [V]. No se reportan resultados con ella.
- La limitación declarada es el supuesto de un **único plano de suelo** [V] (Conclusion).

### 1.5 Forks
`mint-lab/MINTtrack` (commit `5abdbdd`) añade configuraciones de cámara con distorsión por secuencia (`detector/config_mot17_*.json`) [V]. No encontré en él un estimador automático sin GT (NO VERIFICADO en profundidad).

---

## 2. Qué barrer y en qué rangos

### 2.1 Nuestra parametrización (recordatorio)
`Mapa(K(hfov), pitch, altura)`: pitch 0° = cenital y 90° = horizonte en el centro. Roll, yaw y traslación lateral son 0. f = (W/2)/tan(hfov/2), con el centro óptico en el centro de la imagen y píxeles cuadrados. En **manual** (`ucmc_calibrar=False`):
- el pitch es `pitch_respaldo_deg`;
- la altura es `altura_m`, o `ucmc_altura_defecto_m` = 100 **en silencio** si `altura_m` es `None`;
- el punto de apoyo con `ucmc_punto="auto"` es el **centro si pitch_respaldo < 30°** y la base en caso contrario. Es una discontinuidad en mitad del barrido (§6.3).

### 2.2 Sensibilidad: fórmulas [Derivado]
Con x = (u−c_x)/f, β = atan((v−c_y)/f) y ψ = θ − β (ángulo del rayo respecto al nadir):

- Y = h·tan ψ  y  X = h·x·cos β / cos ψ
- Escala local longitudinal: ∂Y/∂v = (h/f)·cos²β / cos²ψ. Escala lateral (en u = c_x): ∂X/∂u = (h/f)·cos β / cos ψ.

Errores:
- **Altura:** δh/h escala **todo el plano por igual**. No deforma nada.
- **Pitch:** δ ln(∂Y/∂v) = 2·tan ψ·δθ y δ ln(∂X/∂u) = tan ψ·δθ. El error crece hacia el horizonte. Con ψ = 60° y δθ = 5°: +30 % en longitudinal y +15 % en lateral. Con ψ = 20°: +6 %.
- **hfov:** δ ln f = −δhfov / sin(hfov). Con hfov = 74° y δhfov = 10°: ~18 %. En cenital es una escala pura (h/f).
- **Horizonte:** si θ + vfov/2 ≥ 90°, las filas de arriba quedan por encima del horizonte y `uv2xy` las descarta (`valid`, `n_fuera`). **Sobrestimar el pitch es más peligroso que subestimarlo.** Con hfov 74° en 16:9, vfov = 46.2°; con pitch real de 65°, el rayo superior ya está a ~88°.

Lo que **perjudica al tracker** no es la escala global (se compensa con los umbrales, §2.3) sino la **no uniformidad**. Un auto a velocidad constante "acelera" en el suelo estimado al cruzar la imagen, y el modelo de velocidad constante del Kalman lo paga.

### 2.3 Sensibilidad: números [Derivado]
1920×1080, hfov real 74°, h = 100 m. Rejilla de 25×15 píxeles. "Escala" = mediana del cociente de escalas locales estimado/real (lo absorbible). "No unif." = máx/mín de ese cociente en la imagen (lo **no** absorbible). "Perdidas" = fracción de la rejilla que pasa por encima del horizonte.

| Pitch real | Perturbación | Escala | No unif. | Perdidas |
|---|---|---|---|---|
| 0° | pitch +5° / +10° | 1.006 / 1.022 | 1.15 / 1.32 | 0 |
| 0° | altura ×1.2 | 1.200 | **1.000** | 0 |
| 0° | hfov −10° / +10° | 0.83 / 1.20 | **1.000** | 0 |
| 30° | pitch +5° / −5° / +10° | 1.08 / 0.94 / 1.19 | 1.27 / 1.23 / 1.67 | 0 |
| 30° | hfov −10° / +10° | 0.83 / 1.20 | 1.19 / 1.23 | 0 |
| 50° | pitch +5° / −5° / +10° | 1.18 / 0.87 / 1.45 | 1.75 / 1.52 / **3.98** | 0 |
| 50° | hfov −10° / +10° | 0.83 / 1.20 | 1.52 / 1.69 | 0 |
| 65° | pitch +5° / −5° / +10° | 1.35 / 0.78 / 1.79 | 13.4 / 4.7 / 19.0 | 0.07 / 0 / **0.20** |

- Por fila, con pitch real 50° y error de +5°, el error de escala longitudinal (= error de velocidad aparente) va de **+69 %** arriba (v = 100) a **+12 %** abajo (v = 1000).
- **hfov frente a pitch** (h libre como escala). Con pitch real 30° y hfov usado de 64° u 84°, la no uniformidad baja de 1.19/1.23 a **1.06/1.04** si se reajusta el pitch a 34.75°/25.75°. Con pitch real 50°, baja de 1.52/1.69 a **1.13/1.10** con un pitch de 55°/45°.

Script: `calc/sens.py` en el scratchpad de la sesión. Reimplementa las ecuaciones de `Mapa`; no importa el código del repo.

### 2.4 Redundancias [Derivado]
1. **Altura ≡ escala ≡ hiperparámetros métricos.** Multiplicar h por s multiplica todas las posiciones y R = C·Σ_uv·Cᵀ por s y s². Es equivalente, exactamente, a dejar h y usar:
   - wx, wy → wx/s², wy/s²;
   - vmax → vmax/s;
   - P0 (posición, 1 m²) → 1/s²;
   - `ucmc_a` → a − 4·ln s, porque MMD = d² + ln|S| y |s²S| = s⁴|S|.

   Por tanto **barrer la altura es barrer los ruidos del Kalman y el umbral de asignación de UCMC**. Choca con D16 si se elige con el GT de evaluación (§4). En automático pasa lo mismo con `ucmc_largo_vehiculo_m`.
2. **Cenital: h y hfov solo entran como h/f.** El pitch casi solo traslada el plano: la no uniformidad es 1.15 con 5° de error.
3. **Oblicua: hfov y pitch son casi colineales.** Hay una familia (f, θ) que deja el horizonte (v_h − c_y = −f·cot θ) en el mismo sitio, y la deformación residual es pequeña (§2.3). En la práctica, **2 grados de libertad**: pitch y escala.
4. **Punto de apoyo:** base o centro cambia la v proyectada en h_caja/2. En oblicua eso es un sesgo de profundidad que también se mezcla con el pitch.

**Consecuencia [Propuesta]:** barrer **pitch** (fino) × **escala** (gruesa, 3–5 valores en escala logarítmica). El **hfov se fija** a la ficha y se hace solo un análisis de sensibilidad con ±1 valor.

### 2.5 Rangos por dataset

**UAVDT** [V] ([arXiv 1804.00518][uavdt], §2; [página oficial][uavdt-site])
- 1080×540 a 30 fps. Dron **DJI Inspire 2** (nota al pie del paper). La cámara montada **no se declara** (NO VERIFICADO).
- Si fuera la Zenmuse X4S (ficha: 8.8 mm, 24 mm eq., **FOV 84°** [V] [DJI X4S][x4s]), el hfov en 16:9 sería ~**74–76°** [Derivado]: 84° coincide con el FOV **diagonal** de 24 mm en 35 mm, 2·atan(21.63/24) = 84.06°.
- **1080×540 es 2:1, no 16:9.** No se sabe si es un recorte vertical (el hfov se conserva) o un reescalado anamórfico (píxeles no cuadrados, fx ≠ fy). **NO VERIFICADO.** Se puede comprobar sin GT comparando el cociente largo/ancho de autos horizontales y verticales en secuencias cenitales [Propuesta].
- Atributos de secuencia: **altitud** baja (10–30 m), media (30–70 m) y alta (>70 m, sin cota superior declarada). **Vista**: frontal ("along with the road"), lateral y cenital ("bird-view", "on the top of objects"). "the first two views may coexist in one sequence" [V]. La página oficial añade que la vista puede cambiar dentro de la secuencia [V].
- **Formato:** carpeta `M_attr/{train,test}/M0101_attr.txt`, **una línea CSV con 10 banderas 0/1** en el orden daylight, night, fog, low-alt, medium-alt, high-alt, front-view, side-view, bird-view, long-term. Así lo lee el loader de terceros `tensorbay` (`tensorbay/opendataset/UAVDT/loader.py` L47–L117 y `catalog.json`, commit `1574902`) [V en ese código]. En el toolkit oficial: **NO VERIFICADO** (no se descargó).
- Split MOT: 30 train / 20 test [V] ([arXiv 1804.00518][uavdt], §2.2).

Rangos de barrido [Propuesta]:

| Grupo UAVDT | Pitch (°) | Altura central / escala |
|---|---|---|
| bird-view | 0–25 (paso 5; **punto = centro**) | low 20 m, med 50 m, high 100 m; ×{0.6, 1, 1.6} |
| front/side-view | 25–70 (paso 5 → refinamiento de 1; **punto = base**) | igual |
| hfov | fijo en 74° (sensibilidad: 66° y 82°) | — |

**VisDrone2019-MOT** [V] ([arXiv 2001.06303][visdrone], §3; [README][visdrone-repo] commit `4364e82`)
- "various drone platforms, i.e., DJI Mavic, Phantom series (3, 3A, 3SE, 3P, 4, 4A, 4P)". Resolución máxima de video 3840×2160.
- Los atributos publicados son **visibilidad de escena, clase y oclusión**. **No hay altitud, vista ni modelo de dron por secuencia.**
- NDFT anotó a mano altitud, vista y clima sobre las **imágenes DET** de VisDrone2018 [V] ([arXiv 1908.03856][ndft], §4.2), no sobre MOT. No encontré esas anotaciones publicadas en su repo (NO VERIFICADO).
- Rango [Propuesta]: pitch de 0 a 70°, escala ×{0.5, 1, 2} sobre 50 m, hfov fijo en ~74° (ficha típica de Phantom/Mavic; **NO VERIFICADO** por secuencia). El grupo (cenital u oblicua) **hay que etiquetarlo a mano**, mirando un frame por secuencia y sin GT.

**DynUAV** [V] ([arXiv 2603.05970][dynuav], §3)
- **DJI Mini 4 Pro**, sensor 1/1.3", **1080p**, 80–120 m. Hay hover, crucero, velocidad variable, **rotación, zoom, órbitas** y acercamiento/alejamiento. Split 30/5/7.
- Ficha DJI [V] ([Mini 4 Pro specs][mini4]):
  - **FOV 82.1°**, 24 mm eq., f/1.7;
  - FHD 1920×1080 a 24–60 fps (100/200 fps en cámara lenta);
  - **zoom digital FHD 1–4×** (4K 1–3×);
  - tilt controlable del gimbal de −90° a 60°.
- La ficha **no dice** si 82.1° es diagonal ni si el video recorta el sensor (NO VERIFICADO). Por la convención de DJI (X4S: 84° = diagonal de 24 mm) es muy probablemente **diagonal**. De ahí [Derivado]:
  - hfov **69.7°** si la diagonal es la del sensor 4:3 y el 16:9 conserva el ancho;
  - **74.4°** si la diagonal es la del cuadro 16:9;
  - 82.1° solo si fuera horizontal.
- **Zoom digital:** hfov efectivo = 2·atan(tan(hfov/2)/z). A 2× da ~38–42° y a 4× ~20–21° [Derivado].
- Rango [Propuesta]: altura central 100 m con escala ×{0.8, 1, 1.25} (la banda 80–120 m está verificada). Pitch de 0 a 60° (el paper no da la inclinación; NO VERIFICADO). hfov fijo en 70° (sensibilidad: 74° y 82°).

**Corrección pendiente en nuestro código:** `CamaraUCMC.hfov_deg = 82` por defecto (comentario "DJI típicos: 73-84°") probablemente toma el FOV **diagonal** de la ficha como horizontal. En DJI de 24 mm eq., el hfov en 16:9 es ~70–74° [Derivado]. Afecta a A7 de DECISIONS y al pitch que estima el modo automático (en vigia_8: 52° con hfov 60 y 63° con 82, según el docstring del archivo).

---

## 3. Granularidad

| Opción | Pros | Contras |
|---|---|---|
| **Por secuencia** | Lo que hicieron los autores (§1.1); se ajusta a cada vuelo | Con GT de test es un oráculo. El máximo de una rejilla ruidosa está sesgado hacia arriba (más en secuencias cortas o con pocos objetos). No es desplegable |
| **Por grupo de atributos** (UAVDT: altitud×vista = 3×3, en la práctica ~4–6 grupos poblados) | Elegible en **train** y aplicable a test sin leakage. Imita lo que se sabría en operación ("vuelo alto, cámara cenital") | Los atributos son bandas anchas (30–70 m) y la vista cambia dentro de la secuencia [V]. Puede haber grupos vacíos en train |
| **Global por dataset** | La más honesta y simple | Mezcla cenital con oblicua: un pitch único es absurdo. Penaliza a UCMC más de lo realista |

**[Propuesta]**
- Número principal: **por grupo, elegido en train**. VisDrone y DynUAV no traen atributos: grupos "cenital u oblicua" etiquetados a mano sin GT, y la altura de DynUAV por banda.
- El oráculo por secuencia se reporta **solo como cota**.
- Variante intermedia para reducir el optimismo: **oráculo cruzado temporal**. En cada secuencia de test se elige en la primera mitad y se evalúa en la segunda, y viceversa. Sigue usando GT de test, así que se etiqueta igualmente.

**Cámara que cambia dentro de la secuencia (DynUAV)**
- **Zoom:** con zoom digital de 1–4×, un hfov fijo es erróneo hasta un factor ~4 en f.
  - En cenital, el zoom equivale a bajar la altura (solo importa h/f), así que lo absorbe un modo que siga la escala.
  - En oblicua no. Además, un zoom puro H = diag(z, z, 1) (en coordenadas centradas) **no** se puede escribir como R + t·nᵀ/d con K fija: t·nᵀ/d tendría rango 2. La descomposición del `CalibradorCamara` recibe datos fuera de modelo [Derivado]. Su comportamiento real: **NO VERIFICADO**, hay que medirlo.
- **Órbitas y rotación (yaw):** no cambian pitch ni altura, así que un juego fijo puede servir. Pero nuestra CMC mueve las posiciones y **no rota la velocidad** del Kalman (`_cmc`: "la velocidad no se toca, como en el original"). Durante giros sostenidos la predicción apunta en la dirección vieja hasta que el filtro corrige [V en el código; efecto en HOTA NO VERIFICADO].
- **Acercamiento/alejamiento:** cambia la altura, y un manual fijo se equivoca de escala. El modo auto lo sigue con la H.
- **Implicación [Propuesta]:**
  - En DynUAV, el manual por secuencia es **un mal modelo** del problema. Ahí el número relevante es **UCMC-auto**, y el manual sirve de referencia.
  - Si hay segmentos de zoom identificables (escala de la H con traslación ~0), estratificar los resultados como "con zoom" y "sin zoom", igual que los bins de ego (D11).

---

## 4. Justicia y leakage

### 4.1 Reglas y literatura
- **MOTChallenge** [V] ([arXiv 2010.07548][motc], Apéndice A.1):
  - "Ground truth is only provided for the training sequences. It is the participant's own responsibility to find the best setting using only the training data… The use of ground truth labels on the test data is strictly forbidden."
  - Máximo de 4 envíos, con 72 h de espera, para "discourage the use of the benchmark server for training and parameter tuning on the test data".
  - En la introducción critica que los métodos se ajusten "for each sequence" y sobreajusten [V].
- **HOTA** [V] ([arXiv 2009.07736][hota]): la descomposición permite "select algorithms or tune algorithms' hyper-parameters based on the nuances of their particular use-case". Advierte que ajustar trackers para optimizar MOTA los sesga hacia la detección. Esto justifica elegir con HOTA o AssA, no con MOTA.
- **Mismo presupuesto:**
  - Melis et al. ([arXiv 1707.05589][melis]): con un ajuste a gran escala igual para todos, baselines bien ajustados superan a modelos más nuevos [V, abstract].
  - Lucic et al. ([arXiv 1711.10337][lucic]): las diferencias entre GANs desaparecen con el mismo presupuesto de cómputo [V, abstract].
  - Dodge et al. ([arXiv 1909.03004][dodge]): reportar el rendimiento esperado en validación **en función del presupuesto** [V, abstract].
  - Para MOT en concreto, MFGCS ([arXiv 2609.12261][mfgcs]): con el mismo espacio de búsqueda y pipeline, TPE/MFGCS superan a las configuraciones a mano y a las publicadas en las 8 combinaciones tracker×dataset, por hasta 4.38 y 16.05 HOTA [V, abstract]. **El presupuesto de búsqueda mueve más HOTA del que suele separar a dos trackers.**
- **Precedente en el propio UCMC y en ByteTrack/BoT-SORT:** configuraciones por secuencia de test en sus repos (§1.3) [V]. Es común, pero choca con la regla de MOTChallenge si se eligieron mirando métricas de test (NO VERIFICADO cómo se eligieron).

### 4.2 Selección sin GT: precedentes
- **Para trackers:** SQE ([arXiv 2004.07472][sqe], CVPR 2020) propone una métrica de autocalidad sin GT, basada en cantidad, longitud y distribución de distancias de apariencia de las trayectorias, "enabling parameters self-optimization" en MOT16 [V, abstract]. Usa **apariencia**, que nuestros trackers no tienen, así que solo vale como precedente conceptual.
- **Para calibración desde vehículos:**
  - Sochor et al. ([arXiv 1702.06451][sochor]) calibran la cámara de tráfico, incluida la **escala**, alineando modelos 3D de vehículos con sus cajas [V, título y abstract].
  - BrnoCompSpeed ([arXiv 1702.06441][brno]) evalúa calibraciones automáticas por el **error de velocidad** medida [V, título y abstract].

  Es el mismo principio que nuestro `CalibradorCamara`: escala con el tamaño de los vehículos y forma con la H.
- **Para UCMC en concreto:** no encontré ningún método publicado que elija la cámara de UCMC sin GT, aparte del alineamiento visual manual de los autores (NO VERIFICADO que no exista). El método de los autores **ya es sin GT** (visual), así que un criterio automático equivalente es defendible.

**Criterios sin GT candidatos para nuestro caso [Propuesta]**, todos calculables con las salidas de UCMC:
1. **Consistencia de tamaño:** el largo proyectado al suelo de los vehículos (dos esquinas de la base, o lado mayor × escala local) no debe depender de la fila de la imagen. Minimizar la pendiente de log(largo) frente a v. Fija pitch/hfov, que son la **no uniformidad**, y su mediana fija la escala con `ucmc_largo_vehiculo_m`.
2. **Velocidad plausible:** fracción de tracks confirmados con |v| > 45 m/s o |a| > 9.8 m/s². Es sensible a la escala y al pitch cerca del horizonte.
3. **Consistencia del filtro:** la media del NIS (d² de Mahalanobis de los pares asociados) debería rondar 2 (los grados de libertad). Ojo: la **verosimilitud en metros no es comparable entre escalas**. Hay que expresarla en píxeles, restando log|J| de la proyección, o la búsqueda premia escalas pequeñas por el término ln|S|.
4. **No usar** como criterio el número de IDs ni la vida media (`sin_gt.csv`): premian fusionar objetos.

Validación del criterio: medir en **train** (con GT) la correlación de rango entre el criterio y HOTA a lo largo de la rejilla. Solo si es alta se usa en test.

### 4.3 ¿Mismo presupuesto para los otros 3?
- La **cámara** es información de entrada que los demás no consumen, como la calibración que KITTI regala. Darle a UCMC una cámara elegida **sin GT de test** no es injusto.
- Pero por §2.4, **barrer la altura con GT equivale a ajustar wx, wy, vmax y a**: hiperparámetros del tracker.

**[Propuesta]**
- Si la altura y la escala se acotan con **física** (centro de la banda UAVDT, 100 m en DynUAV, o el modo auto por vehículos) y solo se elige en train, basta con declararlo. Los otros 3 se quedan en defaults (D4 y D16).
- Si se barre libremente pitch × escala con GT de train (N pruebas por grupo), los otros 3 reciben **el mismo N** sobre sus hiperparámetros, en el mismo split de train. Ejemplos: `track_high_thresh`, `new_track_thresh`, `match_thresh` y `track_buffer` en ByteTrack/BoT-SORT; el umbral IoU y `min_hits` en el propio. Se reportan **las dos tablas**, defaults y ajustados (A2 opción b).
- El oráculo en test **nunca** entra al ranking. Va en una columna aparte, "cota superior de UCMC con cámara perfecta-para-HOTA".

---

## 5. Costo y diseño del barrido

**Costo**
- El costo dominante hoy es la **estabilización**, que nuestro README da como la mayor parte de los 25–80 ms por frame. Pero la H no depende de los parámetros de cámara.
- Hay que cachear por secuencia (H_t, ok_t) y las detecciones ya pasadas a resolución de trabajo. Así cada prueba solo ejecuta `TrackerUCMC.seguir()` (calibrador + núcleo + libro), que ya existe y está separado del video (lo usa `selftest`).
- Costo por prueba: **NO VERIFICADO**. Se puede leer de la columna `tracking_ms` de `_tiempos.csv` de un run existente.

**Rejilla [Propuesta]**
- Cenital: pitch {0, 5, 10, 15, 20, 25} × escala {0.6, 1, 1.6} = **18**.
- Oblicua: pitch 25–70 cada 5° (10) × escala (3) = **30**, más un refinamiento ±4° cada 1° alrededor del mejor (×3) = **~54**.
- Sensibilidad de hfov: ±1 valor solo en el mejor punto (+2).
- Total ≈ **20–60 pruebas por secuencia**. Con 20 secuencias de test de UAVDT, ~1 000 corridas del núcleo.
- Optuna/TPE ([arXiv 1907.10902][optuna]) solo compensa con más de 3 dimensiones. Con 2 (pitch, escala), la rejilla es más interpretable y da la curva de sensibilidad gratis.
- Si se ajustan los otros 3 trackers (A2b), sí conviene TPE con un presupuesto igual y fijo, p. ej. 100 pruebas.

**Métrica objetivo**
- **HOTA** combinada del grupo (suma de conteos, D14), con **AssA** como desempate.
- Hay que vigilar **DetA**: los parámetros de cámara cambian qué detecciones se descartan por encima del horizonte (`n_fuera`). Un pitch malo puede bajar DetA sin que el tracker "asocie peor".
- IDF1 se reporta pero no se optimiza.

**Cómo reportar**
- **Curva de sensibilidad** por grupo: HOTA o AssA frente al pitch, una curva por escala, con el valor de UCMC-auto y de los otros 3 trackers como líneas horizontales.
- **Mejor, mediana y peor de la rejilla**, y la **fracción de la rejilla en la que UCMC supera a cada rival**. Esta última es la respuesta honesta a "¿UCMC gana si se conoce la cámara?".
- **Brecha auto − oráculo**: el costo de no conocer la cámara. **Brecha elegido-en-train − oráculo**: el optimismo del oráculo.
- Δ pareados con IC por bootstrap, como en el `comparaciones.csv` actual.
- El número total de pruebas por configuración, según Dodge et al.

---

## 6. Recomendación concreta

### 6.1 Protocolo (a fijar en DECISIONS.md **antes** de mirar test, como D17) [Propuesta]
1. **hfov fijo por dataset** según la ficha y §2.5: UAVDT 74°, VisDrone 74° y DynUAV 70°. Sensibilidad ±1 valor. Antes, cerrar A7 y corregir el 82° por defecto.
2. **Grupos:** UAVDT por `M_attr` (altitud × {cenital, oblicua}, donde oblicua = front o side). VisDrone y DynUAV con la etiqueta cenital/oblicua puesta a mano, sin GT. La altura central sale de la banda.
3. **Punto de apoyo** fijado por grupo (cenital = centro, oblicua = base), no por el pitch del barrido.
4. **Elegir** (pitch, escala) por grupo en el **split train**, maximizando HOTA (AssA como desempate). Congelar y aplicar en test.
5. **Criterio sin GT** (§4.2): validarlo en train. Si su correlación de rango con HOTA es alta, aplicarlo **por secuencia de test**.
6. **Oráculo** por secuencia en test: solo como cota y fuera del ranking.
7. **Otros 3 trackers:** defaults, y opcionalmente el mismo presupuesto en train (A2b). Los ruidos del Kalman de UCMC quedan fijos en los valores de `demo.py` (D16), y por eso la escala solo se mueve dentro de la banda física.

### 6.2 Configuraciones de UCMC a reportar

| Etiqueta | Cámara | Usa GT | ¿Entra al ranking? | Pregunta que responde |
|---|---|---|---|---|
| `ucmc_auto` | Calibración en línea; hfov de ficha | No | **Sí** (principal) | ¿Sirve UCMC sin conocer la cámara? |
| `ucmc_auto_hfov±` | Igual con hfov ±8° | No | No (sensibilidad) | ¿Cuánto depende del dato de ficha? |
| `ucmc_grupo_train` | Manual, (pitch, escala) por grupo elegido en train | Solo train | **Sí** | ¿Y si se conoce la "clase de vuelo"? |
| `ucmc_singt` | Manual, por secuencia, con criterio de consistencia métrica | No | Sí, si se valida en train | ¿Se puede elegir bien sin GT? |
| `ucmc_oraculo_seq` | Manual, la mejor de la rejilla por secuencia de test | **Test** | **No** (cota, etiquetada) | Techo con cámara perfecta-para-HOTA |
| `ucmc_oraculo_cruzado` (opcional) | Elegida en una mitad temporal, evaluada en la otra | Test | No | Cuánto del oráculo es sobreajuste |
| `ucmc_rejilla_{mediana,peor}` | Estadísticos de la rejilla | Test | No | Robustez a una cámara mal puesta |
| `propio_kf`, `bytetrack`, `botsort` (+ `*_train` si A2b) | — | No (o train) | Sí | Referencia con el mismo presupuesto |

### 6.3 Cambios mínimos de código (no implementados)

**`tracker_ucmc.py`**
1. Separar `ucmc_calibrar` en **`ucmc_calibrar_pitch`** y **`ucmc_calibrar_altura`**. Hoy no se puede fijar el pitch y dejar la altura por vehículos (híbrido útil para DynUAV y para limitar la escala con física). Hoy, si `cam.altura_m` es `None`, la altura sale de los vehículos en modo auto, pero en manual queda en 100 m (`ucmc_altura_defecto_m`) sin avisar.
2. Que el punto de apoyo pueda fijarse desde el barrido (`ucmc_punto="base"|"centro"`). El `"auto"` actual depende de `pitch_respaldo_deg < 30` y salta en mitad de la rejilla.
3. `matriz_K`: parámetro opcional de **aspecto de píxel** (fy = fx·k), por si UAVDT 1080×540 resulta anamórfico.
4. Diagnóstico para el criterio sin GT: exponer por frame las posiciones y velocidades en el suelo de los tracks confirmados, y el d² (NIS) de los pares asociados. Ya existen `n_fuera` y `salida_nucleo`.
5. Opcional: rotar la velocidad en `_cmc` con la parte rotacional de H (giro de yaw), si DynUAV muestra problemas en órbitas.

**Harness (`benchmark/`)**
1. `correr.crear_tracker`: permitir `camara: {...}` en cada entrada de `trackers`, combinado sobre `sec.ucmc`. Hoy la cámara sale solo de la secuencia, así que no se pueden correr dos cámaras en el mismo run.
2. **Caché de H por secuencia** (`cache/h/<seq>.npz`, con firma) y una ruta de ejecución "solo núcleo" que llame a `TrackerUCMC.seguir()` con H y detecciones cacheadas, sin decodificar video.
3. Comando `bench.py barrer --tracker ucmc --rejilla rejilla.yaml --split ajuste`. Escribiría `runs/<run>/barrido/<hash_cfg>/` con un `resultados.csv` (cfg × secuencia × HOTA/AssA/IDF1/DetA/n_fuera). Cerraría con la selección por grupo y una pasada final en test con la configuración congelada.
4. `secuencias.yaml`: campos `grupo` (p. ej. `alta_oblicua`), `camara_fuente` (`ficha`/`banda`/`a_mano`) y `split: ajuste` para UAVDT, VisDrone y DynUAV train. El `split: ajuste` ya está soportado y nunca se reporta.
5. Conversor UAVDT que lea `M_attr/*_attr.txt` → `grupo`.
6. `evaluar.py`: columna `uso_gt` (`no`/`train`/`test`). Las filas `test` (oráculo) se excluyen de `COMBINADO` y de `comparaciones.csv`.

---

## Referencias

**Código (commits leídos)**
- UCMCTrack — [github.com/corfyi/UCMCTrack][ucmc-repo] @ `7851a49078a6666725d1bda670f0046fcc0d715f`: `README.md`, `util/estimate_cam_para.py`, `util/run_ucmc.py`, `detector/{mapper,detector}.py`, `run_mot17_{val,test}.bat`, `run_mot20_test.bat`, `demo.py`, `cam_para/`
- MINTtrack — [github.com/mint-lab/MINTtrack][mint] @ `5abdbdd59d6e1b5228dc1577bba1c0341757ca83`
- ByteTrack — [github.com/ifzhang/ByteTrack][bt] @ `d1bf0191adff59bc8fcfeaa0b33d3d1642552a99`, `yolox/evaluators/mot_evaluator.py`
- BoT-SORT — [github.com/NirAharon/BoT-SORT][bs] @ `251985436d6712aaf682aaaf5f71edb4987224bd`, `tools/track.py`
- tensorbay (loader UAVDT de terceros) — [github.com/Graviti-AI/tensorbay-python-sdk][tb] @ `157490243aab4473e0a1385e4c766ca7afe8c9eb`, `tensorbay/opendataset/UAVDT/`
- VisDrone-Dataset — [README][visdrone-repo] @ `4364e8265275dfa44fd8f767b5180af58580194d`

**Papers y fichas**
- UCMCTrack — Yi et al., AAAI 2024, [arXiv 2312.08952][ucmc]
- UAVDT — Du et al., ECCV 2018, [arXiv 1804.00518][uavdt]; [página oficial][uavdt-site]
- VisDrone — Zhu et al., [arXiv 2001.06303][visdrone]
- DynUAV — CVPR 2026, [arXiv 2603.05970][dynuav]
- NDFT — Wu et al., ICCV 2019, [arXiv 1908.03856][ndft]
- MOTChallenge — Dendorfer et al., [arXiv 2010.07548][motc]
- HOTA — Luiten et al., IJCV 2021, [arXiv 2009.07736][hota]
- SQE — Huang et al., CVPR 2020, [arXiv 2004.07472][sqe]
- MFGCS / HPO en MOT — Adžemović, 2026, [arXiv 2609.12261][mfgcs]
- Melis et al. [arXiv 1707.05589][melis] · Lucic et al. [arXiv 1711.10337][lucic] · Dodge et al. [arXiv 1909.03004][dodge] · Optuna [arXiv 1907.10902][optuna]
- Sochor et al. [arXiv 1702.06451][sochor] · BrnoCompSpeed [arXiv 1702.06441][brno]
- DJI Mini 4 Pro, ficha oficial: [dji.com/mini-4-pro/specs][mini4] · DJI Zenmuse X4S: [dji.com/zenmuse-x4s/info][x4s]

[ucmc]: https://arxiv.org/abs/2312.08952
[ucmc-repo]: https://github.com/corfyi/UCMCTrack/tree/7851a49078a6666725d1bda670f0046fcc0d715f
[mint]: https://github.com/mint-lab/MINTtrack
[bt]: https://github.com/ifzhang/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/yolox/evaluators/mot_evaluator.py
[bs]: https://github.com/NirAharon/BoT-SORT/blob/251985436d6712aaf682aaaf5f71edb4987224bd/tools/track.py
[tb]: https://github.com/Graviti-AI/tensorbay-python-sdk/tree/157490243aab4473e0a1385e4c766ca7afe8c9eb/tensorbay/opendataset/UAVDT
[visdrone-repo]: https://github.com/VisDrone/VisDrone-Dataset
[uavdt]: https://arxiv.org/abs/1804.00518
[uavdt-site]: https://sites.google.com/view/grli-uavdt/
[visdrone]: https://arxiv.org/abs/2001.06303
[dynuav]: https://arxiv.org/abs/2603.05970
[ndft]: https://arxiv.org/abs/1908.03856
[motc]: https://arxiv.org/abs/2010.07548
[hota]: https://arxiv.org/abs/2009.07736
[sqe]: https://arxiv.org/abs/2004.07472
[mfgcs]: https://arxiv.org/abs/2609.12261
[melis]: https://arxiv.org/abs/1707.05589
[lucic]: https://arxiv.org/abs/1711.10337
[dodge]: https://arxiv.org/abs/1909.03004
[optuna]: https://arxiv.org/abs/1907.10902
[sochor]: https://arxiv.org/abs/1702.06451
[brno]: https://arxiv.org/abs/1702.06441
[mini4]: https://www.dji.com/mini-4-pro/specs
[x4s]: https://www.dji.com/zenmuse-x4s/info
