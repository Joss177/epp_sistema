"""
Genera el reporte semanal de cumplimiento de EPP.

Consulta SQLite (solo eventos confirmados: es_alerta=1), arma una
gráfica de barras agrupadas (cumplimientos vs incumplimientos por
cámara) y la envía por WhatsApp junto con un resumen de texto.

Requiere que main.py y alert_manager.py ya registren los
cumplimientos confirmados vía registrar_cumplimiento_confirmado()
(ver parche descrito en la conversación) — de lo contrario el
conteo de cumplimientos siempre dará 0.

Pensado para ejecutarse una vez por semana (Task Scheduler / cron).
Uso: python reporte_semanal.py
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")  # sin ventana gráfica, solo genera el archivo
import matplotlib.pyplot as plt

import yaml
from dotenv import load_dotenv
import requests

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------
# Cámaras a incluir en el reporte.
# Ajustar cuando se agreguen envasado_1 / envasado_2.
# --------------------------------------------------------------
CAMARAS_REPORTE = ["entrada_planta", "linea_embotellado"]


def cargar_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def obtener_conteos(db_path, dias=7):
    """
    Cuenta eventos CONFIRMADOS (es_alerta=1) de tipo 'cumple' e
    'incumplimiento', por cámara, dentro de los últimos `dias` días.
    No cuenta filas de registrar_deteccion_informativa (es_alerta=0),
    que son ruido por-frame, no eventos deduplicados.
    """

    desde = (datetime.now() - timedelta(days=dias)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" for _ in CAMARAS_REPORTE)

    query = f"""
        SELECT camara_id, estado, COUNT(*) as total
        FROM eventos
        WHERE es_alerta = 1
          AND estado IN ('cumple', 'incumplimiento')
          AND camara_id IN ({placeholders})
          AND fecha_hora >= ?
        GROUP BY camara_id, estado
    """

    params = CAMARAS_REPORTE + [desde]
    rows = conn.execute(query, params).fetchall()
    conn.close()

    conteos = {
        camara: {"cumple": 0, "incumplimiento": 0}
        for camara in CAMARAS_REPORTE
    }

    for row in rows:
        conteos[row["camara_id"]][row["estado"]] = row["total"]

    return conteos


def generar_grafica(conteos, output_path):
    """
    Gráfica de barras agrupadas: cumple vs incumplimiento,
    una pareja de barras por cámara.
    """

    camaras = list(conteos.keys())
    cumple = [conteos[c]["cumple"] for c in camaras]
    incumplimiento = [conteos[c]["incumplimiento"] for c in camaras]

    posiciones = range(len(camaras))
    ancho = 0.35

    fig, ax = plt.subplots(figsize=(7, 4.5))

    barras_cumple = ax.bar(
        [i - ancho / 2 for i in posiciones],
        cumple,
        ancho,
        label="Cumplimientos",
        color="#2E7D32",
    )

    barras_incumplimiento = ax.bar(
        [i + ancho / 2 for i in posiciones],
        incumplimiento,
        ancho,
        label="Incumplimientos",
        color="#C62828",
    )

    ax.set_xticks(list(posiciones))
    ax.set_xticklabels(camaras)
    ax.set_ylabel("Número de eventos")
    ax.set_title("Resumen semanal de EPP")
    ax.legend()

    ax.bar_label(barras_cumple, padding=3, fontsize=9)
    ax.bar_label(barras_incumplimiento, padding=3, fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close(fig)

    logger.info(f"Gráfica guardada en {output_path}")


def enviar_reporte(greenapi_config, mensaje, imagen_path, dry_run=False):

    if dry_run:
        logger.info(
            f"[DRY_RUN] Reporte semanal:\n{mensaje}\nImagen: {imagen_path}"
        )
        return

    api_url = os.getenv(greenapi_config["api_url_env"])
    id_instance = os.getenv(greenapi_config["id_instance_env"])
    api_token = os.getenv(greenapi_config["api_token_instance_env"])

    chat_ids = [
        os.getenv(env_name)
        for env_name in greenapi_config["chat_id_envs"]
        if os.getenv(env_name)
    ]

    url = f"{api_url}/waInstance{id_instance}/sendFileByUpload/{api_token}"

    for chat_id in chat_ids:

        with open(imagen_path, "rb") as file:

            files = {
                "file": (os.path.basename(imagen_path), file, "image/png")
            }
            data = {"chatId": chat_id, "caption": mensaje}

            try:
                response = requests.post(
                    url, data=data, files=files, timeout=20
                )
                response.raise_for_status()
                logger.info(
                    f"Reporte enviado a {chat_id}: {response.status_code}"
                )
            except requests.RequestException as error:
                logger.error(f"Error enviando reporte a {chat_id}: {error}")


def main():

    config = cargar_config()

    db_path = config["storage"]["database_path"]
    dry_run = config.get("testing", {}).get("dry_run", False)

    conteos = obtener_conteos(db_path, dias=7)

    total_cumple = sum(c["cumple"] for c in conteos.values())
    total_incumplimiento = sum(c["incumplimiento"] for c in conteos.values())

    logger.info(
        f"Totales de la semana -> "
        f"Cumplimientos: {total_cumple} | "
        f"Incumplimientos: {total_incumplimiento}"
    )

    output_dir = os.path.dirname(db_path) or "data"
    output_path = os.path.join(output_dir, "reporte_semanal.png")

    generar_grafica(conteos, output_path)

    mensaje = (
        "📊 *Resumen de la semana*\n"
        f"Número de Cumplimientos: {total_cumple}\n"
        f"Número de Incumplimientos: {total_incumplimiento}\n\n"
        "_Este conteo es un aproximado ya que el modelo no es 100% "
        "confiable._"
    )

    enviar_reporte(
        config["greenapi"],
        mensaje,
        output_path,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()