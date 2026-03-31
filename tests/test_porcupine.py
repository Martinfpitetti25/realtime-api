"""Test rápido de Porcupine Wake Word"""
import os
from dotenv import load_dotenv
import pvporcupine

load_dotenv()

PORCUPINE_ACCESS_KEY = os.getenv('PORCUPINE_ACCESS_KEY', '')

print("=" * 60)
print("TEST DE PORCUPINE WAKE WORD")
print("=" * 60)

if not PORCUPINE_ACCESS_KEY:
    print("❌ No se encontró PORCUPINE_ACCESS_KEY en .env")
    exit(1)

print(f"✓ Access Key encontrada: {PORCUPINE_ACCESS_KEY[:20]}...")
print()

# Lista de wake words para probar
wake_words = ['jarvis', 'computer', 'alexa', 'hey google', 'picovoice']

print("Probando wake words disponibles:")
print("-" * 60)

for wake_word in wake_words:
    try:
        print(f"Probando '{wake_word}'... ", end='')
        porcupine = pvporcupine.create(
            access_key=PORCUPINE_ACCESS_KEY,
            keywords=[wake_word]
        )
        porcupine.delete()
        print("✅ FUNCIONA")
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "unauthorized" in error_msg.lower():
            print(f"❌ Access Key inválida")
            print(f"   Error: {error_msg[:100]}")
            break
        else:
            print(f"❌ No disponible")
            print(f"   Error: {error_msg[:100]}")

print()
print("=" * 60)
print("RECOMENDACIONES:")
print("=" * 60)

print("""
1. Verifica tu Access Key en: https://console.picovoice.ai/
2. Asegúrate de que sea una key válida (no expirada)
3. En la consola, verifica qué wake words están disponibles
4. Si el plan gratuito tiene límites, verifica tu uso
""")
