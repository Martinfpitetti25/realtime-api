#!/usr/bin/env python3
"""
Test de Auto-detección de Dispositivos de Audio
"""
import sys
sys.path.insert(0, '/home/cluster/Projects/Realtime-IA')

from utils.audio_device_manager import AudioDeviceManager

print("\n" + "="*70)
print("🎵 TEST DE AUTO-DETECCIÓN DE DISPOSITIVOS DE AUDIO")
print("="*70 + "\n")

# Crear manager
manager = AudioDeviceManager()

print("📋 TODOS LOS DISPOSITIVOS DISPONIBLES:\n")
devices = manager.get_devices()

print("🎤 ENTRADA (Micrófono):")
for dev in devices["input"]:
    tipo = dev["device_type"].upper()
    default = " [DEFAULT]" if dev["is_default_input"] else ""
    print(f"  [{dev['index']}] {dev['name']}")
    print(f"      Tipo: {tipo} | Canales: {dev['max_input_channels']} | Rate: {int(dev['default_sample_rate'])} Hz{default}")

print("\n🔊 SALIDA (Altavoz):")
for dev in devices["output"]:
    tipo = dev["device_type"].upper()
    default = " [DEFAULT]" if dev["is_default_output"] else ""
    print(f"  [{dev['index']}] {dev['name']}")
    print(f"      Tipo: {tipo} | Canales: {dev['max_output_channels']} | Rate: {int(dev['default_sample_rate'])} Hz{default}")

print("\n" + "="*70)
print("🤖 AUTO-DETECCIÓN DE MEJORES DISPOSITIVOS")
print("="*70 + "\n")

best_input, best_output = manager.auto_detect_best_devices()

print(f"\n✅ RESULTADO AUTO-DETECCIÓN:")
print(f"  🎤 Input detectado: [{best_input}]")
print(f"  🔊 Output detectado: [{best_output}]")

if best_input is not None:
    for dev in devices["input"]:
        if dev["index"] == best_input:
            print(f"\n  → Micrófono: {dev['name']} ({dev['device_type'].upper()})")

if best_output is not None:
    for dev in devices["output"]:
        if dev["index"] == best_output:
            print(f"  → Altavoz: {dev['name']} ({dev['device_type'].upper()})")

print("\n" + "="*70)
print("📝 NOMBRES PARA GUI")
print("="*70 + "\n")

input_names, output_names = manager.get_device_names()

print("🎤 Nombres de entrada:")
for name in input_names:
    print(f"  {name}")

print("\n🔊 Nombres de salida:")
for name in output_names:
    print(f"  {name}")

print("\n✅ Test completado\n")

manager.cleanup()
