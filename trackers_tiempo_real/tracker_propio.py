"""
tracker_propio.py — TRACKER PROPIO: estabilización con H + Kalman + asociación por IoU (el "propio_kf" de la comparativa)
=====================================================================================================================

Qué lo distingue de ByteTrack:
  ByteTrack predice dónde estará cada objeto con un Kalman de velocidad constante EN LA IMAGEN. Desde un dron eso falla:
  si la cámara gira o avanza, todo se desplaza en la imagen aunque esté quieto y la predicción apunta al lugar equivocado.
  Aquí, ANTES de predecir, el estado del Kalman de cada track se lleva al frame actual con la homografía H de la cámara
  (estabilización). El Kalman solo tiene que explicar el movimiento PROPIO del objeto.

Pipeline de un frame (TrackerPropio.actualizar):

    frame + detecciones
      1. Escala ............. frame original -> resolución de trabajo                          (comun.Escala)
      2. Estabilización ..... H = cómo se movió la cámara desde el frame anterior             (comun.Estabilizador)
      3. Entrada ............ detecciones a trabajo, sin cajas gigantes, + propuestas         (comun.EntradaDetecciones)
      4. Predicción ......... cada track: historial y Kalman al frame actual con H, y Kalman avanza un frame
      5. Asociación ......... IoU (cajas infladas) en dos rondas: detecciones fuertes, luego débiles
      6. Corrección ......... Kalman corrige con la detección; nacen tracks (solo fuertes); mueren los perdidos
      7. ¿Se mueve? ......... desplazamiento estabilizado en 1 s, rectitud, paralaje, histéresis (comun.DecisorMovimiento)
      8. Salida ............. tracks confirmados en píxeles originales                         (comun.TrackSalida)

Uso:
    from tracker_propio import TrackerPropio, ConfigPropio
    tracker = TrackerPropio(fps=30, nombres_clases=detector.names)
    tracks = tracker.actualizar(frame_bgr, detecciones_Nx6)

Por qué IoU y no la MMD de UCMCTrack: se probó (v14 y v14b) y fragmentó más en 9 de 10 videos, incluso con la
compuerta inflada. Ver comparativa_trackers_v14.ipynb, PARTE 3.4.
"""
# ======================================================================
# IMPORTACIONES
# Qué hace : Carga las librerías y las piezas comunes
# ¿Se toca? : No
# ======================================================================
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from comun import (Config, Cronometro, DecisorMovimiento, EntradaDetecciones, Escala, Estabilizador, Track, a_salida,
                   ids_sin_paralaje, iou_pad, warp_pts)


# ======================================================================
# PARTE 1 · ConfigPropio
# Qué hace : Parámetros propios de este tracker (los comunes están en comun.Config)
# ¿Se toca? : SÍ — [ASOCIACION PROPIO]. [KALMAN] no: son los de ByteTrack/BoT-SORT
# ======================================================================
@dataclass
class ConfigPropio(Config):
    # [ASOCIACION PROPIO] cómo se une una detección con un track
    match_iou: float = 0.20        # IoU mínimo (con cajas infladas) para asociar
    box_pad: float = 3.0           # px con que se inflan las cajas para el IoU (objetos pequeños)
    # [KALMAN] valores por defecto de ByteTrack/BoT-SORT. NO ajustarlos con los videos de evaluación
    kf_std_pos: float = 1 / 20     # ruido de posición, como fracción de la altura de la caja
    kf_std_vel: float = 1 / 160    # ruido de velocidad, como fracción de la altura de la caja


# ======================================================================
# PARTE 2 · KalmanXYAH
# Qué hace : Filtro de Kalman de velocidad constante sobre la caja, con la compensación de cámara (warp)
# ¿Se toca? : No
# ======================================================================
def caja_a_xyah(b):
    """[x1,y1,x2,y2] -> [centro x, centro y, ancho/alto, alto] (estado de ByteTrack)."""
    w, h = b[2] - b[0], max(b[3] - b[1], 1e-3)
    return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, w / h, h], np.float64)


