"""
adaptador_ultralytics.py — Usa ByteTrack / BoT-SORT REALES de Ultralytics con NUESTRAS detecciones
==================================================================================================

Ultralytics normalmente detecta y sigue a la vez (model.track). Aquí solo se usa su tracker, alimentado con las
detecciones del detector externo, para que la comparación con el propio y con UCMC sea justa (mismas detecciones).
La API interna de Ultralytics cambia entre versiones: este archivo absorbe esas diferencias (probado con 8.4.x).
Lo usan tracker_bytetrack.py y tracker_botsort.py.
"""
# ======================================================================
# IMPORTACIONES
# Qué hace : Carga las librerías
# ¿Se toca? : No
# ======================================================================
import importlib
import inspect
import os
from types import SimpleNamespace

import numpy as np


# ======================================================================
# PARTE 1 · Compatibilidad con Ultralytics
# Qué hace : Encuentra sus clases y sus yaml en la versión instalada
# ¿Se toca? : No
# ======================================================================
class _Dets:
    """Imita lo mínimo del objeto Boxes de Ultralytics que consumen sus trackers (xyxy, xywh, conf, cls, indexado)."""

    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, np.float32).reshape(-1)
        self.cls = np.asarray(cls, np.float32).reshape(-1)
        if len(self.xyxy):
            x1, y1, x2, y2 = self.xyxy.T
            self.xywh = np.stack([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], 1).astype(np.float32)
        else:
            self.xywh = np.zeros((0, 4), np.float32)
        self.data = np.concatenate([self.xyxy, self.conf[:, None], self.cls[:, None]], 1)

    def __len__(self):
        return len(self.conf)

    def __getitem__(self, idx):
        return _Dets(self.xyxy[idx], self.conf[idx], self.cls[idx])


class _NS(SimpleNamespace):
    """Respaldo de IterableSimpleNamespace por si esta versión de Ultralytics no lo exporta donde se espera."""

    def get(self, k, default=None):
        return getattr(self, k, default)

    def __iter__(self):
        return iter(vars(self).items())


def _importar():
    """Importa BYTETracker, BOTSORT e IterableSimpleNamespace probando varias ubicaciones."""
    ul = importlib.import_module("ultralytics")
    errs, byte, bot, ns = [], None, None, None
    for mb, mt in (("ultralytics.trackers", "ultralytics.trackers"),
                   ("ultralytics.trackers.byte_tracker", "ultralytics.trackers.bot_sort")):
        try:
            byte = getattr(importlib.import_module(mb), "BYTETracker")
            bot = getattr(importlib.import_module(mt), "BOTSORT")
            break
        except Exception as e:
            errs.append(f"{mb}: {e}")
    if byte is None:
        raise ImportError("No encuentro BYTETracker/BOTSORT en Ultralytics. Intentos: " + " | ".join(errs))
    for m in ("ultralytics.utils", "ultralytics.cfg", "ultralytics.utils.checks"):
        try:
            ns = getattr(importlib.import_module(m), "IterableSimpleNamespace")
            break
        except Exception:
            continue
    return ul, byte, bot, (ns or _NS)


def _leer_yaml(ul, fname):
    """Lee bytetrack.yaml / botsort.yaml de la carpeta del paquete."""
    import yaml
    pkg = os.path.dirname(ul.__file__)
    path = os.path.join(pkg, "cfg", "trackers", fname)
    if not os.path.isfile(path):
        for root, _, files in os.walk(pkg):
            if fname in files:
                path = os.path.join(root, fname)
                break
        else:
            raise FileNotFoundError(f"No encuentro {fname} dentro de {pkg}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def diagnostico():
    """Imprime lo necesario para adaptar el código si tu versión de Ultralytics difiere de lo esperado."""
    ul = importlib.import_module("ultralytics")
    print("ultralytics", getattr(ul, "__version__", "?"), "|", os.path.dirname(ul.__file__))
    try:
        _, byte, bot, _ns = _importar()
        for nm, cl in (("BYTETracker", byte), ("BOTSORT", bot)):
            print(nm, "__init__", inspect.signature(cl.__init__), "| update", inspect.signature(cl.update))
    except Exception as e:
        print("Trackers:", e)


# ======================================================================
# PARTE 2 · TrackerUltralytics
# Qué hace : Crea el tracker con los umbrales COMUNES de Config y lo actualiza con nuestras detecciones
# ¿Se toca? : No
# ======================================================================
class TrackerUltralytics:
    """tipo: "bytetrack" | "botsort".  gmc (solo botsort): "sparseOptFlow" | "orb" | "ecc" | "none".
    update(dets, img) -> Nx7 [x1, y1, x2, y2, id, conf, clase]."""

    YAML = {"bytetrack": "bytetrack.yaml", "botsort": "botsort.yaml"}

    def __init__(self, tipo, cfg, fps, gmc=None, overrides=None):
        ul, BYTE, BOT, NS = _importar()
        args = NS(**_leer_yaml(ul, self.YAML[tipo]))
        args.track_high_thresh = cfg.conf_high                     # mismos umbrales que el propio y UCMC
        args.track_low_thresh = cfg.conf_low
        args.new_track_thresh = cfg.conf_high
        args.track_buffer = int(round(cfg.max_miss_sec * 30))      # Ultralytics lo reescala con frame_rate/30
        if tipo == "botsort":
            args.with_reid = False                                 # sin ReID: no requiere pesos adicionales
            if gmc is not None:
                args.gmc_method = gmc
        for k, v in (overrides or {}).items():
            setattr(args, k, v)
        self.tipo, self.args = tipo, args
        self.tracker = self._construir(BYTE if tipo == "bytetrack" else BOT, args, fps)
        # ventana de pérdida en FRAMES, explícita (no depende de cómo cada versión reescala track_buffer)
        self.frames_perdida = max(2, int(round(cfg.max_miss_sec * fps)))
        for attr in ("max_time_lost", "buffer_size"):
            if hasattr(self.tracker, attr):
                setattr(self.tracker, attr, self.frames_perdida)

    @staticmethod
    def _construir(Cls, args, fps):
        """Construye el tracker según la firma REAL del constructor (cambia entre versiones)."""
        nombres = [n for n in inspect.signature(Cls.__init__).parameters if n != "self"]
        kw = {}
        if "args" in nombres:
            kw["args"] = args
        for n in ("frame_rate", "fps"):
            if n in nombres:
                kw[n] = int(round(fps))
        return Cls(**kw) if kw else Cls(args)

    def update(self, dets, img):
        """dets: Nx6 [x1,y1,x2,y2,conf,clase] en píxeles de trabajo; img: frame BGR de trabajo (lo usa el GMC de BoT-SORT)."""
        d = _Dets(dets[:, :4], dets[:, 4], dets[:, 5]) if len(dets) else _Dets([], [], [])
        try:
            out = self.tracker.update(d, img)
        except TypeError:
            out = self.tracker.update(d)
        out = np.asarray(out, np.float32)
        return out[:, :7] if out.ndim == 2 and len(out) else np.zeros((0, 7), np.float32)
