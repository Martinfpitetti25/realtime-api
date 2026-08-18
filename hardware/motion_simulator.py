#!/usr/bin/env python3
"""
MotionSimulator - Movimiento natural simulado para cuando no hay tracking facial
================================================================================
Genera movimiento orgánico de alta fidelidad para el robot InMoov.

Mejoras v2 sobre v1:
  [1] Microsácadas involuntarias (cada 0.5-2s, amplitud 1-3°)
      Los ojos nunca se ven "congelados" entre sácadas grandes.
  [3] Virtual target con física de seguimiento
      Un punto de atención ficticio se mueve con inercia (partícula con
      fricción). Los ojos persiguen ese punto con retardo, dando la
      sensación de estar mirando algo real.
  [6] Coordinación cuello-ojo realista (VOR — reflejo vestíbulo-ocular)
      La cabeza se mueve primero; los ojos compensan en dirección opuesta
      para estabilizar la mirada. Efecto: movimiento "vertebrado".
  [8] Respiración simulada
      Onda lenta de 0.25 Hz en pitch del cuello (±1.5°). Sutil pero muy
      notoria cuando se combina con los demás movimientos.
  +   Acoplamiento párpado-ojo vertical (cuando los ojos miran abajo,
      el párpado superior baja ligeramente — fisiología real).

Zonas seguras (subconjunto conservador de los límites reales):
  Ojos H:       65-115  (real: 40-130, mid:  90)
  Ojos V:       83-100  (real: 80-105, mid:  90)
  Cuello Yaw:   80-120  (real: 50-150, mid: 100)
  Cuello Pitch: 105-140 (real:  60-180, mid: 120)
"""

import threading
import time
import random
import math
from typing import Optional

try:
    from utils.logger import get_logger
    log = get_logger('motion_sim')
except ImportError:
    import logging
    log = logging.getLogger('motion_sim')
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(logging.StreamHandler())

# ── Importar ServoKit compartido con EyeTrackerThread ──────────────────────
try:
    from hardware.eye_tracker_thread import (
        kit, SERVO_AVAILABLE,
        PIN_LH, PIN_LV, PIN_RH, PIN_RV,
        PIN_PARPADO_INF, PIN_PARPADO_SUP,
        PIN_CUELLO_YAW, PIN_CUELLO_PITCH,
        PARPADO_INF_ABIERTO, PARPADO_SUP_ABIERTO, PARPADO_CERRADO,
        clamp,
    )
    HARDWARE_AVAILABLE = SERVO_AVAILABLE and (kit is not None)
except ImportError as _e:
    HARDWARE_AVAILABLE = False
    kit = None
    log.warning(f"⚠️ eye_tracker_thread no disponible: {_e} — modo dry-run")

    PIN_LH = PIN_LV = PIN_RH = PIN_RV = 0
    PIN_PARPADO_INF = PIN_PARPADO_SUP = 0
    PIN_CUELLO_YAW = PIN_CUELLO_PITCH = 0
    PARPADO_INF_ABIERTO = 40
    PARPADO_SUP_ABIERTO = 65
    PARPADO_CERRADO = 95

    def clamp(v, lo, hi):           # type: ignore[misc]
        return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════
# ZONAS SEGURAS
# ═══════════════════════════════════════════════════════════════════════════
SIM_EYE_H_LO     = 65;   SIM_EYE_H_HI     = 115;  SIM_EYE_H_MID    = 90
SIM_EYE_V_LO     = 83;   SIM_EYE_V_HI     = 100;  SIM_EYE_V_MID    = 90
SIM_NECK_YAW_LO  = 80;   SIM_NECK_YAW_HI  = 120;  SIM_NECK_YAW_MID = 100
SIM_NECK_PITCH_LO= 105;  SIM_NECK_PITCH_HI= 140;  SIM_NECK_PITCH_MID=120

# Margen interior para el virtual target (evita que la partícula llegue al límite)
_TGT_H_LO = SIM_EYE_H_LO + 5;  _TGT_H_HI = SIM_EYE_H_HI - 5
_TGT_V_LO = SIM_EYE_V_LO + 2;  _TGT_V_HI = SIM_EYE_V_HI - 2


