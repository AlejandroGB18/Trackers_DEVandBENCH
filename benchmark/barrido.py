"""
barrido.py — "Fuerza bruta" de la cámara de UCMCTrack (protocolo D17)
=====================================================================

Los datasets públicos no traen telemetría, así que la cámara de UCMC (pitch y altura; el hfov sale de la ficha) se
busca en una rejilla. Para que la comparación con los otros 3 trackers sea justa, la cámara se elige de tres formas y
se reporta cada una con su etiqueta:

  versión        cómo se elige                                         uso_gt   ¿ranking?
  grupo_train    la mejor de la rejilla en las secuencias de AJUSTE     train    sí (número principal)
                 de su grupo de vuelo, aplicada a las de test
  singt          por secuencia, con un criterio SIN GT (abajo)          no       sí, si el criterio se valida en ajuste
  oraculo_seq    la mejor de la rejilla en cada secuencia, mirando     test     NO: cota superior etiquetada
                 su GT

`ucmc` a secas (calibración automática en línea) sigue siendo otra versión, la que no necesita nada.

Por qué solo pitch × altura (docs/investigacion-ucmc-fuerza-bruta.md §2.4): en el modelo de UCMC la altura es una
escala global, equivalente a reescalar sus ruidos de Kalman y su umbral `a`; el hfov y el pitch son casi colineales.
El hfov se fija por dataset (ficha) y la altura solo se mueve dentro de la banda física declarada del grupo.

Criterio sin GT (menor = mejor), calculado con las salidas de UCMC en cada punto de la rejilla:
  - pendiente: |pendiente de log(tamaño en el suelo) frente a la fila de la imagen|. Con la cámara correcta un auto
    mide lo mismo cerca y lejos. Tamaño = lado mayor de la caja proyectada (cenital) o ancho de su base (oblicua).
  - escala (solo cenital): |log(mediana del lado mayor / 4.5 m)|.
  - velocidad: 5 × fracción de tracks emitidos con |v| > 45 m/s en el suelo.
Se valida en las secuencias de ajuste con la correlación de Spearman entre el criterio y HOTA en la rejilla.

Rapidez: la H (Estabilizador) y las detecciones a resolución de trabajo se calculan UNA vez por secuencia y se guardan
(cache/entrada/<seq>.npz). Cada punto de la rejilla solo ejecuta TrackerUCMC.seguir(), sin decodificar el video.
"""
import itertools
import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from comunes import DIR_CACHE, DIR_RUNS, fps_de, guardar_json, hash_dict, leer_frames, leer_gt, rango_frames, versiones

UMBRAL_VEL_MS = 45.0
LARGO_REF_M = 4.5


# ======================================================================
# 1. Entrada cacheada: H + detecciones de trabajo por frame
# ======================================================================
class Entrada:
    """Lo que necesita TrackerUCMC.seguir() frame a frame, sin el video."""

    def __init__(self, frames, Hs, oks, dets, forma):
        self.frames, self.Hs, self.oks, self.dets, self.forma = frames, Hs, oks, dets, tuple(forma)

    def __iter__(self):
        return zip(self.frames, self.Hs, self.oks, self.dets)

    def guardar(self, ruta, firma):
        n = np.array([len(d) for d in self.dets], np.int32)
        todas = np.concatenate(self.dets) if len(self.dets) and n.sum() else np.zeros((0, 6), np.float32)
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(ruta, frames=np.asarray(self.frames, np.int32), Hs=np.asarray(self.Hs), oks=np.asarray(self.oks),
                            n=n, dets=todas, forma=np.asarray(self.forma))
        guardar_json(Path(ruta).with_suffix(".json"), dict(firma=firma))

    @classmethod
    def cargar(cls, ruta):
        z = np.load(ruta)
        cortes = np.cumsum(z["n"])[:-1]
        return cls(z["frames"].tolist(), list(z["Hs"]), z["oks"].tolist(), np.split(z["dets"], cortes), z["forma"])


def calcular_entrada(frames_bgr, config_comun, cache, semilla=0):
    """Pasos 1–3 del pipeline común (escala, estabilización, entrada) con use_proposals=False, como en correr.py."""
    from comun import Config, Escala, EntradaDetecciones, Estabilizador
    from correr import _aplicar
    cfg = _aplicar(Config(), {**{k: v for k, v in config_comun.items() if k != "conf_entrada"}, "use_proposals": False})
    conf_entrada = float(config_comun.get("conf_entrada", 0.10))
    est, ent, esc = Estabilizador(cfg), EntradaDetecciones(cfg, 30.0), None
    frames, Hs, oks, dets, forma = [], [], [], [], None
    cv2.setRNGSeed(semilla)
    for f, img in frames_bgr:
        if esc is None:
            esc, forma = Escala(cfg, img.shape), img.shape
        _, gray = esc.frame(img)
        H, ok = est.paso(gray)
        frames.append(f); Hs.append(np.asarray(H, np.float64)); oks.append(bool(ok))
        dets.append(ent.preparar(cache.por_frame(f, conf_entrada), esc, gray, H, ok).astype(np.float32))
    return Entrada(frames, Hs, oks, dets, forma)


