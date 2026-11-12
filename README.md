# ByteTracker — detección y seguimiento de objetos en movimiento desde dron

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

| Ruta | Qué es |
|---|---|
| `trackers_tiempo_real/` | **Versión final para tiempo real**: un archivo por tracker, misma interfaz. Documentación en [`trackers_tiempo_real/README.md`](trackers_tiempo_real/README.md) |
| `tiempo_real_propio.ipynb`, `tiempo_real_ucmc.ipynb`, `tiempo_real_bytetrack.ipynb`, `tiempo_real_botsort.ipynb` | Un notebook **autocontenido** por tracker (mismo código que `trackers_tiempo_real/`, explicado celda por celda) |
| `demo_tiempo_real.ipynb` | Demo con los 4 trackers usando los `.py` de `trackers_tiempo_real/` |
| `comparativa_trackers_v5` … `v14.ipynb` | Historia de la comparativa (cada versión, una mejora) |
| `comparativa*/` | Resultados de cada versión: `resumen_metricas.csv`, métricas y tracks por video, calibraciones de UCMC (`calibracion_ucmc.json`) |
| `tracker_propio.ipynb`, `tracker_bytetrack.ipynb`, `tracker_botsort.ipynb` | Notebooks individuales anteriores (antes de la versión de tiempo real) |
| `deteccion_tracking_movimiento_v1` … `v4.ipynb`, `ByteTracker.ipynb`, `ByteTrack_Jupyter_inicio.ipynb`, `YOLO_ByteTrack_Dron_Diagnostico.ipynb` | Primeros experimentos |
| `bytetrack_experiment/` | Configuraciones (`.yaml`) y estadísticas de los primeros ajustes de ByteTrack / BoT-SORT |

**Dónde empezar:** `trackers_tiempo_real/README.md` y los notebooks `tiempo_real_*.ipynb`.

---

## Lo que NO está en el repo

- **Videos** (`.mp4`, `.webm`): los de entrada (VIGIA) y los generados. Pesan ~60 GB. Los notebooks esperan los videos VIGIA en `/Users/Alex/Documents/videos_VIGIA/` (cambiar `VIDEO_PATH`).
- **Pesos YOLO** (`.pt`): Ultralytics los descarga solo la primera vez (`yolo11n.pt`, `yolo11n-obb.pt`, `yolo11s.pt`).
- **`salidas/`**: lo que escriben los notebooks al ejecutarse.

## Instalación

```bash
pip install numpy opencv-python scipy pandas matplotlib ultralytics
```

`ultralytics` hace falta para el detector YOLO y para ByteTrack / BoT-SORT. El tracker propio y UCMC solo necesitan `numpy`, `opencv-python` y `scipy`.

```bash
cd trackers_tiempo_real && python pruebas.py      # self-tests: debe terminar en "TODO OK"
```

## Licencias de terceros

`trackers_tiempo_real/tracker_ucmc.py` incluye código adaptado de [UCMCTrack](https://github.com/corfyi/UCMCTrack) (MIT, © 2023 Kefu Yi); el aviso de licencia está en el propio archivo.

## Notas del repo

`YOLO_ByteTrack_Dron_Diagnostico.ipynb` se guarda **sin salidas** (con ellas pesa 68 MB). Lo hace un filtro de git declarado en `.gitattributes`; en un clon nuevo, para que el filtro funcione al hacer commit:

```bash
git config filter.sinsalidas.clean "jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to notebook --stdin --stdout --log-level=ERROR"
git config filter.sinsalidas.smudge cat
```
