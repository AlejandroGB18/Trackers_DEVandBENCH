# Investigación: GT para el caso real (dron multirrotor o de ala fija en movimiento continuo)

> **Fecha:** 2026-11-21 · **Pregunta:** ¿con qué ground truth (ideal o aproximado) comparamos los 4 trackers (propio = homografía + Kalman + IoU; UCMCTrack con calibración automática de pitch/altura; ByteTrack; BoT-SORT con GMC) cuando la cámara va en un dron **multirrotor o de ala fija que se mueve todo el tiempo**? Dos objetivos: **(1)** ID estable con ego-movimiento fuerte y continuo; **(2)** un decisor que separe lo que **se mueve de verdad** de lo que solo se desplaza en la imagen por el ego-movimiento (incluido el **paralaje**).
>
> **Cambio de premisa respecto a [`investigacion-gt-existente.md`](investigacion-gt-existente.md):** VIGIA ya **no** es el dominio objetivo; fueron solo videos de prueba. No se repiten aquí las fichas ya verificadas en ese informe (UAVDT, VisDrone, DynUAV, MMOT, MDMT, MOR-UAV, AU-AIR, pNEUMA Vision, highD, CitySim, DRIFT, etc.). Solo se citan para ubicarlas en el nuevo marco. Lo nuevo o corregido se marca **(nuevo)** o **(corrige)**.
>
> **Convención:** **[V]** = verificado en la fuente primaria citada (paper/arXiv, página oficial, repo, API pública o cabecera HTTP, consultados el 2026-11-21) · **NO VERIFICADO** = no se pudo comprobar en fuente primaria · **[Derivado]** = cálculo propio con cifras verificadas · **[Propuesta]** = recomendación propia · **[Supuesto]** = valor elegido para ilustrar, sin fuente. No se descargó ningún dataset. Solo se hicieron `HEAD`/GET de páginas, `README` y metadatos por API pública.

---

## 0. Respuesta corta

1. **No existe un GT público que cubra el caso real completo** (cámara de dron en movimiento continuo + IDs + verdad física de "se mueve / quieto" + pose de cámara). Lo más cercano por partes es:
   - **Ego-movimiento fuerte real con IDs (multirrotor):** **DynUAV** (órbitas, rotación, zoom, velocidad variable) [V] ([arXiv 2603.05970][dynuav]). UAVDT y VisDrone son, según los propios autores de DynUAV, "hovering or slow cruising" [V] ([arXiv 2603.05970][dynuav]): sirven como **control de ego bajo**, ya no como GT principal **(cambia respecto al informe anterior)**.
   - **IDs + telemetría por frame (altitud, pitch del gimbal, rumbo, velocidad, GPS):** **SeaDronesSee-MOT** (marítimo, nadadores y botes, 3840×2160 a 30 fps, dataset **CC0 1.0**) [V] ([README oficial][sds-repo], [arXiv 2105.01922][sds]). Es el **único** dataset real que encontré con IDs **y** metadatos de vuelo por frame. Los metadatos van a 10 Hz y los propios autores dicen que "no son tan fiables" [V] ([arXiv 2311.03561][sds-reid]). **(nuevo)**
   - **Ala fija real con IDs:** solo **BIRDSAI** (térmico nocturno, animales y personas, desde un UAV de ala fija, formato MOT, licencia CDLA-Permissive, descarga directa en LILA) [V] ([LILA][birdsai-lila], [página de la autora][birdsai-site], [WACV 2020][birdsai-mla]). Desde **avión o helicóptero** con vehículos: VETRA (baja tasa de frames) y WPAFB 2009 (1.25 Hz), ya en el informe anterior. **No encontré** ningún dataset público de vehículos en RGB, desde ala fija y a tasa de video, con IDs. **(nuevo)**
   - **Verdad física de movimiento + pose de cámara:** solo **sintético**. **SynDrone** sigue siendo el único publicado útil. Ahora se verificó en el código que usa **hfov = 90°**, 1920×1080, y guarda por frame cajas 3D de vehículos, peatones, **autos estacionados** y objetos estáticos con `actor.id` [V] ([CarlaClient.py][syndrone-code]) **(corrige "NO VERIFICADO")**. **FlyAwareV2 no sirve para tracking**: su página y su abstract solo declaran RGB, profundidad y segmentación semántica, sin cajas, IDs ni pose [V] ([página][flyaware], [arXiv 2510.13243][flyaware-arxiv]) **(nuevo)**.
2. **Para el objetivo (2) con paralaje real y ego controlado de ala fija, la pieza central tiene que ser un generador propio.** Recomiendo **CARLA**: acaba de salir la 1.0 sobre UE 5.8 el 2026-11-17 [V] ([release 1.0][carla-rel]). Tiene tráfico (Traffic Manager), API de velocidad por actor, proyección de cajas e IDs de instancia, y SynDrone ya demuestra cómo mover la cámara por una trayectoria arbitraria con `set_transform` [V] ([código SynDrone][syndrone-code]). Para dinámica de **ala fija físicamente realista** está **Project AirSim (IAMAI)**, que simula ala fija con JSBSim (Cessna 310, Skywalker X8) bajo licencia MIT [V] ([README][pas]). El AirSim original de Microsoft anunció su archivo y no publica release desde 1.8.1 (2022-07), y **Colosseum está archivado** [V] ([anuncio][airsim-ann], [API GitHub, §3.3]).
3. **Los warps sintéticos (homografía, zoom, rotación) aplicados a datasets de cámara quieta reproducen exactamente la rotación y el zoom de la cámara, pero no la traslación.** Por tanto **no generan paralaje**, que es justo el efecto dominante en ala fija a baja altura (§4.1). En una cuenta ilustrativa, un objeto de 10 m de alto visto desde 100 m por un ala fija a 20 m/s produce ≈ 30 px/s de paralaje, más que un auto real a 5 km/h (≈ 19 px/s) [Derivado, §4.1]. Sirven para el objetivo (1) y no para el (2).
4. **La validación final debe hacerse con vuelos propios** con telemetría registrada y **objetivos cooperativos con GPS** (vehículos o personas propios con un registrador GNSS). Es la única forma real de obtener verdad física de "se mueve" y de cubrir el paralaje real, el sensor real y la plataforma real [Propuesta]. El informe anterior proponía anotar 2–3 clips VIGIA. Eso se **reemplaza** por esto.
5. **La recomendación se ramifica** según clases, sensor, plataforma, telemetría y si podemos volar (árbol en §6). La columna vertebral común es: **DynUAV** (ego fuerte real) + **generador CARLA** (verdad física, estratos controlados, ala fija y multirrotor) + **vuelos propios con GPS** (validación). SeaDronesSee, BIRDSAI o los datasets de animales se agregan según el dominio.

---

## 1. Ala fija frente a multirrotor: qué hay y cómo se mueve la cámara