def entrada_de(sec, cache, config_comun, semilla=0, rehacer=False):
    ruta = DIR_CACHE / "entrada" / f"{sec.nombre}.npz"
    firma = dict(config_comun=config_comun, detecciones=cache.meta.get("firma"), semilla=semilla, rango=list(rango_frames(sec)))
    if ruta.exists() and not rehacer:
        previa = json.load(open(ruta.with_suffix(".json")))["firma"]
        if hash_dict(previa) == hash_dict(firma):
            return Entrada.cargar(ruta)
    e = calcular_entrada(leer_frames(sec.video, *rango_frames(sec)), config_comun, cache, semilla)
    e.guardar(ruta, firma)
    return e


# ======================================================================
# 2. Una corrida del núcleo de UCMC con una cámara dada
# ======================================================================
def config_manual(pitch, altura, hfov, punto, aspecto=1.0):
    """(camara, config) de UCMC con la cámara FIJA (como si viniera de telemetría)."""
    return (dict(hfov_deg=float(hfov), pitch_respaldo_deg=float(pitch), altura_m=float(altura), aspecto_px=float(aspecto)),
            dict(ucmc_calibrar_pitch=False, ucmc_calibrar_altura=False, ucmc_punto=punto))


def correr_nucleo(entrada, fps, nombres_clases, config_comun, config_ucmc, camara, punto_tamano="base"):
    """Corre UCMC sobre la entrada cacheada. Devuelve (DataFrame MOT, diagnóstico sin GT)."""
    from comun import Escala, a_salida
    from correr import crear_tracker
    from tracker_ucmc import CalibradorCamara
    trk = crear_tracker("ucmc", fps, nombres_clases, config_comun, config_ucmc, camara)
    trk.escala = Escala(trk.cfg, entrada.forma)
    trk.calibrador = CalibradorCamara(trk.cfg, trk.fps, trk.camara, trk.escala.ww, trk.escala.wh)
    filas, vel, tam_v, tam_log = [], [], [], []
    ch = trk.cfg.conf_high
    for f, H, ok, dets in entrada:
        conf = trk.seguir(dets, H, ok)
        trk.frame += 1
        for s in a_salida(conf, trk.escala, nombres_clases):
            x1, y1, x2, y2 = s.caja
            filas.append((f, s.id, x1, y1, x2 - x1, y2 - y1, s.conf, s.clase))
        vel.append(trk.nucleo.vel_suelo)
        d = dets[(dets[:, 4] >= ch) & (dets[:, 5] >= 0)] if len(dets) else dets
        if len(d):
            v, t = _tamanos(d, trk.calibrador.mapa, punto_tamano)
            tam_v.append(v / trk.escala.wh); tam_log.append(t)
    pred = pd.DataFrame(filas, columns=["frame", "id", "x", "y", "w", "h", "conf", "clase"])
    vel = np.concatenate(vel) if vel else np.zeros(0)
    tv = np.concatenate(tam_v) if tam_v else np.zeros(0)
    tl = np.concatenate(tam_log) if tam_log else np.zeros(0)
    return pred, _criterio(tv, tl, vel, punto_tamano, trk.nucleo.n_fuera)


def _tamanos(d, mapa, punto):
    """(fila de la base en px, log del tamaño en metros) de cada detección válida."""
    I = np.tile(np.eye(2), (len(d), 1, 1))
    if punto == "centro":                                        # cenital: lado mayor de la caja proyectada
        esq = [np.c_[d[:, 0], d[:, 1]], np.c_[d[:, 2], d[:, 1]], np.c_[d[:, 2], d[:, 3]], np.c_[d[:, 0], d[:, 3]]]
        P, oks = [], np.ones(len(d), bool)
        for e in esq:
            xy, _, ok = mapa.uv2xy(e.astype(np.float64), I); P.append(xy); oks &= ok
        lados = np.stack([np.linalg.norm(P[(i + 1) % 4] - P[i], axis=1) for i in range(4)], 1)
        t = lados.max(1)
    else:                                                        # oblicua: ancho de la base
        a, _, oka = mapa.uv2xy(np.c_[d[:, 0], d[:, 3]].astype(np.float64), I)
        b, _, okb = mapa.uv2xy(np.c_[d[:, 2], d[:, 3]].astype(np.float64), I)
        t, oks = np.linalg.norm(b - a, axis=1), oka & okb
    oks &= t > 1e-3
    return d[oks, 3], np.log(t[oks])


