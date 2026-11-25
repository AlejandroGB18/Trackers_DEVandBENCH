"""
adaptadores/uavdt.py — UAVDT-MOT → formato del benchmark (D18, D19, D24)
=========================================================================

Entrada (tal como se descarga, bajo `<datos_raiz>/UAVDT/`):
    UAV-benchmark-M/Mxxxx/img000001.jpg …           frames 1024×540, 30 fps
    UAV-benchmark-MOTD_v1.0/GT/Mxxxx_gt.txt          GT oficial de MOT: frame,id,x,y,w,h,score(1=evaluar),-1,-1
    UAV-benchmark-MOTD_v1.0/GT/Mxxxx_gt_ignore.txt   regiones ignoradas por frame: frame,id,x,y,w,h,1,-1,-1
    M_attr/{train,test}/Mxxxx_attr.txt               10 banderas 0/1 (ver ATRIBUTOS); la carpeta da el split

Salida:
    <datos_raiz>/UAVDT/gt_benchmark/Mxxxx/gt.txt     frame,id,x,y,w,h,considerar,clase,visibilidad
        vehículos  → clase 1 (car/truck/bus fusionados, D7; el gt.txt oficial no trae clase), considerar = score
        ignoradas  → clase 0, id negativo (no se cruzan con los ids de vehículos)
    secuencias del manifiesto (ver `entradas_manifiesto`)

Decisiones:
- Se usa `_gt.txt` (el GT oficial de MOT, el que evalúa el toolkit de UAVDT), no `_gt_whole.txt` (el de DET).
  En train son idénticos; en test `gt_whole` trae ~5–20 % más cajas que el toolkit de MOT no evalúa.
- Regiones ignoradas: se aplica la regla del harness (D8: predicción con ≥ 50 % de su área dentro), en las 50
  secuencias. El toolkit oficial solo quita predicciones contenidas por completo y solo en 18 secuencias de test;
  es una diferencia de protocolo documentada, no un error.
- Frames evaluados: 1 … último frame con GT (M0207 tiene 885 imágenes pero GT hasta el 571, como recorta el toolkit).

Uso:
    python -m adaptadores.uavdt                       # usa BENCH_DATOS o ../datos
    python -m adaptadores.uavdt --raiz /datos --yaml secuencias.yaml
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

ATRIBUTOS = ["dia", "noche", "niebla", "alt_baja", "alt_media", "alt_alta", "frontal", "lateral", "cenital", "largo"]
DIR_FRAMES = "UAV-benchmark-M"
DIR_GT = "UAV-benchmark-MOTD_v1.0/GT"
DIR_ATTR = "M_attr"
DIR_SALIDA = "gt_benchmark"
FPS = 30.0

# D24: grupos de vuelo y rejilla de cámara de UCMC (bandas de altitud de UAVDT: baja 10–30 m, media 30–70, alta > 70)
GRUPOS = {
    "cenital": dict(pitch=[0, 5, 10, 15, 20, 25], altura=[15, 30, 50, 75, 100], punto="centro"),
    "oblicua_baja": dict(pitch=list(range(25, 71, 5)), altura=[10, 15, 20, 25, 30], punto="base"),
    "oblicua_alta": dict(pitch=list(range(25, 71, 5)), altura=[30, 45, 60, 80, 100], punto="base"),
}
HFOV = 74            # D17.1 / A7: ficha aproximada; UAVDT no publica la cámara exacta


def leer_atributos(raiz):
    """DataFrame: secuencia, split (ajuste|test), las 10 banderas, luz, altitud, vista y grupo de vuelo."""
    filas = []
    for carpeta, split in (("train", "ajuste"), ("test", "test")):
        for f in sorted((Path(raiz) / DIR_ATTR / carpeta).glob("*_attr.txt")):
            v = [int(x) for x in f.read_text().replace("\n", "").replace(" ", "").split(",") if x != ""]
            if len(v) != len(ATRIBUTOS):
                raise ValueError(f"{f}: se esperaban {len(ATRIBUTOS)} banderas, hay {len(v)}")
            filas.append(dict(secuencia=f.name.split("_")[0].strip(), split=split, **dict(zip(ATRIBUTOS, v))))
    if not filas:
        raise FileNotFoundError(f"No hay atributos en {Path(raiz) / DIR_ATTR}")
    d = pd.DataFrame(filas)

    def uno(r, cols, nombres):
        x = [n for c, n in zip(cols, nombres) if r[c]]
        return "+".join(x) if x else "?"

    d["luz"] = d.apply(lambda r: uno(r, ATRIBUTOS[0:3], ["dia", "noche", "niebla"]), axis=1)
    d["altitud"] = d.apply(lambda r: uno(r, ATRIBUTOS[3:6], ["baja", "media", "alta"]), axis=1)
    d["vista"] = d.apply(lambda r: uno(r, ATRIBUTOS[6:9], ["frontal", "lateral", "cenital"]), axis=1)
    d["grupo"] = d.apply(grupo_de, axis=1)
    return d


def grupo_de(r):
    """D24: vista cenital → cenital; frontal/lateral con altitud baja → oblicua_baja; si no → oblicua_alta."""
    if r["cenital"]:
        return "cenital"
    return "oblicua_baja" if r["alt_baja"] else "oblicua_alta"


def _leer(ruta, ncol=9):
    ruta = Path(ruta)
    if not ruta.exists() or ruta.stat().st_size == 0:
        return pd.DataFrame(np.zeros((0, ncol)))
    return pd.read_csv(ruta, header=None).iloc[:, :ncol]


def convertir_gt(raiz, secuencia, destino=None):
    """Escribe gt_benchmark/<seq>/gt.txt. Devuelve (ruta, resumen)."""
    raiz = Path(raiz)
    g = _leer(raiz / DIR_GT / f"{secuencia}_gt.txt")
    ig = _leer(raiz / DIR_GT / f"{secuencia}_gt_ignore.txt")
    if len(g) == 0:
        raise FileNotFoundError(f"{secuencia}: GT vacío o ausente en {raiz / DIR_GT}")
    veh = pd.DataFrame(dict(frame=g[0].astype(int), id=g[1].astype(int), x=g[2], y=g[3], w=g[4], h=g[5],
                            considerar=g[6].astype(int), clase=1, visibilidad=-1))
    reg = pd.DataFrame(dict(frame=ig[0].astype(int), id=-(ig[1].astype(int) + 1), x=ig[2], y=ig[3], w=ig[4], h=ig[5],
                            considerar=1, clase=0, visibilidad=-1)) if len(ig) else veh.iloc[:0]
    out = pd.concat([veh, reg]).sort_values(["frame", "clase", "id"], ascending=[True, False, True])
    destino = Path(destino) if destino else raiz / DIR_SALIDA / secuencia / "gt.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(destino, header=False, index=False, float_format="%.2f")
    n_img = len([f for f in (raiz / DIR_FRAMES / secuencia).iterdir() if f.suffix == ".jpg"]) \
        if (raiz / DIR_FRAMES / secuencia).exists() else None
    return destino, dict(secuencia=secuencia, cajas=len(veh), tracks=veh.id.nunique(), regiones=len(reg),
                         ultimo_frame_gt=int(veh.frame.max()), imagenes=n_img)


def entradas_manifiesto(attr, resumen, detector, prefijo="UAVDT"):
    """Lista de dicts para `secuencias:` (rutas relativas a datos_raiz)."""
    r = {x["secuencia"]: x for x in resumen}
    out = []
    for a in attr.sort_values(["split", "secuencia"]).itertuples():
        s = r[a.secuencia]
        out.append(dict(
            nombre=a.secuencia, video=f"{prefijo}/{DIR_FRAMES}/{a.secuencia}", detector=detector,
            rango=[1, s["ultimo_frame_gt"]], fps=FPS, split=a.split,
            toma="cenital" if a.grupo == "cenital" else "oblicua", grupo=a.grupo,
            ucmc=dict(hfov_deg=HFOV, pitch_respaldo_deg=0 if a.grupo == "cenital" else 45),
            camara_fuente="ficha", gt=f"{prefijo}/{DIR_SALIDA}/{a.secuencia}/gt.txt",
            gt_frames=dict(inicio=1, fin=s["ultimo_frame_gt"], paso=1),
            atributos=dict(luz=a.luz, altitud=a.altitud, vista=a.vista, largo=int(a.largo))))
    return out


def barrido_grupos():
    return {g: dict(v, hfov=HFOV) for g, v in GRUPOS.items()}


def preparar(raiz, verbose=True):
    """Convierte el GT de las 50 secuencias. Devuelve (atributos, resumen)."""
    attr = leer_atributos(raiz)
    resumen = [convertir_gt(raiz, s)[1] for s in attr.secuencia]
    if verbose:
        r = pd.DataFrame(resumen).merge(attr[["secuencia", "split", "grupo", "luz"]], on="secuencia")
        print(r.groupby(["split", "grupo"]).agg(secuencias=("secuencia", "size"), cajas=("cajas", "sum"),
                                                 tracks=("tracks", "sum")).to_string())
        print(f"[uavdt] GT convertido → {Path(raiz) / DIR_SALIDA}")
    return attr, resumen


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    base = Path(__file__).resolve().parents[1]
    p.add_argument("--raiz", default=None, help="carpeta UAVDT (por defecto $BENCH_DATOS/UAVDT o ../datos/UAVDT)")
    p.add_argument("--yaml", default=None, help="si se da, escribe ahí las secuencias (sobrescribe la lista)")
    p.add_argument("--detector", default="yolo8x")
    a = p.parse_args()
    raiz = Path(a.raiz) if a.raiz else Path(os.environ.get("BENCH_DATOS", base.parent / "datos")) / "UAVDT"
    attr, resumen = preparar(raiz)
    if a.yaml:
        n = escribir_secuencias(a.yaml, entradas_manifiesto(attr, resumen, a.detector))
        print(f"[uavdt] {n} secuencias → {a.yaml}")


MARCA = "# ---- secuencias: generado por adaptadores/uavdt.py, no editar a mano ----"


def escribir_secuencias(ruta, entradas):
    """Reemplaza todo lo que va después de MARCA en el manifiesto (lo de arriba, con sus comentarios, se conserva)."""
    import yaml
    ruta = Path(ruta)
    texto = ruta.read_text(encoding="utf-8")
    if MARCA not in texto:
        raise ValueError(f"{ruta} no tiene la línea marcador:\n{MARCA}")
    cabeza = texto.split(MARCA)[0]
    cuerpo = yaml.safe_dump({"secuencias": entradas}, allow_unicode=True, sort_keys=False, width=120,
                            default_flow_style=None)
    ruta.write_text(cabeza + MARCA + "\n" + cuerpo, encoding="utf-8")
    return len(entradas)


if __name__ == "__main__":
    main()
