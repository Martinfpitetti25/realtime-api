#!/bin/bash
# Script de instalación para Robot Assistant con Visión
# Uso: ./install_vision.sh

echo "🤖 Instalando Robot Assistant - Visión"
echo "======================================"
echo ""

# Verificar entorno virtual
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  No se detectó un entorno virtual activo"
    echo "Por favor activa tu entorno virtual primero:"
    echo "  source .venv/bin/activate"
    echo ""
    read -p "¿Continuar sin entorno virtual? (no recomendado) [y/N]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "📦 Instalando dependencias de visión..."
echo ""

# Instalar opencv
echo "⏳ Instalando OpenCV (puede tardar 5-10 min)..."
pip install opencv-contrib-python>=4.12.0

# Instalar YOLO
echo "⏳ Instalando YOLO..."
pip install ultralytics>=8.0.196

# Instalar MediaPipe
echo "⏳ Instalando MediaPipe..."
pip install mediapipe>=0.10.14

echo ""
echo "✅ Dependencias instaladas!"
echo ""

# Verificar instalación
echo "🔍 Verificando instalación..."
python3 -c "
import cv2
import mediapipe
from ultralytics import YOLO
print('✅ OpenCV version:', cv2.__version__)
print('✅ MediaPipe version:', mediapipe.__version__)
print('✅ Ultralytics instalado correctamente')
"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ ¡Instalación completada con éxito!"
    echo ""
    echo "📝 Próximos pasos:"
    echo "  1. Test de cámara:"
    echo "     python hardware/camera_service.py"
    echo ""
    echo "  2. Ejecutar robot con visión:"
    echo "     python 07_vision_realtime.py"
    echo ""
else
    echo ""
    echo "❌ Hubo problemas en la instalación"
    echo "Verifica los errores arriba"
fi
