"""
correr.py — Corre los trackers sobre las detecciones cacheadas
===============================================================

Para cada secuencia:
  - Un tracker NUEVO por secuencia (nuestros trackers no guardan estado entre videos).
  - Mismas detecciones (caché), mismo fps real y `use_proposals=False` en todos.
  - Se decodifica el video una sola vez y los frames se reparten a todos los trackers (los 4 calculan su H).
  - Semilla de OpenCV fija (`cv2.setRNGSeed`): el RANSAC del Estabilizador es aleatorio.

Salidas en runs/<run>/<tracker>/:
  <seq>.txt           MOT de 10 columnas, frames del video base 1: frame,id,x,y,w,h,conf,clase,-1,-1
  <seq>_lateral.csv   frame,id,en_movimiento,dx,dy,paralaje (lo que BoxMOT/TrackEval no pueden llevar)
  <seq>_tiempos.csv   ms por etapa y frame (tracker.tiempos_ms)
y runs/<run>/run.json con configuración, versiones y firmas de las cachés.

Política de salida (igual para los 4): solo tracks CONFIRMADOS que tienen detección en el frame.
"""
import time
from dataclasses import fields, replace
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from comunes import DIR_RUNS, escribir_mot, fps_de, guardar_json, hash_dict, leer_frames, rango_frames, versiones

TRACKERS_DISPONIBLES = ("propio_kf", "ucmc", "bytetrack", "botsort")


def _aplicar(cfg, cambios):
    validos = {f.name for f in fields(cfg)}
    desconocidos = set(cambios) - validos
    if desconocidos:
        raise ValueError(f"Parámetros desconocidos para {type(cfg).__name__}: {sorted(desconocidos)}")
    return replace(cfg, **cambios)


def crear_tracker(nombre, fps, nombres_clases, config_comun=None, config_propia=None, camara_ucmc=None):
    """Instancia uno de los 4 trackers con use_proposals=False forzado."""
    comun = {k: v for k, v in (config_comun or {}).items() if k != "conf_entrada"}
    cambios = {**comun, **(config_propia or {}), "use_proposals": False}
    if nombre == "propio_kf":
        from tracker_propio import ConfigPropio, TrackerPropio
        return TrackerPropio(fps, _aplicar(ConfigPropio(), cambios), nombres_clases)
    if nombre == "ucmc":
        from tracker_ucmc import CamaraUCMC, ConfigUCMC, TrackerUCMC
        return TrackerUCMC(fps, CamaraUCMC(**(camara_ucmc or {})), _aplicar(ConfigUCMC(), cambios), nombres_clases)
    from comun import Config
    if nombre == "bytetrack":
        from tracker_bytetrack import TrackerByteTrack
        return TrackerByteTrack(fps, _aplicar(Config(), cambios), nombres_clases)
    if nombre == "botsort":
        from tracker_botsort import TrackerBoTSORT
        return TrackerBoTSORT(fps, _aplicar(Config(), cambios), nombres_clases)
    raise ValueError(f"Tracker desconocido: {nombre}. Disponibles: {TRACKERS_DISPONIBLES}")


USO_GT_POR_VERSION = {"oraculo_seq": "test", "grupo_train": "train", "singt": "no"}


def _normalizar_trackers(lista):
    """Admite 'propio_kf' o un dict:
        {nombre: propio_kf, etiqueta: propio_kf_v2, config: {...}}
        {nombre: ucmc, etiqueta: ucmc_fija, camara: {pitch_respaldo_deg: 40, altura_m: 50}, config: {ucmc_calibrar: false}}
        {nombre: ucmc, etiqueta: ucmc_grupo_train, seleccion: runs/x/barrido/seleccion.csv, version: grupo_train}
    `camara` se combina sobre el `ucmc` de cada secuencia. `seleccion` + `version` toman la cámara elegida por
    `bench.py barrer` para cada secuencia. `uso_gt` (no | train | test) dice si la configuración se eligió mirando GT;
    las de `test` (oráculos) quedan fuera de COMBINADO y de las comparaciones."""
    out = []
    for t in lista:
        t = {"nombre": t} if isinstance(t, str) else dict(t)
        t.setdefault("etiqueta", t["nombre"])
        t.setdefault("config", {})
        t.setdefault("camara", {})
        t.setdefault("uso_gt", USO_GT_POR_VERSION.get(t.get("version"), "no"))
        out.append(t)
    return out


