"""
Test Camera Tracking - Versión simplificada para prueba con webcam
Detecta rostros y muestra el error de posición respecto al centro de la imagen
No requiere hardware conectado
"""

import cv2
import mediapipe as mp
import time

# Mediapipe setup
mp_face_detection = mp.solutions.face_detection
mp_drawing = mp.solutions.drawing_utils

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

with mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5) as face_detection:
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("Error: No se pudo leer el frame")
            break

        # Flip horizontal para efecto espejo (más natural)
        frame = cv2.flip(frame, 1)

        # Convert BGR to RGB for mediapipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb_frame)

        error_x = None
        error_y = None
        faces_detected = 0

        # Draw detections and calculate offsets
        if results.detections:
            faces_detected = len(results.detections)
            for detection in results.detections:
                # Draw bounding box
                mp_drawing.draw_detection(frame, detection)

                # Get bounding box center
                bbox = detection.location_data.relative_bounding_box
                face_x = int((bbox.xmin + bbox.width / 2) * frame_width)
                face_y = int((bbox.ymin + bbox.height / 2) * frame_height)

                # Calculate error from frame center
                error_x = center_x - face_x
                error_y = center_y - face_y

                # Draw a marker at the detected face center
                cv2.circle(frame, (face_x, face_y), 8, (0, 0, 255), -1)
                
                # Draw line from center to face
                cv2.line(frame, (center_x, center_y), (face_x, face_y), (255, 0, 0), 2)

        # Draw center crosshair
        cv2.drawMarker(frame, (center_x, center_y), (0, 255, 0), cv2.MARKER_CROSS, 30, 3)

        # Calculate FPS
        fps_counter += 1
        if time.time() - fps_start_time >= 1.0:
            fps = fps_counter
            fps_counter = 0
            fps_start_time = time.time()

        # Show info on screen
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
        else:
            y_offset += 35
            cv2.putText(frame, "No se detecta rostro", (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Instructions
        cv2.putText(frame, "Presiona ESC para salir", (10, frame_height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # Show window
        cv2.imshow('Test Camera Tracking - Face Detection', frame)

        if cv2.waitKey(1) & 0xFF == 27:  # ESC to quit
            break

cap.release()
cv2.destroyAllWindows()

print("\nCámara cerrada. ¡Hasta luego!")
