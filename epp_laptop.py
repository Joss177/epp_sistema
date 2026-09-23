# epp_laptop.py
import cv2
import time
import datetime
import os
import requests
from inference_sdk import InferenceHTTPClient

# ──────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────
TELEFONO          = "5214622528392"
COOLDOWN_SEG      = 30
CARPETA_SS        = "capturas"
CARPETA_VIDEO     = "grabaciones"
MINUTOS_POR_VIDEO = 60
DIAS_RETENCION    = 7

GREEN_ID_INSTANCE = "710722699428"
GREEN_API_TOKEN   = "7575dcf2d14b4ca0b719c0afaede080afcb3889da1ba4f1fbd"
GREEN_API_URL     = "https://7107.api.greenapi.com/waInstance" + GREEN_ID_INSTANCE

EPP_REQUERIDO = {
    "hardhat": "Casco",
    "gloves":  "Guantes",
    "goggles": "Careta",
}

CLIENT = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="38fcYXkYXgGJmJgZsYZa"
)

MODEL_ID = "personal-protective-equipment-combined-model/8"

# ──────────────────────────────────────────
# INICIALIZACIÓN
# ──────────────────────────────────────────
os.makedirs(CARPETA_SS,    exist_ok=True)
os.makedirs(CARPETA_VIDEO, exist_ok=True)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

if not cap.isOpened():
    raise RuntimeError("No se pudo abrir la camara.")

ultimo_envio = {}
predicciones = []
faltantes    = []
frame_actual = None
frame_count  = 0

# ──────────────────────────────────────────
# FUNCIONES
# ──────────────────────────────────────────
def nuevo_video_writer():
    ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path   = CARPETA_VIDEO + "/grabacion_" + ts + ".avi"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    writer = cv2.VideoWriter(path, fourcc, 20.0, (1280, 720))
    print("  Nueva grabacion iniciada: " + path)
    return writer, time.time()

def limpiar_grabaciones_viejas():
    import glob
    ahora  = time.time()
    limite = DIAS_RETENCION * 86400
    for archivo in glob.glob(CARPETA_VIDEO + "/*.avi"):
        if ahora - os.path.getmtime(archivo) > limite:
            os.remove(archivo)
            print("  Grabacion eliminada: " + archivo)

def tomar_screenshot(motivo):
    ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = CARPETA_SS + "/alerta_" + motivo + "_" + ts + ".png"
    if frame_actual is not None:
        cv2.imwrite(nombre, frame_actual)
        print("  Screenshot guardado: " + nombre)
    return nombre

def enviar_mensaje_whatsapp(mensaje):
    try:
        url   = GREEN_API_URL + "/sendMessage/" + GREEN_API_TOKEN
        chat  = TELEFONO + "@c.us"
        body  = {"chatId": chat, "message": mensaje}
        print("  Enviando mensaje a: " + chat)
        print("  URL: " + url)
        r = requests.post(url, json=body, timeout=10)
        print("  Status mensaje: " + str(r.status_code))
        print("  Respuesta: " + r.text)
        if r.status_code == 200:
            print("  Mensaje enviado correctamente.")
        else:
            print("  Error mensaje: " + str(r.status_code))
    except Exception as e:
        print("  Error enviando mensaje: " + str(e))

def enviar_imagen_whatsapp(ruta_imagen, caption=""):
    try:
        url  = GREEN_API_URL + "/sendFileByUpload/" + GREEN_API_TOKEN
        chat = TELEFONO + "@c.us"
        body = {"chatId": chat, "caption": caption}
        print("  Enviando imagen: " + ruta_imagen)
        with open(ruta_imagen, "rb") as f:
            files = {"file": (os.path.basename(ruta_imagen), f, "image/png")}
            r = requests.post(url, data=body, files=files, timeout=15)
        print("  Status imagen: " + str(r.status_code))
        print("  Respuesta: " + r.text)
        if r.status_code == 200:
            print("  Imagen enviada correctamente.")
        else:
            print("  Error imagen: " + str(r.status_code))
    except Exception as e:
        print("  Error enviando imagen: " + str(e))

