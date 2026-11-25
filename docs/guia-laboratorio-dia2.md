# Guía del laboratorio · Día 2 (fase de ajuste)

Qué se hace hoy en la computadora del laboratorio: preparar el entorno, generar las detecciones de las 50 secuencias con
`yolo8x_best.pt` y correr **solo la fase de ajuste** (30 secuencias). Al final, traer una carpeta pequeña a la Mac para
el congelado 1.

**Regla de oro: hoy nada de test.** Ningún comando con `--split test`, y ningún `correr`, `evaluar`, `moving` ni
`revisar`. Las detecciones de las 50 secuencias sí se generan (no usan GT), y el adaptador convierte el GT de las 50
(tampoco evalúa nada).

Tiempo estimado: **~1 h tuya** (pasos 1–5 y 9) más **2–4 h de cómputo desatendido** (pasos 6–8).

Cada paso dice qué debe salir (**✔ Esperado**) y qué hacer si no (**✘ Si falla**). Si algo no coincide, detente y
pásame el comando, las últimas ~40 líneas de la salida y el resultado de la comprobación del paso 3.

---

## 0. Antes de empezar (5 min)

Necesitas:

- [ ] Acceso al repo `AlejandroGB18/Trackers_DEVandBENCH` desde la máquina (SSH key o token de GitHub).
- [ ] Los tres archivos de UAVDT descomprimidos (los mismos que en la Mac): `UAV-benchmark-M/`,
      `UAV-benchmark-MOTD_v1.0/` y `M_attr/`.
- [ ] La ruta de `yolo8x_best.pt` en el laboratorio.
- [ ] ~15 GB libres: ~7 GB de UAVDT, 5–8 GB del ambiente de conda y algo de cachés.
- [ ] `tmux` o `screen` para que las corridas largas sigan si se cierra la terminal. Compruébalo con `which tmux`.

Comprueba el espacio y qué ambientes existen (no se toca ninguno):

```bash
df -h ~
conda env list
nvidia-smi
```

**✔ Esperado:** hay espacio, **no** existe un ambiente `bench-trackers` y `nvidia-smi` muestra la GPU.
**✘ Si ya existe `bench-trackers`:** cambia la línea `name:` de `benchmark/environment.yml` (paso 2) por otro nombre y
úsalo en todos los `conda activate`.
**✘ Si otros usan la GPU:** elige una libre con `export CUDA_VISIBLE_DEVICES=<n>`, usando el número que muestra
`nvidia-smi`.

---

## 1. Código (5 min)

```bash
cd ~                                   # o donde guarden sus proyectos
git clone -b benchmark-dia2-ajuste-revision git@github.com:AlejandroGB18/Trackers_DEVandBENCH.git
cd Trackers_DEVandBENCH
git log --oneline -1
```

**✔ Esperado:** el último commit dice `Día 2: ajuste del detector y tramos, revisión de moving y reporte`, o uno
posterior de esta misma rama.
**✘ Si `Permission denied (publickey)`:** usa la URL HTTPS `https://github.com/AlejandroGB18/Trackers_DEVandBENCH.git`
con un token, o agrega la llave SSH de la máquina a tu cuenta.

---

## 2. Ambiente de conda (15–30 min, casi todo descarga)

Crea un ambiente **nuevo y aislado**; no modifica `base` ni otros ambientes.

```bash
conda env create -f benchmark/environment.yml
conda activate bench-trackers
which python
```

**✔ Esperado:** `which python` termina en `.../envs/bench-trackers/bin/python`.
**✘ Si no tienes permisos sobre la carpeta de conda:**
`conda env create -f benchmark/environment.yml --prefix ~/envs/bench-trackers`, y luego
`conda activate ~/envs/bench-trackers`.

> **Importante:** cada vez que abras una terminal nueva o una ventana de tmux, vuelve a hacer
> `conda activate bench-trackers` antes de cualquier comando. Nunca instales con `pip` sin el ambiente activado.

---

## 3. Comprobar la GPU y las versiones (2 min)

```bash
python --version
python -c "import torch, ultralytics, trackeval, numpy, cv2; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-', ultralytics.__version__, numpy.__version__, cv2.__version__)"
```