class MotionSimulator(threading.Thread):
    """
    Thread de simulación de movimiento natural del robot InMoov v2.

    Loop a 50 Hz (TICK = 0.02 s) para mayor suavidad:
      1. Virtual target (partícula con inercia) → base de atención
      2. Sácada grande (cada 4-14 s) → salto de atención brusco
      3. Microsácada involuntaria (cada 0.5-2 s, ±1-3°) → micro-temblor ocular
      4. Respiración: onda 0.25 Hz en pitch del cuello
      5. Filtro paso-bajo en ojos → seguimiento suave del target
      6. VOR: cuello se mueve primero; ojos compensan en sentido contrario
      7. Acoplamiento párpado-ojo: párpado baja levemente al mirar abajo
      8. Parpadeo realista en sub-thread
    """

    TICK = 0.02          # 50 Hz — el doble que v1 para mayor suavidad

    # ── Física del virtual target ────────────────────────────────────────
    _FRICTION     = 0.88  # Factor de desaceleración por tick (< 1 → frena)
    _RAND_FORCE   = 0.12  # Amplitud de la fuerza aleatoria por tick (°)
    _ATTRACT      = 0.006 # Fuerza de atracción al centro (evita deriva al borde)

    # ── Seguimiento ojo→target ───────────────────────────────────────────
    _EYE_LP       = 0.18  # Coeficiente del filtro paso-bajo de ojos

    # ── VOR: cuello ─────────────────────────────────────────────────────
    # El cuello sigue al target (no al ojo) — los ojos compensan
    _NECK_LP      = 0.025  # Inercia del cuello (mucho más lento que ojos)
    _VOR_GAIN     = 0.40   # Cuánto compensan los ojos al movimiento del cuello

    # ── Respiración ─────────────────────────────────────────────────────
    _BREATH_FREQ  = 0.25   # Hz (~15 resp/min — reposo)
    _BREATH_AMP   = 1.5    # Amplitud en grados del cuello pitch

    # ── Microsácadas ────────────────────────────────────────────────────
    _MSACC_AMP    = 2.5    # Amplitud máxima (°)
    _MSACC_DUR    = 0.035  # Duración (s) — muy rápidas

    def __init__(self) -> None:
        super().__init__(daemon=True, name="MotionSimulator")
        self._stop     = threading.Event()
        self.hardware  = HARDWARE_AVAILABLE

        # ── Posición actual (ojos y cuello) ──────────────────────────────
        self.eye_h      = float(SIM_EYE_H_MID)
        self.eye_v      = float(SIM_EYE_V_MID)
        self.neck_yaw   = float(SIM_NECK_YAW_MID)
        self.neck_pitch = float(SIM_NECK_PITCH_MID)

        # ── Virtual target (partícula 2D) ─────────────────────────────────
        self._tgt_h  = float(SIM_EYE_H_MID)   # posición
        self._tgt_v  = float(SIM_EYE_V_MID)
        self._vel_h  = 0.0                      # velocidad
        self._vel_v  = 0.0

        # ── Sácadas grandes ───────────────────────────────────────────────
        self._sacc_active   = False
        self._sacc_origin_h = float(SIM_EYE_H_MID)
        self._sacc_origin_v = float(SIM_EYE_V_MID)
        self._sacc_target_h = float(SIM_EYE_H_MID)
        self._sacc_target_v = float(SIM_EYE_V_MID)
        self._sacc_start    = 0.0
        self._sacc_dur      = 0.12
        self._next_sacc     = 0.0

        # ── Microsácadas ──────────────────────────────────────────────────
        self._msacc_active   = False
        self._msacc_offset_h = 0.0
        self._msacc_offset_v = 0.0
        self._msacc_start    = 0.0
        self._next_msacc     = 0.0

        # ── Parpadeo ──────────────────────────────────────────────────────
        self._blink_thread: Optional[threading.Thread] = None
        self._next_blink   = 0.0
        self._eyelid_angle = float(PARPADO_SUP_ABIERTO)  # estado actual del párpado

        log.info(f"MotionSimulator v2 — hardware: {'SÍ' if self.hardware else 'NO (dry-run)'}")

    # ════════════════════════════════════════════════════════════════════════
    # HARDWARE
    # ════════════════════════════════════════════════════════════════════════

    def _init_hw(self) -> None:
        if not self.hardware:
            return
        try:
            for pin in (PIN_LH, PIN_LV, PIN_RH, PIN_RV,
                        PIN_PARPADO_INF, PIN_PARPADO_SUP,
                        PIN_CUELLO_YAW, PIN_CUELLO_PITCH):
                kit.servo[pin].actuation_range = 180
                kit.servo[pin].set_pulse_width_range(600, 2350)
            kit.servo[PIN_PARPADO_SUP].angle = PARPADO_SUP_ABIERTO
            kit.servo[PIN_PARPADO_INF].angle = PARPADO_INF_ABIERTO
            log.info("✅ Servos inicializados")
        except Exception as e:
            log.warning(f"_init_hw: {e}")

    def _write_servos(self,
                      h: float, v: float,
                      yaw: float, pitch: float,
                      eyelid: float) -> None:
        """Escribe ojos, cuello y párpados en un solo ciclo I2C."""
        if not self.hardware:
            return
        try:
            hi   = int(round(clamp(h,      SIM_EYE_H_LO,      SIM_EYE_H_HI)))
            vi   = int(round(clamp(v,      SIM_EYE_V_LO,      SIM_EYE_V_HI)))
            yi   = int(round(clamp(yaw,    SIM_NECK_YAW_LO,   SIM_NECK_YAW_HI)))
            pi_  = int(round(clamp(pitch,  SIM_NECK_PITCH_LO, SIM_NECK_PITCH_HI)))
            eli  = int(round(clamp(eyelid, PARPADO_SUP_ABIERTO, PARPADO_CERRADO)))
            kit.servo[PIN_LH].angle           = hi
            kit.servo[PIN_RH].angle           = hi
            kit.servo[PIN_LV].angle           = vi
            kit.servo[PIN_RV].angle           = vi
            kit.servo[PIN_CUELLO_YAW].angle   = yi
            kit.servo[PIN_CUELLO_PITCH].angle = pi_
            kit.servo[PIN_PARPADO_SUP].angle  = eli
            # Párpado inferior: acoplamiento 80% del superior
            eli_inf = int(round(clamp(
                PARPADO_INF_ABIERTO + (eli - PARPADO_SUP_ABIERTO) * 0.80,
                PARPADO_INF_ABIERTO, PARPADO_CERRADO)))
            kit.servo[PIN_PARPADO_INF].angle  = eli_inf
        except Exception as e:
            log.error(f"_write_servos: {e}")

    def _center_smooth(self) -> None:
        """Regresa suavemente al centro (ease-out cuadrático, 750 ms)."""
        if not self.hardware:
            return
        try:
            steps = 30
            h0, v0, y0, p0 = self.eye_h, self.eye_v, self.neck_yaw, self.neck_pitch
            for i in range(1, steps + 1):
                t = 1 - (1 - i / steps) ** 2
                self._write_servos(
                    h0 + (SIM_EYE_H_MID      - h0) * t,
                    v0 + (SIM_EYE_V_MID      - v0) * t,
                    y0 + (SIM_NECK_YAW_MID   - y0) * t,
                    p0 + (SIM_NECK_PITCH_MID - p0) * t,
                    PARPADO_SUP_ABIERTO,
                )
                time.sleep(0.025)
        except Exception as e:
            log.error(f"_center_smooth: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # PARPADEO (sub-thread)
    # ════════════════════════════════════════════════════════════════════════

    def _blink(self) -> None:
        """Parpadeo completo: cierre rápido → pausa → apertura lenta.
        Escribe directamente el estado interno _eyelid_angle que el loop
        principal envía al servo en cada tick (no hay double-write)."""
        if self._stop.is_set():
            return
        try:
            # Cierre (5 pasos × 10 ms = 50 ms)
            for s in range(1, 6):
                if self._stop.is_set():
                    return
                p = s / 5
                # ease-in: más lento al principio, se acelera al cerrar
                ease = p ** 2
                self._eyelid_angle = (PARPADO_SUP_ABIERTO
                    + (PARPADO_CERRADO - PARPADO_SUP_ABIERTO) * ease)
                time.sleep(0.010)

            # Pausa cerrado
            time.sleep(random.uniform(0.08, 0.20))

            # Apertura (7 pasos × 13 ms = 91 ms — más lenta que el cierre)
            for s in range(1, 8):
                if self._stop.is_set():
                    return
                p = s / 7
                # ease-out: empieza rápido, termina suave
                ease = 1 - (1 - p) ** 2
                self._eyelid_angle = (PARPADO_CERRADO
                    + (PARPADO_SUP_ABIERTO - PARPADO_CERRADO) * ease)
                time.sleep(0.013)

            self._eyelid_angle = float(PARPADO_SUP_ABIERTO)
        except Exception as e:
            log.error(f"_blink: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # API PÚBLICA
    # ════════════════════════════════════════════════════════════════════════

    def stop(self) -> None:
        """Señala detención. El loop centra servos y termina."""
        self._stop.set()

    # ════════════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL
    # ════════════════════════════════════════════════════════════════════════

    def run(self) -> None:
        log.info("🎭 MotionSimulator v2 arrancando…")
        self._init_hw()

        now   = time.time()
        start = now
        self._next_sacc  = now + random.uniform(2.0, 6.0)
        self._next_msacc = now + random.uniform(0.5, 2.0)
        self._next_blink = now + random.uniform(1.5, 4.0)
        self._eyelid_angle = float(PARPADO_SUP_ABIERTO)

        # Iniciar virtual target cerca del centro con velocidad aleatoria baja
        self._tgt_h = SIM_EYE_H_MID + random.uniform(-3, 3)
        self._tgt_v = SIM_EYE_V_MID + random.uniform(-1, 1)
        self._vel_h = random.uniform(-0.3, 0.3)
        self._vel_v = random.uniform(-0.1, 0.1)

        while not self._stop.is_set():
            now = time.time()
            t   = now - start

            # ── [3] VIRTUAL TARGET: dinámica de partícula con inercia ──────
            # Fuerza aleatoria (ruido blanco filtrado → movimiento browniano)
            self._vel_h += random.gauss(0, self._RAND_FORCE)
            self._vel_v += random.gauss(0, self._RAND_FORCE * 0.6)
            # Fricción
            self._vel_h *= self._FRICTION
            self._vel_v *= self._FRICTION
            # Fuerza de retorno al centro (evita que el target derive al borde)
            self._vel_h -= (self._tgt_h - SIM_EYE_H_MID) * self._ATTRACT
            self._vel_v -= (self._tgt_v - SIM_EYE_V_MID) * self._ATTRACT
            # Integrar
            self._tgt_h = clamp(self._tgt_h + self._vel_h, _TGT_H_LO, _TGT_H_HI)
            self._tgt_v = clamp(self._tgt_v + self._vel_v, _TGT_V_LO, _TGT_V_HI)

            # ── [1] SÁCADA GRANDE: salto brusco de atención ────────────────
            if not self._sacc_active and now >= self._next_sacc:
                self._sacc_active   = True
                self._sacc_origin_h = self._tgt_h
                self._sacc_origin_v = self._tgt_v
                # Saltar a un punto aleatorio; amplitud proporcional a duración (main sequence)
                amplitude = random.uniform(8, 22)
                angle     = random.uniform(0, 2 * math.pi)
                dest_h = clamp(SIM_EYE_H_MID + amplitude * math.cos(angle),
                               _TGT_H_LO, _TGT_H_HI)
                dest_v = clamp(SIM_EYE_V_MID + amplitude * 0.45 * math.sin(angle),
                               _TGT_V_LO, _TGT_V_HI)
                self._sacc_target_h = dest_h
                self._sacc_target_v = dest_v
                # Duración proporcional a la amplitud (main sequence real: ~2.2 ms/°)
                dist = math.hypot(dest_h - self._sacc_origin_h,
                                  dest_v - self._sacc_origin_v)
                self._sacc_dur   = clamp(dist * 0.0022, 0.06, 0.18)
                self._sacc_start = now
                self._next_sacc  = now + random.uniform(4.0, 13.0)
                # Mover virtual target al destino para que el ojo llegue y se quede
                self._vel_h = self._vel_v = 0.0

            if self._sacc_active:
                frac = (now - self._sacc_start) / max(self._sacc_dur, 1e-3)
                if frac >= 1.0:
                    frac = 1.0
                    self._sacc_active = False
                    self._tgt_h = self._sacc_target_h
                    self._tgt_v = self._sacc_target_v
                # Ease-out cúbico: arranque muy rápido, frenado suave
                ease = 1 - (1 - frac) ** 3
                sacc_h = (self._sacc_origin_h
                          + (self._sacc_target_h - self._sacc_origin_h) * ease)
                sacc_v = (self._sacc_origin_v
                          + (self._sacc_target_v - self._sacc_origin_v) * ease)
                target_h = sacc_h
                target_v = sacc_v
            else:
                target_h = self._tgt_h
                target_v = self._tgt_v

            # ── [1] MICROSÁCADAS involuntarias ─────────────────────────────
            # Solo fuera de sácadas grandes (no acumular efectos)
            if not self._sacc_active:
                if not self._msacc_active and now >= self._next_msacc:
                    self._msacc_active   = True
                    amp = random.uniform(0.5, self._MSACC_AMP)
                    ang = random.uniform(0, 2 * math.pi)
                    self._msacc_offset_h = amp * math.cos(ang)
                    self._msacc_offset_v = amp * 0.6 * math.sin(ang)
                    self._msacc_start    = now
                    self._next_msacc     = now + random.uniform(0.5, 2.0)

                if self._msacc_active:
                    frac = (now - self._msacc_start) / self._MSACC_DUR
                    if frac >= 1.0:
                        self._msacc_active   = False
                        self._msacc_offset_h = 0.0
                        self._msacc_offset_v = 0.0
                    else:
                        # Perfil: sube rápido (10%), baja lentamente (90%)
                        if frac < 0.1:
                            weight = frac / 0.1
                        else:
                            weight = 1 - (frac - 0.1) / 0.9
                        target_h += self._msacc_offset_h * weight
                        target_v += self._msacc_offset_v * weight

            # ── [5] FILTRO PASO-BAJO en ojos ───────────────────────────────
            self.eye_h = self.eye_h * (1 - self._EYE_LP) + target_h * self._EYE_LP
            self.eye_v = self.eye_v * (1 - self._EYE_LP) + target_v * self._EYE_LP

            # ── [6] VOR: cuello se mueve primero, ojos compensan ───────────
            # Cuello sigue lentamente al virtual target (no al ojo)
            neck_target_yaw   = (SIM_NECK_YAW_MID
                                 + (self._tgt_h - SIM_EYE_H_MID) * 0.35)
            neck_target_pitch = (SIM_NECK_PITCH_MID
                                 - (self._tgt_v - SIM_EYE_V_MID) * 0.45)
            prev_neck_yaw   = self.neck_yaw
            prev_neck_pitch = self.neck_pitch
            self.neck_yaw   = (self.neck_yaw   * (1 - self._NECK_LP)
                               + neck_target_yaw   * self._NECK_LP)
            self.neck_pitch = (self.neck_pitch * (1 - self._NECK_LP)
                               + neck_target_pitch * self._NECK_LP)

            # Compensación VOR: si el cuello gira a la derecha, los ojos
            # compensan moviéndose levemente a la izquierda para estabilizar
            delta_yaw   = self.neck_yaw   - prev_neck_yaw
            delta_pitch = self.neck_pitch - prev_neck_pitch
            self.eye_h -= delta_yaw   * self._VOR_GAIN
            self.eye_v += delta_pitch * self._VOR_GAIN  # invertido: pitch↑ → ojo↓
            # Re-clampar ojos después de la compensación
            self.eye_h = clamp(self.eye_h, SIM_EYE_H_LO, SIM_EYE_H_HI)
            self.eye_v = clamp(self.eye_v, SIM_EYE_V_LO, SIM_EYE_V_HI)

            # ── [8] RESPIRACIÓN: onda 0.25 Hz en cuello pitch ──────────────
            breath = self._BREATH_AMP * math.sin(2 * math.pi * self._BREATH_FREQ * t)
            neck_pitch_final = self.neck_pitch + breath

            # ── [7] ACOPLAMIENTO PÁRPADO-OJO vertical ─────────────────────
            # Cuando el ojo mira abajo (eye_v > mid), párpado baja ligeramente
            eye_down_frac = (self.eye_v - SIM_EYE_V_MID) / max(
                SIM_EYE_V_HI - SIM_EYE_V_MID, 1)  # 0..1 cuando mira abajo
            eye_down_frac = clamp(eye_down_frac, 0.0, 1.0)
            # Sólo activo si no hay parpadeo (no sobreescribir _eyelid_angle del blink)
            if not (self._blink_thread and self._blink_thread.is_alive()):
                self._eyelid_angle = (PARPADO_SUP_ABIERTO
                    + eye_down_frac * 6.0)  # Bajar hasta 6° extra al mirar abajo

            # ── ESCRIBIR SERVOS ────────────────────────────────────────────
            self._write_servos(self.eye_h, self.eye_v,
                               self.neck_yaw, neck_pitch_final,
                               self._eyelid_angle)

            # ── PARPADEO ───────────────────────────────────────────────────
            if now >= self._next_blink:
                if self._blink_thread is None or not self._blink_thread.is_alive():
                    self._blink_thread = threading.Thread(
                        target=self._blink, daemon=True, name="SimBlink")
                    self._blink_thread.start()
                # 15% probabilidad de parpadeo doble rápido
                if random.random() < 0.15:
                    self._next_blink = now + random.uniform(0.25, 0.80)
                else:
                    self._next_blink = now + random.uniform(2.5, 6.5)

            time.sleep(self.TICK)

        # Centrar suavemente y terminar
        self._center_smooth()
        log.info("🎭 MotionSimulator v2 detenido")
