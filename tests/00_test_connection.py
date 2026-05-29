"""
Script de prueba simple - Solo muestra que la conexión funciona
Úsalo primero para verificar que tu API key es correcta
"""
import os
import json
import websocket
from dotenv import load_dotenv
import time

load_dotenv()

API_KEY = os.getenv('OPENAI_API_KEY')
MODEL = 'gpt-realtime-mini'
URL = f'wss://api.openai.com/v1/realtime?model={MODEL}'

print("="*60)
print("🧪 TEST DE CONEXIÓN - OpenAI Realtime API")
print("="*60)
print()

if not API_KEY:
    print("❌ ERROR: No se encontró OPENAI_API_KEY")
    print("   Por favor edita el archivo .env y agrega tu API key")
    exit(1)

print(f"✓ API Key encontrada: {API_KEY[:10]}...{API_KEY[-4:]}")
print(f"✓ Modelo: {MODEL}")
print(f"✓ URL: {URL}")
print()
print("Intentando conectar...")
print()

connected = False
error_msg = None

def on_message(ws, message):
    global connected
    data = json.loads(message)
    event_type = data.get('type', 'unknown')
    
    if event_type == 'session.created':
        print("✅ ¡CONEXIÓN EXITOSA!")
        print(f"   ID de sesión: {data.get('session', {}).get('id', 'N/A')}")
        print()
        print("✅ La API funciona correctamente")
        print("   Ahora puedes usar los otros scripts:")
        print("   - 02_text_chat.py (chat de texto)")
        print("   - 03_audio_chat.py (chat de voz)")
        connected = True
        ws.close()
    elif event_type == 'error':
        print(f"❌ Error: {data.get('error', {}).get('message', 'Unknown')}")

def on_error(ws, error):
    global error_msg
    error_msg = str(error)
    print(f"❌ Error de conexión: {error}")

def on_close(ws, close_status_code, close_msg):
    if not connected and error_msg:
        print()
        print("❌ No se pudo conectar a la API")
        print("   Verifica:")
        print("   1. Tu API key es correcta")
        print("   2. Tienes acceso a la API Realtime")
        print("   3. Tu conexión a internet funciona")

def on_open(ws):
    # Solo configurar la sesión
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text"],
            "instructions": "Test"
        }
    }
    ws.send(json.dumps(session_config))

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "OpenAI-Beta": "realtime=v1"
}

ws = websocket.WebSocketApp(
    URL,
    header=headers,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

ws.run_forever()

print()
print("="*60)
