# limpiar_cola.py
import requests

GREEN_ID_INSTANCE = "710722699428"
GREEN_API_TOKEN   = "7575dcf2d14b4ca0b719c0afaede080afcb3889da1ba4f1fbd"

url = "https://7107.api.greenapi.com/waInstance{}/receiveNotification/{}".format(
    GREEN_ID_INSTANCE, GREEN_API_TOKEN
)

print("Limpiando cola...")
for i in range(15):
    r = requests.get(url, timeout=10)
    data = r.json()
    if data is None:
        print("Cola vacía.")
        break
    
    # Confirmar recepción para eliminarlo de la cola
    receipt_id = data.get("receiptId")
    if receipt_id:
        del_url = "https://7107.api.greenapi.com/waInstance{}/deleteNotification/{}/{}".format(
            GREEN_ID_INSTANCE, GREEN_API_TOKEN, receipt_id
        )
        requests.delete(del_url, timeout=10)
        print("Mensaje {} eliminado.".format(i+1))

print("Listo. Vuelve a correr el test.")