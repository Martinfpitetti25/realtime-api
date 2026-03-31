# 🤖 Realtime-IA: Asistente de Voz Inteligente con Visión

Sistema de asistente de voz multimodal que combina **OpenAI Realtime API** con **visión por computadora** para crear un asistente que puede ver, escuchar y hablar contigo en tiempo real.

## ✨ Características Principales

### 🎙️ Wake Word Detection (Nuevo!)
- **Activación por voz** con palabras clave: "Jarvis", "Alexa", "Computer"
- Detección offline con **Porcupine** (latencia <100ms)
- Confirmación auditiva personalizable: "Estoy aquí"
- Solo activo en **Modo Voz** (modo texto no afectado)
- Plan gratuito: 3,000 detecciones/mes
- Ver guía completa: [WAKE_WORD_SETUP.md](WAKE_WORD_SETUP.md)

### Audio Profesional 🎙️
- **PipeWire** con latencia ultra-baja (2-5ms)
- Soporte completo para **audio Bluetooth** (A2DP, AAC, aptX)
- Procesamiento en tiempo real con AGC optimizado
- Pre-énfasis para frecuencias de voz (300-3400 Hz)
- Noise gate ultra-rápido (3ms attack)
- Anti-clipping inteligente
- Selector de dispositivos en GUI
- Guardado de preferencias de audio
- Interrupción inteligente de conversación
- Feedback visual en tiempo real

### Visión por Computadora 👁️
- **Sistema Híbrido Dual:**
  - YOLO (gratis) para detección continua de objetos
  - GPT-4 Vision (bajo demanda) para análisis detallado
- Detección de 80 tipos de objetos en tiempo real
- Cache inteligente que ahorra **80% de costos**
- Análisis automático cuando la escena cambia

### Interfaz Gráfica Completa 🖥️
- GUI con Tkinter profesional
- Preview de cámara en vivo
- Visualización de detecciones YOLO
- **Panel de estado con indicadores visuales**
- **Barras de volumen animadas**
- Configuración de dispositivos de audio
- Control manual/automático
- Estadísticas de costos en tiempo real

### Optimizaciones 💰
- Reducción de 70-80% en costos de API
- Gestión inteligente de memoria
- Sin memory leaks
- FPS optimizado para bajo consumo
- Rendimiento optimizado en Raspberry Pi

## 📋 Requisitos

- Python 3.8 o superior
- API Key de OpenAI con acceso a Realtime API
- Micrófono y altavoces
- Cámara web (opcional, para visión)
- Linux/Raspberry Pi (audio optimizado para Linux)

## 🚀 Inicio Rápido

### Instalación (una sola vez)

#### En Linux/Raspberry Pi

```bash
# 1. Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependencias del sistema (PipeWire para audio)
sudo apt-get update
sudo apt-get install -y pipewire pipewire-audio-client-libraries \
    pipewire-alsa pipewire-pulse wireplumber libspa-0.2-bluetooth

# 3. Habilitar servicios de audio
systemctl --user --now enable pipewire pipewire-pulse wireplumber

# 4. Instalar dependencias Python
pip install -r requirements.txt

# 5. Configurar API Key
cp .env.example .env
nano .env  # Agregar tu OPENAI_API_KEY
```

#### En Windows

```bash
# 1. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar API Key
copy .env.example .env
# Editar .env y agregar tu OPENAI_API_KEY

# 4. (Opcional) Configurar Wake Word Detection
# Obtén tu Porcupine Access Key gratis en: https://console.picovoice.ai/
# Agrégala al archivo .env como: PORCUPINE_ACCESS_KEY=tu_key_aqui
# Ver guía completa en WAKE_WORD_SETUP.md
```

⚠️ **Importante:** Usa una API key que empiece con `sk-` (no `tsk-proj-`) y que tenga acceso a Realtime API.

Obtén tu key en: https://platform.openai.com/api-keys

---

### Ejecutar el Programa

#### Inicio Rápido con Bluetooth (Linux/Raspberry Pi)

```bash
# Script automático que conecta Bluetooth y muestra menú
./start_audio.sh
```

#### Inicio Manual

```bash
# Activar entorno virtual
source .venv/bin/activate  # Linux/Mac
# o
.venv\Scripts\activate     # Windows

# Menú interactivo (recomendado)
./scripts/start.sh

# O ejecutar directamente un ejemplo
python 05_gui_chat.py      # GUI completo
python 07_vision_realtime.py  # Con visión
```

