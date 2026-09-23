# Detección de EPP - Cervecería Pacífico

Sistema que monitorea cámaras IP TP-Link, detecta si un empleado no trae
casco, botas o guantes, y manda una alerta por WhatsApp (vía GreenAPI) con
foto de evidencia.

## 1. Instalación

```bash
cd ppe-detector
python -m venv venv
source venv/bin/activate       # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Obtener las URLs RTSP de tus cámaras TP-Link

Para cámaras **Tapo** (C200, C210, C310, etc.):
1. Abre la app Tapo → tu cámara → Configuración avanzada → Cuenta de cámara
2. Crea un usuario/contraseña específico para RTSP (distinto al de la app)
3. La URL queda: `rtsp://usuario:password@IP_CAMARA:554/stream1` (HD) o `/stream2` (SD)

Para cámaras **VIGI** (línea profesional):
1. Desde el software VIGI o la interfaz web de la cámara, activa RTSP
2. Mismo formato de URL: `rtsp://usuario:password@IP_CAMARA:554/stream1`

**Recomendación:** usa `/stream2` (SD) para no saturar tu CPU sin GPU — la
resolución baja es más que suficiente para detectar EPP a la distancia
típica de una cámara de vigilancia.

Para confirmar que la URL funciona antes de correr el sistema completo:
```bash
ffplay rtsp://usuario:password@192.168.1.101:554/stream2
```
(o ábrela directo en VLC: Medio → Abrir ubicación de red)

## 3. Conseguir un modelo de EPP

YOLO estándar NO detecta cascos/botas/guantes de fábrica. Tienes 2 opciones:

**Opción A (rápida, para probar el sistema ya):**
Busca en [Roboflow Universe](https://universe.roboflow.com/) proyectos
públicos de "PPE detection" o "construction safety" — hay varios con casco,
chaleco, guantes y botas ya entrenados. Descargas el `.pt` y lo colocas en
`models/ppe_model.pt`.

**Opción B (recomendada para producción):**
Fine-tunear un modelo con fotos reales de tus empleados y uniformes de
Pacífico. Con 200-500 fotos etiquetadas por clase normalmente ya se logra
buena precisión. Roboflow tiene herramienta de etiquetado gratuita para
proyectos chicos. Si llegas a este punto te ayudo con el script de
entrenamiento (`model.train(...)`).

Una vez tengas el modelo, revisa los nombres de clase que trae:
```python
from ultralytics import YOLO
model = YOLO("models/ppe_model.pt")
print(model.names)
```
Y ajusta el diccionario `CLASS_NAME_MAP` en `src/ppe_detector.py` para que
coincida con los nombres reales de tu modelo.

## 4. Configurar `config.yaml`

- Pon las URLs RTSP reales de tus cámaras
- Completa `id_instance` y `api_token_instance` de tu cuenta GreenAPI
- Pon el `chat_id` de WhatsApp destino (formato `521XXXXXXXXXX@c.us` para un
  número, o `XXXXXXXXX@g.us` si prefieres mandarlo a un grupo)

## 5. Correr el sistema

```bash
cd src
python main.py
```

Verás logs en consola cada vez que detecta incumplimiento sostenido. Las
fotos de evidencia quedan en `data/snapshots/` y el historial completo en
`data/events.db` (SQLite — lo puedes abrir con DB Browser for SQLite si
quieres revisar/exportar reportes).

## Notas de rendimiento (CPU sin GPU)

- `frame_skip: 10` en `config.yaml` significa que solo se analiza 1 de
  cada 10 ciclos (~1 análisis por segundo con el loop actual). Si tu laptop
  va lenta, sube este número; si va sobrada, bájalo para reaccionar más rápido.
- El modelo `yolov8n` (nano) es el más liviano de la familia YOLO — si tu
  modelo de EPP está basado en uno más grande (`s`, `m`, `l`), considera
  re-entrenar sobre `yolov8n` para más velocidad en CPU.
- Con 2-3 cámaras y resolución SD, una laptop de oficina normal (i5/Ryzen 5,
  8GB RAM) debería sostener esto sin problema.

## Próximos pasos sugeridos

- [ ] Dashboard web simple para ver eventos históricos (puedo armarlo cuando quieras)
- [ ] Reportes automáticos semanales (ej. enviarse un resumen los viernes)
- [ ] Diferenciar por empleado si agregan reconocimiento facial o gafetes (opcional, tiene implicaciones de privacidad a considerar)
