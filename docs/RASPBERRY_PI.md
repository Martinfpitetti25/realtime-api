# 🍓 Guía Raspberry Pi

Guía específica para instalar y configurar Realtime-IA en Raspberry Pi.

## 📋 Hardware Recomendado

- **Raspberry Pi:** 3B+ o superior (4B recomendado)
- **Micrófono:** USB o módulo I2S
- **Altavoces:** USB, jack 3.5mm o HDMI
- **Cámara:** USB webcam o Raspberry Pi Camera Module
- **Internet:** Ethernet (preferido) o WiFi estable
- **Almacenamiento:** microSD de 16GB mínimo (32GB recomendado)

---

## 🚀 Instalación Completa

### 1. Preparar Sistema Base

```bash
# Actualizar sistema
sudo apt-get update
sudo apt-get upgrade -y

# Instalar dependencias del sistema
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    python3-dev \
    git \
    alsa-utils

# Opcional: Dependencias para visión
sudo apt-get install -y \
    libopencv-dev \
    python3-opencv
```

### 2. Clonar e Instalar Proyecto

```bash
# Clonar repositorio
cd ~
git clone <url_del_repo> Realtime-IA
cd Realtime-IA

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias Python
pip install -r requirements.txt

# Configurar API key
cp .env.example .env
nano .env  # Agregar OPENAI_API_KEY
```

### 3. Configurar Audio

```bash
# Verificar dispositivos de grabación
arecord -l

# Verificar dispositivos de reproducción
aplay -l

# Probar micrófono (graba 5 segundos)
arecord -D hw:1,0 -d 5 -f cd test.wav

# Reproducir grabación
aplay test.wav

# Configurar volumen
alsamixer
```

#### Configurar Dispositivo por Defecto

Si usas micrófono/altavoz USB, edita el archivo de configuración:

```bash
sudo nano /etc/asound.conf
```

Agrega (ajusta `card 1` según tu dispositivo):

```
pcm.!default {
    type hw
    card 1
}

ctl.!default {
    type hw
    card 1
}
```

### 4. Configurar Cámara (Opcional)

```bash
# Verificar cámaras disponibles
ls -l /dev/video*

# Probar con Python
python3 -c "import cv2; cap = cv2.VideoCapture(0); print('✅ OK' if cap.isOpened() else '❌ FAIL'); cap.release()"

# Si usas Pi Camera Module, habilítala
sudo raspi-config
# > Interface Options > Camera > Enable
```

---

## 🎮 Uso en Raspberry Pi

### Ejecución Manual

```bash
# Activar entorno
cd ~/Realtime-IA
source .venv/bin/activate

# Ejecutar
python 03_audio_chat.py      # Solo audio
python 05_gui_chat.py         # Con GUI (requiere monitor)
python 07_vision_realtime.py  # Con visión
```

### Auto-inicio al Encender

Crear servicio systemd para que se ejecute automáticamente:

```bash
# Crear archivo de servicio
sudo nano /etc/systemd/system/realtime-ia.service
```

Contenido:

```ini
[Unit]
Description=Realtime-IA Voice Assistant
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Realtime-IA
Environment="PYTHONUNBUFFERED=1"
Environment="DISPLAY=:0"
ExecStart=/home/pi/Realtime-IA/.venv/bin/python /home/pi/Realtime-IA/03_audio_chat.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Habilitar e iniciar:

```bash
# Habilitar auto-inicio
sudo systemctl enable realtime-ia.service

# Iniciar ahora
sudo systemctl start realtime-ia.service

# Ver estado
sudo systemctl status realtime-ia.service

# Ver logs en tiempo real
sudo journalctl -u realtime-ia.service -f

# Detener
sudo systemctl stop realtime-ia.service

# Deshabilitar auto-inicio
sudo systemctl disable realtime-ia.service
```

---

## ⚡ Optimizaciones para RPi

### 1. Reducir Consumo de CPU

En los archivos Python, ajusta:

```python
# Reducir FPS de cámara
CAMERA_FPS = 10  # En vez de 15 o 30

# Usar modelo YOLO ligero
model_path = "models/yolov8n.pt"  # 'n' = nano (más ligero)
```

### 2. Mejorar Latencia de Red

```bash
# Usar Ethernet si es posible
# Para WiFi, asegúrate de estar cerca del router

# Verificar latencia
ping -c 10 api.openai.com
```

### 3. Overclocking (Opcional)

Solo para RPi 4:

```bash
sudo nano /boot/config.txt
```

Agrega al final:

```
# Overclocking moderado RPi 4
over_voltage=2
arm_freq=1750
```

Reinicia:

```bash
sudo reboot
```

### 4. Deshabilitar Servicios Innecesarios

```bash
# Deshabilitar Bluetooth si no lo usas
sudo systemctl disable bluetooth

# Deshabilitar GUI si usas solo terminal
sudo systemctl set-default multi-user.target

# Volver a habilitar GUI
sudo systemctl set-default graphical.target
```

---

## 🔧 Troubleshooting Raspberry Pi

### Problema: Audio muy bajo

```bash
# Ajustar volumen con alsamixer
alsamixer

# O con amixer
amixer set Master 100%
amixer set Capture 80%
```

### Problema: Micrófono no detectado

```bash
# Verificar que esté conectado
lsusb

# Recargar módulos de audio
sudo modprobe snd-usb-audio

# Verificar permisos
sudo usermod -a -G audio $USER
# Cerrar sesión y volver a entrar
```

### Problema: Cámara no funciona

```bash
# Para USB webcam
sudo modprobe bcm2835-v4l2

# Para Pi Camera Module
sudo raspi-config
# Interface Options > Legacy Camera > Enable
```

### Problema: Memoria insuficiente

```bash
# Crear swap file (2GB)
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Cambiar CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

# Verificar
free -h
```

### Problema: Alta temperatura

```bash
# Ver temperatura
vcgencmd measure_temp

# Si >80°C:
# - Agregar disipador de calor
# - Usar ventilador
# - Reducir overclocking
# - Mejorar ventilación
```

---

## 📊 Monitoreo de Recursos

```bash
# CPU y memoria en tiempo real
htop

# Temperatura
watch -n 2 vcgencmd measure_temp

# Uso de disco
df -h

# Uso de red
iftop
```

---

## 🔄 Actualización del Proyecto

```bash
cd ~/Realtime-IA
source .venv/bin/activate

# Obtener últimos cambios
git pull

# Actualizar dependencias si hay cambios
pip install -r requirements.txt --upgrade

# Reiniciar servicio si está en auto-inicio
sudo systemctl restart realtime-ia.service
```

---

## 💡 Tips Adicionales

1. **Usa Ethernet:** WiFi puede tener latencia variable
2. **Alimentación estable:** Usa fuente de 5V 3A mínimo
3. **Ventilación:** Evita sobrecalentamiento
4. **Backups:** Copia la microSD periódicamente
5. **Monitoreo:** Revisa logs con `journalctl -f`

---

## 📞 Soporte

Si tienes problemas específicos de Raspberry Pi, abre un issue en el repositorio con:
- Modelo de Raspberry Pi
- Versión de Raspbian/Raspberry Pi OS
- Logs completos del error
- Resultado de `uname -a`
