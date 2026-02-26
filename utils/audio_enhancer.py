"""
Audio Enhancer - Procesamiento profesional de audio para Realtime API
Mejoras implementadas:
- AGC (Automatic Gain Control) optimizado para voz
- Anti-clipping mejorado para prevenir distorsión
- Noise gate adaptativo ultra-rápido
- Smoothing para transiciones suaves
- Double buffering para playback sin cortes
- Pre-énfasis de frecuencias de voz (300-3400 Hz)
"""
import numpy as np
import queue
import threading
from collections import deque


class AudioEnhancer:
    """Procesador profesional de audio en tiempo real - OPTIMIZADO"""
    
    def __init__(self, sample_rate=24000):
        self.sample_rate = sample_rate
        
        # AGC (Automatic Gain Control) - OPTIMIZADO para voz clara
        self.target_rms = 5000  # Nivel RMS objetivo aumentado para máxima claridad
        self.current_gain = 1.0
        self.gain_smoothing = 0.85  # Más responsive (era 0.95)
        self.min_gain = 0.5  # Permite reducción moderada
        self.max_gain = 8.0  # Amplificación mayor para voces bajas (antes 4.0)
        
        # Anti-clipping mejorado
        self.clipping_threshold = 31000  # Umbral antes del máximo (32767)
        self.clipping_ratio = 0.85  # Reducir al 85% si hay clipping
        
        # Noise gate adaptativo - INTELIGENTE
        self.noise_floor = None
        self.noise_samples = deque(maxlen=150)  # Más muestras para calibración robusta
        self.noise_gate_threshold = 200  # Threshold inicial conservador
        self.gate_attack = 0.002  # Apertura muy rápida (2ms) - no pierde inicio
        self.gate_release = 0.120   # Cierre suave (120ms) - transiciones naturales
        self.gate_state = 0.0     # 0 = cerrado, 1 = abierto
        
        # Smoothing general
        self.last_output_level = 0
        self.smoothing_factor = 0.75  # Más suave
        
        # Pre-énfasis para frecuencias de voz (NUEVO)
        self.pre_emphasis_alpha = 0.97  # Factor de pre-énfasis
        self.last_sample = 0
        
        # Double buffering para playback
        # Buffer más grande para evitar pérdida de chunks de audio
        self.playback_buffer = queue.Queue(maxsize=100)
        self.buffer_lock = threading.Lock()
        
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
            self.noise_floor = np.percentile(list(self.noise_samples), 30)
            
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
    
    def process_input(self, audio_data):
        """
        Pipeline completo de procesamiento de entrada (micrófono)
        1. Calibrar ruido (primeras muestras)
        2. Noise gate
        3. AGC
        4. Anti-clipping
        """
        # Calibración inicial
        if self.noise_floor is None:
            self.calibrate_noise(audio_data)
            if self.noise_floor is None:
                return audio_data  # Aún calibrando
        
        # 1. Noise gate (eliminar ruido de fondo)
        audio_data = self.apply_noise_gate(audio_data)
        
        # 2. Pre-énfasis (realzar frecuencias de voz)
        audio_array = self.apply_pre_emphasis(audio_data)
        
        # 3. AGC (normalizar volumen)
        audio_array = self.apply_agc(audio_array.astype(np.int16).tobytes())
        
        # 4. Anti-clipping (prevenir distorsión)
        audio_array = self.apply_anti_clipping(audio_array)
        
        # 5. Smoothing
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
        self.gate_state = 0.0
        self.last_output_level = 0
        self.noise_floor = None
        self.noise_samples.clear()
        
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
