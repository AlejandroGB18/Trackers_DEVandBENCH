"""
ego.py — Ego-movimiento del dron, medido OFFLINE e independiente de los trackers
=================================================================================

Para cada frame f se estima H_ref(f-1 → f): lleva un punto del suelo del frame anterior al actual.
Se usa para:
  1. Estratificar las métricas por intensidad del movimiento de la cámara (bins).
  2. Derivar la etiqueta GT `moving` (gt.py).
NUNCA es entrada de los trackers.

Es deliberadamente DISTINTO de `comun.Estabilizador` (LK + RANSAC a 960 px), para que el GT no herede los errores
de la misma H que usan los trackers:
  - SIFT a `ancho_ref` (1920 px por defecto), emparejado con prueba de razón de Lowe;
  - se enmascaran las cajas (GT si existe y TODAS las detecciones cacheadas), para que los vehículos no voten;
  - USAC_MAGSAC en lugar de RANSAC;
  - comprobación ida-vuelta: H_ref se acepta solo si H(f→f-1)·H(f-1→f) ≈ I.

Columnas de salida (CSV, una fila por frame):
  frame, h00..h22 (H en píxeles ORIGINALES), n_inliers, ida_vuelta_px, H_ok,
  ego_px      desplazamiento medio de una rejilla 3×3, en px a 960 de ancho (= mov_camara_px de la v13),
  ego_rot_deg rotación de la parte lineal de H,
  ego_scale   √|det A| (zoom / cambio de altura),
  H_resid_px  error mediano de los inliers (a 960 px),
  ego_px_1s   desplazamiento de la rejilla acumulado en la última ventana de 1 s (a 960 px).
"""
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from comunes import DIR_CACHE, fps_de, leer_frames, leer_gt, rango_frames

ANCHO_METRICA = 960          # las métricas en px se expresan a este ancho (mismo que work_width de los trackers)
H_COLS = [f"h{i}{j}" for i in range(3) for j in range(3)]


def ruta_cache(sec):
    return DIR_CACHE / "ego" / f"{sec.nombre}.csv"


def _rejilla(w, h):
    return np.array([[x, y] for x in (0.1 * w, 0.5 * w, 0.9 * w) for y in (0.1 * h, 0.5 * h, 0.9 * h)], np.float64)


def _warp(H, p):
    q = np.c_[p, np.ones(len(p))] @ H.T
    return q[:, :2] / q[:, 2:3]


def _escalar_H(H, k):
    """H en coordenadas escaladas por k → H en coordenadas originales (o al revés con 1/k)."""
    S = np.diag([k, k, 1.0])
    return np.linalg.inv(S) @ H @ S


def _mascara(forma, cajas, k, margen=0.15):
    m = np.full(forma, 255, np.uint8)
    for x1, y1, x2, y2 in cajas:
        w, h = x2 - x1, y2 - y1
        a = (int((x1 - margen * w) * k), int((y1 - margen * h) * k))
        b = (int((x2 + margen * w) * k) + 1, int((y2 + margen * h) * k) + 1)
        cv2.rectangle(m, a, b, 0, -1)
    return m


class EstimadorEgo:
    def __init__(self, ancho_ref=1920, ratio=0.75, umbral_px=1.0, min_inliers=40, max_ida_vuelta_px=1.0, n_features=4000):
        self.ancho_ref, self.ratio, self.umbral_px = ancho_ref, ratio, umbral_px
        self.min_inliers, self.max_iv = min_inliers, max_ida_vuelta_px
        self.sift = cv2.SIFT_create(nfeatures=n_features)
        self.bf = cv2.BFMatcher(cv2.NORM_L2)

    def _h(self, kp0, d0, kp1, d1):
        if d0 is None or d1 is None or len(kp0) < 8 or len(kp1) < 8:
            return None, 0, np.inf
        pares = [m for m, n in (x for x in self.bf.knnMatch(d0, d1, k=2) if len(x) == 2) if m.distance < self.ratio * n.distance]
        if len(pares) < 8:
            return None, 0, np.inf
        p0 = np.float32([kp0[m.queryIdx].pt for m in pares])
        p1 = np.float32([kp1[m.trainIdx].pt for m in pares])
        H, inl = cv2.findHomography(p0, p1, cv2.USAC_MAGSAC, self.umbral_px)
        if H is None:
            return None, 0, np.inf
        inl = inl.ravel().astype(bool)
        res = np.linalg.norm(_warp(H, p0[inl]) - p1[inl], axis=1)
        return H, int(inl.sum()), float(np.median(res)) if len(res) else np.inf

    def serie(self, frames_bgr, cajas_por_frame):
        """frames_bgr: iterable de (frame, imagen). cajas_por_frame(f) → Mx4 xyxy originales a enmascarar."""
        filas, prev = [], None
        for f, img in frames_bgr:
            H0, W0 = img.shape[:2]
            k = self.ancho_ref / W0
            gris = cv2.cvtColor(cv2.resize(img, (self.ancho_ref, int(round(H0 * k))), interpolation=cv2.INTER_AREA),
                                cv2.COLOR_BGR2GRAY)
            mask = _mascara(gris.shape, cajas_por_frame(f), k)
            kp, d = self.sift.detectAndCompute(gris, mask)
            fila = dict(frame=f, n_inliers=0, ida_vuelta_px=np.nan, H_ok=True, H_resid_px=0.0, _H=np.eye(3), _k=k, _W=W0, _Hh=H0)
            if prev is not None:
                Hf, n, resid = self._h(prev[0], prev[1], kp, d)
                Hb, _, _ = self._h(kp, d, prev[0], prev[1])
                ok = Hf is not None and Hb is not None and n >= self.min_inliers
                iv = np.inf
                if ok:
                    g = _rejilla(*gris.shape[::-1])
                    iv = float(np.linalg.norm(_warp(Hb @ Hf, g) - g, axis=1).mean())
                    ok = iv <= self.max_iv
                fila.update(n_inliers=n, ida_vuelta_px=iv, H_ok=bool(ok),
                            H_resid_px=resid * ANCHO_METRICA / self.ancho_ref if ok else np.nan,
                            _H=_escalar_H(Hf, k) if ok else np.eye(3))
            filas.append(fila)
            prev = (kp, d)
        return filas


