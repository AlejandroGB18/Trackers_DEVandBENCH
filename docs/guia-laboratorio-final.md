# Guía del laboratorio · Corrida final (test)

Qué se hace en esta visita: aplicar las correcciones del GT (D33) y la revisión de `moving` (congelado 2), buscar la
cámara definitiva de UCMC y, **con mi visto bueno**, correr test **una sola vez**. Al final se trae un `.tgz` a la Mac
para escribir los resultados.

Hay dos tandas con una pausa en medio:

| Tanda | Pasos | Tiempo | Toca test |
|---|---|---|---|
| 1 · Preparación | 0–6 | ~20 min tuyos + 1–3 h del barrido | Solo GT y etiquetas, ningún tracker |
| ⏸ Pausa | 7 | Me pasas el log del barrido y reviso la cámara | — |
| 2 · Corrida de test | 8–10 | ~10 min tuyos + 1–3 h de cómputo | **Sí, una sola vez** |

Cada paso dice qué debe salir (**✔ Esperado**) y qué hacer si no (**✘ Si falla**). Si algo no coincide, detente y
pásame el log de ese paso. No improvises arreglos: en test, cualquier cambio después de ver resultados invalida la
comparación.

---

## 0. Antes de empezar (5 min)

Vienes de cerrar la terminal y la sesión de Claude Code. **No se perdió nada**: el ambiente `bench-trackers`, el repo,
los datos, las cachés (`benchmark/cache/`) y los runs (`benchmark/runs/`) siguen en disco.

- [ ] **Energía:** que la máquina **no se suspenda** (Configuración → Energía → suspensión automática: Nunca). `nohup`
      sobrevive a cerrar la terminal, pero no a una suspensión o un reinicio.
- [ ] **GPU y máquina libres** unas 3–6 h. Si alguien más la usa, avísale.
- [ ] **Espacio:** `df -h ~` con al menos 5 GB libres (los runs de test son de cientos de MB).

---

## 1. Terminal y ambiente (2 min)

Abre una terminal nueva. **En cada terminal nueva** repite estas tres líneas antes de cualquier comando:

```bash
conda activate bench-trackers
export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
cd /home/udlap/Documents/Alex_y_sus_cosas/Trackers_DEVandBENCH
```

**✔ Esperado:** el prompt muestra `(bench-trackers)`.
**✘ Si `conda: command not found`:** corre `source ~/miniconda3/etc/profile.d/conda.sh` (o `~/anaconda3/...`) y repite.

---

## 2. Código actualizado (2 min)

```bash
git status --short
git fetch origin
git log --oneline origin/main..HEAD
```

**✔ Esperado:**
- `git status` no muestra archivos modificados (`M`). Solo pueden aparecer sin rastrear (`??`).
- `git log origin/main..HEAD` muestra **a lo más** un commit: `Prueba de rutas: no depende del BENCH_DATOS de quien la
  corre`. Es el parche que se hizo aquí en la visita anterior, y `main` ya lo trae con otro identificador.

Si se cumple, deja el repo idéntico a `main`:

```bash
git checkout main
git reset --hard origin/main
git log --oneline -1
cd benchmark
```

**✔ Esperado:** `Merge pull request #7 from AlejandroGB18/benchmark-dia2-ajuste-revision`, o uno posterior.
**✘ Si `git status` muestra archivos con `M`, o `git log origin/main..HEAD` muestra otros commits:** alguien cambió
código en esta máquina. **No hagas `reset`** (borraría esos cambios). Pásame la salida de los tres comandos y de
`git diff --stat`.
**✘ Si `fetch` pide usuario y contraseña:** usa tu token de GitHub (no la contraseña de la cuenta).

---

## 3. Compuerta (5–10 min)

```bash
grep -n "moving: {rel_mov" secuencias.yaml
ls revision/decisiones | wc -l
python pruebas_benchmark.py 2>&1 | tail -1
```

**✔ Esperado:**
- `moving: {rel_mov: 0.30, rel_est: 0.10}` (congelado 2);
- `22` (20 archivos de decisiones, `acuerdo.csv` y `calibracion.csv`);
- `TODO OK`.

**✘ Si las pruebas fallan:** **no sigas.** Pásame la salida completa de `python pruebas_benchmark.py`.

---

## 4. GT corregido (D33) (2 min)

```bash
python -m adaptadores.uavdt 2>&1 | tee logs/11_adaptador.log
```

**✔ Esperado:**
- Seis líneas `[uavdt] corrección D33`: M0601 (`fin=319`), M1101 (`excluir_frames=[322]` y `tracks_a_ignorada=[7]`),
  M0606, M0802, M1007 y M1401.
- La tabla de arriba con estos tracks:

  | split | cenital | oblicua_alta | oblicua_baja |
  |---|---|---|---|
  | ajuste | 383 | 537 | 446 |
  | test | 261 | 655 | 301 |

**✘ Si los números de ajuste son otros:** detente; el congelado 1 se hizo con esos.
**Ojo:** este comando **no** lleva `--yaml`. El `secuencias.yaml` correcto ya viene del repo.

---

## 5. Cachés y `moving` revisado (5–10 min)

```bash
python bench.py detectar --split test 2>&1 | tee logs/12_detectar_test.log
python bench.py moving --split test 2>&1 | tee logs/13_moving_test.log
python bench.py aplicar-revision --split test --decisiones revision/decisiones 2>&1 | tee logs/14_aplicar_revision.log
```

