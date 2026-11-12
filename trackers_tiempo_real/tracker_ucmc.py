"""
tracker_ucmc.py — UCMCTrack (AAAI 2024) con calibración AUTOMÁTICA de la cámara, en línea (tiempo real)
=========================================================================================================

Qué lo distingue:
  UCMCTrack no asocia en la imagen sino en el SUELO: cada detección se proyecta al plano del suelo (metros) con un
  modelo de cámara, y ahí un Kalman de velocidad constante predice y asocia con la distancia de Mahalanobis (MMD).
  En metros, un auto a 60 km/h se mueve igual cerca o lejos de la cámara; en píxeles, no.

El problema: para proyectar al suelo necesita la cámara (inclinación, campo de visión y altura). El UCMCTrack original
la pide A MANO (cam_para.txt, ajustado con una herramienta interactiva) y la supone FIJA. Desde un dron no es fija:
el gimbal cambia de inclinación y el dron sube y baja.

  MANUAL (original, v12)                         AUTOMÁTICO (v13 -> este archivo, en línea)
  ---------------------------------------------  ----------------------------------------------------------------
  pitch: a ojo, uno para todo el video           pitch: se MIDE cada 0.5 s descomponiendo la H del suelo (PARTE 3)
  altura: a ojo (o una vez con los vehículos)    altura: forma con la H (sube/baja) + escala con el tamaño de los
                                                 vehículos (PARTE 3)
  cámara fija                                    el mapeo imagen<->suelo se rehace cuando cambian pitch o altura
  la CMC usa una sola cámara                     la CMC sale al frame anterior con la cámara anterior y vuelve
                                                 al suelo con la nueva
  hfov: dato de la cámara                        hfov: SIGUE SIENDO UN DATO de la cámara (ficha técnica del dron,
                                                 82° por defecto). No se estima: ver la nota de hfov más abajo.

  Diferencia con el v13: allí la calibración se hacía ANTES de procesar (una pasada por todo el video, programación
  dinámica sobre todo el video, mediana centrada). Aquí es CAUSAL: solo usa los últimos segundos, así que sirve en
  tiempo real. Hasta la primera medida usa `pitch_respaldo_deg` (la estimación a ojo de antes).

Nota sobre el hfov: se probó estimarlo con el tamaño de los vehículos (un auto debe medir lo mismo en el suelo
cerca y lejos de la cámara). Solo fue fiable en vigia_8 y vigia_9; en los demás videos no converge o es ruido, y se
decidió NO incluirlo. Si el hfov de la cámara es otro, cámbialo en CamaraUCMC: el pitch estimado depende de él
(en vigia_8: 52° con hfov 60, 63° con 82, 71° con 95).

Pipeline de un frame (TrackerUCMC.actualizar):

    frame + detecciones
      1. Escala ............. frame original -> resolución de trabajo                          (comun.Escala)
      2. Estabilización ..... H = cómo se movió la cámara desde el frame anterior             (comun.Estabilizador)
      3. Entrada ............ detecciones a trabajo, sin cajas gigantes, + propuestas         (comun.EntradaDetecciones)
      4. Calibración ........ pitch y altura de este frame -> mapa imagen<->suelo             (CalibradorCamara)
      5. UCMC ............... al suelo, predicción + CMC con H, 3 asociaciones MMD, nacer/morir (NucleoUCMC)
      6. Libro .............. salida de UCMC -> Track con historial estabilizado               (comun.LibroTracks)
      7. ¿Se mueve? ......... igual que en todos los trackers                                  (comun.DecisorMovimiento)
      8. Salida ............. tracks confirmados en píxeles originales                         (comun.TrackSalida)

Uso:
    from tracker_ucmc import TrackerUCMC, CamaraUCMC
    cam = CamaraUCMC(hfov_deg=82, pitch_respaldo_deg=50)          # toma oblicua; cenital: pitch_respaldo_deg=0
    tracker = TrackerUCMC(fps=30, camara=cam, nombres_clases=detector.names)
    tracks = tracker.actualizar(frame_bgr, detecciones_Nx6)
    tracker.calibrador.pitch, tracker.calibrador.altura          # cámara estimada en este frame

Supuestos: suelo PLANO (en una ladera la H describe la ladera), sin alabeo (roll ~0, lo mantiene el gimbal), y que el
dron se DESPLACE de vez en cuando (en hover la H no dice nada de la inclinación: se conserva la última medida).
"""
# ======================================================================
# IMPORTACIONES
# Qué hace : Carga las librerías y las piezas comunes
# ¿Se toca? : No
# ======================================================================
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from comun import (Config, Cronometro, DecisorMovimiento, EntradaDetecciones, Escala, Estabilizador, LibroTracks, a_salida,
                   ids_sin_paralaje, warp_pts)


