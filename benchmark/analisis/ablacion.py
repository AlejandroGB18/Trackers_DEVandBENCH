"""
ablacion.py — Resultado de la ablación de propio_kf en ajuste (D35.6). Combina como TrackEval y compara cada variante
contra propio_v1 (y cada variante propia contra BoT-SORT) con bootstrap pareado por secuencia (D28). Protocolo `todos` (en ajuste no hay moving revisado).

Uso (desde benchmark/):
    python analisis/ablacion.py runs/diag_v2                    # ablación acumulativa (D35.6)
    python analisis/ablacion.py runs/diag_v2 runs/diag_v2b      # + variantes sin H3 (D36.1); salida en el último run
Si una etiqueta aparece en dos runs, se usa la del primero (el control repetido se compara aparte con sha256).
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comunes import cargar_manifiesto, leer_gt, leer_mot          # noqa: E402
from estadistica import bootstrap_pareado                          # noqa: E402
from evaluar import combinar, evaluar_datos, preparar, resumen     # noqa: E402
from gt import frames_anotados                                     # noqa: E402

BASE = "propio_v1"
A4 = "propio_A4_tentativos"
# D36.1: candidatos a v2 (todos con H1, obligatoria por D7/D35) y cuántos cambios tiene cada uno respecto a la v1
CANDIDATOS = {"propio_A7_clase_tentativos": 2, "propio_A6_sin_fusion": 3, A4: 4}

if __name__ == "__main__":
    runs = [Path(r) for r in (sys.argv[1:] or ["runs/diag_v2"])]
    man = cargar_manifiesto("diagnostico_v2.yaml")
    origen, seqs = {}, None
    for run in runs:
        meta = json.load(open(run / "run.json"))
        seqs = set(meta["secuencias"]) if seqs is None else seqs & set(meta["secuencias"])
        for t in meta["trackers"]:
            origen.setdefault(t["etiqueta"], run)
    ets = list(origen)
    res = {e: {} for e in ets}
    for sec in (s for s in man.secuencias if s.nombre in seqs):
        gt = leer_gt(sec.gt)
        frames = frames_anotados(sec, gt)
        for e in ets:
            data, _ = preparar(gt, leer_mot(origen[e] / e / f"{sec.nombre}.txt"), frames, man.evaluacion, "todos")
            res[e][sec.nombre] = evaluar_datos(data)
    filas = []
    for e in ets:
        r = resumen(combinar(res[e]))
        f = dict(tracker=e, **{k: r[k] for k in ("HOTA", "DetA", "AssA", "IDF1", "MOTA", "IDSW", "IDs")})
        if e.startswith("propio_"):
            b = bootstrap_pareado(res[e], res["botsort"], "HOTA", n=2000)
            f["dHOTA_vs_botsort"], f["vs_botsort_ic"] = b["delta"], f"[{b['ic95_bajo']:+.2f}, {b['ic95_alto']:+.2f}]"
        if e.startswith("propio_A") and e != A4 and A4 in res:
            b = bootstrap_pareado(res[e], res[A4], "AssA", n=2000)
            f["dAssA_vs_A4"], f["vs_A4_ic"] = b["delta"], f"[{b['ic95_bajo']:+.2f}, {b['ic95_alto']:+.2f}]"
        if e != BASE:
            for m in ("HOTA", "AssA"):
                b = bootstrap_pareado(res[e], res[BASE], m, n=2000)
                f[f"d{m}"], f[f"d{m}_ic"] = b["delta"], f"[{b['ic95_bajo']:+.2f}, {b['ic95_alto']:+.2f}]"
                f[f"{m}_gana_en"] = b["gana_en"]
        filas.append(f)
    t = pd.DataFrame(filas)
    (runs[-1] / "eval").mkdir(exist_ok=True)
    t.to_csv(runs[-1] / "eval" / "ablacion.csv", index=False)
    pd.set_option("display.width", 250)
    print(t.round(2).to_string(index=False))

    # Regla D36.1: el mejor AssA entre candidatos; de los que no son peores que él (IC del ΔAssA pareado incluye 0) y
    # cuyo HOTA no queda bajo la v1 (IC), el de menos cambios.
    cand = [c for c in CANDIDATOS if c in res]
    if len(cand) > 1:
        mejor = max(cand, key=lambda c: resumen(combinar(res[c]))["AssA"])
        print(f"\n[D36.1] mejor AssA: {mejor}")
        validos = []
        for c in cand:
            h = bootstrap_pareado(res[c], res[BASE], "HOTA", n=2000)
            a = bootstrap_pareado(res[c], res[mejor], "AssA", n=2000) if c != mejor else None
            ok_h = h["ic95_alto"] >= 0                    # no significativamente peor que la v1
            ok_a = a is None or a["ic95_alto"] >= 0          # no significativamente peor que el mejor
            txt = "—" if a is None else f"{a['delta']:+.2f} [{a['ic95_bajo']:+.2f}, {a['ic95_alto']:+.2f}]"
            print(f"  {c:28s} cambios={CANDIDATOS[c]}  ΔAssA vs mejor={txt}  "
                  f"no peor que el mejor={ok_a}  HOTA no bajo la v1={ok_h}")
            if ok_a and ok_h:
                validos.append(c)
        elegido = min(validos, key=lambda c: (CANDIDATOS[c], -resumen(combinar(res[c]))["AssA"]))
        print(f"[D36.1] ELEGIDO para la v2: {elegido}")
