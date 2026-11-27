"""Figura cualitativa: mismo vehículo, mismos frames, propio_kf contra BoT-SORT (salidas de test de la v1)."""
import sys, colorsys, cv2, numpy as np, pandas as pd
B = "/Users/alex/Documents/ByteTracker"
NOM = {-1: "?", 0: "car", 1: "truck", 2: "van", 3: "bus", 4: "freight"}
cols = ["frame","id","x","y","w","h","conf","cls","a","b"]

def color(i):
    r, g, b = colorsys.hsv_to_rgb((i * 0.61803) % 1, 0.85, 1.0); return int(b*255), int(g*255), int(r*255)

def panel(seq, trk, f, cx, cy, lado, gt_box):
    im = cv2.imread(f"{B}/datos/UAVDT/UAV-benchmark-M/{seq}/img{f:06d}.jpg")
    x0, y0 = int(max(0, cx - lado/2)), int(max(0, cy - lado/2)); x1, y1 = x0 + lado, y0 + lado
    p = pd.read_csv(f"{B}/benchmark/runs/v1/{trk}/{seq}.txt", header=None, names=cols)
    c = im[y0:y1, x0:x1].copy(); k = 300 / c.shape[1]; c = cv2.resize(c, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    gx, gy, gw, gh = gt_box
    cv2.rectangle(c, (int((gx-x0)*k), int((gy-y0)*k)), (int((gx+gw-x0)*k), int((gy+gh-y0)*k)), (255,255,255), 1, cv2.LINE_AA)
    for r in p[p.frame == f].itertuples():
        a = (int((r.x-x0)*k), int((r.y-y0)*k)); b = (int((r.x+r.w-x0)*k), int((r.y+r.h-y0)*k))
        if b[0] < 0 or b[1] < 0 or a[0] > c.shape[1] or a[1] > c.shape[0]: continue
        col = color(int(r.id)); cv2.rectangle(c, a, b, col, 2, cv2.LINE_AA)
        t = f"ID {int(r.id)} {NOM.get(int(r.cls), r.cls)}"
        cv2.rectangle(c, (a[0], a[1]-18), (a[0]+9*len(t), a[1]), col, -1)
        cv2.putText(c, t, (a[0]+2, a[1]-5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,0,0), 1, cv2.LINE_AA)
    cv2.putText(c, f"frame {f}", (6, c.shape[0]-8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2, cv2.LINE_AA)
    cv2.putText(c, f"frame {f}", (6, c.shape[0]-8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 1, cv2.LINE_AA)
    return c

def figura(seq, gid, frames, salida, lado=110):
    g = pd.read_csv(f"{B}/datos/UAVDT/gt_benchmark/{seq}/gt.txt", header=None, names=cols[:9]); g = g[(g.cls == 1) & (g.id == gid)]
    filas = []
    for trk, nom in (("propio_kf", "propio_kf"), ("botsort", "BoT-SORT")):
        ps = []
        for f in frames:
            r = g[g.frame == f].iloc[0]
            ps.append(panel(seq, trk, f, r.x + r.w/2, r.y + r.h/2, lado, (r.x, r.y, r.w, r.h)))
        fila = np.hstack([np.pad(q, ((4,4),(4,4),(0,0)), constant_values=250) for q in ps])
        tit = np.full((30, fila.shape[1], 3), 250, np.uint8)
        cv2.putText(tit, nom, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (30,30,30), 2, cv2.LINE_AA)
        filas += [tit, fila]
    cv2.imwrite(salida, np.vstack(filas)); print(salida)

if __name__ == "__main__":
    seq, gid, salida = sys.argv[1], int(sys.argv[2]), sys.argv[4]
    figura(seq, gid, [int(f) for f in sys.argv[3].split(",")], salida, int(sys.argv[5]) if len(sys.argv) > 5 else 110)
