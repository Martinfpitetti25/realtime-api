# Realtime-IA - Asistente de IA en Tiempo Real 🤖

Este proyecto implementa un asistente de IA conversacional usando la API de OpenAI Realtime con capacidades de audio, visión por computadora y detección por wake word.

## 🚀 Instalación Completada

✅ **Repositorio actualizado** desde GitHub
✅ **Entorno virtual Python** configurado (`.venv/`)
✅ **Todas las dependencias** instaladas correctamente
✅ **Archivo `.env`** configurado con API keys

## 📦 Dependencias Instaladas

- websocket-client (conexión en tiempo real)
- python-dotenv (gestión de variables de entorno)
- pyaudio (procesamiento de audio)
- numpy y scipy (procesamiento numérico)
- opencv-contrib-python (visión por computadora)
- ultralytics (YOLO para detección de objetos)
- pvporcupine (detección de wake word)

## 🎯 Scripts Disponibles

### Principal
- **05_gui_chat.py** - Interfaz gráfica mejorada con wake word detection

### En Backups
- 00_test_connection.py - Test de conexión
- 01_basic_connection.py - Conexión básica
- 02_text_chat.py - Chat de texto
- 03_audio_chat.py - Chat de audio
- 04_raspberry_pi.py - Versión para Raspberry Pi
- 06_robot_assistant.py - Asistente robótico
- 07_vision_realtime.py - Visión en tiempo real

## 🏃 Cómo Ejecutar

### Ejecutar la interfaz gráfica principal:
```bash
/home/cluster/Projects/Realtime-IA/.venv/bin/python 05_gui_chat.py
```

O usando el script de inicio rápido:
```bash
./quick.sh
```

## 🔑 Configuración

El archivo `.env` ya está configurado con:
- `OPENAI_API_KEY` - Tu API key de OpenAI
- `PORCUPINE_ACCESS_KEY` - Key para wake word detection (opcional)

Para obtener un access key gratuito de Porcupine: https://console.picovoice.ai/

## 📚 Documentación Adicional

- [docs/AUDIO_CONFIGURED.md](docs/AUDIO_CONFIGURED.md) - Configuración de audio
- [docs/QUICKSTART.md](docs/QUICKSTART.md) - Guía de inicio rápido
- [docs/WAKE_WORD_SETUP.md](docs/WAKE_WORD_SETUP.md) - Configuración de wake word
- [docs/MEJORAS_RECONOCIMIENTO_VOZ.md](docs/MEJORAS_RECONOCIMIENTO_VOZ.md) - Mejoras de reconocimiento de voz
- [docs/README_DOCKER.md](docs/README_DOCKER.md) - Instrucciones para Docker
- [docs/VISION_README.md](docs/VISION_README.md) - Documentación de visión

## 🐋 Docker (Opcional)

El proyecto incluye `Dockerfile` y `docker-compose.yml` para ejecución en contenedores.

```bash
docker-compose up -d
```

## 🛠️ Hardware Soportado

- Desktop/Laptop con micrófono y cámara
- Raspberry Pi (script específico incluido)
- Cualquier dispositivo Linux con Python 3.10+

## 📖 Estructura del Proyecto

```
.
├── 05_gui_chat.py           # Interfaz principal
├── requirements.txt         # Dependencias
├── .env                     # Variables de entorno
├── backups/                 # Scripts antiguos
├── docs/                    # Documentación
├── hardware/                # Servicios de hardware
├── models/                  # Modelos YOLO
├── scripts/                 # Scripts de utilidad
├── tests/                   # Tests
└── utils/                   # Utilidades
```

## 🎤 Características

- ✅ Chat de voz en tiempo real
- ✅ Reconocimiento de wake word ("jarvis", "computer", etc.)
- ✅ Visión por computadora con YOLO
- ✅ Interfaz gráfica moderna
- ✅ Soporte para Raspberry Pi
- ✅ Mejoras de audio con cancelación de ruido

## 🐛 Solución de Problemas

Si encuentras problemas con audio:
1. Verifica que PyAudio esté instalado correctamente
2. Ejecuta `./start_audio.sh` para configurar el audio
3. Revisa la documentación en `docs/AUDIO_CONFIGURED.md`

## 📝 Licencia

MIT License - Ver archivo LICENSE para detalles

---

**Nota:** Este proyecto requiere una API key válida de OpenAI para funcionar.