### 1.1 Por qué importa la plataforma [Derivado]
- Un **multirrotor** puede hacer hover, crucero lento, órbitas y giros sobre su eje. Mucho del movimiento aparente viene de **rotación** (yaw, gimbal) y **zoom**, que son transformaciones de imagen exactamente homográficas, sin paralaje (§4.1).
- Un **ala fija** no puede quedarse quieto: siempre **traslada** (crucero, pasadas rectas, loiter en círculo). La traslación produce **paralaje** proporcional a la altura del objeto sobre el suelo e inversamente proporcional a la altura de vuelo (§4.1). En loiter alrededor de un punto, la escena **rota** alrededor del centro y el fondo con relieve "se desliza" de forma diferente según su altura.
- Consecuencia: el decisor (objetivo 2) es más difícil en ala fija a baja altura, y la H de un solo plano (tracker propio, GMC de BoT-SORT) falla más ahí. UCMCTrack corre un Kalman "on the ground plane" a partir de proyecciones por homografía y usa **un solo juego de parámetros de compensación para todo el video** [V] ([arXiv 2312.08952][ucmc]). Eso lo hace dependiente de una escena aproximadamente plana y, en principio, más frágil cuando la actitud de la cámara cambia todo el tiempo. Cómo lo resuelve nuestra variante con calibración automática no se verificó contra el paper (NO VERIFICADO).

### 1.2 Datasets reales por plataforma

| Dataset | Plataforma | Ego-movimiento (con cita) | IDs | Telemetría / intrínsecos | Acceso y licencia hoy |
|---|---|---|---|---|---|
| **BIRDSAI** (nuevo) | **Ala fija** (Air Shepherd), África austral, nocturno | "large camera rotations, motion blur" [V] ([WACV 2020][birdsai-mla]); velocidad, altura y patrón de vuelo NO VERIFICADO (el PDF de CVF devolvió 403) | **Sí**, formato MOT: `frame, object_id, x, y, w, h, class, species, occlusion, noise` [V] ([página][birdsai-site]) | No declarada [V] ([LILA][birdsai-lila]) | LILA (GCS/S3/Azure) directo; real train 2.1 GB, test 1.6 GB, simulado 39.5 GB; **CDLA-Permissive 1.0** [V] ([LILA][birdsai-lila]); `HEAD` 200 |
| **SeaDronesSee-MOT** (nuevo) | Multirrotores DJI (Matrice 100/210, Mavic 2 Pro) + **Trinity F90+ (ala fija VTOL)** en la campaña [V] ([arXiv 2105.01922][sds-ar5iv]) | Vuelo por waypoints; el gimbal filtra el movimiento y el pitch es casi constante salvo cambios intencionales [V] ([arXiv 2105.01922][sds-ar5iv]); "moving, turning and gimbal-shifting cameras" [V] ([arXiv 2311.03561][sds-reid]). **Qué clips son del ala fija: NO VERIFICADO** (el JSON trae `source.drone`, p. ej. `'mavic'`, que permitiría filtrar [V] ([README][sds-repo])) | **Sí** (train/val; test oculto en servidor) [V] ([README][sds-repo]) | **Sí, por frame**: `gps_latitude/longitude`, `altitude`, `gimbal_pitch`, `compass_heading`, `gimbal_heading`, `speed`, `x/y/zspeed` [V] ([README][sds-repo]); registrado a 10 Hz y alineado por vecino más cercano a 30 fps [V] ([arXiv 2105.01922][sds-ar5iv]). Intrínsecos: no publicados (NO VERIFICADO) | **Dataset CC0 1.0**, código MIT [V] ([README][sds-repo]). El servidor de descarga `seadronessee.cs.uni-tuebingen.de` **no respondió (timeout)** el 2026-11-21; MaCVi muestra leaderboards pero no el enlace directo de MOT [V] ([macvi.org/dataset][macvi]) |
| **VETRA** | Avión y helicóptero (DLR, cámaras 3K/4K) | "low frame rates", movimiento de cámara alto (informe anterior); el histograma del paper va de ~2 a ~20 Hz según el buscador, **valor exacto NO VERIFICADO** | Sí (8 clases de vehículo; formato de ID NO VERIFICADO) | Imágenes georreferenciadas [V] ([DLR][vetra]) | 38.9 GB directo; CC BY-NC-ND 3.0 en las figuras de la página [V] ([DLR][vetra]) |
| **WPAFB 2009 (WAMI)** | Avión, 6 cámaras | 1 025 frames a **1.25 Hz** (informe anterior) | Sí (manual) | NO VERIFICADO | SDMS de AFRL responde 200; descarga concreta NO VERIFICADO ([SDMS][sdms]) |
| **DynUAV** | Multirrotor DJI Mini 4 Pro, 80–120 m | hover, crucero, velocidad variable, **rotación, zoom, órbitas, acercamiento/alejamiento**; el paper **no cuantifica** px/frame ni la proporción por tipo [V] ([arXiv 2603.05970][dynuav]) | Sí | No [V] | Baidu; sin licencia de datos (informe anterior) |
| **MMOT** | Multirrotor, 80–200 m | desplazamiento medio de plataforma ≈ 14.1 px/frame (informe anterior) | Sí (OBB) | No | HF 120 GB, CC BY-NC-ND 4.0 |
| **UAVDT / VisDrone-MOT** | Multirrotor | "hovering or slow cruising… relatively smooth camera trajectories" [V] ([arXiv 2603.05970][dynuav]) | Sí | No (solo bandas de altitud en UAVDT) | Directo (informe anterior) |
| **M3OT** (nuevo) | Dos DJI Mavic 3T, 100–120 m | **NO VERIFICADO** (el artículo no lo describe) | Sí, `gt.txt` estilo MOT, solo `vehicle` [V] ([Sci Data][m3ot]) | No reportada [V] | figshare (enlace privado, devolvió 202); artículo CC BY 4.0; licencia de datos NO VERIFICADO [V] ([Sci Data][m3ot]) |
| **VT-MOT, subconjunto dron** (nuevo) | DJI M300 RTK + Zenmuse H20T | NO VERIFICADO | Sí: 111 pares de secuencias, 3 314 tracks, 25 fps, 640×512 RGB y térmico [V] ([arXiv 2408.00969][vtmot]) | No | Repo PFTrack (código MIT); licencia de datos NO VERIFICADO [V] ([arXiv][vtmot], API GitHub) |

**Conclusión de §1 [Derivado]:** para **ala fija** no hay nada en RGB con vehículos a tasa de video. BIRDSAI cubre ala fija + térmico + animales/personas. VETRA y WPAFB cubren aeronave tripulada + vehículos, pero con tasa de frames baja. Para **multirrotor con ego fuerte**, DynUAV es la única opción con GT humano. El resto tiene ego bajo o no lo documenta.

---

## 2. Por dominio y sensor

Columnas: IDs · ego-movimiento · telemetría/intrínsecos · acceso hoy · licencia · tamaño · resolución/fps.

