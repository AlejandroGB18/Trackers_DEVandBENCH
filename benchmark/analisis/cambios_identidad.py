"""Cambios de identidad por GT id (emparejamiento por frame, IoU >= 0.5, húngaro). Solo para ilustrar resultados de test."""
import sys, numpy as np, pandas as pd, yaml
from scipy.optimize import linear_sum_assignment
B = "/Users/alex/Documents/ByteTracker"
man = yaml.safe_load(open(f"{B}/benchmark/secuencias.yaml"))
secs = {s["nombre"]: s for s in man["secuencias"] if s["split"] == "test"}
cols = ["frame","id","x","y","w","h","conf","cls","a","b"]

def iou(a, b):
    ax2, ay2 = a[:,0]+a[:,2], a[:,1]+a[:,3]; bx2, by2 = b[:,0]+b[:,2], b[:,1]+b[:,3]
    iw = np.clip(np.minimum(ax2[:,None], bx2[None]) - np.maximum(a[:,0][:,None], b[:,0][None]), 0, None)
    ih = np.clip(np.minimum(ay2[:,None], by2[None]) - np.maximum(a[:,1][:,None], b[:,1][None]), 0, None)
    i = iw*ih; return i / (a[:,2]*a[:,3])[:,None] + 0 if False else i / ((a[:,2]*a[:,3])[:,None] + (b[:,2]*b[:,3])[None] - i)

def switches(seq, trk):
    s = secs[seq]; g = pd.read_csv(f"{B}/datos/{s['gt']}", header=None, names=cols[:9]); g = g[g.cls == 1]
    fr = set(range(s["gt_frames"]["inicio"], s["gt_frames"]["fin"]+1)) - set(s["gt_frames"].get("excluir", []))
    p = pd.read_csv(f"{B}/benchmark/runs/v1/{trk}/{seq}.txt", header=None, names=cols)
    gp, pp = dict(tuple(g.groupby("frame"))), dict(tuple(p.groupby("frame")))
    last, ev = {}, []
    for f in sorted(fr):
        if f not in gp or f not in pp: continue
        a, b = gp[f], pp[f]
        m = iou(a[["x","y","w","h"]].values, b[["x","y","w","h"]].values)
        r, c = linear_sum_assignment(-m)
        for i, j in zip(r, c):
            if m[i, j] < 0.5: continue
            gid, pid = int(a.id.iloc[i]), int(b.id.iloc[j])
            if gid in last and last[gid][0] != pid:
                ev.append(dict(seq=seq, trk=trk, frame=f, gt=gid, viejo=last[gid][0], nuevo=pid, hueco=f-last[gid][1]-1))
            last[gid] = (pid, f)
    cls = p.groupby("id").cls.agg(lambda v: v.mode().iloc[0])
    nace = p.groupby("id").frame.min()
    e = pd.DataFrame(ev)
    if len(e):
        e["cls_viejo"], e["cls_nuevo"] = e.viejo.map(cls), e.nuevo.map(cls)
        e["nuevo_nace_en"] = e.nuevo.map(nace)
    return e

if __name__ == "__main__":
    out = pd.concat([switches(s, t) for s in sorted(secs) for t in ("propio_kf", "botsort", "bytetrack", "ucmc_grupo_train")])
    out.to_csv(sys.argv[1], index=False); print(out.groupby("trk").size())