def covariables(filas, fps):
    """Añade ego_px, ego_rot_deg, ego_scale y ego_px_1s (todo a ANCHO_METRICA px). Devuelve DataFrame."""
    out = []
    ventana = max(1, int(round(fps)))
    Hs = [r["_H"] for r in filas]
    for i, r in enumerate(filas):
        k = ANCHO_METRICA / r["_W"]
        w, h = ANCHO_METRICA, r["_Hh"] * k
        g = _rejilla(w, h)
        H960 = _escalar_H(r["_H"], 1 / k)
        A = H960[:2, :2] / H960[2, 2]
        acum = np.eye(3)
        valido = True
        for j in range(max(0, i - ventana + 1), i + 1):
            valido &= filas[j]["H_ok"] or j == 0
            acum = _escalar_H(Hs[j], 1 / k) @ acum
        d = dict(frame=r["frame"], **{c: v for c, v in zip(H_COLS, r["_H"].ravel())},
                 n_inliers=r["n_inliers"], ida_vuelta_px=r["ida_vuelta_px"], H_ok=r["H_ok"],
                 ego_px=float(np.linalg.norm(_warp(H960, g) - g, axis=1).mean()) if r["H_ok"] else np.nan,
                 ego_rot_deg=float(np.degrees(np.arctan2(A[1, 0], A[0, 0]))) if r["H_ok"] else np.nan,
                 ego_scale=float(np.sqrt(abs(np.linalg.det(A)))) if r["H_ok"] else np.nan,
                 H_resid_px=r["H_resid_px"],
                 ego_px_1s=float(np.linalg.norm(_warp(acum, g) - g, axis=1).mean()) if valido else np.nan)
        out.append(d)
    return pd.DataFrame(out)


def calcular(sec, cache_dets=None, rehacer=False, **kw):
    out = ruta_cache(sec)
    if out.exists() and not rehacer:
        print(f"[ego] {sec.nombre}: caché existente ({out})")
        return out
    gt = leer_gt(sec.gt) if sec.gt else None

    def cajas(f):
        c = []
        if cache_dets is not None:
            c.append(cache_dets.por_frame(f)[:, :4])
        if gt is not None and len(gt):
            g = gt[gt.frame == f]
            c.append(np.c_[g.x, g.y, g.x + g.w, g.y + g.h])
        return np.vstack(c) if c else np.zeros((0, 4))

    a, b = rango_frames(sec)
    filas = EstimadorEgo(**kw).serie(leer_frames(sec.video, a, b), cajas)
    df = covariables(filas, fps_de(sec))
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"[ego] {sec.nombre}: {len(df)} frames, H no fiable en {100 * (1 - df.H_ok.mean()):.1f} % → {out}")
    return out


def leer(ruta):
    return pd.read_csv(ruta)


def H_de(df_ego):
    """{frame: H (3×3, px originales, f-1 → f)}; None si la H de ese frame no es fiable."""
    return {int(r.frame): (np.array([getattr(r, c) for c in H_COLS]).reshape(3, 3) if r.H_ok else None)
            for r in df_ego.itertuples()}


def bins_ego(df_ego, fps, umbrales=(0.5, 3.0), suavizado_s=0.5):
    """Etiqueta por frame: 'estacionario' | 'suave' | 'rapido' | 'H_no_fiable'.
    Usa ego_px suavizado con una mediana centrada de `suavizado_s` (los umbrales son los de `tipo_toma` de la v13)."""
    v = df_ego.set_index("frame")["ego_px"]
    n = max(1, int(round(suavizado_s * fps)))
    s = v.rolling(n, center=True, min_periods=1).median()
    lab = pd.Series("rapido", index=v.index)
    lab[s < umbrales[1]] = "suave"
    lab[s < umbrales[0]] = "estacionario"
    lab[~df_ego.set_index("frame")["H_ok"].astype(bool)] = "H_no_fiable"
    return lab