def _criterio(v_norm, log_t, vel, punto, n_fuera):
    pend = float(abs(np.polyfit(v_norm, log_t, 1)[0])) if len(log_t) >= 10 and np.ptp(v_norm) > 0.05 else np.nan
    esc = float(abs(np.median(log_t) - np.log(LARGO_REF_M))) if punto == "centro" and len(log_t) else 0.0
    fv = float((vel > UMBRAL_VEL_MS).mean()) if len(vel) else 0.0
    total = (pend if pend == pend else 0.0) + esc + 5.0 * fv
    return dict(singt=total, singt_pendiente=pend, singt_escala=esc, singt_vel_implausible=fv,
                tamano_mediano_m=float(np.exp(np.median(log_t))) if len(log_t) else np.nan, n_fuera=int(n_fuera))


# ======================================================================
# 3. Rejilla, evaluación y selección
# ======================================================================
def rejilla_de(barrido, grupo, toma):
    g = (barrido.get("grupos") or {}).get(grupo) or (barrido.get("grupos") or {}).get(toma)
    if g is None:
        raise KeyError(f"No hay rejilla para el grupo '{grupo}' (ni para la toma '{toma}') en `barrido.grupos`")
    punto = g.get("punto") or ("centro" if toma == "cenital" else "base")
    return [dict(pitch=p, altura=a, hfov=g["hfov"], punto=punto, aspecto=g.get("aspecto", 1.0))
            for p, a in itertools.product(g["pitch"], g["altura"])], g


def barrer(manifiesto, nombre_run, secuencias=None, caches=None, entradas=None, gts=None):
    """Barre la rejilla en todas las secuencias (con o sin GT) y escribe runs/<run>/barrido/."""
    from detecciones import CacheDetecciones, ruta_cache
    from evaluar import evaluar_datos, preparar, resumen
    from gt import frames_anotados

    dest = DIR_RUNS / nombre_run / "barrido"
    dest.mkdir(parents=True, exist_ok=True)
    b = manifiesto.barrido
    secs = [s for s in manifiesto.secuencias if secuencias is None or s.nombre in secuencias]
    filas, res_te = [], {}                                     # res_te[(seq, i)] = resultado TrackEval
    for sec in secs:
        cache = (caches or {}).get(sec.nombre) or CacheDetecciones(ruta_cache(sec, sec.detector))
        ent = (entradas or {}).get(sec.nombre) or entrada_de(sec, cache, manifiesto.config_comun)
        fps = float(sec.fps) if sec.fps else fps_de(sec)
        gt = (gts or {}).get(sec.nombre)
        if gt is None and sec.gt:
            gt = leer_gt(sec.gt)
        frames = frames_anotados(sec, gt) if gt is not None else None
        rej, _ = rejilla_de(b, sec.grupo_barrido, sec.toma)
        print(f"[barrer] {sec.nombre} ({sec.grupo_barrido}, {sec.split}): {len(rej)} cámaras")
        for i, c in enumerate(rej):
            cam, cfg = config_manual(c["pitch"], c["altura"], c["hfov"], c["punto"], c["aspecto"])
            pred, diag = correr_nucleo(ent, fps, cache.nombres_clases, manifiesto.config_comun, cfg, cam, c["punto"])
            fila = dict(secuencia=sec.nombre, grupo=sec.grupo_barrido, split=sec.split, i=i, **c, **diag)
            if gt is not None:
                r = evaluar_datos(preparar(gt, pred, frames, manifiesto.evaluacion)[0])
                res_te[(sec.nombre, i)] = r
                m = resumen(r)
                fila.update({k: m[k] for k in ("HOTA", "DetA", "AssA", "IDF1", "IDSW")})
            filas.append(fila)
    df = pd.DataFrame(filas)
    df.round(5).to_csv(dest / "resultados.csv", index=False)
    sel, val = seleccionar(df, res_te, b)
    sel.to_csv(dest / "seleccion.csv", index=False)
    val.round(4).to_csv(dest / "validacion_singt.csv", index=False)
    guardar_json(dest / "barrido.json", dict(barrido=b, config_comun=manifiesto.config_comun, versiones=versiones(),
                                             n_pruebas=int(len(df))))
    print(f"[barrer] {len(df)} pruebas → {dest}")
    return df, sel, val