### 2.1 RGB urbano / carretera (vehículos y peatones)
| Dataset | IDs | Ego | Telemetría | Acceso | Licencia | Tamaño | Res./fps |
|---|---|---|---|---|---|---|---|
| **DynUAV** | Sí | **Fuerte** | No | Baidu | Sin licencia de datos | NO VERIFICADO | 1080p; fps NO VERIFICADO [V] ([arXiv][dynuav]) |
| **UAVDT** | Sí | Bajo | Bandas de altitud | Google Drive | "research only" | NO VERIFICADO | 1080×540, 30 fps |
| **VisDrone2019-MOT** | Sí | Bajo | No | Directo | No declarada | ~14 GB | mixta |
| **MMOT** | Sí (OBB) | Medio (jitter + rotación) | No | HF | CC BY-NC-ND 4.0 | 120 GB | 1200×900 multiespectral, ≈ 5 fps |
| **MATRIX** (nuevo, sintético UE5 + AirSim) | Sí (detección y tracking de 40 peatones, 8 drones con posición cambiante) [V según el abstract] ([arXiv 2511.08615][matrix]) | Multi-vista; detalle NO VERIFICADO | NO VERIFICADO | NO VERIFICADO | NO VERIFICADO | — | — |
| **P-DESTRE** (nuevo, personas) | IDs consistentes incluso entre días (búsqueda de personas) [V según el abstract] ([arXiv 2004.02782][pdestre]) | NO VERIFICADO | NO VERIFICADO | NO VERIFICADO | NO VERIFICADO | — | — |

### 2.2 Marítimo
- **SeaDronesSee-MOT** [V] ([README][sds-repo], [arXiv 2105.01922][sds-ar5iv], [arXiv 2311.03561][sds-reid]):
  - 22 clips, 54 105 frames, 403 192 instancias, media de 2 460 frames por clip. Dos tareas: *Swimmer* (nadadores y flotantes) y *All-Objects-In-Water* (incluye botes).
  - 3840×2160 a 30 fps (Hasselblad L1D-20c, Zenmuse X5/XT2).
  - Altitud de 5 a 260 m; ángulo de vista de 0 a 90° [V] ([arXiv abs][sds]). En el split MOT, la altitud media es 34 m en train+val y 43 m en test, y el pitch del gimbal va de −2.5 a 90° [V] ([arXiv 2311.03561][sds-reid]).
  - **Metadatos por frame confirmados en el README** (ver §1.2). Problemas reportados: metadatos no sincronizados con el gimbal real en algunos frames, y 2 830 imágenes sin metadatos en otro subconjunto [V según búsqueda; la cifra de 2 830 es de otro paper y no se verificó en su fuente].
  - Los objetos que salen y vuelven reciben un ID nuevo en train/val (no hay IDs de largo plazo); la versión ReID de 2024 sí agrega etiquetas de largo plazo en test [V] ([arXiv 2311.03561][sds-reid]).
  - **Valor para nosotros:** es el único caso real donde se puede **probar la calibración de UCMC contra telemetría** (pitch y altura) con IDs. El mar es un plano casi perfecto (z = 0), que es justo lo que asume UCMC [V el supuesto, en [arXiv 2311.03561][sds-reid]]. Casi no hay paralaje, salvo por los mástiles de los botes. Licencia **CC0**, la más libre de todas.
  - **Riesgo de acceso:** el servidor de descarga no respondió hoy. Hay que reintentarlo o escribir a los organizadores de MaCVi. Los mirrors de terceros no son fuente oficial.
- **BoaTrack** (MaCVi): figura como pista de MOT de botes en la superficie (cámara en el barco, no dron) [V] ([macvi.org/dataset][macvi]). Fuera de alcance.

### 2.3 Térmico
| Dataset | IDs | Plataforma / ego | Telemetría | Acceso / licencia | Notas |
|---|---|---|---|---|---|
| **BIRDSAI** | **Sí** (MOT) | **Ala fija**; rotaciones grandes, desenfoque | No | LILA directo; CDLA-Permissive | 48 videos reales (~62 k imágenes) + 124 sintéticos de AirSim-W (~100 k) [V] ([LILA][birdsai-lila]). Resolución, fps y altura NO VERIFICADO |
| **VT-MOT (dron)** | Sí | M300 RTK; ego NO VERIFICADO | No | Repo PFTrack; licencia de datos NO VERIFICADO | 640×512, 25 fps, RGB+T alineados [V] ([arXiv][vtmot]) |
| **M3OT** | Sí (vehículos) | Mavic 3T, 100–120 m; ego NO VERIFICADO | No | figshare; licencia NO VERIFICADO | 640×512 [V] ([Sci Data][m3ot]) |
| **HIT-UAV** | **No** (solo detección) | 60–130 m, 30–90° | No | GitHub; repo CC-BY-4.0 (API GitHub) | 2 898 imágenes sacadas de 43 470 frames de video; cajas normales y orientadas; personas y vehículos [V] ([arXiv 2204.03245][hituav]). Útil solo para **ajustar el detector térmico** |
| **MONET** | **No declarados** (cajas; IDs NO VERIFICADO) | Dron en zona rural | **Sí**: actitud, velocidad, altitud y GPS alineados por timestamp [V] ([arXiv 2304.05417][monet]) | GitHub del proyecto (200); licencia de datos NO VERIFICADO | ~53 k imágenes, ~162 k cajas. Útil para probar la calibración de UCMC en térmico si se le agregan IDs |

### 2.4 Animales
| Dataset | IDs | Ego | Acceso / licencia | Res./fps |
|---|---|---|---|---|
| **BIRDSAI** | Sí | Ala fija | ver arriba | NO VERIFICADO |
| **BuckTales** (nuevo) | Sí, formato MOTChallenge (DarkLabel); 12 videos, ~22.5 k frames, >1.2 M anotaciones [V] ([arXiv 2411.06896][bucktales]) | DJI Air 2S a 80 m, **cenital (−90°)**; si el dron hace hover o se mueve: **NO VERIFICADO** (solo se menciona una técnica de "relevo" en el material suplementario) [V] | Edmond (MPG): **CC BY-SA 4.0**, `MOT_Dataset.zip` 17.0 GB, sin restricción de acceso por archivo [V] ([API Edmond][bucktales-api]). La página web tiene protección anti-bot (Anubis), pero la API pública de Dataverse responde | 5.4K, 30 fps [V] |
| **BaboonLand** (nuevo) | Sí: tracks con ID persistente en "CVAT for video 1.1"; ~media hora de tracking denso (hasta 70 individuos) [V] ([arXiv 2405.17698][baboon]) | DJI Air 2S, > 20 m; el dron seguía a las tropas, pero si se movía durante la grabación es **NO VERIFICADO** | baboonland.xyz (200); licencia de datos NO VERIFICADO (CC BY 4.0 es la del paper) | 5.3K; fps NO VERIFICADO |
| **WildLive** (nuevo) | 291 tracklets (cebras, jirafas, elefantes), ~215.8 k cajas, 22 secuencias, 19 139 frames [V] ([arXiv 2504.10165][wildlive]) | Mavic 3 Enterprise/Pro y un cuadricóptero propio; "platform motion" como desafío, detalle NO VERIFICADO | Página del proyecto (200); descarga y licencia NO VERIFICADO | 4K; fps NO VERIFICADO |