**✔ Esperado:** Python 3.12, `True` y el nombre de la GPU, y Ultralytics `8.4.192`.
**✘ Si sale `False`:** el PyTorch de pip no coincide con el driver. Mira la versión de CUDA que reporta `nvidia-smi`
(arriba a la derecha) y reinstala **dentro del ambiente**. Por ejemplo, para CUDA 12.1:
`pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cu121`. Repite este paso.

---

## 4. Datos (10 min)

Elige una carpeta raíz de datos y deja ahí UAVDT con **exactamente** esta forma:

```
<RAIZ>/UAVDT/UAV-benchmark-M/M0101/img000001.jpg …        (50 carpetas)
<RAIZ>/UAVDT/UAV-benchmark-MOTD_v1.0/GT/M0101_gt.txt …     (150 archivos)
<RAIZ>/UAVDT/M_attr/train/M0101_attr.txt …                 (30)
<RAIZ>/UAVDT/M_attr/test/M0203_attr.txt …                  (20)
```

Después, en la terminal, apunta a esa raíz. Este `export` hay que repetirlo en cada terminal nueva:

```bash
export BENCH_DATOS=/ruta/a/RAIZ
ls $BENCH_DATOS/UAVDT/UAV-benchmark-M | wc -l            # 50
ls $BENCH_DATOS/UAVDT/UAV-benchmark-MOTD_v1.0/GT | wc -l  # 150
ls $BENCH_DATOS/UAVDT/M_attr/train | wc -l                # 30
ls $BENCH_DATOS/UAVDT/M_attr/test | wc -l                 # 20
```

**✔ Esperado:** 50, 150, 30 y 20.
**✘ Si hay una carpeta de más en medio** (por ejemplo `UAVDT/UAV-benchmark-M/UAV-benchmark-M/M0101`), muévela para que
quede como arriba.

---

## 5. Pruebas del harness (5–10 min) — **compuerta**

```bash
cd benchmark
python pruebas_benchmark.py 2>&1 | tee ../prueba_lab.log | tail -5
```

**✔ Esperado:** la última línea es `TODO OK`.
**✘ Si no:** **detente aquí** y pásame `prueba_lab.log`. Si las pruebas fallan, los números de allá no serían
comparables con los de aquí, así que no sigas con lo demás.

---

## 6. GT de UAVDT y detecciones (30–60 min de GPU)

Abre una sesión de tmux para que siga aunque se cierre la terminal:

```bash
tmux new -s bench            # para volver más tarde: tmux attach -t bench
conda activate bench-trackers
export BENCH_DATOS=/ruta/a/RAIZ
cd ~/Trackers_DEVandBENCH/benchmark
mkdir -p logs
```

**6a. Convertir el GT** (1 min):

```bash
python -m adaptadores.uavdt 2>&1 | tee logs/01_adaptador.log
```

**✔ Esperado:** una tabla con 7/14/9 secuencias de ajuste y 4/10/6 de test por grupo, y la línea
`GT convertido → …/gt_benchmark`. **No** uses `--yaml`: `secuencias.yaml` ya viene generado.

**6b. Detecciones de las 50 secuencias con `yolo8x_best.pt`** (la parte larga de GPU):

```bash
python detectar_lab.py --frames $BENCH_DATOS/UAVDT/UAV-benchmark-M \
                       --pesos /ruta/a/yolo8x_best.pt \
                       --salida $BENCH_DATOS/detecciones/yolo8x \
                       --dispositivo 0 2>&1 | tee logs/02_detectar_lab.log
```

**✔ Esperado:** 50 líneas `[detectar_lab] Mxxxx: N frames, K cajas, X ms/frame`. Después, comprueba:

```bash
ls $BENCH_DATOS/detecciones/yolo8x/*.txt | wc -l      # 50
python -c "import json;d=json.load(open('$BENCH_DATOS/detecciones/yolo8x/firma.json'));print(d['pesos'],d['imgsz'],d['conf'],d['train_args'])"
```

Debe decir `yolo8x_best.pt 640 0.05` y `model: yolov8x.pt`.

