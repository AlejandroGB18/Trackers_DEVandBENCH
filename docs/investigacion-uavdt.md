# Investigación: dataset UAVDT (parte MOT)

Fecha: 2026-11-23. Objetivo: reunir los datos de UAVDT (Du et al., ECCV 2018) que hacen falta para planificar un benchmark MOT de trackers de vehículos. Investigación solo de lectura: no se descargó ningún archivo del dataset.

Leyenda: **[V]** verificado en la fuente citada · **[T]** fuente de terceros, no oficial · **[NV]** no verificado.

Fuentes principales:
- Paper: https://arxiv.org/abs/1804.00518 (texto HTML en https://ar5iv.labs.arxiv.org/html/1804.00518)
- Página oficial: https://sites.google.com/view/grli-uavdt/
- Loader de TensorBay (describe la estructura del zip): https://github.com/Graviti-AI/tensorbay-python-sdk/tree/main/tensorbay/opendataset/UAVDT
- Repo de UAVMOT (CVPR 2022), con las listas train/test: https://github.com/LiuShuaiyr/UAVMOT
- Conversor a YOLO: https://github.com/forever208/yolov5_train_on_UAVDT

## 1. Split oficial de MOT (30 train / 20 test)

- El paper declara 100 secuencias: 30 de entrenamiento y 70 de test. De las de test, 20 son para DET/MOT y 50 para SOT. Los vídeos de train y test se grabaron en lugares distintos. **[V]** (ar5iv §2.1)
- El zip de atributos oficial `M_attr.zip` trae las subcarpetas `M_attr/train/` y `M_attr/test/`, con un archivo `Mxxxx_attr.txt` por secuencia, así que el split oficial va codificado ahí. **[V]** la estructura está tomada del loader de TensorBay (`loader.py`). No se ha abierto el zip.
- Los nombres de abajo salen de `src/data/UAVDT.train` y `src/data/UAVDT.test` del repo UAVMOT, que salen 30/20 como en el paper. **[T]** Aún no se ha cruzado con `M_attr/train|test`.

Los conteos de frames son las líneas de esas listas, es decir, las imágenes por secuencia que usa UAVMOT. Suman 23 829 en train y 16 574 en test, 40 403 en total. **[T]** No se ha comprobado si coinciden exactamente con las imágenes del zip oficial.

**Test (20):** M0203 (995), M0205 (646), M0208 (265), M0209 (1576), M0403 (514), M0601 (372), M0602 (480), M0606 (1374), M0701 (1308), M0801 (298), M0802 (1101), M1001 (1859), M1004 (269), M1007 (659), M1009 (604), M1101 (858), M1301 (1182), M1302 (719), M1303 (445), M1401 (1050).

**Train (30):** M0101 (407), M0201 (1076), M0202 (291), M0204 (350), M0206 (562), M0207 (571), M0210 (583), M0301 (325), M0401 (613), M0402 (410), M0501 (352), M0603 (2035), M0604 (1079), M0605 (787), M0702 (777), M0703 (683), M0704 (832), M0901 (1906), M0902 (384), M1002 (660), M1003 (1346), M1005 (537), M1006 (708), M1008 (569), M1102 (967), M1201 (1197), M1202 (472), M1304 (1550), M1305 (600), M1306 (1200).

## 2. Atributos por secuencia

Definiciones (paper §2.1 **[V]**, página oficial **[V]**):
- Clima / iluminación: daylight, night o fog.
- Altitud: low-alt de 10 a 30 m, medium-alt de 30 a 70 m, high-alt por encima de 70 m.
- Vista de cámara: front-view, side-view o bird-view. Front y side "may coexist in one sequence", así que una secuencia puede tener varias vistas activas.
- Long-term: la página oficial marca así las secuencias de más de 1500 frames.
- No existe un atributo de "movimiento de cámara". El paper solo dice que la cámara se mueve con el UAV.

