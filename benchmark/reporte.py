"""
reporte.py — Tablas y figuras del benchmark desde runs/<run>/eval/ (D28, D31)
=============================================================================

    python bench.py reporte --run v1     → runs/v1/reporte/{resultados.md, *.png, *.csv}

Todo sale de los CSV de `evaluar` (reproducible sin volver a correr trackers). Solo secuencias de TEST.
- Ranking: COMBINADO (suma de conteos, D14) de los trackers en el ranking; referencia y cota aparte (D23).
- Comparaciones pareadas: comparaciones.csv (bootstrap de secuencias, IC 95 %); "gana" solo si el IC excluye 0.
- P1: AssA e IDSW/1000 por tramo de ego (COMBINADO de por_bin_ego.csv) y ΔAssA = alto − bajo por secuencia,
  promediado con peso = detecciones del GT del tramo menor, con IC 95 % por bootstrap de secuencias.
  Un tramo con < 2000 detecciones del GT o < 5 secuencias se marca "indicativo" (D28).
- P2: precisión/recall/F1 del decisor sumando TP/FP/FN de todas las secuencias, IC 95 % por bootstrap.
- Secundarios: valor de la cámara de UCMC (referencia < grupo_train < cota), HOTA por grupo de vuelo e iluminación
  (promedio simple por secuencia: descriptivo) y ms/frame.

Figuras: PNG claros para la tesis, paleta categórica validada (orden fijo por tracker, nunca por posición),
leyenda + etiquetas directas, una sola escala por gráfico.
"""
from pathlib import Path

import numpy as np
import pandas as pd

RANKING = ["propio_kf", "bytetrack", "botsort", "ucmc_grupo_train"]
# Slots 1–4 de la paleta categórica de referencia (validada en orden adyacente); color = tracker, no posición
COLOR = {"propio_kf": "#2a78d6", "bytetrack": "#eb6834", "botsort": "#1baf7a", "ucmc_grupo_train": "#eda100"}
GRIS = "#898781"
TINTA, TINTA2, REJILLA, EJE, FONDO = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
ORDEN_TRAMOS = ["bajo", "medio", "alto", "estacionario", "suave", "rapido", "H_no_fiable"]
MIN_DETS, MIN_SECS, B = 2000, 5, 2000


def _color(t):
    return COLOR.get(t, GRIS)


def _estilo(ax):
    ax.set_facecolor(FONDO)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(EJE)
    ax.tick_params(colors=TINTA2, labelsize=9)
    ax.grid(axis="y", color=REJILLA, linewidth=0.6)
    ax.set_axisbelow(True)


def _fig(n=1, ancho=7.0, alto=3.2):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, n, figsize=(ancho, alto), facecolor=FONDO)
    axs = np.atleast_1d(axs)
    for ax in axs:
        _estilo(ax)
    return fig, axs


def _guardar(fig, ruta):
    fig.tight_layout(rect=(0, 0, 1, 0.88) if fig.legends else (0, 0, 1, 1))
    fig.savefig(ruta, dpi=200, facecolor=FONDO)
    import matplotlib.pyplot as plt
    plt.close(fig)


def _md(df, cols=None, nd=1):
    df = df[cols] if cols else df
    if not len(df):
        return "_(sin datos)_\n"
    fmt = lambda v: (f"{v:.{nd}f}" if isinstance(v, (float, np.floating)) and np.isfinite(v) else
                     "—" if isinstance(v, (float, np.floating)) else str(v))
    filas = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    filas += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(filas) + "\n"


def _boot(valores, pesos=None, n=B, semilla=0):
    v = np.asarray(valores, float)
    w = np.ones_like(v) if pesos is None else np.asarray(pesos, float)
    if len(v) == 0:
        return np.nan, np.nan, np.nan
    est = float(np.average(v, weights=w))
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(v), (n, len(v)))
    bs = (v[idx] * w[idx]).sum(1) / np.maximum(w[idx].sum(1), 1e-12)
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def _boot_f1(tp, fp, fn, n=B, semilla=0):
    tp, fp, fn = (np.asarray(x, float) for x in (tp, fp, fn))
    if len(tp) == 0:
        return (np.nan,) * 3

    def f1(a, b, c):
        p = a / np.maximum(a + b, 1e-12); r = a / np.maximum(a + c, 1e-12)
        return 2 * p * r / np.maximum(p + r, 1e-12)
    est = float(f1(tp.sum(), fp.sum(), fn.sum()))
    idx = np.random.default_rng(semilla).integers(0, len(tp), (n, len(tp)))
    bs = f1(tp[idx].sum(1), fp[idx].sum(1), fn[idx].sum(1))
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


