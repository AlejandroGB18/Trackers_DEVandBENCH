"""
tracker_bytetrack.py — ByteTrack (Ultralytics) con nuestras detecciones
========================================================================

Qué es: Kalman de velocidad constante EN LA IMAGEN + asociación por IoU en dos rondas (fuertes y débiles).
No compensa el movimiento de la cámara: si el dron gira o avanza, la predicción apunta al lugar equivocado.
Es la REFERENCIA: lo que hace el tracker estándar sin saber nada del dron.

La H se calcula igual (paso 2) pero ByteTrack NO la usa para asociar: solo la usa el paso 7 (¿se mueve?), que es
el mismo para todos los trackers.

Pipeline de un frame (TrackerByteTrack.actualizar):
      1. Escala · 2. Estabilización (solo para el paso 7) · 3. Entrada
      4. ByteTrack de Ultralytics (asociación en la imagen, sin H)                (adaptador_ultralytics)
      5. Libro: salida -> Track con historial estabilizado                         (comun.LibroTracks)
      6. ¿Se mueve? · 7. Salida

Uso:
    from tracker_bytetrack import TrackerByteTrack
    tracker = TrackerByteTrack(fps=30, nombres_clases=detector.names)
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
# PARTE 1 · TrackerByteTrack
# Qué hace : El pipeline completo de un frame
# ¿Se toca? : No (los umbrales son los comunes de Config; el resto, el bytetrack.yaml de Ultralytics)
# ======================================================================
class TrackerByteTrack:
    nombre = "bytetrack"

    def __init__(self, fps, cfg=None, nombres_clases=None):
        self.cfg = cfg or Config()
        self.fps = float(fps)
        self.nombres_clases = dict(nombres_clases or {})
        c = self.cfg
        self.escala = None
        self.estabilizador = Estabilizador(c)
        self.entrada = EntradaDetecciones(c, fps)
        self.externo = TrackerUltralytics("bytetrack", c, fps)
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
        confirmados = self.seguir(dets, small, H, ok)                    # 4-5. ByteTrack + libro
        self.cron.marca("tracking")
        self.decisor.actualizar(confirmados, ok)                         # 6. ¿Se mueve?
        self.cron.marca("movimiento")
        self.frame += 1
        return a_salida(confirmados, self.escala, self.nombres_clases)   # 7. Salida

    def seguir(self, dets, small, H, H_ok):
        self.salida_externa = self.externo.update(dets, small)
        return self.libro.actualizar(self.salida_externa, H, H_ok, self.frame)
