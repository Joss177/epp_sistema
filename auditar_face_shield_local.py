"""
Auditoría LOCAL: revisa qué imágenes de face_shield_down/up el modelo
clasifica mal, usando el best.pt que ya descargaste de Colab.

Antes de correr:
1. Coloca best.pt en la ruta que pongas en MODEL_PATH
2. Descarga el .zip de tu dataset desde Roboflow (formato YOLOv8) y
   descomprímelo, apunta CARPETA_VALID a la subcarpeta valid/images
"""

import os
import cv2
from ultralytics import YOLO

MODEL_PATH = "ppe-detector/models/best.pt"          # ajusta si tu archivo está en otra ruta
CARPETA_VALID = "ppe-detector/models/epp-deteccion-v4.v4-dataset03.yolov8/test/images"         # ajusta a donde descomprimiste el dataset

modelo = YOLO(MODEL_PATH)

imagenes = [f for f in os.listdir(CARPETA_VALID) if f.lower().endswith((".jpg", ".png", ".jpeg"))]
print(f"Revisando {len(imagenes)} imágenes de validación...\n")

os.makedirs("revision_face_shield_test", exist_ok=True)

for img_nombre in imagenes:
    ruta = os.path.join(CARPETA_VALID, img_nombre)
    resultado = modelo.predict(ruta, conf=0.25, verbose=False)[0]

    clases_detectadas = [modelo.names[int(box.cls)] for box in resultado.boxes]

    if "face_shield_up" in clases_detectadas or "face_shield_down" in clases_detectadas:
        print(f"📷 {img_nombre}")
        for box in resultado.boxes:
            clase = modelo.names[int(box.cls)]
            conf = float(box.conf)
            if "face_shield" in clase:
                print(f"   → {clase}: {conf:.2f}")

        anotada = resultado.plot()
        salida = f"revision_face_shield/{img_nombre}"
        cv2.imwrite(salida, anotada)
        print(f"   Guardado en: {salida}\n")

print("Listo. Revisa la carpeta 'revision_face_shield/' y compárala con cómo etiquetaste cada foto original en Roboflow.")