import cv2


def find_available_cameras(max_index=5):
    """Returns a list of available camera indices."""
    available = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available.append(i)
            cap.release()
    return available


def preview_camera(index):
    """Opens a live preview window for the given camera index. Press 'q' to quit."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f"[ERROR] Could not open camera {index}")
        return

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    print(f"  Resolution : {width}x{height} @ {fps:.1f} fps")
    print(f"  Press 'q' in the preview window to close.")

    window_name = f"Camera {index} Preview"
    while True:
        ret, frame = cap.read()
        if not ret:
            print(f"[ERROR] Failed to read frame from camera {index}")
            break

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