def xyah_a_caja(z):
    """[centro x, centro y, ancho/alto, alto] -> [x1,y1,x2,y2]."""
    h = max(z[3], 1e-3); w = z[2] * h
    return np.array([z[0] - w / 2, z[1] - h / 2, z[0] + w / 2, z[1] + h / 2], np.float32)


class KalmanXYAH:
    """Estado (x, y, a, h, vx, vy, va, vh): centro, aspecto, alto y sus velocidades (px/frame).
    Mismo modelo y ruidos que ByteTrack/BoT-SORT; lo único nuevo es `estabilizar`."""

    def __init__(self, std_pos=1 / 20, std_vel=1 / 160):
        self.F = np.eye(8); self.F[:4, 4:] = np.eye(4)      # transición: posición += velocidad (1 frame)
        self.Hm = np.eye(4, 8)                               # se observa (x, y, a, h), no la velocidad
        self.wp, self.wv = std_pos, std_vel

    def iniciar(self, z):
        """Estado inicial a partir de la primera detección: velocidad 0 con mucha incertidumbre."""
        h = z[3]
        std = [2 * self.wp * h, 2 * self.wp * h, 1e-2, 2 * self.wp * h,
               10 * self.wv * h, 10 * self.wv * h, 1e-5, 10 * self.wv * h]
        return np.r_[z, np.zeros(4)], np.diag(np.square(std))

    @staticmethod
    def estabilizar(mean, cov, H):
        """Lleva el estado al frame actual con la homografía H (compensación de cámara).
        Centro: H completa. Velocidad y covarianza: parte lineal A. Altura: escala sqrt(|det A|). Aspecto: igual."""
        A = H[:2, :2] / H[2, 2]                              # parte lineal (local) de H
        s = float(np.sqrt(abs(np.linalg.det(A))))            # cambio de escala (zoom / cambio de altura)
        J = np.eye(8)
        J[0:2, 0:2] = A; J[3, 3] = s                         # posición y altura
        J[4:6, 4:6] = A; J[7, 7] = s                         # velocidades
        m = J @ mean
        m[:2] = warp_pts(H, mean[:2])[0]                     # el centro, con la homografía exacta
        return m, J @ cov @ J.T

    def predecir(self, mean, cov):
        """Avanza un frame (movimiento PROPIO del objeto). El ruido escala con la altura de la caja (como ByteTrack)."""
        h = mean[3]
        std = [self.wp * h, self.wp * h, 1e-2, self.wp * h, self.wv * h, self.wv * h, 1e-5, self.wv * h]
        return self.F @ mean, self.F @ cov @ self.F.T + np.diag(np.square(std))

    def corregir(self, mean, cov, z):
        """Corrige el estado con una detección z = (x, y, a, h)."""
        h = mean[3]
        R = np.diag(np.square([self.wp * h, self.wp * h, 1e-1, self.wp * h]))   # ruido de la medida
        S = self.Hm @ cov @ self.Hm.T + R                    # covarianza de la innovación
        K = cov @ self.Hm.T @ np.linalg.inv(S)               # ganancia de Kalman
        return mean + K @ (z - self.Hm @ mean), cov - K @ S @ K.T