# ======================================================================
# PARTE 1 · ConfigUCMC + CamaraUCMC
# Qué hace : Parámetros del algoritmo (ConfigUCMC) y datos de la cámara de cada dron/video (CamaraUCMC)
# ¿Se toca? : CamaraUCMC SÍ (por cámara). [UCMC] no: valores del repo original, fijados antes de evaluar
# ======================================================================
@dataclass
class ConfigUCMC(Config):
    # [UCMC] valores de demo.py del repo original (tráfico vehicular). NO ajustarlos con los videos de evaluación.
    # Umbrales de confianza y ventana de pérdida: los comunes (conf_high, conf_low, max_miss_sec).
    ucmc_a: float = 100.0          # umbral de asignación (costo MMD = Mahalanobis² + log|S|)
    ucmc_wx: float = 5.0           # ruido de proceso en x (aceleración, (m/s²)²)
    ucmc_wy: float = 5.0           # ruido de proceso en y
    ucmc_vmax: float = 10.0        # velocidad máxima esperada al nacer el track (m/s): incertidumbre inicial
    ucmc_uv_ratio: float = 0.05    # error de la detección en píxeles = 5 % de la altura de la caja (con topes)
    ucmc_punto: str = "auto"       # punto de apoyo en el suelo: "base" (original), "centro" o "auto" (centro si pitch_respaldo < 30°)
    # [ALTURA] escala en metros a partir de los vehículos
    ucmc_largo_vehiculo_m: float = 4.5    # tamaño real supuesto del lado mayor de un vehículo
    ucmc_altura_defecto_m: float = 100.0  # hasta que haya vehículos para estimarla
    # [CALIBRACION EN LINEA] (v13, hecha causal)
    ucmc_calibrar: bool = True            # False = modo MANUAL: pitch_respaldo_deg y altura fijos todo el tiempo
    ucmc_calib_ventana_s: float = 1.0     # separación de los dos frames cuya H se descompone
    ucmc_calib_min_t: float = 0.03        # desplazamiento mínimo del dron en la ventana (relativo a la distancia al suelo)
    ucmc_calib_max_roll: float = 25.0     # soluciones con más alabeo que esto se descartan (el gimbal mantiene el roll ~0)
    ucmc_calib_memoria_s: float = 5.0     # la programación dinámica elige entre las 2 soluciones mirando los últimos 5 s
    ucmc_calib_min_cobertura: float = 30.0  # % de ventanas válidas en esa memoria para fiarse de la H
    ucmc_calib_min_muestras: int = 4      # ...y al menos este número de muestras válidas
    ucmc_calib_suavizado: int = 5         # mediana de las últimas 5 muestras (quita saltos aislados)
    ucmc_calib_max_salto: float = 20.0    # °/s: un cambio mayor se cuenta como "salto" (diagnóstico)
    ucmc_calib_altura_memoria_s: float = 10.0  # vehículos de los últimos 10 s fijan la escala de la altura
    ucmc_calib_min_vehiculos: int = 5     # vehículos mínimos para fiarse de esa escala


@dataclass
class CamaraUCMC:
    """Lo que se sabe de la cámara de ANTEMANO (por dron / por video)."""
    hfov_deg: float = 82.0           # campo de visión horizontal: DATO de la cámara (DJI típicos: 73-84°). No se estima
    pitch_respaldo_deg: float = 0.0  # 0 = cenital, 90 = horizonte al centro. Se usa hasta la 1ª medida (o siempre, en manual)
    altura_m: float = None           # None = automática (vehículos + H); un número = altura fija sobre el suelo
    nota: str = ""                   # de dónde salió (para no olvidar qué es estimado)


# ======================================================================
# PARTE 2 · Mapa (imagen <-> suelo)
# Qué hace : Proyecta píxeles al plano del suelo (metros) y al revés, para una cámara (K, pitch, altura)
# ¿Se toca? : No
# ======================================================================
def matriz_K(ww, wh, hfov_deg):
    """Intrínsecos de una cámara ideal (centro óptico en el centro de la imagen) con ese hfov, en píxeles de trabajo."""
    f = (ww / 2.0) / np.tan(np.deg2rad(hfov_deg) / 2.0)
    return np.array([[f, 0, ww / 2.0], [0, f, wh / 2.0], [0, 0, 1.0]]), f


class Mapa:
    """Como detector/mapper.py del original, vectorizado. A = K·[r1 r2 t] lleva (x, y, 1) del suelo (m) a (u, v, 1)."""

    def __init__(self, K, pitch_deg, altura_m):
        self.pitch_deg, self.altura_m = float(pitch_deg), float(altura_m)
        th = np.deg2rad(pitch_deg)
        # Mundo: X derecha, Y adelante, Z arriba. Cámara: x derecha, y abajo, z = eje óptico.
        R = np.array([[1.0, 0.0, 0.0],
                      [0.0, -np.cos(th), -np.sin(th)],
                      [0.0, np.sin(th), -np.cos(th)]])
        T = -R @ np.array([0.0, 0.0, float(altura_m)])                  # la cámara está a altura_m sobre el suelo
        self.A = K @ np.column_stack([R[:, 0], R[:, 1], T])
        self.InvA = np.linalg.inv(self.A)

    def uv2xy(self, uv, sigma_uv):
        """uv: Nx2 píxeles; sigma_uv: Nx2x2. Devuelve xy (Nx2, metros), sigma_xy (Nx2x2) y válido (N,)."""
        uv1 = np.column_stack([uv, np.ones(len(uv))])
        b = uv1 @ self.InvA.T
        valid = b[:, 2] > 1e-9                                           # por encima del horizonte: no corta el suelo
        gamma = 1.0 / np.where(valid, b[:, 2], 1.0)
        xy = b[:, :2] * gamma[:, None]
        # Jacobiano de la proyección (igual que el original): C = γ·InvA[:2,:2] − γ²·b[:2]·InvA[2,:2]
        C = gamma[:, None, None] * self.InvA[None, :2, :2] - (gamma ** 2)[:, None, None] * b[:, :2, None] * self.InvA[None, 2:3, :2]
        return xy, C @ sigma_uv @ np.transpose(C, (0, 2, 1)), valid

    def xy2uv(self, xy):
        p = np.column_stack([xy, np.ones(len(xy))]) @ self.A.T
        return p[:, :2] / p[:, 2:3]


