"""
Detección de EPP usando un modelo YOLO entrenado localmente.

Clases del modelo:

  0: cap                -> casco
  1: face_shield_down   -> careta_abajo
  2: face_shield_up     -> careta_arriba
  3: gloves             -> guantes
  4: person             -> persona
  5: sleeveless         -> sin_manga
  6: sleeves            -> mangas

La CARETA es el núcleo del cumplimiento.

Estados de cumplimiento por frame:

  CUMPLE:
      person + sleeves + face_shield_down

  INCUMPLIMIENTO:
      person + sleeveless                    -> "sin mangas"
      person + face_shield_up                -> "careta levantada"
      person + cap SIN face_shield_down      -> "falta de careta"

  DUDOSO:
      persona detectada, pero no se cumple ninguna
      de las condiciones anteriores (información insuficiente
      o contradictoria).

IMPORTANTE:

  Si en el mismo frame aparecen face_shield_down y face_shield_up
  se considera un CONFLICTO y NO se genera un incumplimiento por
  careta levantada. Esto evita que una falsa detección de
  face_shield_up convierta una persona bien protegida en una alerta.

  Un frame puede tener VARIOS incumplimientos a la vez
  (por ejemplo "sin mangas" y "falta de careta"); todos se
  regresan en la lista "incumplimientos".

La decisión final de alerta mediante varios frames
se realiza en main.py.
"""

from ultralytics import YOLO
import logging


logger = logging.getLogger(__name__)


# ============================================================
# MAPEO DE CLASES DEL MODELO
# ============================================================

CLASS_NAME_MAP = {
    "cap": "casco",
    "face_shield_down": "careta_abajo",
    "face_shield_up": "careta_arriba",
    "gloves": "guantes",
    "person": "persona",
    "sleeveless": "sin_manga",
    "sleeves": "mangas",
}


DEFAULT_CONFIDENCE = 0.4


