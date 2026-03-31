#!/usr/bin/env python3
"""
EyeTrackerThread - Sistema de seguimiento facial con control de servos InMoov
==============================================================================
Adaptado de frankeinstein/seguimiento.py para funcionar como thread integrado.

Este thread es el ÚNICO dueño de la cámara. Todos los demás componentes
que necesiten frames deben leerlos del SharedState.

Funcionalidades:
- Detección facial con YuNet (ligero, 30 FPS)
- Control PID de servos para ojos
- Movimiento de cuello con retardo
- Parpadeo asíncrono natural
- Búsqueda activa cuando se pierde la cara
- Retorno al centro tras inactividad
"""

import cv2
import time
import urllib.request
import pathlib
import json
import random
import threading
import sys
from typing import Optional

# Importar SharedState
from hardware.shared_state import SharedState

# Logger del proyecto
try:
    from utils.logger import get_logger
    log = get_logger('eye_tracker')
except ImportError:
    import logging
    log = logging.getLogger('eye_tracker')
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(logging.StreamHandler())

# ══════════════════════════════════════════════════════════════════════════════
# INTENTAR IMPORTAR SERVOKIT (solo disponible en Raspberry Pi)
# ══════════════════════════════════════════════════════════════════════════════
SERVO_AVAILABLE = False
kit = None

try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16)
    SERVO_AVAILABLE = True
    log.info("✅ ServoKit inicializado correctamente")
except ImportError:
    log.warning("⚠️ adafruit_servokit no disponible - modo simulación de servos")
except Exception as e:
    log.warning(f"⚠️ Error inicializando ServoKit: {e} - modo simulación de servos")


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE HARDWARE (del código original de frankeinstein)
# ══════════════════════════════════════════════════════════════════════════════

# Pines de servos
PIN_LH = 0   # Ojo Izquierdo Horizontal
PIN_LV = 1   # Ojo Izquierdo Vertical
PIN_RH = 9   # Ojo Derecho Horizontal
PIN_RV = 7   # Ojo Derecho Vertical
PIN_PARPADO_INF = 3   # Párpado inferior
PIN_PARPADO_SUP = 5   # Párpado superior
PIN_CUELLO_YAW = 4    # Cuello Yaw horizontal
PIN_CUELLO_PITCH = 8  # Cuello Pitch vertical
PIN_ROLL_1 = 10       # Roll 1 asimétrico
PIN_ROLL_2 = 6        # Roll 2 asimétrico

# Valores de párpados
PARPADO_INF_ABIERTO = 40
PARPADO_SUP_ABIERTO = 65
PARPADO_CERRADO = 95

# Límites calibrados para cada servo
LH = dict(lo=40, hi=130, mid=90)   # Izq Horizontal
LV = dict(lo=80, hi=105, mid=90)   # Izq Vertical
RH = dict(lo=40, hi=130, mid=90)   # Der Horizontal
RV = dict(lo=80, hi=100, mid=90)   # Der Vertical
CUELLO_YAW = dict(lo=50, hi=150, mid=100)    # Cuello horizontal
CUELLO_PITCH = dict(lo=60, hi=180, mid=120)  # Cuello vertical

# Parámetros de control
DEADBAND_X = 30   # Píxeles de zona muerta horizontal
DEADBAND_Y = 25   # Píxeles de zona muerta vertical
I_CLAMP = 20.0    # Límite del integrador PID
LOST_MS = 400     # ms sin cara → iniciar búsqueda
SEARCH_DPS = 18.0 # Velocidad de búsqueda (°/s)
RETURN_MS = 4000  # ms sin cara → volver al centro
ACTIVE_SEARCH_MS = 10000  # 10 segundos sin cara → búsqueda activa con cuello
ACTIVE_SEARCH_INTERVAL_MS = 5000  # 5 segundos mirando en cada dirección

# Ruta al modelo YuNet y config
FRANKEINSTEIN_DIR = pathlib.Path(__file__).parent.parent / "frankeinstein"
MODEL_PATH = FRANKEINSTEIN_DIR / "models" / "yunet.onnx"
CONFIG_PATH = FRANKEINSTEIN_DIR / "config.json"
MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
             "models/face_detection_yunet/face_detection_yunet_2023mar.onnx")