# ======================================================================
# PARTE 3 · CalibradorCamara
# Qué hace : Estima EN LÍNEA el pitch (con la H) y la altura (con la H + los vehículos) de cada frame
# ¿Se toca? : No (parámetros en ConfigUCMC → [CALIBRACION EN LINEA], [ALTURA])
# ======================================================================
class CalibradorCamara:
    """
    PITCH (inclinación) — con la homografía del suelo
      La H entre dos frames separados 1 s (ventana) se descompone como H = K (R + t·nᵀ/d) K⁻¹ (suelo plano).
      n es la normal del suelo vista desde la cámara: cenital -> (0, 0, 1); inclinada θ -> (0, sin θ, cos θ),
      así que  pitch = atan2(n_y, n_z)  y  roll = asin(n_x).
        a) Cada 0.5 s se descompone la H de la última ventana [a, b]: H da la normal en a; H⁻¹, en b (ahora).
        b) Se descartan las soluciones imposibles: suelo detrás de la cámara (n_z <= 0), dron casi quieto (|t| pequeño,
           la normal no se puede medir), alabeo > 25°, pitch fuera de [-3°, 88°].
        c) "Techo" de horizonte: con pitch θ el horizonte queda en y = -cot θ (y = (v - cy)/f). Ningún vehículo puede
           apoyarse por encima, así que la base del 3er vehículo más alto limita θ.
        d) Quedan normalmente 2 soluciones por muestra. Programación dinámica sobre las muestras de los últimos
           `ucmc_calib_memoria_s`: se elige la secuencia más CONTINUA en el tiempo (mínimo salto de pitch).
        e) El pitch de ahora = mediana de las últimas `ucmc_calib_suavizado` muestras de esa secuencia. Costo de ser
           causal: va ~1 s atrasado (si el gimbal gira 3°/s, ~3° de error mientras gira).
        f) Si en la memoria hay pocas muestras válidas (dron en hover, H no fiable), se conserva el último pitch
           (o pitch_respaldo_deg si todavía no hubo ninguno).
    ALTURA — forma con la H, escala con los vehículos
        g) La misma descomposición da cuánto cambió la distancia al suelo: d_b/d_a = 1 + (R·n)·(t/d).
           Encadenando, log(altura) se conoce salvo una constante: L(t).
        h) Cada vehículo detectado cerca del centro da una altura: f · largo_vehiculo / lado_px · cos(pitch).
           Se guarda "relativo a L" y la mediana de los últimos `ucmc_calib_altura_memoria_s` fija la constante:
           altura(ahora) = exp(L(ahora) + mediana(log altura_vehículo - L(cuando se vio))).
           Así un vehículo visto hace 5 s sigue sirviendo aunque el dron haya bajado desde entonces.
    """

    def __init__(self, cfg, fps, cam, ww, wh):
        self.cfg, self.cam = cfg, cam
        self.K, self.f = matriz_K(ww, wh, cam.hfov_deg)
        self.ww, self.wh = ww, wh
        self.gap = max(2, int(round(cfg.ucmc_calib_ventana_s * fps)))   # frames de la ventana
        self.paso = max(1, int(round(fps / 2)))                          # una ventana cada medio segundo
        self.memoria = int(round(cfg.ucmc_calib_memoria_s * fps))
        self.memoria_alt = int(round(cfg.ucmc_calib_altura_memoria_s * fps))
        self.fps = fps
        self.Hs, self.oks = deque(maxlen=self.gap), deque(maxlen=self.gap)
        self.k = -1                                                      # índice del frame actual
        self.muestras = []                                               # [frame, candidatos, es_inversa, (a, b)]
        self.techos = {}                                                 # frame -> techo de pitch (últimos gap frames)
        self.techo = None                                                # último techo conocido
        self.L = {}                                                      # frame -> log(altura) relativo (últimos gap frames)
        self.L_ahora = 0.0
        self.vehiculos = deque()                                         # (frame, log altura_vehículo - L)
        # estado publicado
        self.pitch = float(cam.pitch_respaldo_deg)
        self.altura = float(cam.altura_m) if cam.altura_m is not None else float(cfg.ucmc_altura_defecto_m)
        self.fuente_pitch = "respaldo"
        self.fuente_altura = "fija" if cam.altura_m is not None else "defecto"
        self.n_saltos = 0
        self.mapa = Mapa(self.K, self.pitch, self.altura)

    # ---- entrada principal ---------------------------------------------
    def actualizar(self, H, H_ok, dets):
        """Llamar UNA vez por frame. dets: detecciones de trabajo (Nx6). Devuelve (mapa de ahora, mapa del frame anterior)."""
        self.k += 1
        mapa_prev = self.mapa
        if not self.cfg.ucmc_calibrar:                                   # modo MANUAL
            return self.mapa, mapa_prev
        c = self.cfg
        vehiculos = dets[(dets[:, 5] >= 0) & (dets[:, 4] >= c.conf_high)] if len(dets) else dets
        self._techo_de(vehiculos)                                        # c)
        self.Hs.append(H); self.oks.append(H_ok)
        a = self.k - self.gap
        L_nuevo = self.L_ahora
        if a >= 0 and a % self.paso == 0:                                # a) toca una ventana
            v_alt = self._muestrear(a)
            if v_alt:                                                    # g)
                L_nuevo = self.L.get(a, self.L_ahora) + float(np.mean(v_alt))
        self.L_ahora = L_nuevo
        self.L[self.k] = L_nuevo
        for fr in [f for f in self.L if f < self.k - self.gap - 1]:
            del self.L[fr]
        if self.cam.altura_m is None:
            self._altura_con(vehiculos)                                  # h)
        if abs(self.pitch - self.mapa.pitch_deg) > 0.05 or abs(self.altura - self.mapa.altura_m) > 0.002 * self.mapa.altura_m:
            self.mapa = Mapa(self.K, self.pitch, self.altura)            # la cámara cambió: nuevo mapeo
        return self.mapa, mapa_prev

    # ---- c) techo de horizonte -------------------------------------------
    def _techo_de(self, vehiculos):
        if len(vehiculos) >= 3:
            y = np.sort((vehiculos[:, 3] - self.wh / 2.0) / self.f)[2]  # base del 3er vehículo más alto
            self.techo = 90.0 if y >= 0 else float(np.degrees(np.arctan(1.0 / -y)))
        self.techos[self.k] = self.techo
        for fr in [f for f in self.techos if f < self.k - self.gap - 1]:
            del self.techos[fr]

    # ---- a) b) d) e) f) pitch ----------------------------------------------
    def _candidatos(self, H):
        """[(pitch, roll, |t|/d, d2/d1)] físicamente posibles de H = K (R + t·nᵀ/d) K⁻¹."""
        c = self.cfg
        n_sol, Rs, ts, ns = cv2.decomposeHomographyMat(H / H[2, 2], self.K)
        out = []
        for k in range(n_sol):
            n, t = ns[k].ravel(), ts[k].ravel()
            if not np.all(np.isfinite(n)) or n[2] <= 0:                  # suelo detrás de la cámara
                continue
            if np.linalg.norm(t) < c.ucmc_calib_min_t:                   # casi sin desplazamiento: no se puede medir
                continue
            p = float(np.degrees(np.arctan2(n[1], n[2])))
            r = float(np.degrees(np.arcsin(np.clip(n[0], -1, 1))))
            ratio = 1.0 + float((Rs[k] @ n) @ t)
            if -3.0 <= p <= 88.0 and abs(r) <= c.ucmc_calib_max_roll and ratio > 0:
                out.append((max(p, 0.0), r, float(np.linalg.norm(t)), ratio))
        return out

    def _muestrear(self, a):
        """Descompone la H de la ventana [a, ahora], resuelve el pitch y devuelve las medidas de log(d_ahora/d_a)."""
        b = self.k
        if all(self.oks):
            Hw = np.eye(3)
            for h in self.Hs:                                            # H de a hasta b (los últimos gap pasos)
                Hw = h @ Hw
            for fr, Hv, inv in ((a, Hw, False), (b, np.linalg.inv(Hw), True)):
                cands = self._candidatos(Hv)
                techo = self.techos.get(fr)
                if techo is not None:
                    cands = [x for x in cands if x[0] <= techo + 3.0]
                self.muestras.append([fr, cands, inv, (a, b)])
        else:                                                            # H no fiable en la ventana: muestra vacía
            self.muestras += [[a, [], False, (a, b)], [b, [], True, (a, b)]]
        self.muestras = sorted([m for m in self.muestras if m[0] >= self.k - self.memoria], key=lambda m: m[0])
        con = [m for m in self.muestras if m[1]]
        cobertura = 100.0 * len(con) / max(len(self.muestras), 1)
        if len(con) < self.cfg.ucmc_calib_min_muestras or cobertura < self.cfg.ucmc_calib_min_cobertura:
            return []                                                    # f) pocas muestras: se conserva el pitch
        sel = self._mas_continua(con)                                    # d)
        pitches = [m[1][s][0] for m, s in zip(con, sel)]
        nuevo = float(np.median(pitches[-self.cfg.ucmc_calib_suavizado:]))   # e)
        if abs(nuevo - self.pitch) * self.fps / self.paso > self.cfg.ucmc_calib_max_salto and self.fuente_pitch == "H":
            self.n_saltos += 1
        if self.fuente_pitch == "respaldo":                              # 1ª medida: las alturas de los vehículos
            self.vehiculos.clear()                                       # se calcularon con el pitch de respaldo
        self.pitch, self.fuente_pitch = nuevo, "H"
        v = []                                                           # g) cambio de altura en esta ventana
        for m, s in zip(con, sel):
            if m[3] == (a, b):
                r = m[1][s][3]
                x = -np.log(r) if m[2] else np.log(r)                    # H⁻¹ da d_a/d_b
                if abs(x) < 0.5:
                    v.append(x)
        return v

    @staticmethod
    def _mas_continua(con):
        """Programación dinámica: un candidato por muestra minimizando la suma de |Δpitch| entre muestras seguidas."""
        costo = np.zeros(len(con[0][1]))
        previo = []
        for k in range(1, len(con)):
            a = np.array([x[0] for x in con[k - 1][1]]); b = np.array([x[0] for x in con[k][1]])
            M = costo[:, None] + np.abs(a[:, None] - b[None, :])
            previo.append(M.argmin(0)); costo = M.min(0)
        sel = [int(costo.argmin())]
        for k in range(len(con) - 1, 0, -1):
            sel.append(int(previo[k - 1][sel[-1]]))
        return sel[::-1]

    # ---- h) altura -----------------------------------------------------------
    def _altura_con(self, vehiculos):
        c = self.cfg
        if len(vehiculos):
            cx, cy = (vehiculos[:, 0] + vehiculos[:, 2]) / 2, (vehiculos[:, 1] + vehiculos[:, 3]) / 2
            cerca = (np.abs(cx - self.ww / 2) < 0.3 * self.ww) & (np.abs(cy - self.wh / 2) < 0.3 * self.wh)
            lado = np.maximum(vehiculos[cerca, 2] - vehiculos[cerca, 0], vehiculos[cerca, 3] - vehiculos[cerca, 1])
            alt = self.f * c.ucmc_largo_vehiculo_m / np.maximum(lado, 1.0) * np.cos(np.deg2rad(self.pitch))
            for x in np.log(alt):
                self.vehiculos.append((self.k, float(x) - self.L_ahora))
        while self.vehiculos and self.vehiculos[0][0] < self.k - self.memoria_alt:
            self.vehiculos.popleft()
        if len(self.vehiculos) >= c.ucmc_calib_min_vehiculos:
            self.altura = float(np.exp(self.L_ahora + np.median([v for _, v in self.vehiculos])))
            self.fuente_altura = "vehiculos"
        elif self.fuente_altura == "vehiculos":                          # sin vehículos recientes: la forma la da la H
            self.altura = float(self.altura * np.exp(self.L_ahora - self.L.get(self.k - 1, self.L_ahora)))


