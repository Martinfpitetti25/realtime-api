#!/usr/bin/env python3
"""
MouthController - Control del servo de la boca para animación de habla
=======================================================================
Controla el servo de la boca en el pin 2 del PCA9685 para simular
movimientos de habla mientras el asistente reproduce audio.

Configuración:
- Pin: 2 (PCA9685)
- Boca cerrada: 90 grados
- Boca abierta: 40 grados
"""

import threading
import time
import random
from typing import Optional

# Logger del proyecto
try:
    from utils.logger import get_logger
    log = get_logger('mouth_ctrl')
except ImportError:
    import logging
    log = logging.getLogger('mouth_ctrl')
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(logging.StreamHandler())

# ══════════════════════════════════════════════════════════════════════════════
# INTENTAR IMPORTAR SERVOKIT (compartido con eye_tracker_thread)
# ══════════════════════════════════════════════════════════════════════════════
SERVO_AVAILABLE = False
kit = None

# Primero intentar reutilizar el kit del eye_tracker_thread (evita conflictos I2C)
try:
    from hardware.eye_tracker_thread import kit as shared_kit, SERVO_AVAILABLE as shared_servo_available
    if shared_kit is not None and shared_servo_available:
        kit = shared_kit
        SERVO_AVAILABLE = True
        log.info("✅ MouthController usando ServoKit compartido con EyeTracker")
except ImportError:
    pass

# Si no existe kit compartido, crear uno nuevo
if kit is None:
    try:
        from adafruit_servokit import ServoKit
        kit = ServoKit(channels=16)
        SERVO_AVAILABLE = True
        log.info("✅ ServoKit (boca) inicializado correctamente")
    except ImportError:
        log.warning("⚠️ adafruit_servokit no disponible - modo simulación de boca")
    except Exception as e:
        log.warning(f"⚠️ Error inicializando ServoKit (boca): {e} - modo simulación")


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL SERVO DE LA BOCA
# ══════════════════════════════════════════════════════════════════════════════
PIN_BOCA = 2          # Pin del servo de la boca en PCA9685
BOCA_CERRADA = 90     # Ángulo para boca cerrada
BOCA_ABIERTA = 40     # Ángulo para boca abierta
BOCA_SEMI = 65        # Posición intermedia para movimiento natural


