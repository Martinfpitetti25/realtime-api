"""
Camera and YOLO detection service for Realtime API integration
Optimized for low latency and CPU usage
"""
import cv2
import numpy as np
from ultralytics import YOLO
from typing import Optional, Tuple, List, Dict
import threading
import queue
import time
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.logger import get_logger

logger = get_logger(__name__)


class CameraService:
    """Service for managing webcam capture and YOLO detection"""
    
    def __init__(self):
        self.camera = None
        self.camera_index = None
        self.is_running = False
        self.yolo_model = None
        self.model_loaded = False
        self.last_detections = []  # Store last detections
        
        # Thread-safe queues for async operation
        self.frame_queue = queue.Queue(maxsize=2)
        self.detection_queue = queue.Queue(maxsize=1)
        self.capture_thread = None
        self.detection_thread = None
        
        # Configurable parameters (optimized for Realtime API)
        self.confidence = 0.5
        self.target_width = 640
        self.target_height = 480
        self.yolo_enabled = True
        
        # Performance optimization
        self.detection_fps = 3  # Only 3 detections per second to save CPU
        self.skip_frames = 10   # Process 1 out of 10 frames
        self.frame_counter = 0
        
    def find_camera(self, max_cameras=5) -> Optional[int]:
        """
        Find available camera by testing indices
        
        Args:
            max_cameras: Maximum number of camera indices to test
            
        Returns:
            Camera index if found, None otherwise
        """
        logger.info("🔍 Buscando cámaras disponibles...")
        
        for index in range(max_cameras):
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    logger.info(f"✅ Cámara encontrada en índice {index}")
                    return index
        
        logger.warning("❌ No se encontró ninguna cámara")
        return None
    
    def start_camera(self, camera_index: Optional[int] = None) -> bool:
        """
        Start camera capture
        
        Args:
            camera_index: Specific camera index to use. If None, will search
            
        Returns:
            True if camera started successfully
        """
        if self.is_running:
            logger.warning("⚠️ La cámara ya está en ejecución")
            return True
        
        # Find camera if index not provided
        if camera_index is None:
            camera_index = self.find_camera()
            if camera_index is None:
                logger.error("❌ No se pudo encontrar ninguna cámara")
                return False
        
        self.camera_index = camera_index
        self.camera = cv2.VideoCapture(camera_index)
        
        if not self.camera.isOpened():
            logger.error(f"❌ No se pudo abrir la cámara en índice {camera_index}")
            return False
        
        # Set camera properties for better performance
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)
        self.camera.set(cv2.CAP_PROP_FPS, 30)
        
        self.is_running = True
        logger.info(f"✅ Cámara iniciada ({self.target_width}x{self.target_height}@30fps)")
        return True
    
    def stop_camera(self):
        """Stop camera capture and cleanup"""
        self.is_running = False
        
        # Stop threads
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2)
        if self.detection_thread and self.detection_thread.is_alive():
            self.detection_thread.join(timeout=2)
        
        # Release camera
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        
        logger.info("✅ Cámara detenida")
    
    def is_available(self) -> bool:
        """Check if camera is available and running"""
        return self.is_running and self.camera is not None and self.camera.isOpened()
    
    def load_yolo_model(self, model_name: str = "yolov8m.pt") -> bool:
        """
        Load YOLO model (with caching to avoid reloading)
        Now defaults to medium model for better accuracy
        
        Args:
            model_name: Name of the YOLO model to load
            
        Returns:
            True if model loaded successfully
        """
        try:
            # Check if model is already loaded
            if self.model_loaded and self.yolo_model is not None:
                logger.info("ℹ️ Modelo YOLO ya está cargado")
                return True
            
            # Buscar modelo en la carpeta models/ primero
            model_path = model_name
            models_dir = Path(__file__).parent.parent / "models"
            if models_dir.exists():
                model_in_dir = models_dir / model_name
                if model_in_dir.exists():
                    model_path = str(model_in_dir)
            
            logger.info(f"⏳ Cargando modelo YOLO: {model_path}")
            self.yolo_model = YOLO(model_path)
            
            # Warm up model with dummy inference for faster first detection
            dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
            _ = self.yolo_model(dummy_frame, verbose=False)
            
            self.model_loaded = True
            logger.info("✅ Modelo YOLO cargado y listo")
            return True
        except Exception as e:
            logger.error(f"❌ Error cargando modelo YOLO: {str(e)}")
            self.model_loaded = False
            return False
    
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read a frame from the camera
        
        Returns:
            Tuple of (success, frame)
        """
        if not self.is_running or self.camera is None:
            return False, None
        
        ret, frame = self.camera.read()
        return ret, frame
    
    def detect_objects(self, frame: np.ndarray, confidence: float = 0.5) -> Tuple[np.ndarray, List[Dict]]:
        """
        Run YOLO detection on a frame (optimized for low CPU usage)
        
        Args:
            frame: Input image frame
            confidence: Minimum confidence threshold
            
        Returns:
            Tuple of (annotated frame, list of detections)
        """
        if not self.model_loaded or self.yolo_model is None:
            return frame, []
        
        try:
            # Run inference with optimizations
            results = self.yolo_model(
                frame, 
                conf=confidence, 
                verbose=False,
                max_det=20,  # Limit detections for speed
                half=False   # FP16 for GPU if available
            )
            
            # Get annotated frame
            annotated_frame = results[0].plot()
            
            # Extract detection information
            detections = []
            if results and len(results) > 0:
                result = results[0]
                boxes = result.boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        detection = {
                            'class': result.names[int(box.cls[0])],
                            'confidence': float(box.conf[0]),
                            'bbox': box.xyxy[0].tolist()
                        }
                        detections.append(detection)
            
            # Store last detections
            self.last_detections = detections
            
            return annotated_frame, detections
        
        except Exception as e:
            logger.error(f"❌ Error en detección YOLO: {str(e)}")
            return frame, []
    
    def get_last_detections(self) -> List[Dict]:
        """Get the last detections from YOLO"""
        return self.last_detections.copy()
    
    def get_vision_context_for_realtime(self, detailed: bool = True) -> Dict:
        """
        Get vision context optimized for Realtime API with enhanced details
        Returns a detailed summary suitable for LLM context
        
        Args:
            detailed: If True, includes positions, sizes, and confidence
        
        Returns:
            Dict with 'vision_summary' (str) and 'raw_detections' (list)
        """
        detections = self.get_last_detections()
        
        if not detections:
            return {
                'vision_summary': 'No objects detected',
                'raw_detections': []
            }
        
        # Count objects by class
        object_counts = {}
        for detection in detections:
            obj_class = detection['class']
            object_counts[obj_class] = object_counts.get(obj_class, 0) + 1
        
        if not detailed:
            # Simple summary
            summary_parts = []
            for obj_class, count in sorted(object_counts.items()):
                if count == 1:
                    summary_parts.append(f"1 {obj_class}")
                else:
                    summary_parts.append(f"{count} {obj_class}s")
            vision_summary = "I can see: " + ", ".join(summary_parts)
        else:
            # Detailed summary with positions and attributes
            summary_lines = []
            
            # Group by class for better organization
            by_class = {}
            for detection in detections:
                obj_class = detection['class']
                if obj_class not in by_class:
                    by_class[obj_class] = []
                by_class[obj_class].append(detection)
            
            # Frame dimensions for relative positions
            frame_width = 640
            frame_height = 480
            
            for obj_class, items in sorted(by_class.items()):
                if len(items) == 1:
                    det = items[0]
                    bbox = det['bbox']
                    conf = det['confidence']
                    
                    # Calculate position and size
                    x_center = (bbox[0] + bbox[2]) / 2
                    y_center = (bbox[1] + bbox[3]) / 2
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    
                    # Position description
                    if x_center < frame_width / 3:
                        pos_x = "left"
                    elif x_center < 2 * frame_width / 3:
                        pos_x = "center"
                    else:
                        pos_x = "right"
                    
                    if y_center < frame_height / 3:
                        pos_y = "top"
                    elif y_center < 2 * frame_height / 3:
                        pos_y = "middle"
                    else:
                        pos_y = "bottom"
                    
                    # Size description
                    area = width * height
                    total_area = frame_width * frame_height
                    area_ratio = area / total_area
                    
                    if area_ratio > 0.4:
                        size = "large"
                    elif area_ratio > 0.15:
                        size = "medium"
                    else:
                        size = "small"
                    
                    # Confidence level
                    if conf > 0.9:
                        conf_desc = "very clear"
                    elif conf > 0.7:
                        conf_desc = "clear"
                    else:
                        conf_desc = "detected"
                    
                    summary_lines.append(f"- {size} {obj_class} ({conf_desc}) at {pos_y}-{pos_x}")
                else:
                    # Multiple objects of same class
                    summary_lines.append(f"- {len(items)} {obj_class}s")
            
            vision_summary = "Vision Details:\n" + "\n".join(summary_lines)
        
        return {
            'vision_summary': vision_summary,
            'raw_detections': detections,
            'object_counts': object_counts
        }
    
    def start_async_detection(self):
        """
        Start async detection loop in background thread
        Optimized for Realtime API - low CPU usage
        """
        if not self.is_available() or not self.model_loaded:
            logger.warning("⚠️ Cámara o modelo YOLO no disponibles")
            return False
        
        self.detection_thread = threading.Thread(
            target=self._detection_loop,
            daemon=True
        )
        self.detection_thread.start()
        logger.info(f"✅ Detección async iniciada ({self.detection_fps} FPS)")
        return True
    
    def _detection_loop(self):
        """Background thread for YOLO detection"""
        last_detection_time = 0
        detection_interval = 1.0 / self.detection_fps
        
        while self.is_running:
            current_time = time.time()
            
            # Throttle detection rate
            if current_time - last_detection_time < detection_interval:
                time.sleep(0.05)
                continue
            
            # Read frame
            ret, frame = self.read_frame()
            if not ret or frame is None:
                time.sleep(0.1)
                continue
            
            # Skip frames for performance
            self.frame_counter += 1
            if self.frame_counter % self.skip_frames != 0:
                continue
            
            # Run detection
            if self.yolo_enabled:
                try:
                    _, detections = self.detect_objects(frame, self.confidence)
                    last_detection_time = current_time
                except Exception as e:
                    logger.error(f"❌ Error en detección: {e}")
            
            time.sleep(0.01)
    
    def get_frame_with_detections(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Get current frame with YOLO detections drawn
        Useful for debugging/preview
        
        Returns:
            Tuple of (success, annotated_frame)
        """
        ret, frame = self.read_frame()
        if not ret or frame is None:
            return False, None
        
        if self.yolo_enabled and self.model_loaded:
            annotated_frame, _ = self.detect_objects(frame, self.confidence)
            return True, annotated_frame
        
        return True, frame
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop_camera()
        logger.info("✅ Recursos de cámara liberados")


# Test code
if __name__ == "__main__":
    print("=" * 60)
    print("🎥 TEST: Camera Service con YOLO")
    print("=" * 60)
    
    camera = CameraService()
    
    # Start camera
    if not camera.start_camera():
        print("❌ Error iniciando cámara")
        exit(1)
    
    # Load YOLO
    if not camera.load_yolo_model():
        print("❌ Error cargando YOLO")
        camera.stop_camera()
        exit(1)
    
    print("\n✅ Camera service listo")
    print("📸 Capturando frames (presiona 'q' para salir)...")
    
    try:
        while True:
            ret, frame = camera.get_frame_with_detections()
            
            if ret and frame is not None:
                # Show frame
                cv2.imshow('Camera + YOLO', frame)
                
                # Show vision context
                context = camera.get_vision_context_for_realtime()
                print(f"\r{context['vision_summary']:<60}", end='', flush=True)
            
            # Exit on 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Interrumpido por usuario")
    
    finally:
        camera.cleanup()
        cv2.destroyAllWindows()
        print("\n✅ Test completado")
