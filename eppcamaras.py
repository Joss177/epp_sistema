# epp_camaras_ip.py
import cv2
import time
import datetime
import os
import glob
import requests
import threading
from inference_sdk import InferenceHTTPClient

# ──────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────
COOLDOWN_SEG      = 300              # 5 minutos entre alertas
CARPETA_SS        = "capturas"
CARPETA_VIDEO     = "grabaciones"
MINUTOS_POR_VIDEO = 60
DIAS_RETENCION    = 7

GREEN_ID_INSTANCE = "710722699428"
GREEN_API_TOKEN   = "7575dcf2d14b4ca0b719c0afaede080afcb3889da1ba4f1fbd"
GREEN_API_URL     = "https://7107.api.greenapi.com/waInstance" + GREEN_ID_INSTANCE
TELEFONO          = "5218711968778"

# ── Define aquí tus cámaras IP ──────────────
# Formato: rtsp://usuario:contraseña@IP:puerto/ruta
CAMARAS = [
    {"id": "CAM-01", "nombre": "Pasillo",   "url": "rtsp://MantoGral:0123456789@192.168.0.103:554/stream1"},
    {"id": "CAM-02", "nombre": "Camra 2",   "url": "rtsp://MantoGral:0123456789@192.168.0.104:554/stream1"},
    {"id": "CAM-03", "nombre": "Camra 3",   "url": "rtsp://MantoGral:0123456789@192.168.0.106:554/stream1"}
]
 
EPP_REQUERIDO = {
    "hardhat": "Casco",
    "gloves":  "Guantes",
    "goggles": "Careta",
}