class PPEDetector:

    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = DEFAULT_CONFIDENCE,
        resize_width: int = 640,
        class_confidence: dict | None = None,
    ):
        logger.info(f"Cargando modelo desde {model_path}...")

        self.model = YOLO(model_path)

        self.confidence_threshold = confidence_threshold
        self.resize_width = resize_width

        # --------------------------------------------------------
        # Convertir los nombres internos al nombre real del modelo
        # --------------------------------------------------------

        raw_map = {
            internal_name: raw_name
            for raw_name, internal_name in CLASS_NAME_MAP.items()
        }

        self.class_confidence_raw = {}

        for internal_name, threshold in (class_confidence or {}).items():
            raw_name = raw_map.get(internal_name, internal_name)
            self.class_confidence_raw[raw_name] = threshold

        logger.info(
            "Modelo cargado. Clases disponibles: "
            f"{self.model.names}"
        )

    # ============================================================
    # DETECCION
    # ============================================================

    def detect(self, frame):
        """
        Ejecuta YOLO sobre un frame.

        Regresa una lista:

        [
            {
                "clase": str,
                "confianza": float,
                "box": [x1, y1, x2, y2]
            }
        ]
        """

        h, w = frame.shape[:2]

        # --------------------------------------------------------
        # Redimensionar solamente si el frame es más ancho
        # --------------------------------------------------------

        if w > self.resize_width:
            scale = self.resize_width / w
            frame = cv2_resize(
                frame,
                self.resize_width,
                int(h * scale),
            )

        # --------------------------------------------------------
        # Umbral mínimo global
        #
        # Usamos el umbral más bajo para no eliminar
        # detecciones de clases con confianza menor.
        # --------------------------------------------------------

        min_conf = min(
            [
                self.confidence_threshold,
                *self.class_confidence_raw.values(),
            ],
            default=self.confidence_threshold,
        )

        # --------------------------------------------------------
        # Inferencia YOLO
        # --------------------------------------------------------

        results = self.model.predict(
            frame,
            conf=min_conf,
            verbose=False,
            device="cpu",
        )

        detections = []

        # --------------------------------------------------------
        # Procesar resultados
        # --------------------------------------------------------

        for result in results:
            for box in result.boxes:

                class_id = int(box.cls[0])
                raw_name = self.model.names[class_id]
                confidence = float(box.conf[0])

                # Confianza específica de la clase
                threshold = self.class_confidence_raw.get(
                    raw_name,
                    self.confidence_threshold,
                )

                if confidence < threshold:
                    continue

                # Convertir nombre a nombre interno
                mapped_name = CLASS_NAME_MAP.get(raw_name, raw_name)

                # Coordenadas
                xyxy = box.xyxy[0].tolist()

                detections.append(
                    {
                        "clase": mapped_name,
                        "confianza": confidence,
                        "box": xyxy,
                    }
                )

        return detections

    # ============================================================
    # EVALUACION DEL FRAME
    # ============================================================

    def evaluar_frame(self, detections):
        """
        Evalúa un frame individual.

        Regresa:

        {
            "estado": "cumple" | "dudoso" | "incumplimiento",
            "incumplimientos": [...],
            "clases": [...],
            "conflicto_careta": bool
        }

        ----------------------------------------------------------
        CUMPLE
        ----------------------------------------------------------

        person + sleeves + face_shield_down

        ----------------------------------------------------------
        INCUMPLIMIENTO (pueden sumarse varios motivos)
        ----------------------------------------------------------

        person + sleeveless                 -> "sin mangas"
        person + face_shield_up             -> "careta levantada"
        person + cap SIN face_shield_down   -> "falta de careta"

        Si existen simultáneamente face_shield_down y
        face_shield_up se considera un conflicto y la careta
        NO genera un incumplimiento por careta levantada.

        ----------------------------------------------------------
        DUDOSO
        ----------------------------------------------------------

        Persona detectada, pero no se cumple ninguna de las
        condiciones anteriores.
        """

        # --------------------------------------------------------
        # Clases presentes en el frame
        # --------------------------------------------------------

        clases = {detection["clase"] for detection in detections}

        # --------------------------------------------------------
        # Estado por defecto
        # --------------------------------------------------------

        resultado = {
            "estado": "dudoso",
            "incumplimientos": [],
            "clases": sorted(clases),
            "conflicto_careta": False,
        }

        # --------------------------------------------------------
        # Sin persona
        # --------------------------------------------------------

        if "persona" not in clases:
            return resultado

        casco = "casco" in clases
        careta_abajo = "careta_abajo" in clases
        careta_arriba = "careta_arriba" in clases

        conflicto_careta = careta_abajo and careta_arriba
        resultado["conflicto_careta"] = conflicto_careta

        incumplimientos = []

        # ========================================================
        # 1. SIN MANGAS
        # ========================================================

        if "sin_manga" in clases:
            incumplimientos.append("sin mangas")

        # ========================================================
        # 2. CARETA LEVANTADA
        #
        # Si también existe careta_abajo hay contradicción:
        # no confiamos en careta_arriba.
        # ========================================================

        if careta_arriba and not careta_abajo:
            incumplimientos.append("careta levantada")

        # ========================================================
        # 3. CASCO SIN CARETA
        #
        # La careta es el núcleo: casco sin face_shield_down es
        # incumplimiento. Si ya se reportó "careta levantada"
        # (hay careta_arriba) no se duplica el motivo.
        # ========================================================

        if casco and not careta_abajo and not careta_arriba:
            incumplimientos.append("falta de careta")

        # --------------------------------------------------------
        # Eliminar duplicados conservando el orden
        # --------------------------------------------------------

        incumplimientos = list(dict.fromkeys(incumplimientos))
        resultado["incumplimientos"] = incumplimientos

        # ========================================================
        # INCUMPLIMIENTO
        # ========================================================

        if incumplimientos:
            resultado["estado"] = "incumplimiento"
            return resultado

        # ========================================================
        # CONFLICTO DE CARETA
        #
        # Si hay down + up y no hay otra causa independiente de
        # incumplimiento, no decimos que cumple ni que incumple.
        # ========================================================

        if conflicto_careta:
            resultado["estado"] = "dudoso"
            return resultado

        # ========================================================
        # CUMPLIMIENTO
        # ========================================================

        if "mangas" in clases and careta_abajo:
            resultado["estado"] = "cumple"
            return resultado

        # ========================================================
        # DUDOSO
        # ========================================================

        resultado["estado"] = "dudoso"
        return resultado

    # ============================================================
    # CLASES INFORMATIVAS
    # ============================================================

    def clases_informativas_presentes(self, detections):
        """
        Regresa las clases detectadas que sirven para
        análisis y reportes.

        Incluye:

            casco
            guantes
            careta_abajo
            careta_arriba
            mangas
            sin_manga
            persona
        """

        informativas = {
            "casco",
            "guantes",
            "careta_abajo",
            "careta_arriba",
            "mangas",
            "sin_manga",
            "persona",
        }

        clases_detectadas = {
            detection["clase"] for detection in detections
        }

        return sorted(clases_detectadas & informativas)


# ============================================================
# RESIZE DE FRAME
# ============================================================

def cv2_resize(frame, width, height):
    import cv2

    return cv2.resize(frame, (width, height))