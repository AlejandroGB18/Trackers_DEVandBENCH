# Guía del laboratorio · Ablación complementaria sin H3 (D36.1)

Solo ajuste. No toca test. Corre 4 variantes de `propio_kf` sobre las 30 secuencias de ajuste y aplica la regla de
elección de la v2, fijada en [`DECISIONS.md`, D36.1](../benchmark/DECISIONS.md).

| Pasos | Qué | Tiempo |
|---|---|---|
| 1–3 | Ambiente, código y compuerta | ~10 min |
| 4 | Cadena desatendida: correr → control → análisis | 30–90 min |
| 5–6 | Revisar, empaquetar | 5 min |

Si un paso no da el **✔ Esperado**, detente y pásame la salida.

## 1. Terminal y ambiente

```bash
conda activate bench-trackers
export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
cd /home/udlap/Documents/Alex_y_sus_cosas/Trackers_DEVandBENCH
```

## 2. Código actualizado

```bash
git status --short
git pull origin main
cd benchmark
```

**✔ Esperado:** `git status` sin archivos con `M` y `pull` sin conflictos.
**Reglas de git:** no hagas `commit`, `push`, `reset` ni `stash pop`.

## 3. Compuerta

```bash
ls diagnostico_v2b.yaml analisis/ablacion.py
ls runs/diag_v2/propio_A4_tentativos/*.txt | wc -l
python bench.py correr --manifiesto diagnostico_v2b.yaml --run x --split test 2>&1 | tail -1
```

**✔ Esperado:**
- Los dos archivos existen.
- `30`: la A4 de la visita anterior, contra la que se compara el control.
- `error: un manifiesto de diagnóstico solo corre con --split ajuste`. Que falle aquí es lo correcto.

**✘ Si no da 30:** detente. Sin `runs/diag_v2` no se puede hacer el control ni el análisis.

## 4. Cadena desatendida

```bash
nohup sh -c "\
python bench.py correr --split ajuste --manifiesto diagnostico_v2b.yaml --run diag_v2b && \
echo '[control] A4 repetida contra diag_v2' && \
(cd runs/diag_v2/propio_A4_tentativos && sha256sum *.txt) > /tmp/a4_v2.sha && \
(cd runs/diag_v2b/propio_A4_tentativos && sha256sum -c /tmp/a4_v2.sha --quiet) && \
echo '[control] OK: A4 idéntica (30/30)' && \
python analisis/ablacion.py runs/diag_v2 runs/diag_v2b" > logs/21_ablacion_v2b.log 2>&1 &
```

Para ver el avance (desde otra terminal, con el paso 1 y `cd benchmark`):

```bash
grep -c "^\[correr\] M" logs/21_ablacion_v2b.log     # llega a 30
tail -3 logs/21_ablacion_v2b.log
pgrep -af "bench.py|ablacion.py"                     # si no imprime nada, terminó o se detuvo
```

## 5. Revisar

```bash
grep "\[control\]" logs/21_ablacion_v2b.log
grep -v "^\[gt\]" logs/21_ablacion_v2b.log | tail -16
```

**✔ Esperado:**
- `[control] OK: A4 idéntica (30/30)`.
- La tabla de la ablación con 12 filas (las 8 de `diag_v2` más A6, A7 y A8) y al final `[D36.1] ELEGIDO para la v2: …`.

**✘ Si el control falla** (aparece `FAILED` o no sale la línea OK): no relances nada y pásame
`grep -B2 -A5 control logs/21_ablacion_v2b.log`.

## 6. Empaquetar y traer a la Mac

```bash
tar czf ~/ablacion_v2b.tgz runs/diag_v2b logs/21_ablacion_v2b.log
ls -lh ~/ablacion_v2b.tgz
```

Déjalo en Descargas de la Mac.

## Si lo corre Claude Code en el laboratorio

```text
Ejecuta docs/guia-laboratorio-v2b.md paso a paso, del 1 al 6, en esta máquina Linux.
Repo: /home/udlap/Documents/Alex_y_sus_cosas/Trackers_DEVandBENCH (los comandos van en benchmark/).
Reglas:
- Antes de cada comando: conda activate bench-trackers && export BENCH_DATOS=/home/udlap/Documents/Alex_y_sus_cosas/data_benchmark
- Paso 2: si docs/guia-laboratorio-v2b.md no existe después del pull, detente y avísame (falta fusionar el PR).
- Sigue la guía al pie de la letra. No cambies código ni manifiestos, y no toques runs/diag_v2 ni runs/v1*.
- Git: solo status, fetch, log y pull. Nada de commit, push, reset ni stash pop.
- Nunca corras nada con --split test, salvo la prueba del paso 3, que debe fallar.
- Si un paso no da el "✔ Esperado", detente y muéstrame la salida.
- Paso 4: lanza la cadena con nohup tal cual y revisa el avance cada ~10 min hasta que termine.
- Al terminar, muéstrame la tabla final y la línea "[D36.1] ELEGIDO".
```
