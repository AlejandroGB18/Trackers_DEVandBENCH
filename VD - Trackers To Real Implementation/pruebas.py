"""
pruebas.py — Self-tests de todos los trackers. Ejecutar ANTES de usarlos en un entorno nuevo:  python pruebas.py
"""
import cv2
import numpy as np

import tracker_propio
import tracker_ucmc
from comun import Config, EntradaDetecciones, Escala, como_array


def prueba_comun():
    """Escala ida y vuelta, formato de detecciones y salida para benchmarks."""
    cfg = Config(use_proposals=False)
    esc = Escala(cfg, (2160, 3840, 3))                                   # frame 4K -> trabajo 960 x 540
    assert (esc.ww, esc.wh) == (960, 540)
    d = np.array([[400, 400, 480, 440, 0.9, 2]], np.float32)
    assert np.allclose(esc.a_original(esc.a_trabajo(d)[0, :4]), d[0, :4]), "ida y vuelta"
    try:
        EntradaDetecciones.revisar(np.array([[400, 400, 80, 40, 0.9, 2]]))     # [x, y, w, h] por error
        raise AssertionError("debió avisar de cajas al revés")
    except ValueError:
        pass
    assert EntradaDetecciones.revisar(None).shape == (0, 6) and EntradaDetecciones.revisar([]).shape == (0, 6)
    assert como_array([]).shape == (0, 7)
    print("comun OK | escala ida y vuelta, aviso de formato [x, y, w, h], detecciones vacías")


def prueba_pipeline_completo():
    """Los pipelines completos (frame + detecciones en píxeles ORIGINALES) con un video sintético: un auto que cruza
    sobre fondo con textura y la cámara en paneo. Debe salir 1 ID, en movimiento, con la caja en píxeles originales."""
    rng = np.random.default_rng(0)
    fondo = cv2.GaussianBlur((rng.random((1200, 4000)) * 255).astype(np.uint8), (7, 7), 0)
    fondo = cv2.cvtColor(fondo, cv2.COLOR_GRAY2BGR)
    W, H = 1920, 1080
    trackers = {"propio": tracker_propio.TrackerPropio(30.0, nombres_clases={2: "car"}),
                "ucmc": tracker_ucmc.TrackerUCMC(30.0, nombres_clases={2: "car"})}
    ultimo = {}
    for f in range(90):
        cam_x = 4 * f                                                    # la cámara se desplaza 4 px/frame
        frame = fondo[60:60 + H, cam_x:cam_x + W].copy()
        x = 300 + 12 * f - cam_x                                         # el auto avanza 12 px/frame en el suelo
        cv2.rectangle(frame, (x, 500), (x + 80, 540), (0, 0, 255), -1)
        dets = np.array([[x, 500, x + 80, 540, 0.9, 2]], np.float32)
        for k, t in trackers.items():
            ultimo[k] = t.actualizar(frame, dets)
    for k, t in trackers.items():
        s = ultimo[k]
        assert len(s) == 1 and s[0].en_movimiento and s[0].nombre_clase == "car", (k, s)
        assert abs(s[0].caja[0] - x) < 6, (k, s[0].caja, x)
        print(f"pipeline {k} OK | 1 ID tras 90 frames, en movimiento, caja en píxeles originales | ms por frame: {t.tiempos_ms}")


def prueba_ultralytics():
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("ByteTrack / BoT-SORT: ultralytics no está instalado (no hace falta para el propio ni para UCMC)")
        return
    from tracker_botsort import TrackerBoTSORT
    from tracker_bytetrack import TrackerByteTrack
    img = (np.random.default_rng(0).random((540, 960, 3)) * 255).astype(np.uint8)
    d = np.array([[100, 100, 140, 160, 0.9, 2], [300, 200, 360, 260, 0.8, 0]], np.float32)
    for Cls in (TrackerByteTrack, TrackerBoTSORT):
        t = Cls(30.0, Config(work_width=960, use_proposals=False))
        for _ in range(6):
            out = t.actualizar(img, d)
        assert len(out) == 2, (Cls.__name__, out)
        print(f"{Cls.__name__} OK | 2 tracks confirmados")


if __name__ == "__main__":
    prueba_comun()
    tracker_propio.selftest()
    tracker_ucmc.selftest()
    prueba_pipeline_completo()
    prueba_ultralytics()
    print("\nTODO OK")
