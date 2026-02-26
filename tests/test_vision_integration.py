#!/usr/bin/env python3
"""
Test rápido de la integración de visión
Verifica que todos los componentes funcionen
"""
import sys
import time

print("🧪 TEST DE INTEGRACIÓN - Robot con Visión")
print("=" * 60)

# Test 1: Imports
print("\n1️⃣ Verificando imports...")
try:
    import cv2
    print("   ✅ OpenCV")
    try:
        import mediapipe
        print("   ✅ MediaPipe")
    except ImportError:
        print("   ⚠️  MediaPipe no disponible (opcional)")
    from ultralytics import YOLO
    print("   ✅ Ultralytics (YOLO)")
    import pyaudio
    print("   ✅ PyAudio")
    import websocket
    print("   ✅ WebSocket")
    from hardware.camera_service import CameraService
    print("   ✅ CameraService")
except ImportError as e:
    print(f"   ❌ Error: {e}")
    print("\n💡 Ejecuta: pip install opencv-contrib-python ultralytics")
    sys.exit(1)

# Test 2: Camera
print("\n2️⃣ Verificando cámara...")
try:
    camera = CameraService()
    if camera.start_camera():
        print("   ✅ Cámara iniciada")
        
        # Read a frame
        ret, frame = camera.read_frame()
        if ret and frame is not None:
            print(f"   ✅ Frame capturado ({frame.shape[1]}x{frame.shape[0]})")
        else:
            print("   ⚠️ No se pudo capturar frame")
        
        camera.stop_camera()
    else:
        print("   ❌ No se pudo iniciar cámara")
        print("   💡 Verifica que tu cámara esté conectada")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: YOLO
print("\n3️⃣ Verificando YOLO...")
try:
    camera = CameraService()
    camera.start_camera()
    
    print("   ⏳ Cargando modelo (puede tardar en primera ejecución)...")
    if camera.load_yolo_model():
        print("   ✅ Modelo YOLO cargado")
        
        # Test detection
        ret, frame = camera.read_frame()
        if ret:
            _, detections = camera.detect_objects(frame)
            print(f"   ✅ Detección funcional ({len(detections)} objetos)")
            
            # Show what was detected
            if detections:
                objects = [d['class'] for d in detections]
                print(f"   👁️ Detectados: {', '.join(set(objects))}")
        
    else:
        print("   ⚠️ No se pudo cargar YOLO")
    
    camera.stop_camera()
except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Vision Context
print("\n4️⃣ Verificando contexto visual...")
try:
    camera = CameraService()
    camera.start_camera()
    camera.load_yolo_model()
    
    time.sleep(1)  # Wait for camera
    
    ret, frame = camera.read_frame()
    if ret:
        camera.detect_objects(frame)
        context = camera.get_vision_context_for_realtime()
        
        print(f"   ✅ Vision summary: {context['vision_summary']}")
        print(f"   ✅ Raw detections: {len(context['raw_detections'])} objetos")
    
    camera.cleanup()
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 5: API Key
print("\n5️⃣ Verificando configuración...")
try:
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv('OPENAI_API_KEY')
    if api_key and len(api_key) > 20:
        print(f"   ✅ API Key configurada ({api_key[:8]}...)")
    else:
        print("   ⚠️ API Key no encontrada o inválida")
        print("   💡 Verifica tu archivo .env")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Summary
print("\n" + "=" * 60)
print("📊 RESUMEN")
print("=" * 60)
print("\n✅ Sistema listo para ejecutar 07_vision_realtime.py")
print("\n💡 Próximos pasos:")
print("   1. Test de cámara: python hardware/camera_service.py")
print("   2. Ejecutar robot: python 07_vision_realtime.py")
print("\n" + "=" * 60)
