"""
comunes.py — Lo que comparten todas las etapas del benchmark
=============================================================

- Rutas (dónde viven las cachés y las corridas).
- Lectura del manifiesto (secuencias.yaml).
- Lectura de frames por rango, desde un video o desde una carpeta de imágenes (UAVDT: img000001.jpg …).
- Rutas portables: lo relativo se resuelve contra `datos_raiz` (variable de entorno BENCH_DATOS > `datos_raiz` del
  manifiesto > carpeta del manifiesto), así el mismo manifiesto sirve en la Mac y en el laboratorio.
- Lectura y escritura de archivos MOT.
- Huellas (hash) y versiones, para que cada resultado diga con qué se hizo.

Convención de frames en TODO el benchmark: **número de frame del video, base 1** (frame 1 = primer frame del
archivo), igual que MOTChallenge. Si una secuencia es un tramo del video (`rango`), los frames siguen siendo los del
video completo: así el GT, las detecciones y las salidas de los trackers se cruzan sin desfases.
"""
import functools
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

RAIZ_BENCH = Path(__file__).resolve().parent
RAIZ_REPO = RAIZ_BENCH.parent
DIR_TRACKERS = RAIZ_REPO / "VD - Trackers To Real Implementation"
DIR_CACHE = RAIZ_BENCH / "cache"          # detecciones y ego-movimiento (se calculan UNA vez)
DIR_RUNS = RAIZ_BENCH / "runs"            # salidas de los trackers y evaluaciones

if str(DIR_TRACKERS) not in sys.path:
    sys.path.insert(0, str(DIR_TRACKERS))

MOT_COLS = ["frame", "id", "x", "y", "w", "h", "conf", "clase", "c9", "c10"]


# ======================================================================
# Manifiesto
# ======================================================================
@dataclass
class Secuencia:
    nombre: str
    video: str                             # archivo de video o carpeta de frames (orden alfabético = orden temporal)
    detector: str                          # clave en `detectores`
    rango: tuple = (1, None)               # [primer, último] frame del video (base 1, inclusivo); None = hasta el final
    fps: float = None                      # None = el del archivo de video
    split: str = "test"                    # "ajuste" | "test" (los de ajuste NUNCA se reportan)
    ucmc: dict = field(default_factory=dict)   # kwargs de CamaraUCMC (hfov_deg, pitch_respaldo_deg, altura_m)
    gt: str = None                         # ruta a gt.txt (MOT, frames del video, base 1); None = sin GT
    gt_moving: str = None                  # ruta a moving.csv (frame,id,moving) revisado; None = derivarlo
    gt_frames: dict = None                 # {inicio, fin, paso}: frames ANOTADOS (los únicos que se evalúan)
    toma: str = None                       # "cenital" | "oblicua" (punto de apoyo para `moving` y para UCMC)
    grupo: str = None                      # grupo de vuelo para el barrido de UCMC (p. ej. "alta_oblicua"); None = toma
    camara_fuente: str = None              # de dónde sale la cámara de `ucmc`: telemetria | ficha | banda | a_mano
    atributos: dict = field(default_factory=dict)   # metadatos del dataset (altitud, vista, iluminación…), para estratos

    @property
    def grupo_barrido(self):
        return self.grupo or self.toma or "sin_grupo"


@dataclass
class Manifiesto:
    detectores: dict
    secuencias: list
    trackers: list
    config_comun: dict
    evaluacion: dict
    barrido: dict = field(default_factory=dict)   # rejilla de cámara de UCMC por grupo (ver barrido.py)
    ruta: Path = None
    datos_raiz: Path = None

    def secuencia(self, nombre):
        for s in self.secuencias:
            if s.nombre == nombre:
                return s
        raise KeyError(f"No hay secuencia '{nombre}' en {self.ruta}")


def raiz_datos(d, ruta_manifiesto):
    """BENCH_DATOS > `datos_raiz` del manifiesto (relativo al manifiesto) > carpeta del manifiesto."""
    if os.environ.get("BENCH_DATOS"):
        return Path(os.environ["BENCH_DATOS"]).expanduser().resolve()
    if d.get("datos_raiz"):
        p = Path(d["datos_raiz"]).expanduser()
        return (p if p.is_absolute() else ruta_manifiesto.parent / p).resolve()
    return ruta_manifiesto.parent


def cargar_manifiesto(ruta):
    import yaml
    ruta = Path(ruta).resolve()
    d = yaml.safe_load(open(ruta, encoding="utf-8"))
    base = raiz_datos(d, ruta)

    def abs_(p):
        if p is None:
            return None
        p = Path(p).expanduser()
        return str(p if p.is_absolute() else (base / p).resolve())

    secs = []
    for s in d["secuencias"]:
        s = dict(s)
        for k in ("video", "gt", "gt_moving"):
            s[k] = abs_(s.get(k))
        s["rango"] = tuple(s.get("rango") or (1, None))
        secs.append(Secuencia(**s))
    dets = {}
    for k, v in d["detectores"].items():
        v = dict(v)
        for c in ("pesos", "carpeta"):
            if v.get(c):
                v[c] = abs_(v[c])
        dets[k] = v
    return Manifiesto(detectores=dets, secuencias=secs, trackers=list(d.get("trackers", [])),
                      config_comun=dict(d.get("config_comun", {})), evaluacion=dict(d.get("evaluacion", {})),
                      barrido=dict(d.get("barrido", {})), ruta=ruta, datos_raiz=base)


