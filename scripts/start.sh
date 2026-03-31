#!/bin/bash
# Script de inicio rápido para Realtime-IA
# Uso: ./start.sh [opcion]

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║           🚀 REALTIME-IA - INICIO RÁPIDO                 ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar entorno virtual
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ Error: Entorno virtual no encontrado${NC}"
    echo "Ejecuta primero: python -m venv .venv"
    exit 1
fi

# Activar entorno virtual
echo -e "${GREEN}✓ Activando entorno virtual...${NC}"
source .venv/bin/activate

# Verificar .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  Archivo .env no encontrado, creando desde plantilla...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Edita .env y agrega tu API key de OpenAI${NC}"
    exit 1
fi

# Verificar API key
if grep -q "tu_api_key_aqui" .env; then
    echo -e "${YELLOW}⚠️  Debes configurar tu API key en el archivo .env${NC}"
    echo "Edita: nano .env"
    exit 1
fi

# Menú de opciones
if [ -z "$1" ]; then
    echo ""
    echo "Selecciona una opción:"
    echo ""
    echo "  ${GREEN}0${NC}) 🧪 Test de conexión (verificar API key)"
    echo "  ${GREEN}1${NC}) 🔗 Conexión básica (ver eventos)"
    echo "  ${GREEN}2${NC}) 💬 Chat de texto (recomendado para empezar)"
    echo "  ${GREEN}3${NC}) 🎤 Chat de voz"
    echo "  ${GREEN}4${NC}) 🍓 Raspberry Pi (optimizado)"
    echo "  ${GREEN}5${NC}) 🖥️  Interfaz gráfica (GUI completa)"
    echo "  ${BLUE}d${NC}) 🔍 Diagnóstico completo"
    echo ""
    read -p "Opción: " option
else
    option=$1
fi

# Ejecutar script seleccionado
case $option in
    0)
        echo -e "${BLUE}Ejecutando test de conexión...${NC}"
        python 00_test_connection.py
        ;;
    1)
        echo -e "${BLUE}Ejecutando conexión básica...${NC}"
        python 01_basic_connection.py
        ;;
    2)
        echo -e "${BLUE}Ejecutando chat de texto...${NC}"
        python 02_text_chat.py
        ;;
    3)
        echo -e "${BLUE}Ejecutando chat de voz...${NC}"
        python 03_audio_chat.py
        ;;
    4)
        echo -e "${BLUE}Ejecutando versión Raspberry Pi...${NC}"
        python 04_raspberry_pi.py
        ;;
    5)
        echo -e "${BLUE}Ejecutando GUI...${NC}"
        python 05_gui_chat.py
        ;;
    d|D)
        echo -e "${BLUE}Ejecutando diagnóstico...${NC}"
        python diagnostico.py
        ;;
    *)
        echo -e "${RED}❌ Opción inválida${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✅ Finalizado${NC}"