### 2.5 Personas
- **SeaDronesSee** (nadadores), **BIRDSAI** (personas en térmico nocturno), **VisDrone** (peatones, ego bajo), **DynUAV** (person, cycler; ego fuerte), **P-DESTRE** y **MATRIX** (§2.1), y **Okutama-Action** (informe anterior).
- No encontré un dataset real de **personas** con ego fuerte **y** telemetría a la vez.

---

## 3. GT con verdad física de movimiento y pose de cámara (sintético)

### 3.1 Sintéticos ya publicados
| Dataset | Cajas | IDs | Pose / intrínsecos | Video | Licencia | Veredicto |
|---|---|---|---|---|---|---|
| **SynDrone** | **3D** por frame (8 esquinas en el mundo) de `vehicles + pedestrians + parked + static`, más cajas estáticas del nivel [V] ([código][syndrone-code]) | `actor.id` para los actores; las cajas estáticas del nivel usan un contador propio (`len(sbboxes)`), así que **los IDs pueden chocar entre los dos espacios** [V] ([código][syndrone-code]) | Extrínsecos por frame (README); **hfov = 90°, 1920×1080** fijados en el código [V] ([código][syndrone-code]) | 25 fps; trayectorias del espectador grabadas a mano y validadas [V] ([README][syndrone-repo]) | Código Apache-2.0; datos NO VERIFICADO | **Usable ya** para el objetivo (2) en multirrotor: `moving` exacto, autos estacionados con paralaje y pose para validar UCMC. Las cajas 2D hay que **proyectarlas**, y la **oclusión** hay que resolverla con la segmentación o la profundidad incluidas |
| **FlyAwareV2** (nuevo) | **No declaradas** | No | No declarada | No consta que sea video | Página CC BY-SA 4.0; datos NO VERIFICADO; ~290 GB sintético + ~6 GB real [V] ([descargas][flyaware-dl]) | ✗ para tracking. Solo RGB, profundidad y semántica [V] ([arXiv 2510.13243][flyaware-arxiv]) |
| **BIRDSAI sintético** | Sí (formato MOT) | Sí | NO VERIFICADO | Sí (124 videos de AirSim-W) | CDLA-Permissive | Térmico de sabana. Útil si el dominio es animales en térmico |
| **UAV3D**, **TartanAir** | — | — | — | — | — | ✗ (informe anterior: 0.5 Hz / sin objetos) |
| **UAV-MM3D**, **AirMOT**, **AirTrackSynth** | Anotan **UAVs** u objetos individuales | — | — | — | — | ✗ (otro problema: anti-UAV o SOT) [V abstract] ([arXiv 2511.22404][uavmm3d]) |

### 3.2 Generadores para un dataset a medida

| Herramienta | Estado (2026-11) | Ala fija | Multirrotor | Tráfico / actores | Exportar MOT + velocidad + pose | Esfuerzo [Propuesta] |
|---|---|---|---|---|---|---|
| **CARLA** | **1.0 publicada el 2026-11-17 sobre UE 5.8**; la línea UE4 (0.9.16 y anteriores) se declara obsoleta [V] ([release][carla-rel]); repo MIT, push diario (API GitHub) | **Cinemática** (sin dinámica de vuelo): la cámara se mueve con `set_transform` por tick, igual que SynDrone [V] ([código SynDrone][syndrone-code]). Loiter, pasadas rectas y gimbal = trayectorias escritas a mano | Igual (cinemática) | **Sí**: Traffic Manager con autopilot de vehículos, más peatones [V] ([docs TM][carla-tm]) | `actor.get_velocity()`, `get_angular_velocity()`, `get_transform()` [V] ([API Python][carla-api]); tutorial de proyección de cajas 3D a 2D con matriz de proyección y FOV [V] ([tutorial][carla-bb]); cámara de **segmentación de instancias** con el ID en los canales G/B [V] ([docs][carla-inst]). La correspondencia exacta entre ID de instancia y `actor.id`: NO VERIFICADO | **1–2 semanas-persona** para el pipeline (trayectorias de ambas plataformas, gimbal, export `gt.txt` + `moving.csv` + `pose.csv` + intrínsecos, visibilidad por segmentación). Más el tiempo de render en GPU |
| **Project AirSim (IAMAI)** | Activo; MIT; UE 5.2/5.7/5.8; Microsoft discontinuó la iniciativa e IAMAI la mantiene [V] ([README][pas]) | **Sí, con dinámica JSBSim** (Cessna 310, Skywalker X8) y PX4/ArduPilot SITL [V] ([README][pas]) | Sí | UGV por Blueprint; **tráfico denso no documentado** (NO VERIFICADO) | Sensores de cámara, GPS, IMU, airspeed [V]; anotación de cajas con ID: NO VERIFICADO | 2–4 semanas: hay que construir la escena y el tráfico. Se justifica solo si se necesita la **dinámica real** de ala fija (alabeo en virajes, turbulencia) |
| **Microsoft AirSim** | Anunció su archivo ("no further updates"); último release v1.8.1 del 2022-07-18 [V] ([anuncio][airsim-ann], API GitHub) | Solo multirrotor y auto (NO VERIFICADO ala fija) | Sí | — | — | ✗ para trabajo nuevo |
| **Colosseum** (fork de AirSim) | **Archivado** (`archived: true` en la API de GitHub, 2026-11-21) [V] | — | Sí | — | — | ✗ |
| **Cosys-AirSim** | Activo (push 2026-11-19); anotación multicapa y segmentación de instancias [V] ([README][cosys]) | NO VERIFICADO | Sí | NO VERIFICADO | Segmentación de instancias + anotación | Alternativa a CARLA si se prefiere el ecosistema AirSim |
| **Isaac Sim + Pegasus** | Pegasus v5.1.0 para Isaac 5.1 (2025-10); **"only multirotor vehicles are supported"** [V] ([README Pegasus][pegasus]) | **No** (Pegasus) | Sí, con PX4/ArduPilot | Sin tráfico nativo (NO VERIFICADO); hay que guionizarlo | Replicator: `bounding_box_2d_tight` con IDs y rutas de prim, y `camera_params` [V] ([docs Replicator][replicator], [Writer Control][isaac-writer]) | 2–4 semanas; buen render y exportación, pero sin tráfico ni ala fija |
| **UnrealCV / UnrealZoo** | UnrealCV MIT (push 2026-09); UnrealZoo-gym Apache-2.0 (push 2026-10) (API GitHub) | Cámara libre | Cámara libre | Depende de la escena | IDs y máscaras por objeto (UnrealCV); velocidad y tráfico a cargo nuestro | 3+ semanas; útil para dominios no urbanos (costa, selva, sabana) |
| **Flightmare** | Último push 2024-06 (API GitHub) | — | Sí | — | — | ✗ (poco mantenido) |

