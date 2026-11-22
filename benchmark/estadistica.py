"""
estadistica.py — ¿La diferencia entre dos trackers es real o depende de qué secuencias se evaluaron?
=====================================================================================================

Bootstrap PAREADO por secuencia: se remuestrean secuencias con reemplazo y, en cada réplica, se COMBINAN sus
resultados como lo hace TrackEval (sumando conteos), no promediando HOTA. Se reporta Δ = A − B, su IC 95 % y en
cuántas secuencias gana A.

Limitación: con pocas secuencias (p. ej. 4–5 clips VIGIA) el IC es ancho y poco fiable. El bootstrap por bloques
temporales dentro de cada clip está pendiente (ver DECISIONS.md).
"""
import numpy as np
import pandas as pd

from evaluar import combinar, resumen


def bootstrap_pareado(res_a, res_b, metrica="HOTA", n=10000, semilla=0):
    """res_a, res_b: {secuencia: resultado de evaluar_datos} con las MISMAS secuencias."""
    seqs = sorted(set(res_a) & set(res_b))
    if len(seqs) < 2:
        raise ValueError("Hacen falta al menos 2 secuencias comunes")
    rng = np.random.default_rng(semilla)
    obs = resumen(combinar({s: res_a[s] for s in seqs}))[metrica] - resumen(combinar({s: res_b[s] for s in seqs}))[metrica]
    deltas = np.empty(n)
    for k in range(n):
        m = rng.choice(len(seqs), len(seqs), replace=True)
        ra = {f"{seqs[i]}#{j}": res_a[seqs[i]] for j, i in enumerate(m)}
        rb = {f"{seqs[i]}#{j}": res_b[seqs[i]] for j, i in enumerate(m)}
        deltas[k] = resumen(combinar(ra))[metrica] - resumen(combinar(rb))[metrica]
    por_seq = [resumen(res_a[s])[metrica] - resumen(res_b[s])[metrica] for s in seqs]
    return dict(metrica=metrica, delta=obs, ic95_bajo=float(np.percentile(deltas, 2.5)),
                ic95_alto=float(np.percentile(deltas, 97.5)), gana_en=int(np.sum(np.array(por_seq) > 0)),
                n_secuencias=len(seqs))


def kendall_tau(a, b):
    """τ de Kendall entre dos rankings (mismas claves). Para validar métricas sin GT contra las de GT."""
    from scipy.stats import kendalltau
    k = sorted(set(a) & set(b))
    return float(kendalltau([a[x] for x in k], [b[x] for x in k]).statistic)


def tabla_comparaciones(res_por_tracker, metricas=("HOTA", "AssA", "IDF1"), n=2000):
    """Todas las parejas de trackers. res_por_tracker: {tracker: {secuencia: resultado}}."""
    filas = []
    ks = list(res_por_tracker)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            for m in metricas:
                filas.append(dict(A=a, B=b, **bootstrap_pareado(res_por_tracker[a], res_por_tracker[b], m, n)))
    return pd.DataFrame(filas)
