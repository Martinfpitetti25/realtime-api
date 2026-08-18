import cv2


TARGET_WIDTH  = 720
TARGET_HEIGHT = 480
BUFFER_SIZE   = 4
# Fracción mínima de la imagen (desde abajo) que debe tener datos reales.
# Si la mitad inferior es completamente negra, el frame está partido (torn).
VALID_BOTTOM_THRESHOLD = 0.15  # 15% del alto mínimo con datos


def _is_frame_complete(frame) -> bool:
    """Return True if the frame has real data in both top and bottom halves."""
    h = frame.shape[0]
    bottom = frame[h // 2 :, :, :]
    return bottom.std() > VALID_BOTTOM_THRESHOLD * 10  # std > ~1.5


def find_available_cameras(max_index=5):
    """Returns a list of available camera indices."""
    available = []
    for i in range(max_index):
        # V4L2 evita que GStreamer intervenga y corrompa frames
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            ret, _ = cap.read()
            cap.release()
            if ret:
                available.append(i)
    return available


def preview_camera(index):
    """Opens a live preview window for the given camera index. Press 'q' to quit."""
    # Forzar V4L2: evita que GStreamer intervenga y corrompa frames
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera {index}")
        return

    # Resolución nativa del capturador AV USB (NTSC 720x480).
    # 640x480 causaba mismatch de stride en YUYV → artefactos de color.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  TARGET_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TARGET_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # Buffer 4: necesario para YUYV 720x480 sin frames partidos
    cap.set(cv2.CAP_PROP_BUFFERSIZE, BUFFER_SIZE)

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    print(f"  Resolution : {width}x{height} @ {fps:.1f} fps  (V4L2, buffer={BUFFER_SIZE})")

    # Warmup: el capturador AV analógico necesita varios frames para
    # sincronizarse con la señal. Además esperamos hasta obtener un frame
    # completo (sin la mitad inferior negra = "torn frame").
    print("  Warming up capture card...", end="", flush=True)
    for _ in range(40):
        cap.read()

    # Esperar frame completo antes de abrir ventana (máx 60 intentos extra)
    for attempt in range(60):
        ret, probe = cap.read()
        if ret and _is_frame_complete(probe):
            break
        if attempt == 59:
            print(" [WARN] could not get a complete frame, opening anyway.")
    else:
        pass
    print(" done.")
    print(f"  Press 'q' in the preview window to close.")

    window_name = f"Camera {index} Preview"
    last_good_frame = probe if ret else None

    while True:
        ret, frame = cap.read()
        if not ret:
            print(f"[ERROR] Failed to read frame from camera {index}")
            break

        # Descartar frames partidos: mostrar el último frame bueno en su lugar
        if _is_frame_complete(frame):
            last_good_frame = frame
        elif last_good_frame is not None:
            frame = last_good_frame

        cv2.putText(
            frame,
            f"Camera {index} | {width}x{height} | Press Q to quit",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.imshow(window_name, frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    print("Scanning for available cameras...")
    cameras = find_available_cameras()

    if not cameras:
        print("[FAIL] No cameras found.")
    else:
        print(f"[OK] Found {len(cameras)} camera(s): indices {cameras}")
        for idx in cameras:
            print(f"\n--- Camera {idx} ---")
            preview_camera(idx)
