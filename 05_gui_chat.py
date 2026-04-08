"""
GUI Chat con OpenAI Realtime API - Con modo de voz y configuración
Interfaz gráfica simple y liviana con monitor de tokens
"""
import os
import json
import base64
import gc
import time
import tkinter as tk
from tkinter import scrolledtext
import websocket
import threading
import queue
from dotenv import load_dotenv
from datetime import datetime
from PIL import Image, ImageTk
import cv2
import numpy as np
from utils.logger import get_logger

# Loggers por subsistema
log = get_logger('gui_chat')
log_audio = get_logger('audio')
log_ws = get_logger('websocket')
log_vision = get_logger('vision')
log_aec = get_logger('aec')

try:
    import pyaudio
    AUDIO_AVAILABLE = True
    log_audio.debug("PyAudio importado correctamente")
except ImportError:
    AUDIO_AVAILABLE = False
    log_audio.debug("PyAudio NO disponible")

# Cámara disponible si hay OpenCV
try:
    import cv2
    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False

try:
    from hardware.gpt4_vision_service import GPT4VisionService
    GPT4V_AVAILABLE = True
except ImportError:
    GPT4V_AVAILABLE = False

try:
    from utils.audio_enhancer import AudioEnhancer
    AUDIO_ENHANCER_AVAILABLE = True
except ImportError:
    AUDIO_ENHANCER_AVAILABLE = False
    log_audio.warning("AudioEnhancer no disponible - audio sin procesamiento avanzado")

try:
    from utils.echo_canceller import EchoCanceller
    ECHO_CANCELLER_AVAILABLE = True
except ImportError:
    ECHO_CANCELLER_AVAILABLE = False
    log_aec.warning("EchoCanceller no disponible - usando mute simple para eco")

try:
    from utils.audio_device_manager import AudioDeviceManager
    AUDIO_DEVICE_MANAGER_AVAILABLE = True
except ImportError:
    AUDIO_DEVICE_MANAGER_AVAILABLE = False
    log_audio.warning("AudioDeviceManager no disponible - usando dispositivos por defecto")

# ══════════════════════════════════════════════════════════════════════════════
# SISTEMA DE TRACKING FACIAL (EyeTrackerThread)
# ══════════════════════════════════════════════════════════════════════════════
try:
    from hardware.shared_state import SharedState
    from hardware.eye_tracker_thread import EyeTrackerThread
    EYE_TRACKER_AVAILABLE = True
    log_vision.info("✅ EyeTrackerThread disponible")
