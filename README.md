# OpenAI Realtime API - Ejemplos en Python

Este proyecto contiene ejemplos para usar la API de GPT Realtime Mini de OpenAI, tanto para pruebas en Windows como para implementación en Raspberry Pi.

## Características

- ✅ Conexión básica a la API via WebSocket
- ✅ Envío de mensajes de texto y recepción de respuestas
- ✅ Captura de audio desde micrófono (para Raspberry Pi)
- ✅ Reproducción de audio de respuestas

## Requisitos

- Python 3.8 o superior
- API Key de OpenAI con acceso a la API Realtime
- Micrófono y altavoces (para los ejemplos con audio)

## Instalación

### En Windows

1. Clona o descarga este repositorio
2. Crea un entorno virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Copia el archivo `.env.example` a `.env` y agrega tu API key:
   ```bash
   copy .env.example .env
   ```
5. Edita `.env` y agrega tu OPENAI_API_KEY

### En Raspberry Pi

1. Clona este repositorio:
   ```bash
   git clone [url_del_repo]
   cd realtime-api
   ```
2. Instala las dependencias del sistema:
   ```bash
   sudo apt-get update
   sudo apt-get install portaudio19-dev python3-pyaudio
   ```
3. Crea un entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
4. Instala las dependencias de Python:
   ```bash
   pip install -r requirements.txt
   ```
5. Configura tu API key:
   ```bash
   cp .env.example .env
   nano .env  # Edita y agrega tu API key
   ```

## Uso

### 0. Test de Conexión (¡EMPIEZA AQUÍ!)

Primero verifica que tu API key funciona:

```bash
python 00_test_connection.py
```

### 1. Ejemplo Básico (solo conexión)

Ve todos los eventos que envía la API:

```bash
python 01_basic_connection.py
```

### 2. Ejemplo con Texto

Envía mensajes de texto y recibe respuestas:

```bash
python 02_text_chat.py
```

### 3. Ejemplo con Audio

Usa tu micrófono para hablar con el asistente:

```bash
python 03_audio_chat.py
```

**Nota**: En Windows, PyAudio puede requerir instalación especial. Si tienes problemas, usa solo el chat de texto.

## Modelos Disponibles

- `gpt-realtime` - Modelo principal
- `gpt-realtime-mini` - Versión más económica (recomendada para pruebas)

## Precios (por 1M tokens)

- **Entrada**: $0.60
- **Entrada en caché**: $0.06
- **Salida**: $2.40

## Recursos

- [Documentación oficial](https://platform.openai.com/docs/guides/realtime)
- [Modelos Realtime](https://platform.openai.com/docs/models/gpt-realtime-mini)
- [API Reference](https://platform.openai.com/docs/api-reference/realtime)

## Solución de Problemas

### Error de conexión
- Verifica que tu API key sea válida
- Asegúrate de tener acceso a la API Realtime en tu cuenta

### Error de audio en Raspberry Pi
- Verifica que el micrófono esté conectado: `arecord -l`
- Verifica que los altavoces funcionen: `speaker-test`
- Ajusta el dispositivo de audio en el código si es necesario

### PyAudio en Windows
Si tienes problemas instalando PyAudio en Windows:
```bash
pip install pipwin
pipwin install pyaudio
```

O descarga el wheel pre-compilado desde: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

## Para usar en Raspberry Pi

### Hardware recomendado
- Raspberry Pi 3B+ o superior
- Micrófono USB o módulo I2S
- Altavoces o auriculares
- Conexión a Internet estable

### Configuración de audio en Raspberry Pi

1. **Verifica dispositivos de audio**:
```bash
# Listar dispositivos de grabación
arecord -l

# Listar dispositivos de reproducción
aplay -l
```

2. **Prueba el micrófono**:
```bash
# Graba 5 segundos de audio
arecord -D hw:1,0 -d 5 -f cd test.wav

# Reproduce la grabación
aplay test.wav
```

3. **Configura el volumen**:
```bash
alsamixer
```

4. **Si usas micrófono USB**, puede ser necesario configurarlo como predeterminado:
```bash
# Edita /etc/asound.conf o ~/.asoundrc
pcm.!default {
    type hw
    card 1
}

ctl.!default {
    type hw
    card 1
}
```

### Auto-inicio en Raspberry Pi

Para que el script se ejecute al encender la Raspberry Pi:

1. Crea un servicio systemd:
```bash
sudo nano /etc/systemd/system/realtime-voice.service
```

2. Agrega este contenido:
```ini
[Unit]
Description=OpenAI Realtime Voice Assistant
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/realtime-api
Environment="PYTHONUNBUFFERED=1"
ExecStart=/home/pi/realtime-api/venv/bin/python /home/pi/realtime-api/03_audio_chat.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Habilita e inicia el servicio:
```bash
sudo systemctl enable realtime-voice.service
sudo systemctl start realtime-voice.service

# Ver logs
sudo journalctl -u realtime-voice.service -f
```

## Optimización para Raspberry Pi

Para mejorar el rendimiento en Raspberry Pi:

1. **Usa el modelo mini** (ya configurado por defecto)
2. **Reduce la latencia de red**: Conéctala por Ethernet si es posible
3. **Buffer de audio**: Ajusta `CHUNK` en el script si hay cortes
4. **Overclocking**: Considera overclock moderado si es necesario

## Licencia

MIT
