#!/usr/bin/env python3
"""
Test rápido de auto-detección - Sin dependencias complejas
"""
import sys
import os

# Agregar path del proyecto
sys.path.insert(0, '/home/cluster/Projects/Realtime-IA')

# Solo importar lo necesario
import pyaudio
from utils.audio_device_manager import AudioDeviceManager

print("\n" + "="*70)
print("🎵 TEST DE AUTO-DETECCIÓN DE DISPOSITIVOS DE AUDIO")
print("="*70 + "\n")

try:
    # Crear manager (sin AudioEnhancer para evitar scipy)
    manager = AudioDeviceManager()
    
    print("📋 DISPOSITIVOS DETECTADOS:\n")
    
    # Obtener nombres formateados
    input_names, output_names = manager.get_device_names()
    
    print("🎤 ENTRADA (Micrófono):")
    for name in input_names:
        print(f"  {name}")
    
    print("\n🔊 SALIDA (Altavoz):")
    for name in output_names:
        print(f"  {name}")
    
    print("\n" + "="*70)
    print("🤖 AUTO-DETECCIÓN INTELIGENTE")
    print("="*70 + "\n")
    
    # Auto-detectar
    best_input, best_output = manager.auto_detect_best_devices()
    
    # Obtener info de los seleccionados
    devices = manager.get_devices()
    
    print("\n✅ DISPOSITIVOS SELECCIONADOS AUTOMÁTICAMENTE:\n")
    
    if best_input is not None:
        for dev in devices["input"]:
            if dev["index"] == best_input:
                print(f"  🎤 Micrófono: {dev['name']}")
                print(f"     Tipo: {dev['device_type'].upper()}")
                print(f"     Índice: {dev['index']}")
    else:
        print("  ❌ No se detectó micrófono")
    
    if best_output is not None:
        for dev in devices["output"]:
            if dev["index"] == best_output:
                print(f"\n  🔊 Altavoz: {dev['name']}")
                print(f"     Tipo: {dev['device_type'].upper()}")
                print(f"     Índice: {dev['index']}")
    else:
        print("  ❌ No se detectó altavoz")
    
    # Guardar configuración
    print("\n💾 Guardando configuración...")
    manager.set_preferred_devices(best_input, best_output)
    
    # Verificar que se guardó
    prefs = manager.get_preferred_devices()
    print(f"   ✓ Input guardado: {prefs['input']}")
    print(f"   ✓ Output guardado: {prefs['output']}")
    
    print("\n✅ Test completado exitosamente")
    print(f"Configuración guardada en: {manager.CONFIG_FILE}\n")
    
    manager.cleanup()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