# ======================================================================
# Frames: video o carpeta de imágenes
# ======================================================================
EXT_IMAGEN = (".jpg", ".jpeg", ".png", ".bmp")
FPS_CARPETA = 30.0          # una carpeta de frames no trae fps: se usa `fps` de la secuencia o este valor (UAVDT)


@functools.lru_cache(maxsize=64)
def _imagenes(ruta):
    p = Path(ruta)
    return tuple(sorted(str(f) for f in p.iterdir() if f.suffix.lower() in EXT_IMAGEN))


def info_video(ruta):
    if Path(ruta).is_dir():
        imgs = _imagenes(str(ruta))
        if not imgs:
            raise FileNotFoundError(f"La carpeta {ruta} no tiene imágenes {EXT_IMAGEN}")
        h, w = cv2.imread(imgs[0]).shape[:2]
        return dict(n_frames=len(imgs), fps=FPS_CARPETA, ancho=w, alto=h)
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise FileNotFoundError(f"No se puede abrir el video {ruta}")
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return dict(n_frames=n, fps=float(fps), ancho=w, alto=h)


def rango_frames(sec):
    """(primer, último) frame base 1, inclusivo, ya resuelto contra la duración del video."""
    inf = info_video(sec.video)
    a, b = sec.rango
    a = int(a or 1)
    b = int(b) if b else inf["n_frames"]
    return a, min(b, inf["n_frames"])


def fps_de(sec):
    return float(sec.fps) if sec.fps else info_video(sec.video)["fps"]


def leer_frames(ruta, primero, ultimo):
    """Genera (frame base 1, imagen BGR) de `primero` a `ultimo` inclusive. En una carpeta, el frame k es la k-ésima
    imagen en orden alfabético (img000001.jpg = frame 1)."""
    if Path(ruta).is_dir():
        imgs = _imagenes(str(ruta))
        for f in range(primero, min(ultimo, len(imgs)) + 1):
            img = cv2.imread(imgs[f - 1])
            if img is None:
                raise IOError(f"No se pudo leer {imgs[f - 1]}")
            yield f, img
        return
    cap = cv2.VideoCapture(str(ruta))
    if primero > 1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, primero - 1)
    f = primero
    try:
        while f <= ultimo:
            ok, img = cap.read()
            if not ok:
                break
            yield f, img
            f += 1
    finally:
        cap.release()


# ======================================================================
# Archivos MOT
# ======================================================================
def escribir_mot(ruta, filas):
    """filas: iterable de (frame, id, x1, y1, x2, y2, conf, clase). Escribe MOT de 10 columnas (x, y, w, h)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w") as fh:
        for fr, tid, x1, y1, x2, y2, conf, cls in filas:
            fh.write(f"{int(fr)},{int(tid)},{x1:.2f},{y1:.2f},{x2 - x1:.2f},{y2 - y1:.2f},{conf:.4f},{int(cls)},-1,-1\n")


def leer_mot(ruta, columnas=MOT_COLS):
    """Lee un MOT (gt.txt o salida de tracker). Devuelve DataFrame con frame, id, x, y, w, h, ... (sin filas = vacío)."""
    ruta = Path(ruta)
    if not ruta.exists() or ruta.stat().st_size == 0:
        return pd.DataFrame(columns=columnas[:9])
    df = pd.read_csv(ruta, header=None)
    df = df.iloc[:, :len(columnas)]
    df.columns = columnas[:df.shape[1]]
    df["frame"] = df["frame"].astype(int)
    df["id"] = df["id"].astype(int)
    return df


def leer_gt(ruta):
    """gt.txt estilo MOT / CVAT 'MOT 1.1': frame, id, x, y, w, h, considerar, clase, visibilidad."""
    return leer_mot(ruta, ["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])


# ======================================================================
# Huellas y versiones
# ======================================================================
def sha256_archivo(ruta, bloque=1 << 20):
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for b in iter(lambda: fh.read(bloque), b""):
            h.update(b)
    return h.hexdigest()


def hash_dict(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


def commit_git():
    try:
        c = subprocess.run(["git", "-C", str(RAIZ_REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        sucio = subprocess.run(["git", "-C", str(RAIZ_REPO), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        return c + ("+cambios" if sucio else "")
    except Exception:
        return "desconocido"


def versiones():
    v = dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, pandas=pd.__version__,
             plataforma=platform.platform(), git=commit_git())
    for mod in ("ultralytics", "trackeval", "scipy"):
        try:
            v[mod] = __import__(mod).__version__
        except Exception:
            v[mod] = None
    return v


def guardar_json(ruta, d):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False, default=str)
