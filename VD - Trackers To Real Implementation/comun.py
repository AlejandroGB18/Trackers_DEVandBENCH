"""
comun.py — Piezas que comparten TODOS los trackers (propio, UCMC, ByteTrack, BoT-SORT)
=====================================================================================

Cada tracker es un archivo aparte (tracker_propio.py, tracker_ucmc.py, ...) con una sola clase principal
que se usa igual en todos:

    tracker = TrackerXXX(fps=30, nombres_clases={2: "car", ...})
    for frame in camara:                                   # frame BGR a resolución ORIGINAL
        detecciones = mi_detector(frame)                   # Nx6 [x1, y1, x2, y2, conf, clase] en píxeles del frame
        tracks = tracker.actualizar(frame, detecciones)    # lista de TrackSalida (ID, caja, clase, ¿se mueve?)

Este archivo tiene lo que va ANTES y DESPUÉS del tracker, y es idéntico para todos (así la comparación es justa):

    frame ─► PARTE 2 Escala ─► PARTE 3 Estabilizador (H) ─► PARTE 4 Entrada de detecciones ─► [ TRACKER ] ─►
          ─► PARTE 6 Libro de tracks (solo trackers externos) ─► PARTE 7 ¿Se mueve? ─► PARTE 8 Salida

Todo es CAUSAL (solo usa el frame actual y los anteriores): sirve para tiempo real.
Las distancias de Config están en píxeles de la resolución de TRABAJO (work_width), no de la original.
"""
# ======================================================================
# IMPORTACIONES
# Qué hace : Carga las librerías
# ¿Se toca? : No
# ======================================================================
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import cv2
import numpy as np