Archivo y formato:
- `M_attr.zip`, de 9 503 bytes, en Google Drive con id `1qjipvuk3XE3qU3udluQRRcYuiKzhMXB1`, enlazado desde la página oficial. **[V]** El tamaño se sacó de la cabecera HTTP `content-length`.
- Cada `M_attr/{train,test}/Mxxxx_attr.txt` es una sola fila CSV de 10 enteros 0/1 en este orden: `daylight, night, fog, low-alt, medium-alt, high-alt, front-view, side-view, bird-view, long-term`. **[V]** El orden viene del `catalog.json` y el `loader.py` de TensorBay (https://raw.githubusercontent.com/Graviti-AI/tensorbay-python-sdk/main/tensorbay/opendataset/UAVDT/catalog.json). No se ha mirado un archivo real.

**Tabla de atributos por secuencia: [NV], no se ha encontrado publicada en ningún sitio.** Ni el paper ni la página oficial ni los repos consultados la reproducen. Para tenerla hay que descargar `M_attr.zip` (9,5 KB), y eso queda pendiente de que el usuario lo autorice. Mientras tanto, Dataset Ninja da solo agregados por imagen: daylight 24 055, night 11 501 y fog 5 179; altitud medium 24 059, low 14 644 y high 2 032; vista front 23 601, side 17 672 y bird 10 737 (https://datasetninja.com/uavdt) **[T]**. Las cifras parecen incluir también UAVDT-S, porque Dataset Ninja cuenta 77 819 imágenes.

## 3. Formato de anotación, resolución y fps

- El paper habla de unos 80 000 frames anotados, unas 0,84 M cajas y más de 2 700 vehículos. Las secuencias están a 30 fps, en JPEG, a "1080×540", y se grabaron con un DJI Inspire 2. **[V]** (ar5iv §2)
- Resolución real: **1024×540**. El conversor de forever208 fija `IMG_W = 1024, IMG_H = 540` (`scripts/organise_txt_labels.py`) y Dataset Ninja da ese mismo tamaño en sus muestras. **[T]** Las dos fuentes coinciden, pero no se ha medido ninguna imagen.
- Estructura del zip **[V vía TensorBay]**:
  - `UAV-benchmark-M/Mxxxx/img000001.jpg`: frames numerados desde 1 con seis dígitos.
  - `UAV-benchmark-MOTD_v1.0/GT/Mxxxx_gt.txt`, `Mxxxx_gt_whole.txt` y `Mxxxx_gt_ignore.txt`.
- `*_gt_whole.txt` (GT de DET y la más completa) tiene las columnas `frame_index, target_id, bbox_left, bbox_top, bbox_width, bbox_height, out_of_view, occlusion, object_category`. **[V]** (TensorBay `loader.py`)
  - `object_category` va de 1 a 3: 1 = car, 2 = truck, 3 = bus.
  - `out_of_view` es un índice 1-based sobre `[no, medium, small]`.
  - `occlusion` es un índice 1-based sobre `[no, large, medium, small]`.

  Estos órdenes salen del `catalog.json` de TensorBay **[T]**. Ojo: el catálogo intercambia las descripciones de los dos campos, así que el orden de los niveles hay que validarlo con los datos. Niveles según el paper: occlusion no (0 %), small (1–30 %), medium (30–70 %) y large (70–100 %); out-of-view no (0 %), small (1–30 %) y medium (30–50 %). Los objetos con más del 50 % fuera de la imagen se descartan. **[V]**
- `*_gt.txt` (GT de MOT) tiene los mismos `frame, id, x, y, w, h` y después `score, in-view, occlusion`, que son constantes según TensorBay. **[V vía TensorBay]** Por tanto **no lleva clase**: para filtrar por clase hay que cruzarlo con `gt_whole`. Ejemplo de fila del conversor de forever208: `1089,20,461,207,21,31,1,1,…` **[T]**.
- `*_gt_ignore.txt` contiene las regiones ignoradas, que el paper describe como zonas con vehículos demasiado pequeños, a la manera de PASCAL VOC. En la Fig. 1 aparecen en rosa. **[V]** TensorBay lo llama "useless" y no lo carga **[T]**. Su formato exacto por columnas está **[NV]**. El script de UAVMOT trata como región ignorada las filas con categoría 0 de un txt con 9 columnas **[T]**.
- Evaluación MOT en el paper: IDF1, IDP, IDR, MOTA, MOTP, MT (al menos 80 %), ML (menos del 20 %), FP, FN, IDS y FM. **[V]** (ar5iv §3.2)

## 4. Detecciones públicas para MOT

- El paper evalúa 8 trackers: CMOT, MDP, SORT, DSORT, GOG, CEM, SMOT e IOUT. A cada uno le pasa como entrada las detecciones de Faster-RCNN, R-FCN, SSD y RON. El mejor resultado es MDP con Faster-RCNN, con 43.0 de MOTA y 61.5 de IDF1. La nota 2 dice que el dataset y "all experimental results" se publicarían. **[V]** (ar5iv §3.2)
- **No se ha podido verificar [NV]** si `UAV-benchmark-MOTD_v1.0.zip` trae esas detecciones, en qué carpeta (`RES_DET`?) o con qué nombres de archivo. Ninguna fuente pública que se haya podido leer muestra el contenido del toolkit más allá de `GT/`. Para comprobarlo hay que listar el zip del toolkit (234 MB) con autorización.

## 5. Descargas y licencia

Todo está en Google Drive y se enlaza desde https://sites.google.com/view/grli-uavdt/. **[V]** No hay enlaces a Baidu ni a OneDrive.

| Recurso | Archivo | Tamaño | ID de Drive |
|---|---|---|---|
| Imágenes UAVDT-Benchmark-M | `UAV-benchmark-M.zip` | 6,3 GB | `1m8KA6oPIRK_Iwt9TYFquC87vBc_8wRVc` |
| Toolkit DET/MOT + GT | `UAV-benchmark-MOTD_v1.0.zip` | 234 MB | `19498uJd7T9w4quwnQEy62nibt3uyT9pq` |
| Atributos | `M_attr.zip` | 9,5 KB | `1qjipvuk3XE3qU3udluQRRcYuiKzhMXB1` |
| UAVDT-S + toolkit SOT | (no aplica a MOT) | — | `1661_Z_zL1HxInbsA2Mll9al-Ax6Py1rG`, `1YMFTBatK6qUrtnIe4fZNMZ9FpCpD2cxm` |

Los nombres y tamaños salen del aviso de Drive ("too large to scan") y de las cabeceras HTTP. **[V]**

Hay una alternativa no oficial: el paquete de Dataset Ninja en formato Supervisely, de 13,03 GB, que incluye M y S. **[T]**

Licencia: la página oficial dice "for research purpose only" y pide citar el paper de ECCV 2018. **[V]** No hay una licencia formal como CC u otra. **[NV]**

## 6. Problemas conocidos

- **Resolución**: el paper dice 1080×540, pero los conversores y Dataset Ninja usan 1024×540 (ver §3). Hay que usar el tamaño real de la imagen y no el del paper. **[T]**
- **Cajas erróneas**: forever208 avisa de que hay "some wrongly annotated bbox, most of them are very big". Las filtra quitando las cajas con w > W/6 y h > H/6. **[T]**
- **GT de MOT sin clase**: `gt.txt` no trae categoría. Además los camiones y autobuses son menos del 10 % según el paper, así que en la práctica el benchmark es casi solo de "car". **[V]**
- **Objetos pequeños**: el 27,5 % de los objetos ocupa menos de 400 px², según el paper. Las regiones ignoradas tapan además vehículos diminutos que no se anotaron, así que hay que excluirlas al evaluar. Si no, cuentan como FP. **[V]**
- **Varias vistas dentro de una secuencia**: los atributos de vista no son excluyentes. **[V]**
