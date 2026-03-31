"""
FollowerTestNuevo.py - Test de seguimiento facial: ojos + párpados + cuello
Para Raspberry Pi 5 con PCA9685 (servo driver I2C) + cámara

Fusión adaptada de:
  - CameraProcessor.py  (detección facial con MediaPipe)
  - FollowerBotPicoCode.py (control de servos para tracking)

Controles:
  ESC = salir
  C   = recalibrar servos al centro

NOTA: Los "pines" de la tabla corresponden a CANALES del PCA9685.
"""

import cv2
import mediapipe as mp
import time
import random

# ============================================================
# HARDWARE: PCA9685 Servo Driver
# ============================================================
try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16)
    SERVO_HW = True
    print("[OK] PCA9685 detectado - servos activos")
except Exception as e:
    kit = None
    SERVO_HW = False
    print(f"[WARN] PCA9685 no disponible ({e}) - modo simulación (solo cámara)")

# ============================================================
# CONFIGURACIÓN DE SERVOS
# Según tabla de especificaciones del robot.
# "ch" = canal del PCA9685, "min"/"max" = límites mecánicos,
# "center" = posición neutra.
# ============================================================
SERVOS = {
    # --- Ojos horizontales (izquierda-derecha) ---
    # Ambos: 40 = mirar a su derecha, 120 = mirar a su izquierda
    "ojo_der_h": {"ch": 6,  "min": 40,  "max": 120, "center": 80},
    "ojo_izq_h": {"ch": 11, "min": 40,  "max": 120, "center": 80},

    # --- Ojos verticales (arriba-abajo) ---
    # ojo_der_v: 70 = arriba, 90 = abajo  (valor BAJA para mirar arriba)
    # ojo_izq_v: 105 = arriba, 95 = abajo (valor SUBE para mirar arriba)
    "ojo_der_v": {"ch": 7,  "min": 70,  "max": 90,  "center": 80},
    "ojo_izq_v": {"ch": 10, "min": 85,  "max": 105, "center": 95},

    # --- Párpados ---
    # 40 = abierto, 85 = cerrado
    "parpado_sup": {"ch": 8,  "min": 40, "max": 85, "center": 40},
    "parpado_inf": {"ch": 9,  "min": 40, "max": 85, "center": 40},

    # --- Cuello ---
    # yaw: 50 = mirar izquierda, 150 = mirar derecha, centro = 100
    "cuello_yaw":    {"ch": 13, "min": 50,  "max": 150, "center": 100},
    # pitch: ⚠️ SIN DATOS CONFIRMADOS - ajustar manualmente
    "cuello_pitch":  {"ch": 14, "min": 60,  "max": 120, "center": 90},
    # rolls: 40 = roll abajo, 120 = roll arriba
    "cuello_roll_d": {"ch": 12, "min": 40,  "max": 120, "center": 90},
    "cuello_roll_i": {"ch": 15, "min": 40,  "max": 120, "center": 90},
}

# ============================================================
# PARÁMETROS DE TRACKING
# ============================================================
DEADZONE_EYE = 25       # Píxeles de zona muerta para ojos
DEADZONE_NECK = 15      # Grados de desvío del centro para activar cuello
NECK_DELAY_S = 1.2      # Segundos que los ojos deben estar descentrados antes de mover cuello
KP_H = 0.03             # Ganancia proporcional horizontal (rango 80°)
KP_V = 0.08             # Ganancia proporcional vertical (rango ~20°, necesita más)
NECK_SPEED = 50          # Grados/segundo para movimiento suave del cuello
NECK_PITCH_ENABLED = False  # Desactivado hasta calibrar cuello_pitch
BLINK_PROB = 1 / 60     # ~1.6% probabilidad de parpadeo por ciclo

# ============================================================
# CONFIGURACIÓN DE CÁMARA
# ============================================================
CAMERA_INDEX = 0         # 0 = default, 1 = USB externa, etc.
ROTATE_180 = False       # True si la cámara está montada al revés
FLIP_HORIZONTAL = False  # True para efecto espejo (invertirá el tracking horizontal)

# ============================================================
# ESTADO INTERNO
# ============================================================
pos = {name: float(cfg["center"]) for name, cfg in SERVOS.items()}

