"""
Vista en vivo con detecciones de EPP usando YOLOv8 (best.pt).
Permite alternar entre cámaras y ver las cajas dibujadas en pantalla.

Controles:
  [N]              -> cambia a la siguiente cámara
  [Q] o [ESC]      -> salir
"""

import cv2
import os
import torch
from ultralytics import YOLO

# ──────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────
CAMARAS = [
    {"id": "CAM-01", "nombre": "Pasillo",   "url": "rtsp://MantoGral:0123456789@192.168.0.103:554/stream2"},
    {"id": "CAM-02", "nombre": "Camra 2",   "url": "rtsp://MantoGral:0123456789@192.168.0.104:554/stream2"},
    {"id": "CAM-03", "nombre": "Camra 3",   "url": "rtsp://MantoGral:0123456789@192.168.0.106:554/stream2"}
]

# Ruta al modelo entrenado
MODEL_PATH = "ppe-detector/models/best.pt"
model = YOLO(MODEL_PATH)

# ──────────────────────────────────────────
# AJUSTES DE VELOCIDAD
# ──────────────────────────────────────────
DISPOSITIVO = "cuda" if torch.cuda.is_available() else "cpu"
print(f"\nUsando dispositivo: {DISPOSITIVO}")
if DISPOSITIVO == "cpu":
    print("No se detectó GPU — corriendo en CPU, por eso conviene bajar imgsz y saltar frames.\n")

IMGSZ = 416          # más chico = más rápido (default suele ser 640)
SALTAR_FRAMES = 5    # solo analiza 1 de cada 5 frames, el resto solo se muestra

indice_cam = 0
cap = None
contador_frames = 0
ultimo_resultado_dibujado = None


def conectar_camara(indice):
    cam = CAMARAS[indice]
    print(f"\nConectando a {cam['id']}...")
    c = cv2.VideoCapture(cam["url"], cv2.CAP_FFMPEG)
    if not c.isOpened():
        print(f"[{cam['id']}] No se pudo conectar. Revisa la URL/IP.")
    return c


cap = conectar_camara(indice_cam)

print("\nControles: [N] cambiar cámara | [Q/ESC] salir\n")

while True:
    if cap is None or not cap.isOpened():
        cap = conectar_camara(indice_cam)
        if cap is None or not cap.isOpened():
            cv2.waitKey(1000)
            continue

    ret, frame = cap.read()
    if not ret:
        print("Frame no recibido, reintentando...")
        cv2.waitKey(500)
        continue

    cam_id = CAMARAS[indice_cam]["id"]
    contador_frames += 1

    # Solo corre el modelo cada SALTAR_FRAMES frames; los demás reusan el último dibujo
    if contador_frames % SALTAR_FRAMES == 0:
        results = model(frame, imgsz=IMGSZ, device=DISPOSITIVO, verbose=False)
        ultimo_resultado_dibujado = results[0].plot()

    # Si aún no hay ningún resultado (primeros frames), usa el frame crudo
    annotated_frame = ultimo_resultado_dibujado if ultimo_resultado_dibujado is not None else frame.copy()

    # Overlay con instrucciones
    texto = f"{cam_id} | [N] cambiar cam | [Q] salir | {DISPOSITIVO.upper()}"
    cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(annotated_frame, texto, (10, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.imshow("Vista en vivo EPP", annotated_frame)

    tecla = cv2.waitKey(1) & 0xFF

    if tecla == ord('n') or tecla == ord('N'):
        if len(CAMARAS) > 1:
            cap.release()
            indice_cam = (indice_cam + 1) % len(CAMARAS)
            cap = conectar_camara(indice_cam)
            ultimo_resultado_dibujado = None
        else:
            print("Solo hay una cámara configurada.")

    elif tecla == ord('q') or tecla == ord('Q') or tecla == 27:  # ESC
        break

if cap is not None:
    cap.release()
cv2.destroyAllWindows()
print("\nSesión terminada.")