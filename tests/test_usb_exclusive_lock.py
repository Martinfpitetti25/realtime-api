#!/usr/bin/env python3
"""
Test de Diagnóstico: USB Exclusive Lock Problem
Verifica si PyAudio está bloqueando el acceso al dispositivo USB
"""
import pyaudio
import time
import subprocess
import sys

print("=" * 70)
print("🔍 DIAGNÓSTICO: USB Audio Exclusive Lock")
print("=" * 70)

# Test 1: Verificar dispositivos
print("\n📋 TEST 1: Dispositivos disponibles")
print("-" * 70)

p = pyaudio.PyAudio()
device_count = p.get_device_count()

print(f"Total dispositivos: {device_count}\n")

usb_device = None
pipewire_device = None
default_device = None

for i in range(device_count):
    try:
        info = p.get_device_info_by_index(i)
        name = info['name']
        is_output = info['maxOutputChannels'] > 0
        
        if is_output:
            print(f"[{i}] {name}")
            print(f"    Canales salida: {info['maxOutputChannels']}")
            print(f"    Sample rate: {info['defaultSampleRate']}")
            
            # Identificar dispositivos clave
            if 'USB' in name or 'GeneralPlus' in name.lower():
                usb_device = i
                print(f"    ⚠️ DISPOSITIVO USB IDENTIFICADO")
            if 'pipewire' in name.lower():
                pipewire_device = i
                print(f"    ✅ DISPOSITIVO PIPEWIRE")
            if 'default' in name.lower():
                default_device = i
                print(f"    ✅ DISPOSITIVO DEFAULT")
            print()
    except:
        pass

# Test 2: Verificar device actual
print("\n📋 TEST 2: Dispositivo por defecto")
print("-" * 70)
try:
    default_info = p.get_default_output_device_info()
    print(f"Default output: [{default_info['index']}] {default_info['name']}")
    print(f"Sample rate: {default_info['defaultSampleRate']}")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: Verificar qué backend usa PyAudio
print("\n📋 TEST 3: Backend de PyAudio")
print("-" * 70)
print(f"Host API Count: {p.get_host_api_count()}")
for i in range(p.get_host_api_count()):
    api = p.get_host_api_info_by_index(i)
    default_marker = " ⭐ [DEFAULT]" if i == p.get_default_host_api_info()['index'] else ""
    print(f"  [{i}] {api['name']} - {api['deviceCount']} devices{default_marker}")

# Test 4: Intentar abrir USB sin especificar device (debería usar multiplexado)
print("\n📋 TEST 4: Abrir stream SIN especificar device")
print("-" * 70)
try:
    stream = p.open(
        format=pyaudio.paInt16,
        channels=2,
        rate=48000,
        output=True,
        frames_per_buffer=1024
    )
    print("✅ Stream abierto sin especificar device (usa default)")
    
    # Verificar qué dispositivo se está usando
    result = subprocess.run(['fuser', '-v', '/dev/snd/pcmC0D0p'], 
                          capture_output=True, text=True)
    if 'python' in result.stderr.lower():
        print("⚠️ Python está usando /dev/snd/pcmC0D0p (hardware USB directo)")
        print("   ESTO ES EL PROBLEMA - Bypass de PipeWire")
    else:
        print("✅ No se detecta uso directo de hardware USB")
        print("   PipeWire está multiplexando correctamente")
    
    stream.close()
    
except Exception as e:
    print(f"❌ Error abriendo stream: {e}")

# Test 5: Abrir USB especificando device index
if usb_device is not None:
    print("\n📋 TEST 5: Abrir stream especificando USB device index")
    print("-" * 70)
    print(f"Intentando abrir device index {usb_device}...")
    
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=2,
            rate=48000,
            output=True,
            output_device_index=usb_device,
            frames_per_buffer=1024
        )
        print(f"✅ Stream abierto en device {usb_device}")
        
        # Verificar acceso exclusivo
        result = subprocess.run(['fuser', '-v', '/dev/snd/pcmC0D0p'], 
                              capture_output=True, text=True)
        if 'python' in result.stderr.lower():
            print("⚠️ CONFIRMADO: Python tiene lock exclusivo en USB")
            print("   Otras aplicaciones NO podrán usar este dispositivo")
            print("   ❌ ESTA ES LA CAUSA DEL BUFFERING")
        
        # Mantener abierto 2 segundos
        print("\n🕐 Manteniendo stream abierto 2 segundos...")
        print("   DURANTE ESTE TIEMPO: Intenta reproducir video en navegador")
        print("   Si hace buffering = PROBLEMA CONFIRMADO")
        time.sleep(2)
        
        stream.close()
        print("✅ Stream cerrado, USB liberado")
        
    except Exception as e:
        print(f"❌ Error: {e}")

# Test 6: Verificar acceso actual al USB
print("\n📋 TEST 6: Estado actual del dispositivo USB")
print("-" * 70)
result = subprocess.run(['fuser', '-v', '/dev/snd/pcmC0D0p', '/dev/snd/pcmC0D0c'], 
                      capture_output=True, text=True)
print("Procesos usando USB audio:")
print(result.stderr if result.stderr else "   Ninguno (USB libre)")

# Test 7: Verificar PipeWire está activo
print("\n📋 TEST 7: Estado de PipeWire")
print("-" * 70)
result = subprocess.run(['systemctl', '--user', 'is-active', 'pipewire'], 
                      capture_output=True, text=True)
pipewire_status = result.stdout.strip()
print(f"PipeWire: {pipewire_status}")

result = subprocess.run(['systemctl', '--user', 'is-active', 'pipewire-pulse'], 
                      capture_output=True, text=True)
pulse_status = result.stdout.strip()
print(f"PipeWire-Pulse: {pulse_status}")

# Cleanup
p.terminate()

# Resumen
print("\n" + "=" * 70)
print("📊 RESUMEN DEL DIAGNÓSTICO")
print("=" * 70)

print("\n🎯 DISPOSITIVOS IDENTIFICADOS:")
print(f"   USB Device: {usb_device if usb_device is not None else 'NO ENCONTRADO'}")
print(f"   PipeWire: {pipewire_device if pipewire_device is not None else 'NO ENCONTRADO'}")
print(f"   Default: {default_device if default_device is not None else 'NO ENCONTRADO'}")

print("\n🎯 BACKEND:")
print(f"   PyAudio usa: {p.get_default_host_api_info()['name']}")

print("\n🎯 PROBLEMA:")
if usb_device is not None:
    print("   ⚠️ PyAudio puede acceder directamente a USB")
    print("   ⚠️ Esto causa LOCK EXCLUSIVO")
    print("   ❌ Navegador NO puede usar USB mientras Python lo tiene abierto")
else:
    print("   ✅ PyAudio no ve hardware USB directo")
    print("   ✅ Multiplexado debería funcionar")

print("\n🎯 SOLUCIÓN:")
print("   1. NO usar output_device_index en pyaudio.open()")
print("   2. Setear PULSE_SERVER para forzar PipeWire")
print("   3. Dejar que PipeWire maneje multiplexado")

print("\n" + "=" * 70)
print("✅ Diagnóstico completo - Ver docs/PROBLEMA_USB_BUFFERING.md")
print("=" * 70)
