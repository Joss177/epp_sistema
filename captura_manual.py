"""
Captura manual con vista en vivo — para armar el dataset de guantes.

Controles (con la ventana de video seleccionada):
  [ESPACIO] o [C]  -> guarda una foto
  [N]              -> cambia a la siguiente cámara (si configuraste varias)
  [Q] o [ESC]      -> salir

Las fotos se guardan en dataset_capturas/ con nombre único (cámara + fecha/hora),
para que no se sobreescriban entre sesiones.
"""

import cv2
import os
import datetime

# ──────────────────────────────────────────
# CONFIGURACIÓN — AJUSTA ESTO
# ──────────────────────────────────────────
# Tip para cámaras Tapo: la URL suele ser
#   rtsp://USUARIO:PASSWORD@IP_CAMARA:554/stream1   (calidad alta)
#   rtsp://USUARIO:PASSWORD@IP_CAMARA:554/stream2   (calidad baja, más fluido)
CAMARAS = [
    {"id": "CAM-01", "nombre": "Pasillo",   "url": "rtsp://MantoGral:0123456789@192.168.0.103:554/stream1"},
    {"id": "CAM-02", "nombre": "Camra 2",   "url": "rtsp://MantoGral:0123456789@192.168.0.104:554/stream1"},
    {"id": "CAM-03", "nombre": "Camra 3",   "url": "rtsp://MantoGral:0123456789@192.168.0.106:554/stream1"}
    # Agrega CAM-03 y CAM-04 aquí si también las vas a usar
]

CARPETA_DATASET = "dataset_capturas_07"
os.makedirs(CARPETA_DATASET, exist_ok=True)

# ──────────────────────────────────────────
# LÓGICA
# ──────────────────────────────────────────
indice_cam = 0
cap = None
contador_total = 0


def conectar_camara(indice):
    cam = CAMARAS[indice]
    print(f"\nConectando a {cam['id']}...")
    c = cv2.VideoCapture(cam["url"], cv2.CAP_FFMPEG)
    if not c.isOpened():
        print(f"[{cam['id']}] No se pudo conectar. Revisa la URL/IP.")
    return c


cap = conectar_camara(indice_cam)

print("\nControles: [ESPACIO/C] capturar | [N] siguiente cámara | [Q/ESC] salir\n")

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

    # Overlay con instrucciones y contador, para saber qué está pasando sin ver la consola
    vista = frame.copy()
    texto = f"{cam_id} | Capturas: {contador_total} | [ESPACIO] capturar  [N] cambiar cam  [Q] salir"
    cv2.rectangle(vista, (0, 0), (vista.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(vista, texto, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.imshow("Captura de dataset", vista)

    tecla = cv2.waitKey(1) & 0xFF

    if tecla == ord(' ') or tecla == ord('c') or tecla == ord('C'):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        nombre = f"{CARPETA_DATASET}/{cam_id}_{ts}.jpg"
        cv2.imwrite(nombre, frame)  # guarda el frame limpio, sin el overlay de texto
        contador_total += 1
        print(f"Guardado: {nombre}  (total: {contador_total})")

    elif tecla == ord('n') or tecla == ord('N'):
        if len(CAMARAS) > 1:
            cap.release()
            indice_cam = (indice_cam + 1) % len(CAMARAS)
            cap = conectar_camara(indice_cam)
        else:
            print("Solo hay una cámara configurada.")

    elif tecla == ord('q') or tecla == ord('Q') or tecla == 27:  # ESC
        break

if cap is not None:
    cap.release()
cv2.destroyAllWindows()
print(f"\nSesión terminada. Total capturado: {contador_total} fotos en {CARPETA_DATASET}/")