# ======================================================================
# PARTE 1 · Config
# Qué hace : Parámetros comunes a todos los trackers (cada tracker añade los suyos en su archivo)
# ¿Se toca? : SÍ — pero los marcados "igual para TODOS" deben ser iguales al comparar trackers
# ======================================================================
@dataclass
class Config:
    work_width: int = 960          # ancho al que se estima la H y se hace el tracking (el frame se reduce a este ancho)
    # [CAMARA] movimiento global de la cámara (homografía)
    min_inliers: int = 30          # por debajo, la homografía se considera poco fiable
    ransac_px: float = 1.5         # tolerancia RANSAC: más baja = se ajusta más al plano del suelo
    grid: tuple = (4, 3)           # (cols, filas): reparte los puntos por toda la imagen (evita que domine una zona)
    # [ENTRADA] qué detecciones llegan al tracker (igual para TODOS)
    max_box_area_frac: float = 0.03  # se descartan detecciones con caja mayor a esta fracción del frame
    use_proposals: bool = True     # añadir "propuestas": cajas SIN clase donde algo se mueve y el detector no ve nada
    # [ASOCIACION] umbrales comunes (igual para TODOS: ByteTrack, BoT-SORT y UCMC usan los mismos)
    conf_high: float = 0.35        # detecciones "fuertes" (1ª asociación, crean tracks nuevos)
    conf_low: float = 0.10         # detecciones "débiles" (2ª asociación, estilo ByteTrack)
    max_miss_sec: float = 1.0      # segundos que un track sobrevive sin detección
    min_hits: int = 4              # detecciones para confirmar un track (antes no sale)
    # [CLASE] evita que una detección suelta de baja confianza cambie la etiqueta de un track
    cls_min_conf: float = 0.40     # solo las detecciones con esta confianza votan por una clase
    cls_min_hits: int = 3          # votos mínimos para que el track adopte una clase; si no, queda "desconocido" (-1)
    # [MOVIMIENTO] cuándo un track cuenta como 'en movimiento' (igual para TODOS)
    window_sec: float = 1.0        # ventana temporal para medir el desplazamiento neto
    min_move_px: float = 6.0       # desplazamiento mínimo (en la ventana) para considerar movimiento
    rel_move: float = 0.30         # ...y además >= rel_move * tamaño del objeto (sqrt(ancho*alto)); frena cajas grandes inestables
    adaptive: bool = False         # umbral adaptativo con la población de tracks (solo si la mayoría es estática)
    max_adaptive_px: float = 12.0  # tope del umbral adaptativo
    mad_k: float = 4.0             # umbral adaptativo = mediana + k*MAD de la población de tracks
    on_frames: int = 3             # evaluaciones seguidas "moviéndose" para activar el estado
    off_frames: int = 10           # evaluaciones seguidas "quieto" para desactivarlo
    min_straightness: float = 0.60 # desplazamiento neto / recorrido en la ventana; un objeto real avanza en línea, el ruido deambula
    max_unknown_aspect: float = 6.0  # un track SIN clase más alargado que esto es una estructura (cable, borde), no un objeto
    # [PARALAJE] lo que sobresale del suelo se desplaza respecto a él cuando el dron se traslada
    parallax_filter: bool = True
    parallax_angle_deg: float = 30.0   # el residuo debe ser paralelo al flujo del suelo en ese punto
    parallax_k_min: float = -1.5       # k<0: algo fijo en la IMAGEN (cable que resbala, borde)
    parallax_k_max: float = 3.0        # k>0: paralaje (poste, árbol); un vehículo real tiene k >> 3
    parallax_min_fit: float = 0.6      # R² mínimo del ajuste  residuo(t) ≈ k·flujo_suelo_acumulado(t)
    parallax_min_ground_px: float = 3.0  # flujo NETO del suelo mínimo en la ventana (en hover no se decide)
    parallax_skip: tuple = ("car", "truck", "bus", "motorcycle", "small vehicle", "large vehicle")  # clases que NO se filtran
    # [PROPUESTAS] cambios de imagen sin clase: objetos que el detector no conoce (solo si use_proposals)
    proposal_gap_sec: float = 0.15 # separación temporal entre los frames que se restan
    diff_thr: int = 25             # diferencia de gris mínima para contar un píxel como "cambió"
    min_area: int = 25
    max_area: int = 6000
    dilate: int = 3
    border: int = 15               # se ignora el borde (ahí la imagen alineada no tiene datos)
    max_aspect: float = 5.0
    max_residual: float = 3.5      # diferencia media tras alinear; si se supera, la H falló y no se generan propuestas
    proposal_conf: float = 0.5     # confianza que se le da a una propuesta
    proposal_memory_sec: float = 0.5   # segundos que se recuerdan las detecciones (para no proponer sobre ellas)
    proposal_overlap: float = 0.2      # se descarta la propuesta si esta fracción de su área cae sobre una detección recordada
    max_coherence: float = 0.80    # estructura de una sola orientación (cables, líneas, bordillos) -> no es un objeto


def warp_pts(H, pts):
    """Aplica la homografía H a una lista de puntos (N x 2)."""
    pts = np.asarray(pts, np.float32).reshape(-1, 2)
    if len(pts) == 0:
        return pts
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), H).reshape(-1, 2)


