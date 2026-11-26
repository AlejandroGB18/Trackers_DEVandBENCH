"""
gt.py — Ground truth: carga, frames anotados y etiqueta `moving`
=================================================================

Formato de GT (el de MOTChallenge y el export "MOT 1.1" de CVAT), frames del VIDEO, base 1:
    frame, id, x, y, w, h, considerar, clase, visibilidad
- `considerar` = 0 → la caja se quita del GT (no cuenta como FN), pero la predicción que la cubra cuenta como FP
  (regla MOTChallenge). Para zonas donde no se quiere castigar nada se usa una REGIÓN IGNORADA.
- Las clases las define el manifiesto (`evaluacion`): evaluadas (p. ej. vehicle), ignoradas (regiones: una predicción
  con ≥ 50 % de su área dentro se descarta, regla del toolkit de VisDrone) y distractoras (una predicción emparejada
  con ellas se descarta, regla MOT16/TrackEval).

`moving` (frame, id, moving) con moving ∈ {1 = se mueve, 0 = quieto, -1 = dudoso}:
- Se DERIVA del GT con la H de referencia de ego.py (no con la de los trackers) y luego se REVISA a mano:
  `derivar_moving` produce la propuesta y `lista_revision` los casos a revisar (dudosos y cambios de estado).
- Criterio semántico (no los umbrales del decisor, para no premiar su configuración): desplazamiento estabilizado
  del punto de apoyo en una ventana CENTRADA de 1 s, comparado con el lado mayor de la caja (≈ largo del vehículo):
      moving  si d ≥ 0.30 · L  (≈ 1.35 m/s para un auto de 4.5 m) y d ≥ 3 px a 960 de ancho
      quieto  si d ≤ 0.10 · L
      dudoso  en medio, si la ventana cruza una H no fiable o si el track dura menos de media ventana.
"""
import numpy as np
import pandas as pd

from comunes import leer_gt


def frames_anotados(sec, gt=None):
    """Frames que se evalúan. Con `gt_frames` {inicio, fin, paso} explícito; si no, todos los frames entre el primero
    y el último del GT (paso 1). Ojo: los frames anotados SIN objetos solo existen si se declaran aquí."""
    if sec.gt_frames:
        g = sec.gt_frames
        f = np.arange(int(g["inicio"]), int(g["fin"]) + 1, int(g.get("paso", 1)))
        return f[~np.isin(f, g.get("excluir", []))]           # D33: frames con GT roto, fuera de la evaluación
    gt = gt if gt is not None else leer_gt(sec.gt)
    if len(gt) == 0:
        return np.zeros(0, int)
    return np.arange(int(gt.frame.min()), int(gt.frame.max()) + 1)


def _punto(g, toma):
    """Punto de apoyo: centro de la base (oblicua) o centro de la caja (cenital)."""
    cx = g.x + g.w / 2
    cy = g.y + g.h if toma == "oblicua" else g.y + g.h / 2
    return np.c_[cx, cy]


def _cadena_H(df_ego):
    """C[f]: mapa del primer frame del segmento al frame f; seg[f]: segmento (se corta cuando la H no es fiable)."""
    from ego import H_COLS
    C, seg, actual, s = {}, {}, np.eye(3), 0
    for r in df_ego.sort_values("frame").itertuples():
        if not r.H_ok:
            s += 1
            actual = np.eye(3)
        else:
            actual = np.array([getattr(r, c) for c in H_COLS]).reshape(3, 3) @ actual
        C[int(r.frame)], seg[int(r.frame)] = actual, s
    return C, seg


def _llevar(C, a, b, p):
    """Lleva el punto p del frame a al frame b (mismo segmento)."""
    M = C[b] @ np.linalg.inv(C[a])
    q = M @ np.array([p[0], p[1], 1.0])
    return q[:2] / q[2]


def derivar_moving(gt, df_ego, fps, ancho_video, toma="cenital", clases=None, ventana_s=1.0, rel_mov=0.30,
                   rel_est=0.10, min_px_960=3.0, suavizado=1):
    """Propuesta automática de `moving` para cada caja del GT. Devuelve DataFrame frame,id,moving,d_px,L_px,fuente."""
    C, seg = _cadena_H(df_ego)
    g = gt[gt.considerar != 0] if "considerar" in gt else gt
    if clases is not None:
        g = g[g.clase.isin(clases)]
    min_px = min_px_960 * ancho_video / 960.0
    medio = ventana_s * fps / 2
    filas = []
    for tid, tr in g.sort_values("frame").groupby("id"):
        fr = tr.frame.to_numpy()
        P = _punto(tr, toma)
        L = np.maximum(tr.w.to_numpy(), tr.h.to_numpy())

        def pos(i):                                    # mediana de vecinos para quitar el temblor de la caja
            return np.median(P[max(0, i - suavizado):i + suavizado + 1], axis=0)

        for i, t in enumerate(fr):
            ia = int(np.searchsorted(fr, t - medio))
            ib = int(np.searchsorted(fr, t + medio, side="right")) - 1
            a, b = int(fr[ia]), int(fr[ib])
            estado, d = -1, np.nan
            if b - a >= medio and a in C and b in C and seg[a] == seg[b]:
                d = float(np.linalg.norm(_llevar(C, a, b, pos(ia)) - pos(ib))) * (2 * medio / (b - a))
                if d >= max(rel_mov * L[i], min_px):
                    estado = 1
                elif d <= rel_est * L[i]:
                    estado = 0
            filas.append((int(t), int(tid), estado, d, float(L[i])))
    return pd.DataFrame(filas, columns=["frame", "id", "moving", "d_px", "L_px"]).assign(fuente="auto")


def lista_revision(moving):
    """Casos que una persona debe revisar en CVAT: tramos dudosos y cada cambio de estado de un track."""
    out = []
    for tid, tr in moving.sort_values("frame").groupby("id"):
        prev = None
        for r in tr.itertuples():
            if r.moving == -1 and prev != -1:
                out.append(dict(id=tid, frame=r.frame, motivo="dudoso"))
            elif prev is not None and r.moving != prev and r.moving != -1 and prev != -1:
                out.append(dict(id=tid, frame=r.frame, motivo=f"cambio {prev}→{r.moving}"))
            prev = r.moving
    return pd.DataFrame(out, columns=["id", "frame", "motivo"])


def cargar_moving(sec, gt=None, df_ego=None, ancho_video=None, fps=None, clases=None, umbrales=None):
    """El moving revisado si existe (`gt_moving`, o `moving.csv` junto al gt.txt, que escribe
    `bench.py aplicar-revision`); si no, la derivación automática (avisando)."""
    from pathlib import Path
    ruta = sec.gt_moving or (Path(sec.gt).with_name("moving.csv") if sec.gt else None)
    if ruta and Path(ruta).exists():
        m = pd.read_csv(ruta)
        return m[["frame", "id", "moving"]]
    if df_ego is None:
        return None
    print(f"[gt] {sec.nombre}: sin moving revisado; se usa la derivación AUTOMÁTICA (revisar antes de reportar)")
    return derivar_moving(gt, df_ego, fps, ancho_video, toma=sec.toma or "cenital", clases=clases,
                          **(umbrales or {}))[["frame", "id", "moving"]]