neck_tgt = {
    "cuello_yaw":   SERVOS["cuello_yaw"]["center"],
    "cuello_pitch":  SERVOS["cuello_pitch"]["center"],
}
neck_flag = False
neck_trigger_time = 0.0
last_neck_update = time.time()


# ============================================================
# FUNCIONES DE SERVO
# ============================================================
def write_servo(name, angle):
    """Escribe un ángulo al servo, clampeando a sus límites."""
    cfg = SERVOS[name]
    angle = max(cfg["min"], min(cfg["max"], angle))
    pos[name] = float(angle)
    if SERVO_HW and kit:
        try:
            kit.servo[cfg["ch"]].angle = int(angle)
        except Exception as e:
            print(f"[ERR] Servo {name} (ch{cfg['ch']}): {e}")


def calibrate():
    """Pone todos los servos en su posición central."""
    print("[CAL] Centrando todos los servos...")
    for name, cfg in SERVOS.items():
        write_servo(name, cfg["center"])
    time.sleep(0.5)
    print("[CAL] Listo")


# ============================================================
# MOVIMIENTO DE OJOS
# ============================================================
def move_eye_h(error_x):
    """Mueve ambos ojos horizontalmente.

    La cámara está en la cara del robot mirando a la persona:
      error_x > 0 → cara a la IZQUIERDA del frame → mirar izquierda → valor SUBE (→120)
      error_x < 0 → cara a la DERECHA del frame  → mirar derecha   → valor BAJA (→40)

    Ambos ojos se mueven en la misma dirección.
    """
    if abs(error_x) <= DEADZONE_EYE:
        return

    step = KP_H * error_x
    if abs(step) < 1:
        step = 1.0 if error_x > 0 else -1.0

    write_servo("ojo_der_h", pos["ojo_der_h"] + step)
    write_servo("ojo_izq_h", pos["ojo_izq_h"] + step)


def move_eye_v(error_y):
    """Mueve ambos ojos verticalmente.

      error_y > 0 → cara ARRIBA del centro → mirar arriba
      error_y < 0 → cara ABAJO             → mirar abajo

    ¡DIRECCIONES OPUESTAS entre ojos!
      ojo_der_v: 70 = arriba → para subir, RESTAR  (paso negativo)
      ojo_izq_v: 105 = arriba → para subir, SUMAR (paso positivo)
    """
    if abs(error_y) <= DEADZONE_EYE:
        return

    step = KP_V * error_y
    if abs(step) < 1:
        step = 1.0 if error_y > 0 else -1.0

    # Ojo derecho: invertido (arriba = valor menor)
    write_servo("ojo_der_v", pos["ojo_der_v"] - step)
    # Ojo izquierdo: normal (arriba = valor mayor)
    write_servo("ojo_izq_v", pos["ojo_izq_v"] + step)


# ============================================================
# PÁRPADOS
# ============================================================
def blink():
    """Parpadeo rápido: cierra y abre."""
    write_servo("parpado_sup", SERVOS["parpado_sup"]["max"])
    write_servo("parpado_inf", SERVOS["parpado_inf"]["max"])
    time.sleep(0.06)
    lid_sync()


def lid_sync():
    """Sincroniza apertura de párpados con la posición vertical de los ojos.

    Cuando los ojos miran hacia abajo, los párpados se cierran parcialmente
    (comportamiento humano natural).
    """
    dcfg = SERVOS["ojo_der_v"]
    icfg = SERVOS["ojo_izq_v"]

    # Normalizar "cuánto miran abajo": 0.0 = mirando arriba, 1.0 = mirando abajo
    # ojo_der_v: 70=arriba(0), 90=abajo(1)
    der_down = (pos["ojo_der_v"] - dcfg["min"]) / (dcfg["max"] - dcfg["min"])
    # ojo_izq_v: 105=arriba(0), 85=abajo(1) → invertido
    izq_down = (icfg["max"] - pos["ojo_izq_v"]) / (icfg["max"] - icfg["min"])

    down_avg = (der_down + izq_down) / 2.0

    # Párpados: min=40 (abierto), max=85 (cerrado)
    # Se cierran parcialmente proporcional a cuánto se mira abajo
    sup_cfg = SERVOS["parpado_sup"]
    inf_cfg = SERVOS["parpado_inf"]

    sup_target = sup_cfg["min"] + (sup_cfg["max"] - sup_cfg["min"]) * 0.35 * down_avg
    inf_target = inf_cfg["min"] + (inf_cfg["max"] - inf_cfg["min"]) * 0.25 * down_avg

    write_servo("parpado_sup", int(sup_target))
    write_servo("parpado_inf", int(inf_target))


