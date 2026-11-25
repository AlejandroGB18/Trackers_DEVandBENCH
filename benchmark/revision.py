"""
revision.py — Revisión humana del movimiento real, por track (D27)
==================================================================

Flujo (solo secuencias de TEST):
    bench.py moving   --split test      → moving_auto.csv (propuesta por frame, gt.py)
    bench.py revisar  --split test      → revision/<seq>.html + revision/tracks_<seq>.csv
    (una persona abre cada .html, decide por track y exporta decisiones_<seq>.csv)
    bench.py aplicar-revision --split test --decisiones CARPETA
                                        → moving.csv (el que usa la evaluación) + acuerdo.csv + calibracion.csv

Qué se revisa: cada track del GT se clasifica con la propuesta automática
    dudoso   ≥ 20 % de sus frames sin decisión (-1)
    cambio   tiene tramos en movimiento y quietos (cada uno ≥ 10 % de sus frames): arranca o frena
    seguro   el resto (casi todo 1 o casi todo 0)
y se revisan TODOS los dudosos y cambios, más una muestra aleatoria (semilla fija) del 10 % de los seguros, que mide
cuánto se equivoca la propuesta.

Decisiones por track (teclas en la página):
    M  se mueve todo el track          → moving = 1 en todos sus frames
    Q  quieto todo el track            → 0
    A  la propuesta automática está bien (incluye los cambios de estado tal como los marca) → la de moving_auto
    D  no se puede decidir             → -1 (distractor, D13)
Los tracks no revisados conservan la propuesta automática.

Calibración (D27): con las decisiones M/Q (y A = la mayoría automática) se cuenta, para una rejilla de umbrales
(rel_mov, rel_est), cuántos tracks revisados coinciden. Sirve para elegir umbrales ANTES de ver los trackers.
"""
import base64
import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from comunes import _imagenes, leer_frames

UMBRAL_DUDOSO, UMBRAL_CAMBIO, FRACCION_SEGUROS, SEMILLA = 0.20, 0.10, 0.10, 0
REJILLA_MOV, REJILLA_EST = (0.20, 0.25, 0.30, 0.35, 0.40), (0.05, 0.10, 0.15)


def dir_revision(sec):
    return Path(sec.gt).parent / "revision"


# ======================================================================
# Qué tracks revisar
# ======================================================================
def clasificar_tracks(moving):
    filas = []
    for tid, t in moving.groupby("id"):
        n = len(t)
        f1, f0, fd = (t.moving == 1).mean(), (t.moving == 0).mean(), (t.moving == -1).mean()
        if fd >= UMBRAL_DUDOSO:
            cat = "dudoso"
        elif f1 >= UMBRAL_CAMBIO and f0 >= UMBRAL_CAMBIO:
            cat = "cambio"
        else:
            cat = "seguro"
        filas.append(dict(id=int(tid), frames=n, inicio=int(t.frame.min()), fin=int(t.frame.max()),
                          frac_mov=round(f1, 3), frac_quieto=round(f0, 3), frac_dudoso=round(fd, 3),
                          categoria=cat, mayoria_auto=1 if f1 >= f0 else 0))
    return pd.DataFrame(filas)


def elegir(tracks, semilla=SEMILLA):
    seg = tracks[tracks.categoria == "seguro"]
    k = int(np.ceil(FRACCION_SEGUROS * len(seg))) if len(seg) else 0
    muestra = seg.sample(n=k, random_state=semilla) if k else seg.iloc[:0]
    sel = pd.concat([tracks[tracks.categoria != "seguro"], muestra])
    return tracks.assign(revisar=tracks.id.isin(sel.id), muestra_seguros=tracks.id.isin(muestra.id))


# ======================================================================
# Página
# ======================================================================
def _leer_frame(ruta, f):
    if Path(ruta).is_dir():
        return cv2.imread(_imagenes(str(ruta))[f - 1])
    return next(leer_frames(ruta, f, f))[1]


def _b64(img, calidad=80):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return base64.b64encode(buf.tobytes()).decode()