# ======================================================================
def ranking(m):
    t = m[(m.protocolo == "todos") & m.secuencia.str.startswith("COMBINADO")].copy()
    t["papel"] = t.secuencia.map({"COMBINADO": "ranking", "COMBINADO_REFERENCIA": "referencia",
                                  "COMBINADO_COTA": "cota", "COMBINADO_NO_VALIDADO": "no validado"})
    orden = {k: i for i, k in enumerate(RANKING)}
    t["o"] = t.tracker.map(orden).fillna(99)
    t["op"] = t.papel.map({"ranking": 0, "referencia": 1, "cota": 2, "no validado": 3})
    return t.sort_values(["op", "o"]).drop(columns=["o", "op"])


def fig_ranking(t, ruta):
    mets = ["HOTA", "AssA", "IDF1"]
    fig, axs = _fig(3, 9.0, 3.2)
    t = t[t.papel.isin(["ranking", "referencia", "cota"])]
    etiquetas = [f"{r.tracker}" + ("" if r.papel == "ranking" else f" ({r.papel})") for r in t.itertuples()]
    y = np.arange(len(t))[::-1]
    for ax, met in zip(axs, mets):
        ax.grid(axis="x", color=REJILLA, linewidth=0.6); ax.grid(axis="y", visible=False)
        for yi, r in zip(y, t.itertuples()):
            v = getattr(r, met)
            c = _color(r.tracker) if r.papel == "ranking" else GRIS
            ax.barh(yi, v, height=0.55, color=c, hatch=None if r.papel == "ranking" else "//", edgecolor=FONDO,
                    linewidth=0)
            ax.text(v + 0.5, yi, f"{v:.1f}", va="center", fontsize=8, color=TINTA2)
        ax.set_title(met, fontsize=10, color=TINTA, loc="left")
        ax.set_yticks(y); ax.set_yticklabels(etiquetas if ax is axs[0] else [], fontsize=8, color=TINTA)
        ax.set_xlim(0, max(100, float(np.nanmax(t[met])) * 1.1))
    _guardar(fig, ruta)


def p1(bins_seq, bins_comb, ranking_trackers):
    """Tabla por tramo (COMBINADO) + ΔAssA alto−bajo con IC por tracker."""
    tab = bins_comb[bins_comb.tracker.isin(ranking_trackers)].copy()
    n_secs = bins_seq.groupby(["tracker", "bin"]).secuencia.nunique().rename("secuencias").reset_index()
    tab = tab.merge(n_secs, on=["tracker", "bin"], how="left")
    tab["indicativo"] = (tab.n_gt_dets < MIN_DETS) | (tab.secuencias < MIN_SECS)
    bajo, alto = _extremos(tab.bin.unique())
    filas = []
    for tr in ranking_trackers:
        x = bins_seq[bins_seq.tracker == tr].pivot_table(index="secuencia", columns="bin", values=["AssA", "n_gt_dets"])
        if bajo is None or ("AssA", bajo) not in x or ("AssA", alto) not in x:
            continue
        d = x["AssA"][alto] - x["AssA"][bajo]
        w = np.minimum(x["n_gt_dets"][alto], x["n_gt_dets"][bajo])
        ok = d.notna() & (w > 0)
        est, lo, hi = _boot(d[ok], w[ok])
        filas.append(dict(tracker=tr, bajo=bajo, alto=alto, dAssA=est, IC_inf=lo, IC_sup=hi, secuencias=int(ok.sum())))
    return tab, pd.DataFrame(filas)


def _extremos(bins):
    orden = [b for b in ORDEN_TRAMOS if b in set(bins) and b != "H_no_fiable"]
    return (orden[0], orden[-1]) if len(orden) >= 2 else (None, None)


