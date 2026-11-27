"""
paralaje.py — ¿Cuánto movimiento real apaga el filtro de paralaje del decisor (P2)? Descriptivo, sobre un run ya hecho.

Cruza <seq>_lateral.csv (paralaje, en_movimiento) con el GT de movimiento revisado (moving.csv), emparejando cada
track con el GT por frame (IoU >= 0.5, húngaro).

Uso (desde benchmark/):
    python analisis/paralaje.py runs/v1 botsort propio_kf
"""
import sys

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import linear_sum_assignment

NOM = {0: "car", 1: "truck", 2: "van", 3: "bus", 4: "freight car", -1: "?"}
COLS = ["frame", "id", "x", "y", "w", "h", "conf", "cls", "a", "b"]


def iou(a, b):
    ax2, ay2 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx2, by2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.clip(np.minimum(ax2[:, None], bx2[None]) - np.maximum(a[:, 0][:, None], b[:, 0][None]), 0, None)
    ih = np.clip(np.minimum(ay2[:, None], by2[None]) - np.maximum(a[:, 1][:, None], b[:, 1][None]), 0, None)
    i = iw * ih
    return i / ((a[:, 2] * a[:, 3])[:, None] + (b[:, 2] * b[:, 3])[None] - i)


def cruzar(run, trk, manifiesto="secuencias.yaml", datos="../datos"):
    man = yaml.safe_load(open(manifiesto))
    filas = []
    for s in (s for s in man["secuencias"] if s["split"] == "test"):
        n = s["nombre"]
        p = pd.read_csv(f"{run}/{trk}/{n}.txt", header=None, names=COLS)
        x = p.merge(pd.read_csv(f"{run}/{trk}/{n}_lateral.csv"), on=["frame", "id"])
        g = pd.read_csv(f"{datos}/{s['gt']}", header=None, names=COLS[:9])
        g = g[g.cls == 1].merge(pd.read_csv(f"{datos}/UAVDT/gt_benchmark/{n}/moving.csv")[["frame", "id", "moving"]],
                                on=["frame", "id"], how="left")
        gp = dict(tuple(g.groupby("frame")))
        for f, xf in x.groupby("frame"):
            lab = np.full(len(xf), -9.0)
            if f in gp:
                gf = gp[f]
                m = iou(xf[["x", "y", "w", "h"]].values.astype(float), gf[["x", "y", "w", "h"]].values.astype(float))
                for i, j in zip(*linear_sum_assignment(-m)):
                    if m[i, j] >= 0.5:
                        lab[i] = gf.moving.iloc[j]
            filas.append(pd.DataFrame(dict(seq=n, clase=xf.cls.map(NOM).values, par=xf.paralaje.values,
                                           mov=xf.en_movimiento.values, gt_mov=lab)))
    return pd.concat(filas)


if __name__ == "__main__":
    run, trackers = sys.argv[1], sys.argv[2:] or ["botsort", "propio_kf"]
    for trk in trackers:
        d = cruzar(run, trk)
        z = d[(d.par == 1) & (d.gt_mov != -9)]
        movil = d[d.gt_mov == 1]
        print(f"{trk}: paralaje sobre vehículos del GT {len(z)} frames (GT móvil {(z.gt_mov == 1).mean():.0%}, "
              f"quieto {(z.gt_mov == 0).mean():.0%}); frames móviles apagados {int(movil.par.sum())} de {len(movil)} "
              f"({movil.par.mean():.2%})")
        for cl in (["van", "freight car"], ["car", "truck", "bus"]):
            v = movil[movil.clase.isin(cl)]
            print(f"   {'/'.join(cl)}: {len(v)} frames móviles; apagados por paralaje {v.par.mean():.1%}")
