"""
Test Camera Tracking - Versión con OpenCV puro
Detecta rostros usando Haar Cascades (sin mediapipe)
Compatible con todas las versiones de Python
"""

import cv2
import time

# Cargar el clasificador Haar Cascade para detección de rostros
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Open camera - 0 para webcam por defecto, prueba con 1 si no funciona
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: No se pudo abrir la cámara")
    print("Intenta cambiar el índice en cv2.VideoCapture(0) a 1 o 2")
    exit()

# Get camera resolution
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
center_x = frame_width // 2
center_y = frame_height // 2

print(f"Cámara iniciada: {frame_width}x{frame_height}")
print("Presiona ESC para salir")

# Contador de FPS
fps_start_time = time.time()
fps_counter = 0
fps = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("Error: No se pudo leer el frame")
        break

    # Flip horizontal para efecto espejo (más natural)
    frame = cv2.flip(frame, 1)

    # Convertir a escala de grises para detección
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Detectar rostros
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(50, 50),
        flags=cv2.CASCADE_SCALE_IMAGE
    )

    error_x = None
    error_y = None
    faces_detected = len(faces)

    # Procesar cada rostro detectado
    for (x, y, w, h) in faces:
        # Dibujar rectángulo alrededor del rostro
        cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
        
        # Calcular el centro del rostro
        face_x = x + w // 2
        face_y = y + h // 2
        
        # Calcular error desde el centro de la imagen
        error_x = center_x - face_x
        error_y = center_y - face_y
        
        # Dibujar círculo en el centro del rostro
        cv2.circle(frame, (face_x, face_y), 8, (0, 0, 255), -1)
        
        # Dibujar línea desde el centro de la imagen al centro del rostro
        cv2.line(frame, (center_x, center_y), (face_x, face_y), (255, 0, 0), 2)
        
        # Solo procesamos el primer rostro detectado
        break

    # Dibujar punto central de referencia
    cv2.drawMarker(frame, (center_x, center_y), (0, 255, 0), cv2.MARKER_CROSS, 30, 3)

    # Calcular FPS
    fps_counter += 1
    if time.time() - fps_start_time >= 1.0:
        fps = fps_counter
        fps_counter = 0
        fps_start_time = time.time()

    # Mostrar información en pantalla
    y_offset = 30
    cv2.putText(frame, f"FPS: {fps}", (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    y_offset += 35
    cv2.putText(frame, f"Rostros detectados: {faces_detected}", (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    if error_x is not None and error_y is not None:
        y_offset += 35
        direction_x = "Izquierda" if error_x > 0 else "Derecha"
        direction_y = "Arriba" if error_y > 0 else "Abajo"
        
        cv2.putText(frame, f"Error X: {error_x} px ({direction_x})", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        y_offset += 30
        cv2.putText(frame, f"Error Y: {error_y} px ({direction_y})", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Mostrar el desplazamiento como porcentaje
        y_offset += 30
        percent_x = abs(error_x) / (frame_width / 2) * 100
        percent_y = abs(error_y) / (frame_height / 2) * 100
        cv2.putText(frame, f"Desplazamiento: {percent_x:.1f}% H, {percent_y:.1f}% V", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
    else:
        y_offset += 35
        cv2.putText(frame, "No se detecta rostro", (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # Instrucciones
    cv2.putText(frame, "Presiona ESC para salir", (10, frame_height - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # Mostrar ventana
    cv2.imshow('Test Camera Tracking - OpenCV Face Detection', frame)

    if cv2.waitKey(1) & 0xFF == 27:  # ESC para salir
        break

cap.release()
cv2.destroyAllWindows()

print("\nCámara cerrada. ¡Hasta luego!")