**✔ Esperado:**
- `detectar`: M0601 dice `cajas importadas` (cambió su rango a 1–319); las otras 19 dicen `caché válida, no se rehace`.
- `moving`: 20 líneas `[moving] Mxxxx: …`.
- `aplicar-revision`: una tabla con las 20 secuencias, todas con `faltan 0` y `acuerdo 1.0`. M1004 sale `NaN` porque
  no tiene seguros de muestra; es normal. Al final: `moving.csv escrito junto a cada gt.txt`.

**✘ Si alguna secuencia dice `AVISO, faltan N tracks por decidir`:** detente y pásame el log.
**✘ Si dice `sin página de revisión, se omite`:** falta la carpeta `revision/` de esa secuencia en
`$BENCH_DATOS/UAVDT/gt_benchmark/<seq>/`. Detente.
**No corras `revisar`:** regeneraría la muestra aleatoria y las decisiones dejarían de corresponder.
**No hace falta correr `ego`:** las 20 cachés de test ya existen. La de M0601 cubre 1–372, que incluye el 1–319.

---

## 6. Barrido de cámara de UCMC (1–3 h, desatendido)

Recorre las 50 secuencias con los umbrales congelados: elige la cámara de `ucmc_grupo_train` con las de ajuste y
calcula la cota `ucmc_oraculo_seq` en test.

```bash
nohup python bench.py barrer --run v1_ajuste > logs/15_barrer_todas.log 2>&1 &
```

Puedes cerrar la terminal. Para ver el avance, abre otra terminal, repite el paso 1, entra a `benchmark/` y corre:

```bash
grep -c "cámaras" logs/15_barrer_todas.log     # va de 0 a 50
tail -3 logs/15_barrer_todas.log
pgrep -af "bench.py barrer"                    # si no imprime nada, ya terminó (o se cayó)
```

**✔ Esperado al terminar:**
- 50 líneas `[barrer] Mxxxx (...): N cámaras`;
- `[barrer] 2280 pruebas → …/runs/v1_ajuste/barrido` (30 cámaras en cenital y 50 en las oblicuas);
- la línea del criterio sin GT;
- una tabla de selección con filas `singt`, `oraculo_seq` y `grupo_train`.

**✘ Si `pgrep` no muestra nada y el log no llegó a la tabla:** se cayó. Pásame `tail -40 logs/15_barrer_todas.log`.

---

## 7. ⏸ Pausa: pásame el resultado del barrido

```bash
grep "grupo_train" logs/15_barrer_todas.log
tail -80 logs/15_barrer_todas.log > ~/barrido_final.txt
```

Mándame `~/barrido_final.txt` (o pega las líneas). Reviso que la cámara de cada grupo de vuelo tenga sentido y la anoto
en D32.4. **No sigas al paso 8 hasta que te dé el visto bueno.**

---

## 8. Corrida de test, una sola vez (1–3 h, desatendido)

```bash
nohup sh -c "python bench.py correr --split test --run v1 && \
             python bench.py evaluar --split test --run v1 && \
             python bench.py reporte --run v1" > logs/16_test_v1.log 2>&1 &
```

Avance, desde otra terminal (paso 1 y `cd benchmark`):

```bash
grep -c "^\[correr\] M" logs/16_test_v1.log    # va de 0 a 20
tail -3 logs/16_test_v1.log
pgrep -af "bench.py"
```

**✔ Esperado al terminar:**
- `[correr] listo → …/runs/v1`;
- la tabla `COMBINADO` de `evaluar`;
- `[reporte] → …/runs/v1/reporte/resultados.md`;
- `ls runs/v1` muestra `propio_kf`, `bytetrack`, `botsort`, `ucmc_grupo_train`, `ucmc`, `ucmc_oraculo_seq`, `eval`,
  `reporte` y `run.json`.

**✘ Si `correr` falla a medias:** **no lo relances** ni borres `runs/v1`. Pásame `tail -60 logs/16_test_v1.log`.
Decidimos juntos cómo seguir sin repetir la corrida a ciegas.
**✘ Si falla `evaluar` o `reporte` (pero `correr` dijo `listo`):** esos sí se pueden repetir sin problema, porque no
vuelven a correr trackers. Aun así, pásame el error primero.

---

## 9. Empaquetar y traer a la Mac (5 min)

```bash
tar czf ~/v1_test.tgz runs/v1 runs/v1_ajuste/barrido logs
ls -lh ~/v1_test.tgz
```

Pásalo a la Mac (USB, `scp`, Drive) y déjalo en Descargas. Con eso escribo `docs/resultados-v1.md`.

---

## 10. Cerrar

- Si usaste Claude Code: `/logout` y luego `/exit` (la máquina es compartida).
- Puedes devolver la suspensión automática a como estaba.

---

## Si lo corre Claude Code en el laboratorio

Inicia sesión tú (`claude` dentro del repo) y pega:

```text
Ejecuta docs/guia-laboratorio-final.md paso a paso, del 1 al 7, en esta máquina Linux.
Reglas:
- Sigue la guía al pie de la letra. No cambies código, secuencias.yaml ni revision/decisiones/.
- Antes de cada comando: conda activate bench-trackers y export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
- Si un paso no da el "✔ Esperado", detente y muéstrame el log.
- NO corras revisar, correr, evaluar ni reporte. En el paso 7 muéstrame el resultado del barrido y DETENTE.
- No modifiques ningún ambiente de conda que no sea bench-trackers.
- Avísame al terminar cada paso con los números clave.
```

Después de mi visto bueno, pégale: `Continúa con los pasos 8 y 9 de docs/guia-laboratorio-final.md.`
