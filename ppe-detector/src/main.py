"""
Orquestador principal.

Evalúa las cámaras RTSP y utiliza YOLO local.

Lógica:

- CUMPLE:
    person + sleeves + face_shield_down

- INCUMPLIMIENTO:
    person + sleeveless
    person + face_shield_up
    person + cap sin face_shield_down

- DUDOSO:
    persona detectada pero sin información suficiente.

La decisión de alerta se realiza mediante una ventana de TIEMPO
(alert_window_seconds), no de cantidad fija de frames. Esto es
más robusto ante variaciones de framerate causadas por red
inestable o carga de CPU: la ventana siempre representa el mismo
lapso de tiempo real, sin importar cuántos frames se hayan podido
leer dentro de ese lapso.

Una condición debe aparecer en al menos required_violation_ratio
proporción de las muestras dentro de la ventana para confirmar
una alerta, y se exige un mínimo de muestras (min_samples_ventana)
antes de evaluar, para no confirmar nada con solo 1-2 lecturas.

Cada cámara mantiene su propia ventana y su propio cooldown.

Adicionalmente, el sistema notifica por WhatsApp cuando
arranca y cuando se detiene (manualmente, por señal del
sistema operativo, o por un error inesperado).
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def cargar_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


class ApagadoSolicitado(Exception):
    """
    Señal interna para indicar que el proceso debe
    detenerse de forma controlada, junto con el motivo.
    """

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def main():

    config = cargar_config()

    # =========================================================
    # CAMARAS
    # =========================================================

    streams = {}

    for camera_config in config["cameras"]:

        camera_id = camera_config["id"]

        rtsp_env = camera_config["rtsp_env"]
        rtsp_url = os.getenv(rtsp_env)

        if not rtsp_url:
            raise ValueError(
                "No se encontró la variable de entorno: {}".format(rtsp_env)
            )

        stream = CameraStream(
            camera_id,
            rtsp_url,
        ).start()

        streams[camera_id] = stream

    # =========================================================
    # DETECTOR
    # =========================================================

    detection_config = config["detection"]

    detector = PPEDetector(
        model_path=detection_config["model_path"],
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
        greenapi_config=config["greenapi"],
        storage_config=config["storage"],
        cooldown_seconds=alert_cooldown_seconds,
        dry_run=dry_run,
    )

    # =========================================================
    # SEÑALES DEL SISTEMA OPERATIVO (apagado controlado)
    # =========================================================
    # SIGINT ya llega como KeyboardInterrupt (Ctrl+C).
    # Registramos SIGTERM para capturar, por ejemplo,
    # `systemctl stop` o `kill <pid>`, y lanzamos la misma
    # excepción interna con el motivo correspondiente.

    def _manejar_sigterm(signum, frame):
        raise ApagadoSolicitado(
            "Señal SIGTERM recibida "
            "(systemctl stop / kill)"
        )

    signal.signal(
        signal.SIGTERM,
        _manejar_sigterm,
    )

    # =========================================================
    # CONFIGURACION DE VENTANA (POR TIEMPO)
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
        f"Ventana de evaluación: {window_seconds}s"
    )

    logger.info(
        f"Mínimo de muestras en ventana: {min_samples_ventana}"
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
    # Cada entrada del deque es una tupla:
    #   (timestamp, estado, incumplimientos)
    #
    # No tiene maxlen fijo: el tamaño se controla purgando por
    # tiempo (ver más abajo), no por cantidad de elementos.
    # =========================================================

    historial = defaultdict(deque)

    ultimo_estado_confirmado = defaultdict(lambda: None)

    logger.info(
        "Sistema iniciado."
    )

    # -------------------------------------------------------
    # NOTIFICACION DE ENCENDIDO
    # -------------------------------------------------------

    alert_manager.notificar_sistema_encendido(
        list(streams.keys())
    )

    frame_counter = 0
    motivo_apagado = "Detenido manualmente (Ctrl+C)"

    try:

        while True:

            frame_counter += 1

            # Ritmo del loop
            time.sleep(0.1)

            # Procesar cada N iteraciones
            if frame_counter % frame_skip != 0:
                continue

            # =================================================
            # PROCESAR CAMARAS
            # =================================================

            for camera_id, stream in streams.items():

                frame = stream.read()

                if frame is None:
                    continue

                # -------------------------------------------------
                # DETECCION
                # -------------------------------------------------

                detections = detector.detect(
                    frame
                )

                # -------------------------------------------------
                # EVALUAR FRAME
                # -------------------------------------------------

                evaluation = detector.evaluar_frame(
                    detections
                )

                estado = evaluation["estado"]

                incumplimientos = evaluation[
                    "incumplimientos"
                ]

                clases = evaluation[
                    "clases"
                ]

                ahora = time.time()

                # -------------------------------------------------
                # SIN PERSONA -> reinicia la ventana de esta cámara
                # -------------------------------------------------

                if "persona" not in clases:

                    historial[
                        camera_id
                    ].clear()

                    ultimo_estado_confirmado[camera_id] = None 

                    continue

                # -------------------------------------------------
                # GUARDAR MUESTRA CON TIMESTAMP
                # -------------------------------------------------

                historial[camera_id].append(
                    (ahora, estado, incumplimientos)
                )

                # -------------------------------------------------
                # PURGAR MUESTRAS FUERA DE LA VENTANA DE TIEMPO
                # -------------------------------------------------

                while (
                    historial[camera_id]
                    and ahora - historial[camera_id][0][0] > window_seconds
                ):
                    historial[camera_id].popleft()

                # -------------------------------------------------
                # REGISTRO INFORMATIVO
                # -------------------------------------------------

                alert_manager.registrar_deteccion_informativa(
                    camera_id,
                    clases,
                    estado,
                )

                # -------------------------------------------------
                # ESPERAR MINIMO DE MUESTRAS EN LA VENTANA
                # -------------------------------------------------

                muestras = list(
                    historial[camera_id]
                )

                if len(muestras) < min_samples_ventana:
                    continue

                total_muestras = len(muestras)

                estados = [
                    muestra[1]
                    for muestra in muestras
                ]

                violaciones_por_muestra = [
                    muestra[2]
                    for muestra in muestras
                ]

                # -------------------------------------------------
                # CONTAR CADA INCUMPLIMIENTO DENTRO DE LA VENTANA
                # -------------------------------------------------

                conteo_incumplimientos = defaultdict(
                    int
                )

                for frame_violations in (
                    violaciones_por_muestra
                ):

                    for violation in frame_violations:

                        conteo_incumplimientos[
                            violation
                        ] += 1

                # -------------------------------------------------
                # CONDICIONES CONFIRMADAS POR PROPORCION
                # -------------------------------------------------

                incumplimientos_confirmados = [
                    violation
                    for violation, count
                    in conteo_incumplimientos.items()
                    if (count / total_muestras) >= required_violation_ratio
                ]

                # -------------------------------------------------
                # ESTADO FINAL DE LA VENTANA
                # -------------------------------------------------

                if incumplimientos_confirmados:

                    estado_final = "incumplimiento"

                elif any(
                    state == "incumplimiento"
                    for state in estados
                ):

                    estado_final = "dudoso"

                elif all(
                    state == "cumple"
                    for state in estados
                ):

                    estado_final = "cumple"

                else:

                    estado_final = "dudoso"

                logger.info(
                    f"[{camera_id}] "
                    f"Ventana ({window_seconds}s, {total_muestras} muestras): "
                    f"{estados} | "
                    f"Estado final: {estado_final} | "
                    f"Confirmados: "
                    f"{incumplimientos_confirmados}"
                )

                # -------------------------------------------------
                # CUMPLIMIENTO CONFIRMADO (solo en la transición)
                # -------------------------------------------------

                if estado_final == "cumple":

                    if ultimo_estado_confirmado[camera_id] != "cumple":

                        alert_manager.registrar_cumplimiento_confirmado(
                            camera_id
                        )

                    ultimo_estado_confirmado[camera_id] = "cumple"

                elif estado_final == "dudoso":

                    ultimo_estado_confirmado[camera_id] = "dudoso"

                # -------------------------------------------------
                # ALERTA
                # -------------------------------------------------

                if (
                    estado_final == "incumplimiento"
                    and incumplimientos_confirmados
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

                    ultimo_estado_confirmado[camera_id] = "incumplimiento"

                    # Después de una alerta empezamos
                    # una ventana nueva.
                    historial[
                        camera_id
                    ].clear()

    except KeyboardInterrupt:

        motivo_apagado = (
            "Detenido manualmente (Ctrl+C)"
        )

        logger.info(
            "Deteniendo sistema..."
        )

    except ApagadoSolicitado as apagado:

        motivo_apagado = apagado.motivo

        logger.info(
            f"Deteniendo sistema: {motivo_apagado}"
        )

    except Exception as error:

        motivo_apagado = (
            f"Error inesperado: {error}"
        )

        logger.exception(
            "El sistema se detuvo por un error inesperado."
        )

        raise

    finally:

        for stream in streams.values():
            stream.stop()

        alert_manager.notificar_sistema_apagado(
            motivo_apagado
        )


if __name__ == "__main__":
    main()