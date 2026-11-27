"""
ablacion.py — Resultado de la ablación de propio_kf en ajuste (D35.6). Combina como TrackEval y compara cada variante
contra propio_v1 (y cada variante propia contra BoT-SORT) con bootstrap pareado por secuencia (D28). Protocolo `todos` (en ajuste no hay moving revisado).

Uso (desde benchmark/):
    python analisis/ablacion.py runs/diag_v2
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

if __name__ == "__main__":
    run = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/diag_v2")
    man = cargar_manifiesto("diagnostico_v2.yaml")
    meta = json.load(open(run / "run.json"))
    ets = [t["etiqueta"] for t in meta["trackers"]]
    res = {e: {} for e in ets}
    for sec in (s for s in man.secuencias if s.nombre in meta["secuencias"]):
        gt = leer_gt(sec.gt)
        frames = frames_anotados(sec, gt)
        for e in ets:
            data, _ = preparar(gt, leer_mot(run / e / f"{sec.nombre}.txt"), frames, man.evaluacion, "todos")
            res[e][sec.nombre] = evaluar_datos(data)
    filas = []
    for e in ets:
        r = resumen(combinar(res[e]))
        f = dict(tracker=e, **{k: r[k] for k in ("HOTA", "DetA", "AssA", "IDF1", "MOTA", "IDSW", "IDs")})
        if e.startswith("propio_"):
            b = bootstrap_pareado(res[e], res["botsort"], "HOTA", n=2000)
            f["dHOTA_vs_botsort"], f["vs_botsort_ic"] = b["delta"], f"[{b['ic95_bajo']:+.2f}, {b['ic95_alto']:+.2f}]"
        if e != BASE:
            for m in ("HOTA", "AssA"):
                b = bootstrap_pareado(res[e], res[BASE], m, n=2000)
                f[f"d{m}"], f[f"d{m}_ic"] = b["delta"], f"[{b['ic95_bajo']:+.2f}, {b['ic95_alto']:+.2f}]"
                f[f"{m}_gana_en"] = b["gana_en"]
        filas.append(f)
    t = pd.DataFrame(filas)
    (run / "eval").mkdir(exist_ok=True)
    t.to_csv(run / "eval" / "ablacion.csv", index=False)
    pd.set_option("display.width", 250)
    print(t.round(2).to_string(index=False))
