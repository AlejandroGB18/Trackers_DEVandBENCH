# Detector estándar YOLOv8 entrenado en VisDrone, sin reentrenar en UAVDT

En la v1, los 4 trackers reciben las detecciones de **un solo detector estándar: el YOLOv8 entrenado en VisDrone que el laboratorio ya usa**, sin reentrenarlo con UAVDT. Sus detecciones se generan una sola vez, para las 50 secuencias, en las computadoras del laboratorio, y el harness solo las lee. Como nunca vio UAVDT, el test queda sin fuga de datos y el train de UAVDT queda entero para elegir la cámara de UCMC (sin la limitación L15). Un detector fijo, y no elegido entre candidatos, ahorra ~medio día y un punto de coordinación, y es más fácil de defender como estándar. Su DetA en ajuste se mide igual, para la regla de exclusión y para calibrar `conf_high` y `conf_low`.

## Considered Options

- **Elegir entre 2–3 candidatos del laboratorio (YOLOv8, YOLO11, RT-DETR) por DetA en ajuste**: es posible que dé un detector mejor, pero suma un ciclo de detectar, decidir y volver a detectar. Queda para la v2.
- **Reentrenar o hacer fine-tuning en el train de UAVDT**: mejor DetA, pero cuesta ~1 día de GPU y obliga a partir el train entre el detector y el ajuste.
- **Detecciones públicas de UAVDT (Faster-RCNN)**: protocolo estándar de MOT, pero de calidad modesta (AP ≈ 34 %). Quedan como plan B.
- **YOLO preentrenado en COCO o DOTA**: detecta mal vehículos pequeños, y DetA taparía las diferencias de asociación.

## Consequences

- La decisión D3 de `benchmark/DECISIONS.md` (yolo11n de COCO/DOTA) queda reemplazada.
- El cambio de dominio de VisDrone a UAVDT se reporta como limitación.
- El harness debe aceptar detecciones externas por archivo.
- La v2 compara detectores (detector × tracker) reutilizando estas mismas piezas.