# ======================================================================
# PARTE 4 · NucleoUCMC
# Qué hace : UCMCTrack portado a numpy: Kalman en el suelo, CMC con nuestra H, asociación MMD en 3 pasos
# ¿Se toca? : No (parámetros en ConfigUCMC → [UCMC])
# ----------------------------------------------------------------------
# Adaptado de https://github.com/corfyi/UCMCTrack (commit 7851a49), archivos
# tracker/ucmc.py, tracker/kalman.py y detector/mapper.py.
# MIT License — Copyright (c) 2023 Kefu Yi
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
# following conditions: The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
# EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
# USE OR OTHER DEALINGS IN THE SOFTWARE.
# ======================================================================
def sigma_uv(h, cfg):
    """getUVError del original: 5 % de la altura de la caja, con topes. Los topes del original (2-13 px en u,
    2-10 px en v) son para 1920 px de ancho: se escalan a work_width."""
    k = cfg.work_width / 1920.0
    u = np.clip(cfg.ucmc_uv_ratio * h, 2 * k, 13 * k)
    v = np.clip(cfg.ucmc_uv_ratio * h, 2 * k, 10 * k)
    S = np.zeros((len(h), 2, 2)); S[:, 0, 0] = u ** 2; S[:, 1, 1] = v ** 2
    return S


