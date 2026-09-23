"""
Lectura de cámara RTSP en un hilo separado.

Por qué un hilo aparte: OpenCV va llenando un buffer interno con frames de la
cámara. Si tu CPU tarda en procesar cada frame (por el modelo de detección),
el buffer se acumula y terminas viendo/analizando video "atrasado" respecto
al tiempo real. Con un hilo dedicado a leer, siempre nos quedamos con el
frame MÁS RECIENTE y descartamos los viejos.
"""

import cv2
import os
import threading
import time
import logging

logger = logging.getLogger(__name__)

# Fuerza transporte TCP (evita corrupción de frames por pérdida de paquetes UDP,
# causa típica de "error while decoding MB ... bytestream -36") y baja el
# timeout interno de FFmpeg de 30s (default) a 5s.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000"
)
# stimeout está en microsegundos -> 5,000,000 = 5s


class CameraStream:
    def __init__(self, camera_id: str, rtsp_url: str, reconnect_delay: int = 5,
                 stale_frame_timeout: int = 10):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.reconnect_delay = reconnect_delay
        self.stale_frame_timeout = stale_frame_timeout  # seg sin frame nuevo -> reconectar

        self.capture = None
        self.latest_frame = None
        self.last_frame_at = 0.0
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        logger.info(f"[{self.camera_id}] Hilo de captura iniciado")
        return self

    def _connect(self):
        capture = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.last_frame_at = time.time()
        return capture

    def _reconnect(self):
        if self.capture:
            self.capture.release()
        self.capture = None
        time.sleep(self.reconnect_delay)
        self.capture = self._connect()

    def _update_loop(self):
        self.capture = self._connect()

        while self.running:
            if self.capture is None or not self.capture.isOpened():
                logger.warning(f"[{self.camera_id}] Sin conexión, reintentando en {self.reconnect_delay}s...")
                self._reconnect()
                continue

            ok, frame = self.capture.read()

            if not ok:
                logger.warning(f"[{self.camera_id}] Frame no leído, reconectando...")
                self._reconnect()
                continue

            with self.lock:
                self.latest_frame = frame
                self.last_frame_at = time.time()

            # Watchdog: isOpened() puede seguir devolviendo True aunque el stream
            # ya esté "zombie" (sin frames nuevos). Si pasa demasiado tiempo sin
            # actualizar, forzamos reconexión en vez de esperar el timeout de FFmpeg.
            if time.time() - self.last_frame_at > self.stale_frame_timeout:
                logger.warning(f"[{self.camera_id}] Sin frames nuevos hace >{self.stale_frame_timeout}s, forzando reconexión...")
                self._reconnect()

    def read(self):
        """Devuelve el frame más reciente disponible (o None si aún no hay ninguno)."""
        with self.lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.capture:
            self.capture.release()
        logger.info(f"[{self.camera_id}] Detenido")