"""
ajuste.py — Lo que se mide en las secuencias de AJUSTE antes del congelado 1 (D21, D25, D26)
=============================================================================================

Nada de esto mira test. Produce propuestas que una persona revisa y congela en DECISIONS.md.

1. `det_eval` (D21, D25): el detector SOLO, sin tracker.
   - Curva de confianza: por umbral (0.05 … 0.95), TP/FP/FN con emparejamiento húngaro a IoU ≥ 0.5, quitando antes
     las detecciones con ≥ 50 % de su área en una región ignorada (D8) → precisión, recall, F1.
   - Propuesta: conf_high = umbral de mejor F1 (combinado de ajuste); conf_low = el umbral más bajo con precisión
     ≥ 0.5 (por debajo, la mayoría de lo que entra es basura).
   - DetA de TrackEval (cada detección con su propio id, así que AssA no significa nada) con las detecciones
     ≥ conf_high, por estrato (grupo de vuelo, iluminación) y global. Estrato con DetA < 20 → propuesto para excluir.
2. `tramos` (D26): cortes de ego-movimiento en los percentiles 33/67 de `ego_px` (suavizado como en la evaluación)
   de todos los frames de ajuste con H fiable → tramos bajo, medio y alto. Si el tramo alto no cumple el mínimo de
   datos (≥ 2000 detecciones del GT y ≥ 5 secuencias), se pasa a dos tramos cortando en la mediana.

Salidas en runs/<run>/ajuste/: det_curva.csv, det_deta.csv, tramos_frames.csv, propuesta.json (todo junto).
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from comunes import DIR_RUNS, fps_de, guardar_json, leer_gt
from evaluar import _xyxy, combinar, evaluar_datos, frac_dentro, iou, preparar, resumen

UMBRALES = np.round(np.arange(0.05, 0.951, 0.05), 2)
DETA_MIN = 20.0
MIN_DETS_TRAMO, MIN_SECS_TRAMO = 2000, 5
ETIQUETAS_3 = ("bajo", "medio", "alto")
ETIQUETAS_2 = ("bajo", "alto")


def estratos_de(sec):
    """Estratos de una secuencia: global, grupo de vuelo e iluminación."""
    return {"global": "global", "grupo": sec.grupo_barrido, "luz": (sec.atributos or {}).get("luz", "?")}


# ======================================================================
# 1. Detector
# ======================================================================
def _conteos_por_umbral(gt, cache, frames, cfg):
    """TP/FP/FN por umbral (IoU ≥ 0.5, húngaro), sobre una secuencia."""
    evaluadas = set(cfg.get("clases_evaluadas", [1]))
    ignoradas = set(cfg.get("clases_ignoradas", [0]))
    umbral_area = float(cfg.get("umbral_area_ignorada", 0.5))
    tp = np.zeros(len(UMBRALES), int); fp = np.zeros(len(UMBRALES), int); fn = np.zeros(len(UMBRALES), int)
    gt_por_f = dict(tuple(gt.groupby("frame")))
    vacio = gt.iloc[:0]
    for f in frames:
        g = gt_por_f.get(int(f), vacio)
        reg = _xyxy(g[g.clase.isin(ignoradas)])
        g = g[g.clase.isin(evaluadas) & (g.considerar != 0)]
        gb = _xyxy(g)
        d = cache.por_frame(f, UMBRALES[0])
        if len(d) and len(reg):
            d = d[frac_dentro(d[:, :4], reg).max(1) < umbral_area]
        if len(d) == 0:
            fn += len(gb)
            continue
        s = iou(gb, d[:, :4])
        for k, u in enumerate(UMBRALES):
            m = d[:, 4] >= u
            n_d = int(m.sum())
            if len(gb) == 0 or n_d == 0:
                fp[k] += n_d; fn[k] += len(gb)
                continue
            sk = s[:, m]
            r, c = linear_sum_assignment(-sk)
            n_tp = int((sk[r, c] >= 0.5).sum())
            tp[k] += n_tp; fp[k] += n_d - n_tp; fn[k] += len(gb) - n_tp
    return tp, fp, fn


def _prf(tp, fp, fn):
    p = tp / np.maximum(tp + fp, 1); r = tp / np.maximum(tp + fn, 1)
    return p, r, 2 * p * r / np.maximum(p + r, 1e-9)


def _como_pred(cache, frames, conf_min):
    filas = []
    nid = 1
    for f in frames:
        for x1, y1, x2, y2, c, _ in cache.por_frame(f, conf_min):
            filas.append((int(f), nid, x1, y1, x2 - x1, y2 - y1, c))
            nid += 1
    return pd.DataFrame(filas, columns=["frame", "id", "x", "y", "w", "h", "conf"])


def det_eval(secuencias, caches, cfg_eval, frames_de):
    """Devuelve (curva por estrato y umbral, DetA por secuencia y estrato, propuesta)."""
    por_seq = {}
    for sec in secuencias:
        gt = leer_gt(sec.gt)
        fr = frames_de(sec, gt)
        por_seq[sec.nombre] = (sec, gt, fr, _conteos_por_umbral(gt, caches[sec.nombre], fr, cfg_eval))
        print(f"[det-eval] {sec.nombre}: curva lista")
    curva = []
    for sec, _, _, (tp, fp, fn) in por_seq.values():
        for tipo, val in estratos_de(sec).items():
            for k, u in enumerate(UMBRALES):
                curva.append(dict(tipo=tipo, estrato=val, umbral=u, TP=tp[k], FP=fp[k], FN=fn[k]))
    curva = pd.DataFrame(curva).groupby(["tipo", "estrato", "umbral"], as_index=False).sum()
    p, r, f1 = _prf(curva.TP.to_numpy(), curva.FP.to_numpy(), curva.FN.to_numpy())
    curva["precision"], curva["recall"], curva["F1"] = p, r, f1

    glob = curva[curva.tipo == "global"].sort_values("umbral")
    conf_high = float(glob.loc[glob.F1.idxmax(), "umbral"])
    ok = glob[glob.precision >= 0.5]
    conf_low = float(ok.umbral.min()) if len(ok) else conf_high
    conf_low = min(conf_low, conf_high)

    res, deta = {}, []
    for nombre, (sec, gt, fr, _) in por_seq.items():
        data, _ = preparar(gt, _como_pred(caches[nombre], fr, conf_high), fr, cfg_eval, "todos")
        res[nombre] = evaluar_datos(data)
        deta.append(dict(secuencia=nombre, **estratos_de(sec), **{k: resumen(res[nombre])[k]
                                                               for k in ("DetA", "DetRe", "DetPr", "GT_Dets")}))
    deta = pd.DataFrame(deta)
    filas = []
    for tipo in ("global", "grupo", "luz"):
        for val, x in deta.groupby(tipo):
            m = resumen(combinar({s: res[s] for s in x.secuencia}))
            filas.append(dict(secuencia=f"COMBINADO_{tipo}", tipo=tipo, estrato=val, n_secuencias=int(len(x)),
                              DetA=m["DetA"], DetRe=m["DetRe"], DetPr=m["DetPr"], GT_Dets=m["GT_Dets"]))
    comb = pd.DataFrame(filas)
    excluir = comb[(comb.tipo != "global") & (comb.DetA < DETA_MIN)][["tipo", "estrato", "DetA"]]
    propuesta = dict(conf_high=conf_high, conf_low=conf_low, conf_entrada=conf_low,
                     f1_en_conf_high=float(glob.F1.max()),
                     deta_global=float(comb[comb.tipo == "global"].DetA.iloc[0]),
                     excluir=excluir.round(1).to_dict("records"), deta_min=DETA_MIN)
    return curva, pd.concat([deta, comb], ignore_index=True), propuesta


# ======================================================================
# 2. Tramos de ego
# ======================================================================
def ego_suavizado(df_ego, fps, suavizado_s=0.5):
    """ego_px con la misma mediana centrada que usa bins_ego; NaN donde la H no es fiable."""
    v = df_ego.set_index("frame")["ego_px"]
    n = max(1, int(round(suavizado_s * fps)))
    s = v.rolling(n, center=True, min_periods=1).median()
    s[~df_ego.set_index("frame")["H_ok"].astype(bool)] = np.nan
    return s


def etiquetar(s, cortes, etiquetas):
    """Serie ego_px suavizado → tramo. `cortes` crecientes, len(etiquetas) = len(cortes) + 1."""
    lab = pd.Series(etiquetas[-1], index=s.index, dtype=object)
    for c, e in zip(reversed(cortes), reversed(etiquetas[:-1])):
        lab[s < c] = e
    lab[s.isna()] = "H_no_fiable"
    return lab


def tramos(secuencias, egos, gts, frames_de):
    """Propuesta de cortes (D26) con los frames de ajuste. Devuelve (tabla por tramo, propuesta)."""
    filas = []
    for sec in secuencias:
        s = ego_suavizado(egos[sec.nombre], fps_de(sec))
        gt = gts[sec.nombre]
        n_gt = gt[gt.clase == 1].groupby("frame").size()
        fr = frames_de(sec, gt)
        filas.append(pd.DataFrame(dict(secuencia=sec.nombre, frame=fr, ego=s.reindex(fr).to_numpy(),
                                       n_gt=n_gt.reindex(fr, fill_value=0).to_numpy())))
    d = pd.concat(filas, ignore_index=True)
    v = d.ego.dropna()
    p33, p50, p67 = (float(v.quantile(q)) for q in (0.33, 0.50, 0.67))

    def resumen_tramos(cortes, etiquetas):
        lab = etiquetar(d.ego, cortes, etiquetas)
        t = d.assign(tramo=lab).groupby("tramo").agg(frames=("frame", "size"), gt_dets=("n_gt", "sum"),
                                                     secuencias=("secuencia", "nunique"))
        return t, lab

    t3, _ = resumen_tramos([p33, p67], ETIQUETAS_3)
    alto = t3.loc["alto"] if "alto" in t3.index else None
    tres = alto is not None and alto.gt_dets >= MIN_DETS_TRAMO and alto.secuencias >= MIN_SECS_TRAMO
    if tres:
        cortes, etiquetas, tabla = [p33, p67], ETIQUETAS_3, t3
    else:
        cortes, etiquetas = [p50], ETIQUETAS_2
        tabla, _ = resumen_tramos(cortes, etiquetas)
    propuesta = dict(modo="tres" if tres else "dos", cortes_px=[round(c, 3) for c in cortes], etiquetas=list(etiquetas),
                     percentiles_px=dict(p33=round(p33, 3), p50=round(p50, 3), p67=round(p67, 3),
                                         p90=round(float(v.quantile(0.9)), 3), max=round(float(v.max()), 3)),
                     frames_h_fiable=int(len(v)), frames_total=int(len(d)),
                     regla=f"alto con ≥ {MIN_DETS_TRAMO} detecciones del GT y ≥ {MIN_SECS_TRAMO} secuencias; "
                           "si no, dos tramos en la mediana")
    return tabla.reset_index(), propuesta


def cargar_tramos(valor):
    """`evaluacion.tramos_ego` del manifiesto → (cortes, etiquetas). Acepta el dict congelado en línea
    ({cortes_px: [...], etiquetas: [...]}, lo recomendado) o la ruta a propuesta.json. None si no hay."""
    from pathlib import Path
    if not valor:
        return None
    d = valor
    if not isinstance(valor, dict):
        ruta = Path(valor)
        if not ruta.exists():
            raise FileNotFoundError(f"tramos_ego: no existe {ruta}")
        d = json.load(open(ruta))
        d = d.get("tramos", d)
    if len(d["etiquetas"]) != len(d["cortes_px"]) + 1:
        raise ValueError(f"tramos_ego: {len(d['cortes_px'])} cortes necesitan {len(d['cortes_px']) + 1} etiquetas")
    return list(d["cortes_px"]), tuple(d["etiquetas"])


def correr_ajuste(manifiesto, nombre_run, que=("det", "tramos")):
    """Lo que hace `bench.py ajuste`: secuencias de ajuste del manifiesto (ya filtrado)."""
    from detecciones import CacheDetecciones, ruta_cache
    from ego import leer as leer_ego, ruta_cache as ruta_ego
    from gt import frames_anotados
    secs = [s for s in manifiesto.secuencias if s.split == "ajuste" and s.gt]
    if not secs:
        raise SystemExit("[ajuste] no hay secuencias de ajuste con GT")
    out = DIR_RUNS / nombre_run / "ajuste"
    out.mkdir(parents=True, exist_ok=True)
    prop_p = out / "propuesta.json"
    propuesta = json.load(open(prop_p)) if prop_p.exists() else {}
    propuesta.update(detector={s.detector for s in secs}.pop(), secuencias=[s.nombre for s in secs])
    if "det" in que:
        caches = {s.nombre: CacheDetecciones(ruta_cache(s, s.detector)) for s in secs}
        curva, deta, p = det_eval(secs, caches, manifiesto.evaluacion, frames_anotados)
        curva.round(4).to_csv(out / "det_curva.csv", index=False)
        deta.round(2).to_csv(out / "det_deta.csv", index=False)
        propuesta["detector_umbral"] = p
        print(deta[deta.secuencia.str.startswith("COMBINADO")][["tipo", "estrato", "n_secuencias", "DetA", "DetRe",
                                                                  "DetPr"]].round(1).to_string(index=False))
        print(f"[ajuste] propuesta: conf_high {p['conf_high']} (F1 {p['f1_en_conf_high']:.3f}), conf_low "
              f"{p['conf_low']}; excluir: {p['excluir'] or 'nada'}")
    if "tramos" in que:
        egos, gts = {}, {}
        for s in secs:
            if not ruta_ego(s).exists():
                raise SystemExit(f"[ajuste] falta el ego de {s.nombre}: corre `bench.py ego --split ajuste`")
            egos[s.nombre], gts[s.nombre] = leer_ego(ruta_ego(s)), leer_gt(s.gt)
        tabla, p = tramos(secs, egos, gts, frames_anotados)
        tabla.to_csv(out / "tramos.csv", index=False)
        propuesta["tramos"] = p
        print(tabla.to_string(index=False))
        print(f"[ajuste] tramos: {p['modo']}, cortes {p['cortes_px']} px/frame a 960 ({p['percentiles_px']})")
    guardar_json(prop_p, propuesta)
    print(f"[ajuste] → {out}  (revisar y congelar en DECISIONS.md antes de tocar test)")
    return propuesta
