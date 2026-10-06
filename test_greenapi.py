import os
import requests
from dotenv import load_dotenv

load_dotenv()

# URL por defecto si la instancia no define su propia GREENAPI_URL
DEFAULT_API_URL = "https://7107.api.greenapi.com"

# Cada instancia tiene sus propias credenciales y sus propios chats destino
INSTANCIAS = [
    {
        "name": "instancia_1",
        "api_url_env": "GREENAPI_URL",
        "id_instance_env": "GREENAPI_ID_INSTANCE",
        "token_env": "GREENAPI_TOKEN",
        "chat_id_envs": ["GREENAPI_CHAT_ID", "GREENAPI_CHAT_ID_2"],
    },
    {
        "name": "instancia_2",
        "api_url_env": "GREENAPI_URL_2",
        "id_instance_env": "GREENAPI_ID_INSTANCE_2",
        "token_env": "GREENAPI_TOKEN_2",
        "chat_id_envs": ["GREENAPI_CHAT_ID_3"],
    },
]

MENSAJE = "Prueba EPP Sistema Mensaje Automatico"


def limpiar_telefono(valor):
    """Quita el sufijo @c.us para quedarnos solo con el número."""
    return valor.replace("@c.us", "").strip()


for inst in INSTANCIAS:
    name = inst["name"]

    api_url = os.getenv(inst["api_url_env"]) or DEFAULT_API_URL
    id_instance = os.getenv(inst["id_instance_env"])
    token = os.getenv(inst["token_env"])

    if not id_instance or not token:
        print("[{}] Faltan ID o TOKEN en el .env. Se omite.".format(name))
        continue

    telefonos = [
        limpiar_telefono(os.getenv(env))
        for env in inst["chat_id_envs"]
        if os.getenv(env)
    ]

    if not telefonos:
        print("[{}] No hay chats configurados. Se omite.".format(name))
        continue

    url = "{}/waInstance{}/sendMessage/{}".format(
        api_url.rstrip("/"), id_instance, token
    )

    print("[{}] URL configurada correctamente".format(name))

    for telefono in telefonos:
        body = {
            "chatId": "{}@c.us".format(telefono),
            "message": "{} ({})".format(MENSAJE, name),
        }

        try:
            r = requests.post(url, json=body, timeout=10)
            print("[{}][{}] Status: {}".format(name, telefono, r.status_code))
            print("[{}][{}] Respuesta: {}".format(name, telefono, r.text))
        except requests.RequestException as error:
            print("[{}][{}] Error: {}".format(name, telefono, error))