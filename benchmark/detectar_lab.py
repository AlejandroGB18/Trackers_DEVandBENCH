"""
detectar_lab.py — Detecciones para el benchmark, en la máquina con GPU (D20)
============================================================================

Corre UN modelo de Ultralytics (YOLOv8/11, RT-DETR) sobre carpetas de frames y escribe un archivo por secuencia que
el harness importa con `tipo: archivo`. No necesita el manifiesto: solo la carpeta de secuencias de UAVDT.

    python detectar_lab.py --frames /datos/UAVDT/UAV-benchmark-M --pesos /modelos/yolo8x_best.pt \
                           --salida /datos/detecciones/yolo8x --dispositivo 0
    python detectar_lab.py ... --seq M0101 M0203        # solo algunas
    python detectar_lab.py ... --rehacer                # sobrescribe las que ya existen

Salida:
    <salida>/<secuencia>.txt    frame, -1, x, y, w, h, conf, clase, -1, -1   (frame base 1 = img000001.jpg)
    <salida>/firma.json         modelo, sha256 de los pesos, imgsz, conf, iou, clases, versiones, dispositivo

Umbral bajo (0.05, D2): los trackers hacen una segunda ronda con las débiles; el corte real se aplica en el harness.
Si la firma de una corrida anterior no coincide (otros pesos, imgsz o umbral), se detiene en vez de mezclar.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comunes import guardar_json, info_video, leer_frames, sha256_archivo, versiones  # noqa: E402
from detecciones import detectar_frames, escribir_detecciones_txt  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frames", required=True, help="carpeta con una subcarpeta de frames por secuencia")
    p.add_argument("--pesos", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument("--imgsz", type=int, default=640, help="el de entrenamiento del modelo (640 en los del laboratorio)")
    p.add_argument("--conf", type=float, default=0.05)
    p.add_argument("--iou", type=float, default=0.7)
    p.add_argument("--dispositivo", default=None, help="0 (cuda), cpu, mps")
    p.add_argument("--seq", nargs="*", default=None)
    p.add_argument("--rehacer", action="store_true")
    a = p.parse_args()

    from ultralytics import YOLO
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    modelo = YOLO(a.pesos)
    firma = dict(pesos=Path(a.pesos).name, pesos_sha256=sha256_archivo(a.pesos), imgsz=a.imgsz, conf=a.conf,
                 iou=a.iou, nombres_clases={int(k): v for k, v in modelo.names.items()},
                 train_args={k: v for k, v in ((getattr(modelo, "ckpt", None) or {}).get("train_args") or {}).items()
                             if k in ("model", "data", "imgsz", "epochs")})
    fj = salida / "firma.json"
    if fj.exists():
        previa = json.load(open(fj))
        clave = ("pesos_sha256", "imgsz", "conf", "iou")
        if any(previa.get(k) != firma[k] for k in clave):
            sys.exit(f"{fj} es de otra configuración ({ {k: previa.get(k) for k in clave} }). Usa otra --salida.")
    guardar_json(fj, dict(firma, dispositivo=str(a.dispositivo), versiones=versiones()))

    seqs = sorted(d for d in Path(a.frames).iterdir() if d.is_dir() and (not a.seq or d.name in a.seq))
    if not seqs:
        sys.exit(f"No hay carpetas de secuencias en {a.frames}")
    for d in seqs:
        out = salida / f"{d.name}.txt"
        if out.exists() and not a.rehacer:
            print(f"[detectar_lab] {d.name}: ya existe, se omite")
            continue
        n = info_video(d)["n_frames"]
        t0 = time.time()
        frame, dets, _ = detectar_frames(modelo, leer_frames(d, 1, n), a.imgsz, a.conf, a.iou,
                                         dispositivo=a.dispositivo, nombre=d.name, total=n)
        escribir_detecciones_txt(out.with_suffix(".tmp"), frame, dets)
        out.with_suffix(".tmp").replace(out)          # nunca queda un .txt a medias
        dt = time.time() - t0
        print(f"[detectar_lab] {d.name}: {n} frames, {len(dets)} cajas, {1000 * dt / max(1, n):.0f} ms/frame")


if __name__ == "__main__":
    main()
