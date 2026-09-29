"""
Orquestador principal.

Evalúa las cámaras RTSP y utiliza YOLO local.

Lógica:

- CUMPLE:
    person + sleeves + face_shield_down

- INCUMPLIMIENTO:
    person + sleeveless
    person + face_shield_up

- DUDOSO:
    persona detectada pero sin información suficiente
    o existe información contradictoria.

IMPORTANTE:

La decisión final de alerta se realiza mediante una ventana
de tiempo.

Una condición debe aparecer en al menos
required_violation_ratio de las muestras dentro de la ventana
para confirmar una alerta.

Además:

- Una detección simultánea de face_shield_down y
  face_shield_up se considera conflicto.
- Un conflicto de careta no genera por sí mismo una alerta.
- La ausencia de face_shield_down NO significa automáticamente
  falta de careta.
- La antigua regla "casco sin careta_abajo = falta de careta"
  fue eliminada para evitar falsas alarmas, especialmente
  con cascos blancos y caretas transparentes.

Cada cámara mantiene su propia ventana y su propio cooldown.

El sistema notifica por WhatsApp cuando arranca y cuando
se detiene.
"""

import yaml
import time
import signal
import logging
import os

from dotenv import load_dotenv
from collections import defaultdict, deque

load_dotenv()

from camera_stream import CameraStream
from ppe_detector import PPEDetector
from alert_manager import AlertManager


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# CARGAR CONFIGURACION
# ============================================================

def cargar_config(path="config.yaml"):

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file)


# ============================================================
# EXCEPCION DE APAGADO
# ============================================================

class ApagadoSolicitado(Exception):

    """
    Señal interna para indicar que el proceso debe
    detenerse de forma controlada.
    """

    def __init__(
        self,
        motivo: str,
    ):

        self.motivo = motivo

        super().__init__(
            motivo
        )


# ============================================================
# MAIN
# ============================================================

