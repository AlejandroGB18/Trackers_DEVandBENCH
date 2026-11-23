# UAVDT-MOT es la única fuente de GT de la v1

El benchmark compara los trackers contra una sola fuente de GT, **UAVDT-MOT**, para tener una base comparativa única y robusta aunque no sea exactamente el escenario real. Es la única fuente pública que coincide a la vez en vehículos, entorno urbano y dron DJI. Además, sus atributos de **altitud** y **vista** por secuencia acotan la búsqueda de cámara de UCMC (D17.2) y permiten estratificar los resultados en cenital y oblicuo.

## Considered Options

- **VisDrone2019-MOT**: más diversa y más citada, pero no anota altitud ni ángulo, así que la cámara de UCMC quedaría sin acotar. Mezcla, además, dominios y plataformas.
- **DynUAV**: tiene ego-movimiento más fuerte, pero el acceso no está garantizado y la licencia no es clara.
- **Varias fuentes combinadas**: dan más generalidad, pero multiplican conversores, particiones y fuentes de sesgo dentro del horizonte de la tesis.

## Consequences

- Las debilidades de UAVDT se reportan como limitación: resolución 1080×540 (píxel no cuadrado frente al video original), compresión, ruido de anotación y ego-movimiento mayormente suave.
- VisDrone y DynUAV quedan como trabajo futuro. Gracias al adaptador de dataset, agregarlos no cambia el núcleo del harness.