def config_de_tracker(t, sec):
    """(config_propia, camara_ucmc) de una entrada de `trackers` para una secuencia."""
    config = dict(t["config"])
    camara = {**(sec.ucmc or {}), **t["camara"]}
    if t.get("seleccion"):
        from barrido import camara_de_seleccion
        cam, cfg = camara_de_seleccion(t["seleccion"], sec.nombre, t["version"])
        camara.update(cam)
        config.update(cfg)
    return config, camara


def correr_secuencia(sec, cache, trackers, config_comun, dir_run, frames=None, semilla=0):
    """Corre todos los trackers sobre una secuencia. `frames` = iterable (frame, imagen); None = leer el video.
    Devuelve {etiqueta: ms medianos por frame}."""
    fps = fps_de(sec) if frames is None else float(sec.fps)
    conf_entrada = float(config_comun.get("conf_entrada", 0.10))
    trackers = _normalizar_trackers(trackers)
    inst = {}
    for t in trackers:
        cfg_t, cam_t = config_de_tracker(t, sec)
        inst[t["etiqueta"]] = crear_tracker(t["nombre"], fps, cache.nombres_clases, config_comun, cfg_t, cam_t)
    filas = {k: [] for k in inst}
    lat = {k: [] for k in inst}
    tiempos = {k: [] for k in inst}
    if frames is None:
        frames = leer_frames(sec.video, *rango_frames(sec))
    cv2.setRNGSeed(semilla)
    for f, img in frames:
        dets = cache.por_frame(f, conf_entrada)
        for k, trk in inst.items():
            t0 = time.perf_counter()
            salida = trk.actualizar(img, dets)
            total = (time.perf_counter() - t0) * 1e3
            tiempos[k].append(dict(frame=f, total_ms=total, **{f"{e}_ms": v for e, v in trk.tiempos_ms.items()}))
            for s in salida:
                filas[k].append((f, s.id, *s.caja, s.conf, s.clase))
                lat[k].append((f, s.id, int(s.en_movimiento), *s.desplazamiento_px, int(s.paralaje)))
    resumen = {}
    for k in inst:
        d = Path(dir_run) / k
        escribir_mot(d / f"{sec.nombre}.txt", filas[k])
        pd.DataFrame(lat[k], columns=["frame", "id", "en_movimiento", "dx", "dy", "paralaje"]).to_csv(
            d / f"{sec.nombre}_lateral.csv", index=False)
        tp = pd.DataFrame(tiempos[k])
        tp.to_csv(d / f"{sec.nombre}_tiempos.csv", index=False)
        resumen[k] = float(tp.total_ms.median()) if len(tp) else float("nan")
    return resumen


def correr(manifiesto, nombre_run, secuencias=None, semilla=0, caches=None):
    """Corre los trackers del manifiesto sobre todas (o algunas) secuencias. Devuelve la carpeta del run."""
    from detecciones import CacheDetecciones, ruta_cache
    dir_run = DIR_RUNS / nombre_run
    secs = [s for s in manifiesto.secuencias if secuencias is None or s.nombre in secuencias]
    meta = dict(run=nombre_run, semilla=semilla, trackers=_normalizar_trackers(manifiesto.trackers),
                config_comun=manifiesto.config_comun, versiones=versiones(), secuencias={})
    meta["hash_config"] = hash_dict(dict(t=meta["trackers"], c=meta["config_comun"]))
    for sec in secs:
        cache = (caches or {}).get(sec.nombre) or CacheDetecciones(ruta_cache(sec, sec.detector))
        print(f"[correr] {sec.nombre} ({sec.detector}) → {[t['etiqueta'] for t in meta['trackers']]}")
        ms = correr_secuencia(sec, cache, manifiesto.trackers, manifiesto.config_comun, dir_run, semilla=semilla)
        meta["secuencias"][sec.nombre] = dict(detector=sec.detector, firma_detecciones=cache.meta.get("firma"),
                                              rango=list(rango_frames(sec)), fps=fps_de(sec), ucmc=sec.ucmc,
                                              ms_mediana=ms, split=sec.split)
    guardar_json(dir_run / "run.json", meta)
    print(f"[correr] listo → {dir_run}")
    return dir_run
