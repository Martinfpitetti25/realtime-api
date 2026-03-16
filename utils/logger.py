"""
Logging utility for Realtime-IA
Centraliza todos los logs del proyecto con formato consistente y niveles configurables.

Uso:
    from utils.logger import get_logger
    log = get_logger("audio")
    
    log.debug("Detalle técnico")       # Solo visible con LOG_LEVEL=DEBUG
    log.info("✅ Módulo iniciado")     # Visible por defecto
    log.warning("⚠️ Sin micrófono")   # Siempre visible
    log.error("❌ Conexión fallida")   # Siempre visible

Configuración via variable de entorno:
    LOG_LEVEL=DEBUG ./quick.sh   → Muestra todo (debug incluido)
    LOG_LEVEL=WARNING ./quick.sh → Solo warnings y errores
"""
import logging
import sys
import os


# Nivel global configurable via env var (default: INFO)
_LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Cache de loggers creados
_loggers = {}

# Formato compacto: [HH:MM:SS] [MÓDULO] mensaje
_FORMAT = '%(asctime)s [%(shortname)s] %(message)s'
_DATE_FORMAT = '%H:%M:%S'


class _ShortNameFilter(logging.Filter):
    """Agrega nombre corto del módulo al record para formato compacto"""
    
    # Mapeo de nombres largos a cortos
    _name_map = {
        '__main__': 'APP',
        'gui_chat': 'APP',
        'audio': 'AUDIO',
        'audio_enhancer': 'AUDIO',
        'echo_canceller': 'AEC',
        'aec': 'AEC',
        'vision': 'VISION',
        'gpt4v': 'GPT4V',
        'camera': 'CAM',
        'camera_service': 'CAM',
        'gpt4_vision_service': 'GPT4V',
        'websocket': 'WS',
        'ws': 'WS',
        'wake_word': 'WAKE',
        'porcupine': 'WAKE',
        'device': 'DEVICE',
        'audio_device_manager': 'DEVICE',
        'config': 'CONFIG',
        'interrupt': 'INT',
        'robot': 'ROBOT',
    }
    
    def filter(self, record):
        name = record.name.split('.')[-1].lower()
        record.shortname = self._name_map.get(name, name.upper()[:8])
        return True


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.
    
    Args:
        name: Name of the logger (e.g., 'audio', 'vision', 'ws')
        
    Returns:
        Configured logger instance
    """
    # Devolver cached si existe
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    
    # Solo configurar si no tiene handlers
    if not logger.handlers:
        level = getattr(logging, _LOG_LEVEL, logging.INFO)
        logger.setLevel(level)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        
        # Formato
        formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
        console_handler.setFormatter(formatter)
        
        # Filtro para nombre corto
        console_handler.addFilter(_ShortNameFilter())
        
        logger.addHandler(console_handler)
        
        # No propagar al root logger
        logger.propagate = False
    
    _loggers[name] = logger
    return logger