def asignar_con_limite(cost, limite):
    """Equivale a lap.lapjv(cost, extend_cost=True, cost_limit=limite): asignación óptima donde dejar algo sin pareja
    cuesta limite/2 por lado. Devuelve (pares, filas sin pareja, columnas sin pareja)."""
    n, m = cost.shape
    if n == 0 or m == 0:
        return [], list(range(n)), list(range(m))
    BIG = 1e12
    M = np.full((n + m, m + n), BIG)
    M[:n, :m] = np.where(np.isfinite(cost), cost, BIG)
    M[:n, m:] = np.where(np.eye(n, dtype=bool), limite / 2.0, BIG)
    M[n:, :m] = np.where(np.eye(m, dtype=bool), limite / 2.0, BIG)
    M[n:, m:] = 0.0
    r, c = linear_sum_assignment(M)
    pares = [(i, j) for i, j in zip(r, c) if i < n and j < m and M[i, j] < BIG]
    pi = {i for i, _ in pares}; pj = {j for _, j in pares}
    return pares, [i for i in range(n) if i not in pi], [j for j in range(m) if j not in pj]


def mmd(trks, Y, Rs):
    """Mapped Mahalanobis Distance: d² de Mahalanobis + log|S|, detección x track."""
    if not trks or len(Y) == 0:
        return np.zeros((len(Y), len(trks)))
    zp = np.array([[t.x[0], t.x[2]] for t in trks])
    HPH = np.array([t.P[np.ix_([0, 2], [0, 2])] for t in trks])
    S = HPH[None, :, :, :] + Rs[:, None, :, :]
    d = Y[:, None, :] - zp[None, :, :]
    a, b, c, e = S[..., 0, 0], S[..., 0, 1], S[..., 1, 0], S[..., 1, 1]
    det = np.maximum(a * e - b * c, 1e-12)
    m = (e * d[..., 0] ** 2 - (b + c) * d[..., 0] * d[..., 1] + a * d[..., 1] ** 2) / det
    return m + np.log(det)


