"""
Gestión de alertas.

Responsabilidades:

- Cooldown independiente por cámara.
- Guardado de evidencia.
- Registro SQLite.
- Envío por GreenAPI.
- Registro de estados:
    cumple
    dudoso
    incumplimiento
    sistema_encendido
    sistema_apagado

dry_run=True:
    no envía WhatsApp real.
"""

import cv2
import requests
import sqlite3
import time
import os
import logging

from dotenv import load_dotenv
from datetime import datetime


logger = logging.getLogger(__name__)

load_dotenv()


class AlertManager:

    def __init__(
        self,
        greenapi_config,
        storage_config,
        cooldown_seconds: float = 200,
        dry_run: bool = False,
    ):

        self.id_instance = os.getenv(
            greenapi_config["id_instance_env"]
        )

        self.api_token = os.getenv(
            greenapi_config["api_token_instance_env"]
        )

        self.chat_ids = [
            os.getenv(env_name)
            for env_name in greenapi_config["chat_id_envs"]
            if os.getenv(env_name)
        ]

        self.api_url = os.getenv(
            greenapi_config["api_url_env"]
        )

        self.snapshots_dir = storage_config[
            "snapshots_dir"
        ]

        self.db_path = storage_config[
            "database_path"
        ]

        self.cooldown_seconds = cooldown_seconds

        self.dry_run = dry_run

        os.makedirs(
            self.snapshots_dir,
            exist_ok=True,
        )

        database_dir = os.path.dirname(
            self.db_path
        )

        if database_dir:

            os.makedirs(
                database_dir,
                exist_ok=True,
            )

        self._last_alert_time = {}

        self._init_db()

        if self.dry_run:

            logger.warning(
                "AlertManager en DRY_RUN. "
                "No se enviaran mensajes reales."
            )

    # =========================================================
    # BASE DE DATOS
    # =========================================================

    def _init_db(self):

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camara_id TEXT NOT NULL,
                epp_faltante TEXT NOT NULL,
                fecha_hora TEXT NOT NULL,
                snapshot_path TEXT,
                dry_run INTEGER NOT NULL DEFAULT 0,
                es_alerta INTEGER NOT NULL DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'dudoso'
            )
            """
        )

        # -----------------------------------------------------
        # Migracion para bases anteriores
        # -----------------------------------------------------

        columns = conn.execute(
            "PRAGMA table_info(eventos)"
        ).fetchall()

        column_names = {
            column[1]
            for column in columns
        }

        if "es_alerta" not in column_names:

            conn.execute(
                """
                ALTER TABLE eventos
                ADD COLUMN es_alerta
                INTEGER NOT NULL DEFAULT 0
                """
            )

        if "estado" not in column_names:

            conn.execute(
                """
                ALTER TABLE eventos
                ADD COLUMN estado
                TEXT NOT NULL DEFAULT 'dudoso'
                """
            )

        conn.commit()
        conn.close()

    # =========================================================
    # COOLDOWN
    # =========================================================

    def _en_cooldown(
        self,
        camera_id: str,
    ) -> bool:

        ultimo = self._last_alert_time.get(
            camera_id,
            0,
        )

        return (
            time.time() - ultimo
        ) < self.cooldown_seconds

    # =========================================================
    # SNAPSHOT
    # =========================================================

    def _guardar_snapshot(
        self,
        camera_id: str,
        frame,
    ) -> str:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        filename = (
            f"{camera_id}_{timestamp}.jpg"
        )

        filepath = os.path.join(
            self.snapshots_dir,
            filename,
        )

        cv2.imwrite(
            filepath,
            frame,
        )

        return filepath

    # =========================================================
    # EVENTO
    # =========================================================

    def _registrar_evento(
        self,
        camera_id: str,
        epp_detectado: list,
        snapshot_path,
        estado: str,
        es_alerta: bool,
    ):

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            INSERT INTO eventos (
                camara_id,
                epp_faltante,
                fecha_hora,
                snapshot_path,
                dry_run,
                es_alerta,
                estado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                ", ".join(epp_detectado),
                datetime.now().isoformat(),
                snapshot_path,
                int(self.dry_run),
                int(es_alerta),
                estado,
            ),
        )

        conn.commit()
        conn.close()

    # =========================================================
    # WHATSAPP - CON IMAGEN
    # =========================================================

    def _enviar_whatsapp(
        self,
        mensaje: str,
        snapshot_path: str,
    ):

        if self.dry_run:

            logger.info(
                f"[DRY_RUN] WhatsApp:\n"
                f"{mensaje}\n"
                f"Snapshot: {snapshot_path}"
            )

            return

        url = (
            f"{self.api_url}"
            f"/waInstance{self.id_instance}"
            f"/sendFileByUpload/"
            f"{self.api_token}"
        )

        for chat_id in self.chat_ids:

            with open(
                snapshot_path,
                "rb",
            ) as file:

                files = {
                    "file": (
                        os.path.basename(
                            snapshot_path
                        ),
                        file,
                        "image/jpeg",
                    )
                }

                data = {
                    "chatId": chat_id,
                    "caption": mensaje,
                }

                try:

                    response = requests.post(
                        url,
                        data=data,
                        files=files,
                        timeout=15,
                    )

                    response.raise_for_status()

                    logger.info(
                        f"Alerta enviada por WhatsApp a "
                        f"{chat_id}: "
                        f"{response.status_code}"
                    )

                except requests.RequestException as error:

                    logger.error(
                        f"Error enviando alerta a "
                        f"{chat_id}: "
                        f"{error}"
                    )

    # =========================================================
    # WHATSAPP - SOLO TEXTO
    # =========================================================

    def _enviar_whatsapp_texto(
        self,
        mensaje: str,
    ):

        if self.dry_run:

            logger.info(
                f"[DRY_RUN] WhatsApp (texto):\n"
                f"{mensaje}"
            )

            return

        url = (
            f"{self.api_url}"
            f"/waInstance{self.id_instance}"
            f"/sendMessage/"
            f"{self.api_token}"
        )

        for chat_id in self.chat_ids:

            data = {
                "chatId": chat_id,
                "message": mensaje,
            }

            try:

                response = requests.post(
                    url,
                    json=data,
                    timeout=15,
                )

                response.raise_for_status()

                logger.info(
                    f"Notificación de sistema enviada a "
                    f"{chat_id}: "
                    f"{response.status_code}"
                )

            except requests.RequestException as error:

                logger.error(
                    f"Error enviando notificación de sistema a "
                    f"{chat_id}: "
                    f"{error}"
                )

    # =========================================================
    # ALERTA REAL (EPP)
    # =========================================================

    def registrar_cumplimiento_confirmado(self, camera_id: str):
        """
        Registra un evento de cumplimiento confirmado por la ventana
        de tiempo. No envía WhatsApp ni aplica cooldown — es_alerta=True
        aquí significa "evento confirmado/deduplicado para reportes",
        no "notificación enviada".
        """
        self._registrar_evento(
            camera_id=camera_id,
            epp_detectado=["cumple"],
            snapshot_path=None,
            estado="cumple",
            es_alerta=True,
    )

    def procesar_incumplimiento(
        self,
        camera_id: str,
        epp_faltante: list,
        frame,
    ):

        if self._en_cooldown(
            camera_id
        ):

            logger.info(
                f"[{camera_id}] "
                f"Alerta bloqueada por cooldown."
            )

            return

        snapshot_path = (
            self._guardar_snapshot(
                camera_id,
                frame,
            )
        )

        self._registrar_evento(
            camera_id=camera_id,
            epp_detectado=epp_faltante,
            snapshot_path=snapshot_path,
            estado="incumplimiento",
            es_alerta=True,
        )

        mensaje = (
            f"⚠️ *Alerta de EPP incompleto*\n"
            f"Camara: {camera_id}\n"
            f"Incumplimientos: "
            f"{', '.join(epp_faltante)}\n"
            f"Hora: "
            f"{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
        )

        self._enviar_whatsapp(
            mensaje,
            snapshot_path,
        )

        self._last_alert_time[
            camera_id
        ] = time.time()

    # =========================================================
    # NOTIFICACIONES DE ESTADO DEL SISTEMA
    # =========================================================

    def notificar_sistema_encendido(
        self,
        camaras: list,
    ):
        """
        Envía y registra el aviso de que el sistema
        acaba de iniciar y qué cámaras quedaron activas.
        """

        mensaje = (
            f"🟢 *Sistema de EPP iniciado*\n"
            f"Cámaras activas: "
            f"{', '.join(camaras) if camaras else 'ninguna'}\n"
            f"Hora: "
            f"{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
        )

        self._enviar_whatsapp_texto(
            mensaje
        )

        self._registrar_evento(
            camera_id="SISTEMA",
            epp_detectado=["sistema_encendido"],
            snapshot_path=None,
            estado="sistema_encendido",
            es_alerta=True,
        )

        logger.info(
            "Notificación de encendido registrada."
        )

    def notificar_sistema_apagado(
        self,
        motivo: str = "Detenido manualmente",
    ):
        """
        Envía y registra el aviso de que el sistema
        se está apagando, junto con el motivo.
        """

        mensaje = (
            f"🔴 *Sistema de EPP detenido*\n"
            f"Motivo: {motivo}\n"
            f"Hora: "
            f"{datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
        )

        self._enviar_whatsapp_texto(
            mensaje
        )

        self._registrar_evento(
            camera_id="SISTEMA",
            epp_detectado=["sistema_apagado"],
            snapshot_path=None,
            estado="sistema_apagado",
            es_alerta=True,
        )

        logger.info(
            "Notificación de apagado registrada."
        )

    # =========================================================
    # REGISTRO INFORMATIVO
    # =========================================================

    def registrar_deteccion_informativa(
        self,
        camera_id: str,
        clases_detectadas: list,
        estado: str,
    ):

        if not clases_detectadas:
            return

        self._registrar_evento(
            camera_id=camera_id,
            epp_detectado=clases_detectadas,
            snapshot_path=None,
            estado=estado,
            es_alerta=False,
        )