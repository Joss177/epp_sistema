import os
import requests
from dotenv import load_dotenv

load_dotenv()

GREEN_ID_INSTANCE = os.getenv("GREENAPI_ID_INSTANCE")
GREEN_API_TOKEN = os.getenv("GREENAPI_TOKEN")

TELEFONOS = [
    os.getenv("GREENAPI_CHAT_ID").replace("@c.us", "")
]

url = "https://7107.api.greenapi.com/waInstance{}/sendMessage/{}".format(
    GREEN_ID_INSTANCE, GREEN_API_TOKEN
)

print("URL configurada correctamente")

for telefono in TELEFONOS:
    body = {
        "chatId": "{}@c.us".format(telefono),
        "message": "Prueba EPP Sistema Mensaje Automatico"
    }

    r = requests.post(url, json=body, timeout=10)

    print("[{}] Status: {}".format(telefono, r.status_code))
    print("[{}] Respuesta: {}".format(telefono, r.text))