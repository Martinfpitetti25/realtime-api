/**
 * @file eye_tracking_node.cpp
 * @brief Implementation of ROS 2 C++ Real-Time PID Eye & Neck Tracking.
 */

#include "humanoid_control/eye_tracking_node.hpp"
#include <algorithm>
#include <cmath>

namespace humanoid_control
{

EyeTrackingNode::EyeTrackingNode(const rclcpp::NodeOptions & options)
: Node("eye_tracking_node", options)
{
  RCLCPP_INFO(this->get_logger(), "Initializing High-Speed C++ Humanoid Eye Tracking Node...");

  // Declare & Get ROS 2 Parameters
  this->declare_parameter<float>("kp", 0.80f);
  this->declare_parameter<float>("ki", 0.01f);
  this->declare_parameter<float>("kd", 0.05f);
  this->declare_parameter<float>("deadband_x", 30.0f);
  this->declare_parameter<float>("deadband_y", 25.0f);

  pid_params_.kp = this->get_parameter("kp").as_double();
  pid_params_.ki = this->get_parameter("ki").as_double();
  pid_params_.kd = this->get_parameter("kd").as_double();
  pid_params_.deadband_x = this->get_parameter("deadband_x").as_double();
  pid_params_.deadband_y = this->get_parameter("deadband_y").as_double();

  // Create Subscriptions (Best-Effort QoS for low latency vision frames)
  rclcpp::QoS vision_qos(10);
  vision_qos.best_effort();

  target_sub_ = this->create_subscription<humanoid_interfaces::msg::TargetPosition>(
    "/vision/target_position", vision_qos,
    std::bind(&EyeTrackingNode::onTargetPositionReceived, this, std::placeholders::_1));

  // Create Publishers (Reliable QoS for joint commands)
  joint_cmd_pub_ = this->create_publisher<humanoid_interfaces::msg::JointAngles>(
    "/actuators/joint_commands", 10);
    
  joint_state_pub_ = this->create_publisher<sensor_msgs::msg::JointState>(
    "/joint_states", 10);

  // 100 Hz Timer Loop (10ms cycle time)
  control_timer_ = this->create_wall_timer(
    std::chrono::milliseconds(10),
    std::bind(&EyeTrackingNode::controlLoopCallback, this));

  RCLCPP_INFO(this->get_logger(), "EyeTrackingNode initialized. PID: Kp=%.2f, Ki=%.2f, Kd=%.2f. Deadband X=%.1fpx",
              pid_params_.kp, pid_params_.ki, pid_params_.kd, pid_params_.deadband_x);
}

void EyeTrackingNode::onTargetPositionReceived(const humanoid_interfaces::msg::TargetPosition::SharedPtr msg)
{
  current_target_ = *msg;
  has_target_ = msg->detected;
  last_target_time_ = this->now();
}

float EyeTrackingNode::computePid(float error, float & integral_acc, float & prev_error,
                                   float kp, float ki, float kd, float i_clamp, float deadband)
{
  // 1. Apply Deadband (Zona Muerta) to suppress mechanical gear backlash & noise jitter
  if (std::abs(error) < deadband) {
    return 0.0f;
  }

  // 2. Proportional Term
  float p_term = kp * error;

  // 3. Integral Term with Anti-Windup Clamping
  integral_acc += error * 0.01f; // dt = 10ms
  integral_acc = std::clamp(integral_acc, -i_clamp, i_clamp);
  float i_term = ki * integral_acc;

  // 4. Derivative Term (Predictive Braking)
  float d_term = kd * (error - prev_error) / 0.01f;
  prev_error = error;

  return p_term + i_term + d_term;
}

void EyeTrackingNode::controlLoopCallback()
{
  auto now = this->now();
  
  // Check for target timeout (> 400ms without target -> enter search/center state)
  if (!has_target_ || (now - last_target_time_).seconds() > 0.4) {
    // Gracefully return eyes to center
    eye_h_ += (90.0f - eye_h_) * 0.05f;
    eye_v_ += (90.0f - eye_v_) * 0.05f;
  } else {
    // Calculate Error relative to image center
    float center_x = current_target_.frame_width > 0 ? current_target_.frame_width / 2.0f : 320.0f;
    float center_y = current_target_.frame_height > 0 ? current_target_.frame_height / 2.0f : 240.0f;

    float error_x = current_target_.target_x - center_x;
    float error_y = current_target_.target_y - center_y;

    // Compute PID adjustments
    float delta_x = computePid(error_x, sum_error_x_, prev_error_x_,
                               pid_params_.kp, pid_params_.ki, pid_params_.kd,
                               pid_params_.i_clamp, pid_params_.deadband_x);
                               
    float delta_y = computePid(error_y, sum_error_y_, prev_error_y_,
                               pid_params_.kp, pid_params_.ki, pid_params_.kd,
                               pid_params_.i_clamp, pid_params_.deadband_y);

    // Apply adjustments with joint angle safety limits
    eye_h_ = std::clamp(eye_h_ + delta_x * 0.05f, 40.0f, 140.0f);
    eye_v_ = std::clamp(eye_v_ + delta_y * 0.05f, 60.0f, 120.0f);
    
    // Neck follows eyes with smoothing lag
    neck_yaw_ += (eye_h_ - neck_yaw_) * 0.02f;
    neck_pitch_ += (eye_v_ - neck_pitch_) * 0.02f;
  }

  // Publish Actuator Command Message
  auto cmd = humanoid_interfaces::msg::JointAngles();
  cmd.header.stamp = now;
  cmd.header.frame_id = "head_base_link";
  cmd.neck_yaw = neck_yaw_;
  cmd.neck_pitch = neck_pitch_;
  cmd.eye_left_h = eye_h_;
  cmd.eye_right_h = eye_h_;
  cmd.eye_left_v = eye_v_;
  cmd.eye_right_v = eye_v_;
  cmd.eyelid_upper = 70.0f;
  cmd.eyelid_lower = 30.0f;

  joint_cmd_pub_->publish(cmd);

  // Publish Standard ROS 2 JointStates for RViz / MoveIt 2 Kinematics
  auto state = sensor_msgs::msg::JointState();
  state.header.stamp = now;
  state.name = {"neck_yaw_joint", "neck_pitch_joint", "eye_h_joint", "eye_v_joint"};
  state.position = {neck_yaw_ * M_PI / 180.0, neck_pitch_ * M_PI / 180.0, 
                    eye_h_ * M_PI / 180.0, eye_v_ * M_PI / 180.0};
  joint_state_pub_->publish(state);
}

} // namespace humanoid_control

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<humanoid_control::EyeTrackingNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
