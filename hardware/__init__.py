"""
Hardware components for Robot Assistant
Vision, detection and motor control capabilities
"""
from .camera_service import CameraService

# Nuevos módulos para sistema de tracking facial integrado
try:
    from .shared_state import SharedState
    from .eye_tracker_thread import EyeTrackerThread
    __all__ = ['CameraService', 'SharedState', 'EyeTrackerThread']
except ImportError:
    # Si faltan dependencias (ej: fuera de Raspberry Pi), solo exportar CameraService
    __all__ = ['CameraService']
