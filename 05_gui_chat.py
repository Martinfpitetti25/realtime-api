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
log_wake = get_logger('wake_word')
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

try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
    log_wake.debug("Porcupine importado correctamente")
except ImportError:
    PORCUPINE_AVAILABLE = False
    log_wake.warning("Porcupine no disponible - wake word desactivado")

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
# Modelo mejorado: gpt-4o-realtime-preview (mejor inteligencia, respuestas más naturales)
# Alternativa económica: gpt-4o-mini-realtime-preview
MODEL = 'gpt-4o-realtime-preview'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Precios por 1M tokens (gpt-4o-realtime-preview)
PRICE_INPUT = 5.00   # Input audio/text
PRICE_OUTPUT = 20.00  # Output audio/text

# Configuración de audio optimizada para máxima fluidez
CHUNK = 512  # 21ms @ 24kHz - Balance perfecto latencia/estabilidad
FORMAT = pyaudio.paInt16 if AUDIO_AVAILABLE else None
CHANNELS = 1
RATE_API = 24000  # Requerido por OpenAI Realtime API
RATE_HW = 48000   # Hardware rate (se auto-detecta)

# Configuración de Wake Word (Porcupine)
PORCUPINE_ACCESS_KEY = os.getenv('PORCUPINE_ACCESS_KEY', '')  # Obtener de .env
DEFAULT_WAKE_WORD = 'jarvis'  # Wake word por defecto
WAKE_WORD_CONFIRMATION = "Estoy aquí"  # Frase de confirmación

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
        
        # Cargar dispositivos preferidos
        if self.audio_device_manager:
            prefs = self.audio_device_manager.get_preferred_devices()
            self.input_device_index = prefs.get("input")
            self.output_device_index = prefs.get("output")
            input_name, output_name = self.audio_device_manager.get_preferred_device_names()
            if input_name or output_name:
                log_audio.info("Dispositivos preferidos cargados:")
                if input_name:
                    log_audio.info(f"  🎤 Input: {input_name}")
                if output_name:
                    log_audio.info(f"  🔊 Output: {output_name}")
        
        # Cámara (solo captura OpenCV, sin YOLO)
        self.camera_cap = None
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
        self.gpt4v_refresh_interval = 8  # Background refresh cada 8s
        self.gpt4v_cache_max_age = 6  # Usar cache si tiene menos de 6s
        
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
        
        # Wake Word Detection (Porcupine)
        self.wake_word_enabled = False
        self.porcupine = None
        self.wake_word_thread = None
        self.wake_word_listening = False
        self.waiting_for_wake_word = False
        self.wake_word = DEFAULT_WAKE_WORD
        self.wake_word_confirmation = WAKE_WORD_CONFIRMATION
        self._transitioning_from_wake_word = False
        self._wake_word_return_id = None
        
        # Timer para actualización periódica de visión en modo voz
        self._vision_update_timer_id = None
        self.vision_update_interval_ms = 15000  # Actualizar visión cada 15 segundos
        
        # Configuración personalizable
        self.voice = "echo"
        self.instructions = self._build_conversational_instructions()
        self.temperature = 0.85  # Balance entre creatividad y consistencia
        
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
        
        instructions = f"""Eres un asistente conversacional amigable y natural. Tu objetivo es hacer que cada interacción se sienta como hablar con un amigo cercano que te escucha atentamente.

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
- Por defecto, respuestas cortas-medias (2-4 oraciones)
- Expande solo si es necesario o te lo piden
- Evita parrafadas largas al hablar
- Si algo es extenso, divide: "Primero... [pausa implícita] Y luego..."

Recuerda: No eres un asistente técnico, eres un compañero de conversación amigable y atento. Cada interacción debe sentirse natural, fluida y humana."""
        
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
                self.hw_rate = rate
                self.resample_ratio_in = self.api_rate / self.hw_rate
                self.resample_ratio_out = self.hw_rate / self.api_rate
                return rate
            except Exception as e:
                continue
        
        log_audio.error("No se encontró rate compatible")
        return None
    
    def resample_audio(self, audio_data, ratio):
        """Resample audio usando scipy con manejo robusto de tamaños"""
        try:
            from scipy import signal as scipy_signal
            
            # Convertir bytes a numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            
            # Calcular nueva longitud y redondear para evitar errores de tamaño
            new_length = int(round(len(audio_np) * ratio))
            
            # Asegurar que la longitud sea par (para audio estéreo/chunks)
            if new_length % 2 != 0:
                new_length += 1
            
            # Resample
            resampled = scipy_signal.resample(audio_np, new_length)
            
            # Convertir de vuelta a int16 con clipping para evitar overflow
            resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
            
            return resampled.tobytes()
        except ImportError:
            log_audio.warning("scipy no disponible, sin resampling")
            return audio_data
        except Exception as e:
            log_audio.error(f"Error en resampling: {e}, usando audio original")
            return audio_data
        
    def auto_start_vision_system(self):
        """Inicia automáticamente la cámara y el sistema de visión"""
        try:
            # Iniciar cámara
            self.start_camera_simple()
            
            self.append_message("Sistema", "🤖 Sistema de visión GPT-4 iniciado automáticamente", 'system')
        except Exception as e:
            log_vision.error(f"Error iniciando sistema automático: {e}")
    
    def start_camera_simple(self):
        """Inicia la cámara sin YOLO, solo captura"""
        if not CAMERA_AVAILABLE:
            self.append_message("Sistema", "❌ OpenCV no disponible", 'system')
            return
        
        # Intentar abrir cámara
        for cam_idx in [0, 1, 2]:
            self.camera_cap = cv2.VideoCapture(cam_idx)
            if self.camera_cap.isOpened():
                log_vision.info(f"Cámara abierta en índice {cam_idx}")
                break
        
        if not self.camera_cap or not self.camera_cap.isOpened():
            self.append_message("Sistema", "❌ No se encontró cámara", 'system')
            return
        
        # Crear ventana de video
        self.camera_window = tk.Toplevel(self.root)
        self.camera_window.title("📹 GPT-4 Vision Feed")
        self.camera_window.geometry("400x300")
        self.camera_window.configure(bg='#2c3e50')
        self.camera_window.protocol("WM_DELETE_WINDOW", self.stop_camera_simple)
        
        # Label para el video
        self.camera_label = tk.Label(self.camera_window, bg='#2c3e50')
        self.camera_label.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        
        # Status label
        self.camera_status = tk.Label(
            self.camera_window,
            text="🟢 GPT-4 Vision activo",
            font=('Arial', 9),
            fg='#27ae60',
            bg='#2c3e50'
        )
        self.camera_status.pack(pady=5)
        
        self.camera_running = True
        if hasattr(self, 'camera_button'):
            self.camera_button.config(text="⏹️ Cerrar", bg='#e74c3c')
        
        # Iniciar actualización de frames
        self.update_camera_frame_simple()
        
        # Iniciar thread de actualización GPT-4V
        self.start_gpt4v_refresh_thread()
        
        self.append_message("Sistema", "📹 Cámara GPT-4V iniciada", 'system')
    
    def stop_camera_simple(self):
        """Detiene la cámara simple"""
        self.camera_running = False
        
        # Limpiar referencia de imagen para evitar memory leak
        if self.camera_label and hasattr(self.camera_label, 'imgtk'):
            del self.camera_label.imgtk
            self.camera_label.config(image='')
        
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
        """Lee un frame de la cámara"""
        if not self.camera_cap or not self.camera_cap.isOpened():
            return False, None
        
        ret, frame = self.camera_cap.read()
        return ret, frame
    
    def update_camera_frame_simple(self):
        """Actualiza el frame de la cámara en la ventana"""
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
                # Cancelar auto-retorno a wake word si el usuario habla
                if self._wake_word_return_id:
                    self.root.after_cancel(self._wake_word_return_id)
                    self._wake_word_return_id = None
                
                # INTERRUPCIÓN INTELIGENTE: Usuario empezó a hablar
                if self.assistant_speaking:
                    log_ws.info("🚫 Usuario interrumpe al asistente")
                    self.user_interrupted = True
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
                self.current_response += text
                log_ws.debug(f"Text delta: {text}")
                
            elif event_type == 'response.text.done':
                if hasattr(self, 'current_response') and self.current_response:
                    log_ws.debug(f"Text done: {self.current_response}")
                    self.root.after(0, self.append_message, "Asistente", self.current_response, 'assistant')
                    delattr(self, 'current_response')
                    
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
                    self.current_audio_transcript += delta
                    # Simular volumen del asistente
                    self.set_volume_level(70)
                    # Streaming output (se mantiene print para flush parcial)
                    print(delta, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                # Transcripción completa del asistente
                transcript = data.get('transcript', '')
                if hasattr(self, 'current_audio_transcript'):
                    transcript = self.current_audio_transcript
                    delattr(self, 'current_audio_transcript')
                
                # Agregar respuesta del asistente a memoria conversacional
                if transcript:
                    self._add_to_conversation_memory("assistant", transcript)
                
                # Asistente terminó de hablar
                # AEC maneja el eco residual automáticamente (echo tail)
                self.assistant_speaking = False
                if self.echo_canceller:
                    self.echo_canceller.notify_playback_stopped()
                    log_aec.debug("Micrófono reactivado (AEC maneja eco residual)")
                else:
                    log_audio.debug("Micrófono reactivado")
                self.root.after(0, self.update_activity_status, 'idle', '#95a5a6')
                self.set_volume_level(0)
                log_ws.info("✅ Asistente terminó de hablar")
                
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
                    # Usar buffer del enhancer si está disponible para double buffering
                    if self.audio_enhancer:
                        self.audio_enhancer.add_to_playback_buffer(audio_bytes)
                    else:
                        self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                # Respuesta de audio completa
                self.assistant_speaking = False
                self.current_response_item_id = None
                self.played_audio_bytes = 0
                if self.echo_canceller:
                    self.echo_canceller.notify_playback_stopped()
                
                if not self.user_interrupted:
                    if self.audio_enhancer:
                        self.audio_enhancer.add_to_playback_buffer(None)
                    else:
                        self.output_queue.put(None)
                else:
                    # Si fue interrumpido, limpiar buffers
                    self.clear_audio_buffers()
                
                # WAKE WORD: Solo si wake_word_enabled está activo
                # (Desactivado por defecto - se activa manualmente)
                    
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
                    "threshold": 0.5,           # Sensibilidad de detección de voz (0.0-1.0)
                    "prefix_padding_ms": 300,   # Audio previo al habla (ms)
                    "silence_duration_ms": 700, # Silencio antes de procesar (700ms = natural)
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
            # Detener wake word si está activo
            if self.wake_word_listening:
                self.stop_wake_word_listening()
            
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
    
    # ========== WAKE WORD DETECTION (PORCUPINE) ==========
    
    def init_porcupine(self):
        """Inicializa Porcupine para detección de wake word"""
        if not PORCUPINE_AVAILABLE or not self.audio_available:
            log_wake.warning("Porcupine no disponible")
            return False
        
        if not PORCUPINE_ACCESS_KEY:
            log_wake.warning("Necesitas configurar PORCUPINE_ACCESS_KEY en .env")
            log_wake.info("Obtén tu access key gratis en: https://console.picovoice.ai/")
            self.append_message("Sistema", "⚠️ Wake word requiere PORCUPINE_ACCESS_KEY en .env", 'system')
            self.append_message("Sistema", "Obtén tu key gratis en: https://console.picovoice.ai/", 'system')
            return False
        
        try:
            log_wake.debug(f"Intentando inicializar con wake word: '{self.wake_word}'")
            self.porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=[self.wake_word]
            )
            log_wake.info(f"✅ Porcupine inicializado - Escuchando: '{self.wake_word}'")
            return True
        except Exception as e:
            error_msg = str(e)
            log_wake.error(f"Error inicializando Porcupine: {error_msg}")
            
            # Mensajes específicos según el error
            if "invalid" in error_msg.lower() or "authentication" in error_msg.lower():
                self.append_message("Sistema", "❌ Access Key inválida o expirada", 'system')
                self.append_message("Sistema", "Verifica tu PORCUPINE_ACCESS_KEY en .env", 'system')
            elif "keyword" in error_msg.lower():
                self.append_message("Sistema", f"❌ Wake word '{self.wake_word}' no disponible", 'system')
                self.append_message("Sistema", "Prueba: 'computer' o 'alexa'", 'system')
            else:
                self.append_message("Sistema", f"❌ Error wake word: {error_msg[:80]}", 'system')
            
            self.append_message("Sistema", "ℹ️ Continuando en modo voz sin wake word", 'system')
            return False
    
    def cleanup_porcupine(self):
        """Limpia recursos de Porcupine"""
        if self.porcupine:
            try:
                self.porcupine.delete()
                self.porcupine = None
                log_wake.debug("Porcupine limpiado")
            except Exception as e:
                log_wake.error(f"Error limpiando Porcupine: {e}")
    
    def start_wake_word_listening(self):
        """Inicia el thread de escucha de wake word"""
        if not self.init_porcupine():
            # Si falla, usar modo normal sin wake word
            self.wake_word_enabled = False
            self.start_recording()
            return
        
        self.wake_word_enabled = True
        self.waiting_for_wake_word = True
        self.wake_word_listening = True
        
        # Actualizar UI
        self.record_button.config(text="👂 Esperando Wake Word", bg='#f39c12')
        self.append_message("Sistema", f"👂 Esperando wake word: '{self.wake_word}'", 'system')
        self.append_message("Sistema", f"💡 Di '{self.wake_word}' para activar el asistente", 'system')
        
        # Iniciar thread
        self.wake_word_thread = threading.Thread(target=self.listen_for_wake_word, daemon=True)
        self.wake_word_thread.start()
    
    def stop_wake_word_listening(self):
        """Detiene la escucha de wake word"""
        self.wake_word_listening = False
        self.waiting_for_wake_word = False
        self.cleanup_porcupine()
        
        if self.wake_word_thread and self.wake_word_thread.is_alive():
            self.wake_word_thread.join(timeout=1.0)
    
    def listen_for_wake_word(self):
        """Thread que escucha continuamente la wake word"""
        try:
            # Detectar rate soportado
            if self.find_supported_rate() is None:
                log_wake.error("No se pudo encontrar rate soportado")
                return
            
            # Porcupine requiere 16kHz
            porcupine_rate = 16000
            porcupine_chunk = self.porcupine.frame_length
            
            # Preparar stream
            stream_kwargs = {
                'format': FORMAT,
                'channels': CHANNELS,
                'rate': porcupine_rate,
                'input': True,
                'frames_per_buffer': porcupine_chunk
            }
            
            if self.input_device_index is not None:
                stream_kwargs['input_device_index'] = self.input_device_index
            
            stream = self.audio.open(**stream_kwargs)
            log_wake.info(f"👂 Escuchando wake word... ({porcupine_rate} Hz)")
            
            while self.wake_word_listening and self.waiting_for_wake_word:
                try:
                    pcm = stream.read(porcupine_chunk, exception_on_overflow=False)
                    pcm = np.frombuffer(pcm, dtype=np.int16)
                    
                    keyword_index = self.porcupine.process(pcm)
                    
                    if keyword_index >= 0:
                        log_wake.info(f"✅ Wake word '{self.wake_word}' detectada!")
                        self.root.after(0, self.on_wake_word_detected)
                        break  # Salir del loop de escucha
                    
                except Exception as e:
                    if self.wake_word_listening:
                        log_wake.error(f"Error: {e}")
                    break
            
            stream.stop_stream()
            stream.close()
            log_wake.debug("Escucha detenida")
            
        except Exception as e:
            log_wake.error(f"Error en thread: {e}")
            self.root.after(0, self.append_message, "Error", f"Wake word: {e}", 'system')
    
    def on_wake_word_detected(self):
        """Callback cuando se detecta la wake word"""
        log_wake.info("🎯 Wake word detectada! Procesando...")
        
        # Detener escucha de wake word completamente
        self.waiting_for_wake_word = False
        self.wake_word_listening = False
        self._transitioning_from_wake_word = True  # Evitar race condition con response.audio.done
        
        # Limpiar Porcupine para liberar recursos
        self.cleanup_porcupine()
        
        # Actualizar UI
        self.record_button.config(text="🎙️ Activado!", bg='#27ae60')
        self.append_message("Usuario", f"[{self.wake_word}]", 'user')
        
        # Enviar confirmación al asistente
        self.send_confirmation_message()
        
        # Dar tiempo al thread de wake word para cerrar el stream del mic
        self.root.after(500, self.transition_to_recording)
    
    def send_confirmation_message(self):
        """Envía mensaje de confirmación 'Estoy aquí' al asistente"""
        if self.connected and self.ws:
            event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"[WAKE WORD DETECTADA - Responde solo: '{self.wake_word_confirmation}']"
                        }
                    ]
                }
            }
            self.ws.send(json.dumps(event))
            
            # Solicitar respuesta
            response_event = {"type": "response.create"}
            self.ws.send(json.dumps(response_event))
            
            log_wake.info(f"Enviando confirmación: '{self.wake_word_confirmation}'")
    
    def transition_to_recording(self):
        """Transición de wake word a grabación normal"""
        # Esperar a que termine de hablar el asistente
        if self.assistant_speaking:
            log_wake.debug("Esperando que termine la confirmación...")
            self.root.after(500, self.transition_to_recording)
            return
        
        # Esperar a que el thread de wake word libere el micrófono
        if self.wake_word_thread and self.wake_word_thread.is_alive():
            log_wake.debug("Esperando que thread de wake word libere el mic...")
            self.root.after(200, self.transition_to_recording)
            return
        
        # Transición completada
        self._transitioning_from_wake_word = False
        log_wake.info("🎤 Transición completa, iniciando grabación...")
        self.start_recording()
    
    def _auto_return_to_wake_word(self):
        """Vuelve automáticamente a modo wake word si no hay actividad"""
        self._wake_word_return_id = None
        if not self.recording or self.assistant_speaking:
            return
        if not self.wake_word_enabled or not self.voice_mode:
            return
        log_wake.info("🔄 Sin actividad, volviendo a modo wake word...")
        self.stop_recording()
    
    # ========== FIN WAKE WORD DETECTION ==========
        
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
            if self.input_device_index is not None:
                stream_kwargs['input_device_index'] = self.input_device_index
                log_audio.debug(f"Usando dispositivo de entrada: {self.input_device_index}")
            
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
                    # 1. Echo Canceller: eliminar eco del altavoz capturado por el mic
                    if self.echo_canceller and self.assistant_speaking:
                        data = self.echo_canceller.process(data)
                    
                    # 2. AudioEnhancer: filtro pasa-banda, noise gate, AGC, anti-clipping
                    if self.audio_enhancer:
                        data = self.audio_enhancer.process_input(data)
                    
                    if self.connected:
                        self.send_audio_chunk(data)
                        
                        # Debug cada 50 chunks (aprox. 1 segundo)
                        audio_chunk_counter += 1
                        if audio_chunk_counter % 50 == 0 and volume_percent > 5:
                            processed_audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                            processed_rms = np.sqrt(np.mean(processed_audio ** 2))
                            log_audio.debug(f"📊 Volumen: {volume_percent:.1f}% | RMS: {processed_rms:.0f}")
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
            if self.output_device_index is not None:
                stream_kwargs['output_device_index'] = self.output_device_index
                log_audio.debug(f"Usando dispositivo de salida: {self.output_device_index}")
            
            try:
                stream = self.audio.open(**stream_kwargs)
            except Exception as e_24k:
                # 24kHz no soportado, fallback a hardware rate (48kHz típico)
                log_audio.warning(f"24kHz no soportado ({e_24k}), usando {self.hw_rate} Hz con resampling")
                playback_rate = self.hw_rate
                needs_resample = True
                stream_kwargs['rate'] = playback_rate
                stream = self.audio.open(**stream_kwargs)
            
            log_audio.info(f"🔊 Altavoz activado ({playback_rate} Hz)")
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
                            # IMPORTANTE: Dar tiempo para que el buffer de PyAudio se vacíe completamente
                            import time
                            time.sleep(0.2)  # 200ms para permitir que el buffer interno se reproduzca
                            continue
                    
                    # Chequear interrupción antes de reproducir
                    if self.user_interrupted:
                        log_audio.debug("Reproducción interrumpida")
                        continue
                    
                    # AEC: Alimentar referencia ANTES de reproducir
                    # El echo canceller necesita saber qué sale por el altavoz
                    if self.echo_canceller:
                        self.echo_canceller.feed_reference(audio_chunk)
                    
                    # Resamplear si el hardware no soporta 24kHz
                    if needs_resample:
                        audio_chunk = self.resample_audio(audio_chunk, self.resample_ratio_out)
                    
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
                        log_audio.error(f"Error reproduciendo chunk ({consecutive_errors}/{max_consecutive_errors}): {e}")
                    
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
        """Abre ventana de configuración de dispositivos de audio"""
        if not self.audio_device_manager:
            self.append_message("Sistema", "❌ Gestor de audio no disponible", 'system')
            return
        
        config_win = tk.Toplevel(self.root)
        config_win.title("🎧 Configuración de Audio")
        config_win.geometry("550x500")
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
        
        main_frame = tk.Frame(config_win, bg='#f0f0f0')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Obtener dispositivos
        input_names, output_names = self.audio_device_manager.get_device_names()
        
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
                if current_input_name in name:
                    input_selection = i
                    break
        
        input_var = tk.StringVar(value=input_names[input_selection] if input_names else "")
        
        input_dropdown = tk.OptionMenu(input_frame, input_var, *input_names)
        input_dropdown.config(
            bg='white',
            font=('Arial', 10),
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=0,
            width=45
        )
        input_dropdown["menu"].config(bg='white', font=('Arial', 9))
        input_dropdown.pack(fill=tk.X, padx=10, pady=10)
        
        # Botón test micrófono
        test_input_btn = tk.Button(
            input_frame,
            text="🎤 Probar Micrófono (1s)",
            command=lambda: self.test_audio_device(input_var.get(), "input"),
            bg='#3498db',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        )
        test_input_btn.pack(pady=(0, 10))
        
        # DISPOSITIVO DE SALIDA (Altavoces)
        output_frame = tk.LabelFrame(main_frame, text="🔊 Dispositivo de Salida (Altavoces)", 
                                      font=('Arial', 11, 'bold'), bg='#f0f0f0', fg='#2c3e50')
        output_frame.pack(fill=tk.X, pady=10)
        
        # Si hay dispositivo preferido, encontrar su índice en la lista
        output_selection = 0
        if current_output_name:
            for i, name in enumerate(output_names):
                if current_output_name in name:
                    output_selection = i
                    break
        
        output_var = tk.StringVar(value=output_names[output_selection] if output_names else "")
        
        output_dropdown = tk.OptionMenu(output_frame, output_var, *output_names)
        output_dropdown.config(
            bg='white',
            font=('Arial', 10),
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=0,
            width=45
        )
        output_dropdown["menu"].config(bg='white', font=('Arial', 9))
        output_dropdown.pack(fill=tk.X, padx=10, pady=10)
        
        # Botón test altavoces
        test_output_btn = tk.Button(
            output_frame,
            text="🔊 Probar Altavoces (1s silencio)",
            command=lambda: self.test_audio_device(output_var.get(), "output"),
            bg='#3498db',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2'
        )
        test_output_btn.pack(pady=(0, 10))
        
        # INFO
        info_frame = tk.Frame(main_frame, bg='#ecf0f1', relief=tk.SOLID, borderwidth=1)
        info_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(
            info_frame,
            text="💡 Los dispositivos marcados con (Default) son los del sistema.\n"
                 "Los cambios se guardan automáticamente al aplicar.",
            font=('Arial', 8),
            bg='#ecf0f1',
            fg='#7f8c8d',
            justify=tk.LEFT
        ).pack(padx=10, pady=10)
        
        # BOTONES
        button_frame = tk.Frame(config_win, bg='#f0f0f0')
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_audio_config():
            # Obtener índices de dispositivos
            input_idx = self.audio_device_manager.get_device_index_from_name(input_var.get(), "input")
            output_idx = self.audio_device_manager.get_device_index_from_name(output_var.get(), "output")
            
            # Guardar preferencias
            self.audio_device_manager.set_preferred_devices(input_idx, output_idx)
            
            # Actualizar índices locales
            self.input_device_index = input_idx
            self.output_device_index = output_idx
            
            # Mensaje de confirmación
            input_name = input_var.get().replace("🎤 ", "").replace("   ", "").replace(" (Default)", "")[:30]
            output_name = output_var.get().replace("🔊 ", "").replace("   ", "").replace(" (Default)", "")[:30]
            
            self.append_message("Sistema", 
                              f"✅ Dispositivos guardados:\n  🎤 {input_name}...\n  🔊 {output_name}...", 
                              'system')
            
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
        
        # Detener cámara si está activa
        if self.camera_running:
            try:
                self.stop_camera_simple()
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