def seleccionar(df, res_te, b):
    """Elige la cámara de cada secuencia en las tres versiones. Devuelve (seleccion, validacion_singt)."""
    from evaluar import combinar, resumen
    from scipy.stats import spearmanr
    cols = ["pitch", "altura", "hfov", "punto", "aspecto"]
    sel = []
    con_gt = "HOTA" in df.columns
    # validación del criterio sin GT en ajuste
    val = []
    if con_gt:
        for s, x in df[(df.split == "ajuste") & df.HOTA.notna()].groupby("secuencia"):
            rho = spearmanr(x.singt, x.HOTA).statistic if x.singt.nunique() > 1 and x.HOTA.nunique() > 1 else np.nan
            val.append(dict(secuencia=s, rho_singt_hota=rho, n=len(x)))
    val = pd.DataFrame(val, columns=["secuencia", "rho_singt_hota", "n"])
    rho_min = float(b.get("singt_rho_min", 0.6))
    singt_valido = bool(len(val) and val.rho_singt_hota.mean() <= -rho_min)

    for s, x in df.groupby("secuencia"):
        x = x.sort_values("i")
        # sin GT
        r = x.loc[x.singt.idxmin()]
        sel.append(dict(secuencia=s, version="singt", uso_gt="no", valido=singt_valido, **{c: r[c] for c in cols},
                        HOTA_barrido=r.get("HOTA", np.nan)))
        # oráculo
        if con_gt and x.HOTA.notna().any():
            r = x.sort_values(["HOTA", "AssA"], ascending=False).iloc[0]
            sel.append(dict(secuencia=s, version="oraculo_seq", uso_gt="test", valido=True, **{c: r[c] for c in cols},
                            HOTA_barrido=r["HOTA"]))
    # por grupo, elegida en ajuste
    if con_gt:
        for g, x in df.groupby("grupo"):
            aj = x[(x.split == "ajuste") & x.HOTA.notna()]
            if aj.empty:
                print(f"[barrer] grupo '{g}': sin secuencias de ajuste con GT → no hay versión grupo_train")
                continue
            mejor, mejor_m = None, None
            for i in sorted(aj.i.unique()):
                m = resumen(combinar({s: res_te[(s, i)] for s in aj[aj.i == i].secuencia}))
                if mejor_m is None or (m["HOTA"], m["AssA"]) > (mejor_m["HOTA"], mejor_m["AssA"]):
                    mejor, mejor_m = i, m
            r = aj[aj.i == mejor].iloc[0]
            for s in x.secuencia.unique():
                sel.append(dict(secuencia=s, version="grupo_train", uso_gt="train", valido=True,
                                **{c: r[c] for c in cols}, HOTA_barrido=mejor_m["HOTA"]))
    return pd.DataFrame(sel), val


def camara_de_seleccion(ruta, secuencia, version):
    """(camara, config) de UCMC para una secuencia según seleccion.csv (lo usa correr.py)."""
    s = pd.read_csv(ruta)
    r = s[(s.secuencia == secuencia) & (s.version == version)]
    if r.empty:
        raise KeyError(f"{ruta}: no hay cámara '{version}' para '{secuencia}' (¿grupo sin secuencias de ajuste?)")
    r = r.iloc[0]
    return config_manual(r.pitch, r.altura, r.hfov, r.punto, r.get("aspecto", 1.0))


def seleccion_valida(ruta, version):
    """False si la versión no pasó su validación en ajuste (p. ej. `singt` con Spearman > −ρ_min, D17.6)."""
    s = pd.read_csv(ruta)
    s = s[s.version == version]
    return bool(len(s)) and bool(s["valido"].astype(bool).all()) if "valido" in s.columns else bool(len(s))


def fraccion_rejilla_gana(df, metricas_run, metrica="HOTA"):
    """Por secuencia y rival: fracción de la rejilla de UCMC que supera al rival (metricas.csv de un run normal)."""
    m = metricas_run[(metricas_run.protocolo == "todos") & (~metricas_run.secuencia.str.startswith("COMBINADO"))]
    out = []
    for (s, t), x in m.groupby(["secuencia", "tracker"]):
        g = df[df.secuencia == s][metrica].dropna()
        if len(g):
            out.append(dict(secuencia=s, rival=t, rival_valor=float(x[metrica].iloc[0]),
                            fraccion_rejilla_gana=float((g > x[metrica].iloc[0]).mean()), n_rejilla=len(g)))
    return pd.DataFrame(out)
