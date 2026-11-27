"""
comparar_runs.py — Comprobación D35.3: la v1.1 solo cambia propio_kf.

Compara byte a byte (sha256) las salidas por secuencia de dos runs: <seq>.txt (tracks) y <seq>_lateral.csv
(decisor de movimiento, P2). Los tiempos no se comparan (dependen de la máquina).

Uso (desde benchmark/):
    python analisis/comparar_runs.py runs/v1 runs/v1_1
Termina con código 1 si alguna pareja que debía ser idéntica difiere: en ese caso NO se evalúa (D35.3).
"""
import hashlib
import sys
from pathlib import Path

# (etiqueta en la v1, etiqueta en la v1.1, ¿deben ser idénticas?)
PAREJAS = [
    ("bytetrack", "bytetrack", True),
    ("botsort", "botsort", True),
    ("ucmc_grupo_train", "ucmc_grupo_train", True),
    ("ucmc", "ucmc", True),
    ("ucmc_oraculo_seq", "ucmc_oraculo_seq", True),
    ("propio_kf", "propio_kf_v1", True),       # la v1 corrida otra vez
    ("propio_kf", "propio_kf", False),         # la corrección: debe cambiar
]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def comparar(run_a, run_b):
    run_a, run_b = Path(run_a), Path(run_b)
    malas = []
    for ea, eb, iguales in PAREJAS:
        da, db = run_a / ea, run_b / eb
        if not da.exists() or not db.exists():
            print(f"  FALTA  {da if not da.exists() else db}")
            malas.append(eb)
            continue
        archivos = sorted(p.name for p in da.iterdir() if p.name.endswith((".txt", "_lateral.csv")))
        dif = [n for n in archivos if not (db / n).exists() or sha(da / n) != sha(db / n)]
        ok = (not dif) if iguales else bool(dif)
        estado = "OK " if ok else "MAL"
        esperado = "idénticas" if iguales else "distintas"
        print(f"  {estado} {ea:>17} (v1) vs {eb:<17} (v1.1): {len(archivos) - len(dif)}/{len(archivos)} archivos "
              f"iguales; se esperaban {esperado}" + (f"; difieren: {dif[:6]}" if dif and iguales else ""))
        if not ok:
            malas.append(eb)
    return malas


if __name__ == "__main__":
    a, b = (sys.argv[1:3] if len(sys.argv) >= 3 else ("runs/v1", "runs/v1_1"))
    print(f"[comparar_runs] {a} contra {b}")
    malas = comparar(a, b)
    if malas:
        print(f"[comparar_runs] NO EVALUAR: {malas} no cumplen D35.3. Pásame esta salida.")
        sys.exit(1)
    print("[comparar_runs] TODO OK: solo cambió propio_kf (D35.3). Se puede evaluar.")