**Recomendación de generador [Propuesta]:**
- Usar **CARLA 1.0 con cámara cinemática**. Las trayectorias de ala fija se parametrizan como (a) **pasada recta** a velocidad v y altura H; (b) **loiter**, es decir un círculo de radio R alrededor de un punto con el gimbal apuntando al centro (la cámara rota a ω = v/R); (c) **lazo de búsqueda** ("lawnmower"). Las de multirrotor: hover con viento (jitter), crucero, órbita, giro de yaw y zoom.
- Agregar **ruido de actitud** (alabeo en virajes, turbulencia como ruido de baja frecuencia) y **jitter del gimbal**. Opcionalmente, obtener las trayectorias de **JSBSim** (LGPL-2.1, activo [V] API GitHub) sin render y reproducirlas en CARLA. Eso da dinámica realista sin depender de Project AirSim.
- **Brecha sim→real:** texturas, iluminación, densidad y comportamiento del tráfico, falta de rolling shutter, desenfoque de movimiento y compresión. Se mitiga validando el ranking en DynUAV y en vuelos propios (§4.3). Los mapas de CARLA son urbanos o suburbanos. Para mar, selva o sabana hacen falta escenas Unreal propias o de UnrealZoo.

---

## 4. GT aproximado

### 4.1 Ego-movimiento sintético (warps) sobre datasets de cámara fija o en hover
**Qué cubre y qué no (geometría de proyección):**
- Una **rotación pura** de la cámara alrededor de su centro óptico y un **cambio de zoom** (focal) inducen una **homografía exacta** entre imágenes para *cualquier* escena, haya o no relieve. Es la base de la descomposición "plano + paralaje": después de compensar un plano, lo que queda es el paralaje debido a la **traslación** y a la profundidad relativa al plano [V] ([Irani & Anandan, PAMI 1998, doi:10.1109/34.683770][irani]; revisión en [arXiv 2001.05238][mod-review]).
- Por lo tanto, un warp de homografía sobre pNEUMA Vision, UAVDT o VisDrone en tramos quietos, o highD si hubiera video, **simula bien**: yaw, pitch del gimbal, roll, zoom y jitter. Eso es el objetivo (1) en su parte rotacional.
- **No simula**:
  - (a) **Paralaje** de objetos elevados (postes, árboles, edificios, mástiles) frente al suelo. Es la principal fuente de falsas alarmas del decisor en ala fija.
  - (b) La **oclusión variable** (un objeto que entra o sale por detrás de un edificio cuando el dron se traslada).
  - (c) El cambio de perspectiva del propio objeto (se ve su lateral, luego su techo).
  - (d) El desenfoque de movimiento y el rolling shutter reales.
  - (e) Los bordes: al rotar o hacer zoom aparecen zonas sin imagen. Hay que recortar o trabajar con un recorte móvil (una "cámara virtual" dentro de un frame 4K), lo que también reduce la resolución efectiva.

**Orden de magnitud del paralaje [Derivado; supuestos marcados]:**
- Fórmula para cámara cenital a altura H que se traslada t por frame: un punto a altura h sobre el suelo tiene, después de compensar el plano del suelo, un residuo de ≈ f·t·h / (H·(H−h)) píxeles.
- Supuestos [Supuesto]: hfov 70° y ancho 1920 px, de donde f ≈ 960 / tan 35° ≈ 1 371 px; H = 100 m; 30 fps.
  - **Ala fija** a 20 m/s (t ≈ 0.67 m/frame) [Supuesto de velocidad típica]: un objeto de **10 m** de alto deja un residuo de ≈ 1.0 px/frame ≈ **30 px/s**. El techo de un auto estacionado (1.5 m) deja ≈ 4 px/s.
  - Un auto que se mueve **de verdad a 5 km/h** se desplaza f·v/H ≈ 1 371 · 1.39 / 100 ≈ **19 px/s**.
  - **Multirrotor** a 5 m/s: el objeto de 10 m deja ≈ 7.6 px/s.
- **Lectura:** en ala fija, el paralaje de estructuras altas supera el movimiento de objetos lentos. El decisor no puede probarse solo con warps planos.

**Veredicto [Propuesta]:** usar warps para el **estrato rotacional y de zoom** del objetivo (1) y para el **control** del decisor (sin paralaje, los 4 deberían acertar). Fuentes: **pNEUMA Vision** (CC BY 4.0, velocidad real por vehículo, frames ya estabilizados; informe anterior) y tramos quietos de **UAVDT/VisDrone**. Son **1–2 días** de trabajo: un generador de trayectorias de H suaves, de amplitud conocida, con el GT transformado por la misma H.

### 4.2 Pseudo-GT con detector fuerte + revisión
- Sigue valiendo el protocolo del informe anterior (§5): pre-anotar con un detector y un enlazador **ajenos a los 4 trackers**, revisar todo a mano y medir el sesgo anotando un clip desde cero.
- **Matiz nuevo:** con ego fuerte, los enlazadores IoU fallan justo donde se quiere medir. Conviene pre-enlazar en coordenadas **estabilizadas** con una H independiente (SIFT+MAGSAC, D10) o usar el tracker de CVAT y **revisar con prioridad los frames de ego alto** (ordenar por magnitud de la H) [Propuesta].
- Esto **no** da verdad de "moving" con paralaje. El `moving` derivado hereda el error de la H (informe anterior, §3).

### 4.3 Vuelos propios con telemetría (validación final)
**Qué registrar:**
- **PX4/ArduPilot:** el log ULog guarda la actitud en cuaterniones y los eventos `camera_capture`. Con captura por hardware (`CAM_CAP_FBACK`) se obtiene el instante exacto de exposición [V] ([docs PX4 ULog][px4-ulog], [docs cámara PX4][px4-cam]).
- **DJI:** la telemetría va en subtítulos `.SRT` o en una pista de metadatos dentro del MP4 según el modelo. **No encontré documentación oficial de DJI** sobre los campos; las fuentes comunitarias indican GPS, altitud, focal y, en algunos modelos, solo GPS + altitud → **NO VERIFICADO**. Antes de comprar o elegir dron, hay que comprobar qué registra el modelo concreto, sobre todo el **pitch del gimbal** y el **zoom**.
- **Intrínsecos:** calibrar la cámara con un patrón (por modo de zoom).

**Verdad física de "moving" [Propuesta]:**
- Poner **registradores GNSS** (idealmente RTK) en **objetivos cooperativos**: 2–4 autos o personas propios que alternan quieto, lento y rápido según un guion, más autos **estacionados** conocidos como negativos.
- Volar cerca de estructuras altas para provocar paralaje. Hacer pasadas rectas, loiter y (con multirrotor) órbitas y zoom.
- Así el decisor se evalúa con verdad física en los objetivos cooperativos. El resto del tráfico se etiqueta con el criterio D12 y revisión manual.

**Anotación:** CVAT (informe anterior). Solo los IDs; `moving` sale de GNSS en los cooperativos y de D12 en el resto.

