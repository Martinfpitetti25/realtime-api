#!/bin/bash
# Script de inicio para Realtime-IA con audio Bluetooth
# Autor: Sistema Realtime-IA
# Fecha: 2026-02-23

echo "========================================"
echo "  🎤 Realtime-IA - Inicio con Audio"
echo "========================================"

# 1. Verificar servicios de PipeWire
echo ""
echo "1️⃣  Verificando PipeWire..."
if systemctl --user is-active --quiet pipewire; then
    echo "   ✓ PipeWire activo"
else
    echo "   ⚠️  Iniciando PipeWire..."
    systemctl --user start pipewire pipewire-pulse wireplumber
    sleep 2
fi

# 2. Conectar dispositivo Bluetooth (JBL PARTYBOX 310)
BT_DEVICE="54:15:89:F9:1B:E1"
BT_NAME="JBL PARTYBOX 310"

echo ""
echo "2️⃣  Verificando Bluetooth..."
if bluetoothctl info $BT_DEVICE | grep -q "Connected: yes"; then
    echo "   ✓ $BT_NAME ya conectado"
else
    echo "   🔗 Conectando a $BT_NAME..."
    bluetoothctl trust $BT_DEVICE > /dev/null 2>&1
    bluetoothctl connect $BT_DEVICE > /dev/null 2>&1
    sleep 2
    
    if bluetoothctl info $BT_DEVICE | grep -q "Connected: yes"; then
        echo "   ✓ Conectado exitosamente"
    else
        echo "   ⚠️  No se pudo conectar (intentando continuar...)"
    fi
fi

# 3. Verificar dispositivos de audio
echo ""
echo "3️⃣  Verificando dispositivos de audio..."
source .venv/bin/activate
python -c "import pyaudio; pa = pyaudio.PyAudio(); print(f'   ✓ {pa.get_device_count()} dispositivos detectados'); pa.terminate()" 2>/dev/null

# 4. Opciones de inicio
echo ""
echo "========================================"
echo "Selecciona qué iniciar:"
echo "========================================"
echo "  1) 🎤 Chat de voz (GUI)          - 05_gui_chat.py"
echo "  2) 🎤 Chat de voz (terminal)     - 03_audio_chat.py"
echo "  3) 👁️  Chat con visión           - 07_vision_realtime.py"
echo "  4) 🤖 Asistente robot completo   - 06_robot_assistant.py"
echo "  5) 🔧 Test de audio              - test_audio_simple.py"
echo "  0) ❌ Salir"
echo ""
read -p "Opción (1-5, 0 para salir): " choice

case $choice in
    1)
        echo ""
        echo "🚀 Iniciando GUI de chat de voz..."
        python 05_gui_chat.py
        ;;
    2)
        echo ""
        echo "🚀 Iniciando chat de voz (terminal)..."
        python 03_audio_chat.py
        ;;
    3)
        echo ""
        echo "🚀 Iniciando chat con visión..."
        python 07_vision_realtime.py
        ;;
    4)
        echo ""
        echo "🚀 Iniciando asistente robot..."
        python 06_robot_assistant.py
        ;;
    5)
        echo ""
        echo "🔧 Ejecutando test de audio..."
        python test_audio_simple.py
        ;;
    0)
        echo ""
        echo "👋 Saliendo..."
        exit 0
        ;;
    *)
        echo ""
        echo "❌ Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "✅ Programa finalizado"
