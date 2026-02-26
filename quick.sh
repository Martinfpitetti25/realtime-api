#!/bin/bash
# Script de inicio rápido para Realtime-IA
# Uso: ./quick.sh [opción]

set -e

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

clear
echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════╗"
echo "║      REALTIME-IA - Inicio Rápido             ║"
echo "╚════════════════════════════════════════════════╝"
echo -e "${NC}"

# Función de ayuda
show_help() {
    echo "Uso: ./quick.sh [opción]"
    echo ""
    echo "Opciones disponibles:"
    echo "  ${GREEN}gui${NC}      - Interfaz gráfica completa (recomendado)"
    echo "  ${GREEN}audio${NC}    - Chat de voz en consola"
    echo "  ${GREEN}text${NC}     - Chat de texto"
    echo "  ${GREEN}vision${NC}   - Modo visión con GPT-4"
    echo "  ${GREEN}robot${NC}    - Asistente robot"
    echo "  ${GREEN}test${NC}     - Test de conexión rápido"
    echo "  ${GREEN}install${NC}  - Instalar dependencias"
    echo ""
}

# Activar entorno virtual
activate_env() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Creando entorno virtual...${NC}"
        python3 -m venv .venv
    fi
    source .venv/bin/activate
}

# Verificar .env
check_env() {
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Creando archivo .env...${NC}"
        echo "OPENAI_API_KEY=tu_api_key_aqui" > .env
        echo -e "${RED}ERROR: Configura tu API key en .env${NC}"
        exit 1
    fi
    
    if grep -q "tu_api_key_aqui" .env; then
        echo -e "${RED}ERROR: Configura tu API key en .env${NC}"
        echo "Edita: nano .env"
        exit 1
    fi
}

# Ejecutar con verificaciones
run_script() {
    activate_env
    check_env
    echo -e "${BLUE}▶ Ejecutando: $1${NC}"
    echo ""
    python "$2"
}

# Instalación rápida
install_deps() {
    echo -e "${BLUE}Instalando dependencias...${NC}"
    activate_env
    pip install -q -r requirements.txt
    echo -e "${GREEN}Instalación completa${NC}"
}

# Procesamiento de opciones
case "${1:-menu}" in
    gui)
        run_script "GUI completa" "05_gui_chat.py"
        ;;
    audio|voz)
        run_script "Chat de voz" "03_audio_chat.py"
        ;;
    text|texto)
        run_script "Chat de texto" "02_text_chat.py"
        ;;
    vision)
        run_script "Modo visión" "07_vision_realtime.py"
        ;;
    robot)
        run_script "Asistente robot" "06_robot_assistant.py"
        ;;
    test)
        run_script "Test de conexión" "00_test_connection.py"
        ;;
    install)
        install_deps
        ;;
    help|--help|-h)
        show_help
        ;;
    menu)
        activate_env
        check_env
        echo "Selecciona el modo de inicio:"
        echo ""
        echo "  ${CYAN}1${NC}) GUI completa (recomendado)"
        echo "  ${CYAN}2${NC}) Chat de voz"
        echo "  ${CYAN}3${NC}) Chat de texto"
        echo "  ${CYAN}4${NC}) Modo visión"
        echo "  ${CYAN}5${NC}) Asistente robot"
        echo "  ${CYAN}6${NC}) Test de conexión"
        echo ""
        read -p "Opción [1-6]: " option
        
        case $option in
            1) python 05_gui_chat.py ;;
            2) python 03_audio_chat.py ;;
            3) python 02_text_chat.py ;;
            4) python 07_vision_realtime.py ;;
            5) python 06_robot_assistant.py ;;
            6) python 00_test_connection.py ;;
            *) echo -e "${RED}Opción inválida${NC}" ;;
        esac
        ;;
    *)
        echo -e "${RED}ERROR: Opción desconocida: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
