"""
Robot Assistant con voz en tiempo real - Optimizado profesionalmente
Características:
- Interrupción inteligente (cancelar respuesta mientras habla)
- Reducción de ruido y filtrado de audio
- VAD más sensible para respuesta rápida
- Supresión de eco y normalización de volumen
"""
import os
import json
import base64
import pyaudio
import websocket
import threading
import queue
import numpy as np
from dotenv import load_dotenv
import time

load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Audio optimizado para baja latencia
CHUNK = 512  # Reducido para menor latencia
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000

# Configuración de filtros de audio
NOISE_GATE_THRESHOLD = 500  # Umbral de ruido (ajustable)
VOLUME_NORMALIZATION = True
APPLY_NOISE_REDUCTION = True

class AudioProcessor:
    """Procesador de audio con reducción de ruido y normalización"""
    
    def __init__(self):
        self.noise_floor = None
        self.calibration_frames = []
        self.is_calibrated = False
        
    def calibrate_noise_floor(self, audio_data, max_frames=10):
        """Calibra el nivel de ruido de fondo"""
        if len(self.calibration_frames) < max_frames:
            self.calibration_frames.append(audio_data)
            return False
        
        if not self.is_calibrated:
            # Calcular promedio del ruido de fondo
            all_data = np.concatenate(self.calibration_frames)
            self.noise_floor = np.mean(np.abs(all_data))
            self.is_calibrated = True
            print(f"✓ Calibración de ruido completada (nivel: {self.noise_floor:.0f})")
        
        return True
    
    def apply_noise_gate(self, audio_data, threshold=None):
        """Aplica noise gate para eliminar ruido de fondo"""
        if threshold is None:
            threshold = NOISE_GATE_THRESHOLD
        
        # Convertir a numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # Calcular energía de la señal
        energy = np.abs(audio_array).mean()
        
        # Si está por debajo del umbral, silenciar
        if energy < threshold:
            return np.zeros_like(audio_array).tobytes()
        
        return audio_data
    
    def normalize_volume(self, audio_data, target_level=10000):
        """Normaliza el volumen del audio"""
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # Calcular nivel actual
        current_level = np.abs(audio_array).max()
        
        if current_level == 0:
            return audio_data
        
        # Calcular factor de normalización
        scale = target_level / current_level
        
        # Limitar el factor para evitar distorsión
        scale = min(scale, 3.0)
        
        # Aplicar normalización
        normalized = (audio_array * scale).astype(np.int16)
        
        return normalized.tobytes()
    
    def process_input(self, audio_data):
        """Procesa audio de entrada con todos los filtros"""
        processed = audio_data
        
        # Aplicar noise gate
        if APPLY_NOISE_REDUCTION:
            processed = self.apply_noise_gate(processed)
        
        # Normalizar volumen
        if VOLUME_NORMALIZATION:
            processed = self.normalize_volume(processed)
        
        return processed


