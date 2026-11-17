"""
bench.py — Punto de entrada del benchmark
==========================================

    python bench.py detectar  [--manifiesto secuencias.yaml] [--seq vigia_9 ...] [--rehacer]
    python bench.py ego       [...]                  # H de referencia + covariables de ego-movimiento
    python bench.py correr    --run NOMBRE [...]     # trackers sobre las detecciones cacheadas
    python bench.py moving    [...]                  # propuesta automática de la etiqueta moving + lista de revisión
    python bench.py evaluar   --run NOMBRE [...]     # TrackEval + análisis por ego-movimiento + decisor + sin GT
    python bench.py todo      --run NOMBRE [...]     # detectar → ego → correr → evaluar

Orden recomendado la primera vez: detectar → ego → moving (revisar a mano) → correr → evaluar.
"""
import argparse
from pathlib import Path

from comunes import RAIZ_BENCH, cargar_manifiesto, fps_de, info_video


def _secs(man, nombres):
    return [s for s in man.secuencias if not nombres or s.nombre in nombres]


def cmd_detectar(man, a):
    from detecciones import cachear
    for s in _secs(man, a.seq):
        cachear(s, s.detector, man.detectores[s.detector], rehacer=a.rehacer, dispositivo=a.dispositivo)


def cmd_ego(man, a):
    from detecciones import CacheDetecciones, ruta_cache
    from ego import calcular
    for s in _secs(man, a.seq):
        rc = ruta_cache(s, s.detector)
        calcular(s, CacheDetecciones(rc) if rc.exists() else None, rehacer=a.rehacer)


def cmd_moving(man, a):
    from comunes import leer_gt
    from ego import leer, ruta_cache
    from gt import derivar_moving, lista_revision
    for s in _secs(man, a.seq):
        if not s.gt:
            print(f"[moving] {s.nombre}: sin GT, se omite")
            continue
        m = derivar_moving(leer_gt(s.gt), leer(ruta_cache(s)), fps_de(s), info_video(s.video)["ancho"],
                           toma=s.toma or "cenital", clases=man.evaluacion.get("clases_evaluadas"))
        dest = Path(s.gt).with_name("moving_auto.csv")
        m.to_csv(dest, index=False)
        rev = lista_revision(m)
        rev.to_csv(dest.with_name("moving_revisar.csv"), index=False)
        n = m.moving.value_counts().to_dict()
        print(f"[moving] {s.nombre}: {n} (1 móvil, 0 quieto, -1 dudoso); {len(rev)} casos a revisar → {dest.parent}")


def cmd_correr(man, a):
    from correr import correr
    correr(man, a.run, a.seq or None, semilla=a.semilla)


def cmd_evaluar(man, a):
    from comunes import DIR_RUNS
    from evaluar import evaluar_run
    s = evaluar_run(man, DIR_RUNS / a.run, a.seq or None)
    m = s["metricas"]
    if len(m):
        cols = ["protocolo", "tracker", "secuencia", "HOTA", "DetA", "AssA", "IDF1", "MOTA", "IDSW"]
        print(m[m.secuencia == "COMBINADO"][cols].round(2).to_string(index=False))
    else:
        print(s["sin_gt"].round(2).to_string(index=False))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["detectar", "ego", "moving", "correr", "evaluar", "todo"])
    p.add_argument("--manifiesto", default=str(RAIZ_BENCH / "secuencias.yaml"))
    p.add_argument("--seq", nargs="*", default=None, help="solo estas secuencias")
    p.add_argument("--run", default=None, help="nombre del run (carpeta en runs/)")
    p.add_argument("--rehacer", action="store_true")
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--dispositivo", default=None, help="cpu, mps, 0 (cuda)…")
    a = p.parse_args()
    man = cargar_manifiesto(a.manifiesto)
    if a.comando in ("correr", "evaluar", "todo") and not a.run:
        p.error("--run es obligatorio para correr/evaluar")
    pasos = {"detectar": [cmd_detectar], "ego": [cmd_ego], "moving": [cmd_moving], "correr": [cmd_correr],
             "evaluar": [cmd_evaluar], "todo": [cmd_detectar, cmd_ego, cmd_correr, cmd_evaluar]}[a.comando]
    for f in pasos:
        f(man, a)


if __name__ == "__main__":
    main()
