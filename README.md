# Trackers DEV and BENCH — seguimiento de objetos en movimiento desde dron con fondos en Movimiento

Seguimiento multi-objeto (MOT) sobre video de dron, con la cámara en movimiento: qué objetos hay, con un ID estable, y cuáles **se mueven de verdad** (no por el movimiento del dron).

Se comparan cuatro trackers alimentados con las **mismas detecciones** (YOLO):

| Tracker | Idea |
|---|---|
| **Propio** (`propio_kf`) | Estabilización con la homografía `H` de la cámara + Kalman + IoU |
| **UCMCTrack** | Asocia en el suelo (metros), con calibración **automática** de la cámara (pitch y altura) |
| **ByteTrack** | Referencia de Ultralytics, sin compensar la cámara |
| **BoT-SORT** | Ultralytics, con su propia compensación de cámara (GMC) |

---

## Estructura

```
├── VD - Trackers To Real Implementation/   código final (.py), un archivo por tracker, misma interfaz
├── Tracker Notebooks/                      un notebook por tracker + la demo
├── Historial de desarrollo de trackers/    comparativas v5 → v14, cada una con sus resultados
├── benchmark/                              benchmark con GT: harness propio + TrackEval (ver su README)
└── docs/                                   investigación (cómo evaluar, BoxMOT, métricas)
```

| Carpeta | Qué contiene |
|---|---|
| **`VD - Trackers To Real Implementation/`** | La versión para llevar a tiempo real: `comun.py` (lo compartido), `tracker_propio.py`, `tracker_ucmc.py`, `tracker_bytetrack.py`, `tracker_botsort.py`, `adaptador_ultralytics.py` y `pruebas.py`. Documentación completa en su [README](VD%20-%20Trackers%20To%20Real%20Implementation/README.md) |
| **`Tracker Notebooks/`** | `tiempo_real_propio`, `tiempo_real_ucmc`, `tiempo_real_bytetrack`, `tiempo_real_botsort`: notebooks **autocontenidos** (mismo código que los `.py`, explicado celda por celda). `demo_tiempo_real`: los 4 trackers importando los `.py` |
| **`Historial de desarrollo de trackers/`** | `comparativa_trackers_v5` … `v14.ipynb` y, junto a cada uno, su carpeta de resultados (`comparativa_vXX/`: `resumen_metricas.csv`, métricas y tracks por video, `calibracion_ucmc.json`) |

**Dónde empezar:** el README de `VD - Trackers To Real Implementation/` y los notebooks de `Tracker Notebooks/`.

---

## Lo que NO está en el repo

- **Videos** (`.mp4`, `.webm`): los de entrada (VIGIA) y los generados (~60 GB). Los notebooks esperan los videos VIGIA en `/Users/Alex/Documents/videos_VIGIA/` (cambiar `VIDEO_PATH`); los de las primeras versiones (v5–v7), en `videos/`.
- **Pesos YOLO** (`.pt`): los notebooks los buscan en la raíz del repo (`../yolo11n.pt`, `../yolo11n-obb.pt`). Si no están, Ultralytics los descarga solo.
- **`salidas/`**: lo que escriben los notebooks al ejecutarse.

## Instalación

```bash
pip install numpy opencv-python scipy pandas matplotlib ultralytics
```

`ultralytics` hace falta para el detector YOLO y para ByteTrack / BoT-SORT. El tracker propio y UCMC solo necesitan `numpy`, `opencv-python` y `scipy`.

```bash
cd "VD - Trackers To Real Implementation" && python pruebas.py      # self-tests: debe terminar en "TODO OK"
```

## Licencias de terceros

`VD - Trackers To Real Implementation/tracker_ucmc.py` incluye código adaptado de [UCMCTrack](https://github.com/corfyi/UCMCTrack) (MIT, © 2023 Kefu Yi); el aviso de licencia está en el propio archivo.
