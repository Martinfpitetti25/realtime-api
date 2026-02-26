#!/usr/bin/env python3
"""
Test simple de audio para diagnosticar problemas
"""
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"

print("=" * 60)
print("TEST DE AUDIO - Diagnóstico")
print("=" * 60)

# 1. Test de importación
print("\n1. Verificando PyAudio...")
try:
    import pyaudio
    print(f"   ✓ PyAudio {pyaudio.__version__} importado correctamente")
except ImportError as e:
    print(f"   ✗ Error importando PyAudio: {e}")
    exit(1)

# 2. Test de inicialización
print("\n2. Inicializando PyAudio...")
try:
    pa = pyaudio.PyAudio()
    print(f"   ✓ PyAudio inicializado")
except Exception as e:
    print(f"   ✗ Error inicializando: {e}")
    exit(1)

# 3. Listar dispositivos
print("\n3. Dispositivos de audio detectados:")
device_count = pa.get_device_count()
print(f"   Total: {device_count} dispositivos\n")

input_devices = []
output_devices = []

for i in range(device_count):
    info = pa.get_device_info_by_index(i)
    name = info['name']
    max_input = info['maxInputChannels']
    max_output = info['maxOutputChannels']
    sample_rate = int(info['defaultSampleRate'])
    
    print(f"   [{i}] {name}")
    print(f"       Entrada: {max_input} canales | Salida: {max_output} canales")
    print(f"       Sample rate: {sample_rate} Hz")
    
    if max_input > 0:
        input_devices.append(i)
        print(f"       🎤 MICRÓFONO disponible")
    if max_output > 0:
        output_devices.append(i)
        print(f"       🔊 PARLANTE disponible")
    print()

# 4. Test de grabación
if input_devices:
    print(f"\n4. Test de GRABACIÓN (dispositivo {input_devices[0]})...")
    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=input_devices[0],
            frames_per_buffer=1024
        )
        print("   Grabando 1 segundo...")
        data = stream.read(1024 * 16)  # 1 segundo a 16kHz
        stream.stop_stream()
        stream.close()
        print(f"   ✓ Grabación exitosa ({len(data)} bytes)")
    except Exception as e:
        print(f"   ✗ Error en grabación: {e}")
else:
    print("\n4. ⚠️  No hay dispositivos de entrada (micrófono)")

# 5. Test de reproducción
if output_devices:
    # Intentar con dispositivo PipeWire/default primero
    test_device = None
    for dev_idx in output_devices:
        dev_info = pa.get_device_info_by_index(dev_idx)
        if 'pipewire' in dev_info['name'].lower() or 'default' in dev_info['name'].lower():
            test_device = dev_idx
            break
    
    if test_device is None:
        test_device = output_devices[0]
    
    print(f"\n5. Test de REPRODUCCIÓN (dispositivo {test_device}: {pa.get_device_info_by_index(test_device)['name']})...")
    try:
        import numpy as np
        # Generar tono de 440 Hz (nota LA)
        sample_rate = 24000  # Usar 24kHz como el API de OpenAI
        duration = 0.5  # segundos
        frequency = 440
        
        t = np.linspace(0, duration, int(sample_rate * duration))
        audio = (np.sin(2 * np.pi * frequency * t) * 10000).astype(np.int16)
        
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            output=True,
            output_device_index=test_device,
            frames_per_buffer=1024
        )
        print("   Reproduciendo tono de 440 Hz...")
        stream.write(audio.tobytes())
        stream.stop_stream()
        stream.close()
        print("   ✓ Reproducción exitosa")
    except Exception as e:
        print(f"   ✗ Error en reproducción: {e}")
else:
    print("\n5. ⚠️  No hay dispositivos de salida (parlantes)")

# 6. Cleanup
pa.terminate()

print("\n" + "=" * 60)
print("RESUMEN:")
print(f"  Dispositivos entrada: {len(input_devices)}")
print(f"  Dispositivos salida: {len(output_devices)}")
if input_devices and output_devices:
    print("  ✓ Sistema de audio funcional")
elif not input_devices and not output_devices:
    print("  ✗ No se detectaron dispositivos de audio")
elif not input_devices:
    print("  ⚠️  Solo salida disponible (sin micrófono)")
else:
    print("  ⚠️  Solo entrada disponible (sin parlantes)")
print("=" * 60)
