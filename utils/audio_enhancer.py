"""
Audio Enhancer - Procesamiento profesional de audio para Realtime API
Mejoras implementadas:
- AGC (Automatic Gain Control) optimizado para voz
- Anti-clipping mejorado para prevenir distorsión
- Noise gate adaptativo ultra-rápido
- Smoothing para transiciones suaves
- Double buffering para playback sin cortes
- Pre-énfasis de frecuencias de voz (300-3400 Hz)
- Filtro pasa-banda para eliminar frecuencias no-vocales
"""
import numpy as np
import queue
import threading
from collections import deque
from scipy import signal as scipy_signal


class AudioEnhancer:
    """Procesador profesional de audio en tiempo real - OPTIMIZADO"""
    
    def __init__(self, sample_rate=24000):
        self.sample_rate = sample_rate
        
        # AGC (Automatic Gain Control) - OPTIMIZADO para voz clara
        self.target_rms = 6000  # Nivel RMS objetivo aumentado para máxima claridad
        self.current_gain = 1.0
        self.gain_smoothing = 0.9  # Más suave para evitar distorsión
        self.min_gain = 0.8  # Menos reducción para mantener claridad
        self.max_gain = 6.0  # Amplificación controlada para voces bajas
        
        # Anti-clipping mejorado
        self.clipping_threshold = 31000  # Umbral antes del máximo (32767)
        self.clipping_ratio = 0.85  # Reducir al 85% si hay clipping
        
        # Noise gate adaptativo - INTELIGENTE
        self.noise_floor = None
        self.noise_samples = deque(maxlen=200)  # Más muestras para mejor calibración
        self.noise_gate_threshold = 250  # Threshold más alto = menos ruido
        self.gate_attack = 0.8    # Apertura rápida (80% en 1 frame ~21ms)
        self.gate_release = 0.100   # Cierre más lento (suave)
        self.gate_state = 1.0     # Empezar abierto, la calibración lo ajustará
        
        # Smoothing general
        self.last_output_level = 0
        self.smoothing_factor = 0.75  # Más suave
        
        # Pre-énfasis para frecuencias de voz (NUEVO)
        self.pre_emphasis_alpha = 0.97  # Factor de pre-énfasis
        self.last_sample = 0
        
        # Filtro pasa-banda para voz (300-3400 Hz) - NUEVO
        self.use_bandpass = True  # Activar/desactivar filtro
        self.bandpass_low = 300   # Frecuencia baja (Hz)
        self.bandpass_high = 3400 # Frecuencia alta (Hz)
        self._init_bandpass_filter()
        
        # Double buffering para playback
        # Buffer más grande para evitar pérdida de chunks de audio
        self.playback_buffer = queue.Queue(maxsize=100)
        self.buffer_lock = threading.Lock()
    
    def _init_bandpass_filter(self):
        """Inicializa el filtro pasa-banda Butterworth"""
        try:
            # Filtro Butterworth de orden 4 (balance entre efectividad y fase)
            nyquist = self.sample_rate / 2
            low = self.bandpass_low / nyquist
            high = self.bandpass_high / nyquist
            
            # Asegurar que las frecuencias estén en el rango válido
            low = max(0.01, min(low, 0.99))
            high = max(0.01, min(high, 0.99))
            
            if low < high:
                self.sos = scipy_signal.butter(4, [low, high], btype='band', output='sos')
                self.zi = scipy_signal.sosfilt_zi(self.sos)
                print(f"[AUDIO] ✅ Filtro pasa-banda inicializado ({self.bandpass_low}-{self.bandpass_high} Hz)")
            else:
                self.use_bandpass = False
                print("[AUDIO] ⚠️ Filtro pasa-banda desactivado - frecuencias inválidas")
        except Exception as e:
            self.use_bandpass = False
            print(f"[AUDIO] ⚠️ Error inicializando filtro: {e}")
        
    def calibrate_noise(self, audio_data):
        """
        Calibración inteligente del nivel de ruido
        Toma múltiples muestras y usa estadísticas robustas
        """
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
        
        self.noise_samples.append(rms)
        
        if len(self.noise_samples) >= 20:  # Más muestras = mejor calibración
            # Usar percentil 30 como ruido de fondo (más robusto)
            self.noise_floor = max(1.0, np.percentile(list(self.noise_samples), 30))
            
            # Calcular desviación estándar para detectar variabilidad
            noise_std = np.std(list(self.noise_samples))
            
            # Threshold adaptativo basado en ruido y variabilidad
            # Si hay mucha variabilidad = ambiente ruidoso, threshold más alto
            adaptive_multiplier = 2.2 + (noise_std / self.noise_floor) * 0.5
            adaptive_multiplier = min(adaptive_multiplier, 3.5)  # Limitar
            
            self.noise_gate_threshold = max(180, self.noise_floor * adaptive_multiplier)
            
            print(f"[CALIBRACIÓN] ✅ Ruido: {self.noise_floor:.0f} | Variabilidad: {noise_std:.0f} | Threshold: {self.noise_gate_threshold:.0f} (x{adaptive_multiplier:.1f})")
            return True
        return False
    
    def calculate_rms(self, audio_array):
        """Calcula el RMS (Root Mean Square) del audio"""
        return np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
    
    def apply_agc(self, audio_data):
        """
        Automatic Gain Control mejorado - Ajusta el volumen automáticamente
        con detección de silencio para evitar amplificar ruido
        """
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        
        # Calcular RMS actual
        current_rms = self.calculate_rms(audio_array)
        
        # Solo aplicar AGC si hay señal significativa (no es ruido puro)
        if current_rms > self.noise_gate_threshold * 0.5:  # 50% del threshold
            # Calcular ganancia necesaria
            desired_gain = self.target_rms / current_rms
            
            # Limitar ganancia
            desired_gain = np.clip(desired_gain, self.min_gain, self.max_gain)
            
            # Suavizar cambios de ganancia (evita cambios bruscos)
            self.current_gain = (
                self.gain_smoothing * self.current_gain +
                (1 - self.gain_smoothing) * desired_gain
            )
        else:
            # Es ruido, no amplificar
            self.current_gain = max(0.5, self.current_gain * 0.95)  # Decay
            
        # Aplicar ganancia
        audio_array *= self.current_gain
        
        return audio_array
    
    def apply_anti_clipping(self, audio_array):
        """
        Previene distorsión por clipping (audio muy alto)
        usando soft clipping
        """
        max_val = np.abs(audio_array).max()
        
        if max_val > self.clipping_threshold:
            # Aplicar soft clipping (compresión suave)
            reduction = self.clipping_threshold / max_val
            audio_array *= reduction
            
        # Clipping final en los límites absolutos
        audio_array = np.clip(audio_array, -32767, 32767)
        
        return audio_array
    
    def apply_noise_gate(self, audio_data):
        """
        Noise gate adaptativo con attack/release suave
        para eliminar ruido de fondo sin cortar el inicio de palabras
        """
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        
        # Calcular energía
        current_rms = self.calculate_rms(audio_array)
        
        # Determinar si debe abrir o cerrar el gate
        if current_rms > self.noise_gate_threshold:
            # Abrir gate (attack rápido)
            target_state = 1.0
            rate = self.gate_attack
        else:
            # Cerrar gate (release lento)
            target_state = 0.0
            rate = self.gate_release
        
        # Suavizar transición
        self.gate_state = self.gate_state * (1 - rate) + target_state * rate
        
        # Aplicar gate
        audio_array *= self.gate_state
        
        return audio_array.astype(np.int16).tobytes()
    
    def smooth_output(self, audio_array):
        """Suaviza transiciones bruscas entre chunks"""
        current_level = np.abs(audio_array).mean()
        
        if self.last_output_level > 0:
            # Si hay cambio brusco, suavizar
            if abs(current_level - self.last_output_level) > 1000:
                blend_factor = 1 - self.smoothing_factor
                audio_array = audio_array * blend_factor + self.last_output_level * self.smoothing_factor
        
        self.last_output_level = current_level
        return audio_array
    
    def apply_pre_emphasis(self, audio_data):
        """
        Aplica filtro de pre-énfasis para realzar frecuencias de voz (300-3400 Hz)
        y[n] = x[n] - alpha * x[n-1]
        Mejora claridad vocal y reduce ruido de bajas frecuencias
        """
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        
        # Aplicar filtro FIR de primer orden
        emphasized = np.zeros_like(audio_array)
        emphasized[0] = audio_array[0] - self.pre_emphasis_alpha * self.last_sample
        
        for i in range(1, len(audio_array)):
            emphasized[i] = audio_array[i] - self.pre_emphasis_alpha * audio_array[i-1]
        
        # Guardar último sample para continuidad entre chunks
        self.last_sample = audio_array[-1]
        
        return emphasized
    
    def apply_bandpass_filter(self, audio_array):
        """
        Aplica filtro pasa-banda para aislar frecuencias de voz (300-3400 Hz)
        Elimina ruidos de baja frecuencia (ventiladores, tráfico) y alta (silbidos, electrónica)
        """
        if not self.use_bandpass:
            return audio_array
        
        try:
            # Aplicar filtro con estado para continuidad entre chunks
            filtered, self.zi = scipy_signal.sosfilt(self.sos, audio_array, zi=self.zi)
            return filtered
        except Exception as e:
            print(f"[AUDIO] ⚠️ Error en filtro pasa-banda: {e}")
            return audio_array
    
    def process_input(self, audio_data):
        """
        Pipeline completo de procesamiento de entrada (micrófono)
        1. Calibrar ruido (primeras muestras)
        2. Filtro pasa-banda (aislar frecuencias de voz)
        3. Noise gate
        4. Pre-énfasis
        5. AGC
        6. Anti-clipping
        """
        # Calibración inicial
        if self.noise_floor is None:
            self.calibrate_noise(audio_data)
            if self.noise_floor is None:
                return audio_data  # Aún calibrando
        
        # Convertir a array para procesamiento
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        
        # 1. Filtro pasa-banda (eliminar frecuencias no-vocales)
        if self.use_bandpass:
            audio_array = self.apply_bandpass_filter(audio_array)
        
        # Convertir de vuelta a bytes para noise gate
        audio_data = audio_array.astype(np.int16).tobytes()
        
        # 2. Noise gate (eliminar ruido de fondo)
        audio_data = self.apply_noise_gate(audio_data)
        
        # 3. Pre-énfasis (realzar frecuencias de voz)
        audio_array = self.apply_pre_emphasis(audio_data)
        
        # 4. AGC (normalizar volumen)
        audio_array = self.apply_agc(audio_array.astype(np.int16).tobytes())
        
        # 5. Anti-clipping (prevenir distorsión)
        audio_array = self.apply_anti_clipping(audio_array)
        
        # 6. Smoothing
        audio_array = self.smooth_output(audio_array)
        
        return audio_array.astype(np.int16).tobytes()
    
    def process_output(self, audio_data):
        """
        Pipeline de procesamiento de salida (altavoz)
        Más simple, solo anti-clipping y smoothing
        """
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        
        # Anti-clipping
        audio_array = self.apply_anti_clipping(audio_array)
        
        # Smoothing
        audio_array = self.smooth_output(audio_array)
        
        return audio_array.astype(np.int16).tobytes()
    
    def add_to_playback_buffer(self, audio_chunk):
        """Agrega audio al buffer de reproducción (thread-safe)"""
        try:
            with self.buffer_lock:
                if audio_chunk is None:
                    # Señal de fin
                    self.playback_buffer.put(None, block=False)
                else:
                    # NO procesar el audio de salida - ya viene procesado por OpenAI
                    # El procesamiento causaba volumen que sube/baja
                    self.playback_buffer.put(audio_chunk, block=False)
        except queue.Full:
            # Si el buffer está lleno, descartar el chunk más viejo
            try:
                self.playback_buffer.get_nowait()
                self.playback_buffer.put(audio_chunk, block=False)
            except:
                pass
    
    def get_from_playback_buffer(self, timeout=0.1):
        """Obtiene audio del buffer de reproducción"""
        try:
            return self.playback_buffer.get(timeout=timeout)
        except queue.Empty:
            return b''
    
    def reset(self):
        """Resetea el estado del procesador"""
        self.current_gain = 1.0
        self.gate_state = 1.0  # Empezar abierto para no perder primeras palabras
        self.last_output_level = 0
        self.noise_floor = None
        self.noise_samples.clear()
        
        # Resetear filtro pasa-banda
        if self.use_bandpass:
            try:
                self.zi = scipy_signal.sosfilt_zi(self.sos)
            except:
                pass
        
        # Limpiar buffer
        self.clear_playback_buffer()
    
    def clear_playback_buffer(self):
        """Limpia el buffer de reproducción (útil para interrupciones)"""
        with self.buffer_lock:
            while not self.playback_buffer.empty():
                try:
                    self.playback_buffer.get_nowait()
                except:
                    break
    
    def get_stats(self):
        """Retorna estadísticas útiles para debugging"""
        return {
            'current_gain': f"{self.current_gain:.2f}x",
            'noise_floor': f"{self.noise_floor:.0f}" if self.noise_floor else "Calibrando...",
            'gate_state': f"{self.gate_state * 100:.0f}%",
            'buffer_size': self.playback_buffer.qsize()
        }