TENTATIVO, CONFIRMADO, COSTEANDO = 0, 1, 2       # TrackStatus del original: Tentative, Confirmed, Coasted


class TrackSuelo:
    """KalmanTracker del original: velocidad constante en el SUELO, estado (x, vx, y, vy) en metros."""

    def __init__(self, tid, y, wx, wy, vmax, dt):
        self.F = np.array([[1, dt, 0, 0], [0, 1, 0, 0], [0, 0, 1, dt], [0, 0, 0, 1]], np.float64)
        self.Hm = np.array([[1, 0, 0, 0], [0, 0, 1, 0]], np.float64)
        G = np.zeros((4, 2)); G[0, 0] = 0.5 * dt * dt; G[1, 0] = dt; G[2, 1] = 0.5 * dt * dt; G[3, 1] = dt
        self.Q = G @ np.diag([wx, wy]) @ G.T                             # ruido de proceso (aceleración)
        self.x = np.array([y[0], 0.0, y[1], 0.0])
        self.P = np.diag([1.0, vmax ** 2 / 3.0, 1.0, vmax ** 2 / 3.0])
        self.id, self.status = tid, TENTATIVO
        self.death_count = self.birth_count = 0
        self.detidx = -1

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    def update(self, y, R):
        S = self.Hm @ self.P @ self.Hm.T + R
        K = self.P @ self.Hm.T @ np.linalg.inv(S)
        self.x = self.x + K @ (y - self.Hm @ self.x)
        I_KH = np.eye(4) - K @ self.Hm
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T                    # forma de Joseph, como filterpy


class NucleoUCMC:
    """Fiel al original salvo:
      - Umbrales de confianza y ventana de pérdida = los comunes de Config (igual que ByteTrack/BoT-SORT).
      - Si en un frame no hay detecciones débiles, el original deja los tracks confirmados sin pareja "confirmados"
        para siempre (solo borra los "costeando"). Aquí pasan a costear.
      - Sin "head padding" ni interpolación: son post-procesos OFFLINE del original (reescriben frames pasados).
      - CMC (su opción --cmc) alimentada con NUESTRA H; si la cámara cambió de pitch/altura, el punto sale al frame
        anterior con el mapa anterior y vuelve al suelo con el mapa nuevo."""

    def __init__(self, cfg, fps, punto):
        self.cfg, self.punto = cfg, punto
        self.dt = 1.0 / fps
        self.max_age = max(2, int(round(cfg.max_miss_sec * fps)))     # frames costeando antes de borrar
        self.trackers, self.nid = [], 1
        self.n_fuera = 0                                               # detecciones por encima del horizonte (diagnóstico)
        self.ids_2det = set()                                          # IDs con >= 2 detecciones, aunque sigan tentativos
        self.mapa = None

    def _uv(self, b):
        u = (b[:, 0] + b[:, 2]) / 2
        v = b[:, 3] if self.punto == "base" else (b[:, 1] + b[:, 3]) / 2
        return np.column_stack([u, v])

    def _cmc(self, H, mapa_prev):
        """Lleva el punto de apoyo de cada track al frame actual con H (la velocidad no se toca, como en el original)."""
        if not self.trackers:
            return
        xy = np.array([[t.x[0], t.x[2]] for t in self.trackers])
        uv = warp_pts(H, mapa_prev.xy2uv(xy)).astype(np.float64)
        nxy, _, ok = self.mapa.uv2xy(uv, np.tile(np.eye(2), (len(uv), 1, 1)))
        for t, p, o in zip(self.trackers, nxy, ok):
            if o:
                t.x[0], t.x[2] = p

    def _asociar(self, idx_det, idx_trk, Y, Rs):
        C = mmd([self.trackers[k] for k in idx_trk], Y[idx_det], Rs[idx_det])
        pares, ud, ut = asignar_con_limite(C, self.cfg.ucmc_a)
        return [(idx_det[i], idx_trk[j]) for i, j in pares], [idx_det[i] for i in ud], [idx_trk[j] for j in ut]

    def _corregir(self, t, i, Y, Rs, status):
        t.update(Y[i], Rs[i])
        t.death_count = 0
        t.detidx = i
        if status is not None:
            t.status = status

    def actualizar(self, dets, H, H_ok, mapa, mapa_prev):
        """dets: Nx6 en píxeles de trabajo. Devuelve Nx7 [x1,y1,x2,y2,id,conf,clase]: tracks CONFIRMADOS con detección
        en este frame, con la caja de la detección (como el original)."""
        c = self.cfg
        self.mapa = mapa
        # a) detecciones al suelo (las que están por encima del horizonte no se pueden usar)
        dets = dets[dets[:, 4] >= c.conf_low] if len(dets) else np.zeros((0, 6), np.float32)
        if len(dets):
            Y, Rs, ok = mapa.uv2xy(self._uv(dets[:, :4]).astype(np.float64), sigma_uv(dets[:, 3] - dets[:, 1], c))
        else:
            Y, Rs, ok = np.zeros((0, 2)), np.zeros((0, 2, 2)), np.zeros(0, bool)
        self.n_fuera += int((~ok).sum())
        dets, Y, Rs = dets[ok], Y[ok], Rs[ok]
        fuertes = [i for i in range(len(dets)) if dets[i, 4] >= c.conf_high]
        debiles = [i for i in range(len(dets)) if dets[i, 4] < c.conf_high]
        # b) predicción + CMC
        for t in self.trackers:
            t.predict()
            t.detidx = -1
        if H_ok:
            self._cmc(H, mapa_prev)
        elif mapa_prev is not mapa:                                      # sin H fiable, pero cambió la cámara
            self._cmc(np.eye(3), mapa_prev)
        # c) asociaciones
        conf = [k for k, t in enumerate(self.trackers) if t.status in (CONFIRMADO, COSTEANDO)]
        pares, det_rest, trk_rest = self._asociar(fuertes, conf, Y, Rs)  # 1) fuertes vs confirmados
        for i, k in pares:
            self._corregir(self.trackers[k], i, Y, Rs, CONFIRMADO)
        pares2, _, trk_sin = self._asociar(debiles, trk_rest, Y, Rs)    # 2) débiles vs el resto
        for i, k in pares2:
            self._corregir(self.trackers[k], i, Y, Rs, CONFIRMADO)
        for k in trk_sin:
            self.trackers[k].status = COSTEANDO
        tent = [k for k, t in enumerate(self.trackers) if t.status == TENTATIVO]
        pares3, det_nuevas, _ = self._asociar(det_rest, tent, Y, Rs)    # 3) fuertes sobrantes vs tentativos
        for i, k in pares3:
            t = self.trackers[k]
            self._corregir(t, i, Y, Rs, None)
            self.ids_2det.add(t.id)
            t.birth_count += 1
            if t.birth_count >= 2:                                       # 3 detecciones seguidas -> confirmado
                t.birth_count, t.status = 0, CONFIRMADO
        # d) nacimientos (solo fuertes) y muertes
        for i in det_nuevas:
            t = TrackSuelo(self.nid, Y[i], c.ucmc_wx, c.ucmc_wy, c.ucmc_vmax, self.dt)
            t.detidx = i; self.nid += 1
            self.trackers.append(t)
        vivos = []
        for t in self.trackers:
            t.death_count += 1
            if (t.status == COSTEANDO and t.death_count >= self.max_age) or (t.status == TENTATIVO and t.death_count >= 2):
                continue
            vivos.append(t)
        self.trackers = vivos
        out = [[*dets[t.detidx, :4], t.id, dets[t.detidx, 4], dets[t.detidx, 5]]
               for t in self.trackers if t.status == CONFIRMADO and t.detidx >= 0]
        return np.array(out, np.float32).reshape(-1, 7)