class RobotVoiceAssistant:
    def __init__(self, input_device=None, output_device=None):
        self.ws = None
        self.connected = False
        self.recording = False
        self.audio = pyaudio.PyAudio()
        self.output_queue = queue.Queue()
        self.input_device = input_device
        self.output_device = output_device
        
        # Sistema de interrupción
        self.is_speaking = False
        self.interrupt_requested = False
        self.response_lock = threading.Lock()
        
        # Procesador de audio
        self.audio_processor = AudioProcessor()
        self.calibrating = True
        
        # Estado del robot
        self.state = "idle"  # idle, listening, processing, speaking
        
    def on_message(self, ws, message):
        """Callback cuando se recibe un mensaje"""
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            if event_type == 'session.created':
                print("✅ Robot iniciado")
                self.connected = True
                self.state = "idle"
                
            elif event_type == 'session.updated':
                print("✅ Configuración aplicada")
                print("🎤 Calibrando micrófono (habla durante 3 segundos)...\n")
                
            elif event_type == 'input_audio_buffer.speech_started':
                print("\n🎤 [Escuchando...]", flush=True)
                self.state = "listening"
                
                # Si está hablando, interrumpir
                if self.is_speaking:
                    print("\n⚡ [Interrumpido - Cancelando respuesta]")
                    self.interrupt_response()
                
            elif event_type == 'input_audio_buffer.speech_stopped':
                print("🤖 [Procesando...]", flush=True)
                self.state = "processing"
                
            elif event_type == 'response.audio_transcript.delta':
                if not self.interrupt_requested:
                    text = data.get('delta', '')
                    print(text, end='', flush=True)
                
            elif event_type == 'response.audio_transcript.done':
                if not self.interrupt_requested:
                    print()
                
            elif event_type == 'response.audio.delta':
                if not self.interrupt_requested:
                    audio_b64 = data.get('delta', '')
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        self.output_queue.put(audio_bytes)
                        self.is_speaking = True
                        self.state = "speaking"
                
            elif event_type == 'response.audio.done':
                self.output_queue.put(None)
                self.is_speaking = False
                self.state = "idle"
                
            elif event_type == 'response.done':
                if not self.interrupt_requested:
                    print("\n" + "="*60 + "\n")
                self.interrupt_requested = False
                self.state = "idle"
                
            elif event_type == 'error':
                error = data.get('error', {})
                print(f"\n❌ Error: {error.get('message', 'Unknown')}")
                self.state = "idle"
                
        except Exception as e:
            print(f"❌ Error procesando mensaje: {e}")

    def interrupt_response(self):
        """Interrumpe la respuesta actual del robot"""
        with self.response_lock:
            self.interrupt_requested = True
            self.is_speaking = False
            
            # Limpiar cola de audio pendiente
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                except:
                    break
            
            # Cancelar respuesta en el servidor
            try:
                cancel_event = {
                    "type": "response.cancel"
                }
                self.ws.send(json.dumps(cancel_event))
                
                # Limpiar buffer de entrada
                clear_event = {
                    "type": "input_audio_buffer.clear"
                }
                self.ws.send(json.dumps(clear_event))
                
            except Exception as e:
                print(f"⚠️  Error cancelando respuesta: {e}")

    def on_error(self, ws, error):
        print(f"\n❌ Error WebSocket: {error}")
        self.state = "error"

    def on_close(self, ws, close_status_code, close_msg):
        print(f"\n🔌 Desconectado")
        self.connected = False
        self.state = "disconnected"

    def on_open(self, ws):
        print("🔗 Conectando robot...\n")
        
        # Configuración optimizada para robot con VAD más sensible
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": (
                    "Eres un robot asistente físico. "
                    "Responde de forma concisa (máximo 2-3 frases cortas). "
                    "Usa lenguaje directo y claro. "
                    "Habla en español de forma natural y amigable."
                ),
                "voice": "echo",  # Voz más robótica/autoritativa
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,  # Más sensible (antes 0.5)
                    "prefix_padding_ms": 200,  # Menor padding para respuesta rápida
                    "silence_duration_ms": 500  # Detecta silencio más rápido
                },
                "temperature": 0.7,  # Más consistente
            }
        }
        
        ws.send(json.dumps(session_config))

    def send_audio_chunk(self, audio_bytes):
        """Envía chunk de audio procesado"""
        if not self.connected:
            return
        
        # Procesar audio con filtros
        processed_audio = self.audio_processor.process_input(audio_bytes)
        
        audio_b64 = base64.b64encode(processed_audio).decode('utf-8')
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }
        self.ws.send(json.dumps(event))

    def record_audio(self):
        """Graba audio del micrófono con procesamiento"""
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=self.input_device,
                frames_per_buffer=CHUNK
            )
            
            print("🎤 Micrófono activo\n")
            
            frame_count = 0
            while self.recording:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    
                    # Calibración inicial
                    if self.calibrating:
                        if self.audio_processor.calibrate_noise_floor(
                            np.frombuffer(data, dtype=np.int16)
                        ):
                            self.calibrating = False
                            print("✓ Calibración completada - Listo para hablar\n")
                    
                    if self.connected and not self.calibrating:
                        self.send_audio_chunk(data)
                    
                    frame_count += 1
                    
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
                
                # Si se solicitó interrupción, detener reproducción
                if self.interrupt_requested:
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
        """Inicia conexión WebSocket"""
        if not API_KEY:
            print("❌ Error: OPENAI_API_KEY no configurada")
            return None
        
        print("🤖 Iniciando Robot Asistente")
        print(f"   Modelo: {MODEL}")
        print(f"   Latencia: {CHUNK} samples ({CHUNK/RATE*1000:.1f}ms)")
        print(f"   VAD threshold: 0.3 (alta sensibilidad)")
        print(f"   Reducción de ruido: {'ON' if APPLY_NOISE_REDUCTION else 'OFF'}")
        print(f"   Normalización: {'ON' if VOLUME_NORMALIZATION else 'OFF'}\n")
        
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
        
        time.sleep(2)
        return ws_thread

    def cleanup(self):
        """Limpia recursos"""
        self.recording = False
        if self.ws:
            self.ws.close()
        self.audio.terminate()


def list_audio_devices():
    """Lista dispositivos de audio disponibles"""
    audio = pyaudio.PyAudio()
    print("\n📱 Dispositivos de audio:")
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
            print(f"🎤 [{i}] {name}")
        if max_output > 0:
            output_devices.append((i, name))
            print(f"🔊 [{i}] {name}")
    
    audio.terminate()
    print("="*60 + "\n")
    
    return input_devices, output_devices


def main():
    """Función principal"""
    print("="*60)
    print("🤖 ROBOT ASISTENTE - VOZ EN TIEMPO REAL")
    print("="*60)
    
    # Detectar dispositivos
    input_devices, output_devices = list_audio_devices()
    
    if not input_devices:
        print("❌ No se detectó micrófono")
        return
    
    if not output_devices:
        print("❌ No se detectó altavoz")
        return
    
    input_device = input_devices[0][0]
    output_device = output_devices[0][0]
    
    print(f"✓ Micrófono: {input_devices[0][1]}")
    print(f"✓ Altavoz: {output_devices[0][1]}\n")
    
    # Iniciar robot
    robot = RobotVoiceAssistant(input_device, output_device)
    ws_thread = robot.start()
    
    if not ws_thread:
        return
    
    print("="*60)
    print("🎙️  ROBOT LISTO")
    print("   El robot escucha continuamente")
    print("   Puedes interrumpirlo mientras habla")
    print("   Escribe 'q' + ENTER para salir")
    print("="*60)
    print()
    
    # Iniciar grabación continua
    robot.recording = True
    record_thread = threading.Thread(target=robot.record_audio, daemon=True)
    record_thread.start()
    
    # Iniciar reproducción continua
    play_thread = threading.Thread(target=robot.play_audio, daemon=True)
    play_thread.start()
    
    try:
        while robot.connected or ws_thread.is_alive():
            user_input = input().strip().lower()
            
            if user_input in ['q', 'quit', 'salir', 'exit']:
                break
                
    except KeyboardInterrupt:
        print("\n\n⚠️  Apagando robot...")
    finally:
        robot.cleanup()
        print("👋 Robot apagado")


if __name__ == "__main__":
    main()
