"""
Prueba del reporte semanal con datos de ejemplo.

No consulta la base de datos ni corre el sistema de detección —
usa números inventados solo para ver cómo se ve la gráfica y el
mensaje, y confirmar que la conexión con GreenAPI funciona.

Envía el mensaje REAL por WhatsApp (no es dry_run), para que
puedas verlo llegar directo a tu teléfono.

Uso: python test_reporte_semanal.py

Nota: la gráfica se genera con Pillow (generar_grafica_pillow.py) en vez
de matplotlib, porque en esta máquina una directiva de Control de
Aplicaciones de Windows bloquea el DLL nativo de matplotlib (_image.pyd).
"""

import os
import logging

import yaml
from dotenv import load_dotenv
import requests

from generar_grafica_pillow import generar_grafica

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------
# DATOS DE EJEMPLO (inventados, solo para la prueba visual)
# --------------------------------------------------------------

CONTEOS_EJEMPLO = {
    "entrada_planta": {"cumple": 128, "incumplimiento": 14},
    "linea_embotellado": {"cumple": 95, "incumplimiento": 22},
}

# --------------------------------------------------------------
# Para probar con un solo número: pon aquí los últimos dígitos
# del chat_id (sin @c.us). Déjalo como "" para mandar a todos
# los chat_ids configurados en .env.
# --------------------------------------------------------------

SOLO_TERMINA_EN = "3544"


def cargar_config(path="ppe-detector/config.yaml"):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def enviar_reporte(greenapi_config, mensaje, imagen_path):

    api_url = os.getenv(greenapi_config["api_url_env"])
    id_instance = os.getenv(greenapi_config["id_instance_env"])
    api_token = os.getenv(greenapi_config["api_token_instance_env"])

    chat_ids = [
        os.getenv(env_name)
        for env_name in greenapi_config["chat_id_envs"]
        if os.getenv(env_name)
    ]

    if SOLO_TERMINA_EN:
        chat_ids = [
            chat_id for chat_id in chat_ids
            if chat_id.split("@")[0].endswith(SOLO_TERMINA_EN)
        ]
        logger.info(
            f"Filtrando envío solo a números que terminan en "
            f"'{SOLO_TERMINA_EN}': {chat_ids}"
        )

    if not chat_ids:
        logger.error(
            "No hay chat_ids configurados en las variables de "
            "entorno. Revisa tu .env."
        )
        return

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
                    f"✅ Reporte de PRUEBA enviado a {chat_id}: "
                    f"{response.status_code}"
                )
            except requests.RequestException as error:
                logger.error(
                    f"❌ Error enviando reporte de prueba a "
                    f"{chat_id}: {error}"
                )


def main():

    config = cargar_config()

    total_cumple = sum(c["cumple"] for c in CONTEOS_EJEMPLO.values())
    total_incumplimiento = sum(
        c["incumplimiento"] for c in CONTEOS_EJEMPLO.values()
    )

    logger.info(
        f"[PRUEBA] Cumplimientos: {total_cumple} | "
        f"Incumplimientos: {total_incumplimiento}"
    )

    output_path = "reporte_semanal_prueba.png"
    generar_grafica(CONTEOS_EJEMPLO, output_path)

    mensaje = (
        "📊 *Resumen de la semana*\n"
        f"Número de Cumplimientos: {total_cumple}\n"
        f"Número de Incumplimientos: {total_incumplimiento}\n\n"
        "_Este conteo es un aproximado ya que el modelo no es 100% "
        "confiable._\n\n"
        "⚠️ _Este es un mensaje de PRUEBA con datos inventados._"
    )

    enviar_reporte(config["greenapi"], mensaje, output_path)


if __name__ == "__main__":
    main()