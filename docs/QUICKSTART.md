# 🚀 Guía de Instalación Rápida

## Instalación (Una sola vez)

### 1. Crear entorno virtual
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar dependencias del sistema (Raspberry Pi/Linux)
```bash
sudo apt-get update
sudo apt-get install portaudio19-dev python3-dev
```

### 3. Instalar dependencias Python
```bash
pip install -r requirements.txt
```

### 4. Configurar API Key
```bash
# Copiar plantilla
cp .env.example .env

# Editar y agregar tu API key de OpenAI
nano .env
```

⚠️ **Importante:** Usa una API key que empiece con `sk-` (no `tsk-proj-`) y que tenga acceso a Realtime API.

Obtén tu key en: https://platform.openai.com/api-keys

---

## Uso

### Activar entorno (cada vez que uses el proyecto)
```bash
source .venv/bin/activate
```

### Menú interactivo
```bash
./start.sh
```

### O ejecuta directamente:
```bash
python 05_gui_chat.py        # GUI completa (recomendado)
python 02_text_chat.py        # Chat de texto
python 04_raspberry_pi.py     # Optimizado para RPi con voz
```

---

## 📊 Costos

**Modelo:** gpt-realtime-mini
- Entrada: $0.60 por 1M tokens
- Salida: $2.40 por 1M tokens
- Conversación de 5 min ≈ $0.04-$0.05

---

## 🔗 Recursos

- [Documentación Realtime API](https://platform.openai.com/docs/guides/realtime)
- [Panel de uso](https://platform.openai.com/usage)
- [Modelos disponibles](https://platform.openai.com/docs/models)
