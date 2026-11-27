# Guía del laboratorio · Ablación en ajuste y v1.1

Qué se hace en esta visita, todo en una sola cadena desatendida:

1. **Ablación de `propio_kf` en ajuste** (D35.6): 6 variantes, más ByteTrack y BoT-SORT como referencia. Sirve para
   la v2 y no toca test.
2. **v1.1 en test** (D35): la segunda y última corrida de test, con un único cambio (la asociación de `propio_kf`
   ignora la clase). **Antes de evaluar**, una comprobación automática verifica que todos los demás trackers salieron
   idénticos a la v1. Si no, la cadena se detiene sola.

| Pasos | Qué | Tiempo |
|---|---|---|
| 0–3 | Preparación y compuerta | ~15 min tuyos |
| 4 | Cadena desatendida: ablación → v1.1 → comprobación → evaluación → reporte | 2–5 h de cómputo |
| 5 | Revisar el resultado de la comprobación | 2 min |
| 6–7 | Empaquetar y cerrar | 5 min |

Cada paso dice qué debe salir (**✔ Esperado**) y qué hacer si no (**✘ Si falla**). Si algo no coincide, detente y
pásame el log de ese paso.

---

## 0. Antes de empezar

- [ ] **Energía:** que la máquina **no se suspenda** (Configuración → Energía → suspensión automática: Nunca).
- [ ] **Máquina libre** unas 5 h. No corras otras cosas pesadas en paralelo: la v1.1 mide tiempos por frame.
- [ ] **Espacio:** `df -h ~` con al menos 5 GB libres.

---

## 1. Terminal y ambiente

En cada terminal nueva:

```bash
conda activate bench-trackers
export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
cd /home/udlap/Documents/Alex_y_sus_cosas/Trackers_DEVandBENCH
```

---

## 2. Código actualizado

```bash
git status --short
git fetch origin
git log --oneline HEAD..origin/main | head
git pull origin main
cd benchmark
```

**✔ Esperado:**
- `git status` sin archivos con `M`.
- `pull` sin conflictos, y el último commit es el merge del PR de la v1.1.

**✘ Si hay archivos con `M` o `pull` pide resolver conflictos:** detente, no hagas `reset` y pásame la salida.
**Reglas de git:** no hagas `commit`, `push` ni `stash pop`.

---

## 3. Compuerta (5–10 min)

```bash
python pruebas_benchmark.py 2>&1 | tail -1
python "../VD - Trackers To Real Implementation/tracker_propio.py"
grep -n "gate_clase\|propio_kf_v1" secuencias.yaml
ls runs/v1/propio_kf | wc -l
python bench.py correr --manifiesto diagnostico_v2.yaml --run x --split test 2>&1 | tail -1
```

**✔ Esperado:**
- `TODO OK`.
- `tracker_propio OK | … | car/van alternado: 2 IDs con gate_clase (v1), 1 sin él`.
- Dos líneas de `secuencias.yaml`: `{nombre: propio_kf, config: {gate_clase: false}}` y la de `propio_kf_v1`.
- `60` (los archivos de la v1, contra los que se compara la v1.1).
- `error: un manifiesto de diagnóstico solo corre con --split ajuste`. Es la protección para no usar test por error, y
  que falle aquí es lo correcto.

**✘ Si `ls runs/v1/propio_kf` no da 60:** detente. Sin la v1 completa no se puede hacer la comprobación D35.3.

---

## 4. Cadena desatendida (2–5 h)

Un solo comando. Cada etapa corre solo si la anterior terminó bien (`&&`):

```bash
nohup sh -c "\
python bench.py correr  --split ajuste --manifiesto diagnostico_v2.yaml --run diag_v2 && \
python bench.py evaluar --split ajuste --manifiesto diagnostico_v2.yaml --run diag_v2 && \
python bench.py correr  --split test --run v1_1 && \
python analisis/comparar_runs.py runs/v1 runs/v1_1 && \
python bench.py evaluar --split test --run v1_1 && \
python bench.py reporte --run v1_1" > logs/20_ablacion_y_v1_1.log 2>&1 &
```

Puedes cerrar la terminal. Para ver el avance, desde otra (paso 1 y `cd benchmark`):

```bash
grep -c "^\[correr\] M" logs/20_ablacion_y_v1_1.log    # 30 (ajuste) y luego 50 al terminar test
tail -3 logs/20_ablacion_y_v1_1.log
pgrep -af "bench.py|comparar_runs"                     # si no imprime nada, la cadena terminó o se detuvo
```

---

## 5. Revisar la comprobación D35.3

```bash
grep -A10 "comparar_runs" logs/20_ablacion_y_v1_1.log
tail -2 logs/20_ablacion_y_v1_1.log
```

**✔ Esperado:**
- 7 líneas `OK`. Seis dicen "se esperaban idénticas" (bytetrack, botsort, ucmc_grupo_train, ucmc, ucmc_oraculo_seq y
  propio_kf ↔ propio_kf_v1); una dice "se esperaban distintas" (propio_kf).
- `[comparar_runs] TODO OK: solo cambió propio_kf (D35.3)`.
- Al final del log: `[reporte] → …/runs/v1_1/reporte/resultados.md`.

**✘ Si alguna línea dice `MAL` o aparece `NO EVALUAR`:** la cadena se detuvo **antes** de evaluar, como debe ser. **No
la relances ni borres nada.** Pásame `grep -A12 comparar_runs logs/20_ablacion_y_v1_1.log`.
**✘ Si se detuvo antes, en la ablación o en `correr`:** pásame `tail -40 logs/20_ablacion_y_v1_1.log`.

---

## 6. Empaquetar y traer a la Mac

```bash
tar czf ~/v1_1_y_ablacion.tgz runs/v1_1 runs/diag_v2 logs/20_ablacion_y_v1_1.log
ls -lh ~/v1_1_y_ablacion.tgz
```

Déjalo en Descargas de la Mac. Con eso escribo la comparación v1 contra v1.1 y el resultado de la ablación.

---

## 7. Cerrar

- Si usaste Claude Code: `/logout` y luego `/exit`.
- Puedes devolver la suspensión automática a como estaba.

---

## Si lo corre Claude Code en el laboratorio

```text
Ejecuta docs/guia-laboratorio-v1_1.md paso a paso, del 1 al 6, en esta máquina Linux.
Repo: /home/udlap/Documents/Alex_y_sus_cosas/Trackers_DEVandBENCH (los comandos de bench.py van en benchmark/).
Reglas:
- Antes de cada comando: conda activate bench-trackers && export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
- Sigue la guía al pie de la letra. No cambies código, secuencias.yaml, diagnostico_v2.yaml ni revision/decisiones/.
- Git: solo status, fetch, log y pull. Nada de commit, push, reset ni stash pop.
- Si un paso no da el "✔ Esperado", detente y muéstrame el log.
- Paso 4: lanza la cadena con nohup tal cual y revisa el avance cada ~15 min hasta que termine.
- Paso 5: si comparar_runs no da TODO OK, NO relances nada: muéstrame la salida y detente.
- No modifiques ningún ambiente de conda que no sea bench-trackers.
- Avísame al terminar cada paso con los números clave.
```