def iou_pad(a, b, pad):
    """IoU entre cajas (N x 4 contra M x 4) infladas `pad` px por lado (ayuda con objetos de pocos píxeles)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a = a + np.array([-pad, -pad, pad, pad]); b = b + np.array([-pad, -pad, pad, pad])
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + bb[None, :] - inter + 1e-9)


# ======================================================================
# PARTE 2 · Escala
# Qué hace : Pasa el frame original a la resolución de trabajo, y las cajas de ida (detecciones) y vuelta (salida)
# ¿Se toca? : No (work_width en Config)
# ======================================================================
class Escala:
    """Entra: frame BGR original. Sale: frame de trabajo (BGR) y su gris suavizado (lo usan la H y las propuestas).
    El factor se fija con el primer frame; si cambia la resolución del stream, se crea un tracker nuevo."""

    def __init__(self, cfg, forma_frame):
        H0, W0 = forma_frame[:2]
        self.k = cfg.work_width / W0                                     # original -> trabajo
        self.ww, self.wh = cfg.work_width, int(round(H0 * self.k))

    def frame(self, frame_bgr):
        small = cv2.resize(frame_bgr, (self.ww, self.wh), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        return small, gray

    def a_trabajo(self, dets):
        d = np.asarray(dets, np.float32).reshape(-1, 6).copy()
        d[:, :4] *= self.k
        return d

    def a_original(self, caja):
        return np.asarray(caja, np.float32) / self.k


# ======================================================================
# PARTE 3 · Estabilizador
# Qué hace : Estima cómo se movió la cámara entre el frame anterior y el actual (homografía H, LK + RANSAC)
# ¿Se toca? : No (parámetros en Config → [CAMARA])
# ======================================================================
class Estabilizador:
    """Entra: gris del frame actual. Sale: (H, ok).
    H lleva un punto del frame ANTERIOR al ACTUAL suponiendo que todo es suelo: un objeto quieto en el suelo queda en
    H·(posición anterior). ok=False si no hay suficientes puntos coherentes (imagen borrosa, agua, cambio brusco):
    en ese caso H = identidad y los historiales se reinician."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.prev = None

    def _puntos(self, gray):
        """Puntos repartidos en una rejilla, para que ninguna zona (techos, pastizal) domine la homografía."""
        h, w = gray.shape
        gx, gy = self.cfg.grid
        pts = []
        for i in range(gy):
            for j in range(gx):
                y0, y1, x0, x1 = i * h // gy, (i + 1) * h // gy, j * w // gx, (j + 1) * w // gx
                p = cv2.goodFeaturesToTrack(gray[y0:y1, x0:x1], 150, 0.01, 8)
                if p is not None:
                    pts.append(p.reshape(-1, 2) + np.array([x0, y0], np.float32))
        return np.vstack(pts).reshape(-1, 1, 2).astype(np.float32) if pts else None

    def paso(self, gray):
        if self.prev is None:                                            # primer frame: no hay movimiento que medir
            self.prev = gray
            return np.eye(3), True
        H, ok = np.eye(3), False
        p0 = self._puntos(self.prev)
        if p0 is not None and len(p0) >= 10:
            p1, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, p0, None, winSize=(21, 21), maxLevel=3)
            good = st.ravel() == 1
            if good.sum() >= 10:
                Hc, inl = cv2.findHomography(p0[good], p1[good], cv2.RANSAC, self.cfg.ransac_px)
                if Hc is not None and inl.sum() >= self.cfg.min_inliers:
                    H, ok = Hc, True
        self.prev = gray
        return H, ok