**Costo [Propuesta]:**
- Preparación (guion, loggers, sincronización por reloj GPS o un evento visual) ≈ 2–3 días.
- Vuelo ≈ 1 día por plataforma y entorno.
- Anotación ≈ 2 h por clip de 30–60 s de densidad media (supuesto del informe anterior); con 8–12 clips, ≈ 16–24 h-persona.
- Sincronización y conversores ≈ 2 días.

**Riesgo:** permisos de vuelo y privacidad (personas y matrículas). La anotación se queda interna y no se publica.

---

## 5. Protocolo del benchmark para ego-movimiento constante

**Variables por frame que hay que medir** (desde la telemetría o la pose sintética; si no hay, desde una H independiente) [Propuesta]:
1. **Velocidad angular de la cámara** ω (°/s): yaw + pitch del gimbal + roll, o la rotación estimada de la H.
2. **Flujo de traslación** v/H (1/s): velocidad horizontal dividida por la altura. Mide cuánto "corre" el suelo en la imagen; px/s ≈ f·v/H.
3. **Índice de paralaje** ≈ (v/H)·(h_max/H), donde h_max es la altura de las estructuras en la escena. Se puede aproximar con la fracción de outliers de la H en el fondo.
4. **Tasa de zoom** (Δf/f por segundo).
5. **Oblicuidad**: pitch del gimbal (90° = cenital).
6. **Escala**: GSD o altura del objeto en px (< 16, 16–32, > 32 px).
7. **fps efectivo**, es decir el desplazamiento por frame (ya fijado en el informe anterior).

**Estratos recomendados [Propuesta]:** terciles o umbrales fijos de ω, v/H y paralaje. Además, regímenes de plataforma: *hover*, *crucero multirrotor*, *órbita/loiter*, *pasada recta de ala fija*, *zoom* y *giro brusco de gimbal*.

| Estrato | Fuente que lo cubre (mejor → peor) |
|---|---|
| Hover / ego bajo (control) | pNEUMA Vision, UAVDT, VisDrone |
| Rotación / gimbal / zoom (sin paralaje) | Warps sobre pNEUMA/UAVDT (§4.1); DynUAV (rotación, zoom); CARLA |
| Traslación rápida multirrotor | DynUAV (crucero, velocidad variable); SynDrone (~20 m/s); CARLA |
| **Órbita / loiter** | DynUAV (órbitas multirrotor); **CARLA** (loiter de ala fija); vuelos propios |
| **Pasada recta de ala fija + paralaje** | **CARLA**; vuelos propios; BIRDSAI (sin verdad de movimiento) |
| Oblicuo (pitch < 45°) | SynDrone (30°), SeaDronesSee (pitch por frame), CARLA, vuelos propios |
| Alta altura / objetos diminutos | MMOT, DynUAV (80–120 m), VETRA, M3OT |
| Validar la calibración de UCMC (pitch, altura, hfov) | **SynDrone y CARLA** (exacto); **SeaDronesSee** (telemetría real); MONET (telemetría, sin IDs); vuelos propios |
| Verdad física de `moving` | **CARLA / SynDrone** (exacta); vuelos propios con GNSS (cooperativos); pNEUMA (velocidad real, solo en hover) |

**Reporte [Propuesta]:**
- HOTA/IDF1/IDSW **por estrato** y **por fuente**, nunca promediados entre fuentes.
- Para el decisor: precisión y recall de `moving` por estrato de **paralaje**, y tasa de falsas alarmas sobre los negativos con paralaje (autos estacionados, estructuras).
- Para UCMC: el error de pitch, altura y hfov estimados contra la verdad, y la sensibilidad de su HOTA a ese error.

---

## 6. Recomendación en forma de árbol

**Columna vertebral común (cualquiera sea la respuesta)** [Propuesta]:
1. **Generador CARLA 1.0** (1–2 semanas). Cubre las dos plataformas, `moving` exacto, paralaje y pose para UCMC.
2. **DynUAV**: el único real con ego fuerte. Si Baidu no funciona o no hay permiso, se reemplaza por **MMOT** (jitter + rotación), con la desventaja de que es multiespectral.
3. **Control de ego bajo** con pNEUMA Vision + warps (1–2 días).
4. **Vuelos propios** si es posible (§4.3).

Luego se ramifica:

```
¿Clases objetivo?
├─ Vehículos (urbano/carretera)
│   ├─ Sensor RGB
│   │   ├─ Plataforma multirrotor → DynUAV + UAVDT/VisDrone (control) + SynDrone/CARLA (moving, UCMC)
│   │   └─ Plataforma ala fija   → CARLA (pasadas, loiter; dinámica de JSBSim si hace falta)
│   │                              + VETRA (aeronave real, tasa baja, solo estrés de IDs)
│   │                              + vuelos propios (no hay público RGB de ala fija a tasa de video)
│   └─ Sensor térmico → VT-MOT (dron) y M3OT para IDs; HIT-UAV para el detector;
│                       CARLA no tiene cámara térmica nativa (NO VERIFICADO) → vuelos propios térmicos
├─ Personas
│   ├─ En tierra, RGB → VisDrone (peatones), DynUAV (person/cycler), MATRIX (sintético), P-DESTRE
│   ├─ En agua → SeaDronesSee-MOT (CC0, telemetría por frame) ← prioridad 1 en este dominio
│   └─ Térmico / nocturno → BIRDSAI (ala fija) + VT-MOT
├─ Embarcaciones → SeaDronesSee-MOT (All-Objects-In-Water); paralaje despreciable salvo mástiles
│                  → el decisor se evalúa sobre todo con la estela y la deriva; CARLA no aplica (sin mar)
└─ Animales
    ├─ Térmico / ala fija → BIRDSAI (real + sintético AirSim-W)
    └─ RGB multirrotor   → BuckTales (CC BY-SA, 5.4K), BaboonLand, WildLive (ego NO VERIFICADO en los tres)

¿Hay telemetría en nuestro dron?
├─ Sí → la calibración de UCMC se valida contra telemetría propia; SeaDronesSee como referencia pública
│       además, los estratos (ω, v/H) se calculan directamente de la telemetría
└─ No → UCMC solo se valida en SynDrone/CARLA; en reales, reportar sensibilidad a hfov/pitch;
        estratos estimados desde la H (independiente de los trackers)

¿Podemos grabar vuelos propios?
├─ Sí → §4.3 con objetivos cooperativos con GNSS: es la VALIDACIÓN FINAL (prioridad alta)
└─ No → el ranking final se decide con CARLA (moving + paralaje) + DynUAV (IDs con ego fuerte),
        declarando explícitamente la brecha sim→real y el sesgo de dominio
```

**Orden y costo si aún no sabemos nada** [Propuesta]:

