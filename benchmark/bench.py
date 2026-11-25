"""
bench.py — Punto de entrada del benchmark
==========================================

    python bench.py detectar  [--manifiesto secuencias.yaml] [--seq vigia_9 ...] [--rehacer]
    python bench.py ego       [...]                  # H de referencia + covariables de ego-movimiento
    python bench.py correr    --run NOMBRE [...]     # trackers sobre las detecciones cacheadas
    python bench.py moving    [...]                  # propuesta automática de la etiqueta moving + lista de revisión
    python bench.py evaluar   --run NOMBRE [...]     # TrackEval + análisis por ego-movimiento + decisor + sin GT
    python bench.py barrer    --run NOMBRE [--contra RUN]   # rejilla de cámara de UCMC (D17) → barrido/seleccion.csv
    python bench.py todo      --run NOMBRE [...]     # detectar → ego → correr → evaluar

    --split ajuste|test   solo las secuencias de ese split (el flujo congela entre ajuste y test, D29)
    --detector NOMBRE     usa ese detector del manifiesto en todas las secuencias (p. ej. yolo8n en la Mac)
    Rutas de datos: variable de entorno BENCH_DATOS (si no, `datos_raiz` del manifiesto).

Orden recomendado la primera vez: detectar → ego → moving (revisar a mano) → correr → evaluar.
"""
import argparse
from pathlib import Path

from comunes import RAIZ_BENCH, cargar_manifiesto, fps_de, info_video


def _secs(man, nombres):
    return [s for s in man.secuencias if not nombres or s.nombre in nombres]


def _filtrar(man, a):
    """--split y --detector se aplican al manifiesto antes de cualquier etapa."""
    if a.split:
        man.secuencias = [s for s in man.secuencias if s.split == a.split]
    if a.detector:
        if a.detector not in man.detectores:
            raise SystemExit(f"Detector '{a.detector}' no está en el manifiesto: {sorted(man.detectores)}")
        for s in man.secuencias:
            s.detector = a.detector
    return man


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


def cmd_barrer(man, a):
    import pandas as pd
    from barrido import barrer, fraccion_rejilla_gana
    from comunes import DIR_RUNS
    df, sel, val = barrer(man, a.run, a.seq or None)
    if len(val):
        print(f"[barrer] criterio sin GT: rho media con HOTA en ajuste = {val.rho_singt_hota.mean():.2f} "
              f"(válido si ≤ -{man.barrido.get('singt_rho_min', 0.6)})")
    print(sel.to_string(index=False))
    if a.contra:
        m = DIR_RUNS / a.contra / "eval" / "metricas.csv"
        if m.exists():
            f = fraccion_rejilla_gana(df, pd.read_csv(m))
            f.to_csv(DIR_RUNS / a.run / "barrido" / "fraccion_rejilla_gana.csv", index=False)
            print(f.round(3).to_string(index=False))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando", choices=["detectar", "ego", "moving", "correr", "evaluar", "barrer", "todo"])
    p.add_argument("--manifiesto", default=str(RAIZ_BENCH / "secuencias.yaml"))
    p.add_argument("--seq", nargs="*", default=None, help="solo estas secuencias")
    p.add_argument("--run", default=None, help="nombre del run (carpeta en runs/)")
    p.add_argument("--rehacer", action="store_true")
    p.add_argument("--semilla", type=int, default=0)
    p.add_argument("--dispositivo", default=None, help="cpu, mps, 0 (cuda)…")
    p.add_argument("--contra", default=None, help="barrer: run con los rivales evaluados (fracción de rejilla que gana)")
    p.add_argument("--split", choices=["ajuste", "test"], default=None)
    p.add_argument("--detector", default=None, help="detector del manifiesto para todas las secuencias")
    a = p.parse_args()
    man = _filtrar(cargar_manifiesto(a.manifiesto), a)
    if a.comando in ("correr", "evaluar", "barrer", "todo") and not a.run:
        p.error("--run es obligatorio para correr/evaluar/barrer")
    pasos = {"detectar": [cmd_detectar], "ego": [cmd_ego], "moving": [cmd_moving], "correr": [cmd_correr],
             "evaluar": [cmd_evaluar], "barrer": [cmd_barrer], "todo": [cmd_detectar, cmd_ego, cmd_correr, cmd_evaluar]}[a.comando]
    for f in pasos:
        f(man, a)


if __name__ == "__main__":
    main()
