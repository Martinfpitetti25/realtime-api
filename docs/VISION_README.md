# 🤖 Robot Assistant - Realtime API + Visión

Integración de OpenAI Realtime API con visión por computadora (YOLO + MediaPipe).

## ✨ Características

- ✅ **Audio bidireccional en tiempo real** (OpenAI Realtime API)
- ✅ **Detección de objetos** con YOLOv8 (80 clases)
- ✅ **Contexto visual automático** enviado al LLM cada 5 segundos
- ✅ **Optimizado para bajo CPU** (3 FPS en detección)
- ✅ **Conversación natural** con awareness visual

## 📋 Requisitos

- Python 3.8+
- Cámara USB o webcam
- Micrófono y altavoces
- OpenAI API Key con acceso a Realtime API

## 🚀 Instalación Rápida

### 1. Instalar dependencias

```bash
# Activar entorno virtual
source .venv/bin/activate  # o venv/bin/activate

# Instalar nuevas dependencias
pip install opencv-contrib-python ultralytics mediapipe

# O instalar todo
pip install -r requirements.txt
```

**Nota:** La primera vez que ejecutes el código, YOLO descargará el modelo (~6MB).

### 2. Verificar cámara

```bash
# Test rápido de cámara + YOLO
python hardware/camera_service.py
```

Deberías ver:
- ✅ Ventana con video de tu cámara
- ✅ Bounding boxes alrededor de objetos detectados
- ✅ Labels con nombres de objetos

Presiona `q` para salir.

### 3. Configurar API Key

Tu archivo `.env` ya debe tener:
```bash
OPENAI_API_KEY=tu_api_key_aqui
```

## 🎯 Uso

### Ejecutar el robot con visión

```bash
python 07_vision_realtime.py
```

### Qué esperar

1. **Inicialización:**
   ```
   🎥 Inicializando hardware...
   ✅ Cámara encontrada en índice 0
   ⏳ Descargando modelo YOLO...
   ✅ Modelo YOLO cargado y listo
   🔌 Conectando a OpenAI Realtime API...
   ✅ Sesión creada
   ```

2. **Robot listo:**
   ```
   🎤 ROBOT LISTO - Habla naturalmente
   💡 El robot puede ver objetos con YOLO
   🛑 Presiona Ctrl+C para salir
   ```

3. **Conversación:**
   - Habla naturalmente, el robot te escucha
   - El robot puede ver objetos y te los describirá
   - Contexto visual se actualiza cada 5 segundos

## 💬 Ejemplos de Conversación

**Tú:** "Hola, ¿qué ves?"  
**Robot:** "Hola! Veo que hay una persona y una laptop sobre la mesa. También noto una taza cerca."

**Tú:** "¿Cuántas personas hay?"  
**Robot:** "Veo solamente una persona en este momento."

**Tú:** "¿Qué objetos hay?"  
**Robot:** "Puedo ver una laptop, una taza y algunos libros."

## ⚙️ Configuración Avanzada

### Ajustar FPS de detección

Edita `hardware/camera_service.py`:

```python
# Línea ~30
self.detection_fps = 3  # Cambiar a 5 para más actualizaciones
self.skip_frames = 10   # Cambiar a 5 para más frames procesados
```

### Ajustar frecuencia de contexto visual

Edita `07_vision_realtime.py`:

```python
# Línea ~39
self.vision_update_interval = 5.0  # Cambiar a 3.0 para cada 3 segundos
```

### Deshabilitar visión temporalmente

Edita `07_vision_realtime.py`:

```python
# Línea ~37
self.vision_enabled = False  # Desactivar detección
```

## 🐛 Troubleshooting

### Error: "No se pudo iniciar la cámara"

```bash
# Verificar cámaras disponibles
ls /dev/video*

# Probar con índice diferente
python -c "from hardware.camera_service import CameraService; c=CameraService(); c.find_camera(max_cameras=10)"
```

### Error: "YOLO no disponible"

```bash
# Descargar modelo manualmente
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

### Audio con lag o cortado

1. **Reducir FPS de YOLO:**
   ```python
   self.detection_fps = 1  # Solo 1 detección por segundo
   ```

2. **Aumentar prioridad de audio:**
   ```bash
   # Ejecutar con mayor prioridad (Linux)
   sudo nice -n -10 python 07_vision_realtime.py
   ```

### CPU muy alto

```python
# En camera_service.py, línea ~31
self.skip_frames = 20  # Procesar menos frames
```

## 📊 Rendimiento Esperado

### Raspberry Pi 5 (8GB)
- FPS cámara: 15-20
- FPS YOLO: 3
- CPU usage: 40-60%
- RAM usage: ~2GB

### PC Desktop
- FPS cámara: 30
- FPS YOLO: 5-10
- CPU usage: 20-40%
- RAM usage: ~1.5GB

## 🔧 Estructura del Proyecto

```
Realtime-IA/
├── hardware/
│   ├── __init__.py
│   └── camera_service.py      # Servicio de cámara + YOLO
├── utils/
│   ├── __init__.py
│   └── logger.py              # Logging utility
├── 07_vision_realtime.py      # ⭐ Script principal
├── requirements.txt           # Dependencias actualizadas
└── VISION_README.md           # Este archivo
```

## 🎨 Próximas Mejoras

- [ ] Seguimiento facial con MediaPipe
- [ ] Control de servos (gestos expresivos)
- [ ] Detección de emociones
- [ ] Reconocimiento de personas específicas
- [ ] Integración con smart home

## 📝 Notas Técnicas

### Cómo funciona la integración

1. **Thread de cámara:** Captura frames continuamente
2. **Thread de detección:** Procesa frames con YOLO (throttled a 3 FPS)
3. **Thread de audio input:** Captura micrófono → WebSocket
4. **Thread de audio output:** WebSocket → Altavoz
5. **Thread de visión:** Envía contexto visual cada 5s
6. **WebSocket:** Maneja eventos de Realtime API

### Formato de contexto visual

```python
{
    'vision_summary': 'I can see: 2 persons, 1 laptop, 1 cup',
    'raw_detections': [
        {'class': 'person', 'confidence': 0.87, 'bbox': [...]},
        {'class': 'laptop', 'confidence': 0.72, 'bbox': [...]},
        ...
    ],
    'object_counts': {'person': 2, 'laptop': 1, 'cup': 1}
}
```

El LLM recibe mensajes como:
```
[VISION: I can see: 2 persons, 1 laptop, 1 cup]
```

## 📄 Licencia

Mismo que el proyecto principal Realtime-IA.

## 🤝 Contribuciones

Este módulo es parte del proyecto Realtime-IA. Adaptado de Frankeinstein robot project.

---

**¿Problemas?** Abre un issue o contacta al mantenedor del proyecto.
