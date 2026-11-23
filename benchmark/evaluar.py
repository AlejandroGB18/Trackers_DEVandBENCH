"""
evaluar.py — Evaluación con TrackEval + análisis propio del caso dron
======================================================================

Juez único: las métricas de TrackEval (`trackeval==1.3.0`: HOTA, CLEAR, Identity, Count) llamadas con datos que
preprocesamos aquí. No se usa su clase de dataset MOTChallenge porque solo admite `pedestrian` y no aplica la regla de
regiones ignoradas por área de VisDrone; el preprocesado de abajo replica la regla de distractores de MOTChallenge y
añade la de áreas ignoradas.

Preprocesado por frame anotado (en este orden):
  1. P2 ("e2e_moviles"): solo entran las predicciones con en_movimiento = 1.
  2. Se descartan las predicciones con ≥ `umbral_area_ignorada` de su área dentro de una región ignorada.
  3. Húngaro con IoU ≥ 0.5 entre predicciones y GT (evaluable + distractor); las emparejadas con un distractor se
     descartan.
  4. GT evaluable = considerar ≠ 0, clase evaluada y, según el protocolo, la etiqueta `moving`.

Protocolos (qué GT se evalúa y qué GT es distractor):
  todos        evaluable: todo el GT de clase evaluada                     distractor: clases distractoras
  moviles      evaluable: moving = 1     distractor: moving ∈ {0, -1}      (P1: ¿sigue bien lo que se mueve?)
  estaticos    evaluable: moving = 0     distractor: moving ∈ {1, -1}      (P1': ¿mantiene el ID de lo quieto?)
  e2e_moviles  evaluable: moving = 1     distractor: moving = -1; preds solo en_movimiento = 1   (P2: sistema completo)

Además de TrackEval:
  - HOTA/DetA/AssA e IDSW por bin de ego-movimiento (misma alineación global de HOTA; se agrega por frames del bin).
  - Decisor en_movimiento: P/R/F1 por frame, por track GT, latencias de encendido/apagado, parpadeo y paralaje.
  - Métricas sin GT de la v13, para validarlas contra las de GT.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

warnings.filterwarnings("ignore", category=RuntimeWarning)

ALFAS = np.arange(0.05, 0.99, 0.05)          # los 19 umbrales de HOTA (igual que TrackEval)
I_ALFA_05 = 9                                 # índice de α = 0.5
EPS = np.finfo("float").eps
PROTOCOLOS = ("todos", "moviles", "estaticos", "e2e_moviles")


# ======================================================================
# 1. Geometría
# ======================================================================
def _xyxy(df):
    return np.c_[df.x, df.y, df.x + df.w, df.y + df.h].astype(np.float64) if len(df) else np.zeros((0, 4))


def iou(a, b):
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + bb[None, :] - inter, EPS)


def frac_dentro(a, regiones):
    """Fracción del área de cada caja de `a` que cae dentro de cada región (N × M)."""
    if len(a) == 0 or len(regiones) == 0:
        return np.zeros((len(a), len(regiones)))
    x1 = np.maximum(a[:, None, 0], regiones[None, :, 0]); y1 = np.maximum(a[:, None, 1], regiones[None, :, 1])
    x2 = np.minimum(a[:, None, 2], regiones[None, :, 2]); y2 = np.minimum(a[:, None, 3], regiones[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    return inter / np.maximum(((a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]))[:, None], EPS)


# ======================================================================
# 2. Preprocesado → datos de TrackEval
# ======================================================================
def preparar(gt, pred, frames, cfg_eval, protocolo="todos", moving=None, lateral=None):
    """Construye el dict que consumen las métricas de TrackEval, más los IDs originales por frame.

    gt: DataFrame de gt.txt. pred: DataFrame MOT del tracker. frames: frames anotados (los únicos que se evalúan).
    moving: DataFrame frame,id,moving (requerido salvo en 'todos'). lateral: frame,id,en_movimiento (requerido en P2)."""
    if protocolo not in PROTOCOLOS:
        raise ValueError(f"Protocolo desconocido {protocolo}; opciones {PROTOCOLOS}")
    if protocolo != "todos" and moving is None:
        raise ValueError(f"El protocolo '{protocolo}' necesita la etiqueta GT moving")
    evaluadas = set(cfg_eval.get("clases_evaluadas", [1]))
    ignoradas = set(cfg_eval.get("clases_ignoradas", [0]))
    distractoras = set(cfg_eval.get("clases_distractoras", []))
    umbral_area = float(cfg_eval.get("umbral_area_ignorada", 0.5))

    gt = gt.copy()
    if "considerar" not in gt:
        gt["considerar"] = 1
    if moving is not None:
        gt = gt.merge(moving[["frame", "id", "moving"]], on=["frame", "id"], how="left")
        gt["moving"] = gt["moving"].fillna(-1).astype(int)
    else:
        gt["moving"] = -1
    pred = pred.copy()
    if protocolo == "e2e_moviles":
        if lateral is None:
            raise ValueError("El protocolo e2e_moviles necesita el archivo lateral (en_movimiento)")
        pred = pred.merge(lateral[["frame", "id", "en_movimiento"]], on=["frame", "id"], how="left")
        pred = pred[pred.en_movimiento.fillna(0).astype(int) == 1]

    gt_por_f = dict(tuple(gt.groupby("frame")))
    pr_por_f = dict(tuple(pred.groupby("frame")))
    vacio_gt, vacio_pr = gt.iloc[:0], pred.iloc[:0]
    ids_gt_t, ids_pr_t, sims = [], [], []
    n_desc_ign, n_desc_dis = 0, 0
    for f in frames:
        g = gt_por_f.get(f, vacio_gt)
        p = pr_por_f.get(f, vacio_pr)
        pb = _xyxy(p)
        # 2. regiones ignoradas (por área)
        reg = g[g.clase.isin(ignoradas)]
        keep = np.ones(len(p), bool)
        if len(reg) and len(p):
            keep = frac_dentro(pb, _xyxy(reg)).max(1) < umbral_area
        n_desc_ign += int((~keep).sum())
        p, pb = p[keep], pb[keep]
        # 4. GT evaluable / distractor según protocolo
        g = g[~g.clase.isin(ignoradas)]
        de_clase = g.clase.isin(evaluadas) & (g.considerar != 0)
        mv = g.moving.to_numpy()
        if protocolo == "todos":
            eval_m = de_clase.to_numpy(); dist_m = g.clase.isin(distractoras).to_numpy()
        elif protocolo in ("moviles", "e2e_moviles"):
            eval_m = de_clase.to_numpy() & (mv == 1)
            excl = (mv == -1) if protocolo == "e2e_moviles" else (mv != 1)
            dist_m = g.clase.isin(distractoras).to_numpy() | (de_clase.to_numpy() & excl)
        else:  # estaticos
            eval_m = de_clase.to_numpy() & (mv == 0)
            dist_m = g.clase.isin(distractoras).to_numpy() | (de_clase.to_numpy() & (mv != 0))
        # 3. predicciones emparejadas con distractores
        cand = eval_m | dist_m
        if cand.any() and len(p):
            s = iou(_xyxy(g[cand]), pb)
            s[s < 0.5 - EPS] = 0
            r, c = linear_sum_assignment(-s)
            ok = s[r, c] > EPS
            r, c = r[ok], c[ok]
            es_dist = dist_m[cand][r]
            quitar = c[es_dist]
            n_desc_dis += len(quitar)
            keep = np.ones(len(p), bool); keep[quitar] = False
            p, pb = p[keep], pb[keep]
        ge = g[eval_m]
        ids_gt_t.append(ge.id.to_numpy())
        ids_pr_t.append(p.id.to_numpy())
        sims.append(iou(_xyxy(ge), pb))

    # IDs contiguos (lo que exige TrackEval)
    u_gt = np.unique(np.concatenate(ids_gt_t)) if ids_gt_t else np.zeros(0, int)
    u_pr = np.unique(np.concatenate(ids_pr_t)) if ids_pr_t else np.zeros(0, int)
    m_gt = {v: i for i, v in enumerate(u_gt)}; m_pr = {v: i for i, v in enumerate(u_pr)}
    data = dict(num_timesteps=len(frames), num_gt_ids=len(u_gt), num_tracker_ids=len(u_pr),
                gt_ids=[np.array([m_gt[v] for v in a], int) for a in ids_gt_t],
                tracker_ids=[np.array([m_pr[v] for v in a], int) for a in ids_pr_t],
                similarity_scores=sims, num_gt_dets=int(sum(len(a) for a in ids_gt_t)),
                num_tracker_dets=int(sum(len(a) for a in ids_pr_t)), seq="seq")
    extra = dict(frames=np.asarray(frames), ids_gt_orig=ids_gt_t, ids_pr_orig=ids_pr_t,
                 descartadas_ignoradas=n_desc_ign, descartadas_distractor=n_desc_dis)
    return data, extra


# ======================================================================
# 3. TrackEval
# ======================================================================
def _metricas_te():
    from trackeval.metrics import CLEAR, HOTA, Count, Identity
    cfg = {"THRESHOLD": 0.5, "PRINT_CONFIG": False}
    return dict(HOTA=HOTA(), CLEAR=CLEAR(cfg), Identity=Identity(cfg), Count=Count())


_MET = None


def evaluar_datos(data):
    """{métrica: resultado de TrackEval} para una secuencia ya preparada."""
    global _MET
    if _MET is None:
        _MET = _metricas_te()
    return {k: m.eval_sequence(data) for k, m in _MET.items()}


def combinar(res_por_seq):
    """Combina como TrackEval (sumando conteos, no promediando HOTA)."""
    global _MET
    if _MET is None:
        _MET = _metricas_te()
    return {k: m.combine_sequences({s: r[k] for s, r in res_por_seq.items()}) for k, m in _MET.items()}


def resumen(res):
    h, c, i, n = res["HOTA"], res["CLEAR"], res["Identity"], res["Count"]
    return {"HOTA": 100 * h["HOTA"].mean(), "DetA": 100 * h["DetA"].mean(), "AssA": 100 * h["AssA"].mean(),
            "LocA": 100 * h["LocA"].mean(), "DetRe": 100 * h["DetRe"].mean(), "DetPr": 100 * h["DetPr"].mean(),
            "AssRe": 100 * h["AssRe"].mean(), "AssPr": 100 * h["AssPr"].mean(),
            "HOTA(0.5)": 100 * h["HOTA"][I_ALFA_05],
            "MOTA": 100 * c["MOTA"], "MOTP": 100 * c["MOTP"], "IDF1": 100 * i["IDF1"], "IDP": 100 * i["IDP"],
            "IDR": 100 * i["IDR"], "IDSW": int(c["IDSW"]), "Frag": int(c["Frag"]), "MT": int(c["MT"]),
            "PT": int(c["PT"]), "ML": int(c["ML"]), "FP": int(c["CLR_FP"]), "FN": int(c["CLR_FN"]),
            "IDs": int(n["IDs"]), "GT_IDs": int(n["GT_IDs"]), "GT_Dets": int(n["GT_Dets"])}


# ======================================================================
# 4. Emparejamientos por frame (replican TrackEval para poder estratificar)
# ======================================================================
def clear_por_frame(data, umbral=0.5):
    """Réplica del bucle de CLEAR de TrackEval. Devuelve por frame: tp, fn, fp, idsw y los pares (gt, pred)
    emparejados (índices contiguos). Los totales coinciden con TrackEval (se comprueba en las pruebas)."""
    ng = data["num_gt_ids"]
    prev_tr = np.full(ng, np.nan); prev_ts = np.full(ng, np.nan)
    out = []
    for gi, ti, s in zip(data["gt_ids"], data["tracker_ids"], data["similarity_scores"]):
        d = dict(tp=0, fn=len(gi), fp=len(ti), idsw=0, pares=[], idsw_gt=[])
        if len(gi) and len(ti):
            sc = (ti[None, :] == prev_ts[gi[:, None]]) * 1000 + s
            sc[s < umbral - EPS] = 0
            r, c = linear_sum_assignment(-sc)
            ok = sc[r, c] > EPS
            r, c = r[ok], c[ok]
            mg, mt = gi[r], ti[c]
            pm = prev_tr[mg]
            sw = ~np.isnan(pm) & (mt != pm)
            prev_tr[mg] = mt
            prev_ts[:] = np.nan; prev_ts[mg] = mt
            d.update(tp=len(r), fn=len(gi) - len(r), fp=len(ti) - len(r), idsw=int(sw.sum()),
                     pares=list(zip(mg.tolist(), mt.tolist())), idsw_gt=mg[sw].tolist())
        elif len(gi) == 0:
            pass
        else:
            prev_ts[:] = np.nan
        out.append(d)
    return out


def hota_por_bins(data, etiquetas):
    """HOTA/DetA/AssA por grupo de frames. `etiquetas`: una etiqueta por timestep (frame anotado).
    La alineación global (y por tanto A(c)) es la de toda la secuencia, como en HOTA; solo se agregan por bin los
    TP/FN/FP y la suma de A(c) de los TP del bin. Devuelve {bin: dict de sumas por α} (combinables entre secuencias)."""
    ng, nt = data["num_gt_ids"], data["num_tracker_ids"]
    etiquetas = list(etiquetas)
    bins = sorted(set(etiquetas))
    acc = {b: dict(TP=np.zeros(len(ALFAS)), FN=np.zeros(len(ALFAS)), FP=np.zeros(len(ALFAS)),
                   LocA=np.zeros(len(ALFAS)), AssSum=np.zeros(len(ALFAS)), n_frames=0, n_gt=0) for b in bins}
    if data["num_gt_dets"] == 0 or data["num_tracker_dets"] == 0:
        for gi, ti, b in zip(data["gt_ids"], data["tracker_ids"], etiquetas):
            acc[b]["FN"] += len(gi); acc[b]["FP"] += len(ti); acc[b]["n_frames"] += 1; acc[b]["n_gt"] += len(gi)
        return acc
    pot = np.zeros((ng, nt)); gc = np.zeros((ng, 1)); tc = np.zeros((1, nt))
    for gi, ti, s in zip(data["gt_ids"], data["tracker_ids"], data["similarity_scores"]):
        den = s.sum(0)[None, :] + s.sum(1)[:, None] - s
        si = np.zeros_like(s); m = den > 0 + EPS
        si[m] = s[m] / den[m]
        pot[gi[:, None], ti[None, :]] += si
        gc[gi] += 1; tc[0, ti] += 1
    ali = pot / (gc + tc - pot)
    mc = [np.zeros((ng, nt)) for _ in ALFAS]
    pares_por_t = []
    for gi, ti, s, b in zip(data["gt_ids"], data["tracker_ids"], data["similarity_scores"], etiquetas):
        acc[b]["n_frames"] += 1; acc[b]["n_gt"] += len(gi)
        pt = []
        if len(gi) == 0 or len(ti) == 0:
            acc[b]["FP"] += len(ti); acc[b]["FN"] += len(gi)
            pares_por_t.append(pt)
            continue
        r, c = linear_sum_assignment(-(ali[gi[:, None], ti[None, :]] * s))
        for a, al in enumerate(ALFAS):
            ok = s[r, c] >= al - EPS
            n = int(ok.sum())
            acc[b]["TP"][a] += n; acc[b]["FN"][a] += len(gi) - n; acc[b]["FP"][a] += len(ti) - n
            acc[b]["LocA"][a] += s[r[ok], c[ok]].sum()
            mc[a][gi[r[ok]], ti[c[ok]]] += 1
            pt.append((gi[r[ok]], ti[c[ok]]))
        pares_por_t.append(pt)
    for a in range(len(ALFAS)):
        A = mc[a] / np.maximum(1, gc + tc - mc[a])
        for (gi, ti, s, b), pt in zip(zip(data["gt_ids"], data["tracker_ids"], data["similarity_scores"], etiquetas),
                                      pares_por_t):
            if pt:
                g_, t_ = pt[a]
                acc[b]["AssSum"][a] += A[g_, t_].sum()
    return acc


def combinar_bins(lista):
    out = {}
    for acc in lista:
        for b, d in acc.items():
            if b not in out:
                out[b] = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in d.items()}
            else:
                for k, v in d.items():
                    out[b][k] = out[b][k] + v
    return out


def metricas_bin(d):
    TP, FN, FP = d["TP"], d["FN"], d["FP"]
    det = TP / np.maximum(1, TP + FN + FP)
    ass = d["AssSum"] / np.maximum(1, TP)
    return dict(n_frames=d["n_frames"], n_gt_dets=d["n_gt"], HOTA=100 * np.sqrt(det * ass).mean(),
                DetA=100 * det.mean(), AssA=100 * ass.mean(), LocA=100 * (d["LocA"] / np.maximum(1e-10, TP)).mean())


# ======================================================================
# 5. Decisor en_movimiento
# ======================================================================
def emparejar_original(data, extra):
    """Pares CLEAR (α = 0.5) con IDs ORIGINALES: DataFrame frame, gt_id, pred_id."""
    cl = clear_por_frame(data)
    out = []
    for t, (f, d, g0, p0) in enumerate(zip(extra["frames"], cl, extra["ids_gt_orig"], extra["ids_pr_orig"])):
        gi, ti = data["gt_ids"][t], data["tracker_ids"][t]
        inv_g = {int(c): int(o) for c, o in zip(gi, g0)}
        inv_p = {int(c): int(o) for c, o in zip(ti, p0)}
        for g, p in d["pares"]:
            out.append((int(f), inv_g[g], inv_p[p]))
    return pd.DataFrame(out, columns=["frame", "gt_id", "pred_id"]), cl


def evaluar_decisor(pares, moving, lateral, fps, bins=None):
    """Métricas del decisor sobre los TP del emparejamiento CLEAR. Excluye GT moving = -1 de la confusión."""
    j = pares.merge(moving.rename(columns={"id": "gt_id"}), on=["frame", "gt_id"], how="left") \
             .merge(lateral.rename(columns={"id": "pred_id"}), on=["frame", "pred_id"], how="left")
    j["moving"] = j["moving"].fillna(-1).astype(int)
    j["en_movimiento"] = j["en_movimiento"].fillna(0).astype(int)
    j["paralaje"] = j["paralaje"].fillna(0).astype(int)
    if bins is not None:
        j["bin"] = j.frame.map(bins).fillna("H_no_fiable")

    def conf(x):
        x = x[x.moving != -1]
        tp = int(((x.en_movimiento == 1) & (x.moving == 1)).sum()); fp = int(((x.en_movimiento == 1) & (x.moving == 0)).sum())
        fn = int(((x.en_movimiento == 0) & (x.moving == 1)).sum()); tn = int(((x.en_movimiento == 0) & (x.moving == 0)).sum())
        pr = tp / (tp + fp) if tp + fp else np.nan; re = tp / (tp + fn) if tp + fn else np.nan
        return dict(n=tp + fp + fn + tn, TP=tp, FP=fp, FN=fn, TN=tn, precision=pr, recall=re,
                    F1=2 * pr * re / (pr + re) if pr == pr and re == re and pr + re else np.nan,
                    especificidad=tn / (tn + fp) if tn + fp else np.nan,
                    paralaje_en_estaticos=float(x[x.moving == 0].paralaje.mean()) if (x.moving == 0).any() else np.nan,
                    paralaje_en_moviles=float(x[x.moving == 1].paralaje.mean()) if (x.moving == 1).any() else np.nan)

    por_frame = {"global": conf(j)}
    if bins is not None:
        for b, x in j.groupby("bin"):
            por_frame[b] = conf(x)
    # por track GT
    tr = []
    for gid, x in j.groupby("gt_id"):
        x = x[x.moving != -1]
        if not len(x):
            continue
        tr.append(dict(gt_id=gid, estatico=bool((x.moving == 0).all()), movil_alguna_vez=bool((x.moving == 1).any()),
                       marcado_alguna_vez=bool((x.en_movimiento == 1).any()),
                       frac_correcta=float((x.moving == x.en_movimiento).mean())))
    tr = pd.DataFrame(tr)
    por_track = {}
    if len(tr):
        est, mov = tr[tr.estatico], tr[tr.movil_alguna_vez]
        por_track = dict(n_tracks_estaticos=len(est), falsa_alarma_por_track=float(est.marcado_alguna_vez.mean()) if len(est) else np.nan,
                         n_tracks_moviles=len(mov), deteccion_por_track=float(mov.marcado_alguna_vez.mean()) if len(mov) else np.nan,
                         frac_vida_correcta=float(tr.frac_correcta.mean()))
    lat = latencias(j, moving, fps)
    return por_frame, por_track, lat


def latencias(j, moving, fps):
    """Latencia de encendido (GT pasa a moving = 1) y de apagado (pasa a 0) hasta que el track emparejado cambia.
    Un tramo sin cambio del decisor antes de que termine queda 'sin detectar' (censurado)."""
    est = j.set_index(["frame", "gt_id"])["en_movimiento"]
    filas = []
    for gid, g in moving.sort_values("frame").groupby("id"):
        fr, mv = g.frame.to_numpy(), g.moving.to_numpy()
        i = 0
        while i < len(fr):
            if mv[i] in (0, 1) and (i == 0 or mv[i - 1] != mv[i]):
                objetivo, k = mv[i], i
                tipo = "encendido" if objetivo == 1 else "apagado"
                if tipo == "apagado" and (i == 0 or mv[i - 1] != 1):
                    i += 1
                    continue
                lat = None
                while k < len(fr) and mv[k] == objetivo:
                    v = est.get((int(fr[k]), int(gid)))
                    if v is not None and int(v) == objetivo:
                        lat = (fr[k] - fr[i]) / fps
                        break
                    k += 1
                filas.append(dict(gt_id=int(gid), tipo=tipo, frame_inicio=int(fr[i]), latencia_s=lat,
                                  detectado=lat is not None))
            i += 1
    return pd.DataFrame(filas, columns=["gt_id", "tipo", "frame_inicio", "latencia_s", "detectado"])


def resumen_latencias(lat):
    out = {}
    for tipo in ("encendido", "apagado"):
        x = lat[lat.tipo == tipo]
        d = x[x.detectado].latencia_s.astype(float)
        out[tipo] = dict(n_tramos=len(x), pct_detectado=100 * float(x.detectado.mean()) if len(x) else np.nan,
                         mediana_s=float(d.median()) if len(d) else np.nan,
                         p90_s=float(d.quantile(0.9)) if len(d) else np.nan)
    return out


# ======================================================================
# 6. Métricas sin GT (las de la v13), para validarlas contra las de GT
# ======================================================================
def metricas_sin_gt(pred, lateral, primero, ultimo, fps):
    n_frames = ultimo - primero + 1
    minutos = max(n_frames / fps / 60, 1e-9)
    if len(pred) == 0:
        return dict(tracks=0, vida_media_s=0.0, tracks_por_objeto=0.0, ids_por_minuto=0.0, duracion_mediana_s=0.0,
                    tracks_menores_1s_pct=0.0, objetos_simultaneos_prom=0.0, pct_frames_en_movimiento=0.0,
                    cambios_estado_por_track=0.0)
    por_track = pred.groupby("id").size()
    por_frame = pred.groupby("frame").size().reindex(range(primero, ultimo + 1), fill_value=0)
    cambios = lateral.sort_values("frame").groupby("id").en_movimiento.apply(lambda s: int((s.diff().abs() > 0).sum()))
    return dict(tracks=int(len(por_track)),
                vida_media_s=float(por_track.sum() / len(por_track) / fps),
                tracks_por_objeto=float(len(por_track) / max(por_frame.mean(), 1e-9)),
                ids_por_minuto=float(len(por_track) / minutos),
                duracion_mediana_s=float(por_track.median() / fps),
                tracks_menores_1s_pct=float(100 * (por_track < fps).mean()),
                objetos_simultaneos_prom=float(por_frame.mean()),
                pct_frames_en_movimiento=float(100 * lateral.en_movimiento.mean()) if len(lateral) else 0.0,
                cambios_estado_por_track=float(cambios.mean()) if len(cambios) else 0.0)


# ======================================================================
# 7. Orquestación: un run completo
# ======================================================================
def evaluar_run(manifiesto, dir_run, secuencias=None, protocolos=None):
    """Evalúa todas las secuencias (con GT) de un run. Escribe CSVs en <run>/eval/ y devuelve la tabla principal."""
    import json
    from comunes import leer_gt, leer_mot, rango_frames, fps_de, info_video
    from ego import bins_ego, ruta_cache as ruta_ego, leer as leer_ego
    from gt import cargar_moving, frames_anotados

    dir_run = Path(dir_run)
    meta = json.load(open(dir_run / "run.json"))
    etiquetas = [t["etiqueta"] for t in meta["trackers"]]
    uso_gt = {t["etiqueta"]: t.get("uso_gt", "no") for t in meta["trackers"]}   # no | train | test (oráculo)
    # fuera del ranking: oráculos (uso_gt=test) y selecciones no validadas en ajuste (singt sin D17.6)
    en_ranking = {t["etiqueta"]: t.get("en_ranking", t.get("uso_gt", "no") != "test") for t in meta["trackers"]}
    cfg = manifiesto.evaluacion
    umbr = tuple(cfg.get("bins_ego_px", (0.5, 3.0)))
    secs = [s for s in manifiesto.secuencias if s.nombre in meta["secuencias"] and (secuencias is None or s.nombre in secuencias)]
    protocolos = protocolos or cfg.get("protocolos", ["todos", "moviles", "estaticos", "e2e_moviles"])

    tablas, sin_gt, bins_tab, dec_tab, lat_tab = [], [], [], [], []
    res_comb = {(p, e): {} for p in protocolos for e in etiquetas}
    bins_comb = {e: [] for e in etiquetas}
    for sec in secs:
        a, b = rango_frames(sec)
        fps = fps_de(sec)
        df_ego = leer_ego(ruta_ego(sec)) if ruta_ego(sec).exists() else None
        gt = leer_gt(sec.gt) if sec.gt else None
        frames = frames_anotados(sec, gt) if gt is not None else None
        moving = cargar_moving(sec, gt, df_ego, info_video(sec.video)["ancho"], fps) if gt is not None else None
        bins = bins_ego(df_ego, fps, umbr) if df_ego is not None else None
        for e in etiquetas:
            pred = leer_mot(dir_run / e / f"{sec.nombre}.txt")
            lat = pd.read_csv(dir_run / e / f"{sec.nombre}_lateral.csv")
            sin_gt.append(dict(tracker=e, secuencia=sec.nombre, split=sec.split, **metricas_sin_gt(pred, lat, a, b, fps)))
            if gt is None:
                continue
            for p in protocolos:
                if p != "todos" and moving is None:
                    continue
                data, extra = preparar(gt, pred, frames, cfg, p, moving, lat)
                r = evaluar_datos(data)
                res_comb[(p, e)][sec.nombre] = r
                tablas.append(dict(protocolo=p, tracker=e, secuencia=sec.nombre, split=sec.split, uso_gt=uso_gt[e],
                                   en_ranking=en_ranking[e], **resumen(r),
                                   descartadas_ignoradas=extra["descartadas_ignoradas"],
                                   descartadas_distractor=extra["descartadas_distractor"]))
                if p == "todos" and sec.split != "ajuste":   # D14: bins y decisor solo en test
                    if bins is not None:
                        et = [bins.get(int(f), "H_no_fiable") for f in frames]
                        acc = hota_por_bins(data, et)
                        cl = clear_por_frame(data)
                        for bn, d in acc.items():
                            idsw = sum(c["idsw"] for c, x in zip(cl, et) if x == bn)
                            bins_tab.append(dict(tracker=e, secuencia=sec.nombre, bin=bn, **metricas_bin(d), IDSW=idsw,
                                                 IDSW_por_1000=1000 * idsw / max(1, d["n_gt"])))
                        bins_comb[e].append((acc, cl, et))
                    if moving is not None:
                        pares, _ = emparejar_original(data, extra)
                        pf, pt, la = evaluar_decisor(pares, moving, lat, fps, bins)
                        for k, v in pf.items():
                            dec_tab.append(dict(tracker=e, secuencia=sec.nombre, nivel="frame", grupo=k, **v))
                        if pt:
                            dec_tab.append(dict(tracker=e, secuencia=sec.nombre, nivel="track", grupo="global", **pt))
                        for tipo, v in resumen_latencias(la).items():
                            lat_tab.append(dict(tracker=e, secuencia=sec.nombre, tipo=tipo, **v))

    # combinados (solo split test; el de ajuste no se reporta). Lo elegido mirando el GT de test (oráculos) no entra al
    # COMBINADO del ranking: va en una fila aparte, COMBINADO_COTA.
    test = {s.nombre for s in secs if s.split != "ajuste"}
    for (p, e), d in res_comb.items():
        d = {k: v for k, v in d.items() if k in test}
        if d:
            nombre = ("COMBINADO_COTA" if uso_gt[e] == "test" else
                      "COMBINADO" if en_ranking[e] else "COMBINADO_NO_VALIDADO")
            tablas.append(dict(protocolo=p, tracker=e, secuencia=nombre, split="test", uso_gt=uso_gt[e],
                               en_ranking=en_ranking[e], **resumen(combinar(d))))
    for e, lista in bins_comb.items():
        if lista:
            comb = combinar_bins([x[0] for x in lista])
            for bn, d in comb.items():
                idsw = sum(c["idsw"] for _, cl, et in lista for c, x in zip(cl, et) if x == bn)
                bins_tab.append(dict(tracker=e, secuencia="COMBINADO", bin=bn, **metricas_bin(d), IDSW=idsw,
                                     IDSW_por_1000=1000 * idsw / max(1, d["n_gt"])))

    comparaciones = pd.DataFrame()
    rankeables = [e for e in etiquetas if en_ranking[e]]
    por_tracker = {e: {k: v for k, v in res_comb.get(("todos", e), {}).items() if k in test} for e in rankeables}
    if len(rankeables) > 1 and min(len(v) for v in por_tracker.values()) >= 2:
        from estadistica import tabla_comparaciones
        comparaciones = tabla_comparaciones(por_tracker, n=int(cfg.get("bootstrap_n", 2000)))

    out = dir_run / "eval"
    out.mkdir(exist_ok=True)
    salidas = dict(metricas=pd.DataFrame(tablas), sin_gt=pd.DataFrame(sin_gt), por_bin_ego=pd.DataFrame(bins_tab),
                   decisor=pd.DataFrame(dec_tab), latencias=pd.DataFrame(lat_tab), comparaciones=comparaciones)
    for k, df in salidas.items():
        if len(df):
            df.round(4).to_csv(out / f"{k}.csv", index=False)
    print(f"[evaluar] {dir_run.name}: resultados en {out}")
    return salidas
