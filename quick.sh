#!/bin/bash
# Script de inicio rápido para Realtime-IA
# Uso: ./quick.sh [opción] [--debug]

set -e

# ─── Directorio del script (para paths relativos correctos) ───
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Colores ───
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ─── Flag --debug ───
DEBUG_MODE=false
for arg in "$@"; do
    if [[ "$arg" == "--debug" ]]; then
        DEBUG_MODE=true
        export LOG_LEVEL=DEBUG
    fi
done

# ─── Banner ───
clear
echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════╗"
echo "║       REALTIME-IA  ·  Inicio Rápido           ║"
echo "╚════════════════════════════════════════════════╝"
echo -e "${NC}"
if $DEBUG_MODE; then
    echo -e "  ${YELLOW}⚙  Modo DEBUG activado (LOG_LEVEL=DEBUG)${NC}"
    echo ""
fi

# ─── Función de ayuda ───
show_help() {
    echo -e "Uso: ${BOLD}./quick.sh${NC} [opción] [--debug]"
    echo ""
    echo "Opciones disponibles:"
    echo -e "  ${GREEN}gui${NC}       Interfaz gráfica completa ${DIM}(recomendado)${NC}"
    echo -e "  ${GREEN}audio${NC}     Chat de voz en consola ${DIM}(backups/)${NC}"
    echo -e "  ${GREEN}text${NC}      Chat de texto ${DIM}(backups/)${NC}"
    echo -e "  ${GREEN}vision${NC}    Modo visión con GPT-4V ${DIM}(backups/)${NC}"
    echo -e "  ${GREEN}robot${NC}     Asistente robot ${DIM}(backups/)${NC}"
    echo -e "  ${GREEN}test${NC}      Test de conexión rápido ${DIM}(backups/)${NC}"
    echo -e "  ${GREEN}install${NC}   Instalar dependencias"
    echo -e "  ${GREEN}check${NC}     Verificar entorno y dependencias"
    echo ""
    echo -e "Flags:"
    echo -e "  ${GREEN}--debug${NC}   Activar logs detallados (LOG_LEVEL=DEBUG)"
    echo ""
    echo -e "Ejemplos:"
    echo -e "  ${DIM}./quick.sh gui${NC}           # Lanzar GUI"
    echo -e "  ${DIM}./quick.sh gui --debug${NC}   # GUI con logs detallados"
    echo -e "  ${DIM}./quick.sh${NC}               # Menú interactivo"
    echo ""
}

# ─── Verificar Python 3.10+ ───
check_python() {
    if ! command -v python3 &>/dev/null; then
        echo -e "${RED}✗ Python3 no encontrado${NC}"
        echo "  Instala con: sudo apt install python3 python3-pip python3-venv"
        exit 1
    fi

    local py_version
    py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local py_major py_minor
    py_major=$(echo "$py_version" | cut -d. -f1)
    py_minor=$(echo "$py_version" | cut -d. -f2)

    if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 10 ]]; then
        echo -e "${RED}✗ Python $py_version detectado — se requiere 3.10+${NC}"
        echo "  Instala una versión más reciente de Python."
        exit 1
    fi

    echo -e "  ${GREEN}✓${NC} Python $py_version"
}

# ─── Activar entorno virtual ───
activate_env() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}  ⚙ Creando entorno virtual (.venv)...${NC}"
        python3 -m venv .venv
        echo -e "  ${GREEN}✓${NC} Entorno virtual creado"
    fi
    source .venv/bin/activate
    echo -e "  ${GREEN}✓${NC} Entorno virtual activado"
}

# ─── Verificar .env y API key ───
check_env() {
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}  ⚙ Creando archivo .env de ejemplo...${NC}"
        echo "OPENAI_API_KEY=tu_api_key_aqui" > .env
        echo -e "${RED}✗ Configura tu API key en .env antes de continuar${NC}"
        echo "  Edita: nano .env"
        exit 1
    fi

    if grep -q "tu_api_key_aqui" .env 2>/dev/null; then
        echo -e "${RED}✗ API key no configurada en .env${NC}"
        echo "  Edita: nano .env"
        exit 1
    fi

    echo -e "  ${GREEN}✓${NC} API key configurada"
}

# ─── Verificar dependencias Python ───
check_deps() {
    local missing=()
    local modules=("websocket:websocket-client" "pyaudio:PyAudio" "dotenv:python-dotenv" "numpy:numpy")

    for entry in "${modules[@]}"; do
        local mod="${entry%%:*}"
        local pkg="${entry##*:}"
        if ! python3 -c "import $mod" 2>/dev/null; then
            missing+=("$pkg")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "  ${YELLOW}⚠ Paquetes faltantes: ${missing[*]}${NC}"
        echo -e "  Ejecuta: ${BOLD}./quick.sh install${NC}"
        return 1
    fi

    echo -e "  ${GREEN}✓${NC} Dependencias core instaladas"
    return 0
}

# ─── Verificar que un script exista ───
require_file() {
    if [ ! -f "$1" ]; then
        echo -e "${RED}✗ Archivo no encontrado: $1${NC}"
        echo "  Verifica que el proyecto esté completo."
        exit 1
    fi
}

# ─── Ejecutar script con verificaciones ───
run_script() {
    local label="$1"
    local script="$2"

    echo -e "${DIM}─── Verificando entorno ───${NC}"
    check_python
    activate_env
    check_env
    check_deps || exit 1
    require_file "$script"
    echo -e "${DIM}───────────────────────────${NC}"
    echo ""
    echo -e "${BLUE}▶ Ejecutando: ${BOLD}$label${NC}"
    echo ""
    python "$script"
}

