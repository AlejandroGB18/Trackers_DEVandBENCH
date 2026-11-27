# Resultados del benchmark v1.1 · la asociación ignora la clase

La v1.1 es la segunda y última corrida de test sobre UAVDT-MOT. Se hizo el 2026-11-27 en el laboratorio, con `main`
en `eecd6d0` (PR #12). Corrige un único error de implementación: D7 decía que la clase no debía influir, pero solo se
aplicó en la evaluación, y `propio_kf` seguía usando la clase para asociar. Se declara como desviación del protocolo
([`DECISIONS.md`, D35](../benchmark/DECISIONS.md)). Todo lo demás es igual a la v1
([`resultados-v1.md`](resultados-v1.md)). **Las conclusiones del benchmark se toman de la v1.1** (D35.5).

Reporte completo generado: [`resultados-v1_1/reporte/resultados.md`](resultados-v1_1/reporte/resultados.md).

## En una página

1. **La comprobación D35.3 pasó.** ByteTrack, BoT-SORT, las tres versiones de UCMC y `propio_kf_v1` (la v1 corrida otra
   vez) salieron idénticos byte a byte a la v1: 40 de 40 archivos cada uno. Solo cambió `propio_kf`, que era lo único
   que debía cambiar.
2. **Quitar la compuerta de clase ayuda poco.** HOTA de `propio_kf` 40.3 → 40.7 (+0.4, IC [−0.04, +0.92], empate). IDF1
   +1.0 (IC [+0.2, +2.0], mejora real). Los IDSW bajan de 1 894 a 1 665 (−12 %). Sigue último.
3. **El ranking no cambia:** BoT-SORT 42.5, UCMC por grupo 42.3, ByteTrack 41.9, `propio_kf` 40.7. Un solo veredicto
   cambia: contra ByteTrack, `propio_kf` pasa de perder a **empatar** en HOTA e IDF1. En AssA sigue perdiendo con
   todos.
4. **P1 (ego):** la conclusión se mantiene: ninguno pierde AssA de forma robustamente menor que los demás. Hay una
   excepción frágil, explicada abajo.
5. **P2 (decisor):** sin cambios. F1 ≈ 83 en los cuatro.
6. **El cambio de clase no era la causa, sino el detonante.** Sin la compuerta, `propio_kf` sigue haciendo los mismos
   cambios de identidad de ida y vuelta (71 %). La ablación en ajuste encontró la causa principal: los tracks
   tentativos compiten con los establecidos ([`diagnostico-propio-kf.md`, §6](diagnostico-propio-kf.md#6-resultado-de-la-ablación-en-ajuste)).

## 1. v1 y v1.1 lado a lado

| tracker | HOTA v1 | HOTA v1.1 | AssA v1 | AssA v1.1 | IDF1 v1 | IDF1 v1.1 | IDSW v1 | IDSW v1.1 |
|---|---|---|---|---|---|---|---|---|
| botsort | 42.5 | 42.5 | 55.7 | 55.7 | 55.3 | 55.3 | 298 | 298 |
| ucmc_grupo_train | 42.3 | 42.3 | 53.6 | 53.6 | 55.1 | 55.1 | 614 | 614 |
| bytetrack | 41.9 | 41.9 | 54.5 | 54.5 | 54.5 | 54.5 | 342 | 342 |
| **propio_kf** | 40.3 | **40.7** | 49.6 | **50.6** | 51.6 | **52.7** | 1 894 | **1 665** |

Los otros tres no cambian porque sus salidas son idénticas (D35.3). DetA de `propio_kf` queda igual (33.1).

**`propio_kf` v1.1 contra v1** (bootstrap pareado, 20 secuencias):

| métrica | Δ | IC 95 % | gana en | veredicto |
|---|---|---|---|---|
| HOTA | +0.40 | [−0.04, +0.92] | 13/20 | empate |
| AssA | +1.02 | [−0.03, +2.13] | 13/20 | empate |
| IDF1 | +1.00 | [+0.18, +1.95] | 11/20 | mejora |
| DetA | −0.02 | [−0.09, +0.03] | 7/20 | igual |

**Comparaciones del ranking que tocan a `propio_kf`** (A − B):

| A vs B | métrica | v1 | v1.1 | ¿cambia? |
|---|---|---|---|---|
| propio_kf vs bytetrack | HOTA | −1.5 [−2.9, −0.3] gana ByteTrack | −1.1 [−2.7, +0.2] **empate** | sí |
| | AssA | −5.0 [−7.0, −3.0] | −3.9 [−5.9, −2.1] | no, gana ByteTrack |
| | IDF1 | −2.8 [−5.4, −0.4] gana ByteTrack | −1.8 [−4.4, +0.3] **empate** | sí |
| propio_kf vs botsort | HOTA | −2.2 [−3.7, −0.9] | −1.8 [−3.4, −0.5] | no, gana BoT-SORT |
| | AssA | −6.1 [−8.0, −4.1] | −5.1 [−6.9, −3.3] | no |
| | IDF1 | −3.6 [−6.2, −1.1] | −2.6 [−5.1, −0.4] | no |
| propio_kf vs ucmc_grupo_train | HOTA | −1.9 [−2.9, −1.1] | −1.5 [−2.2, −1.0] | no, gana UCMC |
| | AssA | −4.0 [−6.0, −2.3] | −3.0 [−4.3, −2.0] | no |
| | IDF1 | −3.5 [−5.2, −1.9] | −2.5 [−3.5, −1.5] | no |

Las comparaciones entre BoT-SORT, ByteTrack y UCMC son idénticas a la v1: BoT-SORT le gana a ByteTrack en las tres
métricas y empata con UCMC en HOTA e IDF1.

## 2. P1 · Ego-movimiento

ΔAssA de `propio_kf` entre el tramo bajo y el alto: −6.3 [−10.0, +1.2] en la v1 y −3.3 [−6.6, +3.5] en la v1.1. Los
otros tres no cambian (−5.3, −6.1 y −7.2).

En la diferencia pareada aparece **una** comparación significativa: `propio_kf` pierde menos AssA que
`ucmc_grupo_train` (+3.9, IC [+1.3, +6.4], 11 secuencias). Las otras cinco parejas son empates, igual que en la v1. Se
reporta, pero no cambia la conclusión de P1, por tres razones:

- Es 1 de 6 comparaciones, sin corrección por comparaciones múltiples, y con solo 11 secuencias.
- En la v1 era un empate (+0.9 [−0.7, +3.8]). Cambió con una corrección que no tiene nada que ver con el ego.
- `propio_kf` parte de un AssA más bajo en el tramo bajo, así que tiene menos que perder.

**Conclusión de P1 (v1.1):** ningún tracker es robustamente más estable con ego alto. Compensar el movimiento de
cámara (BoT-SORT, UCMC) no se tradujo en más estabilidad de identidad.

## 3. P2 · Decisor de movimiento

| tracker | precisión | recall | F1 [IC 95 %] |
|---|---|---|---|
| propio_kf | 99.2 | 72.2 | 83.6 [77.8, 88.9] |
| ucmc_grupo_train | 99.2 | 72.0 | 83.5 [77.7, 88.8] |
| botsort | 99.3 | 71.2 | 83.0 [77.1, 88.5] |
| bytetrack | 99.3 | 71.1 | 82.9 [76.9, 88.4] |

Igual que en la v1: los ICs se traslapan por completo. La limitación del filtro de paralaje (D35.7) sigue vigente.

## 4. ¿Por qué ayudó tan poco?

En la v1, el 79 % de los cambios de identidad de `propio_kf` coincidían con un cambio de clase, y se sospechó de la
compuerta (H1). La v1.1 permite revisar esa sospecha con el mismo conteo descriptivo
(`benchmark/analisis/cambios_identidad.py`):

| `propio_kf` | v1 (con compuerta) | v1.1 (sin compuerta) |
|---|---|---|
| Cambios de identidad | 3 636 | 3 187 (−12 %) |
| …con cambio de clase entre la identidad vieja y la nueva | 79 % | 43 % |
| …sin ningún frame perdido entre las dos | 86 % | 87 % |
| …ida y vuelta en ≤ 10 frames | 67 % | 71 % |

La relación con la clase casi desaparece, pero los cambios de ida y vuelta siguen. La clase marcaba **cuándo** se
duplicaba un track, no **por qué** sobrevivía el duplicado. La ablación en ajuste lo confirma: lo que elimina la mayoría
de los switches es que los tracks tentativos no compitan con los establecidos (H4, −84 % de IDSW en ajuste).
Corregirlo es v2, elegido en ajuste (D35.6), y no entra a test de UAVDT.

## 5. Conclusiones finales del benchmark (v1.1)

1. **Ranking:** BoT-SORT primero, en empate técnico con UCMC por grupo; ByteTrack tercero (BoT-SORT le gana con IC
   que excluye 0); `propio_kf` último, empatado con ByteTrack en HOTA pero peor en asociación que los tres.
2. **P1:** ningún tracker resiste mejor el ego alto de forma robusta.
3. **P2:** el tracker no cambia la capacidad de decidir qué se mueve (F1 ≈ 83).
4. **Cámara de UCMC:** vale poco con este detector (cota +1 HOTA).
5. **El detector es el cuello de botella** (DetA 33–34; [`resultados-v1.md`, §6](resultados-v1.md#6-el-detector-la-mayor-limitación)).

Limitaciones: las de la v1 ([`resultados-v1.md`, §7](resultados-v1.md#7-limitaciones)), más que test se usó dos veces.
La segunda corrida cambió un solo tracker, con las reglas fijadas antes (D35) y comprobación byte a byte de los demás.

## Reproducir

```bash
cd benchmark
python bench.py correr  --split test --run v1_1
python analisis/comparar_runs.py runs/v1 runs/v1_1
python bench.py evaluar --split test --run v1_1
python bench.py reporte --run v1_1
```

Log del laboratorio: `benchmark/logs/lab_v1_1/20_ablacion_y_v1_1.log` (local, no versionado). Datos de evaluación y
reporte: [`resultados-v1_1/`](resultados-v1_1/).
