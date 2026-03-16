"""
Echo Canceller - Cancelación de eco acústico para asistente de voz en tiempo real

Problema: Cuando el asistente habla por el altavoz, el micrófono capta ese sonido
(eco) y lo reenvía a la API, causando feedback o que el sistema se "escuche a sí mismo".

Solución anterior: Hard mute (descartar TODO el audio del mic cuando el asistente habla)
  → Problema: El usuario NO PUEDE interrumpir naturalmente
  → Problema: Delay artificial de 1 segundo post-respuesta

Nueva solución (este módulo):
  - Tracking de señal de referencia (audio que sale por el altavoz)
  - Supresión espectral del eco (resta el perfil del altavoz del micrófono)
  - Double Talk Detection (detecta cuando el usuario habla sobre el asistente)
  - Gate suave con transiciones naturales (no hard mute)
  - El audio SIEMPRE se envía a la API → interrupciones naturales funcionan

Optimizado para Raspberry Pi (usa NumPy FFT, O(n log n), sin dependencias extra)
"""
import numpy as np
from collections import deque
import threading


class EchoCanceller:
    """
    Cancelador de eco acústico para voz en tiempo real.
    
    Diseñado para: altavoz + micrófono en el mismo dispositivo
    (laptop, Raspberry Pi, robot con mic y altavoz)
    
    Uso:
        ec = EchoCanceller(sample_rate=24000)
        
        # En el thread de playback (ANTES de reproducir):
        ec.feed_reference(audio_chunk)
        stream.write(audio_chunk)
        
        # En el thread de grabación (REEMPLAZA hard mute):
        clean_audio = ec.process(mic_chunk)
        send_to_api(clean_audio)
        
        # Cuando el asistente termina de hablar:
        ec.notify_playback_stopped()
    """
    
    def __init__(self, sample_rate=24000, frame_size=512):
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        
        # --- Tracking de señal de referencia ---
        # Buffer circular con últimos 500ms de audio reproducido
        ref_duration_s = 0.5
        self.ref_buffer_size = int(sample_rate * ref_duration_s)
        self.ref_buffer = np.zeros(self.ref_buffer_size, dtype=np.float32)
        self.ref_write_pos = 0
        
        # Energía de referencia (media móvil)
        self.ref_energy_history = deque(maxlen=30)
        self.ref_energy_avg = 0.0
        
        # --- Estado de eco ---
        self.is_playing = False
        self.samples_since_stop = 0
        # Eco residual después de que el altavoz para (ms)
        self.echo_tail_ms = 350
        self.echo_tail_samples = int(sample_rate * self.echo_tail_ms / 1000)
        
        # --- Gate suave (reemplaza hard mute) ---
        self.gate = 1.0            # 1.0 = mic abierto, 0.0 = silenciado
        self.gate_target = 1.0
        self.gate_open_rate = 0.03  # Apertura lenta (evita eco residual)
        self.gate_close_rate = 0.20 # Cierre rápido (corta eco inmediatamente)
        
        # --- Supresión espectral ---
        self.fft_size = max(frame_size, 256)  # Mínimo 256 para resolución decente
        # Espectro de referencia (perfil frecuencial del eco)
        self.ref_spectrum = np.zeros(self.fft_size // 2 + 1, dtype=np.float32)
        self.spectrum_smoothing = 0.80  # Suavizado del espectro
        # Ventana pre-calculada para FFT
        self._window = np.hanning(self.fft_size).astype(np.float32)
        
        # --- Double Talk Detection (DTD) ---
        # Detecta cuando el usuario habla AL MISMO TIEMPO que el asistente
        self.dtd_ratio = 2.5        # Si input es 2.5x > eco esperado → usuario hablando
        self.dtd_min_energy = 400   # Energía mínima para considerar voz real
        self.input_energy_history = deque(maxlen=10)
        
        # --- Acoplamiento de eco ---
        # Cuánto del altavoz capta el micrófono (depende del hardware)
        # 0.05-0.15: Auriculares / buena separación
        # 0.15-0.30: Laptop / separación media
        # 0.30-0.50: Speaker cerca del mic / robot
        # 0.50-0.80: Mic y speaker muy juntos
        self.echo_coupling = 0.30
        
        # --- Thread safety ---
        self.lock = threading.Lock()
        
        # --- Stats para debug ---
        self._stats = {
            'echo_active': False,
            'double_talk': False,
            'gate': 1.0,
            'suppression_db': 0.0
        }
        
        print(f"[AEC] ✅ Echo Canceller inicializado (SR={sample_rate}, FFT={self.fft_size}, coupling={self.echo_coupling})")
    
    def feed_reference(self, audio_bytes):
        """
        Alimenta la señal de referencia (audio que sale por el altavoz).
        Llamar ANTES de reproducir cada chunk.
        
        Args:
            audio_bytes: Audio PCM int16
        """
        with self.lock:
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            n = len(audio)
            
            if n == 0:
                return
            
            # Escribir en buffer circular (eficiente, sin loops Python)
            end_pos = self.ref_write_pos + n
            if end_pos <= self.ref_buffer_size:
                self.ref_buffer[self.ref_write_pos:end_pos] = audio
            else:
                # Wrap around
                first_part = self.ref_buffer_size - self.ref_write_pos
                self.ref_buffer[self.ref_write_pos:] = audio[:first_part]
                remaining = n - first_part
                self.ref_buffer[:remaining] = audio[first_part:]
            self.ref_write_pos = end_pos % self.ref_buffer_size
            
            # Actualizar espectro de referencia (perfil frecuencial del eco)
            if n >= self.fft_size:
                windowed = audio[:self.fft_size] * self._window
                spectrum = np.abs(np.fft.rfft(windowed))
            else:
                padded = np.zeros(self.fft_size, dtype=np.float32)
                padded[:n] = audio
                windowed = padded * self._window
                spectrum = np.abs(np.fft.rfft(windowed))
            
            self.ref_spectrum = (self.spectrum_smoothing * self.ref_spectrum + 
                                (1 - self.spectrum_smoothing) * spectrum)
            
            # Energía de referencia
            rms = np.sqrt(np.mean(audio ** 2))
            self.ref_energy_history.append(rms)
            self.ref_energy_avg = np.mean(list(self.ref_energy_history))
            
            self.is_playing = True
            self.samples_since_stop = 0
    
    def notify_playback_stopped(self):
        """
        Notifica que el altavoz dejó de reproducir.
        El echo tail maneja el eco residual automáticamente.
        """
        with self.lock:
            self.is_playing = False
            self.samples_since_stop = 0
    
    def process(self, input_bytes):
        """
        Procesa audio del micrófono: elimina eco del altavoz.
        REEMPLAZA el hard mute (if assistant_speaking: continue).
        
        El audio SIEMPRE pasa (procesado), permitiendo interrupciones naturales.
        
        Args:
            input_bytes: Audio crudo del micrófono (PCM int16)
            
        Returns:
            Audio limpio sin eco (PCM int16)
        """
        with self.lock:
            audio = np.frombuffer(input_bytes, dtype=np.int16).astype(np.float32)
            n = len(audio)
            
            if n == 0:
                return input_bytes
            
            # ¿Estamos en zona de eco?
            in_echo_zone = (self.is_playing or 
                           self.samples_since_stop < self.echo_tail_samples)
            
            if not in_echo_zone:
                # Sin eco esperado → abrir gate completamente
                self.gate_target = 1.0
                self._smooth_gate()
                self._stats['echo_active'] = False
                self._stats['double_talk'] = False
                self._stats['gate'] = self.gate
                return (audio * self.gate).astype(np.int16).tobytes()
            
            # === EN ZONA DE ECO ===
            self._stats['echo_active'] = True
            
            # Energía de entrada del micrófono
            input_rms = np.sqrt(np.mean(audio ** 2))
            self.input_energy_history.append(input_rms)
            
            # Eco esperado = energía de referencia × factor de acoplamiento
            expected_echo_rms = self.ref_energy_avg * self.echo_coupling
            
            # --- Double Talk Detection ---
            is_double_talk = False
            if input_rms > self.dtd_min_energy:
                if expected_echo_rms > 0:
                    ratio = input_rms / expected_echo_rms
                    is_double_talk = ratio > self.dtd_ratio
                else:
                    # No hay referencia → probablemente es voz real
                    is_double_talk = True
            
            self._stats['double_talk'] = is_double_talk
            
            # --- Decidir nivel de supresión ---
            if is_double_talk:
                # Usuario hablando sobre el asistente → INTERRUPCIÓN
                # Supresión espectral ligera + gate parcialmente abierto
                output = self._spectral_suppress(audio, strength=0.5)
                self.gate_target = 0.65
            else:
                # Solo eco del altavoz → suprimir fuertemente
                output = self._spectral_suppress(audio, strength=1.5)
                self.gate_target = 0.05
            
            # Suavizar gate
            self._smooth_gate()
            output *= self.gate
            
            # Actualizar contador de echo tail
            if not self.is_playing:
                self.samples_since_stop += n
            
            # Stats
            if input_rms > 0:
                output_rms = np.sqrt(np.mean(output ** 2))
                self._stats['suppression_db'] = 20 * np.log10(
                    max(output_rms / input_rms, 1e-10))
            self._stats['gate'] = self.gate
            
            return np.clip(output, -32767, 32767).astype(np.int16).tobytes()
    
    def _spectral_suppress(self, audio, strength=1.0):
        """
        Supresión espectral del eco.
        Resta el perfil frecuencial del altavoz del audio del micrófono.
        
        Args:
            audio: Array float32 del micrófono
            strength: Factor de supresión (0.5=ligera, 1.0=normal, 1.5=agresiva)
            
        Returns:
            Audio con eco suprimido (float32)
        """
        n = len(audio)
        
        # Preparar para FFT (pad o truncar al fft_size)
        if n < self.fft_size:
            padded = np.zeros(self.fft_size, dtype=np.float32)
            padded[:n] = audio
        else:
            padded = audio[:self.fft_size].copy()
        
        # Ventana de Hann para evitar artefactos en los bordes
        windowed = padded * self._window
        
        # FFT
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)
        
        # Estimar espectro del eco
        echo_estimate = self.ref_spectrum[:len(magnitude)] * self.echo_coupling * strength
        
        # Spectral subtraction con floor (evita "ruido musical")
        spectral_floor = 0.02
        clean_magnitude = magnitude - echo_estimate
        clean_magnitude = np.maximum(clean_magnitude, spectral_floor * magnitude)
        
        # Reconstruir señal
        clean_spectrum = clean_magnitude * np.exp(1j * phase)
        clean_audio = np.fft.irfft(clean_spectrum)
        
        # Devolver solo la longitud original
        if n < self.fft_size:
            return clean_audio[:n].astype(np.float32)
        elif n > self.fft_size:
            # Procesar el resto sin modificar (chunks más grandes que fft_size)
            result = np.zeros(n, dtype=np.float32)
            result[:self.fft_size] = clean_audio
            result[self.fft_size:] = audio[self.fft_size:]
            return result
        else:
            return clean_audio.astype(np.float32)
    
    def _smooth_gate(self):
        """Transición suave del gate (evita clicks/pops)"""
        if self.gate_target > self.gate:
            # Abriendo (lento para evitar eco residual)
            self.gate += self.gate_open_rate * (self.gate_target - self.gate)
        else:
            # Cerrando (rápido para cortar eco inmediatamente)
            self.gate += self.gate_close_rate * (self.gate_target - self.gate)
        self.gate = float(np.clip(self.gate, 0.0, 1.0))
    
    def set_echo_coupling(self, coupling):
        """
        Ajusta el factor de acoplamiento eco según el hardware.
        
        Valores recomendados:
            0.05-0.15: Auriculares / buena separación mic-speaker
            0.15-0.30: Laptop / separación media
            0.30-0.50: Speaker externo cerca del mic / robot
            0.50-0.80: Mic y speaker muy juntos
        """
        with self.lock:
            self.echo_coupling = float(np.clip(coupling, 0.01, 0.95))
            print(f"[AEC] Echo coupling ajustado a {self.echo_coupling:.2f}")
    
    def get_stats(self):
        """Retorna estadísticas del echo canceller para debug"""
        return self._stats.copy()
    
    def reset(self):
        """Resetea el estado del echo canceller para nueva sesión"""
        with self.lock:
            self.ref_buffer = np.zeros(self.ref_buffer_size, dtype=np.float32)
            self.ref_write_pos = 0
            self.ref_spectrum = np.zeros(self.fft_size // 2 + 1, dtype=np.float32)
            self.ref_energy_history.clear()
            self.ref_energy_avg = 0.0
            self.input_energy_history.clear()
            self.gate = 1.0
            self.gate_target = 1.0
            self.is_playing = False
            self.samples_since_stop = self.echo_tail_samples + 1
            self._stats = {
                'echo_active': False,
                'double_talk': False,
                'gate': 1.0,
                'suppression_db': 0.0
            }
            print("[AEC] 🔄 Echo Canceller reseteado")