# ─── Instalación de dependencias ───
install_deps() {
    echo -e "${DIM}─── Instalando dependencias ───${NC}"
    check_python
    activate_env
    require_file "requirements.txt"
    echo ""
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    echo ""
    echo -e "  ${GREEN}✓${NC} Dependencias instaladas correctamente"
    echo ""

    # Verificar paquetes opcionales
    echo -e "${DIM}Paquetes opcionales:${NC}"
    if python3 -c "import pvporcupine" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} pvporcupine (wake word)"
    else
        echo -e "  ${DIM}–${NC} pvporcupine (wake word) — no instalado"
    fi
    if python3 -c "import cv2" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} opencv-python (visión)"
    else
        echo -e "  ${DIM}–${NC} opencv-python (visión) — no instalado"
    fi
    echo ""
}

# ─── Verificar entorno completo (check) ───
full_check() {
    echo -e "${DIM}─── Verificación del entorno ───${NC}"
    check_python
    activate_env
    check_env
    echo ""

    # Core
    echo -e "${BOLD}Dependencias core:${NC}"
    local core_modules=("websocket:websocket-client" "pyaudio:PyAudio" "dotenv:python-dotenv" "numpy:numpy" "tkinter:tkinter")
    for entry in "${core_modules[@]}"; do
        local mod="${entry%%:*}"
        local pkg="${entry##*:}"
        if python3 -c "import $mod" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $pkg"
        else
            echo -e "  ${RED}✗${NC} $pkg"
        fi
    done
    echo ""

    # Opcional
    echo -e "${BOLD}Dependencias opcionales:${NC}"
    local opt_modules=("pvporcupine:pvporcupine (wake word)" "cv2:opencv-python (visión)" "ultralytics:ultralytics (YOLO)")
    for entry in "${opt_modules[@]}"; do
        local mod="${entry%%:*}"
        local pkg="${entry##*:}"
        if python3 -c "import $mod" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $pkg"
        else
            echo -e "  ${DIM}–${NC} $pkg — no instalado"
        fi
    done
    echo ""

    # Archivos principales
    echo -e "${BOLD}Archivos del proyecto:${NC}"
    local files=("05_gui_chat.py" "requirements.txt" "utils/logger.py" "utils/audio_enhancer.py" "utils/echo_canceller.py" "hardware/camera_service.py")
    for f in "${files[@]}"; do
        if [ -f "$f" ]; then
            echo -e "  ${GREEN}✓${NC} $f"
        else
            echo -e "  ${RED}✗${NC} $f"
        fi
    done
    echo ""
    echo -e "${GREEN}Verificación completa.${NC}"
}

# ─── Procesamiento de opciones ───
# Filtrar --debug del primer argumento
OPTION="${1:-menu}"
[[ "$OPTION" == "--debug" ]] && OPTION="menu"

case "$OPTION" in
    gui)
        run_script "GUI completa" "05_gui_chat.py"
        ;;
    audio|voz)
        run_script "Chat de voz" "backups/03_audio_chat.py"
        ;;
    text|texto)
        run_script "Chat de texto" "backups/02_text_chat.py"
        ;;
    vision)
        run_script "Modo visión" "backups/07_vision_realtime.py"
        ;;
    robot)
        run_script "Asistente robot" "backups/06_robot_assistant.py"
        ;;
    test)
        run_script "Test de conexión" "backups/00_test_connection.py"
        ;;
    install)
        install_deps
        ;;
    check)
        full_check
        ;;
    help|--help|-h)
        show_help
        ;;
    menu)
        echo -e "${DIM}─── Verificando entorno ───${NC}"
        check_python
        activate_env
        check_env
        check_deps || true
        echo -e "${DIM}───────────────────────────${NC}"
        echo ""
        echo "Selecciona el modo de inicio:"
        echo ""
        echo -e "  ${CYAN}1${NC}) GUI completa ${DIM}(recomendado)${NC}"
        echo -e "  ${CYAN}2${NC}) Chat de voz ${DIM}(backups/)${NC}"
        echo -e "  ${CYAN}3${NC}) Chat de texto ${DIM}(backups/)${NC}"
        echo -e "  ${CYAN}4${NC}) Modo visión ${DIM}(backups/)${NC}"
        echo -e "  ${CYAN}5${NC}) Asistente robot ${DIM}(backups/)${NC}"
        echo -e "  ${CYAN}6${NC}) Test de conexión ${DIM}(backups/)${NC}"
        echo ""
        read -p "Opción [1-6]: " option

        case $option in
            1) require_file "05_gui_chat.py"           && python 05_gui_chat.py ;;
            2) require_file "backups/03_audio_chat.py"  && python backups/03_audio_chat.py ;;
            3) require_file "backups/02_text_chat.py"   && python backups/02_text_chat.py ;;
            4) require_file "backups/07_vision_realtime.py" && python backups/07_vision_realtime.py ;;
            5) require_file "backups/06_robot_assistant.py" && python backups/06_robot_assistant.py ;;
            6) require_file "backups/00_test_connection.py" && python backups/00_test_connection.py ;;
            *) echo -e "${RED}Opción inválida${NC}" ;;
        esac
        ;;
    *)
        echo -e "${RED}✗ Opción desconocida: $OPTION${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
