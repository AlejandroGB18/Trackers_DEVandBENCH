"""
detecciones.py — Detector FIJO y cacheado
==========================================

Una sola pasada del detector por secuencia. Todos los trackers consumen exactamente estas cajas, así que lo que
cambia entre ellos es solo la asociación.

- Umbral de caché BAJO (`conf_cache`, 0.05 por defecto): por debajo de `conf_low` (0.10), porque los trackers hacen
  una segunda ronda con las detecciones débiles. El umbral que realmente entra al tracker es `config_comun.conf_entrada`.
- Se guardan: caja horizontal xyxy, confianza, clase y, si el modelo es OBB, el polígono original (8 valores).
- Junto a cada caché va un .json con el hash de los pesos, imgsz, clases, versión de Ultralytics y dispositivo.
  Si alguno cambia, la caché se rehace.
"""
from pathlib import Path

import numpy as np

from comunes import DIR_CACHE, fps_de, guardar_json, hash_dict, leer_frames, rango_frames, sha256_archivo, versiones


def ruta_cache(sec, nombre_det):
    return DIR_CACHE / "detecciones" / nombre_det / f"{sec.nombre}.npz"


def _ids_clases(names, wanted):
    inv = {str(v).lower(): int(k) for k, v in names.items()}
    falt = [w for w in wanted if str(w).lower() not in inv]
    if falt:
        raise ValueError(f"Clases que no existen en el modelo: {falt}. Disponibles: {sorted(inv)}")
    return [inv[str(w).lower()] for w in wanted]


def firma(sec, perfil):
    return dict(pesos_sha256=sha256_archivo(perfil["pesos"]), imgsz=perfil.get("imgsz", 1280),
                conf_cache=perfil.get("conf_cache", 0.05), clases=list(perfil.get("clases") or []),
                iou_nms=perfil.get("iou_nms", 0.7), rango=list(rango_frames(sec)), video=sec.video)


def cachear(sec, nombre_det, perfil, rehacer=False, dispositivo=None):
    """Corre el detector sobre la secuencia y guarda la caché. Devuelve la ruta del .npz."""
    out = ruta_cache(sec, nombre_det)
    meta_p = out.with_suffix(".json")
    f = firma(sec, perfil)
    if out.exists() and meta_p.exists() and not rehacer:
        import json
        previa = json.load(open(meta_p))
        if hash_dict(previa.get("firma")) == hash_dict(f):
            print(f"[detecciones] {sec.nombre}/{nombre_det}: caché válida, no se rehace")
            return out
        print(f"[detecciones] {sec.nombre}/{nombre_det}: la configuración cambió, se rehace")

    from ultralytics import YOLO
    modelo = YOLO(perfil["pesos"])
    clases = _ids_clases(modelo.names, perfil["clases"]) if perfil.get("clases") else None
    a, b = rango_frames(sec)
    frames, cajas, polis = [], [], []
    for fr, img in leer_frames(sec.video, a, b):
        r = modelo.predict(img, imgsz=f["imgsz"], conf=f["conf_cache"], iou=f["iou_nms"], classes=clases,
                           device=dispositivo, verbose=False)[0]
        obb = getattr(r, "obb", None)
        bx = obb if obb is not None else r.boxes
        if bx is None or len(bx) == 0:
            continue
        d = np.concatenate([bx.xyxy.cpu().numpy(), bx.conf.cpu().numpy()[:, None], bx.cls.cpu().numpy()[:, None]], 1)
        frames.append(np.full(len(d), fr, np.int32))
        cajas.append(d.astype(np.float32))
        polis.append(obb.xyxyxyxy.cpu().numpy().reshape(-1, 8).astype(np.float32) if obb is not None
                     else np.full((len(d), 8), np.nan, np.float32))
        if fr % 200 == 0:
            print(f"[detecciones] {sec.nombre}: frame {fr}/{b}")
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out,
                        frame=np.concatenate(frames) if frames else np.zeros(0, np.int32),
                        dets=np.concatenate(cajas) if cajas else np.zeros((0, 6), np.float32),
                        obb=np.concatenate(polis) if polis else np.zeros((0, 8), np.float32))
    guardar_json(meta_p, dict(firma=f, nombres_clases={int(k): v for k, v in modelo.names.items()},
                              fps=fps_de(sec), dispositivo=str(dispositivo), versiones=versiones()))
    print(f"[detecciones] {sec.nombre}/{nombre_det}: {sum(len(c) for c in cajas)} cajas → {out}")
    return out


class CacheDetecciones:
    """Lee una caché: por_frame(f) → Nx6 [x1, y1, x2, y2, conf, clase] en píxeles del frame original."""

    def __init__(self, ruta_npz):
        import json
        z = np.load(ruta_npz)
        self.frame, self.dets = z["frame"], z["dets"]
        meta = json.load(open(Path(ruta_npz).with_suffix(".json")))
        self.nombres_clases = {int(k): v for k, v in meta["nombres_clases"].items()}
        self.meta = meta
        orden = np.argsort(self.frame, kind="stable")
        self.frame, self.dets = self.frame[orden], self.dets[orden]
        self._ini = {}
        if len(self.frame):
            u, i0, n = np.unique(self.frame, return_index=True, return_counts=True)
            self._ini = {int(f): (int(s), int(s + c)) for f, s, c in zip(u, i0, n)}

    def por_frame(self, f, conf_min=0.0):
        s = self._ini.get(int(f))
        if s is None:
            return np.zeros((0, 6), np.float32)
        d = self.dets[s[0]:s[1]]
        return d[d[:, 4] >= conf_min]

    @classmethod
    def desde_arrays(cls, frame, dets, nombres_clases):
        """Para pruebas: caché en memoria sin archivo."""
        self = cls.__new__(cls)
        self.frame, self.dets = np.asarray(frame, np.int32), np.asarray(dets, np.float32)
        self.nombres_clases, self.meta = dict(nombres_clases), {}
        self._ini = {}
        if len(self.frame):
            orden = np.argsort(self.frame, kind="stable")
            self.frame, self.dets = self.frame[orden], self.dets[orden]
            u, i0, n = np.unique(self.frame, return_index=True, return_counts=True)
            self._ini = {int(f): (int(s), int(s + c)) for f, s, c in zip(u, i0, n)}
        return self
