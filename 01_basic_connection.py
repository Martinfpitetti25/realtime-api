"""
Script básico de conexión a la OpenAI Realtime API
Este script establece una conexión WebSocket y muestra los eventos que llegan del servidor
"""
import os
import json
import websocket
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'  # Usa el modelo más económico para pruebas
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

def on_message(ws, message):
    """Callback cuando se recibe un mensaje del servidor"""
    try:
        data = json.loads(message)
        event_type = data.get('type', 'unknown')
        print(f"\n📨 Evento recibido: {event_type}")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(f"❌ Error decodificando mensaje: {message}")

def on_error(ws, error):
    """Callback cuando hay un error"""
    print(f"\n❌ Error: {error}")

def on_close(ws, close_status_code, close_msg):
    """Callback cuando se cierra la conexión"""
    print(f"\n🔌 Conexión cerrada (código: {close_status_code})")
    if close_msg:
        print(f"   Mensaje: {close_msg}")

def on_open(ws):
    """Callback cuando se abre la conexión"""
    print("✅ Conectado al servidor OpenAI Realtime API\n")
    
    # Configurar la sesión
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": "Eres un asistente útil y amigable. Responde en español.",
            "voice": "alloy",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "temperature": 0.8,
        }
    }
    
    print("📤 Enviando configuración de sesión...")
    ws.send(json.dumps(session_config))
    print(json.dumps(session_config, indent=2, ensure_ascii=False))

def main():
    """Función principal"""
    if not API_KEY:
        print("❌ Error: No se encontró OPENAI_API_KEY en el archivo .env")
        print("   Copia .env.example a .env y agrega tu API key")
        return
    
    print("🚀 Iniciando conexión a OpenAI Realtime API...")
    print(f"   Modelo: {MODEL}")
    print(f"   URL: {URL}\n")
    
    # Configurar WebSocket con autenticación
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    # Crear y configurar el cliente WebSocket
    ws = websocket.WebSocketApp(
        URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    
    # Iniciar la conexión (esto bloqueará el programa)
    try:
        ws.run_forever()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupción del usuario (Ctrl+C)")
        ws.close()

if __name__ == "__main__":
    main()