def enviar_alerta(mensaje, ruta_imagen):
    enviar_mensaje_whatsapp(mensaje)
    time.sleep(3)
    enviar_imagen_whatsapp(ruta_imagen, "Captura del incidente")

# Umbral de confianza por clase (más bajo = más fácil de detectar)
CONFIANZA_POR_CLASE = {
    "hardhat": 0.5,   # Casco detecta bien, umbral normal
    "gloves":  0.15,  # Guantes detecta menos, umbral más bajo
    "goggles": 0.15,  # Careta detecta menos, umbral más bajo
}

def detectar_faltantes(preds):
    detectados = set()
    for pred in preds:
        clase = pred["class"].lower()
        umbral = CONFIANZA_POR_CLASE.get(clase, 0.3)
        if pred["confidence"] >= umbral:
            detectados.add(clase)
    return [nombre for clave, nombre in EPP_REQUERIDO.items()
            if clave not in detectados]

def dibujar_ui(frame, preds, faltantes):
    for pred in preds:
        if pred["confidence"] < 0.3:
            continue
        x = int(pred["x"] - pred["width"]  / 2)
        y = int(pred["y"] - pred["height"] / 2)
        w = int(pred["width"])
        h = int(pred["height"])
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 200, 0), 2)
        cv2.putText(frame, pred["class"] + " " + str(round(pred["confidence"]*100)) + "%",
                    (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 0), 2)

    fondo_h = len(EPP_REQUERIDO) * 30 + 10
    cv2.rectangle(frame, (0, 0), (220, fondo_h), (30, 30, 30), -1)
    for i, (clave, nombre) in enumerate(EPP_REQUERIDO.items()):
        ok    = nombre not in faltantes
        color = (0, 220, 0) if ok else (0, 60, 220)
        icono = "OK" if ok else "!!"
        cv2.putText(frame, "[" + icono + "] " + nombre,
                    (8, 25 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    cv2.putText(frame, ts, (10, frame.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    if faltantes:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, h - 45), (w, h - 25), (0, 0, 180), -1)
        cv2.putText(frame, "FALTA: " + ", ".join(faltantes),
                    (10, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    return frame

# ──────────────────────────────────────────
# BUCLE PRINCIPAL
# ──────────────────────────────────────────
print("Sistema EPP activo 24/7 - presiona 'q' para salir.")
print("URL base: " + GREEN_API_URL)
out, tiempo_inicio_video = nuevo_video_writer()
limpiar_grabaciones_viejas()

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("No se pudo leer frame. Reintentando...")
        time.sleep(0.5)
        continue

    frame_count += 1
    frame_actual = frame.copy()

    if frame_count % 10 == 0:
        try:
            temp_path = CARPETA_SS + "/temp_frame.jpg"
            cv2.imwrite(temp_path, frame)
            resultado    = CLIENT.infer(temp_path, model_id=MODEL_ID)
            predicciones = resultado.get("predictions", [])
            faltantes    = detectar_faltantes(predicciones)
        except Exception as e:
            print("  Error API: " + str(e))
            predicciones = []
            faltantes    = []

    frame = dibujar_ui(frame, predicciones, faltantes)
    out.write(frame)

    if time.time() - tiempo_inicio_video >= MINUTOS_POR_VIDEO * 60:
        out.release()
        out, tiempo_inicio_video = nuevo_video_writer()
        limpiar_grabaciones_viejas()

    cv2.imshow("EPP - Camara Laptop", frame)

    if faltantes:
        clave_alerta = "_".join(sorted(faltantes))
        ahora        = time.time()
        if ahora - ultimo_envio.get(clave_alerta, 0) >= COOLDOWN_SEG:
            ultimo_envio[clave_alerta] = ahora
            ts      = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            mensaje = (
                "ALERTA SEGURIDAD - EPP INCOMPLETO\n"
                "Ubicacion: Camara Laptop\n"
                "Hora: " + ts + "\n"
                "Faltante(s): " + ", ".join(faltantes) + "\n"
                "Por favor equipese antes de continuar."
            )
            ruta = tomar_screenshot(clave_alerta)
            enviar_alerta(mensaje, ruta)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
out.release()
cv2.destroyAllWindows()
print("Sistema detenido.")