---

## 📚 Ejemplos Progresivos

El proyecto incluye 8 ejemplos que van de básico a avanzado:

| Archivo | Descripción | Nivel |
|---------|-------------|-------|
| `00_test_connection.py` | Verificar API key y conexión | ⭐ Básico |
| `01_basic_connection.py` | Ver eventos de la API | ⭐ Básico |
| `02_text_chat.py` | Chat de texto simple | ⭐⭐ Intermedio |
| `03_audio_chat.py` | Audio bidireccional | ⭐⭐ Intermedio |
| `04_raspberry_pi.py` | Adaptación para RPi | ⭐⭐ Intermedio |
| `05_gui_chat.py` | **GUI completo con Tkinter** | ⭐⭐⭐ Avanzado |
| `06_robot_assistant.py` | Procesamiento avanzado de audio | ⭐⭐⭐ Avanzado |
| `07_vision_realtime.py` | **Visión + Audio + LLM completo** | ⭐⭐⭐⭐ Experto |

### Recomendados para Empezar

- **Solo probar:** `00_test_connection.py`
- **Chat básico:** `02_text_chat.py`
- **Experiencia completa:** `05_gui_chat.py`
- **Con visión:** `07_vision_realtime.py` (requiere cámara)

---

## 🗂️ Estructura del Proyecto

```
Realtime-IA/
├── 00-07_*.py          # Ejemplos progresivos
├── hardware/           # Servicios de cámara y visión
│   ├── camera_service.py      # YOLO + detección
│   └── gpt4_vision_service.py # GPT-4V integración
├── utils/              # Utilidades compartidas
│   ├── logger.py              # Sistema de logging
│   └── audio_enhancer.py      # Procesamiento de audio
├── models/             # Modelos YOLO pre-entrenados
│   ├── yolov8n.pt
│   └── yolov8m.pt
├── scripts/            # Scripts de instalación
│   ├── start.sh               # Menú interactivo
│   ├── install_vision.sh      # Instalar dependencias de visión
│   └── quickstart_vision.sh   # Inicio rápido visión
├── tests/              # Tests de verificación
├── docs/               # Documentación técnica detallada
├── backups/            # Archivos de respaldo (no versionados)
├── .env                # Configuración (no versionado)
├── .gitignore          # Archivos ignorados
├── requirements.txt    # Dependencias Python
├── README.md           # Este archivo
├── QUICKSTART.md       # Guía de inicio rápido
└── VISION_README.md    # Documentación de visión
```

---

## 💰 Costos y Modelos

### Modelos Disponibles
- `gpt-4o-realtime-preview` - Modelo principal (más potente)
- `gpt-4o-realtime-preview-mini` - Versión económica ⭐ **Recomendado**

### Precios Realtime API (por 1M tokens)
- **Entrada audio:** $100
- **Entrada texto:** $5
- **Entrada en caché:** $1.25
- **Salida audio:** $200
- **Salida texto:** $20

### Precios GPT-4 Vision (por imagen)
- **Análisis de imagen:** ~$0.01 USD
- **Con cache (< 6s):** $0.00 (gratis)

### Ahorro con Optimizaciones
- **Cache inteligente:** 70-80% reducción
- **Sistema híbrido:** YOLO gratis + GPT-4V bajo demanda
- **Costo estimado (1 hora uso normal):** $0.06 - $0.20

---

## 📖 Documentación

### Documentos Principales
- **[README.md](README.md)** (este archivo) - Introducción y guía de inicio
- **[QUICKSTART.md](QUICKSTART.md)** - Guía rápida de instalación y uso
- **[VISION_README.md](VISION_README.md)** - Documentación completa de visión

### Documentación Técnica ([docs/](docs/))
- [ANALISIS_COMPLETO.md](docs/ANALISIS_COMPLETO.md) - Análisis técnico del proyecto
- [HYBRID_SYSTEM.md](docs/HYBRID_SYSTEM.md) - Sistema híbrido de visión YOLO + GPT-4V
- [MEMORY_OPTIMIZATION.md](docs/MEMORY_OPTIMIZATION.md) - Optimizaciones de memoria
- [AUDIO_IMPROVEMENTS.md](docs/AUDIO_IMPROVEMENTS.md) - Mejoras de audio profesional
- [MEJORAS_IMPLEMENTADAS.md](docs/MEJORAS_IMPLEMENTADAS.md) - Top 3 mejoras
- [INTEGRATION_SUMMARY.md](docs/INTEGRATION_SUMMARY.md) - Resumen de integración