def clamp(v: float, lo: float, hi: float) -> float:
    """Limita un valor entre lo y hi."""
    return max(lo, min(hi, v))


class EyeTrackerThread(threading.Thread):
    """
    Thread de seguimiento facial que controla los servos de ojos y cuello.
    Es el ÚNICO propietario de la cámara en todo el sistema.
    """
    
    def __init__(
        self,
        shared_state: SharedState,
        camera_index: int = 0,
        headless: bool = True,
        enable_servos: bool = True
    ):
        """
        Inicializa el thread de tracking.
        
        Args:
            shared_state: Instancia de SharedState para compartir frames
            camera_index: Índice de la cámara (default: 0)
            headless: Si True, no muestra ventana de OpenCV (default: True para integración)
            enable_servos: Si True, activa los servos (False para testing sin hardware)
        """
        super().__init__(daemon=True, name="EyeTrackerThread")
        
        self.shared_state = shared_state
        self.camera_index = camera_index
        self.headless = headless
        self.enable_servos = enable_servos and SERVO_AVAILABLE
        
        # Cámara y detector
        self.cap: Optional[cv2.VideoCapture] = None
        self.face_detector = None
        
        # Cargar configuración PID desde config.json de frankeinstein
        self.cfg = {
            "KP": 0.80,
            "KI": 0.01,
            "SMOOTH": 0.15,
            "OFFSET_X": 0
        }
        self._load_config()
        
        # Estado de tracking (variables del código original)
        self.lh = float(LH["mid"])
        self.lv = float(LV["mid"])
        self.rh = float(RH["mid"])
        self.rv = float(RV["mid"])
        self.cuello_yaw_ang = float(CUELLO_YAW["mid"])
        self.cuello_pitch_ang = float(CUELLO_PITCH["mid"])
        
        self.sum_ex = 0.0
        self.sum_ey = 0.0
        
        self.last_time = 0.0
        self.last_seen = 0.0
        self.dir_x = 0
        self.dir_y = 0
        self.centered = False
        self.returning = False
        self.tracked_face = None
        self.face_first_seen_time = 0.0
        
        # Estado de búsqueda activa
        self.active_search_mode = False
        self.active_search_target_yaw = CUELLO_YAW["mid"]
        self.active_search_direction = 1  # 1 = derecha, -1 = izquierda
        self.active_search_start_time = 0.0
        
        # Estado del parpadeo
        self.blink_phase = "IDLE"
        self.next_blink_time = 0.0
        self.blink_state_end = 0.0
        self.blinks_to_do = 0
        
        # Contadores de FPS
        self.frames = 0
        self.fps_t = 0.0
        self.current_fps = 0.0
        
        log.info(f"EyeTrackerThread inicializado - Servos: {'ON' if self.enable_servos else 'OFF'}")
    
    def _load_config(self) -> None:
        """Carga configuración desde frankeinstein/config.json."""
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r") as f:
                    loaded = json.load(f)
                    self.cfg.update(loaded)
                log.info(f"Config cargada: KP={self.cfg['KP']}, KI={self.cfg['KI']}, "
                        f"SMOOTH={self.cfg['SMOOTH']}, OFFSET_X={self.cfg['OFFSET_X']}")
            except Exception as e:
                log.warning(f"Error cargando config: {e}, usando valores por defecto")
    
    def _save_config(self) -> None:
        """Guarda configuración actual a frankeinstein/config.json."""
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception as e:
            log.warning(f"Error guardando config: {e}")
    
    def _ensure_model(self) -> bool:
        """Descarga el modelo YuNet si no existe."""
        if not MODEL_PATH.exists() or MODEL_PATH.stat().st_size < 100000:
            log.info("⬇️ Descargando modelo YuNet...")
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            if MODEL_PATH.exists():
                MODEL_PATH.unlink()
            try:
                urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
                log.info("✅ Modelo YuNet descargado")
                return True
            except Exception as e:
                log.error(f"❌ Error descargando modelo: {e}")
                return False
        return True
    
    def _init_servos(self) -> None:
        """Inicializa los servos con los rangos correctos."""
        if not self.enable_servos:
            return
        
        try:
            for pin in (PIN_LH, PIN_LV, PIN_RH, PIN_RV, PIN_PARPADO_INF, 
                       PIN_PARPADO_SUP, PIN_CUELLO_YAW, PIN_CUELLO_PITCH,
                       PIN_ROLL_1, PIN_ROLL_2):
                kit.servo[pin].actuation_range = 180
                kit.servo[pin].set_pulse_width_range(600, 2350)
            
            # Párpados abiertos
            kit.servo[PIN_PARPADO_INF].angle = PARPADO_INF_ABIERTO
            kit.servo[PIN_PARPADO_SUP].angle = PARPADO_SUP_ABIERTO
            
            # Rolls fijos
            kit.servo[PIN_ROLL_1].angle = 40
            kit.servo[PIN_ROLL_2].angle = 85
            
            # Centrar todo
            self._center_all()
            time.sleep(0.5)
            
            log.info("✅ Servos inicializados")
        except Exception as e:
            log.error(f"❌ Error inicializando servos: {e}")
            self.enable_servos = False
    
    def _center_all(self) -> None:
        """Centra todos los servos."""
        if not self.enable_servos:
            return
        
        offset = self.cfg["OFFSET_X"]
        kit.servo[PIN_LH].angle = LH["mid"] + offset
        kit.servo[PIN_LV].angle = LV["mid"]
        kit.servo[PIN_RH].angle = RH["mid"] + offset
        kit.servo[PIN_RV].angle = RV["mid"]
        kit.servo[PIN_CUELLO_YAW].angle = CUELLO_YAW["mid"]
        kit.servo[PIN_CUELLO_PITCH].angle = CUELLO_PITCH["mid"]
    
    def _apply_eyes(self, lh: float, lv: float, rh: float, rv: float) -> None:
        """Aplica ángulos a los servos de los ojos."""
        if not self.enable_servos:
            return
        
        kit.servo[PIN_LH].angle = int(round(clamp(lh, LH["lo"], LH["hi"])))
        kit.servo[PIN_LV].angle = int(round(clamp(lv, LV["lo"], LV["hi"])))
        kit.servo[PIN_RH].angle = int(round(clamp(rh, RH["lo"], RH["hi"])))
        kit.servo[PIN_RV].angle = int(round(clamp(rv, RV["lo"], RV["hi"])))
    
    def _smooth_eyelid(self, target_angle_sup: int, target_angle_inf: int, steps: int = 6, delay: float = 0.012, is_closing: bool = True) -> None:
        """Mueve los párpados suavemente con interpolación gradual.
        
        Args:
            target_angle_sup: Ángulo objetivo superior (65 abierto, 95 cerrado)
            target_angle_inf: Ángulo objetivo inferior (40 abierto, 95 cerrado)
            steps: Número de pasos intermedios
            delay: Retardo entre pasos (ms)
            is_closing: True=cerrar (más rápido), False=abrir (más lento)
        """
        if not self.enable_servos:
            return
        
        current_sup = int(kit.servo[PIN_PARPADO_SUP].angle) if hasattr(kit.servo[PIN_PARPADO_SUP], 'angle') else PARPADO_SUP_ABIERTO
        current_inf = int(kit.servo[PIN_PARPADO_INF].angle) if hasattr(kit.servo[PIN_PARPADO_INF], 'angle') else PARPADO_INF_ABIERTO
        
        # Ajustar velocidad: cerrar es más rápido que abrir
        actual_delay = delay if is_closing else delay * 1.5
        
        for i in range(1, steps + 1):
            progress = i / steps
            # Interpolación no lineal (ease-out)
            smooth_progress = 1 - (1 - progress) ** 2
            
            # Superior cierra/abre primero (30ms de desfase)
            angle_sup = int(current_sup + (target_angle_sup - current_sup) * smooth_progress)
            kit.servo[PIN_PARPADO_SUP].angle = clamp(angle_sup, PARPADO_INF_ABIERTO, PARPADO_CERRADO)
            
            # Inferior con pequeño retardo
            if i > 1:  # Desfase de un paso
                angle_inf = int(current_inf + (target_angle_inf - current_inf) * smooth_progress)
                kit.servo[PIN_PARPADO_INF].angle = clamp(angle_inf, PARPADO_INF_ABIERTO, PARPADO_CERRADO)
            
            time.sleep(actual_delay)
    
    def _handle_blink(self, now: float) -> None:
        """Maneja el parpadeo asíncrono con movimientos suaves y timing realista."""
        if not self.enable_servos:
            return
        
        if self.blink_phase == "IDLE":
            if now > self.next_blink_time:
                # Decidir número de parpadeos (70% uno, 30% dos)
                self.blinks_to_do = 1 if random.random() < 0.7 else 2
                
                # Decidir intensidad: 80% completo, 20% parcial
                if random.random() < 0.8:
                    target_sup = PARPADO_CERRADO
                    target_inf = PARPADO_CERRADO
                else:
                    # Parpadeo parcial
                    target_sup = 75
                    target_inf = 60
                
                # Cerrar suavemente (rápido)
                self._smooth_eyelid(target_sup, target_inf, steps=5, delay=0.010, is_closing=True)
                
                # Tiempo variable de ojos cerrados (100-200ms normal, 10% más largo)
                closed_duration = random.uniform(0.10, 0.20) if random.random() < 0.9 else random.uniform(0.25, 0.35)
                
                self.blink_phase = "CLOSED"
                self.blink_state_end = now + closed_duration
        
        elif self.blink_phase == "CLOSED":
            if now > self.blink_state_end:
                # Abrir suavemente (más lento que cerrar) - valores seguros originales
                self._smooth_eyelid(PARPADO_SUP_ABIERTO, PARPADO_INF_ABIERTO, steps=6, delay=0.012, is_closing=False)
                
                self.blinks_to_do -= 1
                if self.blinks_to_do > 0:
                    self.blink_phase = "OPEN_WAIT"
                    # Espera entre parpadeos múltiples (200-500ms)
                    self.blink_state_end = now + random.uniform(0.20, 0.50)
                else:
                    self.blink_phase = "IDLE"
                    # Frecuencia más humana: 3-6 segundos (~12 parpadeos/min)
                    # Ocasionalmente crear clusters: 20% de las veces, parpadeo más rápido
                    if random.random() < 0.2:
                        self.next_blink_time = now + random.uniform(1.5, 3.0)  # Cluster
                    else:
                        self.next_blink_time = now + random.uniform(3.0, 6.0)  # Normal
        
        elif self.blink_phase == "OPEN_WAIT":
            if now > self.blink_state_end:
                # Cerrar nuevamente para siguiente parpadeo del cluster
                if random.random() < 0.8:
                    target_sup = PARPADO_CERRADO
                    target_inf = PARPADO_CERRADO
                else:
                    target_sup = 75
                    target_inf = 60
                
                self._smooth_eyelid(target_sup, target_inf, steps=5, delay=0.010, is_closing=True)
                
                closed_duration = random.uniform(0.10, 0.20)
                self.blink_phase = "CLOSED"
                self.blink_state_end = now + closed_duration
    
    def run(self) -> None:
        """Loop principal del thread de tracking."""
        log.info("🤖 EyeTrackerThread iniciando...")
        
        # Asegurar que el modelo existe
        if not self._ensure_model():
            self.shared_state.update_tracker_status(False, error="No se pudo cargar modelo YuNet")
            return
        
        # Abrir cámara
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        if not self.cap.isOpened():
            log.error("❌ No se pudo abrir la cámara")
            self.shared_state.update_tracker_status(False, error="No se pudo abrir la cámara")
            return
        
        log.info(f"✅ Cámara abierta en /dev/video{self.camera_index}")
        
        # Crear detector facial
        self.face_detector = cv2.FaceDetectorYN.create(
            str(MODEL_PATH), "", (640, 480),
            score_threshold=0.6, nms_threshold=0.3
        )
        
        # Inicializar servos
        self._init_servos()
        
        # Señalar que la cámara está lista
        self.shared_state.camera_ready.set()
        self.shared_state.update_tracker_status(True, fps=0.0, mode="idle")
        
        # Inicializar tiempos
        self.last_time = time.time()
        self.last_seen = time.time() * 1000.0
        self.fps_t = time.time()
        self.next_blink_time = time.time() + random.uniform(3.0, 6.0)
        
        log.info("🎯 Loop de tracking iniciado")
        
        try:
            while not self.shared_state.stop_requested.is_set():
                self._tracking_loop_iteration()
        
        except Exception as e:
            log.error(f"❌ Error en loop de tracking: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self._cleanup()
    
    def _tracking_loop_iteration(self) -> None:
        """Una iteración del loop de tracking."""
        ok, frame = self.cap.read()
        if not ok:
            return
        
        # Rotar frame (cámara rotada físicamente)
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        
        # Actualizar frame en SharedState para que otros threads lo usen
        self.shared_state.update_frame(frame)
        
        # Contadores de FPS
        self.frames += 1
        if self.frames % 30 == 0:
            elapsed = max(time.time() - self.fps_t, 1e-6)
            self.current_fps = 30.0 / elapsed
            self.fps_t = time.time()
        
        # Timing
        now = time.time()
        dt = max(1e-3, now - self.last_time)
        self.last_time = now
        now_ms = now * 1000.0
        
        # Parpadeo
        self._handle_blink(now)
        
        # Dimensiones del frame rotado
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        
        # Configurar detector con tamaño actual
        self.face_detector.setInputSize((w, h))
        
        # Detectar caras
        _, faces = self.face_detector.detect(frame)
        
        # Variables de control
        KP = self.cfg["KP"]
        KI = self.cfg["KI"]
        SMOOTH = self.cfg["SMOOTH"]
        OFFSET_X = self.cfg["OFFSET_X"]
        
        if faces is not None:
            self.centered = False
            self.returning = False
            self.active_search_mode = False  # Desactivar búsqueda activa si encontramos cara
            
            # Target Lock: seguir la cara más cercana a la última posición conocida
            best = None
            if self.tracked_face is not None:
                min_dist = float('inf')
                for f in faces:
                    fx_t = f[0] + f[2] // 2
                    fy_t = f[1] + f[3] // 2
                    dist = (fx_t - self.tracked_face[0])**2 + (fy_t - self.tracked_face[1])**2
                    if dist < min_dist:
                        min_dist = dist
                        best = f
            else:
                best = faces[faces[:, 14].argmax()]
                self.face_first_seen_time = now
            
            bx, by = int(best[0]), int(best[1])
            bw, bh = int(best[2]), int(best[3])
            fx, fy = bx + bw // 2, by + bh // 2
            
            self.tracked_face = (fx, fy)
            
            # Actualizar SharedState con detección
            self.shared_state.update_face_detection(
                detected=True,
                x=bx, y=by,
                width=bw, height=bh,
                confidence=float(best[14])
            )
            
            # Calcular error en píxeles con zona muerta
            epx = cx - fx
            epy = cy - fy
            if abs(epx) <= DEADBAND_X:
                epx = 0.0
            if abs(epy) <= DEADBAND_Y:
                epy = 0.0
            
            # Normalizar error [-1, +1]
            ex = epx / (w / 2.0)
            ey = epy / (h / 2.0)
            
            # PID (P + I)
            self.sum_ex = clamp(self.sum_ex + ex * dt, -I_CLAMP, I_CLAMP)
            self.sum_ey = clamp(self.sum_ey + ey * dt, -I_CLAMP, I_CLAMP)
            pid_x = KP * ex + KI * self.sum_ex
            pid_y = KP * ey + KI * self.sum_ey
            
            # Mapeo a ángulos
            half_h = (LH["hi"] - LH["lo"]) / 2.0
            t_lh = LH["mid"] + OFFSET_X + pid_x * half_h
            t_rh = RH["mid"] + OFFSET_X + pid_x * half_h
            
            half_lv = (LV["hi"] - LV["lo"]) / 2.0
            half_rv = (RV["hi"] - RV["lo"]) / 2.0
            t_lv = LV["mid"] + pid_y * half_lv
            t_rv = RV["mid"] - pid_y * half_rv  # Invertido
            
            # Suavizado EMA
            self.lh = SMOOTH * self.lh + (1 - SMOOTH) * t_lh
            self.lv = SMOOTH * self.lv + (1 - SMOOTH) * t_lv
            self.rh = SMOOTH * self.rh + (1 - SMOOTH) * t_rh
            self.rv = SMOOTH * self.rv + (1 - SMOOTH) * t_rv
            
            # Cuello lento (solo después de 2 segundos mirando la misma cara)
            if (now - self.face_first_seen_time) > 2.0:
                self.cuello_yaw_ang = clamp(
                    self.cuello_yaw_ang + (ex * 50.0 * dt),
                    CUELLO_YAW["lo"], CUELLO_YAW["hi"]
                )
                self.cuello_pitch_ang = clamp(
                    self.cuello_pitch_ang - (ey * 50.0 * dt),
                    CUELLO_PITCH["lo"], CUELLO_PITCH["hi"]
                )
                if self.enable_servos:
                    kit.servo[PIN_CUELLO_YAW].angle = int(self.cuello_yaw_ang)
                    kit.servo[PIN_CUELLO_PITCH].angle = int(self.cuello_pitch_ang)
            
            # Aplicar a servos
            self._apply_eyes(self.lh, self.lv, self.rh, self.rv)
            
            # Actualizar estado
            self.last_seen = now_ms
            self.dir_x = -1 if fx < cx else 1
            self.dir_y = -1 if fy < cy else 1
            
            # Actualizar SharedState
            self.shared_state.update_tracker_status(True, self.current_fps, "follow")
            self.shared_state.update_servo_positions(
                self.lh, self.lv, self.rh, self.rv,
                self.cuello_yaw_ang, self.cuello_pitch_ang
            )
        
        else:
            # No hay cara detectada
            dt_lost = now_ms - self.last_seen
            
            self.shared_state.update_face_detection(detected=False)
            
            if dt_lost > LOST_MS * 1.5:
                self.tracked_face = None
                self.face_first_seen_time = 0.0
            
            # ══════════════════════════════════════════════════════════════════
            # BÚSQUEDA ACTIVA: Girar cabeza después de 10 segundos sin rostro
            # Gira en intervalos de 5 segundos (izquierda/derecha alternando)
            # ══════════════════════════════════════════════════════════════════
            if dt_lost > ACTIVE_SEARCH_MS:
                if not self.active_search_mode:
                    # Iniciar búsqueda activa
                    self.active_search_mode = True
                    self.active_search_start_time = now_ms
                    
                    # Elegir dirección aleatoria (izquierda o derecha)
                    self.active_search_direction = random.choice([-1, 1])
                    
                    # Calcular ángulo objetivo (±40-50 grados desde el centro)
                    offset_angle = random.uniform(40, 50) * self.active_search_direction
                    self.active_search_target_yaw = clamp(
                        CUELLO_YAW["mid"] + offset_angle,
                        CUELLO_YAW["lo"],
                        CUELLO_YAW["hi"]
                    )
                    
                    direction_text = "izquierda" if self.active_search_direction == -1 else "derecha"
                    log.info(f"🔍 Búsqueda activa: girando cabeza a la {direction_text} (objetivo: {self.active_search_target_yaw:.1f}°)")
                
                # Ejecutar movimiento de búsqueda con intervalos de 5 segundos
                time_since_start = now_ms - self.active_search_start_time
                
                # Verificar si es momento de cambiar de dirección (cada 5 segundos)
                if time_since_start > ACTIVE_SEARCH_INTERVAL_MS:
                    # Cambiar al lado opuesto
                    self.active_search_direction *= -1
                    offset_angle = random.uniform(40, 50) * self.active_search_direction
                    self.active_search_target_yaw = clamp(
                        CUELLO_YAW["mid"] + offset_angle,
                        CUELLO_YAW["lo"],
                        CUELLO_YAW["hi"]
                    )
                    self.active_search_start_time = now_ms
                    
                    direction_text = "izquierda" if self.active_search_direction == -1 else "derecha"
                    log.debug(f"🔍 Búsqueda activa: cambiando a la {direction_text}")
                
                # Mover suavemente el cuello hacia el objetivo actual
                yaw_diff = self.active_search_target_yaw - self.cuello_yaw_ang
                
                if abs(yaw_diff) > 2:  # Si aún no llegamos al objetivo
                    # Movimiento suave hacia el objetivo
                    self.cuello_yaw_ang += yaw_diff * 0.08  # Factor de suavizado
                    
                    # Mover ojos en la misma dirección (buscando)
                    eye_offset = (self.cuello_yaw_ang - CUELLO_YAW["mid"]) * 0.3
                    self.lh = clamp(LH["mid"] + OFFSET_X + eye_offset, LH["lo"], LH["hi"])
                    self.rh = clamp(RH["mid"] + OFFSET_X + eye_offset, RH["lo"], RH["hi"])
                    
                    if self.enable_servos:
                        kit.servo[PIN_CUELLO_YAW].angle = int(self.cuello_yaw_ang)
                    
                    self._apply_eyes(self.lh, self.lv, self.rh, self.rv)
                
                self.shared_state.update_tracker_status(True, self.current_fps, "active_search")
            
            # Retorno al centro (> 4s sin cara, pero < 10s para no interferir con búsqueda activa)
            elif dt_lost > RETURN_MS and not self.centered:
                if not self.returning:
                    log.debug("⏺️ Sin rostro → volviendo al centro...")
                    self.returning = True
                
                dlh = (LH["mid"] + OFFSET_X) - self.lh
                dlv = LV["mid"] - self.lv
                drh = (RH["mid"] + OFFSET_X) - self.rh
                drv = RV["mid"] - self.rv
                dyaw = CUELLO_YAW["mid"] - self.cuello_yaw_ang
                dpitch = CUELLO_PITCH["mid"] - self.cuello_pitch_ang
                
                if max(abs(dlh), abs(dlv), abs(drh), abs(drv), abs(dyaw), abs(dpitch)) > 1:
                    self.lh += dlh * 0.15
                    self.lv += dlv * 0.15
                    self.rh += drh * 0.15
                    self.rv += drv * 0.15
                    self.cuello_yaw_ang += dyaw * 0.10
                    self.cuello_pitch_ang += dpitch * 0.10
                    
                    if self.enable_servos:
                        kit.servo[PIN_CUELLO_YAW].angle = int(self.cuello_yaw_ang)
                        kit.servo[PIN_CUELLO_PITCH].angle = int(self.cuello_pitch_ang)
                    
                    self._apply_eyes(self.lh, self.lv, self.rh, self.rv)
                else:
                    self._center_all()
                    self.lh = float(LH["mid"] + OFFSET_X)
                    self.lv = float(LV["mid"])
                    self.rh = float(RH["mid"] + OFFSET_X)
                    self.rv = float(RV["mid"])
                    self.cuello_yaw_ang = float(CUELLO_YAW["mid"])
                    self.cuello_pitch_ang = float(CUELLO_PITCH["mid"])
                    self.sum_ex = self.sum_ey = 0.0
                    self.dir_x = self.dir_y = 0
                    self.centered = True
                    self.returning = False
                    log.debug("✓ Centrado")
                
                self.shared_state.update_tracker_status(True, self.current_fps, "center")
            
            # Búsqueda (400ms - 4s sin cara)
            elif dt_lost > LOST_MS and (self.dir_x or self.dir_y) and not self.centered:
                if self.dir_x:
                    self.lh = clamp(self.lh - self.dir_x * SEARCH_DPS * dt, LH["lo"], LH["hi"])
                    self.rh = clamp(self.rh - self.dir_x * SEARCH_DPS * dt, RH["lo"], RH["hi"])
                if self.dir_y:
                    self.lv = clamp(self.lv - self.dir_y * SEARCH_DPS * dt, LV["lo"], LV["hi"])
                    self.rv = clamp(self.rv + self.dir_y * SEARCH_DPS * dt, RV["lo"], RV["hi"])
                
                self._apply_eyes(self.lh, self.lv, self.rh, self.rv)
                self.shared_state.update_tracker_status(True, self.current_fps, "search")
            
            else:
                self.shared_state.update_tracker_status(True, self.current_fps, "idle")
            
            # Actualizar posiciones de servos
            self.shared_state.update_servo_positions(
                self.lh, self.lv, self.rh, self.rv,
                self.cuello_yaw_ang, self.cuello_pitch_ang
            )
        
        # Mostrar ventana si no es headless (para debug)
        if not self.headless:
            cv2.line(frame, (cx, 0), (cx, h), (255, 0, 0), 1)
            cv2.line(frame, (0, cy), (w, cy), (255, 0, 0), 1)
            
            if faces is not None and best is not None:
                cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
                cv2.circle(frame, (fx, fy), 5, (0, 0, 255), -1)
            
            cv2.imshow("EyeTracker", frame)
            if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
                self.shared_state.request_stop()
        
        # ══════════════════════════════════════════════════════════════════════
        # OPTIMIZACIÓN: Limitar FPS para reducir carga de CPU
        # 15 FPS cuando hay cara (seguimiento), 10 FPS sin cara (búsqueda)
        # Esto reduce ~50% el uso de CPU sin afectar calidad de tracking
        # ══════════════════════════════════════════════════════════════════════
        if faces is not None:
            time.sleep(0.033)  # ~30 FPS con cara (antes: sin límite ~60+ FPS)
        else:
            time.sleep(0.066)  # ~15 FPS sin cara (ahorro máximo en idle)
    
    def _cleanup(self) -> None:
        """Limpieza al salir."""
        log.info("🔄 Limpiando EyeTrackerThread...")
        
        # Centrar servos
        if self.enable_servos:
            try:
                self._center_all()
                time.sleep(0.3)
            except Exception:
                pass
        
        # Liberar cámara
        if self.cap:
            self.cap.release()
        
        # Cerrar ventanas
        if not self.headless:
            cv2.destroyAllWindows()
        
        # Actualizar estado
        self.shared_state.camera_ready.clear()
        self.shared_state.update_tracker_status(False, mode="stopped")
        
        log.info("✅ EyeTrackerThread limpiado")
    
    def stop(self) -> None:
        """Solicita detener el thread de forma limpia."""
        self.shared_state.request_stop()


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN DE PRUEBA STANDALONE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Función de prueba para ejecutar el tracker de forma independiente."""
    print("🤖 Prueba de EyeTrackerThread")
    print("Press Ctrl+C para salir\n")
    
    shared_state = SharedState()
    tracker = EyeTrackerThread(
        shared_state=shared_state,
        camera_index=0,
        headless=False,  # Mostrar ventana para debug
        enable_servos=True
    )
    
    tracker.start()
    
    try:
        # Esperar a que la cámara esté lista
        if shared_state.wait_for_camera(timeout=10.0):
            print("✅ Cámara lista")
        else:
            print("❌ Timeout esperando cámara")
            return
        
        # Loop de monitoreo
        while tracker.is_alive():
            status = shared_state.get_tracker_status()
            face = shared_state.get_face_data()
            
            if face.detected:
                print(f"👤 Cara: ({face.center_x}, {face.center_y}) | "
                      f"FPS: {status['fps']:.1f} | Modo: {status['mode']}")
            else:
                print(f"⏳ Sin cara | FPS: {status['fps']:.1f} | Modo: {status['mode']}")
            
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo...")
    
    finally:
        tracker.stop()
        tracker.join(timeout=5.0)
        print("✅ Finalizado")


if __name__ == "__main__":
    main()