# ======================================================================
# PARTE 5 · TrackerUCMC
# Qué hace : El pipeline completo de un frame (pasos 1-8 del encabezado), en una sola clase
# ¿Se toca? : No (parámetros en ConfigUCMC; la cámara en CamaraUCMC)
# ======================================================================
class TrackerUCMC:
    nombre = "ucmc"

    def __init__(self, fps, camara=None, cfg=None, nombres_clases=None):
        self.cfg = cfg or ConfigUCMC()
        self.camara = camara or CamaraUCMC()
        self.fps = float(fps)
        self.nombres_clases = dict(nombres_clases or {})
        c = self.cfg
        punto = c.ucmc_punto if c.ucmc_punto != "auto" else ("centro" if self.camara.pitch_respaldo_deg < 30 else "base")
        self.escala = None                                   # paso 1 (con el primer frame)
        self.calibrador = None                               # paso 4 (necesita el tamaño del frame de trabajo)
        self.estabilizador = Estabilizador(c)                # paso 2
        self.entrada = EntradaDetecciones(c, fps)            # paso 3
        self.nucleo = NucleoUCMC(c, fps, punto)              # paso 5
        self.libro = LibroTracks(c, fps)                     # paso 6
        self.decisor = DecisorMovimiento(c, fps, ids_sin_paralaje(self.nombres_clases, c))   # paso 7
        self.frame = 0
        self.cron = Cronometro()
        self.salida_nucleo = np.zeros((0, 7), np.float32)    # última salida de UCMC (diagnóstico / benchmarks)

    @property
    def tiempos_ms(self):
        return self.cron.ms

    @property
    def ids_emitidos(self):
        return self.nucleo.nid - 1

    def actualizar(self, frame_bgr, detecciones):
        """frame_bgr: frame ORIGINAL. detecciones: Nx6 [x1,y1,x2,y2,conf,clase] en píxeles del frame original."""
        self.cron.inicio()
        # 1. Escala
        if self.escala is None:
            self.escala = Escala(self.cfg, frame_bgr.shape)
            self.calibrador = CalibradorCamara(self.cfg, self.fps, self.camara, self.escala.ww, self.escala.wh)
        _, gray = self.escala.frame(frame_bgr)
        self.cron.marca("escala")
        # 2. Estabilización
        H, ok = self.estabilizador.paso(gray)
        self.cron.marca("estabilizacion")
        # 3. Entrada
        dets = self.entrada.preparar(detecciones, self.escala, gray, H, ok)
        self.cron.marca("entrada")
        # 4-6. Calibración + UCMC + libro
        confirmados = self.seguir(dets, H, ok)
        self.cron.marca("tracking")
        # 7. ¿Se mueve?
        self.decisor.actualizar(confirmados, ok)
        self.cron.marca("movimiento")
        # 8. Salida
        self.frame += 1
        return a_salida(confirmados, self.escala, self.nombres_clases)

    def seguir(self, dets, H, H_ok):
        """Pasos 4-6 sobre detecciones en píxeles de trabajo. Devuelve los Track confirmados de este frame."""
        mapa, mapa_prev = self.calibrador.actualizar(H, H_ok, dets)      # 4
        self.salida_nucleo = self.nucleo.actualizar(dets, H, H_ok, mapa, mapa_prev)   # 5
        return self.libro.actualizar(self.salida_nucleo, H, H_ok, self.frame)        # 6


