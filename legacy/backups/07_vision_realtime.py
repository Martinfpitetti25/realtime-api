"""
Vision + Realtime Assistant con resampling de audio automático
Integración completa de YOLO object detection con OpenAI Realtime API
Incluye resampling automático de audio para compatibilidad con hardware
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
from scipy import signal as scipy_signal

# Importar nuestro servicio de visión
from hardware.camera_service import CameraService
from utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-4o-realtime-preview-2024-12-17'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

# Audio - API requiere 24kHz
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE_API = 24000  # Lo que requiere la API

# Rate de hardware (se detectará automáticamente)
RATE_HW = 48000  # Default, se ajustará si es necesario

class VisionRealtimeAssistant:
    """Asistente con visión y audio resampling automático"""
    
    def __init__(self):
        self.ws = None
        self.p = pyaudio.PyAudio()
        self.stream_in = None
        self.stream_out = None
        self.recording = False
        self.input_queue = queue.Queue()
        self.output_queue = queue.Queue()
        
        # Visión
        self.camera_service = CameraService()
        self.vision_thread = None
        self.last_vision_context = None
        
        # Audio resampling
        self.hw_rate_in = RATE_HW   # Default input rate
        self.hw_rate_out = RATE_HW  # Default output rate
        self.api_rate = RATE_API
        self.resample_ratio_in = self.api_rate / self.hw_rate_in   # hw -> api
        self.resample_ratio_out = self.hw_rate_out / self.api_rate # api -> hw
        
        logger.info(f"🤖 Vision Realtime Assistant inicializado")
        logger.info(f"🎤 Audio: Hardware {self.hw_rate_in}Hz → API {self.api_rate}Hz")
    
    def find_supported_rate(self, for_output=False):
        """Encuentra un rate de audio soportado por el hardware"""
        test_rates = [48000, 44100, 32000, 16000, 8000]
        channels = 2 if for_output else CHANNELS  # Output necesita 2 canales
        
        for rate in test_rates:
            try:
                # Intentar abrir un stream temporal
                test_stream = self.p.open(
                    format=FORMAT,
                    channels=channels,
                    rate=rate,
                    output=for_output,
                    input=not for_output,
                    frames_per_buffer=CHUNK
                )
                test_stream.close()
                logger.info(f"✅ Rate soportado {'output' if for_output else 'input'}: {rate} Hz ({channels} ch)")
                return rate
            except Exception as e:
                logger.debug(f"❌ Rate {rate} Hz no soportado: {e}")
                continue
        
        logger.error("❌ No se encontró ningún rate soportado")
        return None
    
    def resample_audio(self, audio_data, ratio):
        """Resamplea audio usando scipy"""
        # Convertir bytes a numpy array
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        # Calcular nueva longitud
        new_length = int(len(audio_np) * ratio)
        
        # Resamplear
        resampled = scipy_signal.resample(audio_np, new_length)
        
        # Convertir de vuelta a bytes
        return resampled.astype(np.int16).tobytes()
    
    def start_recording(self):
        """Inicia grabación con resampling automático (solo input por ahora)"""
        # Detectar rate soportado para input
        detected_rate_in = self.find_supported_rate(for_output=False)
        if not detected_rate_in:
            logger.error("❌ No se encontró rate para input")
            return
        
        # Configurar resampling
        self.hw_rate_in = detected_rate_in
        self.resample_ratio_in = self.api_rate / self.hw_rate_in
        
        logger.info(f"🔄 Resampling configurado:")
        logger.info(f"   Input:  {self.hw_rate_in}Hz → {self.api_rate}Hz")
        logger.warning(f"⚠️  Output deshabilitado (hardware no soportado)")
        
        try:
            # Abrir stream de entrada con rate de hardware
            self.stream_in = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.hw_rate_in,
                input=True,
                frames_per_buffer=CHUNK
            )
            logger.info(f"🎤 Micrófono activado ({self.hw_rate_in} Hz → {self.api_rate} Hz)")
        except Exception as e:
            logger.error(f"❌ Error iniciando micrófono: {e}")
            return
        
        self.recording = True
        
        # Iniciar threads (sin output por ahora)
        threading.Thread(target=self._audio_input_loop, daemon=True).start()
        threading.Thread(target=self._send_audio_loop, daemon=True).start()
        logger.warning("⚠️  Audio output deshabilitado - solo entrada de voz")
    
    def _audio_input_loop(self):
        """Captura audio del micrófono y lo resamplea"""
        logger.info("🎙️ Loop de captura iniciado")
        
        while self.recording:
            try:
                # Leer del micrófono (hw_rate)
                data = self.stream_in.read(CHUNK, exception_on_overflow=False)
                
                # Resamplear a api_rate
                resampled = self.resample_audio(data, self.resample_ratio_in)
                
                # Enviar a cola
                self.input_queue.put(resampled)
                
            except Exception as e:
                logger.error(f"❌ Error en captura de audio: {e}")
                break
    
    def _send_audio_loop(self):
        """Envía audio a la API desde la cola"""
        while self.recording:
            try:
                audio_data = self.input_queue.get(timeout=0.1)
                
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    event = {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(audio_data).decode()
                    }
                    self.ws.send(json.dumps(event))
                    
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ Error enviando audio: {e}")
    
    def _audio_output_loop(self):
        """Reproduce audio desde la cola con resampling (DESHABILITADO)"""
        logger.warning("🔇 Output loop deshabilitado - hardware no soportado")
        return
        
        # TODO: Habilitar cuando se solucione el problema de formato de audio
        # logger.info("🔊 Loop de reproducción iniciado")
        # 
        # while self.recording:
        #     try:
        #         # Obtener audio de la cola (api_rate, mono)
        #         audio_data = self.output_queue.get(timeout=0.1)
        #         
        #         # Resamplear a hw_rate
        #         resampled = self.resample_audio(audio_data, self.resample_ratio_out)
        #         
        #         # Convertir mono a stereo (duplicar canal)
        #         audio_np = np.frombuffer(resampled, dtype=np.int16)
        #         stereo = np.column_stack((audio_np, audio_np)).flatten()
        #         
        #         # Reproducir
        #         self.stream_out.write(stereo.tobytes())
        #         
        #     except queue.Empty:
        #         continue
        #     except Exception as e:
        #         logger.error(f"❌ Error en reproducción: {e}")
        #         break
    
    def stop_recording(self):
        """Detiene la grabación"""
        self.recording = False
        
        if self.stream_in:
            self.stream_in.stop_stream()
            self.stream_in.close()
        
        if self.stream_out:
            self.stream_out.stop_stream()
            self.stream_out.close()
        
        logger.info("🛑 Audio detenido")
    
    def start_vision(self):
        """Inicia el servicio de visión en background"""
        logger.info("👁️ Iniciando servicio de visión...")
        
        # Inicializar cámara
        cam_idx = self.camera_service.find_camera()
        if cam_idx is None:
            logger.error("❌ No se encontró cámara")
            return
        
        if not self.camera_service.start_camera(cam_idx):
            logger.error("❌ Error iniciando cámara")
            return
        
        # Cargar YOLO
        if not self.camera_service.load_yolo_model():
            logger.error("❌ Error cargando YOLO")
            return
        
        # Iniciar detección asíncrona
        self.camera_service.start_async_detection()
        
        # Thread para actualizar contexto de visión
        self.vision_thread = threading.Thread(target=self._vision_update_loop, daemon=True)
        self.vision_thread.start()
    
    def _vision_update_loop(self):
        """Actualiza el contexto de visión periódicamente"""
        while self.recording:
            try:
                # Obtener contexto actual
                context = self.camera_service.get_vision_context_for_realtime()
                
                if context and context != self.last_vision_context:
                    self.last_vision_context = context
                    
                    # Enviar a la API
                    if self.ws and self.ws.sock and self.ws.sock.connected:
                        vision_message = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": f"[VISION] {context['vision_summary']}"
                                    }
                                ]
                            }
                        }
                        self.ws.send(json.dumps(vision_message))
                        logger.info(f"👁️ Contexto enviado: {context['vision_summary']}")
                
                # Esperar antes de la siguiente actualización
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Error en vision loop: {e}")
                time.sleep(1)
    
    def stop_vision(self):
        """Detiene el servicio de visión"""
        if self.camera_service:
            self.camera_service.stop_async_detection()
            self.camera_service.release()
        logger.info("👁️ Visión detenida")
    
    def connect(self):
        """Conecta al servidor WebSocket"""
        logger.info(f"🔌 Conectando a {URL}")
        
        self.ws = websocket.WebSocketApp(
            URL,
            header={
                "Authorization": f"Bearer {API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            },
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        # Iniciar visión
        self.start_vision()
        
        # Ejecutar WebSocket
        wst = threading.Thread(target=self.ws.run_forever, daemon=True)
        wst.start()
        
        # Mantener vivo
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("\n👋 Cerrando...")
            self.cleanup()
    
    def _on_open(self, ws):
        """Callback cuando se abre la conexión"""
        logger.info("✅ Conexión establecida")
        
        # Configurar sesión
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": """Eres un asistente de robot con visión. 
Cuando recibas información con [VISION], úsala en tus respuestas.
Sé conciso y amigable.""",
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
                    "silence_duration_ms": 500
                }
            }
        }
        ws.send(json.dumps(session_update))
        logger.info("📝 Sesión configurada")
        
        # Iniciar grabación
        self.start_recording()
    
    def _on_message(self, ws, message):
        """Callback cuando llega un mensaje"""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            # Audio de respuesta
            if msg_type == 'response.audio.delta':
                audio_b64 = data.get('delta')
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self.output_queue.put(audio_bytes)
            
            # Transcripción del usuario
            elif msg_type == 'conversation.item.input_audio_transcription.completed':
                transcript = data.get('transcript', '')
                if transcript:
                    logger.info(f"👤 Tú: {transcript}")
            
            # Texto de respuesta
            elif msg_type == 'response.text.delta':
                delta = data.get('delta', '')
                print(delta, end='', flush=True)
            
            elif msg_type == 'response.text.done':
                print()  # Nueva línea
            
            # Errores
            elif msg_type == 'error':
                error_info = data.get('error', {})
                logger.error(f"❌ Error API: {error_info}")
                
        except Exception as e:
            logger.error(f"❌ Error procesando mensaje: {e}")
    
    def _on_error(self, ws, error):
        """Callback de error"""
        logger.error(f"❌ WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Callback cuando se cierra la conexión"""
        logger.info(f"🔌 Conexión cerrada: {close_status_code} - {close_msg}")
        self.cleanup()
    
    def cleanup(self):
        """Limpia recursos"""
        self.stop_recording()
        self.stop_vision()
        if self.ws:
            self.ws.close()
        self.p.terminate()
        logger.info("✅ Recursos liberados")

def main():
    """Función principal"""
    print("=" * 60)
    print("🤖 VISION REALTIME ASSISTANT")
    print("=" * 60)
    print()
    
    if not API_KEY:
        logger.error("❌ OPENAI_API_KEY no encontrada en .env")
        return
    
    assistant = VisionRealtimeAssistant()
    
    try:
        assistant.connect()
    except KeyboardInterrupt:
        logger.info("\n👋 Interrupted by user")
        assistant.cleanup()

if __name__ == "__main__":
    main()