---

## 🔧 Configuración Avanzada

### Configuración de Audio (Linux/RPi con PipeWire)

**Ver documentación completa:** [docs/AUDIO_SETUP.md](docs/AUDIO_SETUP.md)

#### Verificar Sistema de Audio

```bash
# Test completo de audio
source .venv/bin/activate
python test_audio_simple.py

# Ver dispositivos PipeWire
pw-cli list-objects | grep -E "(node.name|device.description)"

# Estado de servicios
systemctl --user status pipewire pipewire-pulse wireplumber
```

#### Conectar Bluetooth

```bash
# Listar dispositivos emparejados
bluetoothctl devices

# Conectar (ejemplo con JBL)
bluetoothctl connect 54:15:89:F9:1B:E1

# Confiar para auto-reconexión
bluetoothctl trust 54:15:89:F9:1B:E1
```

#### Seleccionar Dispositivos en GUI

1. Ejecuta `05_gui_chat.py`
2. Click en botón **🎧 Audio**
3. Selecciona micrófono y parlantes
4. Click **💾 Guardar y Cerrar**
5. Las preferencias se guardan en `.audio_config`

**Recomendación:** Usa siempre el dispositivo **"pipewire (PipeWire - Recomendado)"** para latencia mínima.

### Configuración de Visión

Ver [VISION_README.md](VISION_README.md) para configuración detallada de:
- Umbral de detección
- Refresh automático
- Keywords de activación
- Configuración de cámara

---

## ❓ Solución de Problemas

### Error de API Key
```
❌ Error: Invalid API key
```
**Solución:** Verifica que tu API key en `.env` sea válida y empiece con `sk-`

### Audio no funciona (Linux/RPi)
```
❌ No se detectan dispositivos de audio
```
**Solución:**
```bash
# 1. Verificar PipeWire
systemctl --user status pipewire

# 2. Si no está activo, iniciarlo
systemctl --user start pipewire pipewire-pulse wireplumber

# 3. Si tienes Bluetooth, conectarlo
bluetoothctl connect <MAC_ADDRESS>

# 4. Ejecutar test
python test_audio_simple.py
```

### Error de Audio en Linux (antiguo)
```
❌ Error: No se encuentra el dispositivo de audio
```
**Solución:**
```bash
sudo apt-get install portaudio19-dev python3-dev
pip install --upgrade pyaudio
```

### Error de Cámara
```
❌ Error: Cannot open camera
```
**Solución:**
```bash
# Verificar cámaras disponibles
ls -l /dev/video*

# Probar con OpenCV
python -c "import cv2; cap = cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL')"
```

### PyAudio en Windows
Si tienes problemas instalando PyAudio:
```bash
pip install pipwin
pipwin install pyaudio
```

O descarga el wheel desde: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

### Memory Leaks
El proyecto ya tiene optimizaciones anti-memory-leak. Si experimentas alto uso de RAM:
- Reinicia el programa periódicamente
- Reduce FPS de cámara en el código
- Desactiva la ventana de preview si no la necesitas

---

## 🎯 Roadmap y Mejoras Futuras

### En Desarrollo
- [ ] Selector de dispositivos de audio en GUI
- [ ] Persistencia de configuración de audio
- [ ] Control por gestos con MediaPipe
- [ ] Indicador visual de "está escuchando"

### Planeado
- [ ] Integración con servos/motores
- [ ] Sistema de comandos personalizados
- [ ] Dashboard de estadísticas
- [ ] Modo offline con modelos locales

### Contribuciones
¡Las contribuciones son bienvenidas! Por favor abre un issue primero para discutir cambios mayores.

---

## 📄 Licencia

MIT License - Ver archivo LICENSE para detalles

---

## 🔗 Recursos

- [Documentación oficial OpenAI Realtime](https://platform.openai.com/docs/guides/realtime)
- [API Reference](https://platform.openai.com/docs/api-reference/realtime)
- [Modelos Disponibles](https://platform.openai.com/docs/models)
- [Ultralytics YOLO](https://docs.ultralytics.com/)

---

## 👨‍💻 Autor

Proyecto desarrollado como demostración de integración multimodal con OpenAI Realtime API.

Para soporte o preguntas, abre un issue en el repositorio.
