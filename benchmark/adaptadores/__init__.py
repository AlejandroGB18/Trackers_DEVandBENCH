"""Adaptadores de dataset: convierten cada fuente de GT al formato del harness (D30).

Un adaptador lee el dataset tal como se descarga y produce:
- `gt.txt` por secuencia (frame, id, x, y, w, h, considerar, clase, visibilidad; clase 1 = vehicle, 0 = región
  ignorada), en una carpeta bajo `datos_raiz`;
- las entradas de `secuencias.yaml` (split, grupo de vuelo, atributos, cámara de UCMC).
Agregar un dataset = agregar un módulo aquí; el núcleo del harness no cambia.
"""