# ======================================================================
# PARTE 3 · TrackerPropio
# Qué hace : El pipeline completo de un frame (pasos 1-8 del encabezado), en una sola clase
# ¿Se toca? : No (parámetros en ConfigPropio)
# ======================================================================
class TrackerPropio:
    nombre = "propio_kf"

    def __init__(self, fps, cfg=None, nombres_clases=None):
        self.cfg = cfg or ConfigPropio()
        self.fps = float(fps)
        self.nombres_clases = dict(nombres_clases or {})
        c = self.cfg
        # piezas del pipeline
        self.escala = None                                   # se crea con el primer frame (paso 1)
        self.estabilizador = Estabilizador(c)                # paso 2
        self.entrada = EntradaDetecciones(c, fps)            # paso 3
        self.kalman = KalmanXYAH(c.kf_std_pos, c.kf_std_vel)  # pasos 4 y 6
        self.decisor = DecisorMovimiento(c, fps, ids_sin_paralaje(self.nombres_clases, c))   # paso 7
        # estado
        self.tracks, self.nid, self.frame = [], 1, 0
        self.max_miss = max(2, int(round(c.max_miss_sec * fps)))     # frames sin detección antes de borrar un track
        self.maxlen = int(round(c.window_sec * fps)) + 1             # largo del historial (ventana de movimiento)
        self.cron = Cronometro()
        self.H, self.H_ok = np.eye(3), True                  # última H (diagnóstico)

    @property
    def tiempos_ms(self):
        return self.cron.ms

    @property
    def ids_emitidos(self):
        """IDs creados en total (incluye los que nunca se confirmaron)."""
        return self.nid - 1

    def actualizar(self, frame_bgr, detecciones):
        """frame_bgr: frame ORIGINAL. detecciones: Nx6 [x1,y1,x2,y2,conf,clase] en píxeles del frame original.
        Devuelve la lista de TrackSalida confirmados en este frame."""
        self.cron.inicio()
        # 1. Escala
        if self.escala is None:
            self.escala = Escala(self.cfg, frame_bgr.shape)
        _, gray = self.escala.frame(frame_bgr)
        self.cron.marca("escala")
        # 2. Estabilización
        H, ok = self.estabilizador.paso(gray)
        self.H, self.H_ok = H, ok
        self.cron.marca("estabilizacion")
        # 3. Entrada
        dets = self.entrada.preparar(detecciones, self.escala, gray, H, ok)
        self.cron.marca("entrada")
        # 4-6. Tracking
        confirmados = self.seguir(dets, H, ok)
        self.cron.marca("tracking")
        # 7. ¿Se mueve?
        self.decisor.actualizar(confirmados, ok)
        self.cron.marca("movimiento")
        # 8. Salida
        self.frame += 1
        return a_salida(confirmados, self.escala, self.nombres_clases)

    def seguir(self, dets, H, H_ok):
        """Pasos 4-6 sobre detecciones ya en píxeles de trabajo. Devuelve los Track confirmados de este frame."""
        c = self.cfg
        self._predecir(H, H_ok)                                          # 4
        fuertes = dets[dets[:, 4] >= c.conf_high] if len(dets) else dets
        debiles = dets[(dets[:, 4] >= c.conf_low) & (dets[:, 4] < c.conf_high)] if len(dets) else dets
        pares, sin_det, det_libres = self._asociar(self.tracks, fuertes)  # 5a. ronda fuerte
        for i, j in pares:
            self._corregir(self.tracks[i], fuertes[j])                   # 6
        resto = [self.tracks[i] for i in sin_det]
        pares2, _, _ = self._asociar(resto, debiles)                     # 5b. ronda débil (solo tracks sin pareja)
        for i, j in pares2:
            self._corregir(resto[i], debiles[j])
        con_det = {self.tracks[i].id for i, _ in pares} | {resto[i].id for i, _ in pares2}
        for t in self.tracks:
            if t.id not in con_det:
                t.miss += 1                                              # sigue vivo con su predicción hasta max_miss
        for j in det_libres:
            self.tracks.append(self._nuevo(fuertes[j]))                  # nacen solo con detecciones fuertes
        self.tracks = [t for t in self.tracks if t.miss <= self.max_miss]   # mueren los perdidos
        return [t for t in self.tracks if t.hits >= c.min_hits and t.miss == 0]

    # ---- paso 4 -------------------------------------------------------
    def _predecir(self, H, H_ok):
        """Cada track: historial al frame actual (para el paso 7), Kalman al frame actual con H (ESTABILIZACIÓN) y
        Kalman un frame hacia adelante (movimiento propio). La asociación usa la caja PREDICHA."""
        for t in self.tracks:
            t.warp(H, H_ok)
            m, P = self.kalman.estabilizar(*t.kf, H)
            t.kf = self.kalman.predecir(m, P)
            t.box = xyah_a_caja(t.kf[0][:4])

    # ---- paso 5 -------------------------------------------------------
    def _asociar(self, tracks, dets):
        """IoU (cajas infladas box_pad) + asignación óptima (húngaro). Solo valen parejas con IoU >= match_iou y clase
        compatible. Devuelve (pares (i track, j det), tracks sin pareja, detecciones sin pareja)."""
        if not tracks or len(dets) == 0:
            return [], list(range(len(tracks))), list(range(len(dets)))
        iou = iou_pad(np.array([t.box for t in tracks]), dets[:, :4], self.cfg.box_pad)
        for i, t in enumerate(tracks):
            for j in range(len(dets)):
                if not (t.cls < 0 or dets[j, 5] < 0 or t.cls == int(dets[j, 5])):
                    iou[i, j] = 0                                        # un "car" no se une con un "truck"
        r, cc = linear_sum_assignment(1 - iou)
        pares = [(i, j) for i, j in zip(r, cc) if iou[i, j] >= self.cfg.match_iou]
        mi = {i for i, _ in pares}; mj = {j for _, j in pares}
        return pares, [i for i in range(len(tracks)) if i not in mi], [j for j in range(len(dets)) if j not in mj]

    # ---- paso 6 -------------------------------------------------------
    def _corregir(self, t, det):
        """Kalman corrige con la detección; el track guarda la caja FILTRADA (como Ultralytics) y la clase/conf de la detección."""
        t.kf = self.kalman.corregir(*t.kf, caja_a_xyah(det[:4]))
        f = det.astype(np.float32).copy()
        f[:4] = xyah_a_caja(t.kf[0][:4])
        t.update(f, self.frame)

    def _nuevo(self, det):
        c = self.cfg
        t = Track(self.nid, det, self.frame, self.maxlen, c.cls_min_conf, c.cls_min_hits)
        t.kf = self.kalman.iniciar(caja_a_xyah(det[:4]))
        self.nid += 1
        return t