def main():

    config = cargar_config()

    # =========================================================
    # CAMARAS
    # =========================================================

    streams = {}

    for camera_config in config["cameras"]:

        camera_id = camera_config["id"]

        rtsp_env = camera_config["rtsp_env"]

        rtsp_url = os.getenv(
            rtsp_env
        )

        if not rtsp_url:

            raise ValueError(
                "No se encontró la variable de entorno: {}".format(
                    rtsp_env
                )
            )

        stream = CameraStream(
            camera_id,
            rtsp_url,
        ).start()

        streams[
            camera_id
        ] = stream

    # =========================================================
    # DETECTOR
    # =========================================================

    detection_config = config[
        "detection"
    ]

    detector = PPEDetector(
        model_path=detection_config[
            "model_path"
        ],

        confidence_threshold=detection_config.get(
            "confidence_threshold",
            0.4,
        ),

        resize_width=detection_config.get(
            "resize_width",
            640,
        ),

        class_confidence=detection_config.get(
            "class_confidence",
            {},
        ),
    )

    # =========================================================
    # ALERT MANAGER
    # =========================================================

    testing_config = config.get(
        "testing",
        {},
    )

    dry_run = testing_config.get(
        "dry_run",
        False,
    )

    alert_cooldown_seconds = detection_config.get(
        "alert_cooldown_seconds",
        30,
    )

    alert_manager = AlertManager(
        greenapi_config=config[
            "greenapi"
        ],

        storage_config=config[
            "storage"
        ],

        cooldown_seconds=alert_cooldown_seconds,

        dry_run=dry_run,
    )

    # =========================================================
    # SEÑALES DEL SISTEMA OPERATIVO
    # =========================================================

    def _manejar_sigterm(
        signum,
        frame,
    ):

        raise ApagadoSolicitado(
            "Señal SIGTERM recibida "
            "(systemctl stop / kill)"
        )

    signal.signal(
        signal.SIGTERM,
        _manejar_sigterm,
    )

    # =========================================================
    # CONFIGURACION DE VENTANA
    # =========================================================

    frame_skip = detection_config.get(
        "frame_skip",
        1,
    )

    window_seconds = detection_config.get(
        "alert_window_seconds",
        3.0,
    )

    min_samples_ventana = detection_config.get(
        "min_samples_ventana",
        3,
    )

    required_violation_ratio = detection_config.get(
        "required_violation_ratio",
        0.7,
    )

    logger.info(
        f"Ventana de evaluación: "
        f"{window_seconds}s"
    )

    logger.info(
        f"Mínimo de muestras en ventana: "
        f"{min_samples_ventana}"
    )

    logger.info(
        f"Proporción requerida para confirmar: "
        f"{required_violation_ratio * 100:.0f}%"
    )

    logger.info(
        f"Cooldown WhatsApp: "
        f"{alert_cooldown_seconds}s por cámara"
    )

    # =========================================================
    # HISTORIAL POR CAMARA
    #
    # Cada entrada:
    #
    #   (
    #       timestamp,
    #       estado,
    #       incumplimientos,
    #       conflicto_careta
    #   )
    #
    # =========================================================

    historial = defaultdict(
        deque
    )

    ultimo_estado_confirmado = defaultdict(
        lambda: None
    )

    logger.info(
        "Sistema iniciado."
    )

    # =========================================================
    # NOTIFICACION DE ENCENDIDO
    # =========================================================

    alert_manager.notificar_sistema_encendido(
        list(
            streams.keys()
        )
    )

    frame_counter = 0

    motivo_apagado = (
        "Detenido manualmente (Ctrl+C)"
    )

    try:

        while True:

            frame_counter += 1

            # -------------------------------------------------
            # Ritmo del loop
            # -------------------------------------------------

            time.sleep(
                0.1
            )

            # -------------------------------------------------
            # Procesar cada N iteraciones
            # -------------------------------------------------

            if (
                frame_counter
                % frame_skip
                != 0
            ):

                continue

            # =================================================
            # PROCESAR CAMARAS
            # =================================================

            for camera_id, stream in streams.items():

                frame = stream.read()

                if frame is None:

                    continue

                # =================================================
                # DETECCION
                # =================================================

                detections = detector.detect(
                    frame
                )

                # =================================================
                # EVALUAR FRAME
                # =================================================

                evaluation = detector.evaluar_frame(
                    detections
                )

                estado = evaluation[
                    "estado"
                ]

                incumplimientos = evaluation[
                    "incumplimientos"
                ]

                clases = evaluation[
                    "clases"
                ]

                conflicto_careta = evaluation.get(
                    "conflicto_careta",
                    False,
                )

                ahora = time.time()

                # =================================================
                # SIN PERSONA
                # =================================================

                if "persona" not in clases:

                    historial[
                        camera_id
                    ].clear()

                    ultimo_estado_confirmado[
                        camera_id
                    ] = None

                    continue

                # =================================================
                # GUARDAR MUESTRA
                # =================================================

                historial[
                    camera_id
                ].append(
                    (
                        ahora,
                        estado,
                        incumplimientos,
                        conflicto_careta,
                    )
                )

                # =================================================
                # PURGAR FUERA DE LA VENTANA
                # =================================================

                while (
                    historial[camera_id]
                    and
                    ahora
                    - historial[camera_id][0][0]
                    > window_seconds
                ):

                    historial[
                        camera_id
                    ].popleft()

                # =================================================
                # REGISTRO INFORMATIVO
                # =================================================

                alert_manager.registrar_deteccion_informativa(
                    camera_id,
                    clases,
                    estado,
                )

                # =================================================
                # MINIMO DE MUESTRAS
                # =================================================

                muestras = list(
                    historial[
                        camera_id
                    ]
                )

                if (
                    len(muestras)
                    < min_samples_ventana
                ):

                    continue

                total_muestras = len(
                    muestras
                )

                # =================================================
                # SEPARAR INFORMACION DE LA VENTANA
                # =================================================

                estados = [
                    muestra[1]
                    for muestra in muestras
                ]

                violaciones_por_muestra = [
                    muestra[2]
                    for muestra in muestras
                ]

                conflictos_por_muestra = [
                    muestra[3]
                    for muestra in muestras
                ]

                # =================================================
                # CONTAR INCUMPLIMIENTOS
                # =================================================

                conteo_incumplimientos = defaultdict(
                    int
                )

                for frame_violations in (
                    violaciones_por_muestra
                ):

                    for violation in (
                        frame_violations
                    ):

                        conteo_incumplimientos[
                            violation
                        ] += 1

                # =================================================
                # CONTAR CONFLICTOS DE CARETA
                # =================================================

                cantidad_conflictos = sum(
                    1
                    for conflicto
                    in conflictos_por_muestra
                    if conflicto
                )

                # =================================================
                # CONDICIONES CONFIRMADAS
                # =================================================

                incumplimientos_confirmados = [
                    violation
                    for violation, count
                    in conteo_incumplimientos.items()
                    if (
                        count
                        / total_muestras
                    )
                    >= required_violation_ratio
                ]

                # =================================================
                # PROTECCION EXTRA PARA CARETA LEVANTADA
                # =================================================
                #
                # No permitir alerta de "careta levantada"
                # cuando existe demasiado conflicto entre
                # careta_abajo y careta_arriba.
                #
                # Esto evita que una detección falsa repetida
                # de face_shield_up domine la ventana.
                #
                # =================================================

                if (
                    "careta levantada"
                    in incumplimientos_confirmados
                ):

                    proporcion_conflicto = (
                        cantidad_conflictos
                        / total_muestras
                    )

                    if (
                        proporcion_conflicto
                        >= (
                            1.0
                            - required_violation_ratio
                        )
                    ):

                        logger.info(
                            f"[{camera_id}] "
                            f"Conflicto de careta detectado "
                            f"en {cantidad_conflictos}/"
                            f"{total_muestras} muestras. "
                            f"Se descarta alerta de "
                            f"careta levantada por "
                            f"información contradictoria."
                        )

                        incumplimientos_confirmados = [
                            violation
                            for violation
                            in incumplimientos_confirmados
                            if (
                                violation
                                != "careta levantada"
                            )
                        ]

                # =================================================
                # ESTADO FINAL DE LA VENTANA
                # =================================================

                if incumplimientos_confirmados:

                    estado_final = (
                        "incumplimiento"
                    )

                elif any(
                    state
                    == "incumplimiento"
                    for state in estados
                ):

                    estado_final = (
                        "dudoso"
                    )

                elif all(
                    state
                    == "cumple"
                    for state in estados
                ):

                    estado_final = (
                        "cumple"
                    )

                else:

                    estado_final = (
                        "dudoso"
                    )

                # =================================================
                # LOG
                # =================================================

                logger.info(
                    f"[{camera_id}] "
                    f"Ventana ({window_seconds}s, "
                    f"{total_muestras} muestras): "
                    f"{estados} | "
                    f"Conflictos careta: "
                    f"{cantidad_conflictos}/"
                    f"{total_muestras} | "
                    f"Estado final: "
                    f"{estado_final} | "
                    f"Confirmados: "
                    f"{incumplimientos_confirmados}"
                )

                # =================================================
                # CUMPLIMIENTO CONFIRMADO
                # =================================================

                if (
                    estado_final
                    == "cumple"
                ):

                    if (
                        ultimo_estado_confirmado[
                            camera_id
                        ]
                        != "cumple"
                    ):

                        alert_manager.registrar_cumplimiento_confirmado(
                            camera_id
                        )

                    ultimo_estado_confirmado[
                        camera_id
                    ] = "cumple"

                elif (
                    estado_final
                    == "dudoso"
                ):

                    ultimo_estado_confirmado[
                        camera_id
                    ] = "dudoso"

                # =================================================
                # ALERTA
                # =================================================

                if (
                    estado_final
                    == "incumplimiento"
                    and
                    incumplimientos_confirmados
                ):

                    logger.warning(
                        f"[{camera_id}] "
                        f"INCUMPLIMIENTO CONFIRMADO: "
                        f"{incumplimientos_confirmados}"
                    )

                    alert_manager.procesar_incumplimiento(
                        camera_id,
                        incumplimientos_confirmados,
                        frame,
                    )

                    ultimo_estado_confirmado[
                        camera_id
                    ] = "incumplimiento"

                    # -------------------------------------------------
                    # Después de una alerta empezamos
                    # una ventana nueva.
                    # -------------------------------------------------

                    historial[
                        camera_id
                    ].clear()

    # =========================================================
    # APAGADO MANUAL
    # =========================================================

    except KeyboardInterrupt:

        motivo_apagado = (
            "Detenido manualmente (Ctrl+C)"
        )

        logger.info(
            "Deteniendo sistema..."
        )

    # =========================================================
    # APAGADO CONTROLADO
    # =========================================================

    except ApagadoSolicitado as apagado:

        motivo_apagado = (
            apagado.motivo
        )

        logger.info(
            f"Deteniendo sistema: "
            f"{motivo_apagado}"
        )

    # =========================================================
    # ERROR INESPERADO
    # =========================================================

    except Exception as error:

        motivo_apagado = (
            f"Error inesperado: {error}"
        )

        logger.exception(
            "El sistema se detuvo por un error inesperado."
        )

        raise

    # =========================================================
    # FINALIZACION
    # =========================================================

    finally:

        for stream in streams.values():

            stream.stop()

        alert_manager.notificar_sistema_apagado(
            motivo_apagado
        )


# ============================================================
# EJECUCION
# ============================================================

if __name__ == "__main__":

    main()