# 🤖 Realtime Multimodal Humanoid Assistant

An end-to-end real-time conversational humanoid robot platform integrating **OpenAI Realtime API (WebSockets)**, **High-Speed Vision PID Servo Actuation**, **YOLO & GPT-4 Multimodal Vision**, and a production **ROS 2 C++ / FreeRTOS** architecture.

---

## 🏛️ Project Architecture

```
realtime-api/
├── main.py                       # Main application entry point launcher
├── 05_gui_chat.py                # Graphical User Interface & WebSockets pipeline
├── hardware/                     # Thread-safe hardware controllers & SharedState
│   ├── shared_state.py           # Thread-safe Singleton state container
│   ├── eye_tracker_thread.py     # 6-DOF Eye & Neck PID control loop (YuNet 30 FPS)
│   ├── mouth_controller.py       # Speech-synced PWM mouth servo controller
│   ├── camera_service.py         # YOLOv8 local object detection service
│   └── gpt4_vision_service.py    # On-demand GPT-4 Vision service with caching
├── utils/                        # Audio device management & noise gate enhancers
├── models/                       # Computer vision models (YOLOv8, YuNet ONNX)
├── ros2_ws/                      # Production ROS 2 C++ & FreeRTOS colcon workspace
│   └── src/
│       ├── humanoid_interfaces/  # Custom ROS 2 msg definitions (TargetPosition, JointAngles)
│       ├── humanoid_control/     # C++ 100Hz PID tracking node (rclcpp)
│       ├── humanoid_description/ # URDF 3D robot kinematics model
│       └── humanoid_firmware/    # ESP32 dual-core FreeRTOS / micro-ROS driver
├── scripts/                      # Startup, configuration, and helper scripts
├── tests/                        # Automated unit & integration tests
├── docs/                         # System architecture & documentation
└── legacy/                       # Historical prototypes & hardware experiment archives
```

---

## 🚀 Quickstart

### 1. Requirements
- Python 3.10+
- OpenAL / PortAudio (`pyaudio`)
- OpenCV & NumPy

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/Martinfpitetti25/realtime-api.git
cd realtime-api

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=your_api_key
```

### 3. Run Application
```bash
python main.py
```

---

## ⚙️ ROS 2 C++ Workspace Build (`ros2_ws`)

```bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash

# Run the 100Hz C++ Eye Tracking Node
ros2 run humanoid_control eye_tracking_node
```

---

## 📄 License
MIT License
