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

try:
    import pyaudio
    AUDIO_AVAILABLE = True
    print("[DEBUG] PyAudio importado correctamente - AUDIO_AVAILABLE = True")
except ImportError:
    AUDIO_AVAILABLE = False
    print("[DEBUG] PyAudio NO disponible - AUDIO_AVAILABLE = False")

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
    print("[WARNING] AudioEnhancer no disponible - audio sin procesamiento avanzado")

try:
    from utils.audio_device_manager import AudioDeviceManager
    AUDIO_DEVICE_MANAGER_AVAILABLE = True
except ImportError:
    AUDIO_DEVICE_MANAGER_AVAILABLE = False
    print("[WARNING] AudioDeviceManager no disponible - usando dispositivos por defecto")

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Precios por 1M tokens
PRICE_INPUT = 0.60
PRICE_OUTPUT = 2.40

# Configuración de audio optimizada para máxima fluidez
CHUNK = 512  # 21ms @ 24kHz - Balance perfecto latencia/estabilidad
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
                print(f"[DEBUG] PyAudio inicializado correctamente - {self.audio.get_device_count()} dispositivos encontrados")
        except Exception as e:
            print(f"[ERROR] No se pudo inicializar PyAudio: {e}")
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
            print("[AUDIO] ✅ Procesamiento profesional activado (AGC + Anti-clipping + Noise Gate)")
        
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
                print(f"[AUDIO] Dispositivos preferidos cargados:")
                if input_name:
                    print(f"  🎤 Input: {input_name}")
                if output_name:
                    print(f"  🔊 Output: {output_name}")
        
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
        self.user_interrupted = False
        
        # Contador de costos GPT-4V
        self.gpt4v_analyses_count = 0
        self.gpt4v_total_cost = 0.0
        
        # Configuración personalizable
        self.voice = "alloy"
        self.instructions = "Eres un asistente útil y amigable. Responde en español de forma concisa y clara. Cuando recibas mensajes con [VISIÓN], úsalos para entender lo que estoy viendo y responder preguntas sobre eso."
        self.temperature = 0.8
        
        self.setup_ui()
        self.start_connection()
        
        # Auto-iniciar cámara y visión
        if CAMERA_AVAILABLE:
            self.root.after(500, self.auto_start_vision_system)
    
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
                            print(f"[AUDIO] Input PipeWire encontrado: [{i}] {info['name']}")
                        if info.get('maxOutputChannels', 0) > 0 and output_dev is None:
                            output_dev = i
                            print(f"[AUDIO] Output PipeWire encontrado: [{i}] {info['name']}")
                except Exception as e:
                    continue
            
            return input_dev, output_dev
        except Exception as e:
            print(f"[ERROR] Error buscando PipeWire: {e}")
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
                
                print(f"✅ Audio rate soportado: {rate} Hz")
                self.hw_rate = rate
                self.resample_ratio_in = self.api_rate / self.hw_rate
                self.resample_ratio_out = self.hw_rate / self.api_rate
                return rate
            except Exception as e:
                continue
        
        print("❌ No se encontró rate compatible")
        return None
    
    def resample_audio(self, audio_data, ratio):
        """Resample audio usando scipy"""
        try:
            from scipy import signal as scipy_signal
            
            # Convertir bytes a numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            
            # Calcular nueva longitud
            new_length = int(len(audio_np) * ratio)
            
            # Resample
            resampled = scipy_signal.resample(audio_np, new_length)
            
            # Convertir de vuelta a int16
            resampled = resampled.astype(np.int16)
            
            return resampled.tobytes()
        except ImportError:
            print("⚠️ scipy no disponible, sin resampling")
            return audio_data
        except Exception as e:
            print(f"❌ Error en resampling: {e}")
            return audio_data
        
    def auto_start_vision_system(self):
        """Inicia automáticamente la cámara y el sistema de visión"""
        try:
            # Iniciar cámara
            self.start_camera_simple()
            
            self.append_message("Sistema", "🤖 Sistema de visión GPT-4 iniciado automáticamente", 'system')
        except Exception as e:
            print(f"Error iniciando sistema automático: {e}")
    
    def start_camera_simple(self):
        """Inicia la cámara sin YOLO, solo captura"""
        if not CAMERA_AVAILABLE:
            self.append_message("Sistema", "❌ OpenCV no disponible", 'system')
            return
        
        # Intentar abrir cámara
        for cam_idx in [0, 1, 2]:
            self.camera_cap = cv2.VideoCapture(cam_idx)
            if self.camera_cap.isOpened():
                print(f"[Cámara] Abierta en índice {cam_idx}")
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
                        
                        print(f"[GPT-4V] 🔄 Background refresh: {vision_description[:50]}...")
            except Exception as e:
                print(f"Error GPT-4V background: {e}")
            finally:
                self.gpt4v_analyzing = False
        
        threading.Thread(target=analyze, daemon=True).start()
    
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
                print(f"[DEBUG] Evento: {event_type}")
            
            if event_type == 'input_audio_buffer.speech_started':
                # INTERRUPCIÓN INTELIGENTE: Usuario empezó a hablar
                if self.assistant_speaking:
                    print("[INTERRUPT] 🚫 Usuario interrumpe al asistente")
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
                    print(f"[Transcripción] {transcript}")
            
            elif event_type == 'conversation.item.input_audio_transcription.failed':
                error = data.get('error', {})
                print(f"❌ Error transcripción: {error}")
            
            elif event_type == 'session.created':
                self.connected = True
                self.root.after(0, self.update_status, "Conectado", "#27ae60")
                self.root.after(0, lambda: self.send_button.config(state=tk.NORMAL))
                if self.audio_available:
                    self.root.after(0, lambda: self.mode_button.config(state=tk.NORMAL))
                self.root.after(0, self.append_message, "Sistema", "✓ Conectado. Escribe o usa voz!", 'system')
                
            elif event_type == 'session.updated':
                print("[DEBUG] Sesión actualizada")
                
            elif event_type == 'response.text.delta':
                text = data.get('delta', '')
                if not hasattr(self, 'current_response'):
                    self.current_response = ""
                self.current_response += text
                print(f"[DEBUG] Text delta: {text}")
                
            elif event_type == 'response.text.done':
                if hasattr(self, 'current_response') and self.current_response:
                    print(f"[DEBUG] Text done: {self.current_response}")
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
                    print(f"[DEBUG] Response done - Tokens: {usage}")
                
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
                                        print(f"[TEXTO] Respuesta: {text}")
                                        self.root.after(0, self.append_message, "Asistente", text, 'assistant')
                
            elif event_type == 'response.audio_transcript.delta':
                # Transcripción parcial en tiempo real
                delta = data.get('delta', '')
                if delta:
                    if not hasattr(self, 'current_audio_transcript'):
                        self.current_audio_transcript = ""
                        # INTERRUPCIÓN: Asistente empezó a responder
                        self.assistant_speaking = True
                        self.root.after(0, self.update_activity_status, 'speaking', '#9b59b6')
                        print("[ASSISTANT] 🗣️ Asistente empezó a hablar")
                    self.current_audio_transcript += delta
                    # Simular volumen del asistente
                    self.set_volume_level(70)
                    print(delta, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                # Transcripción completa del asistente
                transcript = data.get('transcript', '')
                if hasattr(self, 'current_audio_transcript'):
                    transcript = self.current_audio_transcript
                    delattr(self, 'current_audio_transcript')
                
                # INTERRUPCIÓN: Asistente terminó de hablar
                # Mantener el micrófono mutado 1 segundo extra para evitar captar eco
                def unmute_mic():
                    time.sleep(1.0)  # Esperar a que el eco del parlante desaparezca
                    self.assistant_speaking = False
                    print("[MIC] ✅ Micrófono reactivado (eco eliminado)")
                
                threading.Thread(target=unmute_mic, daemon=True).start()
                self.root.after(0, self.update_activity_status, 'idle', '#95a5a6')
                self.set_volume_level(0)
                print("[ASSISTANT] ✅ Asistente terminó de hablar")
                
                if transcript and not self.user_interrupted:
                    print()  # Nueva línea
                    self.root.after(0, self.append_message, "Asistente (voz)", transcript, 'assistant')
                    print(f"[Asistente] {transcript}")
                    
            elif event_type == 'response.audio.delta':
                audio_b64 = data.get('delta', '')
                if audio_b64 and not self.user_interrupted:
                    audio_bytes = base64.b64decode(audio_b64)
                    # Usar buffer del enhancer si está disponible para double buffering
                    if self.audio_enhancer:
                        self.audio_enhancer.add_to_playback_buffer(audio_bytes)
                    else:
                        self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                # INTERRUPCIÓN: Respuesta de audio completa
                self.assistant_speaking = False
                
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
                print(f"[ERROR] {error}")
                
        except Exception as e:
            print(f"Error procesando mensaje: {e}")
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
        self.update_session_config()
        
        # Iniciar thread de playback para reproducir audio incluso en modo texto
        if self.audio_available and not hasattr(self, 'playback_thread_started'):
            self.playback_thread = threading.Thread(target=self.play_audio, daemon=True)
            self.playback_thread.start()
            self.playback_thread_started = True
            print("[DEBUG] Thread de playback iniciado para modo texto")
        
    def update_session_config(self):
        # SIEMPRE usar audio para que las respuestas se reproduzcan en el parlante
        # Aunque el input sea solo texto, el output será audio
        modalities = ["text", "audio"]
        
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
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,       # Más sensible para detectar voz baja
                    "prefix_padding_ms": 500, # Más contexto para no cortar inicio
                    "silence_duration_ms": 500  # Balance entre corte rápido y natural
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
        print(f"[DEBUG] toggle_voice_mode llamado - audio_available: {self.audio_available}, voice_mode actual: {self.voice_mode}")
        if not self.audio_available:
            print("[DEBUG] Audio no disponible, retornando")
            return
            
        self.voice_mode = not self.voice_mode
        print(f"[DEBUG] voice_mode cambiado a: {self.voice_mode}")
        
        if self.voice_mode:
            self.mode_label.config(text="Modo: Voz 🎤", fg='#e74c3c')
            self.mode_button.config(text="💬 Modo Texto", bg='#3498db')
            self.message_entry.pack_forget()
            self.send_button.pack_forget()
            self.record_button.pack(fill=tk.Y)
            self.record_button.config(state=tk.NORMAL if self.connected else tk.DISABLED)
            self.append_message("Sistema", "✓ Modo voz activado", 'system')
            
            # AUTO-START: Iniciar grabación automáticamente después de 500ms
            if self.connected and not self.recording:
                print("[DEBUG] Auto-iniciando grabación en 500ms...")
                self.root.after(500, self.start_recording)
        else:
            self.mode_label.config(text="Modo: Texto 💬", fg='#7f8c8d')
            self.mode_button.config(text="🎤 Modo Voz", bg='#9b59b6')
            self.record_button.pack_forget()
            self.message_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
            self.send_button.pack(fill=tk.Y)
            self.append_message("Sistema", "✓ Modo texto activado", 'system')
            
        self.update_session_config()
        
    def toggle_recording(self):
        print(f"[DEBUG] toggle_recording llamado - recording: {self.recording}")
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()
            
    def start_recording(self):
        print("[DEBUG] start_recording llamado")
        # Detectar rate soportado
        if self.find_supported_rate() is None:
            print("[ERROR] No se pudo encontrar rate soportado")
            self.append_message("Sistema", "❌ No se pudo inicializar audio", 'system')
            return
        
        print(f"[DEBUG] Rate detectado: {self.hw_rate} Hz")
        
        # Resetear audio enhancer para nueva sesión
        if self.audio_enhancer:
            self.audio_enhancer.reset()
            print("[AUDIO] AudioEnhancer reseteado para nueva sesión")
        
        self.recording = True
        self.record_button.config(text="⏹️ Detener", bg='#27ae60')
        
        # Mensaje informativo - modo manos libres con VAD
        features = []
        if self.audio_enhancer:
            features = ["VAD Automático", "AGC", "Noise Gate"]
            features_str = " + ".join(features)
            self.append_message("Sistema", f"🎤 Modo manos libres activado | {features_str}", 'system')
            self.append_message("Sistema", "💡 Habla libremente - el sistema detecta automáticamente tu voz", 'system')
        else:
            self.append_message("Sistema", f"🎤 Modo manos libres activado", 'system')
        
        print("[DEBUG] Iniciando threads de audio...")
        self.audio_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.audio_thread.start()
        
        # No iniciar playback thread aquí porque ya se inicia en on_open
        # para permitir reproducción en modo texto también
        print("[DEBUG] Thread de grabación iniciado")
        
    def stop_recording(self):
        self.recording = False
        self.record_button.config(text="🎤 Iniciar", bg='#e74c3c')
        self.append_message("Sistema", "⏸️ Modo manos libres detenido", 'system')
        
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
                print(f"[AUDIO] Usando dispositivo de entrada: {self.input_device_index}")
            
            stream = self.audio.open(**stream_kwargs)
            
            print(f"🎤 Micrófono activado ({self.hw_rate} Hz)")
            if self.audio_enhancer:
                print("[AUDIO] Procesamiento: AGC + Noise Gate + Anti-clipping")
            
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
                    
                    # CANCELACIÓN DE ECO: No enviar audio si el asistente está hablando
                    # Esto evita feedback y que el micrófono capte el sonido del parlante
                    if self.assistant_speaking:
                        continue  # Descartar este chunk, el asistente está hablando
                    
                    # Resample a API rate (24000 Hz)
                    if self.hw_rate != self.api_rate:
                        data = self.resample_audio(data, self.resample_ratio_in)
                    
                    # Procesar con AudioEnhancer (AGC, noise gate, etc.)
                    if self.audio_enhancer:
                        data = self.audio_enhancer.process_input(data)
                    
                    if self.connected:
                        self.send_audio_chunk(data)
                        # Debug: mostrar que se está enviando audio
                        if volume_percent > 5:
                            print(f"[MIC] Enviando audio: {volume_percent:.1f}% volumen")
                except Exception as e:
                    if self.recording:
                        print(f"Error audio: {e}")
                    break
                    
        except Exception as e:
            self.root.after(0, self.append_message, "Error", f"Micrófono: {e}", 'system')
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
                print("🎤 Micrófono detenido")
                
    def play_audio(self):
        """Reproduce audio del asistente con procesamiento profesional"""
        try:
            # Usar 24kHz directamente (rate de la API) - compatible con todos los dispositivos
            playback_rate = self.api_rate
            
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
                print(f"[AUDIO] Usando dispositivo de salida: {self.output_device_index}")
            
            stream = self.audio.open(**stream_kwargs)
            
            print(f"🔊 Altavoz activado ({playback_rate} Hz)")
            if self.audio_enhancer:
                print("[AUDIO] Playback: Double buffering + Anti-clipping")
            
            # Reproducir mientras esté conectado (no solo mientras graba)
            # Esto permite reproducir respuestas en modo texto también
            while self.connected:
                try:
                    # Usar buffer del enhancer si está disponible
                    if self.audio_enhancer:
                        audio_chunk = self.audio_enhancer.get_from_playback_buffer(timeout=0.1)
                        if audio_chunk is None:
                            # None indica fin de mensaje, pero seguir esperando nuevos mensajes
                            print("[DEBUG] Fin de mensaje de audio, esperando siguiente...")
                            continue
                        if audio_chunk == b'':
                            continue
                    else:
                        audio_chunk = self.output_queue.get(timeout=0.1)
                        if audio_chunk is None:
                            # None indica fin de mensaje, pero seguir esperando nuevos mensajes
                            print("[DEBUG] Fin de mensaje de audio, esperando siguiente...")
                            continue
                    
                    # Chequear interrupción antes de reproducir
                    if self.user_interrupted:
                        print("[DEBUG] Reproducción interrumpida por usuario")
                        continue
                    
                    # El audio ya viene en 24kHz de la API, reproducir directamente sin resample
                    stream.write(audio_chunk)
                except queue.Empty:
                    continue
                except Exception as e:
                    if self.connected:
                        print(f"Error play: {e}")
                    break
                    
            stream.stop_stream()
            stream.close()
            print("🔊 Altavoz detenido")
            
        except Exception as e:
            print(f"❌ Error iniciando altavoz: {e}")
            print("⚠️  Modo solo entrada (micrófono)")
            # Vaciar cola aunque no haya output
            while self.connected:
                try:
                    if self.audio_enhancer:
                        self.audio_enhancer.get_from_playback_buffer(timeout=0.1)
                    else:
                        self.output_queue.get(timeout=0.1)
                except:
                    pass
                    
        except Exception as e:
            self.root.after(0, self.append_message, "Error", f"Altavoz: {e}", 'system')
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
                
    def send_audio_chunk(self, audio_bytes):
        if not self.connected:
            print("[DEBUG] send_audio_chunk: No conectado")
            return
        if not self.voice_mode:
            print("[DEBUG] send_audio_chunk: voice_mode es False")
            return
        
        # Log cada 500 chunks para verificar que se está enviando
        if not hasattr(self, '_audio_chunk_count'):
            self._audio_chunk_count = 0
            print("[DEBUG] Iniciando contador de chunks de audio")
        self._audio_chunk_count += 1
        if self._audio_chunk_count % 500 == 0:
            print(f"[AUDIO] ✓ {self._audio_chunk_count} chunks enviados")
            
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
            print("[INTERRUPT] 📨 Cancelación enviada a API")
            
            # Limpiar buffer de entrada de audio (nuevo audio del usuario)
            clear_event = {
                "type": "input_audio_buffer.clear"
            }
            self.ws.send(json.dumps(clear_event))
            print("[INTERRUPT] 🧹 Buffer de entrada limpiado")
            
            # Limpiar buffers de audio de salida
            self.clear_audio_buffers()
            
        except Exception as e:
            print(f"[ERROR] Error cancelando respuesta: {e}")
    
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
            
            print("[INTERRUPT] 🗑️ Buffers de audio limpiados")
            
        except Exception as e:
            print(f"[ERROR] Error limpiando buffers: {e}")
        
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
                print(f"[GPT-4V] 💾 Cache usado ({cache_age:.1f}s): {vision_description[:50]}...")
            else:
                print(f"[GPT-4V] 🔄 Generando análisis fresco...")
                
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
                        
                        print(f"[GPT-4V] ✅ ${cost:.4f} | Total: ${self.gpt4v_total_cost:.3f} ({self.gpt4v_analyses_count} análisis)")
                    else:
                        print(f"[GPT-4V] ❌ Error en análisis")
                else:
                    print(f"[GPT-4V] ❌ Error capturando frame")
        
        if display_message == message:
            print(f"[DEBUG] Enviando sin visión")
        
        self.append_message("Tú", display_message, 'user')
        self.message_entry.delete('1.0', tk.END)
        
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
        
        print(f"[DEBUG] Enviando mensaje de texto con audio habilitado: {full_message[:100]}...")
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
            ("Alloy (neutral)", "alloy"),
            ("Echo (masculina)", "echo"),
            ("Fable (británica)", "fable"),
            ("Onyx (grave)", "onyx"),
            ("Nova (femenina)", "nova"),
            ("Shimmer (suave)", "shimmer")
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
                            print("🤖 [AUTO] Cambio detectado, activando GPT-4V...")
                            self._auto_analyze_with_gpt4v()
                
                # Actualizar cada 2 segundos
                time.sleep(2)
                
            except Exception as e:
                print(f"Error en vision loop: {e}")
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
                print(f"🔄 Cambio significativo: {change_percentage*100:.1f}% (umbral: {self.gpt4v_change_threshold*100:.0f}%)")
                self.previous_object_set = current_objects
                self.last_gpt4v_time = current_time
                return True
        
        # Razón 2: Refresh periódico (si está habilitado)
        if self.gpt4v_refresh_interval > 0:
            time_since_last = current_time - self.last_gpt4v_time
            if time_since_last >= self.gpt4v_refresh_interval:
                print(f"⏰ Refresh automático ({self.gpt4v_refresh_interval}s transcurridos)")
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
                    print("❌ Error capturando frame para GPT-4V")
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
                    
                    print(f"✅ GPT-4V actualizado (${cost:.4f}): {description[:60]}...")
                else:
                    print(f"❌ Error en GPT-4V: {result}")
                
            except Exception as e:
                print(f"❌ Error en análisis automático GPT-4V: {e}")
            
            finally:
                self.gpt4v_analyzing = False
        
        # Ejecutar en thread separado
        threading.Thread(target=analyze, daemon=True).start()
    
    def on_closing(self):
        """Cerrar aplicación correctamente"""
        print("🛑 Cerrando aplicación...")
        
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
        print("✅ Aplicación cerrada")

def main():
    root = tk.Tk()
    app = RealtimeGUIChat(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
