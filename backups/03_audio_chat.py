"""
Chat de voz con OpenAI Realtime API
Este script captura audio del micrófono, lo envía a la API y reproduce la respuesta
Ideal para usar en Raspberry Pi con micrófono y altavoces
"""
import os
import json
import base64
import wave
import pyaudio
import websocket
import threading
import queue
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Configuración de audio
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000  # La API Realtime usa 24kHz

class RealtimeVoiceChat:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.recording = False
        self.audio = pyaudio.PyAudio()
        self.audio_queue = queue.Queue()
        self.output_queue = queue.Queue()
        
    def on_message(self, ws, message):
        """Callback cuando se recibe un mensaje del servidor"""
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            if event_type == 'session.created':
                print("✅ Sesión creada")
                self.connected = True
                
            elif event_type == 'session.updated':
                print("✅ Sesión actualizada")
                
            elif event_type == 'input_audio_buffer.speech_started':
                print("\n🎤 Detectado inicio de habla...")
                
            elif event_type == 'input_audio_buffer.speech_stopped':
                print("🎤 Detectado fin de habla")
                
            elif event_type == 'response.audio_transcript.delta':
                # Transcripción de lo que el asistente está diciendo
                text = data.get('delta', '')
                print(text, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                print()  # Nueva línea
                
            elif event_type == 'response.audio.delta':
                # Audio de respuesta (en base64, PCM16 a 24kHz)
                audio_b64 = data.get('delta', '')
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                print("✅ Respuesta de audio completa")
                self.output_queue.put(None)  # Señal de fin
                
            elif event_type == 'response.done':
                print("="*60 + "\n")
                
            elif event_type == 'error':
                error = data.get('error', {})
                print(f"\n❌ Error: {error.get('message', 'Unknown error')}")
                
        except json.JSONDecodeError:
            print(f"❌ Error decodificando mensaje")

    def on_error(self, ws, error):
        """Callback cuando hay un error"""
        print(f"\n❌ Error de conexión: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Callback cuando se cierra la conexión"""
        print(f"\n🔌 Conexión cerrada")
        self.connected = False

    def on_open(self, ws):
        """Callback cuando se abre la conexión"""
        print("🔗 Estableciendo conexión...\n")
        
        # Configurar la sesión para audio
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "Eres un asistente útil y amigable. Responde en español de forma concisa y natural.",
                "voice": "alloy",  # Opciones: alloy, echo, shimmer
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",  # Detección automática de voz
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                },
                "temperature": 0.8,
            }
        }
        
        ws.send(json.dumps(session_config))

    def send_audio_chunk(self, audio_bytes):
        """Envía un chunk de audio al servidor"""
        if not self.connected:
            return
            
        # Codificar en base64
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        # Enviar el evento
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        
        self.ws.send(json.dumps(event))

    def record_audio(self):
        """Graba audio del micrófono y lo envía"""
        print("🎤 Iniciando grabación...")
        
        stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        try:
            while self.recording:
                data = stream.read(CHUNK, exception_on_overflow=False)
                if self.connected:
                    self.send_audio_chunk(data)
        finally:
            stream.stop_stream()
            stream.close()
            print("🎤 Grabación detenida")

    def play_audio(self):
        """Reproduce el audio de respuesta"""
        stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            output=True,
            frames_per_buffer=CHUNK
        )
        
        try:
            while True:
                audio_chunk = self.output_queue.get()
                if audio_chunk is None:  # Señal de fin
                    break
                stream.write(audio_chunk)
        finally:
            stream.stop_stream()
            stream.close()

    def start(self):
        """Inicia la conexión WebSocket"""
        if not API_KEY:
            print("❌ Error: No se encontró OPENAI_API_KEY")
            return None
        
        print("🚀 Iniciando chat de voz con OpenAI...")
        print(f"   Modelo: {MODEL}")
        print(f"   Tasa de muestreo: {RATE}Hz\n")
        
        # Configurar WebSocket
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
        
        # Ejecutar WebSocket en un hilo
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        # Esperar conexión
        import time
        time.sleep(2)
        
        return ws_thread

    def cleanup(self):
        """Limpia recursos"""
        self.recording = False
        if self.ws:
            self.ws.close()
        self.audio.terminate()

def main():
    """Función principal"""
    chat = RealtimeVoiceChat()
    ws_thread = chat.start()
    
    if not ws_thread:
        return
    
    print("="*60)
    print("🎙️  Chat de voz iniciado")
    print("   Presiona ENTER para hablar")
    print("   Escribe 'salir' para terminar")
    print("="*60)
    print()
    
    try:
        while chat.connected or ws_thread.is_alive():
            user_input = input("Presiona ENTER para hablar (o 'salir'): ").strip()
            
            if user_input.lower() in ['salir', 'exit', 'quit']:
                break
            
            # Iniciar grabación
            chat.recording = True
            record_thread = threading.Thread(target=chat.record_audio)
            record_thread.start()
            
            # Iniciar reproducción en otro hilo
            play_thread = threading.Thread(target=chat.play_audio)
            play_thread.start()
            
            print("\n🗣️  Habla ahora... (Presiona ENTER para detener)\n")
            input()
            
            # Detener grabación
            chat.recording = False
            record_thread.join()
            
            print("\n🤖 Asistente: ", end='', flush=True)
            
            # Esperar a que termine la reproducción
            play_thread.join()
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupción del usuario")
    finally:
        chat.cleanup()
        print("👋 ¡Hasta luego!")

if __name__ == "__main__":
    main()
