#!/usr/bin/env python3
"""
Test script to diagnose camera detection issues
"""
import cv2
import sys

def test_camera(index):
    """Test if a camera at a given index can be opened and read"""
    print(f"\n🔍 Testing camera index {index}...")
    
    cap = cv2.VideoCapture(index)
    
    if not cap.isOpened():
        print(f"❌ Cannot open camera at index {index}")
        return False
    
    print(f"✅ Camera {index} opened successfully")
    
    # Try to read a frame
    ret, frame = cap.read()
    
    if not ret:
        print(f"❌ Cannot read frame from camera {index}")
        cap.release()
        return False
    
    # Get camera properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    
    print(f"✅ Camera {index} is working!")
    print(f"   Resolution: {width}x{height}")
    print(f"   FPS: {fps}")
    print(f"   Frame shape: {frame.shape}")
    
    cap.release()
    return True

def main():
    print("=" * 60)
    print("Camera Detection Diagnostic Tool")
    print("=" * 60)
    
    # Test cameras 0-4
    working_cameras = []
    for i in range(5):
        if test_camera(i):
            working_cameras.append(i)
    
    print("\n" + "=" * 60)
    print("📊 Summary:")
    if working_cameras:
        print(f"✅ Found {len(working_cameras)} working camera(s): {working_cameras}")
        print(f"   Recommended camera index: {working_cameras[0]}")
    else:
        print("❌ No working cameras found!")
        print("\nPossible issues:")
        print("  1. Camera not connected properly")
        print("  2. Permission issues (user not in 'video' group)")
        print("  3. Another application is using the camera")
        print("  4. OpenCV not installed or compiled without video support")
    print("=" * 60)

if __name__ == "__main__":
    main()
