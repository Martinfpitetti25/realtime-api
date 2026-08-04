# Custom ROS 2 Message for Vision Target Position Tracking
std_msgs/Header header

bool detected          # True if target/face is detected
float32 target_x       # Target center X (pixels or normalized)
float32 target_y       # Target center Y (pixels or normalized)
float32 frame_width    # Image width
float32 frame_height   # Image height
float32 confidence     # Detection confidence score (0.0 to 1.0)
string target_class    # Class name (e.g. "face", "person", "cup")