def fig_p1(tab, ruta):
    tramos = [b for b in ORDEN_TRAMOS if b in set(tab.bin) and b != "H_no_fiable"]
    fig, axs = _fig(2, 9.0, 3.2)
    x = np.arange(len(tramos))
    for ax, met, titulo in ((axs[0], "AssA", "AssA por tramo de ego"), (axs[1], "IDSW_por_1000",
                                                                        "IDSW por 1000 detecciones del GT")):
        finales = []
        for tr in RANKING:
            s = tab[tab.tracker == tr].set_index("bin").reindex(tramos)
            if s[met].isna().all():
                continue
            ax.plot(x, s[met], color=_color(tr), linewidth=2, marker="o", markersize=5, label=tr)
            finales.append([float(s[met].iloc[-1]), tr])
        _etiquetas_finales(ax, finales, x[-1])
        ax.set_xticks(x); ax.set_xticklabels(tramos, fontsize=9)
        ax.set_title(titulo, fontsize=10, color=TINTA, loc="left")
        ax.set_xlim(-0.3, len(tramos) - 0.1)
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=len(l), fontsize=8, frameon=False, bbox_to_anchor=(0.5, 0.995))
    _guardar(fig, ruta)


def _etiquetas_finales(ax, finales, x):
    """Etiquetas directas al final de cada línea, separadas para que no se encimen."""
    if not finales:
        return
    lo, hi = ax.get_ylim()
    gap = 0.07 * (hi - lo)
    finales.sort()
    ys = [f[0] for f in finales]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    for (y0, tr), y in zip(finales, ys):
        ax.annotate(tr, (x, y0), xytext=(x + 0.08, y), textcoords="data", fontsize=7, color=TINTA2, va="center")


def p2(dec, ranking_trackers):
    d = dec[(dec.nivel == "frame") & (dec.grupo == "global") & dec.tracker.isin(ranking_trackers)]
    filas = []
    for tr, x in d.groupby("tracker"):
        est, lo, hi = _boot_f1(x.TP, x.FP, x.FN)
        tp, fp, fn = x.TP.sum(), x.FP.sum(), x.FN.sum()
        filas.append(dict(tracker=tr, precision=100 * tp / max(tp + fp, 1), recall=100 * tp / max(tp + fn, 1),
                          F1=100 * est, IC_inf=100 * lo, IC_sup=100 * hi, n_frames_emparejados=int(x.n.sum()),
                          secuencias=x.secuencia.nunique()))
    out = pd.DataFrame(filas)
    if len(out):
        out = out.set_index("tracker").reindex([t for t in RANKING if t in set(out.tracker)]).reset_index()
    return out


def fig_p2(t, ruta):
    fig, axs = _fig(1, 5.0, 3.0)
    ax = axs[0]
    x = np.arange(len(t))
    for xi, r in zip(x, t.itertuples()):
        ax.bar(xi, r.F1, width=0.55, color=_color(r.tracker))
        if np.isfinite(r.IC_inf):
            ax.plot([xi, xi], [r.IC_inf, r.IC_sup], color=TINTA2, linewidth=1)
        ax.text(xi, (r.IC_sup if np.isfinite(r.IC_sup) else r.F1) + 1.5, f"{r.F1:.1f}", ha="center", fontsize=8,
                color=TINTA2)
    ax.set_xticks(x); ax.set_xticklabels(t.tracker, fontsize=8)
    ax.set_ylim(0, 105); ax.set_title("F1 del decisor de movimiento (IC 95 %)", fontsize=10, color=TINTA, loc="left")
    _guardar(fig, ruta)


