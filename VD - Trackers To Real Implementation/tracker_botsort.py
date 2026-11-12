"""
tracker_botsort.py — BoT-SORT (Ultralytics) con nuestras detecciones, con su propia compensación de cámara (GMC)
================================================================================================================

Qué es: ByteTrack + GMC: antes de asociar, BoT-SORT estima el movimiento de la cámara por SU cuenta (flujo óptico
disperso sobre la imagen, "sparseOptFlow") y corrige la predicción del Kalman. Sin ReID (no necesita otro modelo).
Diferencia con el propio: el propio usa NUESTRA H (homografía con puntos repartidos por toda la imagen y RANSAC
ajustado al suelo); BoT-SORT usa una transformación afín propia. Por eso le pasamos la imagen de trabajo.

La H nuestra (paso 2) solo la usa el paso 6 (¿se mueve?), igual que en todos los trackers.

Pipeline de un frame (TrackerBoTSORT.actualizar):
      1. Escala · 2. Estabilización (solo para el paso 6) · 3. Entrada
      4. BoT-SORT de Ultralytics (GMC propio + asociación en la imagen)           (adaptador_ultralytics)
      5. Libro: salida -> Track con historial estabilizado                         (comun.LibroTracks)
      6. ¿Se mueve? · 7. Salida

Uso:
    from tracker_botsort import TrackerBoTSORT
    tracker = TrackerBoTSORT(fps=30, nombres_clases=detector.names)          # gmc="none" = sin compensar
    tracks = tracker.actualizar(frame_bgr, detecciones_Nx6)
"""
# ======================================================================
# IMPORTACIONES
# Qué hace : Carga las piezas comunes y el adaptador de Ultralytics
# ¿Se toca? : No
# ======================================================================
import numpy as np

from adaptador_ultralytics import TrackerUltralytics
from comun import (Config, Cronometro, DecisorMovimiento, EntradaDetecciones, Escala, Estabilizador, LibroTracks, a_salida,
                   ids_sin_paralaje)


# ======================================================================
# PARTE 1 · TrackerBoTSORT
# Qué hace : El pipeline completo de un frame
# ¿Se toca? : gmc ("sparseOptFlow" por defecto, como en la comparativa). Umbrales: los comunes de Config
# ======================================================================
class TrackerBoTSORT:
    nombre = "botsort"

    def __init__(self, fps, cfg=None, nombres_clases=None, gmc="sparseOptFlow"):
        self.cfg = cfg or Config()
        self.fps = float(fps)
        self.nombres_clases = dict(nombres_clases or {})
        c = self.cfg
        self.escala = None
        self.estabilizador = Estabilizador(c)
        self.entrada = EntradaDetecciones(c, fps)
        self.externo = TrackerUltralytics("botsort", c, fps, gmc=gmc)
        self.libro = LibroTracks(c, fps)
        self.decisor = DecisorMovimiento(c, fps, ids_sin_paralaje(self.nombres_clases, c))
        self.frame = 0
        self.cron = Cronometro()
        self.salida_externa = np.zeros((0, 7), np.float32)

    @property
    def tiempos_ms(self):
        return self.cron.ms

    def actualizar(self, frame_bgr, detecciones):
        self.cron.inicio()
        if self.escala is None:                                          # 1. Escala
            self.escala = Escala(self.cfg, frame_bgr.shape)
        small, gray = self.escala.frame(frame_bgr)
        self.cron.marca("escala")
        H, ok = self.estabilizador.paso(gray)                            # 2. Estabilización (solo para el paso 6)
        self.cron.marca("estabilizacion")
        dets = self.entrada.preparar(detecciones, self.escala, gray, H, ok)   # 3. Entrada
        self.cron.marca("entrada")
        confirmados = self.seguir(dets, small, H, ok)                    # 4-5. BoT-SORT (con su GMC) + libro
        self.cron.marca("tracking")
        self.decisor.actualizar(confirmados, ok)                         # 6. ¿Se mueve?
        self.cron.marca("movimiento")
        self.frame += 1
        return a_salida(confirmados, self.escala, self.nombres_clases)   # 7. Salida

    def seguir(self, dets, small, H, H_ok):
        self.salida_externa = self.externo.update(dets, small)          # small = imagen para su GMC
        return self.libro.actualizar(self.salida_externa, H, H_ok, self.frame)