# ======================================================================
# PARTE 6 · Pruebas
# Qué hace : Mapeo al suelo, asignación, CMC y calibración en línea con una cámara sintética
# ¿Se toca? : No — se ejecuta con  python tracker_ucmc.py
# ======================================================================
def selftest():
    cfg = ConfigUCMC(use_proposals=False)
    K, f = matriz_K(960, 540, 82.0)
    m = Mapa(K, 0.0, 100.0)                                              # cenital a 100 m
    xy, _, ok = m.uv2xy(np.array([[480.0, 270.0], [580.0, 270.0]]), np.tile(np.eye(2), (2, 1, 1)))
    assert ok.all() and np.allclose(xy[0], 0, atol=1e-6) and np.isclose(xy[1, 0], 100 * 100 / f), "mapeo cenital"
    assert np.allclose(m.xy2uv(xy), [[480, 270], [580, 270]]), "ida y vuelta"
    pares, ud, ut = asignar_con_limite(np.array([[1.0, 50.0], [60.0, 200.0]]), 100.0)
    assert pares == [(0, 0)] and ud == [1] and ut == [1], "asignación con límite"
    # objeto QUIETO en el suelo, paneo de 14 px/frame: con CMC conserva su ID
    trk = TrackerUCMC(30.0, CamaraUCMC(pitch_respaldo_deg=0.0, altura_m=100.0), cfg)
    trk.escala = type("E", (), {"ww": 960, "wh": 540})()
    trk.calibrador = CalibradorCamara(cfg, 30.0, trk.camara, 960, 540)
    for fr in range(60):
        x = 200 + 14 * fr
        Hf = np.array([[1, 0, 14 if fr else 0], [0, 1, 0], [0, 0, 1]], np.float64)
        trk.seguir(np.array([[x, 100, x + 12, 112, 0.9, 0]], np.float32), Hf, True); trk.frame += 1
    assert trk.ids_emitidos == 1, trk.ids_emitidos
    # calibración en línea: el gimbal baja de 50° a 20° mientras el dron avanza y baja de 80 a 60 m
    ww, wh, fps, N = 960, 540, 30.0, 300
    verdad, alt_v = np.linspace(50, 20, N), np.linspace(80, 60, N)
    maps = []
    for k in range(N):
        mk = Mapa(K, float(verdad[k]), float(alt_v[k]))
        th = np.deg2rad(verdad[k])
        R = np.array([[1.0, 0, 0], [0, -np.cos(th), -np.sin(th)], [0, np.sin(th), -np.cos(th)]])
        T = -R @ np.array([0.0, 0.25 * k, alt_v[k]])                     # avanza 7.5 m/s y baja
        mk.A = K @ np.column_stack([R[:, 0], R[:, 1], T]); mk.InvA = np.linalg.inv(mk.A)
        maps.append(mk)
    cal = CalibradorCamara(ConfigUCMC(), fps, CamaraUCMC(pitch_respaldo_deg=0.0), ww, wh)
    lado = lambda k: f * 4.5 / (alt_v[k] / np.cos(np.deg2rad(verdad[k])))   # un vehículo de 4.5 m en el centro
    err_p, err_a = [], []
    for k in range(N):
        H = np.eye(3) if k == 0 else maps[k].A @ maps[k - 1].InvA
        s = lado(k)
        dets = np.array([[480 - s / 2, 270 - s / 4, 480 + s / 2, 270 + s / 4, 0.9, 2]] * 3, np.float32)
        cal.actualizar(H, True, dets)
        if k > 2 * fps:                                                  # tras 2 s ya debe haber medido
            err_p.append(abs(cal.pitch - verdad[k])); err_a.append(abs(cal.altura / alt_v[k] - 1))
    # ser causal tiene un costo: la mediana de 5 muestras va ~1 s atrasada y entre muestras (0.5 s) se mantiene el
    # último valor. Aquí el gimbal gira 3°/s -> hasta ~4.5° de error mientras gira
    assert cal.fuente_pitch == "H" and max(err_p) < 5.0, f"pitch: error máx {max(err_p):.1f}°"
    assert max(err_a) < 0.08, f"altura: error máx {100 * max(err_a):.1f} %"
    print(f"tracker_ucmc OK | mapeo, asignación, CMC (1 ID con paneo) | calibración en línea tras 2 s: "
          f"pitch error máx {max(err_p):.1f}°, altura error máx {100 * max(err_a):.1f} %")


if __name__ == "__main__":
    selftest()