def generar_reporte(dir_run, manifiesto=None):
    dir_run = Path(dir_run)
    ev = dir_run / "eval"
    out = dir_run / "reporte"
    out.mkdir(exist_ok=True)
    leer = lambda n: pd.read_csv(ev / f"{n}.csv") if (ev / f"{n}.csv").exists() else pd.DataFrame()
    m, comp, bins, dec, lat, singt = (leer(n) for n in ("metricas", "comparaciones", "por_bin_ego", "decisor",
                                                        "latencias", "sin_gt"))
    md = [f"# Resultados · run `{dir_run.name}`\n",
          "Generado por `bench.py reporte` desde `eval/`. Solo secuencias de test; combinados por suma de conteos "
          "(D14). Ranking = una entrada por tracker (D23); referencia y cota no compiten.\n"]
    rk = RANKING
    if len(m):
        t = ranking(m)
        rk = [x for x in RANKING if x in set(t[t.papel == "ranking"].tracker)] or RANKING
        md += ["## Ranking\n", _md(t, ["tracker", "papel", "HOTA", "DetA", "AssA", "IDF1", "MOTA", "IDSW", "Frag"])]
        fig_ranking(t, out / "ranking.png")
        md.append("![Ranking](ranking.png)\n")
        t.to_csv(out / "ranking.csv", index=False)
        seq = m[(m.protocolo == "todos") & ~m.secuencia.str.startswith("COMBINADO")]
        if manifiesto is not None and len(seq):
            meta = {s.nombre: dict(grupo=s.grupo_barrido, luz=(s.atributos or {}).get("luz", "?"))
                    for s in manifiesto.secuencias}
            seq = seq.assign(grupo=seq.secuencia.map(lambda s: meta.get(s, {}).get("grupo")),
                             luz=seq.secuencia.map(lambda s: meta.get(s, {}).get("luz")))
            for est in ("grupo", "luz"):
                p = seq[seq.tracker.isin(rk)].pivot_table(index=est, columns="tracker", values="HOTA", aggfunc="mean")
                p["secuencias"] = seq.groupby(est).secuencia.nunique()
                md += [f"### HOTA por {est} (promedio simple por secuencia, descriptivo)\n", _md(p.reset_index())]
    if len(comp):
        c = comp.copy()
        if {"ic95_bajo", "ic95_alto"} <= set(c.columns):
            c["veredicto"] = np.where(c.ic95_bajo > 0, "gana " + c.A, np.where(c.ic95_alto < 0, "gana " + c.B, "empate"))
        md += ["## Comparaciones pareadas (IC 95 %, bootstrap de secuencias)\n",
               "Un tracker gana solo si el IC de la diferencia excluye 0; si no, es empate técnico (D28).\n",
               _md(c)]
    if len(bins):
        bc = bins[bins.secuencia == "COMBINADO"]
        bs = bins[bins.secuencia != "COMBINADO"]
        tab, d = p1(bs, bc, rk)
        md += ["## P1 · Estabilidad de identidad por tramo de ego\n",
               _md(tab, ["tracker", "bin", "n_frames", "n_gt_dets", "secuencias", "HOTA", "AssA", "IDSW",
                         "IDSW_por_1000", "indicativo"]),
               "### ΔAssA (alto − bajo), IC 95 %\n", _md(d)]
        tab.to_csv(out / "p1_tramos.csv", index=False); d.to_csv(out / "p1_delta.csv", index=False)
        fig_p1(tab, out / "p1.png")
        md.append("![P1](p1.png)\n")
    if len(dec):
        t2 = p2(dec, rk)
        md += ["## P2 · Decisor de movimiento contra movimiento real\n", _md(t2)]
        if len(t2):
            fig_p2(t2, out / "p2.png"); md.append("![P2](p2.png)\n")
            t2.to_csv(out / "p2.csv", index=False)
    if len(lat):
        lt = lat[lat.tracker.isin(rk)].groupby(["tracker", "tipo"], as_index=False).agg(
            tramos=("n_tramos", "sum"), pct_detectado=("pct_detectado", "mean"), mediana_s=("mediana_s", "median"))
        md += ["### Latencias del decisor (descriptivo)\n", _md(lt, nd=2)]
    if len(m):
        cam = m[(m.protocolo == "todos") & m.tracker.str.startswith("ucmc") & m.secuencia.str.startswith("COMBINADO")]
        md += ["## Secundario · Valor de conocer la cámara (UCMC)\n",
               "Automática (referencia) → elegida por grupo en ajuste (ranking) → mejor por secuencia (cota).\n",
               _md(cam, ["tracker", "secuencia", "HOTA", "AssA", "IDF1"])]
    tiempos = sorted(dir_run.glob("*/*_tiempos.csv"))
    if tiempos:
        tt = pd.concat([pd.read_csv(p).assign(tracker=p.parent.name) for p in tiempos])
        col = [c for c in tt.columns if "ms" in c]
        if col:
            md += ["## Secundario · Costo (ms por frame, relativo; misma máquina)\n",
                   _md(tt.groupby("tracker", as_index=False)[col[0]].median(), nd=2)]
    (out / "resultados.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[reporte] → {out / 'resultados.md'}")
    return out
