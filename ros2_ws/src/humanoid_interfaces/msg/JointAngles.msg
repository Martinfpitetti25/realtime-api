# Custom ROS 2 Message for Actuator Servo Joint Commands
std_msgs/Header header

float32 neck_yaw       # Neck horizontal yaw angle (degrees or radians)
float32 neck_pitch     # Neck vertical pitch angle (degrees or radians)
float32 eye_left_h     # Left eye horizontal angle
float32 eye_left_v     # Left eye vertical angle
float32 eye_right_h    # Right eye horizontal angle
float32 eye_right_v    # Right eye vertical angle
float32 eyelid_upper   # Upper eyelid angle (0 = closed, 100 = open)
float32 eyelid_lower   # Lower eyelid angle
float32 mouth_aperture # Mouth servo position for speech articulation