| # | Paso | Para qué | Costo |
|---|---|---|---|
| 1 | Generador **CARLA** (trayectorias de multirrotor y ala fija, export MOT + `moving` + pose + hfov) | Objetivos (1) y (2) con verdad física; estratos controlados; UCMC | 1–2 semanas-persona + GPU |
| 2 | **SynDrone** (1–2 ciudades, ~5 GB c/u) | Prueba rápida mientras se arma el paso 1; mismo formato de cajas 3D | 2–3 días de conversor (informe anterior) |
| 3 | **DynUAV** | IDs con ego fuerte real | 0.5 día de conversor + gestionar Baidu y permiso |
| 4 | **pNEUMA Vision + warps** y **UAVDT** | Control de ego bajo y estrato rotacional | 1–2 días |
| 5 | **Vuelos propios** con telemetría + GNSS cooperativo | Validación en el dominio real (sensor, plataforma, paralaje) | ~1.5–2 semanas en total (§4.3) |
| 6 | Según el dominio: SeaDronesSee-MOT / BIRDSAI / BuckTales | Dominio específico | 0.5–1 día de conversor cada uno |
| — | Ala fija con **dinámica real** (Project AirSim + JSBSim) | Solo si los resultados de CARLA dependen de la actitud en los virajes | 2–4 semanas |

---

## 7. Tabla final: fuente × pregunta del benchmark

Leyenda: **●** responde bien · **◐** parcial o aproximado · **○** no responde · **?** NO VERIFICADO.

| Fuente | IDs con ego fuerte | IDs con ego bajo (control) | `moving` con verdad física | Paralaje real | Ala fija | Calibración UCMC (pose/telemetría) | Dominio real | Licencia apta para uso interno |
|---|---|---|---|---|---|---|---|---|
| **CARLA (generador)** | ● | ● | ● | ● | ◐ (cinemática) | ● | ○ | ● (MIT) |
| **SynDrone** | ◐ (~20 m/s, trayectorias fijas) | ○ | ● | ● | ○ | ● (hfov 90°, extrínsecos) | ○ | ? (datos) |
| **Project AirSim + JSBSim** | ● | ● | ● (si se exporta) | ● | ● (dinámica) | ● | ○ | ● (MIT) |
| **DynUAV** | ● | ◐ | ◐ (derivado con H) | ◐ (en la imagen, sin verdad) | ○ | ○ | ● | ? (sin licencia) |
| **UAVDT / VisDrone** | ○ | ● | ◐ | ◐ | ○ | ○ | ● | ◐ |
| **MMOT** | ◐ | ◐ | ◐ | ◐ | ○ | ○ | ◐ (multiespectral) | ◐ (NC-ND) |
| **pNEUMA Vision + warps** | ◐ (solo rotación/zoom) | ● | ● (velocidad real) | ○ | ○ | ○ | ◐ | ● (CC BY) |
| **SeaDronesSee-MOT** | ◐ (por waypoints, gimbal estabilizado) | ● | ◐ | ○ (mar plano) | ? (F90+ en la campaña) | ● (telemetría por frame, poco fiable) | ● marítimo | ● (CC0) |
| **BIRDSAI** | ◐ (rotaciones grandes) | ○ | ◐ | ◐ | ● | ○ | ● térmico/animales | ● (CDLA-P) |
| **VETRA** | ◐ (tasa baja) | ○ | ◐ | ◐ | ● (aeronave tripulada) | ◐ (georreferencia) | ◐ | ◐ (NC-ND) |
| **WPAFB 2009** | ○ (1.25 Hz) | ○ | ◐ | ◐ | ● (avión) | ? | ◐ | ? |
| **VT-MOT (dron) / M3OT** | ? | ● | ◐ | ◐ | ○ | ○ | ● térmico | ? |
| **BuckTales / BaboonLand / WildLive** | ? | ● | ◐ | ○ (sabana plana) | ○ | ○ | ● animales | BuckTales ● (CC BY-SA); resto ? |
| **MONET / HIT-UAV** | ○ (sin IDs) | ○ | ○ | ○ | ○ | MONET ◐ | ● térmico | ? / ● |
| **Vuelos propios + GNSS** | ● | ● | ● (cooperativos) | ● | ● (si hay plataforma) | ● (si hay telemetría) | **●** | ● |

---

## 8. Qué cambió respecto al informe anterior

| Tema | Antes | Ahora |
|---|---|---|
| Dominio objetivo | VIGIA (4K oblicuo urbano) | Dron multirrotor o ala fija en **movimiento continuo** |
| GT principal de tracking | UAVDT | **DynUAV** (ego fuerte) + **CARLA**; UAVDT/VisDrone pasan a **control de ego bajo** |
| Validación de dominio | 2–3 clips VIGIA anotados | **Vuelos propios** con telemetría y **objetivos GNSS** |
| Ala fija | No considerada | BIRDSAI (único real con IDs), VETRA/WPAFB (aeronave, tasa baja), **CARLA cinemático / Project AirSim + JSBSim** |
| Telemetría real con IDs | "Ninguno accesible" (AU-AIR caído) | **SeaDronesSee-MOT** tiene metadatos por frame y licencia CC0 (servidor caído hoy) |
| SynDrone | hfov NO VERIFICADO | **hfov 90°, 1920×1080**; incluye autos estacionados y objetos estáticos con ID; posible choque de IDs entre actores y cajas del nivel |
| FlyAwareV2 | "Sucesor recomendado" | **No trae cajas, IDs ni pose declarados** → ✗ para tracking |
| Simuladores | No evaluados | CARLA 1.0 (UE 5.8, 2026-11-17), Project AirSim activo con ala fija, AirSim en archivo, Colosseum archivado, Pegasus solo multirrotor |
| Warps sintéticos | Propuesta sin acotar | Acotados: **exactos para rotación y zoom, ciegos al paralaje**; cuenta de orden de magnitud para ala fija |
| Nuevos por dominio | — | Térmico (VT-MOT, M3OT, HIT-UAV, MONET), animales (BuckTales, BaboonLand, WildLive), personas (P-DESTRE, MATRIX) |

---

## 9. Abiertos / NO VERIFICADO prioritarios
- Velocidad, altura, resolución y fps de **BIRDSAI** (el PDF de CVF devolvió 403). Habría que leerlos en el PDF o en las cabeceras del zip de LILA.
- Qué clips de **SeaDronesSee-MOT** son del **Trinity F90+**, y si el servidor de descarga vuelve. Si no vuelve, escribir a MaCVi.
- Si BuckTales, BaboonLand, WildLive, M3OT y VT-MOT tienen **ego-movimiento** real (los papers no lo dicen).
- La correspondencia exacta entre el ID de la cámara de instancias de CARLA y `actor.id`, y si CARLA 1.0 trae un sensor térmico.
- Qué campos de telemetría (pitch del gimbal, zoom) graba el **dron concreto** que se vaya a usar.
- La licencia de los **datos** de SynDrone, DynUAV, VT-MOT y M3OT.

---

## 10. Fuentes

