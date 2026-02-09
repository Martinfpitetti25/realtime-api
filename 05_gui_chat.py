"""
GUI Chat con OpenAI Realtime API - Con modo de voz y configuración
Interfaz gráfica simple y liviana con monitor de tokens
"""
import os
import json
import base64
import tkinter as tk
from tkinter import scrolledtext
import websocket
import threading
import queue
from dotenv import load_dotenv
from datetime import datetime

try:
    import pyaudio
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Precios por 1M tokens
PRICE_INPUT = 0.60
PRICE_OUTPUT = 2.40

# Configuración de audio
CHUNK = 2048
FORMAT = pyaudio.paInt16 if AUDIO_AVAILABLE else None
CHANNELS = 1
RATE = 24000

class RealtimeGUIChat:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenAI Realtime Chat - GUI con Voz")
        self.root.geometry("800x720")
        self.root.configure(bg='#f0f0f0')
        
        self.ws = None
        self.connected = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_cost = 0.0
        
        # Audio
        self.voice_mode = False
        self.recording = False
        self.audio = pyaudio.PyAudio() if AUDIO_AVAILABLE else None
        self.output_queue = queue.Queue()
        self.audio_thread = None
        self.playback_thread = None
        
        # Configuración personalizable
        self.voice = "alloy"
        self.instructions = "Eres un asistente útil y amigable. Responde en español de forma concisa y clara."
        self.temperature = 0.8
        
        self.setup_ui()
        self.start_connection()
        
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
        mode_text = "🎤 Modo Voz" if AUDIO_AVAILABLE else "🎤 (Audio no disponible)"
        self.mode_button = tk.Button(
            controls_frame,
            text=mode_text,
            command=self.toggle_voice_mode,
            bg='#9b59b6',
            fg='white',
            font=('Arial', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2' if AUDIO_AVAILABLE else 'arrow',
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
        
        # Grabar
        self.record_button = tk.Button(
            self.button_frame,
            text="🎤 Grabar",
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
        
    def append_message(self, sender, message, tag='user'):
        self.chat_display.config(state=tk.NORMAL)
        time_str = datetime.now().strftime("%H:%M:%S")
        self.chat_display.insert(tk.END, f"[{time_str}] ", 'time')
        self.chat_display.insert(tk.END, f"{sender}: ", tag)
        self.chat_display.insert(tk.END, f"{message}\n\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def update_stats(self):
        self.total_cost = (self.input_tokens / 1_000_000 * PRICE_INPUT + 
                          self.output_tokens / 1_000_000 * PRICE_OUTPUT)
        stats_text = (f"Tokens: {self.input_tokens:,} entrada, {self.output_tokens:,} salida | "
                     f"Costo: ${self.total_cost:.4f}")
        self.stats_label.config(text=stats_text)
        
    def update_status(self, status, color):
        self.status_label.config(text=f"● {status}", fg=color)
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            if event_type == 'session.created':
                self.connected = True
                self.root.after(0, self.update_status, "Conectado", "#27ae60")
                self.root.after(0, lambda: self.send_button.config(state=tk.NORMAL))
                if AUDIO_AVAILABLE:
                    self.root.after(0, lambda: self.mode_button.config(state=tk.NORMAL))
                self.root.after(0, self.append_message, "Sistema", "✓ Conectado. Escribe o usa voz!", 'system')
                
            elif event_type == 'session.updated':
                pass
                
            elif event_type == 'response.text.delta':
                text = data.get('delta', '')
                if not hasattr(self, 'current_response'):
                    self.current_response = ""
                self.current_response += text
                
            elif event_type == 'response.text.done':
                if hasattr(self, 'current_response') and not self.voice_mode:
                    self.root.after(0, self.append_message, "Asistente", self.current_response, 'assistant')
                    delattr(self, 'current_response')
                    
            elif event_type == 'input_audio_buffer.speech_started':
                self.root.after(0, self.append_message, "Sistema", "🎤 Detectando...", 'system')
                
            elif event_type == 'input_audio_buffer.speech_stopped':
                self.root.after(0, self.append_message, "Sistema", "🎤 Procesando...", 'system')
                
            elif event_type == 'response.audio_transcript.delta':
                text = data.get('delta', '')
                if not hasattr(self, 'current_response'):
                    self.current_response = ""
                self.current_response += text
                
            elif event_type == 'response.audio_transcript.done':
                if hasattr(self, 'current_response'):
                    self.root.after(0, self.append_message, "Asistente", self.current_response, 'assistant')
                    delattr(self, 'current_response')
                    
            elif event_type == 'response.audio.delta':
                audio_b64 = data.get('delta', '')
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                self.output_queue.put(None)
                    
            elif event_type == 'response.done':
                usage = data.get('response', {}).get('usage', {})
                if usage:
                    self.input_tokens += usage.get('input_tokens', 0)
                    self.output_tokens += usage.get('output_tokens', 0)
                    self.root.after(0, self.update_stats)
                    
            elif event_type == 'error':
                error = data.get('error', {})
                error_msg = error.get('message', 'Error desconocido')
                self.root.after(0, self.append_message, "Error", error_msg, 'system')
                
        except Exception as e:
            print(f"Error procesando: {e}")
            
    def on_error(self, ws, error):
        self.root.after(0, self.update_status, "Error", "#e74c3c")
        self.root.after(0, self.append_message, "Sistema", f"Error: {error}", 'system')
        
    def on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.root.after(0, self.update_status, "Desconectado", "#e74c3c")
        self.root.after(0, lambda: self.send_button.config(state=tk.DISABLED))
        
    def on_open(self, ws):
        self.update_session_config()
        
    def update_session_config(self):
        modalities = ["text", "audio"] if self.voice_mode else ["text"]
        
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": modalities,
                "instructions": self.instructions,
                "temperature": self.temperature,
            }
        }
        
        if self.voice_mode:
            session_config["session"].update({
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700
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
        if not AUDIO_AVAILABLE:
            return
            
        self.voice_mode = not self.voice_mode
        
        if self.voice_mode:
            self.mode_label.config(text="Modo: Voz 🎤", fg='#e74c3c')
            self.mode_button.config(text="💬 Modo Texto", bg='#3498db')
            self.message_entry.pack_forget()
            self.send_button.pack_forget()
            self.record_button.pack(fill=tk.Y)
            self.record_button.config(state=tk.NORMAL if self.connected else tk.DISABLED)
            self.append_message("Sistema", "✓ Modo voz activado", 'system')
        else:
            self.mode_label.config(text="Modo: Texto 💬", fg='#7f8c8d')
            self.mode_button.config(text="🎤 Modo Voz", bg='#9b59b6')
            self.record_button.pack_forget()
            self.message_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
            self.send_button.pack(fill=tk.Y)
            self.append_message("Sistema", "✓ Modo texto activado", 'system')
            
        self.update_session_config()
        
    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()
            
    def start_recording(self):
        self.recording = True
        self.record_button.config(text="⏹️ Detener", bg='#27ae60')
        self.append_message("Sistema", "🔴 Grabando...", 'system')
        
        self.audio_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.audio_thread.start()
        
        self.playback_thread = threading.Thread(target=self.play_audio, daemon=True)
        self.playback_thread.start()
        
    def stop_recording(self):
        self.recording = False
        self.record_button.config(text="🎤 Grabar", bg='#e74c3c')
        self.append_message("Sistema", "⏸️ Detenido", 'system')
        
    def record_audio(self):
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
            
            while self.recording:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    if self.connected:
                        self.send_audio_chunk(data)
                except Exception as e:
                    print(f"Error audio: {e}")
                    break
                    
        except Exception as e:
            self.root.after(0, self.append_message, "Error", f"Micrófono: {e}", 'system')
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
                
    def play_audio(self):
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK
            )
            
            while True:
                audio_chunk = self.output_queue.get()
                if audio_chunk is None:
                    break
                try:
                    stream.write(audio_chunk)
                except Exception as e:
                    print(f"Error play: {e}")
                    break
                    
        except Exception as e:
            self.root.after(0, self.append_message, "Error", f"Altavoz: {e}", 'system')
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
                
    def send_audio_chunk(self, audio_bytes):
        if not self.connected or not self.voice_mode:
            return
            
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        self.ws.send(json.dumps(event))
        
    def send_message(self):
        message = self.message_entry.get('1.0', tk.END).strip()
        
        if not message or not self.connected:
            return
            
        self.append_message("Tú", message, 'user')
        self.message_entry.delete('1.0', tk.END)
        
        message_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": message}]
            }
        }
        
        response_event = {"type": "response.create"}
        
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
        
    def on_closing(self):
        self.recording = False
        if self.ws:
            self.ws.close()
        if self.audio:
            self.audio.terminate()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = RealtimeGUIChat(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