# Umbral de confianza por clase
CONFIANZA_POR_CLASE = {
    "hardhat": 0.5,
    "gloves":  0.25,
    "goggles": 0.20,
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

lock_ws     = threading.Lock()
ultimo_envio = {}

# ──────────────────────────────────────────
# FUNCIONES
# ──────────────────────────────────────────
def nuevo_video_writer(cam_id, resolucion):
    ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path   = CARPETA_VIDEO + "/" + cam_id + "_" + ts + ".avi"
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    w, h   = resolucion
    writer = cv2.VideoWriter(path, fourcc, 20.0, (w, h))
    print("[" + cam_id + "] Nueva grabacion: " + path)
    return writer, time.time()

def limpiar_grabaciones_viejas():
    ahora  = time.time()
    limite = DIAS_RETENCION * 86400
    for archivo in glob.glob(CARPETA_VIDEO + "/*.avi"):
        if ahora - os.path.getmtime(archivo) > limite:
            os.remove(archivo)
            print("Grabacion eliminada: " + archivo)

def tomar_screenshot(cam_id, frame):
    ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = CARPETA_SS + "/" + cam_id + "_alerta_" + ts + ".png"
    cv2.imwrite(nombre, frame)
    print("[" + cam_id + "] Screenshot: " + nombre)
    return nombre

def enviar_mensaje_whatsapp(cam_id, mensaje):
    try:
        url  = GREEN_API_URL + "/sendMessage/" + GREEN_API_TOKEN
        body = {"chatId": TELEFONO + "@c.us", "message": mensaje}
        r = requests.post(url, json=body, timeout=10)
        if r.status_code == 200:
            print("[" + cam_id + "] Mensaje enviado.")
        else:
            print("[" + cam_id + "] Error mensaje: " + str(r.status_code))
    except Exception as e:
        print("[" + cam_id + "] Error: " + str(e))

def enviar_imagen_whatsapp(cam_id, ruta_imagen):
    try:
        url  = GREEN_API_URL + "/sendFileByUpload/" + GREEN_API_TOKEN
        body = {"chatId": TELEFONO + "@c.us", "caption": "[" + cam_id + "] Captura del incidente"}
        with open(ruta_imagen, "rb") as f:
            files = {"file": (os.path.basename(ruta_imagen), f, "image/png")}
            r = requests.post(url, data=body, files=files, timeout=15)
        if r.status_code == 200:
            print("[" + cam_id + "] Imagen enviada.")
        else:
            print("[" + cam_id + "] Error imagen: " + str(r.status_code))
    except Exception as e:
        print("[" + cam_id + "] Error imagen: " + str(e))

def enviar_alerta(cam_id, cam_nombre, mensaje, ruta_imagen):
    with lock_ws:
        enviar_mensaje_whatsapp(cam_id, mensaje)
        time.sleep(3)
        enviar_imagen_whatsapp(cam_id, ruta_imagen)

def detectar_faltantes(preds):
    detectados = set()
    for pred in preds:
        clase   = pred["class"].lower()
        umbral  = CONFIANZA_POR_CLASE.get(clase, 0.3)
        if pred["confidence"] >= umbral:
            detectados.add(clase)
    return [nombre for clave, nombre in EPP_REQUERIDO.items()
            if clave not in detectados]

def dibujar_ui(frame, preds, faltantes, cam_nombre):
    # Bounding boxes
    for pred in preds:
        clase  = pred["class"].lower()
        umbral = CONFIANZA_POR_CLASE.get(clase, 0.3)
        if pred["confidence"] < umbral:
            continue
        x = int(pred["x"] - pred["width"]  / 2)
        y = int(pred["y"] - pred["height"] / 2)
        w = int(pred["width"])
        h = int(pred["height"])
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 200, 0), 2)
        cv2.putText(frame, pred["class"] + " " + str(round(pred["confidence"]*100)) + "%",
                    (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 0), 2)

    # Panel EPP
    fondo_h = len(EPP_REQUERIDO) * 30 + 10
    cv2.rectangle(frame, (0, 0), (220, fondo_h), (30, 30, 30), -1)
    for i, (clave, nombre) in enumerate(EPP_REQUERIDO.items()):
        ok    = nombre not in faltantes
        color = (0, 220, 0) if ok else (0, 60, 220)
        icono = "OK" if ok else "!!"
        cv2.putText(frame, "[" + icono + "] " + nombre,
                    (8, 25 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

    # Nombre de camara
    h_frame, w_frame = frame.shape[:2]
    cv2.rectangle(frame, (w_frame - 240, 0), (w_frame, 30), (30, 30, 30), -1)
    cv2.putText(frame, cam_nombre, (w_frame - 235, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)

    # Timestamp
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    cv2.putText(frame, ts, (10, h_frame - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    # Barra roja
    if faltantes:
        cv2.rectangle(frame, (0, h_frame - 45), (w_frame, h_frame - 25), (0, 0, 180), -1)
        cv2.putText(frame, "FALTA: " + ", ".join(faltantes),
                    (10, h_frame - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    return frame

# ──────────────────────────────────────────
# HILO POR CAMARA
# ──────────────────────────────────────────
def procesar_camara(camara):
    cam_id     = camara["id"]
    cam_nombre = camara["nombre"]
    cam_url    = camara["url"]

    print("[" + cam_id + "] Conectando a " + cam_url + "...")
    cap = cv2.VideoCapture(cam_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(7,0)

    if not cap.isOpened():
        print("[" + cam_id + "] No se pudo conectar. Verifica IP, usuario y contrasena.")
        return

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if w == 0 or h == 0:
        w, h = 1280, 720

    print("[" + cam_id + "] Conectado — " + cam_nombre + " (" + str(w) + "x" + str(h) + ")")

    out, tiempo_inicio_video = nuevo_video_writer(cam_id, (w, h))
    limpiar_grabaciones_viejas()

    predicciones = []
    faltantes    = []
    frame_count  = 0
    reintentos   = 0
    ventana      = "EPP | " + cam_id + " - " + cam_nombre

    while True:
        ret, frame = cap.read()

        if not ret:
            reintentos += 1
            print("[" + cam_id + "] Frame perdido (intento " + str(reintentos) + "). Reconectando...")
            cap.release()
            time.sleep(3)
            cap = cv2.VideoCapture(cam_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if reintentos >= 10:
                print("[" + cam_id + "] Demasiados fallos. Hilo detenido.")
                break
            continue

        reintentos  = 0
        frame_count += 1

        # API cada 10 frames
        if frame_count % 10 == 0:
            try:
                temp_path = CARPETA_SS + "/" + cam_id + "_temp.jpg"
                cv2.imwrite(temp_path, frame)
                resultado    = CLIENT.infer(temp_path, model_id=MODEL_ID)
                predicciones = resultado.get("predictions", [])
                faltantes    = detectar_faltantes(predicciones)
            except Exception as e:
                print("[" + cam_id + "] Error API: " + str(e))
                predicciones = []
                faltantes    = []

        frame = dibujar_ui(frame, predicciones, faltantes, cam_nombre)
        out.write(frame)

        # Partir video
        if time.time() - tiempo_inicio_video >= MINUTOS_POR_VIDEO * 60:
            out.release()
            out, tiempo_inicio_video = nuevo_video_writer(cam_id, (w, h))
            limpiar_grabaciones_viejas()

        cv2.imshow(ventana, frame)

        # Alerta
        if faltantes:
            clave_alerta = cam_id + "_" + "_".join(sorted(faltantes))
            ahora        = time.time()
            if ahora - ultimo_envio.get(clave_alerta, 0) >= COOLDOWN_SEG:
                ultimo_envio[clave_alerta] = ahora
                ts      = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                mensaje = (
                    "ALERTA SEGURIDAD - EPP INCOMPLETO\n"
                    "Ubicacion: " + cam_nombre + " (" + cam_id + ")\n"
                    "Hora: " + ts + "\n"
                    "Faltante(s): " + ", ".join(faltantes) + "\n"
                    "Por favor equipese antes de continuar."
                )
                ruta = tomar_screenshot(cam_id, frame)
                threading.Thread(
                    target=enviar_alerta,
                    args=(cam_id, cam_nombre, mensaje, ruta),
                    daemon=True
                ).start()

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    out.release()
    cv2.destroyWindow(ventana)
    print("[" + cam_id + "] Hilo detenido.")

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("Sistema EPP IP iniciado - " + str(len(CAMARAS)) + " camara(s).")
    hilos = []
    for camara in CAMARAS:
        hilo = threading.Thread(
            target=procesar_camara,
            args=(camara,),
            daemon=True,
            name=camara["id"]
        )
        hilo.start()
        hilos.append(hilo)

    for hilo in hilos:
        hilo.join()

    cv2.destroyAllWindows()
    print("Sistema detenido.")