class MouthController:
    """
    Controlador del servo de la boca para animación de habla.
    
    Proporciona movimientos fluidos y naturales de la boca mientras
    el asistente habla, sincronizándose con la reproducción de audio.
    """
    
    def __init__(self, enable_servo: bool = True):
        """
        Inicializa el controlador de boca.
        
        Args:
            enable_servo: Si True, activa el servo real. False para simulación.
        """
        self.enable_servo = enable_servo and SERVO_AVAILABLE
        
        # Estado del controlador
        self.is_speaking = False
        self._speak_thread: Optional[threading.Thread] = None
        self._stop_speaking = threading.Event()
        self._lock = threading.Lock()
        
        # Posición actual de la boca
        self.current_angle = BOCA_CERRADA
        
        # Parámetros de animación de habla
        self.speak_speed = 0.08  # Velocidad base del movimiento (segundos)
        self.variation = 0.04   # Variación aleatoria en tiempos
        
        # Inicializar servo
        self._init_servo()
        
        log.info(f"MouthController inicializado - Servo: {'ON' if self.enable_servo else 'OFF (simulación)'}")
    
    def _init_servo(self) -> None:
        """Inicializa el servo de la boca con los rangos correctos."""
        if not self.enable_servo:
            return
        
        try:
            kit.servo[PIN_BOCA].actuation_range = 180
            kit.servo[PIN_BOCA].set_pulse_width_range(600, 2350)
            # Cerrar boca al iniciar
            self.close_mouth()
            log.info(f"✅ Servo de boca inicializado en pin {PIN_BOCA}")
        except Exception as e:
            log.error(f"❌ Error inicializando servo de boca: {e}")
            self.enable_servo = False
    
    def _set_angle(self, angle: int) -> None:
        """
        Establece el ángulo del servo de la boca de forma segura.
        
        Args:
            angle: Ángulo deseado (40-90 grados)
        """
        # Limitar el ángulo a los valores válidos
        angle = max(BOCA_ABIERTA, min(BOCA_CERRADA, angle))
        
        if self.enable_servo:
            try:
                kit.servo[PIN_BOCA].angle = angle
                self.current_angle = angle
            except Exception as e:
                log.error(f"Error moviendo boca a {angle}°: {e}")
        else:
            # Modo simulación: solo actualizar estado
            self.current_angle = angle
            log.debug(f"[SIM] Boca → {angle}°")
    
    def _smooth_move(self, target_angle: int, steps: int = 5, delay: float = 0.01) -> None:
        """
        Mueve el servo suavemente hacia el ángulo objetivo.
        
        Args:
            target_angle: Ángulo objetivo
            steps: Número de pasos para el movimiento
            delay: Retardo entre pasos
        """
        if self._stop_speaking.is_set():
            return
        
        start_angle = self.current_angle
        diff = target_angle - start_angle
        
        for i in range(1, steps + 1):
            if self._stop_speaking.is_set():
                break
            new_angle = int(start_angle + (diff * i / steps))
            self._set_angle(new_angle)
            time.sleep(delay)
    
    def close_mouth(self) -> None:
        """Cierra la boca completamente (posición de reposo)."""
        self._smooth_move(BOCA_CERRADA, steps=3, delay=0.015)
        log.debug("Boca cerrada")
    
    def open_mouth(self) -> None:
        """Abre la boca completamente."""
        self._smooth_move(BOCA_ABIERTA, steps=3, delay=0.015)
        log.debug("Boca abierta")
    
    def _speaking_animation(self) -> None:
        """
        Animación continua de habla con movimientos naturales y variados.
        Se ejecuta en un thread separado mientras is_speaking es True.
        """
        log.info("🗣️ Iniciando animación de habla")
        
        # Patrones de movimiento para simular habla natural
        # Cada patrón tiene: (ángulo_objetivo, duración_base)
        patterns = [
            (BOCA_ABIERTA, 0.06),      # Boca muy abierta (vocales abiertas)
            (BOCA_SEMI, 0.05),          # Semi abierta
            (BOCA_CERRADA, 0.04),       # Cerrada (consonantes)
            (BOCA_SEMI + 10, 0.05),     # Ligeramente abierta
            (BOCA_ABIERTA + 15, 0.06),  # Abierta media
            (BOCA_SEMI - 5, 0.04),      # Semi cerrada
        ]
        
        try:
            while not self._stop_speaking.is_set():
                # Seleccionar patrón aleatorio para naturalidad
                target_angle, base_duration = random.choice(patterns)
                
                # Añadir variación aleatoria
                variation = random.uniform(-8, 8)
                target_angle = int(max(BOCA_ABIERTA, min(BOCA_CERRADA, target_angle + variation)))
                
                duration = base_duration + random.uniform(-self.variation, self.variation)
                duration = max(0.03, duration)  # Mínimo 30ms
                
                # Movimiento suave hacia el objetivo
                self._smooth_move(target_angle, steps=3, delay=duration / 3)
                
                # Pequeña pausa entre movimientos
                if not self._stop_speaking.is_set():
                    time.sleep(random.uniform(0.02, 0.05))
        
        except Exception as e:
            log.error(f"Error en animación de habla: {e}")
        
        finally:
            # Siempre cerrar la boca al terminar
            self._stop_speaking.clear()
            self.close_mouth()
            log.info("✅ Animación de habla terminada - boca cerrada")
    
    def start_speaking(self) -> None:
        """
        Inicia la animación de habla.
        Debe llamarse cuando el asistente comienza a hablar/reproducir audio.
        """
        with self._lock:
            if self.is_speaking:
                log.debug("Ya estaba hablando, ignorando start_speaking")
                return
            
            self.is_speaking = True
            self._stop_speaking.clear()
            
            # Iniciar thread de animación
            self._speak_thread = threading.Thread(
                target=self._speaking_animation,
                daemon=True,
                name="MouthSpeakingThread"
            )
            self._speak_thread.start()
            log.debug("Thread de habla iniciado")
    
    def stop_speaking(self) -> None:
        """
        Detiene la animación de habla y cierra la boca.
        Debe llamarse cuando el asistente termina de hablar.
        """
        with self._lock:
            if not self.is_speaking:
                return
            
            self.is_speaking = False
            self._stop_speaking.set()
            
            # Esperar a que el thread termine (con timeout)
            if self._speak_thread and self._speak_thread.is_alive():
                self._speak_thread.join(timeout=0.5)
            
            # Asegurar que la boca esté cerrada
            self.close_mouth()
            log.debug("Habla detenida")
    
    def cleanup(self) -> None:
        """Limpia recursos y cierra la boca al terminar."""
        self.stop_speaking()
        self.close_mouth()
        log.info("MouthController cleanup completado")


# ══════════════════════════════════════════════════════════════════════════════
# INSTANCIA GLOBAL (singleton) para acceso desde otros módulos
# ══════════════════════════════════════════════════════════════════════════════
_mouth_controller: Optional[MouthController] = None


def get_mouth_controller(enable_servo: bool = True) -> MouthController:
    """
    Obtiene la instancia global del controlador de boca (singleton).
    
    Args:
        enable_servo: Si True, habilita el servo real.
        
    Returns:
        Instancia del MouthController
    """
    global _mouth_controller
    if _mouth_controller is None:
        _mouth_controller = MouthController(enable_servo=enable_servo)
    return _mouth_controller


def start_mouth_speaking() -> None:
    """Función de conveniencia para iniciar la animación de habla."""
    controller = get_mouth_controller()
    controller.start_speaking()


def stop_mouth_speaking() -> None:
    """Función de conveniencia para detener la animación de habla."""
    controller = get_mouth_controller()
    controller.stop_speaking()


def close_mouth() -> None:
    """Función de conveniencia para cerrar la boca."""
    controller = get_mouth_controller()
    controller.close_mouth()


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🧪 Test del MouthController")
    print("-" * 40)
    
    # Crear controlador
    mouth = MouthController(enable_servo=True)
    
    print("✅ Boca cerrada (posición inicial)")
    time.sleep(1)
    
    print("🗣️ Iniciando simulación de habla (5 segundos)...")
    mouth.start_speaking()
    time.sleep(5)
    
    print("⏹️ Deteniendo habla...")
    mouth.stop_speaking()
    
    print("✅ Test completado - boca cerrada")
    mouth.cleanup()