# ============================================================
# CUELLO
# ============================================================
def update_neck_target():
    """Calcula el target del cuello basándose en la posición actual de los ojos.

    Horizontal (yaw):
      Ojos: 40=derecha, 120=izquierda, centro=80
      Cuello: 150=derecha, 50=izquierda, centro=100
      → Mapeo INVERTIDO: cuando ojos están en valor bajo (derecha),
        cuello va a valor alto (derecha).

    Vertical (pitch): solo si NECK_PITCH_ENABLED.
    """
    # --- Yaw (horizontal) ---
    avg_h = (pos["ojo_der_h"] + pos["ojo_izq_h"]) / 2.0
    eye_min, eye_max = 40.0, 120.0
    neck_min = float(SERVOS["cuello_yaw"]["min"])   # 50
    neck_max = float(SERVOS["cuello_yaw"]["max"])    # 150

    # ratio: 0.0 = ojos full derecha, 1.0 = ojos full izquierda
    ratio = (avg_h - eye_min) / (eye_max - eye_min)
    # Invertir: cuando ratio=0 (ojos derecha), cuello debe ir a max (derecha)
    yaw_target = neck_max - ratio * (neck_max - neck_min)
    neck_tgt["cuello_yaw"] = yaw_target

    # --- Pitch (vertical) ---
    if NECK_PITCH_ENABLED:
        dcfg = SERVOS["ojo_der_v"]
        icfg = SERVOS["ojo_izq_v"]

        # Normalizar a 0=abajo, 1=arriba
        der_up = (dcfg["max"] - pos["ojo_der_v"]) / (dcfg["max"] - dcfg["min"])
        izq_up = (pos["ojo_izq_v"] - icfg["min"]) / (icfg["max"] - icfg["min"])
        avg_up = (der_up + izq_up) / 2.0  # 0=abajo, 0.5=centro, 1=arriba

        pcfg = SERVOS["cuello_pitch"]
        pitch_range = pcfg["max"] - pcfg["min"]
        # El cuello sigue el 60% del movimiento vertical (como el original)
        pitch_target = pcfg["center"] + (avg_up - 0.5) * pitch_range * 0.6
        neck_tgt["cuello_pitch"] = pitch_target


def neck_smooth_move():
    """Mueve el cuello suavemente hacia sus targets a velocidad constante."""
    global last_neck_update

    now = time.time()
    dt = now - last_neck_update
    last_neck_update = now

    step_max = NECK_SPEED * dt

    # Yaw siempre activo
    axes = ["cuello_yaw"]
    if NECK_PITCH_ENABLED:
        axes.append("cuello_pitch")

    for axis in axes:
        diff = neck_tgt[axis] - pos[axis]
        if abs(diff) <= step_max:
            write_servo(axis, neck_tgt[axis])
        else:
            direction = 1.0 if diff > 0 else -1.0
            write_servo(axis, pos[axis] + direction * step_max)


