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

Dos fuentes de detecciones (campo `tipo` del perfil en `detectores`):
- `yolo` (por defecto): el harness corre el modelo de Ultralytics sobre la secuencia.
- `archivo` (D20): las detecciones ya existen, generadas fuera (p. ej. en el laboratorio con `detectar_lab.py`):
      <carpeta>/<secuencia>.txt   MOT: frame, -1, x, y, w, h, conf, clase, -1, -1  (frames base 1, px originales)
      <carpeta>/firma.json        modelo, sha256 de los pesos, imgsz, conf, iou, nombres de clase, versiones
  `bench.py detectar` solo las importa a la caché (.npz); el resto del harness no distingue el origen.
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


def detectar_frames(modelo, frames, imgsz, conf, iou, clases=None, dispositivo=None, nombre="", total=None):
    """Corre un modelo de Ultralytics sobre (frame, imagen). Devuelve (frame int32[N], dets float32[N,6], obb[N,8])."""
    fr_l, cajas, polis = [], [], []
    for fr, img in frames:
        r = modelo.predict(img, imgsz=imgsz, conf=conf, iou=iou, classes=clases, device=dispositivo, verbose=False)[0]
        obb = getattr(r, "obb", None)
        bx = obb if obb is not None else r.boxes
        if fr % 200 == 0:
            print(f"[detecciones] {nombre}: frame {fr}" + (f"/{total}" if total else ""))
        if bx is None or len(bx) == 0:
            continue
        d = np.concatenate([bx.xyxy.cpu().numpy(), bx.conf.cpu().numpy()[:, None], bx.cls.cpu().numpy()[:, None]], 1)
        fr_l.append(np.full(len(d), fr, np.int32))
        cajas.append(d.astype(np.float32))
        polis.append(obb.xyxyxyxy.cpu().numpy().reshape(-1, 8).astype(np.float32) if obb is not None
                     else np.full((len(d), 8), np.nan, np.float32))
    return (np.concatenate(fr_l) if fr_l else np.zeros(0, np.int32),
            np.concatenate(cajas) if cajas else np.zeros((0, 6), np.float32),
            np.concatenate(polis) if polis else np.zeros((0, 8), np.float32))


def escribir_detecciones_txt(ruta, frame, dets):
    """dets Nx6 [x1, y1, x2, y2, conf, clase] → MOT de 10 columnas (id = -1)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w") as fh:
        for f, (x1, y1, x2, y2, c, k) in zip(frame, dets):
            fh.write(f"{int(f)},-1,{x1:.2f},{y1:.2f},{x2 - x1:.2f},{y2 - y1:.2f},{c:.4f},{int(k)},-1,-1\n")


def leer_detecciones_txt(ruta):
    """Inverso de escribir_detecciones_txt → (frame int32[N], dets float32[N,6])."""
    ruta = Path(ruta)
    if ruta.stat().st_size == 0:
        return np.zeros(0, np.int32), np.zeros((0, 6), np.float32)
    a = np.loadtxt(ruta, delimiter=",", ndmin=2)
    if a.shape[1] < 8:
        raise ValueError(f"{ruta}: se esperaban ≥ 8 columnas (frame,id,x,y,w,h,conf,clase), hay {a.shape[1]}")
    x, y, w, h = a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    dets = np.stack([x, y, x + w, y + h, a[:, 6], a[:, 7]], 1).astype(np.float32)
    return a[:, 0].astype(np.int32), dets


def _importar_archivo(sec, nombre_det, perfil, rehacer):
    import json
    carpeta = Path(perfil["carpeta"])
    txt, fj = carpeta / f"{sec.nombre}.txt", carpeta / "firma.json"
    for p in (txt, fj):
        if not p.exists():
            raise FileNotFoundError(f"[detecciones] falta {p} (¿se corrió detectar_lab.py para '{sec.nombre}'?)")
    externa = json.load(open(fj))
    f = dict(origen="archivo", txt_sha256=sha256_archivo(txt), firma_externa=externa,
             clases=list(perfil.get("clases") or []), rango=list(rango_frames(sec)))
    out = ruta_cache(sec, nombre_det)
    meta_p = out.with_suffix(".json")
    if out.exists() and meta_p.exists() and not rehacer and hash_dict(json.load(open(meta_p)).get("firma")) == hash_dict(f):
        print(f"[detecciones] {sec.nombre}/{nombre_det}: caché válida, no se rehace")
        return out
    nombres = {int(k): v for k, v in externa["nombres_clases"].items()}
    frame, dets = leer_detecciones_txt(txt)
    if perfil.get("clases"):
        ids = _ids_clases(nombres, perfil["clases"])
        m = np.isin(dets[:, 5].astype(int), ids)
        frame, dets = frame[m], dets[m]
    a, b = f["rango"]
    m = (frame >= a) & (frame <= b)
    frame, dets = frame[m], dets[m]
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, frame=frame, dets=dets, obb=np.full((len(dets), 8), np.nan, np.float32))
    guardar_json(meta_p, dict(firma=f, nombres_clases=nombres, fps=fps_de(sec), versiones=versiones()))
    print(f"[detecciones] {sec.nombre}/{nombre_det}: {len(dets)} cajas importadas de {txt}")
    return out


def firma(sec, perfil):
    return dict(pesos_sha256=sha256_archivo(perfil["pesos"]), imgsz=perfil.get("imgsz", 1280),
                conf_cache=perfil.get("conf_cache", 0.05), clases=list(perfil.get("clases") or []),
                iou_nms=perfil.get("iou_nms", 0.7), rango=list(rango_frames(sec)), video=sec.video)


def cachear(sec, nombre_det, perfil, rehacer=False, dispositivo=None):
    """Corre el detector (o importa sus archivos, `tipo: archivo`) y guarda la caché. Devuelve la ruta del .npz."""
    if perfil.get("tipo", "yolo") == "archivo":
        return _importar_archivo(sec, nombre_det, perfil, rehacer)
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
    frame, dets, obb = detectar_frames(modelo, leer_frames(sec.video, a, b), f["imgsz"], f["conf_cache"],
                                       f["iou_nms"], clases, dispositivo, sec.nombre, b)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, frame=frame, dets=dets, obb=obb)
    guardar_json(meta_p, dict(firma=f, nombres_clases={int(k): v for k, v in modelo.names.items()},
                              fps=fps_de(sec), dispositivo=str(dispositivo), versiones=versiones()))
    print(f"[detecciones] {sec.nombre}/{nombre_det}: {len(dets)} cajas → {out}")
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
