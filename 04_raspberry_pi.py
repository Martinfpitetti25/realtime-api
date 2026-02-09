"""
Chat de voz optimizado para Raspberry Pi
Incluye detección automática de dispositivos de audio y mejor manejo de errores
"""
import os
import json
import base64
import pyaudio
import websocket
import threading
import queue
from dotenv import load_dotenv

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Audio
CHUNK = 2048  # Buffer más grande para Raspberry Pi
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000

def list_audio_devices():
    """Lista todos los dispositivos de audio disponibles"""
    audio = pyaudio.PyAudio()
    print("\n📱 Dispositivos de audio detectados:")
    print("="*60)
    
    input_devices = []
    output_devices = []
    
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        name = info.get('name')
        max_input = info.get('maxInputChannels')
        max_output = info.get('maxOutputChannels')
        
        if max_input > 0:
            input_devices.append((i, name))
            print(f"🎤 [{i}] {name} (Entrada)")
        if max_output > 0:
            output_devices.append((i, name))
            print(f"🔊 [{i}] {name} (Salida)")
    
    audio.terminate()
    print("="*60 + "\n")
    
    return input_devices, output_devices

class RaspberryPiVoiceChat:
    def __init__(self, input_device=None, output_device=None):
        self.ws = None
        self.connected = False
        self.recording = False
        self.audio = pyaudio.PyAudio()
        self.output_queue = queue.Queue()
        self.input_device = input_device
        self.output_device = output_device
        
    def on_message(self, ws, message):
        """Callback cuando se recibe un mensaje"""
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            if event_type == 'session.created':
                print("✅ Sesión iniciada")
                self.connected = True
                
            elif event_type == 'session.updated':
                print("✅ Configuración aplicada\n")
                
            elif event_type == 'input_audio_buffer.speech_started':
                print("🎤 [Escuchando...]", flush=True)
                
            elif event_type == 'input_audio_buffer.speech_stopped':
                print("🎤 [Procesando...]", flush=True)
                
            elif event_type == 'response.audio_transcript.delta':
                text = data.get('delta', '')
                print(text, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                print()
                
            elif event_type == 'response.audio.delta':
                audio_b64 = data.get('delta', '')
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self.output_queue.put(audio_bytes)
                    
            elif event_type == 'response.audio.done':
                self.output_queue.put(None)
                
            elif event_type == 'response.done':
                print("\n" + "="*60 + "\n")
                
            elif event_type == 'error':
                error = data.get('error', {})
                print(f"\n❌ Error API: {error.get('message', 'Unknown')}")
                
        except Exception as e:
            print(f"❌ Error procesando mensaje: {e}")

    def on_error(self, ws, error):
        print(f"\n❌ Error WebSocket: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print(f"\n🔌 Desconectado")
        self.connected = False

    def on_open(self, ws):
        print("🔗 Conectando...\n")
        
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "Eres un asistente de voz útil para Raspberry Pi. Responde en español de forma concisa y clara.",
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700  # Un poco más largo para Raspberry Pi
                },
                "temperature": 0.8,
            }
        }
        
        ws.send(json.dumps(session_config))

    def send_audio_chunk(self, audio_bytes):
        if not self.connected:
            return
        
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        self.ws.send(json.dumps(event))

    def record_audio(self):
        """Graba audio del micrófono"""
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=self.input_device,
                frames_per_buffer=CHUNK
            )
            
            print("🎤 Grabando...")
            
            while self.recording:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    if self.connected:
                        self.send_audio_chunk(data)
                except Exception as e:
                    print(f"⚠️  Error leyendo audio: {e}")
                    break
                    
        except Exception as e:
            print(f"❌ Error abriendo micrófono: {e}")
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()

    def play_audio(self):
        """Reproduce audio de respuesta"""
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                output_device_index=self.output_device,
                frames_per_buffer=CHUNK
            )
            
            while True:
                audio_chunk = self.output_queue.get()
                if audio_chunk is None:
                    break
                try:
                    stream.write(audio_chunk)
                except Exception as e:
                    print(f"⚠️  Error reproduciendo: {e}")
                    break
                    
        except Exception as e:
            print(f"❌ Error abriendo altavoz: {e}")
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()

    def start(self):
        if not API_KEY:
            print("❌ Error: OPENAI_API_KEY no configurada")
            return None
        
        print("🚀 Iniciando Asistente de Voz para Raspberry Pi")
        print(f"   Modelo: {MODEL}")
        print(f"   Tasa: {RATE}Hz, Buffer: {CHUNK}\n")
        
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
        
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        import time
        time.sleep(2)
        
        return ws_thread

    def cleanup(self):
        self.recording = False
        if self.ws:
            self.ws.close()
        self.audio.terminate()

def main():
    """Función principal con detección automática"""
    print("="*60)
    print("🍓 ASISTENTE DE VOZ PARA RASPBERRY PI")
    print("="*60)
    
    # Listar dispositivos disponibles
    input_devices, output_devices = list_audio_devices()
    
    if not input_devices:
        print("❌ No se detectó ningún micrófono")
        print("   Conecta un micrófono USB y ejecuta de nuevo")
        return
    
    if not output_devices:
        print("❌ No se detectó ningún dispositivo de salida")
        return
    
    # Usar el primer dispositivo de entrada/salida por defecto
    input_device = input_devices[0][0]
    output_device = output_devices[0][0]
    
    print(f"✓ Usando micrófono: {input_devices[0][1]}")
    print(f"✓ Usando altavoz: {output_devices[0][1]}\n")
    
    # Iniciar chat
    chat = RaspberryPiVoiceChat(input_device, output_device)
    ws_thread = chat.start()
    
    if not ws_thread:
        return
    
    print("="*60)
    print("🎙️  LISTO PARA HABLAR")
    print("   Presiona ENTER para empezar a grabar")
    print("   Presiona ENTER otra vez para detener")
    print("   Escribe 'salir' para terminar")
    print("="*60)
    print()
    
    try:
        while chat.connected or ws_thread.is_alive():
            user_input = input("▶️  Presiona ENTER para hablar: ").strip()
            
            if user_input.lower() in ['salir', 'exit', 'quit', 'q']:
                break
            
            # Iniciar grabación y reproducción
            chat.recording = True
            record_thread = threading.Thread(target=chat.record_audio)
            play_thread = threading.Thread(target=chat.play_audio)
            
            record_thread.start()
            play_thread.start()
            
            print("🗣️  HABLANDO... (Presiona ENTER para detener)\n")
            input()
            
            chat.recording = False
            record_thread.join()
            
            print("\n🤖 Respuesta: ", flush=True)
            play_thread.join()
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrumpido")
    finally:
        chat.cleanup()
        print("\n👋 ¡Adiós!\n")

if __name__ == "__main__":
    main()
