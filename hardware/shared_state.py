"""
SharedState - Estado compartido entre threads para el sistema de visión y tracking
================================================================================
Este módulo centraliza el acceso a la cámara y permite que múltiples threads
consuman frames sin conflictos.

Arquitectura:
- EyeTrackerThread: ÚNICO dueño de la cámara, escribe frames y estado de detección
- GPT-4V / GUI: Consumen frames del SharedState en modo lectura
"""

import threading
import time
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class FaceData:
    """Datos de la cara detectada"""
    detected: bool = False
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    center_x: int = 0
    center_y: int = 0
    confidence: float = 0.0
    timestamp: float = 0.0


class SharedState:
    """
    Estado compartido thread-safe para el sistema de visión y tracking.
    
    El EyeTrackerThread es el único que escribe en este estado.
    Otros threads (GPT-4V, GUI preview) solo leen.
    """
    
    def __init__(self):
        # Lock principal para acceso thread-safe
        self._lock = threading.Lock()
        
        # Evento de sincronización: se activa cuando la cámara está lista
        self.camera_ready = threading.Event()
        
        # Evento para señalar que el tracker debe detenerse
        self.stop_requested = threading.Event()
        
        # ═══════════════════════════════════════════════════════════════
        # ESTADO DEL FRAME (escrito por EyeTrackerThread)
        # ═══════════════════════════════════════════════════════════════
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_timestamp: float = 0.0
        self._frame_width: int = 0
        self._frame_height: int = 0
        
        # ═══════════════════════════════════════════════════════════════
        # ESTADO DE DETECCIÓN FACIAL (escrito por EyeTrackerThread)
        # ═══════════════════════════════════════════════════════════════
        self._face_data = FaceData()
        
        # ═══════════════════════════════════════════════════════════════
        # ESTADO DEL TRACKER (escrito por EyeTrackerThread)
        # ═══════════════════════════════════════════════════════════════
        self._tracker_running: bool = False
        self._tracker_fps: float = 0.0
        self._tracker_mode: str = "follow"  # follow, search, center, idle
        self._tracker_error: Optional[str] = None
        
        # ═══════════════════════════════════════════════════════════════
        # POSICIÓN DE LOS SERVOS (para debugging/UI)
        # ═══════════════════════════════════════════════════════════════
        self._servo_positions = {
            "left_h": 0.0,
            "left_v": 0.0,
            "right_h": 0.0,
            "right_v": 0.0,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # MÉTODOS DE ESCRITURA (solo para EyeTrackerThread)
    # ═══════════════════════════════════════════════════════════════════════
    
    def update_frame(self, frame: np.ndarray) -> None:
        """
        Actualiza el frame actual. Solo debe llamarlo EyeTrackerThread.
        
        Args:
            frame: Frame de OpenCV (BGR). Se hace una copia para evitar race conditions.
        """
        with self._lock:
            self._latest_frame = frame.copy()
            self._frame_timestamp = time.time()
            self._frame_height, self._frame_width = frame.shape[:2]
    
    def update_face_detection(
        self,
        detected: bool,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        confidence: float = 0.0
    ) -> None:
        """
        Actualiza el estado de detección facial. Solo debe llamarlo EyeTrackerThread.
        """
        with self._lock:
            self._face_data.detected = detected
            self._face_data.x = x
            self._face_data.y = y
            self._face_data.width = width
            self._face_data.height = height
            self._face_data.center_x = x + width // 2
            self._face_data.center_y = y + height // 2
            self._face_data.confidence = confidence
            self._face_data.timestamp = time.time()
    
    def update_tracker_status(
        self,
        running: bool,
        fps: float = 0.0,
        mode: str = "idle",
        error: Optional[str] = None
    ) -> None:
        """
        Actualiza el estado del tracker. Solo debe llamarlo EyeTrackerThread.
        """
        with self._lock:
            self._tracker_running = running
            self._tracker_fps = fps
            self._tracker_mode = mode
            self._tracker_error = error
    
    def update_servo_positions(
        self,
        left_h: float,
        left_v: float,
        right_h: float,
        right_v: float,
        neck_yaw: float = 0.0,
        neck_pitch: float = 0.0
    ) -> None:
        """
        Actualiza las posiciones de los servos para debugging/UI.
        """
        with self._lock:
            self._servo_positions["left_h"] = left_h
            self._servo_positions["left_v"] = left_v
            self._servo_positions["right_h"] = right_h
            self._servo_positions["right_v"] = right_v
            self._servo_positions["neck_yaw"] = neck_yaw
            self._servo_positions["neck_pitch"] = neck_pitch
    
    # ═══════════════════════════════════════════════════════════════════════
    # MÉTODOS DE LECTURA (para cualquier thread)
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_frame(self) -> Tuple[bool, Optional[np.ndarray], float]:
        """
        Obtiene el frame más reciente.
        
        Returns:
            Tuple de (success, frame, age_seconds)
            - success: True si hay un frame disponible
            - frame: Copia del frame o None
            - age_seconds: Antigüedad del frame en segundos
        """
        with self._lock:
            if self._latest_frame is None:
                return False, None, float('inf')
            
            age = time.time() - self._frame_timestamp
            return True, self._latest_frame.copy(), age
    
    def get_frame_if_fresh(self, max_age_seconds: float = 1.0) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Obtiene el frame solo si es reciente.
        
        Args:
            max_age_seconds: Edad máxima aceptable del frame
            
        Returns:
            Tuple de (success, frame)
        """
        success, frame, age = self.get_frame()
        if success and age <= max_age_seconds:
            return True, frame
        return False, None
    
    def get_face_data(self) -> FaceData:
        """
        Obtiene una copia de los datos de detección facial.
        """
        with self._lock:
            # Crear copia para evitar modificaciones externas
            return FaceData(
                detected=self._face_data.detected,
                x=self._face_data.x,
                y=self._face_data.y,
                width=self._face_data.width,
                height=self._face_data.height,
                center_x=self._face_data.center_x,
                center_y=self._face_data.center_y,
                confidence=self._face_data.confidence,
                timestamp=self._face_data.timestamp
            )
    
    def is_face_detected(self) -> bool:
        """Retorna True si hay una cara detectada recientemente (< 1s)."""
        with self._lock:
            if not self._face_data.detected:
                return False
            age = time.time() - self._face_data.timestamp
            return age < 1.0
    
    def get_tracker_status(self) -> dict:
        """
        Obtiene el estado actual del tracker.
        
        Returns:
            Dict con running, fps, mode, error
        """
        with self._lock:
            return {
                "running": self._tracker_running,
                "fps": self._tracker_fps,
                "mode": self._tracker_mode,
                "error": self._tracker_error
            }
    
    def is_tracker_running(self) -> bool:
        """Retorna True si el tracker está corriendo."""
        with self._lock:
            return self._tracker_running
    
    def get_servo_positions(self) -> dict:
        """Obtiene las posiciones actuales de los servos."""
        with self._lock:
            return self._servo_positions.copy()
    
    def get_frame_dimensions(self) -> Tuple[int, int]:
        """Retorna (width, height) del frame actual."""
        with self._lock:
            return self._frame_width, self._frame_height
    
    # ═══════════════════════════════════════════════════════════════════════
    # MÉTODOS DE CONTROL
    # ═══════════════════════════════════════════════════════════════════════
    
    def request_stop(self) -> None:
        """Señala al tracker que debe detenerse."""
        self.stop_requested.set()
    
    def reset_stop_request(self) -> None:
        """Limpia la señal de stop (para reiniciar el tracker)."""
        self.stop_requested.clear()
    
    def wait_for_camera(self, timeout: float = 10.0) -> bool:
        """
        Espera a que la cámara esté lista.
        
        Args:
            timeout: Tiempo máximo de espera en segundos
            
        Returns:
            True si la cámara está lista, False si timeout
        """
        return self.camera_ready.wait(timeout=timeout)
    
    def reset(self) -> None:
        """Resetea todo el estado (para reiniciar el sistema)."""
        with self._lock:
            self._latest_frame = None
            self._frame_timestamp = 0.0
            self._face_data = FaceData()
            self._tracker_running = False
            self._tracker_fps = 0.0
            self._tracker_mode = "idle"
            self._tracker_error = None
        
        self.camera_ready.clear()
        self.stop_requested.clear()
