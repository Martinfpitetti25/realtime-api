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
from collections import deque

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
        
        # Estado del parpadeo (gestionado por BlinkThread separado)
        self.blink_phase = "IDLE"
        self.next_blink_time = 0.0
        self.blink_state_end = 0.0
        self.blinks_to_do = 0
        self._blink_thread: Optional[threading.Thread] = None
        self._blink_stop = threading.Event()
        self._eyelid_lock = threading.Lock()  # Protege acceso a servos de párpados
        
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
        Seguro para llamar desde BlinkThread (usa _eyelid_lock).
        
        Args:
            target_angle_sup: Ángulo objetivo superior (65 abierto, 95 cerrado)
            target_angle_inf: Ángulo objetivo inferior (40 abierto, 95 cerrado)
            steps: Número de pasos intermedios
            delay: Retardo entre pasos (ms)
            is_closing: True=cerrar (más rápido), False=abrir (más lento)
        """
        if not self.enable_servos:
            return
        
        with self._eyelid_lock:
            current_sup = int(kit.servo[PIN_PARPADO_SUP].angle) if hasattr(kit.servo[PIN_PARPADO_SUP], 'angle') else PARPADO_SUP_ABIERTO
            current_inf = int(kit.servo[PIN_PARPADO_INF].angle) if hasattr(kit.servo[PIN_PARPADO_INF], 'angle') else PARPADO_INF_ABIERTO
        
        # Ajustar velocidad: cerrar es más rápido que abrir
        actual_delay = delay if is_closing else delay * 1.5
        
        for i in range(1, steps + 1):
            if self._blink_stop.is_set():
                return
            progress = i / steps
            # Interpolación no lineal (ease-out)
            smooth_progress = 1 - (1 - progress) ** 2
            
            with self._eyelid_lock:
                # Superior cierra/abre primero (30ms de desfase)
                angle_sup = int(current_sup + (target_angle_sup - current_sup) * smooth_progress)
                kit.servo[PIN_PARPADO_SUP].angle = clamp(angle_sup, PARPADO_INF_ABIERTO, PARPADO_CERRADO)
                
                # Inferior con pequeño retardo
                if i > 1:  # Desfase de un paso
                    angle_inf = int(current_inf + (target_angle_inf - current_inf) * smooth_progress)
                    kit.servo[PIN_PARPADO_INF].angle = clamp(angle_inf, PARPADO_INF_ABIERTO, PARPADO_CERRADO)
            
            time.sleep(actual_delay)
    
    def _blink_loop(self) -> None:
        """Loop del thread dedicado al parpadeo. No bloquea el tracking."""
        self.next_blink_time = time.time() + random.uniform(3.0, 6.0)
        
        while not self._blink_stop.is_set():
            now = time.time()
            
            if self.blink_phase == "IDLE":
                if now >= self.next_blink_time:
                    self.blinks_to_do = 1 if random.random() < 0.7 else 2
                    
                    if random.random() < 0.8:
                        target_sup = PARPADO_CERRADO
                        target_inf = PARPADO_CERRADO
                    else:
                        target_sup = 75
                        target_inf = 60
                    
                    self._smooth_eyelid(target_sup, target_inf, steps=5, delay=0.010, is_closing=True)
                    
                    closed_duration = random.uniform(0.10, 0.20) if random.random() < 0.9 else random.uniform(0.25, 0.35)
                    self.blink_phase = "CLOSED"
                    self.blink_state_end = time.time() + closed_duration
                else:
                    # Dormir hasta el próximo parpadeo (máx 100ms para responder al stop)
                    sleep_time = min(self.next_blink_time - now, 0.1)
                    time.sleep(max(sleep_time, 0))
                    continue
            
            elif self.blink_phase == "CLOSED":
                if time.time() >= self.blink_state_end:
                    self._smooth_eyelid(PARPADO_SUP_ABIERTO, PARPADO_INF_ABIERTO, steps=6, delay=0.012, is_closing=False)
                    
                    self.blinks_to_do -= 1
                    if self.blinks_to_do > 0:
                        self.blink_phase = "OPEN_WAIT"
                        self.blink_state_end = time.time() + random.uniform(0.20, 0.50)
                    else:
                        self.blink_phase = "IDLE"
                        if random.random() < 0.2:
                            self.next_blink_time = time.time() + random.uniform(1.5, 3.0)
                        else:
                            self.next_blink_time = time.time() + random.uniform(3.0, 6.0)
                else:
                    time.sleep(0.01)
                    continue
            
            elif self.blink_phase == "OPEN_WAIT":
                if time.time() >= self.blink_state_end:
                    if random.random() < 0.8:
                        target_sup = PARPADO_CERRADO
                        target_inf = PARPADO_CERRADO
                    else:
                        target_sup = 75
                        target_inf = 60
                    
                    self._smooth_eyelid(target_sup, target_inf, steps=5, delay=0.010, is_closing=True)
                    
                    closed_duration = random.uniform(0.10, 0.20)
                    self.blink_phase = "CLOSED"
                    self.blink_state_end = time.time() + closed_duration
                else:
                    time.sleep(0.01)
                    continue
            
            time.sleep(0.005)
    
    def _handle_blink(self, now: float) -> None:
        """Ya no bloquea el loop: el parpadeo corre en BlinkThread.
        Se mantiene por compatibilidad pero no hace nada."""
        pass

    def _open_camera(self, first_index: int) -> Optional[cv2.VideoCapture]:
        """Abre la cámara con retry en múltiples índices. Retorna cap abierto o None."""
        _try_indices = list(dict.fromkeys([first_index, 0, 1, 2]))
        for attempt in range(3):
            for idx in _try_indices:
                # Forzar V4L2 explícitamente: evita que el OpenCV del sistema
                # elija GStreamer por defecto, que falla con V4L2 posicional
                # y causa corrupción completa del frame ocasionalmente.
                _cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                # Resolución nativa del capturador: 720x480 (NTSC).
                # Pedir 640x480 causa mismatch de stride en YUYV 4:2:2
                # → artefactos de color y líneas horizontales partidas.
                _cap.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
                _cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                # Buffer 4: suficiente para que el driver procese YUYV completo
                # antes del siguiente read. Buffer=1 causaba frames incompletos.
                _cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
                if _cap.isOpened():
                    actual_w = int(_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    log.info(f"✅ Cámara abierta en índice {idx} — {actual_w}x{actual_h} (V4L2)")
                    return _cap
                _cap.release()
            if attempt < 2:
                log.warning(f"⚠️ Intento {attempt + 1}/3 fallido — reintentando en 2s...")
                time.sleep(2.0)
        return None

    def run(self) -> None:
        """Loop principal del thread de tracking."""
        log.info("🤖 EyeTrackerThread iniciando...")

        # Asegurar que el modelo existe
        if not self._ensure_model():
            self.shared_state.update_tracker_status(False, error="No se pudo cargar modelo YuNet")
            return

        # Abrir cámara
        self.cap = self._open_camera(self.camera_index)
        if self.cap is None:
            log.error("❌ No se pudo abrir la cámara tras 3 intentos")
            self.shared_state.update_tracker_status(False, error="No se pudo abrir la cámara")
            return

        # Crear detector facial
        self.face_detector = cv2.FaceDetectorYN.create(
            str(MODEL_PATH), "", (640, 480),
            score_threshold=0.6, nms_threshold=0.3
        )

        # Inicializar servos
        self._init_servos()

        # Arrancar thread dedicado al parpadeo
        if self.enable_servos:
            self._blink_stop.clear()
            self._blink_thread = threading.Thread(
                target=self._blink_loop,
                daemon=True,
                name="BlinkThread"
            )
            self._blink_thread.start()
            log.info("✅ BlinkThread iniciado")

        # Iniciar CameraReader: lee frames en su propio thread para no bloquear el loop
        import queue as _qmod
        self._frame_queue: _qmod.Queue = _qmod.Queue(maxsize=2)
        self._cam_reader_stop = threading.Event()

        _READER_TARGET_DT = 1.0 / 32.0  # Cap a 32fps: evita hammering del bus USB

        def _camera_reader_loop():
            while not self._cam_reader_stop.is_set():
                _t0 = time.time()
                if self.cap is None or not self.cap.isOpened():
                    time.sleep(0.05)
                    continue
                ok, frm = self.cap.read()
                if ok:
                    # Drop frame si la cola está llena (preferir frame fresco)
                    if self._frame_queue.full():
                        try:
                            self._frame_queue.get_nowait()
                        except Exception:
                            pass
                    try:
                        self._frame_queue.put_nowait(frm)
                    except Exception:
                        pass
                else:
                    time.sleep(0.01)
                    continue
                # Throttle: dormir el tiempo restante para no saturar el bus USB.
                # Sin esto el reader corre a ~200fps en el lock del driver,
                # causando spikes de bandwidth que rompen frames YUYV.
                _elapsed = time.time() - _t0
                _sleep = _READER_TARGET_DT - _elapsed
                if _sleep > 0.001:
                    time.sleep(_sleep)

        self._cam_reader_thread = threading.Thread(
            target=_camera_reader_loop,
            daemon=True,
            name="CameraReader"
        )
        self._cam_reader_thread.start()

        # Señalar que la cámara está lista
        self.shared_state.camera_ready.set()
        self.shared_state.update_tracker_status(True, fps=0.0, mode="idle")

        # Inicializar tiempos
        self.last_time = time.time()
        self.last_seen = time.time() * 1000.0
        self.fps_t = time.time()
        self._last_frame_time = time.time()  # Watchdog de stall

        log.info("🎯 Loop de tracking iniciado")

        try:
            while not self.shared_state.stop_requested.is_set():
                # Watchdog: si no llega ningún frame en 5s → reconectar cámara
                if time.time() - self._last_frame_time > 5.0:
                    log.warning("⚠️ Stall de cámara detectado (5s sin frames) — reconectando...")
                    old_cap = self.cap
                    self.cap = None
                    try:
                        old_cap.release()
                    except Exception:
                        pass
                    # Vaciar cola
                    while not self._frame_queue.empty():
                        try:
                            self._frame_queue.get_nowait()
                        except Exception:
                            break
                    time.sleep(1.0)
                    new_cap = self._open_camera(self.camera_index)
                    if new_cap is not None:
                        self.cap = new_cap
                        self._last_frame_time = time.time()
                        log.info("✅ Cámara reconectada")
                    else:
                        log.error("❌ No se pudo reconectar la cámara — esperando 5s...")
                        time.sleep(5.0)
                        self._last_frame_time = time.time()  # Reset para no spamear
                    continue

                self._tracking_loop_iteration()

        except Exception as e:
            log.error(f"❌ Error en loop de tracking: {e}")
            import traceback
            traceback.print_exc()

        finally:
            self._cam_reader_stop.set()
            self._cleanup()
    
    def _tracking_loop_iteration(self) -> None:
        """Una iteración del loop de tracking."""
        _TARGET_DT = 1.0 / 25.0  # Cap a 25 FPS
        _iter_start = time.time()

        # Leer frame de la cola del CameraReader (timeout 0.1s)
        try:
            frame = self._frame_queue.get(timeout=0.1)
            self._last_frame_time = time.time()  # Reset watchdog
        except Exception:
            # No hay frame nuevo — el watchdog en run() maneja el stall si persiste
            return
        
        # Actualizar frame en SharedState ANTES de rotar (sin copia extra)
        # La rotación solo se aplica para mostrar en pantalla (headless=False)
        self.shared_state.update_frame(frame)
        
        # Rotar solo para display y detección facial (cámara rotada físicamente)
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        
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
        
        # Componer frame anotado y publicarlo en SharedState.
        # PreviewThread (hilo separado) lo leerá y llamará cv2.imshow — nunca desde aquí.
        display = frame.copy()
        cv2.line(display, (cx, 0), (cx, h), (255, 0, 0), 1)
        cv2.line(display, (0, cy), (w, cy), (255, 0, 0), 1)
        if faces is not None and best is not None:
            cv2.rectangle(display, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
            cv2.circle(display, (fx, fy), 5, (0, 0, 255), -1)
        status_text = f"FPS:{self.current_fps:.1f}"
        cv2.putText(display, status_text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        self.shared_state.update_display_frame(display)

        # Cap a 25 FPS: dormir el tiempo restante de la iteración
        _elapsed = time.time() - _iter_start
        _sleep = _TARGET_DT - _elapsed
        if _sleep > 0.001:
            time.sleep(_sleep)
        

    
    def _cleanup(self) -> None:
        """Limpieza al salir."""
        log.info("🔄 Limpiando EyeTrackerThread...")
        
        # Detener BlinkThread
        self._blink_stop.set()
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1.0)
        
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

        # Las ventanas OpenCV las cierra PreviewThread (no llamar destroyAllWindows aquí)
        
        # Actualizar estado
        self.shared_state.camera_ready.clear()
        self.shared_state.update_tracker_status(False, mode="stopped")
        
        log.info("✅ EyeTrackerThread limpiado")
    
    def stop(self) -> None:
        """Solicita detener el thread de forma limpia."""
        self.shared_state.request_stop()


# ══════════════════════════════════════════════════════════════════════════════
# PREVIEW THREAD — muestra la ventana OpenCV de forma desacoplada del tracker
# ══════════════════════════════════════════════════════════════════════════════

class PreviewThread(threading.Thread):
    """
    Thread dedicado a mostrar el preview de la cámara con anotaciones.

    Completamente desacoplado de EyeTrackerThread: lee el frame anotado del
    SharedState a ~15 FPS y llama cv2.imshow/cv2.waitKey desde su propio
    contexto, evitando que la detección YuNet congele el display.
    """

    def __init__(self, shared_state: SharedState, fps: int = 15):
        super().__init__(daemon=True, name="PreviewThread")
        self.shared_state = shared_state
        self.target_dt = 1.0 / fps
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Señala al thread que debe detenerse."""
        self._stop_event.set()

    def run(self) -> None:
        log.info("🖥️ PreviewThread iniciado")
        window_name = "EyeTracker"

        # CRÍTICO en Linux/GTK: habilita highgui desde threads de fondo
        try:
            cv2.startWindowThread()
        except Exception:
            pass

        # Crear ventana desde este thread
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window_name, 480, 640)
            log.info("🖥️ Ventana EyeTracker creada")
        except Exception as e:
            log.warning(f"PreviewThread: namedWindow error: {e}")

        no_frame_count = 0

        while not self._stop_event.is_set() and not self.shared_state.stop_requested.is_set():
            t0 = time.time()

            success, frame, age = self.shared_state.get_display_frame()

            if success and frame is not None and age < 1.5:
                no_frame_count = 0
                try:
                    cv2.imshow(window_name, frame)
                except Exception as e:
                    log.debug(f"PreviewThread imshow error: {e}")
                    # No hacer break — reintentar en el siguiente ciclo
            else:
                no_frame_count += 1
                # Sin frame por más de 5 segundos: loguear una vez y esperar
                if no_frame_count == 75:  # ~5s a 15fps
                    log.warning("⚠️ PreviewThread: sin frames del tracker por 5s")

            # waitKey SIEMPRE: procesa eventos de ventana aunque no haya frame nuevo
            try:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    self.shared_state.request_stop()
                    break
            except Exception:
                pass

            elapsed = time.time() - t0
            sleep_t = self.target_dt - elapsed
            if sleep_t > 0.001:
                time.sleep(sleep_t)

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        log.info("🖥️ PreviewThread detenido")


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
