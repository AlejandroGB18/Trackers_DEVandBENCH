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
8. Núcleo de UCMC = tracker completo; integración barrido → selección D17 → correr → evaluar.
9. Adaptador de UAVDT (formato real de GT, regiones ignoradas, atributos → grupos y split) y frames desde carpeta.
10. Detecciones externas (`tipo: archivo`): ida y vuelta del .txt, filtro de rango y caché; rutas portables.
11. Ajuste (detector por umbral con regiones ignoradas, tramos de ego por percentiles) y revisión de `moving`
    (clasificación de tracks, muestra, decisiones M/Q/A/D, acuerdo y calibración); reporte en la integración.
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
    Comprueba la selección D17, que el oráculo y el singt no validado queden fuera de COMBINADO y de las
    comparaciones, y que los bins y el decisor no incluyan las secuencias de ajuste."""
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
                        {"nombre": "ucmc", "etiqueta": "ucmc_oraculo_seq", "seleccion": str(sel_csv), "version": "oraculo_seq"},
                        {"nombre": "ucmc", "etiqueta": "ucmc_singt", "seleccion": str(sel_csv), "version": "singt"}]
        # en el sintético toda la rejilla da el mismo HOTA → ρ indefinida → singt no validado (D17.6)
        assert not sel[sel.version == "singt"].valido.any()
        correr(man, run, caches=caches)
        s = evaluar_run(man, DIR_RUNS / run)
        from reporte import generar_reporte
        rep = generar_reporte(DIR_RUNS / run, man)
        for f in ("resultados.md", "ranking.png", "p1.png", "p2.png"):
            assert (rep / f).exists(), f
        texto = (rep / "resultados.md").read_text()
        assert "ucmc_oraculo_seq | cota" in texto and "## P1" in texto and "## P2" in texto
        m = s["metricas"]
        comb = m[(m.secuencia == "COMBINADO") & (m.protocolo == "todos")]
        assert set(comb.tracker) == {"propio_kf", "ucmc", "ucmc_grupo_train"}, comb.tracker.tolist()
        cota = m[m.secuencia == "COMBINADO_COTA"]
        assert set(cota.tracker) == {"ucmc_oraculo_seq"} and (cota.uso_gt == "test").all()
        fuera = set(s["comparaciones"].A) | set(s["comparaciones"].B)
        assert "ucmc_oraculo_seq" not in fuera and "ucmc_singt" not in fuera
        novalid = m[m.secuencia == "COMBINADO_NO_VALIDADO"]
        assert set(novalid.tracker) == {"ucmc_singt"} and not novalid.en_ranking.any()
        # D14: bins de ego y decisor sin las secuencias de ajuste
        for k in ("por_bin_ego", "decisor", "latencias"):
            if len(s[k]):
                assert "_prueba_aj" not in set(s[k].secuencia), k
        assert len(s["por_bin_ego"]) and len(s["decisor"]) and len(s["sin_gt"]) == 5 * len(secs)
        assert (m[m.protocolo == "todos"].HOTA > 50).all(), m[["tracker", "secuencia", "HOTA"]]
        hota = comb.set_index("tracker").HOTA.round(1).to_dict()
        print(f"  integración: barrido {len(df)} pruebas, selección D17 ok; evaluar_run con GT → COMBINADO {hota}, "
              f"oráculo solo en COMBINADO_COTA ({cota[cota.protocolo == 'todos'].HOTA.iloc[0]:.1f}), singt no validado "
              "en COMBINADO_NO_VALIDADO, ambos fuera de comparaciones; bins/decisor sin ajuste")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(DIR_RUNS / run, ignore_errors=True)
        for nom in nombres:
            for p in (DIR_CACHE / "ego" / f"{nom}.csv", DIR_CACHE / "entrada" / f"{nom}.npz", DIR_CACHE / "entrada" / f"{nom}.json"):
                p.unlink(missing_ok=True)


def _uavdt_mini(raiz):
    """Árbol UAVDT mínimo con el formato real: 2 secuencias, GT de MOT, regiones ignoradas, atributos y frames."""
    import cv2
    raiz = Path(raiz)
    gtd = raiz / "UAV-benchmark-MOTD_v1.0" / "GT"
    gtd.mkdir(parents=True)
    # M0001 (ajuste, frontal, altitud baja): 2 autos en 5 frames, 1 región ignorada en el frame 2
    (gtd / "M0001_gt.txt").write_text("".join(f"{f},{i},{10 * i + f},20,30,15,1,-1,-1\n" for f in range(1, 6) for i in (1, 2)))
    (gtd / "M0001_gt_ignore.txt").write_text("2,7,500,300,80,40,1,-1,-1\n")
    # M0002 (test, cenital, altitud media): 1 auto hasta el frame 3 aunque haya 5 imágenes; sin regiones
    (gtd / "M0002_gt.txt").write_text("".join(f"{f},5,100,100,20,20,1,-1,-1\n" for f in range(1, 4)))
    (gtd / "M0002_gt_ignore.txt").write_text("")
    for split, seq, v in (("train", "M0001", "1,0,0,1,0,0,1,0,0,0"), ("test", "M0002", "0,1,0,0,1,0,0,0,1,0")):
        d = raiz / "M_attr" / split
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{seq}_attr.txt").write_text(v + "\n")
    for seq in ("M0001", "M0002"):
        d = raiz / "UAV-benchmark-M" / seq
        d.mkdir(parents=True)
        for f in range(1, 6):
            img = np.full((54, 102, 3), f * 40, np.uint8)
            cv2.imwrite(str(d / f"img{f:06d}.jpg"), img)
    return raiz


def prueba_adaptador_uavdt():
    """Conversión del GT, grupos de vuelo y split; frames de carpeta = frame k ↔ img00000k.jpg."""
    from adaptadores.uavdt import MARCA, entradas_manifiesto, escribir_secuencias, preparar
    from comunes import info_video, leer_frames, leer_gt
    with tempfile.TemporaryDirectory() as tmp:
        raiz = _uavdt_mini(Path(tmp) / "UAVDT")
        attr, resumen = preparar(raiz, verbose=False, correcciones=None)
        a = attr.set_index("secuencia")
        assert a.loc["M0001", "split"] == "ajuste" and a.loc["M0001", "grupo"] == "oblicua_baja"
        assert a.loc["M0002", "split"] == "test" and a.loc["M0002", "grupo"] == "cenital"
        assert a.loc["M0002", "luz"] == "noche" and a.loc["M0001", "vista"] == "frontal"
        g = leer_gt(raiz / "gt_benchmark" / "M0001" / "gt.txt")
        assert (g.clase == 1).sum() == 10 and set(g[g.clase == 1].id) == {1, 2}
        reg = g[g.clase == 0]
        assert len(reg) == 1 and reg.frame.iloc[0] == 2 and reg.id.iloc[0] < 0   # id negativo: no choca con autos
        r = {x["secuencia"]: x for x in resumen}
        assert r["M0002"]["ultimo_frame_gt"] == 3 and r["M0002"]["imagenes"] == 5
        ent = {e["nombre"]: e for e in entradas_manifiesto(attr, resumen, "det")}
        assert ent["M0002"]["rango"] == [1, 3] and ent["M0002"]["toma"] == "cenital"
        assert ent["M0001"]["ucmc"]["hfov_deg"] == 74 and ent["M0001"]["gt_frames"]["fin"] == 5
        y = Path(tmp) / "m.yaml"
        y.write_text("# cabecera que se conserva\nx: 1\n" + MARCA + "\nsecuencias: []\n")
        escribir_secuencias(y, list(ent.values()))
        import yaml
        d = yaml.safe_load(y.read_text())
        assert y.read_text().startswith("# cabecera") and d["x"] == 1 and len(d["secuencias"]) == 2
        carpeta = raiz / "UAV-benchmark-M" / "M0001"
        inf = info_video(carpeta)
        assert inf["n_frames"] == 5 and (inf["ancho"], inf["alto"]) == (102, 54) and inf["fps"] == 30.0
        fr = list(leer_frames(carpeta, 2, 4))
        assert [f for f, _ in fr] == [2, 3, 4] and abs(int(fr[0][1].mean()) - 80) <= 2   # frame 2 = img000002
        # D33: correcciones al GT oficial (fin, frames excluidos, tracks → región ignorada)
        from adaptadores.uavdt import OFFSET_IGNORADA, cargar_correcciones
        from comunes import Secuencia
        from gt import frames_anotados
        corr = {"M0001": {"excluir_frames": [3], "tracks_a_ignorada": [2]}, "M0002": {"fin": 2}}
        attr, resumen = preparar(raiz, verbose=False, correcciones=corr)
        g = leer_gt(raiz / "gt_benchmark" / "M0001" / "gt.txt")
        assert set(g[g.clase == 1].id) == {1} and set(g[g.clase == 1].frame) == {1, 2, 4, 5}
        ign = g[g.id == -(OFFSET_IGNORADA + 2)]
        assert len(ign) == 4 and (ign.clase == 0).all() and 3 not in set(g.frame)
        ent = {e["nombre"]: e for e in entradas_manifiesto(attr, resumen, "det")}
        assert ent["M0001"]["gt_frames"]["excluir"] == [3] and "excluir" not in ent["M0002"]["gt_frames"]
        assert ent["M0002"]["rango"] == [1, 2] and leer_gt(raiz / "gt_benchmark" / "M0002" / "gt.txt").frame.max() == 2
        s = Secuencia(nombre="M0001", video="x", detector="d", gt_frames=ent["M0001"]["gt_frames"])
        assert list(frames_anotados(s)) == [1, 2, 4, 5]
        try:
            preparar(raiz, verbose=False, correcciones={"M0001": {"tracks_a_ignorada": [99]}})
            raise AssertionError("un track inexistente debía fallar")
        except ValueError:
            pass
        real = cargar_correcciones()                    # el archivo versionado se lee y solo usa claves válidas
        assert real["M0601"]["fin"] == 319 and real["M1101"]["excluir_frames"] == [322]
    print("  adaptador UAVDT: GT oficial → clase 1, regiones → clase 0 con id < 0, grupos/split/luz desde M_attr, "
          "rango hasta el último frame con GT; carpeta de frames base 1; correcciones D33")


def prueba_detecciones_y_rutas():
    """`tipo: archivo`: el .txt de detectar_lab.py entra a la caché igual que una detección propia; rutas portables."""
    import json
    import os
    from comunes import Secuencia, cargar_manifiesto
    from detecciones import (CacheDetecciones, cachear, escribir_detecciones_txt, leer_detecciones_txt,
                             ruta_cache)
    frame = np.array([1, 1, 2, 4], np.int32)
    dets = np.array([[10, 20, 50, 40, .9, 0], [60, 60, 80, 90, .3, 3], [11, 21, 51, 41, .8, 0],
                     [0, 0, 5, 5, .06, 4]], np.float32)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        escribir_detecciones_txt(tmp / "det" / "_prueba_det.txt", frame, dets)
        f2, d2 = leer_detecciones_txt(tmp / "det" / "_prueba_det.txt")
        assert (f2 == frame).all() and np.allclose(d2, dets, atol=0.01)
        (tmp / "det" / "firma.json").write_text(json.dumps(dict(
            pesos_sha256="x", imgsz=640, conf=0.05, nombres_clases={"0": "car", "3": "bus", "4": "freight car"})))
        _uavdt_mini(tmp / "UAVDT")
        sec = Secuencia(nombre="_prueba_det", video=str(tmp / "UAVDT" / "UAV-benchmark-M" / "M0001"),
                        detector="ext", rango=(1, 3))
        perfil = dict(tipo="archivo", carpeta=str(tmp / "det"))
        try:
            c = CacheDetecciones(cachear(sec, "ext", perfil))
            assert len(c.por_frame(1)) == 2 and len(c.por_frame(1, conf_min=0.5)) == 1
            assert len(c.por_frame(4)) == 0                      # fuera de rango (1–3): no entra
            assert c.nombres_clases[4] == "freight car"
            c2 = CacheDetecciones(cachear(sec, "ext", dict(perfil, clases=["car"])))
            assert len(c2.por_frame(1)) == 1                     # filtro por nombre de clase
        finally:
            for p in (ruta_cache(sec, "ext"), ruta_cache(sec, "ext").with_suffix(".json")):
                p.unlink(missing_ok=True)
        # rutas: relativas a datos_raiz; BENCH_DATOS la sobrescribe
        y = tmp / "conf" / "m.yaml"
        y.parent.mkdir()
        y.write_text("datos_raiz: ../datosA\ndetectores: {d: {tipo: archivo, carpeta: detecciones/d}}\n"
                     "secuencias: [{nombre: s, video: UAVDT/x, detector: d, gt: UAVDT/g.txt}]\n")
        previo = os.environ.pop("BENCH_DATOS", None)     # la prueba no debe depender del BENCH_DATOS de quien la corre
        try:
            m = cargar_manifiesto(y)
            assert m.secuencias[0].video == str((tmp / "datosA" / "UAVDT" / "x").resolve())
            assert m.detectores["d"]["carpeta"] == str((tmp / "datosA" / "detecciones" / "d").resolve())
            os.environ["BENCH_DATOS"] = str(tmp / "lab")
            assert cargar_manifiesto(y).secuencias[0].gt == str((tmp / "lab" / "UAVDT" / "g.txt").resolve())
        finally:
            if previo is None:
                os.environ.pop("BENCH_DATOS", None)
            else:
                os.environ["BENCH_DATOS"] = previo
    print("  detecciones externas: .txt ida y vuelta, rango y filtro de clase en la caché; "
          "rutas relativas a datos_raiz y BENCH_DATOS")


def prueba_ajuste_y_revision():
    from ajuste import _conteos_por_umbral, UMBRALES, cargar_tramos, etiquetar, tramos
    from detecciones import CacheDetecciones
    from comunes import Secuencia
    from revision import acuerdo, aplicar, calibracion, clasificar_tracks, elegir
    # --- detector: 2 autos; 1 detección buena (0.9), 1 FP débil (0.2), 1 FP dentro de región ignorada (0.8)
    gt = pd.DataFrame([(1, 1, 10, 10, 20, 20, 1, 1, 1), (1, 2, 100, 100, 20, 20, 1, 1, 1),
                       (1, -1, 300, 300, 50, 50, 1, 0, -1)],
                      columns=["frame", "id", "x", "y", "w", "h", "considerar", "clase", "visibilidad"])
    cache = CacheDetecciones.desde_arrays([1, 1, 1], [[10, 10, 30, 30, .9, 0], [200, 200, 220, 220, .2, 0],
                                                      [310, 310, 330, 330, .8, 0]], {0: "car"})
    tp, fp, fn = _conteos_por_umbral(gt, cache, [1], CFG)
    k05, k50 = list(UMBRALES).index(0.05), list(UMBRALES).index(0.5)
    assert (tp[k05], fp[k05], fn[k05]) == (1, 1, 1), (tp[k05], fp[k05], fn[k05])   # la de la región no cuenta
    assert (tp[k50], fp[k50], fn[k50]) == (1, 0, 1)
    # --- tramos: 6 secuencias, ego creciente; con mucho GT en "alto" quedan 3 tramos
    secs, egos, gts = [], {}, {}
    for i in range(6):
        nom = f"s{i}"
        secs.append(Secuencia(nombre=nom, video="x", detector="d", fps=30.0, gt_frames=dict(inicio=1, fin=300)))
        egos[nom] = pd.DataFrame(dict(frame=np.arange(1, 301), ego_px=np.linspace(0, 6, 300) + i * 0.1, H_ok=True))
        gts[nom] = pd.DataFrame(dict(frame=np.repeat(np.arange(1, 301), 5), id=1, x=0, y=0, w=1, h=1, considerar=1,
                                     clase=1))
    frames_de = lambda sec, gt: np.arange(1, 301)
    tabla, prop = tramos(secs, egos, gts, frames_de)
    assert prop["modo"] == "tres" and len(prop["cortes_px"]) == 2 and set(tabla.tramo) == {"bajo", "medio", "alto"}
    _, prop2 = tramos(secs[:2], {k: egos[k] for k in ("s0", "s1")}, gts, frames_de)   # 2 secuencias: no alcanza
    assert prop2["modo"] == "dos" and prop2["etiquetas"] == ["bajo", "alto"]
    c, e = cargar_tramos(dict(cortes_px=[1.0, 2.0], etiquetas=["bajo", "medio", "alto"]))
    lab = etiquetar(pd.Series([0.5, 1.5, 2.5, np.nan]), c, e)
    assert lab.tolist() == ["bajo", "medio", "alto", "H_no_fiable"]
    # --- revisión: 4 tracks (seguro móvil, seguro quieto, cambio, dudoso)
    filas = []
    for tid, patron in ((1, [1] * 30), (2, [0] * 30), (3, [0] * 15 + [1] * 15), (4, [-1] * 20 + [1] * 10)):
        for f, m in enumerate(patron, 1):
            filas.append((f, tid, m, 10.0 if m == 1 else 0.5 if m == 0 else np.nan, 20.0))
    mov = pd.DataFrame(filas, columns=["frame", "id", "moving", "d_px", "L_px"])
    t = elegir(clasificar_tracks(mov))
    cat = dict(zip(t.id, t.categoria))
    assert cat == {1: "seguro", 2: "seguro", 3: "cambio", 4: "dudoso"}
    assert t.revisar.sum() == 3 and t.muestra_seguros.sum() == 1          # cambio + dudoso + 10 % de 2 seguros
    dec = pd.DataFrame(dict(id=[3, 4] + t[t.muestra_seguros].id.tolist(), decision=["M", "D", "A"]))
    m2, t2, faltan = aplicar(mov, t, dec)
    assert (m2[m2.id == 3].moving == 1).all() and (m2[m2.id == 4].moving == -1).all() and len(faltan) == 0
    assert acuerdo(t2)["acuerdo"] == 1.0
    cal = calibracion(mov, t2, min_px=3.0)
    assert len(cal) == 15 and cal.acuerdo.between(0, 1).all()
    print("  ajuste: curva del detector respeta regiones ignoradas; tramos por percentiles (3 o 2 según datos); "
          "revisión: categorías, muestra 10 %, M/Q/A/D, acuerdo y calibración")


if __name__ == "__main__":
    for p in (prueba_sanidad, prueba_cambio_id, prueba_replicas, prueba_motmetrics, prueba_ignoradas_y_protocolos,
              prueba_moving_con_paneo, prueba_punta_a_punta, prueba_nucleo_equivale,
              prueba_integracion_barrido_y_evaluacion, prueba_adaptador_uavdt, prueba_detecciones_y_rutas, prueba_ajuste_y_revision):
        print(p.__name__)
        p()
    print("TODO OK")
