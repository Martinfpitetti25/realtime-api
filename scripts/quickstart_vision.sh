#!/bin/bash
# Quick Start - Robot con Visión
# Ejecuta este script para empezar rápido

clear
echo "╔════════════════════════════════════════════════════════╗"
echo "║  🤖 ROBOT ASSISTANT - QUICK START                     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check venv
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Entorno virtual no activo"
    echo "Activando .venv..."
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    elif [ -d "venv" ]; then
        source venv/bin/activate
    else
        echo "❌ No se encontró entorno virtual"
        echo "Crear con: python -m venv .venv"
        exit 1
    fi
fi

echo "✅ Entorno virtual: $VIRTUAL_ENV"
echo ""

# Menu
PS3="Selecciona una opción: "
options=(
    "Instalar dependencias de visión"
    "Test rápido (verifica todo)"
    "Test de cámara + YOLO (visual)"
    "Ejecutar robot completo"
    "Ver documentación"
    "Salir"
)

select opt in "${options[@]}"
do
    case $opt in
        "Instalar dependencias de visión")
            echo ""
            echo "📦 Instalando dependencias..."
            ./install_vision.sh
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        "Test rápido (verifica todo)")
            echo ""
            python test_vision_integration.py
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        "Test de cámara + YOLO (visual)")
            echo ""
            echo "📸 Abriendo preview de cámara..."
            echo "💡 Presiona 'q' para salir"
            echo ""
            python hardware/camera_service.py
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        "Ejecutar robot completo")
            echo ""
            echo "🤖 Iniciando robot..."
            echo "💡 Presiona Ctrl+C para detener"
            echo ""
            python 07_vision_realtime.py
            ;;
        "Ver documentación")
            echo ""
            echo "📚 Documentación disponible:"
            echo ""
            echo "  • README.md - Documentación principal"
            echo "  • VISION_README.md - Guía completa de visión"
            echo "  • INTEGRATION_SUMMARY.md - Resumen técnico"
            echo ""
            echo "Abrir con: cat VISION_README.md | less"
            echo ""
            read -p "Presiona Enter para continuar..."
            ;;
        "Salir")
            echo ""
            echo "👋 ¡Hasta luego!"
            break
            ;;
        *) 
            echo "Opción inválida"
            ;;
    esac
done