# ======================================================================
# PARTE 4 · Prueba
# Qué hace : Comprueba la estabilización del Kalman y que un objeto quieto con el dron en paneo conserve su ID
# ¿Se toca? : No — se ejecuta con  python tracker_propio.py
# ======================================================================
def selftest():
    kf = KalmanXYAH()
    m, P = kf.iniciar(np.array([100.0, 50.0, 0.5, 20.0]))
    m[4:6] = [3.0, 0.0]                                                  # el objeto avanza 3 px/frame en x
    mt, _ = KalmanXYAH.estabilizar(m, P, np.array([[1, 0, 10], [0, 1, -5], [0, 0, 1]], np.float64))
    assert np.allclose(mt[:2], [110, 45]) and np.allclose(mt[4:6], [3, 0]), "traslación"
    mz, _ = KalmanXYAH.estabilizar(m, P, np.diag([2.0, 2.0, 1.0]))
    assert np.allclose(mz[:4], [200, 100, 0.5, 40]) and np.allclose(mz[4:6], [6, 0]), "zoom"
    trk = TrackerPropio(30.0, ConfigPropio(use_proposals=False))
    for f in range(60):                                                  # objeto QUIETO en el suelo, paneo de 14 px/frame
        x = 200 + 14 * f
        d = np.array([[x, 100, x + 12, 112, 0.9, 0]], np.float32)
        Hf = np.array([[1, 0, 14 if f else 0], [0, 1, 0], [0, 0, 1]], np.float64)
        out = trk.seguir(d, Hf, True); trk.frame += 1
    assert trk.ids_emitidos == 1 and len(out) == 1, trk.ids_emitidos
    print("tracker_propio OK | estabilización del Kalman (traslación y zoom) | objeto quieto, paneo de 14 px/frame -> 1 ID")


if __name__ == "__main__":
    selftest()
