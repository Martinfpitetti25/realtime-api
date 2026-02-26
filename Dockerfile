# Dockerfile para realtime-api (PC y Raspberry Pi)

# --- Etapa base ---
FROM python:3.11-slim AS base

# Instala dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    portaudio19-dev \
    libasound2-dev \
    libopencv-dev \
    ffmpeg \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia requirements y código
COPY requirements.txt ./
COPY . .

# Instala dependencias Python
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Variables de entorno ---
ENV PYTHONUNBUFFERED=1

# --- Comando por defecto ---
CMD ["python", "05_gui_chat.py"]
