"""
pruebas_benchmark.py — Comprobaciones del harness (python pruebas_benchmark.py → debe terminar en "TODO OK")
============================================================================================================

1. Sanidad: el GT como predicción da HOTA = MOTA = IDF1 = 100.
2. Un cambio de ID da exactamente 1 IDSW y baja AssA, pero no DetA.
3. Las réplicas por frame (CLEAR y HOTA por bins) coinciden con TrackEval.
4. Validación cruzada con py-motmetrics (MOTA, IDF1, IDSW).
5. Regla de regiones ignoradas por área y protocolos de móviles/estáticos.
6. Derivación de `moving` con una cámara que se desplaza.
7. De punta a punta con un video sintético (cámara en paneo, autos quietos y en movimiento):
   ego-movimiento, los 4 trackers, evaluación y determinismo.
"""
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluar import (clear_por_frame, emparejar_original, evaluar_datos, evaluar_decisor, hota_por_bins,  # noqa: E402
                     metricas_bin, preparar, resumen)

CFG = dict(clases_evaluadas=[1], clases_ignoradas=[0], clases_distractoras=[], umbral_area_ignorada=0.5)


def _gt_sintetico(n_obj=6, n_frames=40, semilla=0):
    rng = np.random.default_rng(semilla)
    filas = []
    for i in range(n_obj):
        x, y = rng.uniform(50, 800), rng.uniform(50, 500)
        vx, vy = rng.uniform(-3, 3), rng.uniform(-3, 3)
        ini, fin = rng.integers(1, 10), rng.integers(n_frames - 10, n_frames + 1)
        for f in range(ini, fin + 1):
            filas.append((f, i + 1, x + vx * f, y + vy * f, 40, 25, 1, 1, 1.0))
    return pd.DataFrame(filas, columns=["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])


def _pred_ruidosa(gt, semilla=1, ruido=3.0, p_falta=0.1, p_fp=0.05):
    rng = np.random.default_rng(semilla)
    p = gt[rng.random(len(gt)) > p_falta].copy()
    p[["x", "y"]] += rng.normal(0, ruido, (len(p), 2))
    p["id"] = p["id"] + 100
    fp = gt.sample(frac=p_fp, random_state=semilla).copy()
    fp[["x", "y"]] += 300; fp["id"] = 1000 + np.arange(len(fp))           # IDs únicos (un ID no se repite en un frame)
    p = pd.concat([p, fp])
    p["conf"] = 0.9
    return p[["frame", "id", "x", "y", "w", "h", "conf"]].sort_values("frame")


def prueba_sanidad():
    gt = _gt_sintetico()
    frames = np.arange(1, 41)
    pred = gt.assign(conf=1.0)
    r = resumen(evaluar_datos(preparar(gt, pred, frames, CFG)[0]))
    assert abs(r["HOTA"] - 100) < 1e-6 and abs(r["MOTA"] - 100) < 1e-6 and abs(r["IDF1"] - 100) < 1e-6, r
    print("  sanidad GT=pred: HOTA 100, MOTA 100, IDF1 100")


def prueba_cambio_id():
    gt = _gt_sintetico(n_obj=1)
    pred = gt.assign(conf=1.0)
    mitad = pred.frame.median()
    pred.loc[pred.frame > mitad, "id"] = 77
    r = resumen(evaluar_datos(preparar(gt, pred, np.arange(1, 41), CFG)[0]))
    assert r["IDSW"] == 1 and r["AssA"] < 70 and abs(r["DetA"] - 100) < 1e-6, r
    print(f"  cambio de ID: IDSW=1, AssA={r['AssA']:.1f}, DetA=100")


def prueba_replicas():
    gt = _gt_sintetico(n_obj=10, semilla=3)
    pred = _pred_ruidosa(gt, semilla=4, ruido=6)
    pred.loc[(pred.id == 103) & (pred.frame > 20), "id"] = 555           # provoca un IDSW
    data, _ = preparar(gt, pred, np.arange(1, 41), CFG)
    te = evaluar_datos(data)
    cl = clear_por_frame(data)
    for k, v in (("CLR_TP", "tp"), ("CLR_FN", "fn"), ("CLR_FP", "fp"), ("IDSW", "idsw")):
        assert te["CLEAR"][k] == sum(d[v] for d in cl), (k, te["CLEAR"][k], sum(d[v] for d in cl))
    un_bin = metricas_bin(hota_por_bins(data, ["x"] * 40)["x"])
    for k in ("HOTA", "DetA", "AssA", "LocA"):
        assert abs(un_bin[k] - 100 * te["HOTA"][k].mean()) < 1e-6, (k, un_bin[k], te["HOTA"][k].mean())
    dos = hota_por_bins(data, ["a"] * 20 + ["b"] * 20)
    assert np.allclose(dos["a"]["TP"] + dos["b"]["TP"], te["HOTA"]["HOTA_TP"])
    print(f"  réplicas = TrackEval (CLEAR por frame y HOTA por bins; HOTA {un_bin['HOTA']:.2f}, IDSW {te['CLEAR']['IDSW']})")


def prueba_motmetrics():
    try:
        import motmetrics as mm
    except ImportError:
        print("  (py-motmetrics no instalado: se omite)")
        return
    gt = _gt_sintetico(n_obj=8, semilla=5)
    pred = _pred_ruidosa(gt, semilla=6, ruido=5)
    pred.loc[(pred.id == 102) & (pred.frame > 25), "id"] = 777            # un cambio de ID real
    r = resumen(evaluar_datos(preparar(gt, pred, np.arange(1, 41), CFG)[0]))
    acc = mm.MOTAccumulator(auto_id=True)
    for f in range(1, 41):
        g, p = gt[gt.frame == f], pred[pred.frame == f]
        from evaluar import iou, _xyxy                                     # iou_matrix de motmetrics usa np.asfarray (NumPy<2)
        d = 1 - iou(_xyxy(g), _xyxy(p))
        d[d > 0.5] = np.nan
        acc.update(g.id.tolist(), p.id.tolist(), d)
    s = mm.metrics.create().compute(acc, metrics=["mota", "idf1", "num_switches"], name="x")
    assert abs(100 * s["mota"].iloc[0] - r["MOTA"]) < 1e-6, (s["mota"].iloc[0], r["MOTA"])
    assert abs(100 * s["idf1"].iloc[0] - r["IDF1"]) < 1e-6, (s["idf1"].iloc[0], r["IDF1"])
    assert int(s["num_switches"].iloc[0]) == r["IDSW"]
    print(f"  py-motmetrics coincide: MOTA {r['MOTA']:.2f}, IDF1 {r['IDF1']:.2f}, IDSW {r['IDSW']}")


def prueba_ignoradas_y_protocolos():
    gt = pd.DataFrame([(1, 1, 0, 0, 100, 100, 1, 0, 1.0),                 # región ignorada
                       (1, 2, 300, 300, 40, 20, 1, 1, 1.0),               # auto quieto
                       (1, 3, 500, 300, 40, 20, 1, 1, 1.0)],              # auto en movimiento
                      columns=["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])
    pred = pd.DataFrame([(1, 10, 50, 50, 20, 20, 0.9),                    # 100 % dentro → se descarta
                         (1, 11, 90, 90, 20, 20, 0.9),                    # 25 % dentro → FP
                         (1, 12, 300, 300, 40, 20, 0.9),                  # sobre el quieto
                         (1, 13, 500, 300, 40, 20, 0.9)],                 # sobre el móvil
                        columns=["frame", "id", "x", "y", "w", "h", "conf"])
    mov = pd.DataFrame([(1, 2, 0), (1, 3, 1)], columns=["frame", "id", "moving"])
    lat = pd.DataFrame([(1, 12, 1), (1, 13, 1), (1, 10, 0), (1, 11, 0)], columns=["frame", "id", "en_movimiento"])
    _, ex = preparar(gt, pred, [1], CFG)
    assert ex["descartadas_ignoradas"] == 1
    r0 = resumen(evaluar_datos(preparar(gt, pred, [1], CFG)[0]))
    assert r0["FP"] == 1 and r0["FN"] == 0
    r1 = resumen(evaluar_datos(preparar(gt, pred, [1], CFG, "moviles", mov)[0]))
    assert r1["FP"] == 1 and r1["GT_Dets"] == 1                            # el quieto es distractor: su pred no es FP
    r2 = resumen(evaluar_datos(preparar(gt, pred, [1], CFG, "e2e_moviles", mov, lat)[0]))
    assert r2["FP"] == 1 and r2["GT_Dets"] == 1                            # el quieto marcado móvil SÍ es FP
    re_ = resumen(evaluar_datos(preparar(gt, pred, [1], CFG, "estaticos", mov)[0]))
    assert re_["GT_Dets"] == 1 and re_["FP"] == 1
    print("  regiones ignoradas por área y protocolos todos/moviles/estaticos/e2e_moviles")


def prueba_moving_con_paneo():
    from ego import H_COLS
    from gt import derivar_moving
    fps, n = 30, 60
    ego = []
    for f in range(1, n + 1):
        H = np.eye(3); H[0, 2] = -5.0 if f > 1 else 0.0                   # la cámara avanza 5 px/frame → el suelo se mueve -5
        ego.append(dict(frame=f, H_ok=True, **{c: v for c, v in zip(H_COLS, H.ravel())}))
    ego = pd.DataFrame(ego)
    filas = []
    for f in range(1, n + 1):
        filas.append((f, 1, 600 - 5 * f, 300, 40, 20, 1, 1, 1.0))         # quieto en el mundo
        filas.append((f, 2, 200 - 5 * f + 3 * f, 400, 40, 20, 1, 1, 1.0))  # se mueve 3 px/frame en el mundo
    gt = pd.DataFrame(filas, columns=["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])
    m = derivar_moving(gt, ego, fps, 1280, "cenital")
    medio = m[(m.frame > 20) & (m.frame < 40)]
    assert (medio[medio.id == 1].moving == 0).all(), medio[medio.id == 1]
    assert (medio[medio.id == 2].moving == 1).all(), medio[medio.id == 2]
    print("  moving: el quieto con paneo sale 0 y el que avanza sale 1")


# ----------------------------------------------------------------------
# De punta a punta con video sintético
# ----------------------------------------------------------------------
@dataclass
class _Sec:
    nombre: str = "sintetico"
    fps: float = 30.0
    ucmc: dict = None
    video: str = None
    gt: str = None
    gt_frames: dict = None
    toma: str = "cenital"


def _video_sintetico(n=90, W=1280, Hh=720, paso_cam=3, semilla=0):
    import cv2
    rng = np.random.default_rng(semilla)
    mundo = cv2.GaussianBlur((rng.random((Hh + 100, W + n * paso_cam + 200)) * 255).astype(np.uint8), (0, 0), 2)
    mundo = cv2.cvtColor(mundo, cv2.COLOR_GRAY2BGR)
    autos = [dict(id=1, x=300, y=200, vx=0), dict(id=2, x=700, y=400, vx=0), dict(id=3, x=1000, y=250, vx=0),
             dict(id=4, x=100, y=500, vx=5), dict(id=5, x=500, y=100, vx=4)]
    frames, gt = [], []
    for f in range(1, n + 1):
        cx = paso_cam * f
        img = mundo[50:50 + Hh, cx:cx + W].copy()
        for a in autos:
            x = a["x"] + a["vx"] * f - paso_cam * f + 150
            y = a["y"]
            if 0 <= x and x + 48 < W:
                cv2.rectangle(img, (int(x), y), (int(x) + 48, y + 24), (40 * a["id"], 255 - 30 * a["id"], 200), -1)
                gt.append((f, a["id"], float(int(x)), float(y), 49.0, 25.0, 1, 1, 1.0))
        frames.append((f, img))
    gt = pd.DataFrame(gt, columns=["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])
    return frames, gt


def prueba_punta_a_punta():
    from correr import correr_secuencia
    from detecciones import CacheDetecciones
    from ego import EstimadorEgo, bins_ego, covariables
    from comunes import leer_mot

    frames, gt = _video_sintetico()
    rng = np.random.default_rng(1)
    d = gt[rng.random(len(gt)) > 0.05]
    dets = np.c_[d.x, d.y, d.x + d.w, d.y + d.h] + rng.normal(0, 1.0, (len(d), 4))
    cache = CacheDetecciones.desde_arrays(d.frame, np.c_[dets, np.full(len(d), 0.9), np.full(len(d), 2)], {2: "car"})

    # ego-movimiento: la cámara se mueve 3 px/frame a 1280 → 2.25 px a 960
    filas = EstimadorEgo(ancho_ref=1280).serie(frames, lambda f: np.c_[gt[gt.frame == f][["x", "y"]].to_numpy(),
                                                                       (gt[gt.frame == f][["x", "y"]].to_numpy() + [49, 25])])
    ego = covariables(filas, 30)
    med = ego.ego_px.iloc[1:].median()
    assert abs(med - 2.25) < 0.2 and ego.H_ok.mean() > 0.95, (med, ego.H_ok.mean())
    assert (bins_ego(ego, 30).iloc[5:-5] == "suave").all()

    sec = _Sec(ucmc=dict(hfov_deg=82, pitch_respaldo_deg=0))
    comun = dict(conf_entrada=0.1, min_hits=3)
    trk = ["propio_kf", "ucmc", "bytetrack", "botsort"]
    with tempfile.TemporaryDirectory() as tmp:
        correr_secuencia(sec, cache, trk, comun, tmp, frames=frames)
        correr_secuencia(sec, cache, ["propio_kf", "ucmc"], comun, Path(tmp) / "otra", frames=frames)
        from gt import derivar_moving
        mov = derivar_moving(gt, ego, 30, 1280, "cenital")
        res = {}
        for t in trk:
            pred = leer_mot(Path(tmp) / t / "sintetico.txt")
            lat = pd.read_csv(Path(tmp) / t / "sintetico_lateral.csv")
            data, extra = preparar(gt, pred, np.arange(1, 91), CFG)
            r = resumen(evaluar_datos(data))
            pares, _ = emparejar_original(data, extra)
            pf, pt, la = evaluar_decisor(pares, mov, lat, 30)
            res[t] = (r["HOTA"], r["IDSW"], pf["global"]["F1"])
            assert r["HOTA"] > 60, (t, r)
        for t in ("propio_kf", "ucmc"):
            a = (Path(tmp) / t / "sintetico.txt").read_bytes()
            b = (Path(tmp) / "otra" / t / "sintetico.txt").read_bytes()
            assert a == b, f"{t} no es determinista"
    txt = ", ".join(f"{k} HOTA {v[0]:.1f}/IDSW {v[1]}/F1-mov {v[2]:.2f}" for k, v in res.items())
    print(f"  punta a punta (sintético, paneo 3 px/frame): ego_px {med:.2f} ≈ 2.25; {txt}; determinista")


def _cache_de(gt, semilla=1):
    from detecciones import CacheDetecciones
    rng = np.random.default_rng(semilla)
    d = gt[rng.random(len(gt)) > 0.05]
    cajas = np.c_[d.x, d.y, d.x + d.w, d.y + d.h] + rng.normal(0, 1.0, (len(d), 4))
    return CacheDetecciones.desde_arrays(d.frame, np.c_[cajas, np.full(len(d), 0.9), np.full(len(d), 2)], {2: "car"})


def prueba_nucleo_equivale():
    """El núcleo de UCMC sobre la H cacheada da EXACTAMENTE lo mismo que el tracker completo frame a frame."""
    from barrido import calcular_entrada, config_manual, correr_nucleo
    from comunes import leer_mot
    from correr import correr_secuencia
    frames, gt = _video_sintetico()
    cache = _cache_de(gt)
    comun = dict(conf_entrada=0.1, min_hits=3)
    cam, cfg = config_manual(0.0, 80.0, 74.0, "centro")
    with tempfile.TemporaryDirectory() as tmp:
        t = {"nombre": "ucmc", "etiqueta": "ucmc_fija", "camara": cam, "config": cfg}
        correr_secuencia(_Sec(ucmc={}), cache, [t], comun, tmp, frames=frames)
        completo = leer_mot(Path(tmp) / "ucmc_fija" / "sintetico.txt")
    nucleo, diag = correr_nucleo(calcular_entrada(frames, comun, cache), 30.0, cache.nombres_clases, comun, cfg, cam, "centro")
    assert len(completo) == len(nucleo) > 0
    a = completo[["frame", "id", "x", "y", "w", "h"]].to_numpy(float)
    b = nucleo[["frame", "id", "x", "y", "w", "h"]].to_numpy(float)
    assert np.allclose(a, b, atol=0.01), "el núcleo cacheado no reproduce al tracker completo"
    assert diag["tamano_mediano_m"] > 0 and diag["singt_vel_implausible"] == 0.0, diag
    print(f"  núcleo UCMC con H cacheada = tracker completo ({len(nucleo)} cajas); tamaño mediano en el suelo "
          f"{diag['tamano_mediano_m']:.1f} m")


def prueba_integracion_barrido_y_evaluacion():
    """De punta a punta sobre archivos reales: video → ego → correr (con cámaras del barrido) → evaluar_run con GT.
    Comprueba la selección D17 y que el oráculo quede fuera de COMBINADO y de las comparaciones."""
    import shutil
    import cv2
    from barrido import barrer
    from comunes import DIR_CACHE, DIR_RUNS, Manifiesto, Secuencia, escribir_mot
    from correr import correr
    from ego import calcular as calcular_ego
    from evaluar import evaluar_run

    run = "_prueba_integracion"
    nombres = ["_prueba_aj", "_prueba_te1", "_prueba_te2"]
    tmp = Path(tempfile.mkdtemp())
    try:
        secs, caches = [], {}
        for k, nom in enumerate(nombres):
            frames, gt = _video_sintetico(n=75, semilla=k)
            vw = cv2.VideoWriter(str(tmp / f"{nom}.avi"), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (1280, 720))
            for _, img in frames:
                vw.write(img)
            vw.release()
            gt.to_csv(tmp / f"{nom}_gt.txt", header=False, index=False)
            secs.append(Secuencia(nombre=nom, video=str(tmp / f"{nom}.avi"), detector="sint", fps=30.0, toma="cenital",
                                  split="ajuste" if k == 0 else "test", gt=str(tmp / f"{nom}_gt.txt"),
                                  ucmc=dict(hfov_deg=74, pitch_respaldo_deg=0)))
            caches[nom] = _cache_de(gt, semilla=10 + k)
        man = Manifiesto(detectores={}, secuencias=secs, trackers=[], config_comun=dict(conf_entrada=0.1, min_hits=3),
                         evaluacion=dict(CFG, protocolos=["todos", "moviles"], bootstrap_n=200),
                         barrido=dict(grupos=dict(cenital=dict(pitch=[0, 15], altura=[40, 120], hfov=74, punto="centro"))))
        for s in secs:
            calcular_ego(s, caches[s.nombre], rehacer=True, ancho_ref=1280)
        df, sel, val = barrer(man, run, caches=caches)
        assert len(df) == 4 * len(secs) and set(sel.version) == {"singt", "oraculo_seq", "grupo_train"}
        o = sel[(sel.version == "oraculo_seq") & (sel.secuencia == "_prueba_te1")].HOTA_barrido.iloc[0]
        assert o >= df[df.secuencia == "_prueba_te1"].HOTA.max() - 1e-9
        sel_csv = DIR_RUNS / run / "barrido" / "seleccion.csv"
        man.trackers = ["propio_kf", "ucmc",
                        {"nombre": "ucmc", "etiqueta": "ucmc_grupo_train", "seleccion": str(sel_csv), "version": "grupo_train"},
                        {"nombre": "ucmc", "etiqueta": "ucmc_oraculo_seq", "seleccion": str(sel_csv), "version": "oraculo_seq"}]
        correr(man, run, caches=caches)
        s = evaluar_run(man, DIR_RUNS / run)
        m = s["metricas"]
        comb = m[(m.secuencia == "COMBINADO") & (m.protocolo == "todos")]
        assert set(comb.tracker) == {"propio_kf", "ucmc", "ucmc_grupo_train"}, comb.tracker.tolist()
        cota = m[m.secuencia == "COMBINADO_COTA"]
        assert set(cota.tracker) == {"ucmc_oraculo_seq"} and (cota.uso_gt == "test").all()
        assert "ucmc_oraculo_seq" not in set(s["comparaciones"].A) | set(s["comparaciones"].B)
        assert len(s["por_bin_ego"]) and len(s["decisor"]) and len(s["sin_gt"]) == 4 * len(secs)
        assert (m[m.protocolo == "todos"].HOTA > 50).all(), m[["tracker", "secuencia", "HOTA"]]
        hota = comb.set_index("tracker").HOTA.round(1).to_dict()
        print(f"  integración: barrido {len(df)} pruebas, selección D17 ok; evaluar_run con GT → COMBINADO {hota}, "
              f"oráculo solo en COMBINADO_COTA ({cota[cota.protocolo == 'todos'].HOTA.iloc[0]:.1f}) y fuera de comparaciones")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(DIR_RUNS / run, ignore_errors=True)
        for nom in nombres:
            for p in (DIR_CACHE / "ego" / f"{nom}.csv", DIR_CACHE / "entrada" / f"{nom}.npz", DIR_CACHE / "entrada" / f"{nom}.json"):
                p.unlink(missing_ok=True)


if __name__ == "__main__":
    for p in (prueba_sanidad, prueba_cambio_id, prueba_replicas, prueba_motmetrics, prueba_ignoradas_y_protocolos,
              prueba_moving_con_paneo, prueba_punta_a_punta, prueba_nucleo_equivale,
              prueba_integracion_barrido_y_evaluacion):
        print(p.__name__)
        p()
    print("TODO OK")