# ======================================================================
# PARTE 4 · EntradaDetecciones (+ Propuestas)
# Qué hace : Revisa y escala las detecciones del detector externo; opcionalmente añade "propuestas" sin clase
# ¿Se toca? : No (parámetros en Config → [ENTRADA], [PROPUESTAS])
# ======================================================================
class Propuestas:
    """Cambios respecto al frame t-gap, ya compensando la cámara con H: cajas SIN clase (clase -1) para cosas que se
    mueven y el detector no conoce. Se descartan las que caen sobre una detección reciente (su estela)."""

    def __init__(self, cfg, fps):
        self.cfg = cfg
        self.gap = max(2, int(round(cfg.proposal_gap_sec * fps)))
        self.grays = deque(maxlen=self.gap + 1)
        self.Hs = deque(maxlen=self.gap)
        self.oks = deque(maxlen=self.gap)
        self.memoria = deque(maxlen=max(1, int(round(cfg.proposal_memory_sec * fps))))   # cajas recientes, una entrada por frame

    def paso(self, gray, H, ok, dets):
        """dets: detecciones del frame (trabajo). Devuelve las propuestas (Nx6) ya filtradas."""
        self._recordar(dets, H)
        pr = self._cambios(gray, H, ok)
        pr = self._fuera_de_memoria(pr)
        if len(pr) and len(dets):
            pr = pr[iou_pad(pr[:, :4], dets[:, :4], 2.0).max(1) < 0.1]
        return pr

    def _recordar(self, dets, H):
        """Lleva las cajas recordadas al frame actual con H y añade las de este frame."""
        self.memoria = deque([warp_pts(H, b.reshape(-1, 2)).reshape(-1, 4) for b in self.memoria], maxlen=self.memoria.maxlen)
        if len(dets):
            self.memoria.append(dets[:, :4].astype(np.float32).copy())

    def _cambios(self, gray, H, ok):
        c = self.cfg
        if len(self.grays) > 0:
            self.Hs.append(H); self.oks.append(ok)
        self.grays.append(gray)
        if len(self.grays) < self.gap + 1 or not all(self.oks):
            return np.zeros((0, 6), np.float32)
        M = np.eye(3)
        for h in self.Hs:                                                # H_t @ ... @ H_{t-gap+1}
            M = h @ M
        prev, curr = self.grays[0], gray
        h_, w_ = curr.shape
        warped = cv2.warpPerspective(prev, M, (w_, h_))
        valid = cv2.erode(cv2.warpPerspective(np.full((h_, w_), 255, np.uint8), M, (w_, h_)), np.ones((11, 11), np.uint8))
        d = cv2.bitwise_and(cv2.absdiff(curr, warped), valid)
        if valid.any() and d[valid > 0].mean() > c.max_residual:
            return np.zeros((0, 6), np.float32)                          # la alineación falló: todo "cambió"
        m = (d > c.diff_thr).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        m = cv2.dilate(m, np.ones((c.dilate, c.dilate), np.uint8))
        n, _, s, _ = cv2.connectedComponentsWithStats(m)
        gx = cv2.Sobel(curr, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(curr, cv2.CV_32F, 0, 1, ksize=3)
        out = []
        for k in range(1, n):
            x, y, bw, bh, a = s[k]
            if not (c.min_area <= a <= c.max_area):
                continue
            if x < c.border or y < c.border or x + bw > w_ - c.border or y + bh > h_ - c.border:
                continue
            ar = bw / max(bh, 1)
            if ar > c.max_aspect or ar < 1 / c.max_aspect:
                continue
            sx, sy = gx[y:y + bh, x:x + bw], gy[y:y + bh, x:x + bw]
            jxx, jyy, jxy = float((sx * sx).sum()), float((sy * sy).sum()), float((sx * sy).sum())
            coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
            if coh > c.max_coherence:
                continue                                                 # línea/cable/borde, no un objeto
            out.append([x, y, x + bw, y + bh, c.proposal_conf, -1])
        return np.array(out, np.float32).reshape(-1, 6)

    def _fuera_de_memoria(self, pr):
        """Quita las propuestas cuya área cae en >= proposal_overlap sobre alguna detección recordada."""
        if not len(pr) or not self.memoria:
            return pr
        D = np.vstack(self.memoria)
        x1 = np.maximum(pr[:, None, 0], D[None, :, 0]); y1 = np.maximum(pr[:, None, 1], D[None, :, 1])
        x2 = np.minimum(pr[:, None, 2], D[None, :, 2]); y2 = np.minimum(pr[:, None, 3], D[None, :, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        area = np.maximum((pr[:, 2] - pr[:, 0]) * (pr[:, 3] - pr[:, 1]), 1.0)
        return pr[(inter / area[:, None]).max(1) < self.cfg.proposal_overlap]


class EntradaDetecciones:
    """Entra: detecciones del detector EXTERNO, Nx6 [x1, y1, x2, y2, conf, clase] en píxeles del frame ORIGINAL
    (clase = id entero >= 0). Sale: detecciones en píxeles de TRABAJO, sin cajas gigantes, + propuestas (clase -1)."""

    def __init__(self, cfg, fps):
        self.cfg = cfg
        self.propuestas = Propuestas(cfg, fps) if cfg.use_proposals else None

    @staticmethod
    def revisar(dets):
        """Convierte a Nx6 float32 y avisa con un mensaje claro si el formato no es el esperado."""
        if dets is None:
            return np.zeros((0, 6), np.float32)
        d = np.asarray(dets, np.float32)
        if d.size == 0:
            return np.zeros((0, 6), np.float32)
        if d.ndim != 2 or d.shape[1] < 6:
            raise ValueError(f"Las detecciones deben ser Nx6 [x1, y1, x2, y2, conf, clase]; llegó {d.shape}")
        d = d[:, :6]
        if np.any(d[:, 2] < d[:, 0]) or np.any(d[:, 3] < d[:, 1]):
            raise ValueError("Cajas con x2 < x1 o y2 < y1: ¿el detector devuelve [x, y, ancho, alto]? Hay que pasarlas a esquinas.")
        return d

    def preparar(self, dets, escala, gray, H, ok):
        d = escala.a_trabajo(self.revisar(dets))
        if len(d):
            area = (d[:, 2] - d[:, 0]) * (d[:, 3] - d[:, 1])
            d = d[area <= self.cfg.max_box_area_frac * escala.ww * escala.wh]
        if self.propuestas is not None:
            pr = self.propuestas.paso(gray, H, ok, d)
            if len(pr):
                d = np.vstack([d, pr]) if len(d) else pr
        return d


# ======================================================================
# PARTE 5 · Track
# Qué hace : Objeto 'track' común: caja, votos de clase, historial ESTABILIZADO y estado de movimiento
# ¿Se toca? : No
# ======================================================================
class Track:
    """El historial de centros (pts) está siempre en coordenadas del frame ACTUAL: cada frame se re-proyecta con H.
    Así un objeto quieto en el suelo tiene un historial quieto aunque el dron se mueva."""

    def __init__(self, tid, det, fidx, maxlen, cls_min_conf=0.40, cls_min_hits=3):
        self.id = tid
        self.box = det[:4].astype(np.float32).copy()
        self.conf = float(det[4])
        self.hits, self.miss = 1, 0
        self.cls_min_conf, self.cls_min_hits = cls_min_conf, cls_min_hits
        self.votes = defaultdict(float)
        self.counts = defaultdict(int)
        self._vote(det)
        self.pts = np.array([self._center()], np.float32)   # historial de centros (frame actual)
        self.gs = np.zeros((1, 2), np.float32)             # flujo que la cámara induce en el track, por frame (paralaje)
        self._g = np.zeros(2, np.float32)
        self.maxlen = maxlen
        self.first = self.last = fidx
        # estado de movimiento (lo llena DecisorMovimiento)
        self.disp, self.vec, self.moving = 0.0, np.zeros(2, np.float32), False
        self.straight, self.par, self.k_par = 1.0, False, None
        self.on_cnt = self.off_cnt = 0
        self.toggles = self.moving_frames = self.par_frames = 0
        self.max_disp = 0.0

    def _center(self):
        return [(self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2]

    def _vote(self, det):
        if det[5] >= 0 and det[4] >= self.cls_min_conf:
            self.votes[int(det[5])] += float(det[4]); self.counts[int(det[5])] += 1

    @property
    def cls(self):
        """Clase más votada (suma de confianzas) si tiene al menos cls_min_hits votos; si no, -1 (desconocido)."""
        if not self.votes:
            return -1
        c = max(self.votes, key=self.votes.get)
        return c if self.counts[c] >= self.cls_min_hits else -1

    def warp(self, H, H_ok=True):
        """Lleva caja e historial al frame actual con H. Sin H fiable, el historial se reinicia (no es comparable)."""
        old_c = np.array(self._center(), np.float32)
        self.box = warp_pts(H, [self.box[:2], self.box[2:]]).reshape(-1).astype(np.float32)
        self._g = np.array(self._center(), np.float32) - old_c          # flujo del suelo en este punto
        self.pts = warp_pts(H, self.pts)
        A = (H[:2, :2] / H[2, 2]).astype(np.float32)
        self.gs = self.gs @ A.T
        if not H_ok:
            self.pts, self.gs = self.pts[-1:], self.gs[-1:]

    def update(self, det, fidx):
        self.box = det[:4].astype(np.float32).copy()
        self.conf = float(det[4])
        self.hits += 1; self.miss = 0; self.last = fidx
        self._vote(det)
        self.pts = np.vstack([self.pts, self._center()])[-self.maxlen:]
        self.gs = np.vstack([self.gs, self._g])[-self.maxlen:]


# ======================================================================
# PARTE 6 · LibroTracks
# Qué hace : Para trackers EXTERNOS (UCMC, ByteTrack, BoT-SORT): convierte su salida (ids + cajas) en objetos Track
# ¿Se toca? : No
# ======================================================================
class LibroTracks:
    """Entra: salida del tracker externo, Nx7 [x1, y1, x2, y2, id, conf, clase] (trabajo). Sale: Track confirmados.
    Así la decisión de movimiento y la salida son EXACTAMENTE las mismas que en el tracker propio."""

    def __init__(self, cfg, fps):
        self.cfg = cfg
        self.tracks = {}
        self.max_miss = max(2, int(round(cfg.max_miss_sec * fps)))
        self.maxlen = int(round(cfg.window_sec * fps)) + 1

    def actualizar(self, out, H, H_ok, fidx):
        for t in self.tracks.values():
            t.warp(H, H_ok)
        vistos = set()
        for r in out:
            tid = int(r[4])
            det = np.array([r[0], r[1], r[2], r[3], r[5], r[6]], np.float32)
            if tid in self.tracks:
                self.tracks[tid].update(det, fidx)
            else:
                self.tracks[tid] = Track(tid, det, fidx, self.maxlen, self.cfg.cls_min_conf, self.cfg.cls_min_hits)
            vistos.add(tid)
        for tid in list(self.tracks):
            if tid not in vistos:
                self.tracks[tid].miss += 1
                if self.tracks[tid].miss > self.max_miss:
                    del self.tracks[tid]
        return [t for t in self.tracks.values() if t.hits >= self.cfg.min_hits and t.miss == 0]


# ======================================================================
# PARTE 7 · DecisorMovimiento
# Qué hace : Decide si cada track se mueve DE VERDAD (no por el movimiento del dron)
# ¿Se toca? : No (parámetros en Config → [MOVIMIENTO], [PARALAJE])
# ======================================================================
def ids_sin_paralaje(nombres_clases, cfg):
    """Ids de las clases que no pasan por el filtro de paralaje (vehículos: no sobresalen del suelo como un poste)."""
    return {i for i, n in (nombres_clases or {}).items() if str(n).lower() in cfg.parallax_skip}


class DecisorMovimiento:
    """Mide el desplazamiento NETO del track en la ventana (window_sec) en coordenadas estabilizadas, con tres defensas:
      1) avanzar en línea (min_straightness): el ruido de la caja deambula, un objeto real avanza;
      2) umbral que crece con el tamaño del objeto (rel_move);
      3) paralaje: si el desplazamiento es proporcional al flujo acumulado del suelo, es algo alto y quieto (poste).
    Histéresis: on_frames evaluaciones seguidas para encender, off_frames para apagar."""

    def __init__(self, cfg, fps, skip_ids=()):
        self.cfg = cfg
        self.W = int(round(cfg.window_sec * fps))
        self.thr = cfg.min_move_px
        self.skip_ids = set(skip_ids)

    @staticmethod
    def _rectitud(p):
        """Desplazamiento neto / recorrido, sobre 6 tramos (medianas) para no contar el jitter de la caja."""
        if len(p) < 6:
            return 1.0
        m = np.array([np.median(ch, 0) for ch in np.array_split(p, 6)])
        recorrido = float(np.linalg.norm(np.diff(m, axis=0), axis=1).sum())
        return float(np.linalg.norm(m[-1] - m[0]) / (recorrido + 1e-6))

    def _es_paralaje(self, t, n):
        """Si el objeto está quieto en el mundo, su desplazamiento estabilizado P(t) es proporcional al flujo
        acumulado del suelo en ese punto C(t):  P(t) ≈ k·C(t).  k > 0: sobresale del suelo; k ≈ -1: fijo en la imagen.
        Se exige dirección paralela, k en [k_min, k_max] y buen ajuste en el tiempo (R²)."""
        c = self.cfg
        p, g = t.pts[-n:], t.gs[-n:]
        if len(p) < 6 or t.disp < 1e-6:
            t.k_par = None
            return False
        P = p - p[0]
        C = np.cumsum(g, 0); C = C - C[0]
        Gn = float(np.linalg.norm(C[-1]))
        if Gn < c.parallax_min_ground_px:
            t.k_par = None
            return False
        cos = float(t.vec @ C[-1]) / (t.disp * Gn)
        k = float((P * C).sum() / ((C * C).sum() + 1e-9))
        fit = 1.0 - float(((P - k * C) ** 2).sum()) / (float((P ** 2).sum()) + 1e-9)
        t.k_par = k
        return (abs(cos) >= np.cos(np.deg2rad(c.parallax_angle_deg))
                and c.parallax_k_min <= k <= c.parallax_k_max and fit >= c.parallax_min_fit)

    def actualizar(self, tracks, H_ok):
        c = self.cfg
        if not H_ok:                                                     # sin H fiable no se decide (se mantiene el estado)
            return
        disps = []
        for t in tracks:                                                 # 1) desplazamiento neto en la ventana
            n = min(len(t.pts), self.W + 1)
            if n < max(5, int(0.5 * self.W)):
                t.disp = 0.0; t.vec = np.zeros(2, np.float32); t.par = False; continue
            p = t.pts[-n:]; k = max(1, n // 5)
            t.vec = (np.median(p[-k:], 0) - np.median(p[:k], 0)).astype(np.float32)
            t.disp = float(np.linalg.norm(t.vec))
            disps.append(t.disp)
        self.thr = c.min_move_px
        if c.adaptive and len(disps) >= 5:
            med = np.median(disps); mad = np.median(np.abs(np.array(disps) - med)) * 1.4826
            self.thr = float(min(max(c.min_move_px, med + c.mad_k * mad), c.max_adaptive_px))
        for t in tracks:                                                 # 2) ¿cuenta como movimiento?
            n = min(len(t.pts), self.W + 1)
            if len(t.pts) < max(5, int(0.5 * self.W)):
                continue
            t.straight = self._rectitud(t.pts[-n:])
            size = float(np.sqrt(max((t.box[2] - t.box[0]) * (t.box[3] - t.box[1]), 1.0)))
            thr_t = max(self.thr, c.rel_move * size)
            bw, bh = t.box[2] - t.box[0], t.box[3] - t.box[1]
            estructura = t.cls < 0 and max(bw, bh) / max(min(bw, bh), 1.0) > c.max_unknown_aspect
            raw = t.disp > thr_t and t.straight >= c.min_straightness and not estructura
            t.par = False
            if raw and c.parallax_filter and t.cls not in self.skip_ids and self._es_paralaje(t, n):
                raw, t.par = False, True
                t.par_frames += 1
            if raw:                                                      # 3) histéresis
                t.on_cnt += 1; t.off_cnt = 0
            else:
                t.off_cnt += 1; t.on_cnt = 0
            if not t.moving and t.on_cnt >= c.on_frames:
                t.moving = True; t.toggles += 1
            elif t.moving and t.off_cnt >= c.off_frames:
                t.moving = False; t.toggles += 1
            t.moving_frames += int(t.moving)
            t.max_disp = max(t.max_disp, t.disp)


# ======================================================================
# PARTE 8 · Salida
# Qué hace : Lo que devuelve actualizar(): un TrackSalida por track confirmado, en píxeles del frame ORIGINAL
# ¿Se toca? : No
# ======================================================================
@dataclass
class TrackSalida:
    id: int
    caja: tuple                 # (x1, y1, x2, y2) en píxeles del frame original
    conf: float                 # confianza de la última detección asociada
    clase: int                  # id de clase votado (-1 = desconocido / propuesta)
    nombre_clase: str
    en_movimiento: bool         # decisión de DecisorMovimiento (con histéresis)
    desplazamiento_px: tuple    # desplazamiento neto en la ventana (≈ window_sec), estabilizado, px originales
    paralaje: bool = False      # True = parecía moverse pero lo explica el paralaje (algo alto y quieto)


def a_salida(tracks, escala, nombres_clases):
    nombres = nombres_clases or {}
    out = []
    for t in tracks:
        cls = t.cls
        out.append(TrackSalida(id=int(t.id), caja=tuple(float(x) for x in escala.a_original(t.box)), conf=round(t.conf, 3),
                               clase=int(cls), nombre_clase=nombres.get(cls, "desconocido") if cls >= 0 else "desconocido",
                               en_movimiento=bool(t.moving), desplazamiento_px=tuple(float(x) for x in t.vec / escala.k),
                               paralaje=bool(t.par)))
    return out


def como_array(salida):
    """TrackSalida -> Nx7 [x1, y1, x2, y2, id, conf, clase] (el formato que piden la mayoría de benchmarks MOT)."""
    return np.array([[*s.caja, s.id, s.conf, s.clase] for s in salida], np.float32).reshape(-1, 7)


class Cronometro:
    """Milisegundos de cada etapa del último frame (para saber si llega a tiempo real). tracker.tiempos_ms."""

    def __init__(self):
        self.ms, self._t = {}, None

    def inicio(self):
        self.ms, self._t = {}, time.perf_counter()

    def marca(self, etapa):
        t = time.perf_counter()
        self.ms[etapa] = round(1000 * (t - self._t), 2)
        self._t = t


# ======================================================================
# PARTE 9 · dibujar
# Qué hace : Dibuja la salida sobre el frame original (solo para ver; no afecta al tracking)
# ¿Se toca? : No
# ======================================================================
VERDE, ROJO, NARANJA, GRIS = (60, 200, 60), (40, 40, 255), (0, 150, 255), (170, 170, 170)


def color_id(tid):
    """Color estable por ID: un cambio de color sobre el mismo objeto = el tracker le cambió el ID."""
    c = cv2.cvtColor(np.uint8([[[int((tid * 47) % 180), 220, 230]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(c[0]), int(c[1]), int(c[2])


def dibujar(frame, salida, titulo=None):
    """Verde = quieto · Rojo = se mueve (con clase) · Naranja = se mueve (sin clase) · Gris = descartado por paralaje.
    El recuadro con número es el ID (cada ID, su color)."""
    for s in salida:
        if not s.en_movimiento and s.clase < 0 and not s.paralaje:
            continue                                                     # propuesta quieta: no aporta nada
        color = GRIS if (s.paralaje and not s.en_movimiento) else (VERDE if not s.en_movimiento else (ROJO if s.clase >= 0 else NARANJA))
        x1, y1, x2, y2 = (int(round(v)) for v in s.caja)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        txt = f"{s.id}"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, max(th + 8, y1)), color_id(s.id), -1)
        cv2.putText(frame, txt, (x1 + 4, max(th + 4, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, s.nombre_clase, (x1 + tw + 12, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    n_mov = sum(s.en_movimiento for s in salida)
    cv2.putText(frame, f"{titulo + ' | ' if titulo else ''}en movimiento: {n_mov} | tracks: {len(salida)}", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return frame
