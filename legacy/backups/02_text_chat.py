"""
Chat de texto con OpenAI Realtime API
Este script permite enviar mensajes de texto y recibir respuestas
"""
import os
import json
import base64
import websocket
import threading
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

class RealtimeChat:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.audio_chunks = []
        
    def on_message(self, ws, message):
        """Callback cuando se recibe un mensaje del servidor"""
        try:
            data = json.loads(message)
            event_type = data.get('type', 'unknown')
            
            # Mostrar solo eventos relevantes
            if event_type == 'session.created':
                print("✅ Sesión creada exitosamente")
                self.connected = True
                
            elif event_type == 'session.updated':
                print("✅ Sesión actualizada")
                
            elif event_type == 'response.text.delta':
                # Texto incremental de la respuesta
                text = data.get('delta', '')
                print(text, end='', flush=True)
                
            elif event_type == 'response.text.done':
                # Texto completo
                print()  # Nueva línea
                
            elif event_type == 'response.audio.delta':
                # Audio incremental (en base64)
                audio_data = data.get('delta', '')
                if audio_data:
                    self.audio_chunks.append(audio_data)
                    
            elif event_type == 'response.audio.done':
                print("\n🎵 Audio recibido (no reproducido en esta demo)")
                self.audio_chunks = []
                
            elif event_type == 'response.done':
                print("\n✅ Respuesta completa\n")
                
            elif event_type == 'error':
                error = data.get('error', {})
                print(f"\n❌ Error: {error.get('message', 'Unknown error')}")
                
            # Descomentar para ver todos los eventos:
            # else:
            #     print(f"📨 {event_type}")
                
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
        print("🔗 Conectando al servidor...\n")
        
        # Configurar la sesión
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text"],  # Solo texto por ahora
                "instructions": "Eres un asistente útil y amigable. Responde en español de forma concisa.",
                "temperature": 0.8,
            }
        }
        
        ws.send(json.dumps(session_config))

    def send_message(self, text):
        """Envía un mensaje de texto al asistente"""
        if not self.connected:
            print("❌ No hay conexión activa")
            return
            
        # Crear el evento de conversación
        message_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": text
                    }
                ]
            }
        }
        
        # Solicitar una respuesta
        response_event = {
            "type": "response.create"
        }
        
        # Enviar ambos eventos
        self.ws.send(json.dumps(message_event))
        self.ws.send(json.dumps(response_event))

    def start(self):
        """Inicia la conexión WebSocket"""
        if not API_KEY:
            print("❌ Error: No se encontró OPENAI_API_KEY en el archivo .env")
            return
        
        print("🚀 Iniciando chat con OpenAI Realtime API...")
        print(f"   Modelo: {MODEL}\n")
        
        # Configurar WebSocket con autenticación
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        # Crear el cliente WebSocket
        self.ws = websocket.WebSocketApp(
            URL,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Ejecutar en un hilo separado
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        # Esperar a que se conecte
        import time
        time.sleep(2)
        
        return ws_thread

def main():
    """Función principal"""
    chat = RealtimeChat()
    ws_thread = chat.start()
    
    if not ws_thread:
        return
    
    print("="*60)
    print("💬 Chat iniciado. Escribe tus mensajes (o 'salir' para terminar)")
    print("="*60)
    print()
    
    try:
        while chat.connected or ws_thread.is_alive():
            try:
                # Leer input del usuario
                user_input = input("Tú: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['salir', 'exit', 'quit']:
                    print("\n👋 Cerrando chat...")
                    break
                
                # Enviar mensaje
                print("\nAsistente: ", end='', flush=True)
                chat.send_message(user_input)
                
            except EOFError:
                break
                
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupción del usuario (Ctrl+C)")
    
    finally:
        if chat.ws:
            chat.ws.close()
        print("👋 ¡Hasta luego!")

if __name__ == "__main__":
    main()