- **✘ Si se corta a la mitad:** vuelve a correr el mismo comando. Las secuencias ya hechas se omiten solas.
- **✘ Si `CUDA out of memory`:** alguien más está usando la GPU. Elige otra con `CUDA_VISIBLE_DEVICES` o espera.
- **✘ Si dice que `firma.json` es de otra configuración:** se corrió antes con otros pesos o umbrales. Usa otra
  carpeta en `--salida`, nunca mezcles.

---

## 7. Fase de ajuste: importar, ego y medición del detector (1–2 h de CPU)

Dentro de la misma sesión de tmux:

```bash
python bench.py detectar --split ajuste 2>&1 | tee logs/03_detectar_ajuste.log
python bench.py ego      --split ajuste 2>&1 | tee logs/04_ego_ajuste.log
python bench.py ajuste   --split ajuste --run v1_ajuste 2>&1 | tee logs/05_ajuste.log
```

- **`detectar`** importa las 30 de ajuste a la caché (segundos).
- **`ego`** es lo más lento: ~0.14 s por frame, unas 24k frames, así que **~1 h**. Cada secuencia imprime
  `H no fiable en X %`.
- **`ajuste`** imprime la tabla de DetA por grupo de vuelo e iluminación, la propuesta de `conf_high`/`conf_low` y los
  cortes de los tramos de ego.

**✔ Esperado:** existe `runs/v1_ajuste/ajuste/propuesta.json`, y en `05_ajuste.log` aparecen las líneas
`[ajuste] propuesta: …` y `[ajuste] tramos: …`.
**✘ Si alguna secuencia de `ego` da `H no fiable` > 20 %:** no es un error; anótala y sigue.
**✘ Si `ajuste` dice "falta el ego de Mxxxx":** el paso `ego` no terminó para esa secuencia. Repítelo con `--seq Mxxxx`.

---

## 8. Cámara de UCMC por grupo de vuelo (30–90 min)

```bash
python bench.py barrer --split ajuste --run v1_ajuste 2>&1 | tee logs/06_barrer_ajuste.log
```

**✔ Esperado:** 30 líneas `[barrer] Mxxxx (grupo, ajuste): 30|50 cámaras`, después `… pruebas → …/barrido` y una tabla
de selección con `grupo_train` para cada secuencia.
**✘ Si sale "grupo 'X': sin secuencias de ajuste con GT":** pásame el log. No debería pasar con UAVDT completo.

Para salir de tmux sin detener nada: `Ctrl-b` y luego `d`.

---

## 9. Traer los resultados a la Mac (5 min)

```bash
cd ~/Trackers_DEVandBENCH/benchmark
tar czf ~/v1_ajuste_lab.tgz runs/v1_ajuste cache/ego logs ../prueba_lab.log \
    $BENCH_DATOS/detecciones/yolo8x/firma.json
ls -lh ~/v1_ajuste_lab.tgz
```

Son pocos MB. Pásalo a la Mac (USB, `scp`, Drive) y avísame dónde quedó. Con eso hago el **congelado 1**: umbrales
del detector, estratos excluidos, tramos de ego y cámaras de UCMC, que quedan en `secuencias.yaml` y
`DECISIONS.md`. Hasta entonces, **no corras nada de test**.

Las detecciones (`$BENCH_DATOS/detecciones/yolo8x/*.txt`) se quedan en el laboratorio; se usan en el día 4.

---

## Resumen de comandos (si todo sale bien)

```bash
conda env create -f benchmark/environment.yml && conda activate bench-trackers
export BENCH_DATOS=/ruta/a/RAIZ && cd benchmark
python pruebas_benchmark.py                                   # TODO OK  ← compuerta
python -m adaptadores.uavdt
python detectar_lab.py --frames $BENCH_DATOS/UAVDT/UAV-benchmark-M --pesos /ruta/a/yolo8x_best.pt \
                       --salida $BENCH_DATOS/detecciones/yolo8x --dispositivo 0
python bench.py detectar --split ajuste
python bench.py ego      --split ajuste
python bench.py ajuste   --split ajuste --run v1_ajuste
python bench.py barrer   --split ajuste --run v1_ajuste
tar czf ~/v1_ajuste_lab.tgz runs/v1_ajuste cache/ego logs
```