except ImportError as e:
    EYE_TRACKER_AVAILABLE = False
    log_vision.warning(f"⚠️ EyeTrackerThread no disponible: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SISTEMA DE CONTROL DE BOCA (MouthController)
# ══════════════════════════════════════════════════════════════════════════════
try:
    from hardware.mouth_controller import get_mouth_controller, start_mouth_speaking, stop_mouth_speaking
    MOUTH_CONTROLLER_AVAILABLE = True
    log.info("✅ MouthController disponible")
except ImportError as e:
    MOUTH_CONTROLLER_AVAILABLE = False
    log.warning(f"⚠️ MouthController no disponible: {e}")

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
# Modelo flagship de voz (el más actual disponible en Realtime API)
MODEL = 'gpt-realtime-1.5'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Precios por 1M tokens (gpt-realtime-1.5)
PRICE_INPUT = 4.00   # Text input $4.00 / Audio input $32.00
PRICE_OUTPUT = 16.00 # Text output $16.00 / Audio output $64.00

# Configuración de audio optimizada para máxima fluidez
# OPTIMIZADO: CHUNK aumentado de 512 a 1024 para reducir overhead de CPU (~50% menos llamadas)
CHUNK = 1024  # 43ms @ 24kHz - Mejor balance latencia/CPU
FORMAT = pyaudio.paInt16 if AUDIO_AVAILABLE else None
CHANNELS = 1
RATE_API = 24000  # Requerido por OpenAI Realtime API
RATE_HW = 48000   # Hardware rate (se auto-detecta)

class RealtimeGUIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenAI Realtime Chat - GUI con Voz")
        self.root.geometry("800x720")
        self.root.configure(bg='#f0f0f0')
        
        self.ws = None
        self.connected = False
        
        # Verificar disponibilidad de audio
        self.audio_available = AUDIO_AVAILABLE
        
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_cost = 0.0
        
        # Audio
        self.voice_mode = False
        self.recording = False
        try:
            self.audio = pyaudio.PyAudio() if self.audio_available else None
            if self.audio:
                log_audio.debug(f"PyAudio inicializado - {self.audio.get_device_count()} dispositivos")
        except Exception as e:
            log_audio.error(f"No se pudo inicializar PyAudio: {e}")
            self.audio = None
            self.audio_available = False
        
        self.output_queue = queue.Queue()
        self.audio_thread = None
        self.playback_thread = None
        
        # Audio resampling para Raspberry Pi
        self.hw_rate = RATE_HW
        self.api_rate = RATE_API
        self.resample_ratio_in = self.api_rate / self.hw_rate
        self.resample_ratio_out = self.hw_rate / self.api_rate
        
        # Audio Enhancer profesional
        self.audio_enhancer = AudioEnhancer(sample_rate=RATE_API) if AUDIO_ENHANCER_AVAILABLE else None
        if self.audio_enhancer:
            log_audio.info("✅ Procesamiento profesional activado (AGC + Anti-clipping + Noise Gate)")
        
        # Echo Canceller (AEC) - Reemplaza hard mute por cancelación inteligente
        self.echo_canceller = EchoCanceller(sample_rate=RATE_API, frame_size=CHUNK) if ECHO_CANCELLER_AVAILABLE else None
        if self.echo_canceller:
            log_aec.info("✅ Cancelación de eco acústico (AEC) activada")
        
        # Audio Device Manager
        self.audio_device_manager = AudioDeviceManager() if AUDIO_DEVICE_MANAGER_AVAILABLE and self.audio_available else None
        self.input_device_index = None
        self.output_device_index = None

        # Cargar dispositivos preferidos o auto-detectar
        if self.audio_device_manager:
            prefs = self.audio_device_manager.get_preferred_devices()
            self.input_device_index = prefs.get("input")
            self.output_device_index = prefs.get("output")

            # Restaurar sink Bluetooth si estaba configurado en la sesión anterior
            output_pw_id = prefs.get("output_pipewire_id")
            if output_pw_id:
                log_audio.info(f"🔊 Restaurando Bluetooth preferido (PipeWire ID: {output_pw_id})...")
                self.audio_device_manager.set_pipewire_default(output_pw_id)

            # AUTO-DETECCIÓN: Si no hay preferencias guardadas, buscar automáticamente
            if self.input_device_index is None or self.output_device_index is None:
                log_audio.info("🔍 Auto-detectando dispositivos físicos...")
                auto_input, auto_output = self.audio_device_manager.auto_detect_best_devices()

                if self.input_device_index is None and auto_input is not None:
                    self.input_device_index = auto_input
                    self.audio_device_manager.set_preferred_devices(input_index=auto_input)
                    log_audio.info(f"✅ Micrófono auto-detectado y guardado")

                if self.output_device_index is None and auto_output is not None:
                    self.output_device_index = auto_output
                    self.audio_device_manager.set_preferred_devices(output_index=auto_output)
                    log_audio.info(f"✅ Altavoz auto-detectado y guardado")

            # Mostrar dispositivos cargados
            input_name, output_name = self.audio_device_manager.get_preferred_device_names()
            if input_name or output_name:
                log_audio.info("🎧 Dispositivos de audio configurados:")
                if input_name:
                    log_audio.info(f"  🎤 Input: {input_name}")
                if output_name:
                    log_audio.info(f"  🔊 Output: {output_name}")

        # ═══════════════════════════════════════════════════════════════════════
        # FORZAR PIPEWIRE PARA BLUETOOTH: Buscar dispositivo "default" o "pipewire"
        # Esto garantiza que el audio llegue a dispositivos Bluetooth (JBL, etc.)
        # ═══════════════════════════════════════════════════════════════════════
        if self.audio_available and self.audio:
            self._ensure_pipewire_output()
        
        # ═══════════════════════════════════════════════════════════════════════
        # SISTEMA DE CÁMARA CENTRALIZADO (EyeTrackerThread es dueño de la cámara)
        # ═══════════════════════════════════════════════════════════════════════
        self.shared_state = SharedState() if EYE_TRACKER_AVAILABLE else None
        self.eye_tracker = None
        self.camera_cap = None  # DEPRECATED: ya no se usa directamente
        self.gpt4v_service = GPT4VisionService() if GPT4V_AVAILABLE else None
        self.camera_window = None
        self.camera_label = None
        self.camera_status = None
        self.camera_running = False
        
        # GPT-4 Vision con cache inteligente
        self.last_gpt4v_description = None
        self.last_gpt4v_time = 0
        self.gpt4v_analyzing = False
        self.gpt4v_thread = None
        # OPTIMIZADO: Intervalo aumentado de 8s a 30s para reducir costos y CPU
        self.gpt4v_refresh_interval = 30  # Background refresh cada 30s (antes: 8s)
        self.gpt4v_cache_max_age = 25  # Usar cache si tiene menos de 25s
        
        # Estado del asistente para interrupción inteligente
        self.assistant_speaking = False
        self.current_response_id = None
        self.current_response_item_id = None  # Item ID para truncation
        self.played_audio_bytes = 0           # Bytes reproducidos para truncation
        self.user_interrupted = False
        
        # Contador de costos GPT-4V
        self.gpt4v_analyses_count = 0
        self.gpt4v_total_cost = 0.0
        
        # Memoria conversacional para naturalidad
        self.conversation_memory = []
        self.max_memory_items = 10
        
        # Timer para actualización periódica de visión en modo voz
        self._vision_update_timer_id = None
        self.vision_update_interval_ms = 15000  # Actualizar visión cada 15 segundos
        
        # ═══════════════════════════════════════════════════════════════════════
        # CONTROLADOR DE BOCA (servo pin 2 del PCA9685)
        # ═══════════════════════════════════════════════════════════════════════
        self.mouth_controller = None
        if MOUTH_CONTROLLER_AVAILABLE:
            try:
                self.mouth_controller = get_mouth_controller(enable_servo=True)
                log.info("✅ MouthController inicializado - boca cerrada")
            except Exception as e:
                log.error(f"❌ Error inicializando MouthController: {e}")
                self.mouth_controller = None
        
        # Configuración personalizable
        self.voice = "echo"
        self.instructions = self._build_conversational_instructions()
        # OPTIMIZADO: Temperature reducida de 0.85 a 0.6 para mayor precisión en transcripción
        self.temperature = 0.6  # Mayor precisión, menos "creatividad" errónea
        
        self.setup_ui()
        self.start_connection()
        
        # Auto-iniciar cámara y visión
        if CAMERA_AVAILABLE:
            self.root.after(500, self.auto_start_vision_system)
    
    def _build_conversational_instructions(self):
        """
        Construye instrucciones dinámicas para conversación natural con contexto temporal
        """
        from datetime import datetime
        import locale
        
        # Obtener hora actual y contexto temporal
        now = datetime.now()
        hour = now.hour
        day_name = now.strftime("%A")
        
        # Saludo contextual según hora del día
        if 5 <= hour < 12:
            time_context = "Es por la mañana"
            greeting_suggestion = "buenos días"
        elif 12 <= hour < 19:
            time_context = "Es por la tarde"
            greeting_suggestion = "buenas tardes"
        else:
            time_context = "Es por la noche"
            greeting_suggestion = "buenas noches"
        
        # Contexto semanal
        if day_name in ["Monday"]:
            week_context = "Es lunes, inicio de semana"
        elif day_name in ["Friday"]:
            week_context = "Es viernes, casi fin de semana"
        elif day_name in ["Saturday", "Sunday"]:
            week_context = "Es fin de semana"
        else:
            week_context = f"Es {day_name}"
        
        instructions = f"""Tu NOMBRE ES FRANK. Fuiste creado en el Cluster Tecnológico por 2 estudiantes de ingenierías y un ingeniero electrónico. Esta información sobre tu identidad es MUY IMPORTANTE - siempre recuérdala si te preguntan quién eres o quién te creó.

Eres un asistente conversacional amigable y natural. Tu objetivo es hacer que cada interacción se sienta como hablar con un amigo cercano que te escucha atentamente.

REGLA FUNDAMENTAL DE BREVEDAD:
- Las respuestas DEBEN ser CORTAS por defecto (1-3 oraciones máximo)
- Solo expande si el usuario EXPLÍCITAMENTE pide más información o una respuesta extensa
- Ve directo al grano, sin rodeos ni introducciones largas

CONTEXTO TEMPORAL:
{time_context}. {week_context}.
Usa este contexto de forma natural en tus respuestas cuando sea relevante.

PERSONALIDAD Y ESTILO:
- Sé cálido, amigable y cercano (pero no excesivo)
- Habla como en una conversación casual, no como un manual
- Usa un tono relajado y accesible
- Muestra interés genuino en lo que te cuentan
- EVITA usar fillers como "mmm", "ehh", "hmm" - ve directo al punto
- Varía tu tono: entusiasta cuando sea apropiado, empático cuando detectes preocupación

CONVERSACIÓN NATURAL:
1. **Mantén el contexto**: Recuerda lo que se viene hablando y haz referencias naturales
   - "Como mencionaste antes..."
   - "Sobre lo que dijiste de..."
   - "Retomando lo anterior..."

2. **Haz preguntas de seguimiento**: No solo respondas y te quedes callado
   - "¿Y eso cómo te fue?"
   - "¿Quieres que profundice en algo?"
   - "¿Te ayudo con algo más relacionado?"
   
3. **Respuestas graduales**: No sueltes todo de golpe, divide en partes naturales
   - Da la info principal primero
   - Espera implícitamente si el usuario quiere más detalle
   - Si hay mucho que decir, ofrece: "¿Quieres que continúe?" o "Hay más, ¿te lo cuento?"

4. **Clarifica cuando sea necesario**: Si algo no está claro, pregunta naturalmente
   - "¿Te refieres a X o a Y?"
   - "Solo para estar seguro, ¿hablas de...?"
   - "¿Podrías darme un ejemplo?"

5. **Timing natural**: 
   - Respuestas simples → Directas y rápidas
   - Respuestas complejas → Ve directo al punto sin rodeos
   - Mantén fluidez sin pausas innecesarias

REGLAS DE ORO:
✅ SÍ habla así:
- "Claro, entiendo"
- "Interesante, ¿y entonces qué pasó?"
- "Sí, tiene sentido. ¿Seguiste...?"
- "Perfecto. ¿Algo más que necesites?"
- "Déjame ayudarte con eso"

❌ NO hables así:
- "Como modelo de lenguaje..."
- "No puedo sentir emociones..."
- "Mi función es..."
- "Procesando tu solicitud..."
- Demasiado formal o robótico

MEMORIA CONVERSACIONAL:
- Mantén el hilo de la conversación activo
- Si el usuario cambia de tema, síguelo naturalmente sin perder contexto
- Si retoma algo anterior, reconéctalo: "Ah sí, sobre lo que preguntaste de..."

CUANDO USES VISIÓN:
- Si recibes contexto con [VISIÓN], úsalo naturalmente
- Describe lo que ves como si lo estuvieras viendo en tiempo real
- Haz comentarios relevantes basados en la imagen
- Pregunta si quieren más detalles: "¿Quieres que me fije en algo específico?"

TONO EMOCIONAL:
- Adapta tu tono al del usuario
- Si suena entusiasta → Responde con energía
- Si suena preocupado → Sé empático y tranquilizador
- Si suena casual → Mantén la informalidad

BREVEDAD INTELIGENTE:
- Por defecto, respuestas MUY CORTAS (1-3 oraciones)
- NUNCA expandas a menos que te lo pidan explícitamente
- Evita parrafadas largas al hablar
- Si algo requiere extensión, pregunta: "¿Quieres que te cuente más?"

Recuerda: Eres FRANK, creado en el Cluster Tecnológico. No eres un asistente técnico genérico, eres un compañero de conversación amigable y atento. Respuestas CORTAS siempre."""
        
        return instructions
    
    def _add_to_conversation_memory(self, role, content):
        """
        Agrega mensajes a la memoria conversacional para mantener contexto
        """
        self.conversation_memory.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now()
        })
        
        # Mantener solo los últimos N mensajes para no saturar
        if len(self.conversation_memory) > self.max_memory_items:
            self.conversation_memory = self.conversation_memory[-self.max_memory_items:]
    
    def _get_conversation_context(self):
        """
        Obtiene resumen de conversación reciente para contexto
        """
        if not self.conversation_memory:
            return ""
        
        # Crear resumen de últimas interacciones
        recent_topics = []
        for msg in self.conversation_memory[-5:]:  # Últimos 5 mensajes
            content_preview = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
            recent_topics.append(f"{msg['role']}: {content_preview}")
        
        return f"\n[Contexto reciente de conversación:\n" + "\n".join(recent_topics) + "]"
    
    def _ensure_pipewire_output(self):
        """
        CRÍTICO PARA BLUETOOTH: Asegura que el audio de salida use PipeWire/default.
        
        Los dispositivos Bluetooth (JBL Flip 6, etc.) solo son accesibles a través de 
        PipeWire. Si se usa un dispositivo ALSA directo (como surround40, front, etc.),
        el audio NO llegará al altavoz Bluetooth.
        
        Esta función busca el dispositivo "default" que está conectado a PipeWire,
        y PipeWire automáticamente rutea al sink predeterminado (que es el Bluetooth).
        """
        try:
            device_count = self.audio.get_device_count()
            default_output_idx = None
            pipewire_output_idx = None
            
            for i in range(device_count):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    name = info.get('name', '').lower()
                    max_out = info.get('maxOutputChannels', 0)
                    
                    if max_out > 0:
                        # Preferencia: "default" es el mejor porque usa PipeWire real
                        if name == 'default' and default_output_idx is None:
                            default_output_idx = i
                            log_audio.debug(f"Encontrado 'default' output: [{i}]")
                        # Segunda opción: pipewire explícito
                        elif 'pipewire' in name and pipewire_output_idx is None:
                            pipewire_output_idx = i
                            log_audio.debug(f"Encontrado 'pipewire' output: [{i}]")
                except Exception:
                    continue
            
            # Preferir 'default' sobre 'pipewire' porque 'default' usa PulseAudio compat
            # que es más estable para Bluetooth
            best_output = default_output_idx if default_output_idx is not None else pipewire_output_idx
            
            if best_output is not None:
                old_output = self.output_device_index
                self.output_device_index = best_output
                
                # Verificar qué nombre tiene el dispositivo seleccionado
                output_name = self.audio.get_device_info_by_index(best_output).get('name', 'unknown')
                
                if old_output != best_output:
                    log_audio.info(f"🔊 Salida de audio configurada para Bluetooth:")
                    log_audio.info(f"   Dispositivo [{best_output}]: {output_name}")
                    log_audio.info(f"   (PipeWire ruteará al sink predeterminado)")
                else:
                    log_audio.debug(f"Salida ya configurada correctamente: [{best_output}] {output_name}")
            else:
                log_audio.warning("⚠️ No se encontró dispositivo PipeWire/default para salida")
                log_audio.warning("   El audio Bluetooth puede no funcionar correctamente")
                
        except Exception as e:
            log_audio.error(f"Error configurando salida PipeWire: {e}")
    
    def find_pipewire_device(self):
        """Encuentra el dispositivo PipeWire para mejor compatibilidad"""
        if not AUDIO_AVAILABLE:
            return None, None
        
        try:
            device_count = self.audio.get_device_count()
            input_dev = None
            output_dev = None
            
            for i in range(device_count):
                try:
                    info = self.audio.get_device_info_by_index(i)
                    name = info.get('name', '').lower()
                    
                    # Buscar PipeWire o default
                    if 'pipewire' in name or 'default' in name:
                        if info.get('maxInputChannels', 0) > 0 and input_dev is None:
                            input_dev = i
                            log_audio.info(f"Input PipeWire encontrado: [{i}] {info['name']}")
                        if info.get('maxOutputChannels', 0) > 0 and output_dev is None:
                            output_dev = i
                            log_audio.info(f"Output PipeWire encontrado: [{i}] {info['name']}")
                except Exception as e:
                    continue
            
            return input_dev, output_dev
        except Exception as e:
            log_audio.error(f"Error buscando PipeWire: {e}")
            return None, None
    
    def find_supported_rate(self):
        """Encuentra un sample rate soportado por el hardware"""
        if not AUDIO_AVAILABLE:
            return None
        
        # Detectar dispositivos PipeWire si no están configurados
        if self.input_device_index is None or self.output_device_index is None:
            pw_in, pw_out = self.find_pipewire_device()
            if pw_in is not None:
                self.input_device_index = pw_in
            if pw_out is not None:
                self.output_device_index = pw_out
            
        # Probar 24kHz primero (rate de la API)
        test_rates = [24000, 48000, 44100, 32000, 16000]
        
        for rate in test_rates:
            try:
                # Preparar kwargs
                input_kwargs = {
                    'format': FORMAT,
                    'channels': CHANNELS,
                    'rate': rate,
                    'input': True,
                    'frames_per_buffer': CHUNK
                }
                
                # Agregar device index si está configurado
                if self.input_device_index is not None:
                    input_kwargs['input_device_index'] = self.input_device_index
                
                # Test input
                stream = self.audio.open(**input_kwargs)
                stream.close()
                
                log_audio.info(f"✅ Audio rate soportado: {rate} Hz")
                # Solo actualizar hw_rate si NO hay un thread de playback activo
                # Esto previene cambiar las ratios mientras se reproduce audio
                if not (hasattr(self, 'playback_thread') and self.playback_thread and self.playback_thread.is_alive()):
                    self.hw_rate = rate
                    self.resample_ratio_in = self.api_rate / self.hw_rate
                    self.resample_ratio_out = self.hw_rate / self.api_rate
                    log_audio.debug(f"Ratios actualizadas: in={self.resample_ratio_in:.3f}, out={self.resample_ratio_out:.3f}")
                else:
                    log_audio.debug(f"Playback thread activo - manteniendo ratios existentes (out={self.resample_ratio_out:.3f})")
                return rate
            except Exception as e:
                continue
        
        log_audio.error("No se encontró rate compatible")
        return None
    
    def _is_multiplexed_device(self, device_index):
        """
        Verifica si un device debe usar multiplexado (evitar lock exclusivo).
        
        IMPORTANTE PARA BLUETOOTH:
        - "default" y "pipewire" deben usar multiplexado porque:
          1. Evitan lock exclusivo del hardware
          2. Permiten que PipeWire rutee al dispositivo Bluetooth correcto
          3. El sink predeterminado de PipeWire es el Bluetooth (JBL, etc.)
        
        Retorna True = NO especificar output_device_index (dejar que sistema elija)
        Retorna False = Usar output_device_index específico
        """
        if device_index is None:
            return True
        
        try:
            device_info = self.audio.get_device_info_by_index(device_index)
            device_name = device_info['name'].lower()
            
            # TODOS estos dispositivos deben usar multiplexado:
            # - "default" → PulseAudio compat → PipeWire → Bluetooth sink
            # - "pipewire" → PipeWire directo → Bluetooth sink
            # - "sysdefault" / "dmix" → Evitar lock exclusivo
            multiplexed_devices = ['default', 'pipewire', 'sysdefault', 'dmix']
            
            if any(name in device_name for name in multiplexed_devices):
                log_audio.debug(f"Device '{device_name}' - usando multiplexado del sistema (Bluetooth compatible)")
                return True
            
            return False
        except Exception as e:
            log_audio.warning(f"Error verificando device {device_index}: {e}")
            return True  # En caso de duda, usar multiplexado
    
    def resample_audio(self, audio_data, ratio):
        """Resample audio usando scipy o numpy como fallback"""
        try:
            # Convertir bytes a numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            original_length = len(audio_np)
            
            # Calcular nueva longitud (usar round para evitar errores de redondeo)
            new_length = int(round(original_length * ratio))
            
            # Si no necesita resampling, retornar original
            if abs(ratio - 1.0) < 0.01 or new_length == original_length:
                return audio_data
            
            # CASO ESPECIAL: Si new_length es 0 o negativo, retornar audio original
            if new_length <= 0:
                log_audio.warning(f"Resampling: new_length={new_length} inválido (ratio={ratio:.3f}), usando original")
                return audio_data
            
            # OPTIMIZACIÓN: Usar siempre numpy (más rápido que scipy para audio en tiempo real)
            # La interpolación lineal es suficiente para audio de voz (no necesitamos FFT de scipy)
            old_indices = np.arange(original_length)
            new_indices = np.linspace(0, original_length - 1, new_length)
            
            # Interpolación lineal sobre float32 para precisión
            resampled = np.interp(new_indices, old_indices, audio_np.astype(np.float32))
            
            # Convertir de vuelta a int16 con clipping
            resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
            
            log_audio.debug(f"Resampled: {original_length} → {len(resampled)} samples (ratio={ratio:.3f})")
            
            # Verificar que el tamaño sea correcto antes de retornar
            if len(resampled) != new_length:
                log_audio.error(f"Resampling size mismatch: expected {new_length}, got {len(resampled)} - usando original")
                return audio_data
            
            return resampled.tobytes()
            
        except Exception as e:
            log_audio.error(f"Error en resampling (ratio={ratio:.3f}, input_size={len(audio_data)}): {e}")
            import traceback
            log_audio.debug(traceback.format_exc())
            return audio_data
        
    def auto_start_vision_system(self):
        """Inicia automáticamente el EyeTrackerThread y el sistema de visión"""
        try:
            # Iniciar sistema de tracking/cámara
            self.start_camera_simple()
            
            self.append_message("Sistema", "🤖 Sistema de visión GPT-4 iniciado automáticamente", 'system')
        except Exception as e:
            log_vision.error(f"Error iniciando sistema automático: {e}")
    
    def start_camera_simple(self):
        """
        Inicia el sistema de cámara usando EyeTrackerThread como dueño único.
        El EyeTrackerThread captura frames, muestra ventana de detección y comparte vía SharedState.
        GPT-4V lee frames del SharedState para análisis.
        """
        if not CAMERA_AVAILABLE:
            self.append_message("Sistema", "❌ OpenCV no disponible", 'system')
            return
        
        # ═══════════════════════════════════════════════════════════════════════
        # INICIAR EyeTrackerThread (si está disponible)
        # ═══════════════════════════════════════════════════════════════════════
        if EYE_TRACKER_AVAILABLE and self.shared_state:
            # Resetear estado si hubo ejecución previa
            self.shared_state.reset()
            
            # Crear e iniciar el thread de tracking
            # headless=False: Muestra ventana de OpenCV con detección de rostros
            self.eye_tracker = EyeTrackerThread(
                shared_state=self.shared_state,
                camera_index=0,
                headless=False,  # Mostrar ventana de OpenCV con detección facial
                enable_servos=True  # Habilitar servos si están disponibles
            )
            self.eye_tracker.start()
            
            # Esperar a que la cámara esté lista
            if not self.shared_state.wait_for_camera(timeout=10.0):
                self.append_message("Sistema", "❌ Timeout esperando cámara del tracker", 'system')
                return
            
            log_vision.info("✅ EyeTrackerThread iniciado - Ventana de detección activa")
            self.append_message("Sistema", "👁️ Tracking facial activo (ventana de detección visible)", 'system')
            
            self.camera_running = True
            if hasattr(self, 'camera_button'):
                self.camera_button.config(text="⏹️ Cerrar", bg='#e74c3c')
            
            # Iniciar thread de actualización GPT-4V (sin ventana de Tkinter)
            self.start_gpt4v_refresh_thread()
            
            self.append_message("Sistema", "📹 Sistema de visión iniciado", 'system')
            return
        
        # ═══════════════════════════════════════════════════════════════════════
        # FALLBACK: Cámara directa sin tracker (mantiene ventana Tkinter)
        # ═══════════════════════════════════════════════════════════════════════
        log_vision.warning("⚠️ EyeTrackerThread no disponible, usando cámara directa")
        for cam_idx in [0, 1, 2]:
            self.camera_cap = cv2.VideoCapture(cam_idx)
            if self.camera_cap.isOpened():
                log_vision.info(f"Cámara abierta en índice {cam_idx}")
                break
        
        if not self.camera_cap or not self.camera_cap.isOpened():
            self.append_message("Sistema", "❌ No se encontró cámara", 'system')
            return
        
        # Crear ventana de video (solo fallback)
        self.camera_window = tk.Toplevel(self.root)
        self.camera_window.title("📹 GPT-4 Vision Feed")
        self.camera_window.geometry("400x350")
        self.camera_window.configure(bg='#2c3e50')
        self.camera_window.protocol("WM_DELETE_WINDOW", self.stop_camera_simple)
        
        # Label para el video
        self.camera_label = tk.Label(self.camera_window, bg='#2c3e50')
        self.camera_label.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        
        # Status label
        self.camera_status = tk.Label(
            self.camera_window,
            text="🟢 GPT-4 Vision activo (modo fallback)",
            font=('Arial', 9),
            fg='#27ae60',
            bg='#2c3e50'
        )
        self.camera_status.pack(pady=5)
        
        self.camera_running = True
        if hasattr(self, 'camera_button'):
            self.camera_button.config(text="⏹️ Cerrar", bg='#e74c3c')
        
        # Iniciar actualización de frames (solo fallback)
        self.update_camera_frame_simple()
        
        # Iniciar thread de actualización GPT-4V
        self.start_gpt4v_refresh_thread()
        
        self.append_message("Sistema", "📹 Cámara GPT-4V iniciada (modo fallback)", 'system')
    
    def stop_camera_simple(self):
        """Detiene la cámara y el EyeTrackerThread"""
        self.camera_running = False
        
        # ═══════════════════════════════════════════════════════════════════════
        # DETENER EyeTrackerThread (cierra su propia ventana de OpenCV)
        # ═══════════════════════════════════════════════════════════════════════
        if self.eye_tracker and self.eye_tracker.is_alive():
            log_vision.info("🛑 Deteniendo EyeTrackerThread...")
            self.eye_tracker.stop()
            self.eye_tracker.join(timeout=5.0)
            self.eye_tracker = None
            log_vision.info("✅ EyeTrackerThread detenido")
        
        # ═══════════════════════════════════════════════════════════════════════
        # LIMPIAR VENTANA TKINTER (solo si se usó fallback)
        # ═══════════════════════════════════════════════════════════════════════
        if self.camera_label and hasattr(self.camera_label, 'imgtk'):
            del self.camera_label.imgtk
            self.camera_label.config(image='')
        
        # Cerrar cámara directa (solo si se usó fallback)
        if self.camera_cap:
            self.camera_cap.release()
            self.camera_cap = None
        
        if self.camera_window:
            self.camera_window.destroy()
            self.camera_window = None
        
        # Resetear referencias
        self.camera_label = None
        self.camera_status = None
        
        if hasattr(self, 'camera_button'):
            self.camera_button.config(text="📹 Cámara", bg='#16a085')
        
        self.append_message("Sistema", "📹 Cámara detenida", 'system')
    
    def read_camera_frame(self):
        """
        Lee un frame de la cámara.
        Usa SharedState si EyeTrackerThread está activo, sino usa cámara directa.
        """
        # Opción 1: Leer del SharedState (EyeTrackerThread activo)
        if EYE_TRACKER_AVAILABLE and self.shared_state and self.shared_state.is_tracker_running():
            success, frame, age = self.shared_state.get_frame()
            if success and age < 1.0:  # Frame fresco (< 1 segundo)
                return True, frame
            else:
                log_vision.debug(f"Frame desactualizado o no disponible (age={age:.2f}s)")
                return False, None
        
        # Opción 2: Leer directamente de la cámara (fallback)
        if self.camera_cap and self.camera_cap.isOpened():
            ret, frame = self.camera_cap.read()
            return ret, frame
        
        return False, None
    
    def update_camera_frame_simple(self):
        """Actualiza el frame de la cámara en la ventana Tkinter (solo para fallback)"""
        if not self.camera_running or not self.camera_window:
            return
        
        try:
            ret, frame = self.read_camera_frame()
            
            if ret and frame is not None:
                # Redimensionar
                height, width = frame.shape[:2]
                max_width = 380
                max_height = 220
                
                scale = min(max_width / width, max_height / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                
                frame_resized = cv2.resize(frame, (new_width, new_height))
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                
                img = Image.fromarray(frame_rgb)
                imgtk = ImageTk.PhotoImage(image=img)
                
                # FIX MEMORY LEAK: Liberar referencia anterior antes de asignar nueva
                if hasattr(self.camera_label, 'imgtk') and self.camera_label.imgtk is not None:
                    del self.camera_label.imgtk
                
                self.camera_label.imgtk = imgtk
                self.camera_label.configure(image=imgtk)
            
            # Optimizado: 15 FPS en lugar de 30 FPS (más liviano, igual de fluido)
            self.camera_window.after(66, self.update_camera_frame_simple)
            
        except Exception as e:
            if self.camera_status:
                self.camera_status.config(text=f"❌ Error: {str(e)}", fg='#e74c3c')
            self.camera_window.after(100, self.update_camera_frame_simple)
    
    def start_gpt4v_refresh_thread(self):
        """Inicia thread de actualización periódica GPT-4V"""
        if self.gpt4v_thread and self.gpt4v_thread.is_alive():
            return
        
        def refresh_loop():
            import time
            gc_counter = 0  # Contador para GC periódico
            while self.camera_running:
                if not self.gpt4v_analyzing:
                    current_time = time.time()
                    if current_time - self.last_gpt4v_time >= self.gpt4v_refresh_interval:
                        self.update_gpt4v_background()
                        self.last_gpt4v_time = current_time
                        
                        # Forzar garbage collection cada 5 actualizaciones para liberar memoria
                        gc_counter += 1
                        if gc_counter >= 5:
                            gc.collect()
                            gc_counter = 0
                time.sleep(2)
        
        self.gpt4v_thread = threading.Thread(target=refresh_loop, daemon=True)
        self.gpt4v_thread.start()
    
    def update_gpt4v_background(self):
        """Actualiza descripción GPT-4V en background (no cuenta en costos mostrados)"""
        if not GPT4V_AVAILABLE or not self.gpt4v_service:
            return
        
        def analyze():
            self.gpt4v_analyzing = True
            try:
                import time
                ret, frame = self.read_camera_frame()
                if ret and frame is not None:
                    result = self.gpt4v_service.quick_description(frame)
                    
                    vision_description = None
                    if isinstance(result, dict) and result.get('success'):
                        vision_description = result['description']
                    elif isinstance(result, str):
                        vision_description = result
                    
                    if vision_description:
                        self.last_gpt4v_description = vision_description
                        self.last_gpt4v_time = time.time()
                        
                        if self.camera_status:
                            status_text = f"👁️ {vision_description[:40]}..."
                            self.root.after(0, lambda: self.camera_status.config(text=status_text, fg='#27ae60'))
                        
                        log_vision.debug(f"🔄 Background refresh: {vision_description[:50]}...")
            except Exception as e:
                log_vision.error(f"GPT-4V background: {e}")
            finally:
                self.gpt4v_analyzing = False
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def capture_and_send_visual_context(self):
        """Captura imagen y envía contexto visual al asistente en modo voz"""
        if not self.camera_running or not GPT4V_AVAILABLE or not self.gpt4v_service:
            log_vision.debug("Captura visual omitida: cámara o GPT-4V no disponibles")
            return
        
        if not self.connected or not self.ws:
            log_vision.debug("Captura visual omitida: WebSocket no conectado")
            return
        
        try:
            import time
            log_vision.debug("Capturando contexto visual para modo voz...")
            
            ret, frame = self.read_camera_frame()
            if ret and frame is not None:
                result = self.gpt4v_service.quick_description(frame)
                
                vision_description = None
                cost = 0
                
                if isinstance(result, dict):
                    if result.get('success'):
                        vision_description = result.get('description', '')
                        cost = result.get('cost', 0)
                    else:
                        vision_description = result.get('description', result.get('error', ''))
                elif isinstance(result, str):
                    vision_description = result
                
                if vision_description:
                    # Actualizar cache
                    self.last_gpt4v_description = vision_description
                    self.last_gpt4v_time = time.time()
                    self.gpt4v_analyses_count += 1
                    self.gpt4v_total_cost += cost
                    
                    # Enviar contexto visual al asistente
                    context_message = {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "system",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": f"[CONTEXTO VISUAL ACTUAL] {vision_description}"
                                }
                            ]
                        }
                    }
                    self.ws.send(json.dumps(context_message))
                    
                    # Actualizar stats en UI
                    self.root.after(0, self.update_stats)
                    
                    log_vision.info(f"👁️ Contexto visual enviado: {vision_description[:60]}...")
                    log_vision.info(f"💰 ${cost:.4f} | Total: ${self.gpt4v_total_cost:.3f} ({self.gpt4v_analyses_count} análisis)")
                    
                    # Mostrar indicador en chat
                    self.root.after(0, self.append_message, "Sistema", "👁️ Contexto visual capturado", 'system')
                else:
                    log_vision.error("Error: No se obtuvo descripción de GPT-4V")
            else:
                log_vision.error("Error: No se pudo capturar frame de cámara")
                
        except Exception as e:
            log_vision.error(f"Error capturando contexto visual: {e}")
    
    def start_periodic_vision_updates(self):
        """Inicia actualizaciones periódicas del contexto visual durante modo voz"""
        # Cancelar timer existente si lo hay
        self.stop_periodic_vision_updates()
        
        if not self.camera_running or not GPT4V_AVAILABLE or not self.gpt4v_service:
            return
        
        log_vision.debug(f"Iniciando actualizaciones periódicas de visión (cada {self.vision_update_interval_ms/1000}s)")
        self._schedule_next_vision_update()
    
    def stop_periodic_vision_updates(self):
        """Detiene las actualizaciones periódicas del contexto visual"""
        if self._vision_update_timer_id is not None:
            try:
                self.root.after_cancel(self._vision_update_timer_id)
            except:
                pass
            self._vision_update_timer_id = None
            log_vision.debug("Actualizaciones periódicas de visión detenidas")
    
    def _schedule_next_vision_update(self):
        """Programa la próxima actualización de contexto visual"""
        if not self.recording:
            # Si ya no está grabando, no programar más actualizaciones
            self._vision_update_timer_id = None
            return
        
        # Capturar y enviar contexto visual
        self.capture_and_send_visual_context()
        
        # Programar próxima actualización
        self._vision_update_timer_id = self.root.after(
            self.vision_update_interval_ms,
            self._schedule_next_vision_update
        )
    
    def setup_ui(self):
        """Crea la interfaz"""
        # Header
        header_frame = tk.Frame(self.root, bg='#2c3e50', height=80)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        # Estado
        self.status_label = tk.Label(
            header_frame,
            text="● Desconectado",
            font=('Arial', 11, 'bold'),
            fg='#e74c3c',
            bg='#2c3e50'
        )
        self.status_label.pack(pady=(10, 5))
        
        # Monitor
        self.stats_label = tk.Label(
            header_frame,
            text="Tokens: 0 entrada, 0 salida | Costo: $0.0000",
            font=('Arial', 9),
            fg='#ecf0f1',
            bg='#2c3e50'
        )
        self.stats_label.pack()
        
        # Modelo
        model_label = tk.Label(
            header_frame,
            text=f"Modelo: {MODEL}",
            font=('Arial', 8),
            fg='#95a5a6',
            bg='#2c3e50'
        )
        model_label.pack()
        
        # PANEL DE ESTADO VISUAL (Nuevo)
        self.status_panel = tk.Frame(self.root, bg='#34495e', height=50)
        self.status_panel.pack(fill=tk.X, padx=0, pady=0)
        self.status_panel.pack_propagate(False)
        
        # Indicador de estado del asistente
        self.activity_label = tk.Label(
            self.status_panel,
            text="⚪ Inactivo",
            font=('Arial', 10, 'bold'),
            fg='#95a5a6',
            bg='#34495e'
        )
        self.activity_label.pack(side=tk.LEFT, padx=20, pady=10)
        
        # Barra de volumen (canvas para animación)
        self.volume_canvas = tk.Canvas(
            self.status_panel,
            width=200,
            height=30,
            bg='#2c3e50',
            highlightthickness=0
        )
        self.volume_canvas.pack(side=tk.LEFT, padx=10)
        
        # Crear barras de volumen (10 barras)
        self.volume_bars = []
        bar_width = 15
        bar_gap = 5
        for i in range(10):
            x = i * (bar_width + bar_gap)
            bar = self.volume_canvas.create_rectangle(
                x, 30, x + bar_width, 30,
                fill='#27ae60',
                outline=''
            )
            self.volume_bars.append(bar)
        
        # Iniciar animación de volumen
        self.current_volume_level = 0
        self.animate_volume()
        
        # Chat
        chat_frame = tk.Frame(self.root, bg='#ffffff')
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=('Arial', 10),
            bg='#ffffff',
            fg='#2c3e50',
            state=tk.DISABLED,
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # Tags
        self.chat_display.tag_config('user', foreground='#3498db', font=('Arial', 10, 'bold'))
        self.chat_display.tag_config('assistant', foreground='#27ae60', font=('Arial', 10, 'bold'))
        self.chat_display.tag_config('system', foreground='#95a5a6', font=('Arial', 9, 'italic'))
        self.chat_display.tag_config('time', foreground='#95a5a6', font=('Arial', 8))
        
        # Controles
        controls_frame = tk.Frame(self.root, bg='#f0f0f0')
        controls_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        
        # Botón modo
        mode_text = "🎤 Modo Voz" if self.audio_available else "🎤 (Audio no disponible)"
        self.mode_button = tk.Button(
            controls_frame,
            text=mode_text,
            command=self.toggle_voice_mode,
            bg='#9b59b6',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2' if self.audio_available else 'arrow',
            state=tk.DISABLED,
            padx=15,
            pady=5
        )
        self.mode_button.pack(side=tk.LEFT)
        
        # Label modo
        self.mode_label = tk.Label(
            controls_frame,
            text="Modo: Texto 💬",
            font=('Arial', 9),
            fg='#7f8c8d',
            bg='#f0f0f0'
        )
        self.mode_label.pack(side=tk.LEFT, padx=10)
        
        # Label voz
        self.voice_label = tk.Label(
            controls_frame,
            text=f"Voz: {self.voice}",
            font=('Arial', 8),
            fg='#95a5a6',
            bg='#f0f0f0'
        )
        self.voice_label.pack(side=tk.RIGHT, padx=10)
        
        # Botón config
        self.config_button = tk.Button(
            controls_frame,
            text="⚙️ Configuración",
            command=self.open_config,
            bg='#34495e',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=5
        )
        self.config_button.pack(side=tk.RIGHT)
        
        # Botón cámara
        if CAMERA_AVAILABLE:
            self.camera_button = tk.Button(
                controls_frame,
                text="📹 Cámara",
                command=self.toggle_camera,
                bg='#16a085',
                fg='white',
                font=('Arial', 9, 'bold'),
                relief=tk.FLAT,
                cursor='hand2',
                padx=15,
                pady=5
            )
            self.camera_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Botón config audio
        if self.audio_available and self.audio_device_manager:
            self.audio_config_button = tk.Button(
                controls_frame,
                text="🎧 Audio",
                command=self.open_audio_config,
                bg='#8e44ad',
                fg='white',
                font=('Arial', 9, 'bold'),
                relief=tk.FLAT,
                cursor='hand2',
                padx=15,
                pady=5
            )
            self.audio_config_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Entrada
        self.input_frame = tk.Frame(self.root, bg='#f0f0f0')
        self.input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        # Texto
        self.message_entry = tk.Text(
            self.input_frame,
            height=3,
            font=('Arial', 10),
            wrap=tk.WORD,
            relief=tk.SOLID,
            borderwidth=1
        )
        self.message_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.message_entry.bind('<Return>', self.handle_enter)
        self.message_entry.bind('<Shift-Return>', lambda e: None)
        
        # Botones
        self.button_frame = tk.Frame(self.input_frame, bg='#f0f0f0')
        self.button_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Enviar
        self.send_button = tk.Button(
            self.button_frame,
            text="Enviar\n(Enter)",
            command=self.send_message,
            bg='#3498db',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            width=10,
            state=tk.DISABLED
        )
        self.send_button.pack()
        
        # Iniciar modo manos libres (VAD automático)
        self.record_button = tk.Button(
            self.button_frame,
            text="🎤 Iniciar",
            command=self.toggle_recording,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            width=10,
            state=tk.DISABLED
        )
        
        self.append_message("Sistema", "Conectando...", 'system')
        
    def handle_enter(self, event):
        if not event.state & 0x1:
            self.send_message()
            return 'break'
        return None
    
    def update_activity_status(self, status, color='#95a5a6'):
        """Actualiza el indicador visual de actividad"""
        status_icons = {
            'idle': '⚪',
            'listening': '🎤',
            'processing': '🤔',
            'speaking': '🗣️',
            'interrupted': '🚫'
        }
        
        status_texts = {
            'idle': 'Inactivo',
            'listening': 'Escuchando...',
            'processing': 'Pensando...',
            'speaking': 'Hablando...',
            'interrupted': 'Interrumpido'
        }
        
        icon = status_icons.get(status, '⚪')
        text = status_texts.get(status, 'Inactivo')
        
        self.activity_label.config(
            text=f"{icon} {text}",
            fg=color
        )
    
    def set_volume_level(self, level):
        """Establece el nivel de volumen visual (0-100)"""
        self.current_volume_level = max(0, min(100, level))
    
    def animate_volume(self):
        """Anima las barras de volumen"""
        try:
            # Calcular cuántas barras mostrar basado en el nivel
            num_bars = int((self.current_volume_level / 100) * 10)
            
            for i, bar in enumerate(self.volume_bars):
                if i < num_bars:
                    # Barra activa con gradiente de color
                    if i < 6:
                        color = '#27ae60'  # Verde
                    elif i < 8:
                        color = '#f39c12'  # Amarillo
                    else:
                        color = '#e74c3c'  # Rojo
                    
                    height = 5 + (i * 2)  # Altura gradual
                    self.volume_canvas.coords(bar, 
                        i * 20, 30 - height,
                        i * 20 + 15, 30
                    )
                    self.volume_canvas.itemconfig(bar, fill=color)
                else:
                    # Barra inactiva
                    self.volume_canvas.coords(bar,
                        i * 20, 30,
                        i * 20 + 15, 30
                    )
                    self.volume_canvas.itemconfig(bar, fill='#34495e')
            
            # Decay suave del volumen
            if self.current_volume_level > 0:
                self.current_volume_level *= 0.85
            
            # Continuar animación
            self.root.after(50, self.animate_volume)
        except:
            pass
        
    def append_message(self, sender, message, tag='user'):
        self.chat_display.config(state=tk.NORMAL)
        time_str = datetime.now().strftime("%H:%M:%S")
        self.chat_display.insert(tk.END, f"[{time_str}] ", 'time')
        self.chat_display.insert(tk.END, f"{sender}: ", tag)
        self.chat_display.insert(tk.END, f"{message}\n\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def update_stats(self):
        # Costo Realtime API
        api_cost = (self.input_tokens / 1_000_000 * PRICE_INPUT + 
                    self.output_tokens / 1_000_000 * PRICE_OUTPUT)
        
        # Costo total incluyendo GPT-4V
        total = api_cost + self.gpt4v_total_cost
        
        stats_text = (f"Tokens: {self.input_tokens:,} in, {self.output_tokens:,} out | "
                     f"API: ${api_cost:.4f}")
        
        # Agregar costos GPT-4V si hay análisis
        if self.gpt4v_analyses_count > 0:
            stats_text += f" | 📸 Vision: ${self.gpt4v_total_cost:.3f} ({self.gpt4v_analyses_count}x)"
        
        stats_text += f" | 💰 Total: ${total:.3f}"
        
        self.stats_label.config(text=stats_text)
        
    def update_status(self, status, color):
        self.status_label.config(text=f"● {status}", fg=color)
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            # Debug: imprimir eventos recibidos
            if event_type not in ['response.audio.delta', 'input_audio_buffer.speech_started']:
                log_ws.debug(f"Evento: {event_type}")
            
            if event_type == 'input_audio_buffer.speech_started':
                # INTERRUPCIÓN INTELIGENTE: Usuario empezó a hablar
                if self.assistant_speaking:
                    log_ws.info("🚫 Usuario interrumpe al asistente")
                    self.user_interrupted = True
                    # NOTA: La boca se detiene automáticamente en play_audio()
                    # cuando detecta user_interrupted = True
                    self.cancel_response()
                    self.root.after(0, self.update_activity_status, 'interrupted', '#e74c3c')
                    self.root.after(0, self.append_message, "Sistema", "🚫 Interrumpido por usuario", 'system')
                else:
                    self.root.after(0, self.update_activity_status, 'listening', '#3498db')
                    self.root.after(0, self.append_message, "Sistema", "🎤 Escuchando...", 'system')
                    # Simular volumen mientras escucha
                    self.set_volume_level(60)
            
            elif event_type == 'input_audio_buffer.speech_stopped':
                self.user_interrupted = False
                self.root.after(0, self.update_activity_status, 'processing', '#f39c12')
                self.root.after(0, self.append_message, "Sistema", "⏸️ Procesando voz...", 'system')
                self.set_volume_level(0)
            
            elif event_type == 'conversation.item.input_audio_transcription.completed':
                transcript = data.get('transcript', '')
                if transcript:
                    self.root.after(0, self.append_message, "Tú (voz)", transcript, 'user')
                    log_ws.info(f"Transcripción: {transcript}")
                    
                    # Detectar comando de calibración
                    if self.detect_calibration_keyword(transcript):
                        log_audio.info("🎯 Comando de calibración detectado")
                        self.handle_calibration_command()
            
            elif event_type == 'conversation.item.input_audio_transcription.failed':
                error = data.get('error', {})
                log_ws.error(f"Error transcripción: {error}")
            
            elif event_type == 'session.created':
                self.connected = True
                self.root.after(0, self.update_status, "Conectado", "#27ae60")
                self.root.after(0, lambda: self.send_button.config(state=tk.NORMAL))
                if self.audio_available:
                    self.root.after(0, lambda: self.mode_button.config(state=tk.NORMAL))
                self.root.after(0, self.append_message, "Sistema", "✓ Conectado. Escribe o usa voz!", 'system')
                
            elif event_type == 'session.updated':
                log_ws.debug("Sesión actualizada")
                
            elif event_type == 'response.text.delta':
                text = data.get('delta', '')
                if not hasattr(self, 'current_response'):
                    self.current_response = ""
                    # Iniciar animación de boca para respuestas de texto
                    if self.mouth_controller and not self.voice_mode:
                        self.mouth_controller.start_speaking()
                        log.debug("🗣️ Iniciando animación de boca (texto)")
                self.current_response += text
                log_ws.debug(f"Text delta: {text}")
                
            elif event_type == 'response.text.done':
                if hasattr(self, 'current_response') and self.current_response:
                    log_ws.debug(f"Text done: {self.current_response}")
                    self.root.after(0, self.append_message, "Asistente", self.current_response, 'assistant')
                    delattr(self, 'current_response')
                # Detener animación de boca para respuestas de texto
                if self.mouth_controller and not self.voice_mode:
                    self.mouth_controller.stop_speaking()
                    log.debug("✅ Animación de boca detenida (texto)")
                    
            elif event_type == 'response.done':
                # Manejar fin de respuesta
                response_data = data.get('response', {})
                
                # Actualizar tokens
                usage = response_data.get('usage', {})
                if usage:
                    self.input_tokens += usage.get('input_tokens', 0)
                    self.output_tokens += usage.get('output_tokens', 0)
                    self.root.after(0, self.update_stats)
                    log_ws.debug(f"Response done - Tokens: {usage}")
                
                # Si es respuesta de texto (no audio) extraer y mostrar
                output = response_data.get('output', [])
                if output and not self.voice_mode:
                    for item in output:
                        if item.get('type') == 'message':
                            content = item.get('content', [])
                            for c in content:
                                if c.get('type') == 'text':
                                    text = c.get('text', '')
                                    if text:
                                        log_ws.debug(f"Respuesta texto: {text[:80]}")
                                        self.root.after(0, self.append_message, "Asistente", text, 'assistant')
                
            elif event_type == 'response.audio_transcript.delta':
                # Transcripción parcial en tiempo real
                delta = data.get('delta', '')
                if delta:
                    if not hasattr(self, 'current_audio_transcript'):
                        self.current_audio_transcript = ""
                        # INTERRUPCIÓN: Asistente empezó a responder
                        self.assistant_speaking = True
                        self.current_response_item_id = data.get('item_id')
                        self.played_audio_bytes = 0  # Reset para nuevo turno
                        self.root.after(0, self.update_activity_status, 'speaking', '#9b59b6')
                        log_ws.info("🗣️ Asistente empezando a hablar")
                        # NOTA: La boca se inicia en response.audio.delta para sincronizar con audio real
                    self.current_audio_transcript += delta
                    # Simular volumen del asistente
                    self.set_volume_level(70)
                    # Streaming output (se mantiene print para flush parcial)
                    print(delta, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                # Transcripción completa del asistente (pero el audio puede seguir)
                transcript = data.get('transcript', '')
                if hasattr(self, 'current_audio_transcript'):
                    transcript = self.current_audio_transcript
                    delattr(self, 'current_audio_transcript')
                
                # Agregar respuesta del asistente a memoria conversacional
                if transcript:
                    self._add_to_conversation_memory("assistant", transcript)
                
                # NOTA: NO detener la boca aquí - el audio sigue reproduciéndose
                # La boca se detendrá en response.audio.done
                log_ws.debug("Transcripción completa (audio puede continuar)")
                
                if transcript and not self.user_interrupted:
                    print()  # Nueva línea tras streaming
                    self.root.after(0, self.append_message, "Asistente (voz)", transcript, 'assistant')
                    log_ws.info(f"Asistente: {transcript}")
                    
            elif event_type == 'response.audio.delta':
                audio_b64 = data.get('delta', '')
                if audio_b64 and not self.user_interrupted:
                    audio_bytes = base64.b64decode(audio_b64)
                    # Capturar item_id para truncation en interrupciones
                    if not self.current_response_item_id:
                        self.current_response_item_id = data.get('item_id')
                    
                    # NOTA: La boca se controla en play_audio() para sincronizar
                    # con la reproducción REAL del audio, no con la llegada de datos
                    
                    # Usar buffer del enhancer si está disponible para double buffering
                    if self.audio_enhancer:
                        self.audio_enhancer.add_to_playback_buffer(audio_bytes)
                    else:
                        self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                # Respuesta de audio completa (datos recibidos, pero pueden estar reproduciéndose)
                self.assistant_speaking = False
                self.current_response_item_id = None
                self.played_audio_bytes = 0
                
                # NOTA: La boca se detiene en play_audio() cuando REALMENTE
                # termina de reproducirse el audio (no cuando llegan los datos)
                
                # Restaurar estado del micrófono
                if self.echo_canceller:
                    self.echo_canceller.notify_playback_stopped()
                    log_aec.debug("Micrófono reactivado (AEC maneja eco residual)")
                else:
                    log_audio.debug("Micrófono reactivado")
                
                self.root.after(0, self.update_activity_status, 'idle', '#95a5a6')
                self.set_volume_level(0)
                log_ws.info("✅ Audio recibido completo (reproducción puede continuar)")
                
                if not self.user_interrupted:
                    if self.audio_enhancer:
                        self.audio_enhancer.add_to_playback_buffer(None)
                    else:
                        self.output_queue.put(None)
                else:
                    # Si fue interrumpido, limpiar buffers
                    self.clear_audio_buffers()
                    
            elif event_type == 'error':
                error = data.get('error', {})
                error_msg = error.get('message', 'Error desconocido')
                self.root.after(0, self.append_message, "Error", error_msg, 'system')
                log_ws.error(f"{error}")
                
        except Exception as e:
            log_ws.error(f"Error procesando mensaje: {e}")
            import traceback
            traceback.print_exc()
            
    def on_error(self, ws, error):
        self.root.after(0, self.update_status, "Error", "#e74c3c")
        self.root.after(0, self.append_message, "Sistema", f"Error: {error}", 'system')
        
    def on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.root.after(0, self.update_status, "Desconectado", "#e74c3c")
        self.root.after(0, lambda: self.send_button.config(state=tk.DISABLED))
        
    def on_open(self, ws):
        self.connected = True
        self.update_session_config()
        
        # Iniciar/reiniciar thread de playback para reproducir audio
        # Verificar si el thread está vivo, no solo si fue iniciado alguna vez
        if self.audio_available:
            thread_is_alive = hasattr(self, 'playback_thread') and self.playback_thread and self.playback_thread.is_alive()
            
            if not thread_is_alive:
                log_audio.info("🔄 Iniciando thread de playback...")
                self.playback_thread = threading.Thread(target=self.play_audio, daemon=True)
                self.playback_thread.start()
                self.playback_thread_started = True
                log_audio.debug("✅ Thread de playback iniciado")
            else:
                log_audio.debug("Thread de playback ya está activo")
        
    def update_session_config(self):
        # SIEMPRE usar audio para que las respuestas se reproduzcan en el parlante
        # Aunque el input sea solo texto, el output será audio
        modalities = ["text", "audio"]
        
        # Regenerar instrucciones con contexto temporal actualizado
        self.instructions = self._build_conversational_instructions()
        
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": modalities,
                "instructions": self.instructions,
                "temperature": self.temperature,
                "voice": self.voice,
                "output_audio_format": "pcm16",
                "max_response_output_tokens": 4096
            }
        }
        
        # Solo agregar configuración de INPUT de audio si está en modo voz
        if self.voice_mode:
            session_config["session"].update({
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1",
                    "language": "es"  # ⭐ FORZAR ESPAÑOL para transcripción correcta
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.4,           # Más sensible (0.4 detecta voces normales; 0.6 era muy alto)
                    "prefix_padding_ms": 300,   # Audio previo al habla (ms)
                    "silence_duration_ms": 600, # Silencio antes de procesar (ms)
                    "create_response": True,
                    "interrupt_response": True
                },
                "input_audio_noise_reduction": {
                    "type": "far_field"  # far_field: robot/laptop con mic separado del speaker
                }
            })
        
        if self.ws and self.connected:
            self.ws.send(json.dumps(session_config))
        
    def start_connection(self):
        if not API_KEY:
            self.append_message("Error", "No API KEY", 'system')
            return
            
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        self.ws = websocket.WebSocketApp(
            URL,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        ws_thread.start()
        
    def toggle_voice_mode(self):
        log.debug(f"toggle_voice_mode llamado - audio_available: {self.audio_available}, voice_mode actual: {self.voice_mode}")
        if not self.audio_available:
            log_audio.debug("Audio no disponible, retornando")
            return
            
        self.voice_mode = not self.voice_mode
        log.debug(f"voice_mode cambiado a: {self.voice_mode}")
        
        if self.voice_mode:
            self.mode_label.config(text="Modo: Voz 🎤", fg='#e74c3c')
            self.mode_button.config(text="💬 Modo Texto", bg='#3498db')
            self.message_entry.pack_forget()
            self.send_button.pack_forget()
            self.record_button.pack(fill=tk.Y)
            self.record_button.config(state=tk.NORMAL if self.connected else tk.DISABLED)
            self.append_message("Sistema", "✓ Modo voz activado", 'system')
            
            # Iniciar grabación directamente (modo manos libres)
            if self.connected and not self.recording:
                log_audio.debug("Auto-iniciando grabación en 500ms...")
                self.root.after(500, self.start_recording)
        else:
            # Detener grabación si está activa
            if self.recording:
                self.stop_recording()
            
            self.mode_label.config(text="Modo: Texto 💬", fg='#7f8c8d')
            self.mode_button.config(text="🎤 Modo Voz", bg='#9b59b6')
            self.record_button.pack_forget()
            self.message_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
            self.send_button.pack(fill=tk.Y)
            self.append_message("Sistema", "✓ Modo texto activado", 'system')
            
        self.update_session_config()
        
    def toggle_recording(self):
        log_audio.debug(f"toggle_recording llamado - recording: {self.recording}")
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()
            
    def start_recording(self):
        log_audio.debug("start_recording llamado")
        # Detectar rate soportado
        if self.find_supported_rate() is None:
            log_audio.error("No se pudo encontrar rate soportado")
            self.append_message("Sistema", "❌ No se pudo inicializar audio", 'system')
            return
        
        log_audio.debug(f"Rate detectado: {self.hw_rate} Hz")
        
        # Resetear audio enhancer para nueva sesión
        if self.audio_enhancer:
            self.audio_enhancer.reset()
            log_audio.debug("AudioEnhancer reseteado")
        
        # Resetear echo canceller
        if self.echo_canceller:
            self.echo_canceller.reset()
        
        self.recording = True
        self.record_button.config(text="⏹️ Detener", bg='#27ae60')
        
        # Mensaje informativo - modo manos libres con VAD
        features = []
        if self.audio_enhancer:
            features = ["VAD Automático", "AGC", "Noise Gate"]
        if self.echo_canceller:
            features.append("AEC")
            features_str = " + ".join(features)
            self.append_message("Sistema", f"🎤 Modo manos libres activado | {features_str}", 'system')
            self.append_message("Sistema", "� Calibrando ruido ambiente... (permanece en silencio 2 segundos)", 'system')
            self.append_message("Sistema", "💡 Después habla normalmente - el sistema filtra el ruido automáticamente", 'system')
        else:
            self.append_message("Sistema", f"🎤 Modo manos libres activado", 'system')
        
        # CAPTURAR CONTEXTO VISUAL si cámara está disponible
        self.capture_and_send_visual_context()
        
        # Iniciar actualizaciones periódicas de contexto visual
        self.start_periodic_vision_updates()
        
        log_audio.debug("Iniciando threads de audio...")
        self.audio_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.audio_thread.start()
        
        # No iniciar playback thread aquí porque ya se inicia en on_open
        # para permitir reproducción en modo texto también
        log_audio.debug("Thread de grabación iniciado")
        
    def stop_recording(self):
        self.recording = False
        self.record_button.config(text="🎤 Iniciar", bg='#e74c3c')
        self.append_message("Sistema", "⏸️ Modo manos libres detenido", 'system')
        
        # Detener actualizaciones periódicas de contexto visual
        self.stop_periodic_vision_updates()
    
    def detect_calibration_keyword(self, transcript):
        """Detecta si la transcripción contiene el comando de calibración"""
        keywords = [
            "calibra el micrófono",
            "calibra el microfono",
            "calibrar el micrófono", 
            "calibrar el microfono",
            "calibra micrófono",
            "calibra microfono",
            "recalibra",
            "recalibrar"
        ]
        transcript_lower = transcript.lower()
        return any(keyword in transcript_lower for keyword in keywords)
    
    def handle_calibration_command(self):
        """Maneja el comando de calibración del micrófono"""
        try:
            # Cancelar la respuesta del asistente en curso
            if self.ws and self.connected:
                cancel_event = {
                    "type": "response.cancel"
                }
                self.ws.send(json.dumps(cancel_event))
                log_ws.info("Respuesta cancelada para calibración")
            
            # Enviar respuesta de confirmación del sistema
            self.root.after(0, self.append_message, "Asistente", 
                          "Entendido, calibrando ahora. Aguarda un segundo.", 'assistant')
            
            # Resetear el audio enhancer para recalibrar
            if self.audio_enhancer:
                self.audio_enhancer.reset()
                log_audio.info("🔄 Audio enhancer reseteado para recalibración")
                
                # Mensaje para el usuario
                self.root.after(0, self.append_message, "Sistema", 
                              "🔧 Calibrando ruido ambiente... (permanece en silencio 2 segundos)", 'system')
            else:
                self.root.after(0, self.append_message, "Sistema", 
                              "⚠️ Audio enhancer no disponible para calibración", 'system')
                              
        except Exception as e:
            log_audio.error(f"Error en calibración: {e}")
            self.root.after(0, self.append_message, "Sistema", 
                          f"❌ Error al calibrar: {e}", 'system')
        
    def record_audio(self):
        try:
            # Preparar kwargs con dispositivo si está configurado
            stream_kwargs = {
                'format': FORMAT,
                'channels': CHANNELS,
                'rate': self.hw_rate,
                'input': True,
                'frames_per_buffer': CHUNK
            }
            
            # Usar dispositivo preferido si está configurado
            # 🔧 SOLUCIÓN USB BUFFERING: NO especificar index para devices multiplexados
            if self.input_device_index is not None and not self._is_multiplexed_device(self.input_device_index):
                stream_kwargs['input_device_index'] = self.input_device_index
                log_audio.debug(f"Usando dispositivo de entrada específico: {self.input_device_index}")
            else:
                log_audio.debug(f"Usando multiplexado del sistema (device index no especificado)")
            
            stream = self.audio.open(**stream_kwargs)
            
            log_audio.info(f"🎤 Micrófono activado ({self.hw_rate} Hz)")
            if self.audio_enhancer:
                log_audio.info("✅ Procesamiento activo: Filtro 300-3400Hz + Noise Gate + AGC + Anti-clipping")
                log_audio.info("🇪🇸 Transcripción configurada en ESPAÑOL")
            
            # Contador para logging de debug (no saturar consola)
            audio_chunk_counter = 0
            
            while self.recording:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    
                    # Calcular volumen REAL del micrófono para visualización
                    audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    rms = np.sqrt(np.mean(audio_array ** 2))
                    volume_percent = min(100, (rms / 3000) * 100)
                    
                    # Actualizar visualización de volumen
                    if volume_percent > 1:  # Solo actualizar si hay sonido
                        self.root.after(0, self.set_volume_level, volume_percent)
                    
                    # Resample a API rate (24000 Hz)
                    if self.hw_rate != self.api_rate:
                        data = self.resample_audio(data, self.resample_ratio_in)
                    
                    # Procesamiento de audio antes de enviar a la API
                    # 1. Echo Canceller: activo mientras haya audio reproduciéndose O mientras
                    #    assistant_speaking sea True (la señal del servidor tarda en llegar)
                    aec_active = self.echo_canceller and (
                        self.assistant_speaking or 
                        (self.echo_canceller.is_playing or 
                         self.echo_canceller.samples_since_stop < self.echo_canceller.echo_tail_samples)
                    )
                    if aec_active:
                        data = self.echo_canceller.process(data)
                    
                    # 2. AudioEnhancer: filtro pasa-banda, noise gate, AGC, anti-clipping
                    if self.audio_enhancer:
                        data = self.audio_enhancer.process_input(data)
                    
                    if self.connected:
                        self.send_audio_chunk(data)
                        
                        # Log cada 50 chunks (~1 segundo) para diagnóstico de audio
                        audio_chunk_counter += 1
                        if audio_chunk_counter % 50 == 0:
                            processed_audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                            processed_rms = np.sqrt(np.mean(processed_audio ** 2))
                            gate_info = ""
                            if self.audio_enhancer:
                                stats = self.audio_enhancer.get_stats()
                                gate_info = f" | Gate: {stats['gate_state']} | Ganancia: {stats['current_gain']} | Ruido base: {stats['noise_floor']}"
                            log_audio.info(f"🎤 AUDIO ENVIADO | Vol: {volume_percent:.1f}% | RMS procesado: {processed_rms:.0f}{gate_info}")
                except Exception as e:
                    if self.recording:
                        log_audio.error(f"Error audio: {e}")
                    break
                    
        except Exception as e:
            self.root.after(0, self.append_message, "Error", f"Micrófono: {e}", 'system')
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
                log_audio.info("🎤 Micrófono detenido")
                
    def play_audio(self):
        """Reproduce audio del asistente con procesamiento profesional - ROBUSTO"""
        stream = None
        consecutive_errors = 0
        max_consecutive_errors = 10
        is_playing = False  # Flag para saber si estamos reproduciendo activamente
        
        # Capturar hw_rate y ratios al inicio del thread para evitar cambios durante ejecución
        playback_hw_rate = self.hw_rate
        playback_resample_ratio = self.resample_ratio_out
        
        try:
            # Intentar 24kHz primero (rate nativo de la API), fallback a hw_rate
            playback_rate = self.api_rate
            needs_resample = False
            
            # Preparar kwargs con dispositivo si está configurado
            stream_kwargs = {
                'format': FORMAT,
                'channels': CHANNELS,
                'rate': playback_rate,
                'output': True,
                'frames_per_buffer': CHUNK * 4  # Buffer más grande para playback sin cortes
            }
            
            # Usar dispositivo preferido si está configurado
            # 🔧 SOLUCIÓN BLUETOOTH: NO especificar index para devices multiplexados (default/pipewire)
            # Esto permite que PipeWire rutee al sink predeterminado (JBL Flip 6, etc.)
            if self.output_device_index is not None and not self._is_multiplexed_device(self.output_device_index):
                stream_kwargs['output_device_index'] = self.output_device_index
                log_audio.debug(f"Usando dispositivo de salida específico: {self.output_device_index}")
            else:
                log_audio.info(f"🔊 Usando salida PipeWire/default → Bluetooth (JBL, etc.)")
            
            try:
                stream = self.audio.open(**stream_kwargs)
                log_audio.info(f"🔊 Altavoz activado ({playback_rate} Hz) - Audio listo para reproducir")
            except Exception as e_24k:
                # 24kHz no soportado, fallback a hardware rate (48kHz típico)
                log_audio.warning(f"24kHz no soportado ({e_24k}), forzando {playback_hw_rate} Hz con resampling")
                playback_rate = playback_hw_rate
                needs_resample = True
                stream_kwargs['rate'] = playback_rate
                stream = self.audio.open(**stream_kwargs)
                log_audio.info(f"🔊 Altavoz activado ({playback_rate} Hz) CON RESAMPLING activo (ratio={playback_resample_ratio:.4f})")
            
            if self.audio_enhancer:
                log_audio.debug("Playback: Double buffering + Anti-clipping")
            
            # Reproducir mientras esté conectado (no solo mientras graba)
            # Esto permite reproducir respuestas en modo texto también
            while self.connected:
                try:
                    # Usar buffer del enhancer si está disponible
                    if self.audio_enhancer:
                        audio_chunk = self.audio_enhancer.get_from_playback_buffer(timeout=0.1)
                        if audio_chunk is None:
                            log_audio.debug("Fin de mensaje de audio")
                            # DETENER BOCA: Audio terminó de reproducirse
                            if is_playing and self.mouth_controller:
                                self.mouth_controller.stop_speaking()
                                log_audio.debug("🔇 Boca detenida (fin de reproducción real)")
                                is_playing = False
                            # IMPORTANTE: Dar tiempo para que el buffer de PyAudio se vacíe completamente
                            # Esto evita que se corte el audio antes de terminar
                            import time
                            time.sleep(0.2)  # 200ms para permitir que el buffer interno se reproduzca
                            continue
                        if audio_chunk == b'':
                            continue
                    else:
                        audio_chunk = self.output_queue.get(timeout=0.1)
                        if audio_chunk is None:
                            log_audio.debug("Fin de mensaje de audio")
                            # DETENER BOCA: Audio terminó de reproducirse
                            if is_playing and self.mouth_controller:
                                self.mouth_controller.stop_speaking()
                                log_audio.debug("🔇 Boca detenida (fin de reproducción real)")
                                is_playing = False
                            # IMPORTANTE: Dar tiempo para que el buffer de PyAudio se vacíe completamente
                            import time
                            time.sleep(0.2)  # 200ms para permitir que el buffer interno se reproduzca
                            continue
                    
                    # INICIAR BOCA: Primer chunk de audio real
                    if not is_playing and self.mouth_controller:
                        self.mouth_controller.start_speaking()
                        log_audio.debug("🗣️ Boca iniciada (reproducción real)")
                        is_playing = True
                    
                    # Chequear interrupción antes de reproducir
                    if self.user_interrupted:
                        log_audio.debug("Reproducción interrumpida")
                        # Detener boca si fue interrumpido
                        if is_playing and self.mouth_controller:
                            self.mouth_controller.stop_speaking()
                            is_playing = False
                        continue
                    
                    # AEC: Alimentar referencia ANTES de reproducir
                    # El echo canceller necesita saber qué sale por el altavoz
                    if self.echo_canceller:
                        self.echo_canceller.feed_reference(audio_chunk)
                    
                    # Resamplear si el hardware no soporta 24kHz
                    if needs_resample:
                        original_len = len(audio_chunk)
                        original_samples = original_len // 2  # bytes to samples (int16 = 2 bytes)
                        expected_samples = int(round(original_samples * playback_resample_ratio))
                        
                        audio_chunk_resampled = self.resample_audio(audio_chunk, playback_resample_ratio)
                        
                        # Verificar que el resampling funcionó correctamente
                        resampled_samples = len(audio_chunk_resampled) // 2
                        if abs(resampled_samples - expected_samples) > 1:
                            log_audio.warning(f"Resampling deviation: expected ~{expected_samples}, got {resampled_samples} samples")
                        
                        log_audio.debug(f"Resampling: {original_len} bytes ({original_samples} samples) → {len(audio_chunk_resampled)} bytes ({resampled_samples} samples) | ratio={playback_resample_ratio:.4f}")
                        audio_chunk = audio_chunk_resampled
                    
                    # Verificar que el stream esté activo antes de escribir
                    if stream and stream.is_active():
                        stream.write(audio_chunk)
                        self.played_audio_bytes += len(audio_chunk)
                        consecutive_errors = 0  # Reset contador de errores en éxito
                    else:
                        # Stream inactivo, intentar recrearlo
                        log_audio.warning("Stream inactivo, recreando...")
                        if stream:
                            try:
                                stream.stop_stream()
                                stream.close()
                            except:
                                pass
                        stream = self.audio.open(**stream_kwargs)
                        log_audio.info("✅ Stream recreado")
                        
                except queue.Empty:
                    consecutive_errors = 0  # Queue vacío no es error
                    continue
                except Exception as e:
                    consecutive_errors += 1
                    if self.connected:
                        error_msg = str(e)
                        log_audio.error(f"Error reproduciendo chunk ({consecutive_errors}/{max_consecutive_errors}): {error_msg}")
                        
                        # Si es error de broadcast/shape, dar más detalles
                        if "broadcast" in error_msg or "shape" in error_msg:
                            log_audio.error(f"  → Problema de resampling detectado")
                            log_audio.error(f"  → hw_rate={playback_hw_rate}, api_rate={self.api_rate}, ratio_out={playback_resample_ratio:.4f}")
                            log_audio.error(f"  → needs_resample={needs_resample}, playback_rate={playback_rate}")
                    
                    # Si hay demasiados errores consecutivos, recrear stream
                    if consecutive_errors >= max_consecutive_errors:
                        log_audio.warning("⚠️ Demasiados errores, recreando stream...")
                        try:
                            if stream:
                                stream.stop_stream()
                                stream.close()
                            stream = self.audio.open(**stream_kwargs)
                            consecutive_errors = 0
                            log_audio.info("✅ Stream recreado después de errores")
                        except Exception as recreate_error:
                            log_audio.error(f"No se pudo recrear stream: {recreate_error}")
                            # Esperar un poco antes de continuar
                            import time
                            time.sleep(0.5)
                    
                    # NO usar break - continuar loop para mantener thread vivo
                    continue
                    
            stream.stop_stream()
            stream.close()
            log_audio.info("🔊 Altavoz detenido")
            
        except Exception as e:
            log_audio.error(f"Error iniciando altavoz: {e}")
            log_audio.warning("Modo solo entrada (micrófono)")
            self.root.after(0, self.append_message, "Error", f"Altavoz: {e}", 'system')
            # Vaciar cola aunque no haya output
            while self.connected:
                try:
                    if self.audio_enhancer:
                        self.audio_enhancer.get_from_playback_buffer(timeout=0.1)
                    else:
                        self.output_queue.get(timeout=0.1)
                except:
                    pass
        finally:
            if 'stream' in locals():
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
                
    def send_audio_chunk(self, audio_bytes):
        if not self.connected:
            log_audio.debug("send_audio_chunk: No conectado")
            return
        if not self.voice_mode:
            log_audio.debug("send_audio_chunk: voice_mode es False")
            return
        
        # Log cada 500 chunks para verificar que se está enviando
        if not hasattr(self, '_audio_chunk_count'):
            self._audio_chunk_count = 0
            log_audio.debug("Iniciando contador de chunks")
        self._audio_chunk_count += 1
        if self._audio_chunk_count % 500 == 0:
            log_audio.debug(f"✓ {self._audio_chunk_count} chunks enviados")
            
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        self.ws.send(json.dumps(event))
    
    def cancel_response(self):
        """Cancela la respuesta actual del asistente cuando el usuario interrumpe"""
        if not self.connected:
            return
        
        try:
            # Enviar evento de cancelación a la API
            cancel_event = {
                "type": "response.cancel"
            }
            self.ws.send(json.dumps(cancel_event))
            log_ws.info("📨 Cancelación enviada a API")
            
            # Truncar audio no reproducido para sincronizar contexto del modelo
            # Sin truncate, el modelo cree que el usuario escuchó TODA la respuesta
            if self.current_response_item_id:
                audio_end_ms = int(self.played_audio_bytes / (2 * self.api_rate) * 1000)
                truncate_event = {
                    "type": "conversation.item.truncate",
                    "item_id": self.current_response_item_id,
                    "content_index": 0,
                    "audio_end_ms": audio_end_ms
                }
                self.ws.send(json.dumps(truncate_event))
                log_ws.info(f"✂️ Audio truncado a {audio_end_ms}ms")
            
            # NO limpiar input_audio_buffer — contiene la voz nueva del usuario
            
            # Limpiar buffers de audio de salida
            self.clear_audio_buffers()
            
        except Exception as e:
            log_ws.error(f"Error cancelando respuesta: {e}")
    
    def clear_audio_buffers(self):
        """Limpia todos los buffers de audio pendientes"""
        try:
            # Limpiar queue normal
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                except:
                    break
            
            # Limpiar buffer del AudioEnhancer si existe
            if self.audio_enhancer:
                self.audio_enhancer.clear_playback_buffer()
            
            log_audio.debug("🗑️ Buffers de audio limpiados")
            
        except Exception as e:
            log_audio.error(f"Error limpiando buffers: {e}")
        
    def send_message(self):
        message = self.message_entry.get('1.0', tk.END).strip()
        
        if not message or not self.connected:
            return
        
        # Agregar contexto visual si está disponible
        full_message = message
        display_message = message
        
        # GPT-4V con cache inteligente
        if self.camera_running and GPT4V_AVAILABLE and self.gpt4v_service:
            import time
            current_time = time.time()
            cache_age = current_time - self.last_gpt4v_time
            
            # Usar cache si es reciente (<6s), sino generar fresco
            if self.last_gpt4v_description and cache_age < self.gpt4v_cache_max_age:
                vision_description = self.last_gpt4v_description
                full_message = f"Contexto visual actual: {vision_description}\n\nPregunta del usuario: {message}"
                display_message = f"{message} 👁️"
                log_vision.debug(f"💾 Cache usado ({cache_age:.1f}s): {vision_description[:50]}...")
            else:
                log_vision.debug("Generando análisis fresco...")
                
                ret, frame = self.read_camera_frame()
                if ret and frame is not None:
                    result = self.gpt4v_service.quick_description(frame)
                    
                    vision_description = None
                    cost = 0
                    
                    if isinstance(result, dict):
                        if result.get('success'):
                            vision_description = result.get('description', '')
                            cost = result.get('cost', 0)
                        else:
                            vision_description = result.get('description', result.get('error', ''))
                    elif isinstance(result, str):
                        vision_description = result
                    
                    if vision_description:
                        self.last_gpt4v_description = vision_description
                        self.last_gpt4v_time = current_time
                        self.gpt4v_analyses_count += 1
                        self.gpt4v_total_cost += cost
                        
                        full_message = f"Contexto visual actual: {vision_description}\n\nPregunta del usuario: {message}"
                        display_message = f"{message} 👁️"
                        
                        # Actualizar stats en UI
                        self.update_stats()
                        
                        log_vision.info(f"✅ ${cost:.4f} | Total: ${self.gpt4v_total_cost:.3f} ({self.gpt4v_analyses_count} análisis)")
                    else:
                        log_vision.error("Error en análisis GPT-4V")
                else:
                    log_vision.error("Error capturando frame")
        
        if display_message == message:
            log_ws.debug("Enviando sin visión")
        
        # Agregar mensaje del usuario a memoria conversacional
        self._add_to_conversation_memory("user", message)
        
        self.append_message("Tú", display_message, 'user')
        self.message_entry.delete('1.0', tk.END)
        
        # Obtener contexto de conversación reciente
        conversation_context = self._get_conversation_context()
        if conversation_context:
            # Agregar contexto al mensaje para que el asistente lo tenga
            full_message = full_message + conversation_context
        
        message_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": full_message}]
            }
        }
        
        # Especificar explícitamente que queremos audio en la respuesta
        response_event = {
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"]
            }
        }
        
        log_ws.debug(f"Enviando mensaje texto+audio: {full_message[:80]}...")
        self.ws.send(json.dumps(message_event))
        self.ws.send(json.dumps(response_event))
        
        self.input_tokens += len(message.split())
        self.update_stats()
        
    def open_config(self):
        """Abre ventana de configuración"""
        config_win = tk.Toplevel(self.root)
        config_win.title("⚙️ Configuración")
        config_win.geometry("500x450")
        config_win.configure(bg='#f0f0f0')
        config_win.transient(self.root)
        config_win.grab_set()
        
        # Título
        tk.Label(
            config_win,
            text="Personaliza tu asistente",
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        ).pack(pady=15)
        
        main_frame = tk.Frame(config_win, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # VOZ
        voice_frame = tk.LabelFrame(main_frame, text="Voz", font=('Arial', 10, 'bold'), bg='#f0f0f0')
        voice_frame.pack(fill=tk.X, pady=10)
        
        voice_var = tk.StringVar(value=self.voice)
        voices = [
            ("Coral (natural) ⭐", "coral"),
            ("Marin (clara) ⭐", "marin"),
            ("Cedar (cálida) ⭐", "cedar"),
            ("Alloy (neutral)", "alloy"),
            ("Echo (masculina)", "echo"),
            ("Sage (serena)", "sage"),
            ("Ash (firme)", "ash"),
            ("Ballad (suave)", "ballad"),
            ("Shimmer (brillante)", "shimmer"),
            ("Verse (expresiva)", "verse")
        ]
        
        for text, value in voices:
            tk.Radiobutton(
                voice_frame,
                text=text,
                variable=voice_var,
                value=value,
                font=('Arial', 9),
                bg='#f0f0f0',
                selectcolor='#ecf0f1'
            ).pack(anchor=tk.W, padx=10, pady=2)
        
        # TEMPERATURA
        temp_frame = tk.LabelFrame(main_frame, text="Temperatura (creatividad)", font=('Arial', 10, 'bold'), bg='#f0f0f0')
        temp_frame.pack(fill=tk.X, pady=10)
        
        temp_label = tk.Label(temp_frame, text=f"Valor: {self.temperature}", font=('Arial', 9), bg='#f0f0f0')
        temp_label.pack(pady=5)
        
        temp_var = tk.DoubleVar(value=self.temperature)
        temp_scale = tk.Scale(
            temp_frame,
            from_=0.0,
            to=1.0,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=temp_var,
            bg='#f0f0f0',
            highlightthickness=0,
            command=lambda v: temp_label.config(text=f"Valor: {float(v):.1f}")
        )
        temp_scale.pack(fill=tk.X, padx=10, pady=5)
        
        # INSTRUCCIONES
        inst_frame = tk.LabelFrame(main_frame, text="Instrucciones (Prompt)", font=('Arial', 10, 'bold'), bg='#f0f0f0')
        inst_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        inst_text = tk.Text(
            inst_frame,
            height=5,
            font=('Arial', 9),
            wrap=tk.WORD,
            relief=tk.SOLID,
            borderwidth=1
        )
        inst_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        inst_text.insert('1.0', self.instructions)
        
        # BOTONES
        button_frame = tk.Frame(config_win, bg='#f0f0f0')
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_config():
            self.voice = voice_var.get()
            self.temperature = temp_var.get()
            self.instructions = inst_text.get('1.0', tk.END).strip()
            self.voice_label.config(text=f"Voz: {self.voice}")
            self.update_session_config()
            self.append_message("Sistema", f"✓ Config guardada: {self.voice}, Temp={self.temperature}", 'system')
            config_win.destroy()
        
        tk.Button(
            button_frame,
            text="💾 Guardar",
            command=save_config,
            bg='#27ae60',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
        
        tk.Button(
            button_frame,
            text="❌ Cancelar",
            command=config_win.destroy,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
    
    def open_audio_config(self):
        """Abre ventana de configuración de dispositivos de audio mejorada"""
        if not self.audio_device_manager:
            self.append_message("Sistema", "❌ Gestor de audio no disponible", 'system')
            return
        
        config_win = tk.Toplevel(self.root)
        config_win.title("🎧 Configuración de Audio")
        config_win.geometry("650x700")
        config_win.configure(bg='#f0f0f0')
        config_win.transient(self.root)
        config_win.grab_set()
        
        # Título
        tk.Label(
            config_win,
            text="Configuración de Dispositivos de Audio",
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        ).pack(pady=15)
        
        # ESTADO ACTUAL
        status_frame = tk.Frame(config_win, bg='#d5f4e6', relief=tk.SOLID, borderwidth=2)
        status_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        tk.Label(
            status_frame,
            text="🟢 Estado Actual",
            font=('Arial', 11, 'bold'),
            bg='#d5f4e6',
            fg='#27ae60'
        ).pack(pady=(10, 5))
        
        # Mostrar dispositivos actualmente en uso
        current_input, current_output = self.audio_device_manager.get_preferred_device_names()
        
        current_input_label = tk.Label(
            status_frame,
            text=f"🎤 Micrófono: {current_input if current_input else 'No configurado'}",
            font=('Arial', 9),
            bg='#d5f4e6',
            fg='#2c3e50',
            wraplength=550,
            justify=tk.LEFT
        )
        current_input_label.pack(padx=10, pady=2, anchor=tk.W)
        
        current_output_label = tk.Label(
            status_frame,
            text=f"🔊 Altavoz: {current_output if current_output else 'No configurado'}",
            font=('Arial', 9),
            bg='#d5f4e6',
            fg='#2c3e50',
            wraplength=550,
            justify=tk.LEFT
        )
        current_output_label.pack(padx=10, pady=(2, 10), anchor=tk.W)
        
        main_frame = tk.Frame(config_win, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Obtener dispositivos
        input_names, output_names = self.audio_device_manager.get_device_names()

        def _rename_device(device_var, device_type):
            """Permite asignar un nombre amigable a un dispositivo (alias)"""
            selected = device_var.get()
            if not selected or 'Sin dispositivos' in selected:
                return
            dev_info = self.audio_device_manager.get_device_full_info_from_name(selected, device_type)
            if not dev_info:
                self.append_message("Sistema", "❌ No se pudo identificar el dispositivo", 'system')
                return
            original_name = dev_info["name"]
            current_alias = self.audio_device_manager.get_device_alias(original_name) or original_name
            from tkinter import simpledialog
            new_name = simpledialog.askstring(
                "Renombrar dispositivo",
                f"Nombre para:\n{original_name}",
                initialvalue=current_alias,
                parent=config_win
            )
            if new_name is not None:
                self.audio_device_manager.set_device_alias(original_name, new_name.strip())
                # Refrescar ventana con el nuevo nombre aplicado
                config_win.destroy()
                self.open_audio_config()

        # DISPOSITIVO DE ENTRADA (Micrófono)
        input_frame = tk.LabelFrame(main_frame, text="🎤 Dispositivo de Entrada (Micrófono)", 
                                     font=('Arial', 11, 'bold'), bg='#f0f0f0', fg='#2c3e50')
        input_frame.pack(fill=tk.X, pady=10)
        
        # Obtener selección actual
        current_input_name, current_output_name = self.audio_device_manager.get_preferred_device_names()
        
        # Si hay dispositivo preferido, encontrar su índice en la lista
        input_selection = 0
        if current_input_name:
            for i, name in enumerate(input_names):
                # Comparar solo el nombre base sin etiquetas
                if any(part in name for part in current_input_name.split()):
                    input_selection = i
                    break
        
        input_var = tk.StringVar(value=input_names[input_selection] if input_names else "")
        
        input_dropdown = tk.OptionMenu(input_frame, input_var, *input_names)
        input_dropdown.config(
            bg='white',
            font=('Arial', 9),
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=0,
            width=55
        )
        input_dropdown["menu"].config(bg='white', font=('Arial', 9))
        input_dropdown.pack(fill=tk.X, padx=10, pady=10)
        
        # Botones de test y ayuda
        input_buttons = tk.Frame(input_frame, bg='#f0f0f0')
        input_buttons.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        test_input_btn = tk.Button(
            input_buttons,
            text="🎤 Probar (1s)",
            command=lambda: self.test_audio_device(input_var.get(), "input"),
            bg='#3498db',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        )
        test_input_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            input_buttons,
            text="🏷️ Renombrar",
            command=lambda: _rename_device(input_var, "input"),
            bg='#9b59b6',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(
            input_buttons,
            text="⭐ = Dispositivo físico recomendado",
            font=('Arial', 8),
            bg='#f0f0f0',
            fg='#7f8c8d'
        ).pack(side=tk.LEFT, padx=10)
        
        # DISPOSITIVO DE SALIDA (Altavoces)
        output_frame = tk.LabelFrame(main_frame, text="🔊 Dispositivo de Salida (Altavoces)", 
                                      font=('Arial', 11, 'bold'), bg='#f0f0f0', fg='#2c3e50')
        output_frame.pack(fill=tk.X, pady=10)
        
        # Si hay dispositivo preferido, encontrar su índice en la lista
        output_selection = 0
        if current_output_name:
            for i, name in enumerate(output_names):
                # Comparar solo el nombre base sin etiquetas
                if any(part in name for part in current_output_name.split()):
                    output_selection = i
                    break
        
        output_var = tk.StringVar(value=output_names[output_selection] if output_names else "")
        
        output_dropdown = tk.OptionMenu(output_frame, output_var, *output_names)
        output_dropdown.config(
            bg='white',
            font=('Arial', 9),
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=0,
            width=55
        )
        output_dropdown["menu"].config(bg='white', font=('Arial', 9))
        output_dropdown.pack(fill=tk.X, padx=10, pady=10)
        
        # Botones de test y ayuda
        output_buttons = tk.Frame(output_frame, bg='#f0f0f0')
        output_buttons.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        test_output_btn = tk.Button(
            output_buttons,
            text="🔊 Probar (1s silencio)",
            command=lambda: self.test_audio_device(output_var.get(), "output"),
            bg='#3498db',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        )
        test_output_btn.pack(side=tk.LEFT, padx=5)

        tk.Button(
            output_buttons,
            text="🏷️ Renombrar",
            command=lambda: _rename_device(output_var, "output"),
            bg='#9b59b6',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(
            output_buttons,
            text="⭐ = Dispositivo físico recomendado",
            font=('Arial', 8),
            bg='#f0f0f0',
            fg='#7f8c8d'
        ).pack(side=tk.LEFT, padx=10)
        
        # BOTÓN DE AUTO-DETECCIÓN
        auto_detect_frame = tk.Frame(main_frame, bg='#fff3cd', relief=tk.SOLID, borderwidth=2)
        auto_detect_frame.pack(fill=tk.X, pady=15)
        
        def run_auto_detect():
            log_audio.info("🔍 Ejecutando auto-detección...")
            auto_input, auto_output = self.audio_device_manager.auto_detect_best_devices()
            
            if auto_input is not None:
                # Encontrar el nombre en la lista
                devices = self.audio_device_manager.get_devices()
                for dev in devices["input"]:
                    if dev["index"] == auto_input:
                        # Buscar en input_names
                        for name in input_names:
                            if dev["name"] in name:
                                input_var.set(name)
                                break
                        break
            
            if auto_output is not None:
                # Encontrar el nombre en la lista
                devices = self.audio_device_manager.get_devices()
                for dev in devices["output"]:
                    if dev["index"] == auto_output:
                        # Buscar en output_names
                        for name in output_names:
                            if dev["name"] in name:
                                output_var.set(name)
                                break
                        break
            
            self.append_message("Sistema", "✅ Auto-detección completada - Revisa las selecciones", 'system')
        
        tk.Button(
            auto_detect_frame,
            text="🤖 Auto-Detectar Dispositivos Físicos",
            command=run_auto_detect,
            bg='#ffc107',
            fg='#2c3e50',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=8
        ).pack(pady=10)
        
        tk.Label(
            auto_detect_frame,
            text="Busca automáticamente micrófono y altavoz USB/Bluetooth/Auxiliar",
            font=('Arial', 8),
            bg='#fff3cd',
            fg='#856404'
        ).pack(pady=(0, 10))
        
        # INFO
        info_frame = tk.Frame(main_frame, bg='#ecf0f1', relief=tk.SOLID, borderwidth=1)
        info_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(
            info_frame,
            text="💡 Leyenda:\n"
                 "⭐ = Dispositivo físico (USB/Bluetooth/Auxiliar) - RECOMENDADO\n"
                 "🔌 = USB  |📶 = Bluetooth  |🎙️ = Interno  |⚙️ = Virtual\n"
                 "\n🏷️ Renombrar: asigna un nombre amigable al dispositivo seleccionado.\n"
                 "Los cambios se guardan automáticamente al aplicar.\n"
                 "Usa 'Auto-Detectar' para encontrar dispositivos conectados.",
            font=('Arial', 8),
            bg='#ecf0f1',
            fg='#34495e',
            justify=tk.LEFT
        ).pack(padx=10, pady=10)
        
        # BOTONES
        button_frame = tk.Frame(config_win, bg='#f0f0f0')
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_audio_config():
            # Obtener info completa de los dispositivos seleccionados (maneja aliases y BT)
            input_info = self.audio_device_manager.get_device_full_info_from_name(input_var.get(), "input")
            output_info = self.audio_device_manager.get_device_full_info_from_name(output_var.get(), "output")

            input_idx = input_info["index"] if input_info else None
            output_idx = output_info["index"] if output_info else None
            input_pw_id = input_info.get("pipewire_id") if input_info else None
            output_pw_id = output_info.get("pipewire_id") if output_info else None

            # Si el output es un dispositivo Bluetooth via PipeWire, activarlo como sink default
            if output_info and output_info.get("via_pipewire") and output_pw_id:
                log_audio.info(f"🔊 Activando {output_info['name']} como sink PipeWire...")
                if self.audio_device_manager.set_pipewire_default(output_pw_id):
                    self.append_message("Sistema",
                        f"📶 {output_info['name']} activado como salida Bluetooth", 'system')

            # Si el input es Bluetooth via PipeWire, activarlo como source default
            if input_info and input_info.get("via_pipewire") and input_pw_id:
                log_audio.info(f"🎤 Activando {input_info['name']} como source PipeWire...")
                self.audio_device_manager.set_pipewire_default(input_pw_id)

            # Guardar preferencias (incluye pipewire_id para restaurar al reiniciar)
            self.audio_device_manager.set_preferred_devices(
                input_idx, output_idx,
                input_pipewire_id=input_pw_id,
                output_pipewire_id=output_pw_id
            )

            # Actualizar índices locales
            self.input_device_index = input_idx
            self.output_device_index = output_idx

            # Obtener nombres completos actualizados
            saved_input, saved_output = self.audio_device_manager.get_preferred_device_names()

            self.append_message("Sistema", "✅ Dispositivos guardados:", 'system')
            if saved_input:
                self.append_message("Sistema", f"  🎤 {saved_input}", 'system')
            if saved_output:
                self.append_message("Sistema", f"  🔊 {saved_output}", 'system')

            # Si está grabando, advertir que debe reiniciar
            if self.recording:
                self.append_message("Sistema",
                                  "⚠️ Detén y reinicia la grabación para aplicar cambios",
                                  'system')

            config_win.destroy()
        
        tk.Button(
            button_frame,
            text="💾 Guardar y Aplicar",
            command=save_audio_config,
            bg='#27ae60',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
        
        tk.Button(
            button_frame,
            text="❌ Cancelar",
            command=config_win.destroy,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
    
    def test_audio_device(self, device_name, device_type):
        """Prueba un dispositivo de audio"""
        if not self.audio_device_manager:
            return
        
        device_idx = self.audio_device_manager.get_device_index_from_name(device_name, device_type)
        
        if device_idx is None:
            self.append_message("Sistema", f"❌ No se pudo encontrar el dispositivo", 'system')
            return
        
        self.append_message("Sistema", f"🔍 Probando dispositivo...", 'system')
        
        def test():
            success = self.audio_device_manager.test_device(device_idx, device_type, duration=1.0)
            if success:
                self.root.after(0, self.append_message, "Sistema", "✅ Dispositivo funciona correctamente", 'system')
            else:
                self.root.after(0, self.append_message, "Sistema", "❌ Error probando dispositivo", 'system')
        
        threading.Thread(target=test, daemon=True).start()
    
    def toggle_camera(self):
        """Abre o cierra la ventana de cámara"""
        if self.camera_running:
            self.stop_camera_simple()
        else:
            self.start_camera_simple()
    
    def toggle_gpt4v_auto(self):
        """Toggle del sistema automático GPT-4V"""
        self.gpt4v_auto_enabled = not self.gpt4v_auto_enabled
        
        if self.gpt4v_auto_enabled:
            self.gpt4v_auto_button.config(text="🤖 Auto: ON", bg='#27ae60')
            self.append_message("Sistema", "✅ GPT-4V automático activado (Sistema Híbrido)", 'system')
            # Reiniciar tracking
            import time
            self.last_gpt4v_time = time.time()
            self.previous_object_set = set()
        else:
            self.gpt4v_auto_button.config(text="🤖 Auto: OFF", bg='#95a5a6')
            self.append_message("Sistema", "⏸️ GPT-4V automático desactivado", 'system')
    
    def open_gpt4v_config(self):
        """Abre ventana de configuración del sistema híbrido"""
        config_win = tk.Toplevel(self.root)
        config_win.title("⚙️ Config GPT-4V Automático")
        config_win.geometry("450x300")
        config_win.configure(bg='#f0f0f0')
        config_win.transient(self.root)
        
        # Título
        tk.Label(
            config_win,
            text="🤖 Sistema Híbrido Inteligente",
            font=('Arial', 14, 'bold'),
            bg='#f0f0f0'
        ).pack(pady=10)
        
        # Descripción
        tk.Label(
            config_win,
            text="GPT-4V se activa automáticamente cuando:\n• Detecta cambios significativos en la escena\n• Transcurre el tiempo de refresh (opcional)",
            font=('Arial', 9),
            bg='#f0f0f0',
            justify=tk.LEFT
        ).pack(pady=5)
        
        # Frame configuración
        frame = tk.Frame(config_win, bg='#f0f0f0')
        frame.pack(pady=10, padx=20, fill=tk.BOTH)
        
        # Umbral de cambio
        tk.Label(frame, text="Umbral de cambio:", bg='#f0f0f0', font=('Arial', 10)).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        threshold_var = tk.DoubleVar(value=self.gpt4v_change_threshold)
        threshold_scale = tk.Scale(
            frame,
            from_=0.1,
            to=1.0,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=threshold_var,
            bg='#f0f0f0',
            length=200
        )
        threshold_scale.grid(row=0, column=1, padx=10, pady=5)
        tk.Label(frame, text="(30% = sensible, 80% = conservador)", bg='#f0f0f0', font=('Arial', 8), fg='#7f8c8d').grid(row=0, column=2, sticky=tk.W)
        
        # Refresh periódico
        tk.Label(frame, text="Refresh automático (s):", bg='#f0f0f0', font=('Arial', 10)).grid(row=1, column=0, sticky=tk.W, pady=5)
        
        refresh_var = tk.IntVar(value=self.gpt4v_refresh_interval)
        refresh_scale = tk.Scale(
            frame,
            from_=0,
            to=180,
            resolution=15,
            orient=tk.HORIZONTAL,
            variable=refresh_var,
            bg='#f0f0f0',
            length=200
        )
        refresh_scale.grid(row=1, column=1, padx=10, pady=5)
        tk.Label(frame, text="(0 = desactivado)", bg='#f0f0f0', font=('Arial', 8), fg='#7f8c8d').grid(row=1, column=2, sticky=tk.W)
        
        # Costo estimado
        cost_label = tk.Label(
            config_win,
            text="",
            font=('Arial', 9, 'bold'),
            bg='#f0f0f0',
            fg='#e67e22'
        )
        cost_label.pack(pady=10)
        
        def update_cost_estimate(*args):
            refresh = refresh_var.get()
            if refresh > 0:
                calls_per_hour = 3600 / refresh
                cost_per_hour = calls_per_hour * 0.01
                cost_label.config(text=f"💰 Costo estimado: ${cost_per_hour:.2f}/hora (solo refresh)")
            else:
                cost_label.config(text="💰 Costo: Variable según cambios detectados")
        
        refresh_var.trace('w', update_cost_estimate)
        update_cost_estimate()
        
        # Botones
        button_frame = tk.Frame(config_win, bg='#f0f0f0')
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_config():
            self.gpt4v_change_threshold = threshold_var.get()
            self.gpt4v_refresh_interval = refresh_var.get()
            self.append_message("Sistema", f"✅ Config GPT-4V: Umbral={self.gpt4v_change_threshold*100:.0f}%, Refresh={self.gpt4v_refresh_interval}s", 'system')
            config_win.destroy()
        
        tk.Button(
            button_frame,
            text="💾 Guardar",
            command=save_config,
            bg='#27ae60',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
        
        tk.Button(
            button_frame,
            text="❌ Cancelar",
            command=config_win.destroy,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 10, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20
        ).pack(side=tk.RIGHT, padx=5)
    
    def analyze_with_gpt4v(self):
        """Analiza la imagen actual con GPT-4 Vision"""
        if not GPT4V_AVAILABLE or not self.gpt4v_service:
            self.append_message("Sistema", "❌ GPT-4 Vision no disponible", 'system')
            return
        
        if not self.camera_running or not self.camera_service:
            self.append_message("Sistema", "❌ Cámara no activa", 'system')
            return
        
        # Deshabilitar botón temporalmente
        self.gpt4v_button.config(state=tk.DISABLED, text="⏳ Analizando...")
        
        def analyze():
            try:
                # Obtener frame actual
                ret, frame = self.camera_service.read_frame()
                if not ret or frame is None:
                    self.root.after(0, self.append_message, "Sistema", "❌ Error capturando frame", 'system')
                    return
                
                # Analizar con GPT-4V
                result = self.gpt4v_service.quick_description(frame)
                
                # Mostrar resultado
                if isinstance(result, dict) and result.get('success'):
                    description = result['description']
                    cost = result.get('cost', 0)
                    
                    self.root.after(0, self.append_message, "GPT-4 Vision", description, 'assistant')
                    self.root.after(0, self.append_message, "Sistema", f"💰 Costo: ${cost:.4f}", 'system')
                else:
                    self.root.after(0, self.append_message, "GPT-4 Vision", result, 'assistant')
                
            except Exception as e:
                self.root.after(0, self.append_message, "Sistema", f"❌ Error: {e}", 'system')
            
            finally:
                # Reactivar botón
                self.root.after(0, lambda: self.gpt4v_button.config(
                    state=tk.NORMAL, 
                    text="🔍 Análisis Detallado (GPT-4V)"
                ))
        
        # Ejecutar en thread separado
        threading.Thread(target=analyze, daemon=True).start()
    
    def _vision_update_loop(self):
        """Loop que actualiza el contexto visual en background"""
        import time
        
        while self.vision_enabled and self.camera_running:
            try:
                # Obtener contexto visual
                context = self.camera_service.get_vision_context_for_realtime()
                
                if context:
                    self.last_vision_context = context
                    self.detected_objects = context.get('raw_detections', [])
                    
                    # Actualizar UI con detecciones
                    if hasattr(self, 'detections_label') and self.detections_label:
                        summary = context.get('vision_summary', 'No hay detecciones')
                        self.detections_label.config(text=f"👁️ {summary}")
                    
                    # Sistema Híbrido Inteligente - Detectar cambios significativos
                    if self.gpt4v_auto_enabled and GPT4V_AVAILABLE and not self.gpt4v_analyzing:
                        should_analyze = self._should_trigger_gpt4v()
                        
                        if should_analyze:
                            log_vision.info("🤖 Cambio detectado, activando GPT-4V...")
                            self._auto_analyze_with_gpt4v()
                
                # Actualizar cada 2 segundos
                time.sleep(2)
                
            except Exception as e:
                log_vision.error(f"Error en vision loop: {e}")
                time.sleep(1)
        
    def _should_trigger_gpt4v(self):
        """Determina si debe activarse GPT-4V automáticamente (Sistema Híbrido)"""
        import time
        
        # Crear set de objetos actuales (clase + posición aproximada)
        current_objects = set()
        for det in self.detected_objects:
            # Crear identificador: clase + zona aproximada (simplificado)
            obj_id = f"{det['class']}_{det.get('x', 0)//100}_{det.get('y', 0)//100}"
            current_objects.add(obj_id)
        
        current_time = time.time()
        
        # Razón 1: Nuevos objetos detectados (cambio en la escena)
        if self.previous_object_set:
            # Calcular diferencia
            new_objects = current_objects - self.previous_object_set
            removed_objects = self.previous_object_set - current_objects
            total_change = len(new_objects) + len(removed_objects)
            
            # Calcular porcentaje de cambio
            max_objects = max(len(current_objects), len(self.previous_object_set), 1)
            change_percentage = total_change / max_objects
            
            if change_percentage >= self.gpt4v_change_threshold:
                log_vision.debug(f"🔄 Cambio significativo: {change_percentage*100:.1f}% (umbral: {self.gpt4v_change_threshold*100:.0f}%)")
                self.previous_object_set = current_objects
                self.last_gpt4v_time = current_time
                return True
        
        # Razón 2: Refresh periódico (si está habilitado)
        if self.gpt4v_refresh_interval > 0:
            time_since_last = current_time - self.last_gpt4v_time
            if time_since_last >= self.gpt4v_refresh_interval:
                log_vision.debug(f"⏰ Refresh automático ({self.gpt4v_refresh_interval}s transcurridos)")
                self.previous_object_set = current_objects
                self.last_gpt4v_time = current_time
                return True
        
        # Actualizar set de objetos para próxima comparación
        self.previous_object_set = current_objects
        
        return False
    
    def _auto_analyze_with_gpt4v(self):
        """Análisis automático con GPT-4V (Sistema Principal)"""
        
        def analyze():
            self.gpt4v_analyzing = True
            try:
                # Obtener frame actual
                ret, frame = self.camera_service.read_frame()
                if not ret or frame is None:
                    log_vision.error("Error capturando frame para GPT-4V")
                    return
                
                # Analizar con GPT-4V
                result = self.gpt4v_service.quick_description(frame)
                
                # Guardar resultado en contexto
                if isinstance(result, dict) and result.get('success'):
                    description = result['description']
                    cost = result.get('cost', 0)
                    
                    # Guardar última descripción para usar en mensajes
                    self.last_gpt4v_description = description
                    
                    # Agregar a contexto visual
                    if self.last_vision_context:
                        self.last_vision_context['gpt4v_description'] = description
                        self.last_vision_context['gpt4v_cost'] = cost
                    
                    # Solo mostrar en status, no llenar el chat
                    if hasattr(self, 'camera_status') and self.camera_status:
                        status_text = f"👁️ GPT-4V: {description[:50]}..." if len(description) > 50 else f"👁️ GPT-4V: {description}"
                        self.root.after(0, lambda: self.camera_status.config(text=status_text, fg='#27ae60'))
                    
                    log_vision.info(f"GPT-4V actualizado (${cost:.4f}): {description[:60]}...")
                else:
                    log_vision.error(f"Error en GPT-4V: {result}")
                
            except Exception as e:
                log_vision.error(f"Error en análisis automático GPT-4V: {e}")
            
            finally:
                self.gpt4v_analyzing = False
        
        # Ejecutar en thread separado
        threading.Thread(target=analyze, daemon=True).start()
    
    def on_closing(self):
        """Cerrar aplicación correctamente"""
        log.info("🛑 Cerrando aplicación...")
        
        self.recording = False
        
        # ═══════════════════════════════════════════════════════════════════════
        # DETENER EyeTrackerThread PRIMERO (para liberar la cámara)
        # ═══════════════════════════════════════════════════════════════════════
        if self.eye_tracker and self.eye_tracker.is_alive():
            log.info("🛑 Deteniendo EyeTrackerThread...")
            self.eye_tracker.stop()
            self.eye_tracker.join(timeout=5.0)
            self.eye_tracker = None
            log.info("✅ EyeTrackerThread detenido")
        
        # Detener cámara si está activa (fallback)
        if self.camera_running:
            try:
                self.camera_running = False
                if self.camera_cap:
                    self.camera_cap.release()
                    self.camera_cap = None
            except:
                pass
        
        # Cerrar ventana de cámara
        if self.camera_window:
            try:
                self.camera_window.destroy()
            except:
                pass
        
        # Cerrar WebSocket
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        # Terminar audio
        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass
        
        # Limpiar controlador de boca
        if self.mouth_controller:
            try:
                self.mouth_controller.cleanup()
                log.info("✅ MouthController cerrado")
            except:
                pass
        
        # Destruir ventana
        self.root.destroy()
        log.info("✅ Aplicación cerrada")

def main():
    root = tk.Tk()
    app = RealtimeGUIChat(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
