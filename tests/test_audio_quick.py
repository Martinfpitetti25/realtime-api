#!/usr/bin/env python3
"""
Test rápido de reproducción de audio en PipeWire
"""
import pyaudio
import numpy as np
import time

print("="*60)
print("TEST RÁPIDO DE AUDIO - PipeWire")
print("="*60)

# Inicializar PyAudio
pa = pyaudio.PyAudio()

# Buscar dispositivo PipeWire
pipewire_idx = None
for i in range(pa.get_device_count()):
    info = pa.get_device_info_by_index(i)
    name = info['name'].lower()
    if ('pipewire' in name or 'default' in name) and info['maxOutputChannels'] > 0:
        pipewire_idx = i
        print(f"\n✓ Dispositivo encontrado: [{i}] {info['name']}")
        print(f"  Canales: {info['maxOutputChannels']}")
        print(f"  Sample rate: {int(info['defaultSampleRate'])} Hz")
        break

if pipewire_idx is None:
    print("\n❌ No se encontró dispositivo PipeWire")
    pa.terminate()
    exit(1)

# Generar tono de prueba
print("\n🔊 Generando tono de 440 Hz (nota LA)...")
sample_rate = 24000  # Mismo rate que OpenAI API
duration = 2.0  # segundos
frequency = 440  # Hz

t = np.linspace(0, duration, int(sample_rate * duration))
audio = (np.sin(2 * np.pi * frequency * t) * 10000).astype(np.int16)

# Abrir stream de salida
print(f"🎵 Abriendo dispositivo [{pipewire_idx}] a {sample_rate} Hz...")
try:
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        output=True,
        output_device_index=pipewire_idx,
        frames_per_buffer=1024
    )
    
    print("▶️  Reproduciendo... (deberías escucharlo en el JBL)")
    stream.write(audio.tobytes())
    time.sleep(0.5)
    
    stream.stop_stream()
    stream.close()
    print("\n✅ ¡Audio reproducido exitosamente!")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    
pa.terminate()
print("="*60)