def check_neck_trigger():
    """Activa movimiento del cuello si los ojos permanecen descentrados por más de NECK_DELAY_S."""
    global neck_flag, neck_trigger_time

    # Desviación horizontal promedio
    avg_h = (pos["ojo_der_h"] + pos["ojo_izq_h"]) / 2.0
    h_dev = abs(avg_h - SERVOS["ojo_der_h"]["center"])

    # Desviación vertical (la mayor de ambos ojos)
    der_v_dev = abs(pos["ojo_der_v"] - SERVOS["ojo_der_v"]["center"])
    izq_v_dev = abs(pos["ojo_izq_v"] - SERVOS["ojo_izq_v"]["center"])
    v_dev = max(der_v_dev, izq_v_dev)

    if h_dev >= DEADZONE_NECK or v_dev >= DEADZONE_NECK:
        if not neck_flag:
            neck_trigger_time = time.time()
            neck_flag = True
        elif (time.time() - neck_trigger_time) >= NECK_DELAY_S:
            update_neck_target()
            neck_flag = False
    else:
        neck_flag = False


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================
def main():
    print("=" * 55)
    print("  FOLLOWER TEST NUEVO")
    print("  Seguimiento facial: ojos + párpados + cuello")
    print("  Hardware:", "PCA9685 activo" if SERVO_HW else "SIMULACIÓN")
    print("=" * 55)
    print("  ESC = salir | C = recalibrar")
    print()

    # Calibrar todos los servos al centro
    calibrate()

    # MediaPipe Face Detection
    mp_face = mp.solutions.face_detection
    mp_draw = mp.solutions.drawing_utils

    # Cámara
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[ERR] No se pudo abrir la cámara (índice {CAMERA_INDEX})")
        return

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    center_x = frame_w // 2
    center_y = frame_h // 2
    print(f"[OK] Cámara abierta: {frame_w}x{frame_h}")
    print()

    last_send = 0.0

    with mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5) as face_det:
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Transformaciones según montaje físico de la cámara
                if ROTATE_180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                if FLIP_HORIZONTAL:
                    frame = cv2.flip(frame, 1)

                # Detección facial
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_det.process(rgb)

                error_x = 0
                error_y = 0
                face_detected = False

                if results.detections:
                    detection = results.detections[0]
                    mp_draw.draw_detection(frame, detection)

                    bbox = detection.location_data.relative_bounding_box
                    face_x = int((bbox.xmin + bbox.width / 2) * frame_w)
                    face_y = int((bbox.ymin + bbox.height / 2) * frame_h)

                    error_x = center_x - face_x
                    error_y = center_y - face_y
                    face_detected = True

                    # Marker en centro de la cara
                    cv2.circle(frame, (face_x, face_y), 5, (0, 0, 255), -1)

                # ---- Control de servos ----
                now = time.time()
                if face_detected and (now - last_send) >= 0.01:  # 100 Hz max
                    move_eye_h(error_x)
                    move_eye_v(error_y)
                    last_send = now

                    # Parpadeo aleatorio
                    if random.random() < BLINK_PROB:
                        blink()
                        time.sleep(0.06)

                # Sincronizar párpados con posición de ojos (siempre)
                lid_sync()

                # Cuello: verificar trigger + mover suavemente
                check_neck_trigger()
                neck_smooth_move()

                # ---- HUD (información en pantalla) ----
                # Cruceta central
                cv2.drawMarker(frame, (center_x, center_y),
                               (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

                if face_detected:
                    cv2.putText(frame,
                                f"Error: X={error_x:+d}  Y={error_y:+d}",
                                (10, frame_h - 45),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                # Posiciones de servos de ojos
                cv2.putText(frame,
                            f"OjoH: D={pos['ojo_der_h']:.0f} I={pos['ojo_izq_h']:.0f}  |  "
                            f"OjoV: D={pos['ojo_der_v']:.0f} I={pos['ojo_izq_v']:.0f}",
                            (10, frame_h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

                # Posiciones del cuello
                cv2.putText(frame,
                            f"Cuello: Yaw={pos['cuello_yaw']:.0f}  "
                            f"Pitch={pos['cuello_pitch']:.0f}",
                            (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                # Indicador de hardware
                hw_color = (0, 255, 0) if SERVO_HW else (0, 0, 255)
                hw_text = "HW: ON" if SERVO_HW else "HW: SIM"
                cv2.putText(frame, hw_text, (frame_w - 110, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, hw_color, 1)

                # Indicador de cuello activo
                if neck_flag:
                    elapsed = time.time() - neck_trigger_time
                    cv2.putText(frame,
                                f"Cuello en {NECK_DELAY_S - elapsed:.1f}s",
                                (frame_w - 180, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

                cv2.imshow("Follower Test Nuevo", frame)

                # Controles de teclado
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC = salir
                    break
                elif key == ord('c') or key == ord('C'):  # C = recalibrar
                    calibrate()
                    neck_tgt["cuello_yaw"] = SERVOS["cuello_yaw"]["center"]
                    neck_tgt["cuello_pitch"] = SERVOS["cuello_pitch"]["center"]
                    print("[INFO] Recalibrado")

        except KeyboardInterrupt:
            print("\n[INFO] Interrumpido por usuario")

        finally:
            print("[INFO] Cerrando...")
            calibrate()  # Centrar servos antes de apagar
            cap.release()
            cv2.destroyAllWindows()
            print("[OK] Finalizado")


if __name__ == "__main__":
    main()