def _figura(sec, g, m, C, seg, ancho=640):
    """Fondo = frame central del track; trayectoria del punto de apoyo llevada a ese frame con la H de referencia."""
    from gt import _punto
    g = g.sort_values("frame")
    ref = int(g.frame.iloc[len(g) // 2])
    img = _leer_frame(sec.video, ref)
    k = ancho / img.shape[1]
    img = cv2.resize(img, (ancho, int(img.shape[0] * k)))
    P = _punto(g, sec.toma or "cenital")
    lab = g.frame.map(m.set_index("frame").moving).fillna(-1).astype(int).to_numpy()
    pts = []
    for f, p, l in zip(g.frame.to_numpy(), P, lab):
        f = int(f)
        if f in C and ref in C and seg[f] == seg[ref]:
            q = C[ref] @ np.linalg.inv(C[f]) @ np.array([p[0], p[1], 1.0])
            pts.append((q[:2] / q[2] * k, l))
    col = {1: (60, 200, 60), 0: (230, 140, 40), -1: (160, 160, 160)}
    for (a, la), (b, _) in zip(pts[:-1], pts[1:]):
        cv2.line(img, tuple(np.int32(a)), tuple(np.int32(b)), col[la], 2, cv2.LINE_AA)
    if pts:
        cv2.circle(img, tuple(np.int32(pts[0][0])), 5, (255, 255, 255), -1)
        cv2.circle(img, tuple(np.int32(pts[-1][0])), 5, (0, 0, 255), -1)
    r = g[g.frame == ref].iloc[0]
    cv2.rectangle(img, (int(r.x * k), int(r.y * k)), (int((r.x + r.w) * k), int((r.y + r.h) * k)), (0, 255, 255), 1)
    desp = float(np.linalg.norm(pts[-1][0] - pts[0][0]) / k) if len(pts) > 1 else 0.0
    return img, desp


def _recortes(sec, g, alto=110):
    out = []
    g = g.sort_values("frame")
    for i in (0, len(g) // 2, len(g) - 1):
        r = g.iloc[i]
        img = _leer_frame(sec.video, int(r.frame))
        m = max(r.w, r.h) * 1.2
        x1, y1 = int(max(0, r.x - m)), int(max(0, r.y - m))
        x2, y2 = int(min(img.shape[1], r.x + r.w + m)), int(min(img.shape[0], r.y + r.h + m))
        c = img[y1:y2, x1:x2].copy()
        cv2.rectangle(c, (int(r.x - x1), int(r.y - y1)), (int(r.x + r.w - x1), int(r.y + r.h - y1)), (0, 255, 255), 1)
        out.append((int(r.frame), cv2.resize(c, (max(1, int(c.shape[1] * alto / max(1, c.shape[0]))), alto))))
    return out


def generar(sec, gt, moving, df_ego, fps):
    """Escribe revision/<seq>.html y revision/tracks_<seq>.csv. Devuelve la tabla de tracks."""
    from gt import _cadena_H
    d = dir_revision(sec)
    d.mkdir(parents=True, exist_ok=True)
    tracks = elegir(clasificar_tracks(moving))
    tracks.to_csv(d / f"tracks_{sec.nombre}.csv", index=False)
    C, seg = _cadena_H(df_ego)
    g_all = gt[gt.clase == 1]
    items = []
    orden = {"cambio": 0, "dudoso": 1, "seguro": 2}
    for t in sorted(tracks[tracks.revisar].itertuples(), key=lambda t: (orden[t.categoria], t.id)):
        g = g_all[g_all.id == t.id]
        m = moving[moving.id == t.id]
        fig, desp = _figura(sec, g, m, C, seg)
        L = float(np.median(np.maximum(g.w, g.h)))
        items.append(dict(id=t.id, categoria=t.categoria, inicio=t.inicio, fin=t.fin,
                          duracion_s=round(t.frames / fps, 1), mov=t.frac_mov, quieto=t.frac_quieto,
                          dudoso=t.frac_dudoso, desp_L=round(desp / max(L, 1), 1),
                          fig=_b64(fig), recortes=[dict(f=f, img=_b64(c)) for f, c in _recortes(sec, g)]))
    html = PLANTILLA.replace("__SEQ__", sec.nombre).replace("__DATOS__", json.dumps(items))
    (d / f"{sec.nombre}.html").write_text(html, encoding="utf-8")
    n = tracks.revisar.sum()
    print(f"[revisar] {sec.nombre}: {len(tracks)} tracks, {n} a revisar "
          f"({(tracks.categoria == 'cambio').sum()} cambios, {(tracks.categoria == 'dudoso').sum()} dudosos, "
          f"{tracks.muestra_seguros.sum()} seguros de muestra) → {d / (sec.nombre + '.html')}")
    return tracks


# ======================================================================
# Aplicar decisiones
# ======================================================================
def leer_decisiones(carpeta, secuencia):
    p = Path(carpeta) / f"decisiones_{secuencia}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    d["decision"] = d.decision.str.upper().str.strip()
    malas = set(d.decision) - set("MQAD")
    if malas:
        raise ValueError(f"{p}: decisiones desconocidas {malas} (válidas: M, Q, A, D)")
    return d[["id", "decision"]]


def aplicar(moving_auto, tracks, decisiones):
    """moving final por frame + tabla de acuerdo en la muestra de seguros."""
    m = moving_auto[["frame", "id", "moving", "d_px", "L_px"]].copy()
    dec = dict(zip(decisiones.id, decisiones.decision)) if decisiones is not None else {}
    nuevo = m.moving.copy()
    for tid, dcs in dec.items():
        sel = m.id == tid
        if dcs == "M":
            nuevo[sel] = 1
        elif dcs == "Q":
            nuevo[sel] = 0
        elif dcs == "D":
            nuevo[sel] = -1
    m["moving"] = nuevo
    t = tracks.merge(pd.DataFrame(dict(id=list(dec), decision=list(dec.values()))), on="id", how="left")
    faltan = t[t.revisar & t.decision.isna()]
    return m, t, faltan


def acuerdo(t):
    """En la muestra aleatoria de seguros: ¿la mayoría automática coincide con la persona? (A cuenta como sí)."""
    s = t[t.muestra_seguros & t.decision.notna()]
    if not len(s):
        return dict(n=0, acuerdo=np.nan)
    humano = s.decision.map({"M": 1, "Q": 0}).where(s.decision.isin(["M", "Q"]), s.mayoria_auto)
    ok = (s.decision == "A") | (humano == s.mayoria_auto)
    ok = ok[s.decision != "D"]
    return dict(n=int(len(ok)), acuerdo=float(ok.mean()) if len(ok) else np.nan, n_indecidibles=int((s.decision == "D").sum()))


def calibracion(moving_auto, t, min_px):
    """Acuerdo por track (mayoría) entre la regla con otros umbrales y las decisiones humanas M/Q/A."""
    ref = t[t.decision.isin(["M", "Q", "A"])].copy()
    if not len(ref):
        return pd.DataFrame()
    ref["humano"] = ref.decision.map({"M": 1, "Q": 0}).fillna(ref.mayoria_auto).astype(int)
    m = moving_auto[moving_auto.id.isin(ref.id)]
    filas = []
    for rm in REJILLA_MOV:
        for re_ in REJILLA_EST:
            lab = np.where(m.d_px.isna(), -1, np.where(m.d_px >= np.maximum(rm * m.L_px, min_px), 1,
                                                       np.where(m.d_px <= re_ * m.L_px, 0, -1)))
            x = m.assign(l=lab)
            may = x.groupby("id").l.agg(lambda v: int((v == 1).sum() >= (v == 0).sum()))
            r = ref.set_index("id").humano
            filas.append(dict(rel_mov=rm, rel_est=re_, tracks=len(r), acuerdo=float((may.reindex(r.index) == r).mean()),
                              frac_frames_dudosos=float((lab == -1).mean())))
    return pd.DataFrame(filas)


PLANTILLA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Revisión __SEQ__</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--card:#fff;--bd:#e7e5e4;--ac:#2563eb;--ok:#16a34a}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--bd:#44403c;--ac:#60a5fa;--ok:#4ade80}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--bd);padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;z-index:2}
h1{font-size:16px;margin:0}.mut{color:var(--mut)}button{font:inherit;padding:6px 12px;border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
main{max-width:980px;margin:0 auto;padding:16px}.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px}
.fig{width:100%;height:auto;border-radius:6px}.rec{display:flex;gap:8px;margin:10px 0;flex-wrap:wrap}.rec figure{margin:0}.rec figcaption{font-size:12px;color:var(--mut)}
.dec{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.dec button.on{outline:2px solid var(--ac);font-weight:600}
.ley span{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px}kbd{border:1px solid var(--bd);border-radius:4px;padding:0 4px;font-size:12px}
.barra{height:6px;background:var(--bd);border-radius:3px;flex:1;min-width:120px}.barra i{display:block;height:100%;background:var(--ok);border-radius:3px}
</style></head><body>
<header><h1>Revisión de movimiento real · __SEQ__</h1><span id="pos" class="mut"></span>
<div class="barra"><i id="prog" style="width:0"></i></div>
<button id="exp">Exportar decisiones</button></header>
<main><div id="card" class="card"></div>
<p class="mut">Teclas: <kbd>M</kbd> se mueve todo · <kbd>Q</kbd> quieto todo · <kbd>A</kbd> la propuesta está bien ·
<kbd>D</kbd> no se puede decidir · <kbd>←</kbd>/<kbd>→</kbd> anterior/siguiente. Las decisiones se guardan en este navegador;
al terminar, <b>exporta</b> el CSV.</p>
<p class="mut ley">Trayectoria estabilizada sobre el frame central:<span style="background:#3cc83c"></span>en movimiento
<span style="background:#288ce6"></span>quieto<span style="background:#a0a0a0"></span>sin decisión · punto blanco = inicio, rojo = fin.</p></main>
<script>
const SEQ="__SEQ__", T=__DATOS__, KEY="revision_"+SEQ;
let dec={}; try{dec=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
let i=0; const N=T.length;
const NOM={M:"Se mueve",Q:"Quieto",A:"Propuesta OK",D:"No se puede"};
function guardar(){try{localStorage.setItem(KEY,JSON.stringify(dec))}catch(e){}}
function pinta(){
 if(!N){document.getElementById("card").innerHTML="<p>No hay tracks que revisar en esta secuencia.</p>";return}
 const t=T[i], d=dec[t.id]||"";
 const cat={cambio:"Cambia de estado",dudoso:"Dudoso",seguro:"Seguro (muestra aleatoria)"}[t.categoria];
 document.getElementById("pos").textContent=`${i+1} / ${N} · ${Object.keys(dec).length} decididos`;
 document.getElementById("prog").style.width=(100*Object.keys(dec).length/N)+"%";
 document.getElementById("card").innerHTML=`
 <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px"><b>Track ${t.id} · ${cat}</b>
 <span class="mut">frames ${t.inicio}–${t.fin} (${t.duracion_s} s) · desplazamiento ${t.desp_L} largos ·
 propuesta: ${Math.round(100*t.mov)}% mov, ${Math.round(100*t.quieto)}% quieto, ${Math.round(100*t.dudoso)}% sin decisión</span></div>
 <img class="fig" alt="Trayectoria del track ${t.id}" src="data:image/jpeg;base64,${t.fig}">
 <div class="rec">${t.recortes.map(r=>`<figure><img alt="frame ${r.f}" src="data:image/jpeg;base64,${r.img}"><figcaption>frame ${r.f}</figcaption></figure>`).join("")}</div>
 <div class="dec">${["M","Q","A","D"].map(k=>`<button data-k="${k}" class="${d===k?"on":""}">${k} · ${NOM[k]}</button>`).join("")}</div>`;
 document.querySelectorAll(".dec button").forEach(b=>b.onclick=()=>decide(b.dataset.k));
}
function decide(k){dec[T[i].id]=k;guardar();if(i<N-1)i++;pinta()}
document.addEventListener("keydown",e=>{const k=e.key.toUpperCase();
 if("MQAD".includes(k)&&k.length===1)decide(k);else if(e.key==="ArrowRight"&&i<N-1){i++;pinta()}else if(e.key==="ArrowLeft"&&i>0){i--;pinta()}});
document.getElementById("exp").onclick=()=>{
 const filas=["id,decision,categoria"].concat(T.filter(t=>dec[t.id]).map(t=>`${t.id},${dec[t.id]},${t.categoria}`));
 const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([filas.join("\n")+"\n"],{type:"text/csv"}));
 a.download=`decisiones_${SEQ}.csv`;a.click();
 if(Object.keys(dec).length<N)alert(`Faltan ${N-Object.keys(dec).length} tracks por decidir (se exportan los decididos).`)};
pinta();
</script></body></html>"""