[dynuav]: https://arxiv.org/html/2603.05970
[sds]: https://arxiv.org/abs/2105.01922
[sds-ar5iv]: https://ar5iv.labs.arxiv.org/html/2105.01922
[sds-reid]: https://arxiv.org/html/2311.03561v2
[sds-repo]: https://github.com/Ben93kie/SeaDronesSee
[macvi]: https://macvi.org/dataset
[birdsai-lila]: https://lila.science/datasets/conservationdrones
[birdsai-site]: https://www.sites.google.com/view/elizabethbondi/dataset
[birdsai-mla]: https://mlanthology.org/wacv/2020/bondi2020wacv-birdsai
[vetra]: https://www.dlr.de/en/eoc/vetra
[sdms]: https://www.sdms.afrl.af.mil/
[m3ot]: https://pmc.ncbi.nlm.nih.gov/articles/PMC12686387/
[vtmot]: https://arxiv.org/html/2408.00969v1
[hituav]: https://arxiv.org/abs/2204.03245
[monet]: https://arxiv.org/abs/2304.05417
[bucktales]: https://arxiv.org/html/2411.06896v1
[bucktales-api]: https://doi.org/10.17617/3.JCZ9WK
[baboon]: https://arxiv.org/html/2405.17698v3
[wildlive]: https://arxiv.org/html/2504.10165v3
[matrix]: https://arxiv.org/abs/2511.08615
[pdestre]: https://arxiv.org/abs/2004.02782
[syndrone-repo]: https://github.com/LTTM/Syndrone
[syndrone-code]: https://github.com/LTTM/Syndrone/blob/main/modules/carla_utils/CarlaClient.py
[flyaware]: https://medialab.dei.unipd.it/paper_data/FlyAwareV2/
[flyaware-dl]: https://medialab.dei.unipd.it/paper_data/FlyAwareV2/downloads
[flyaware-arxiv]: https://arxiv.org/abs/2510.13243
[uavmm3d]: https://arxiv.org/abs/2511.22404
[carla-rel]: https://github.com/carla-simulator/carla/releases/tag/1.0
[carla-tm]: https://carla.readthedocs.io/en/latest/adv_traffic_manager/
[carla-api]: https://carla.readthedocs.io/en/latest/python_api/
[carla-bb]: https://carla.readthedocs.io/en/latest/tuto_G_bounding_boxes/
[carla-inst]: https://carla.readthedocs.io/en/latest/tuto_G_instance_segmentation_sensor/
[pas]: https://github.com/iamaisim/ProjectAirSim
[airsim-ann]: https://github.com/microsoft/AirSim/blob/main/project_airsim.md
[cosys]: https://github.com/Cosys-Lab/Cosys-AirSim
[pegasus]: https://github.com/PegasusSimulator/PegasusSimulator
[replicator]: https://docs.omniverse.nvidia.com/py/replicator/1.12.16/source/extensions/omni.replicator.core/docs/annotators_details.html
[isaac-writer]: https://docs.isaacsim.omniverse.nvidia.com/5.1.0/action_and_event_data_generation/ext_replicator-agent/writer_control.html
[ucmc]: https://arxiv.org/abs/2312.08952
[irani]: https://doi.org/10.1109/34.683770
[mod-review]: https://arxiv.org/abs/2001.05238
[px4-ulog]: https://docs.px4.io/main/en/dev_log/ulog_file_format.html
[px4-cam]: https://docs.px4.io/main/ko/camera/fc_connected_camera

- **DynUAV**: Ye et al., CVPR 2026, [arXiv 2603.05970][dynuav].
- **SeaDronesSee**: Varga et al., WACV 2022, [arXiv 2105.01922][sds]; [README oficial (licencia CC0, campos de metadatos)][sds-repo]; Kiefer et al., "Sea You Later", [arXiv 2311.03561][sds-reid]; [MaCVi][macvi].
- **BIRDSAI**: Bondi et al., WACV 2020, [mlanthology][birdsai-mla]; [LILA][birdsai-lila]; [página de la autora][birdsai-site].
- **VETRA**: Hellekes et al., ECCV 2024, [DLR][vetra]. **WPAFB 2009**: [AFRL SDMS][sdms].
- **M3OT**: Sci. Data 2025, [PMC12686387][m3ot]. **VT-MOT**: [arXiv 2408.00969][vtmot]. **HIT-UAV**: Suo et al., Sci. Data 10:227 (2023), [arXiv 2204.03245][hituav]. **MONET**: CVPRW 2023, [arXiv 2304.05417][monet].
- **BuckTales**: Naik et al., NeurIPS 2024 D&B, [arXiv 2411.06896][bucktales]; Edmond [doi:10.17617/3.JCZ9WK][bucktales-api] (metadatos leídos por la API pública de Dataverse). **BaboonLand**: [arXiv 2405.17698][baboon]. **WildLive**: [arXiv 2504.10165][wildlive].
- **MATRIX**: [arXiv 2511.08615][matrix]. **P-DESTRE**: [arXiv 2004.02782][pdestre]. **UAV-MM3D**: [arXiv 2511.22404][uavmm3d].
- **SynDrone**: [repo][syndrone-repo]; [CarlaClient.py][syndrone-code] (hfov, export de cajas). **FlyAwareV2**: [arXiv 2510.13243][flyaware-arxiv]; [página][flyaware]; [descargas][flyaware-dl].
- **CARLA**: [release 1.0][carla-rel]; [Traffic Manager][carla-tm]; [API Python][carla-api]; [tutorial de cajas][carla-bb]; [segmentación de instancias][carla-inst].
- **Project AirSim (IAMAI)**: [README][pas]. **AirSim (Microsoft)**: [anuncio de archivo][airsim-ann]. **Cosys-AirSim**: [README][cosys]. **Pegasus Simulator**: [README][pegasus]. **Isaac Sim Replicator**: [annotators][replicator]; [Writer Control][isaac-writer].
- Estado de los repos (archivado, último push, licencia): API pública de GitHub `api.github.com/repos/<org>/<repo>`, consultada el 2026-11-21: microsoft/AirSim, CodexLabsLLC/Colosseum (**archived**), Cosys-Lab/Cosys-AirSim, iamaisim/ProjectAirSim, carla-simulator/carla, PegasusSimulator/PegasusSimulator, unrealcv/unrealcv, UnrealZoo/unrealzoo-gym, uzh-rpg/flightmare, JSBSim-Team/jsbsim, suojiashun/HIT-UAV-Infrared-Thermal-Dataset, wqw123wqw/PFTrack.
- **Geometría plano + paralaje**: Irani & Anandan, IEEE TPAMI 20(6):577–589, 1998, [doi:10.1109/34.683770][irani]; revisión [arXiv 2001.05238][mod-review].
- **UCMCTrack**: [arXiv 2312.08952][ucmc].
- **PX4**: [formato ULog][px4-ulog]; [cámaras conectadas al FC / captura][px4-cam].
- **Telemetría DJI (.SRT o metadatos en MP4)**: solo fuentes comunitarias (foros, parsers de terceros) → **NO VERIFICADO**. No se usan como fuente principal.
