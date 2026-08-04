/**
 * @file eye_tracking_node.hpp
 * @brief ROS 2 C++ Node for High-Speed PID Tracking & Kinematic Joint Command Computation.
 * @author Javier - Robotics Software & Integration Engineer
 */

#ifndef HUMANOID_CONTROL__EYE_TRACKING_NODE_HPP_
#define HUMANOID_CONTROL__EYE_TRACKING_NODE_HPP_

#include <memory>
#include <chrono>

#include "rclcpp/rclcpp.hpp"
#include "humanoid_interfaces/msg/target_position.hpp"
#include "humanoid_interfaces/msg/joint_angles.hpp"
#include "sensor_msgs/msg/joint_state.hpp"

namespace humanoid_control
{

/**
 * @class EyeTrackingNode
 * @brief Real-time C++ ROS 2 Node implementing PID control, Deadband filtering,
 *        and anti-windup clamping for 6-DOF Humanoid Eye & Neck Actuation.
 */
class EyeTrackingNode : public rclcpp::Node
{
public:
  explicit EyeTrackingNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());
  virtual ~EyeTrackingNode() = default;

private:
  // ROS 2 Communication Handles
  rclcpp::Subscription<humanoid_interfaces::msg::TargetPosition>::SharedPtr target_sub_;
  rclcpp::Publisher<humanoid_interfaces::msg::JointAngles>::SharedPtr joint_cmd_pub_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_state_pub_;
  rclcpp::TimerBase::SharedPtr control_timer_;

  // Callback for vision target updates
  void onTargetPositionReceived(const humanoid_interfaces::msg::TargetPosition::SharedPtr msg);
  
  // 100 Hz Control Loop Execution
  void controlLoopCallback();

  // PID Calculation Core Method
  float computePid(float error, float & integral_acc, float & prev_error, 
                   float kp, float ki, float kd, float i_clamp, float deadband);

  // Controller State & Parameters
  struct PidParams {
    float kp{0.80f};
    float ki{0.01f};
    float kd{0.05f};
    float i_clamp{20.0f};
    float deadband_x{30.0f};
    float deadband_y{25.0f};
  } pid_params_;

  // Accumulators
  float sum_error_x_{0.0f};
  float sum_error_y_{0.0f};
  float prev_error_x_{0.0f};
  float prev_error_y_{0.0f};

  // Current Joint Output Positions (degrees)
  float neck_yaw_{90.0f};
  float neck_pitch_{90.0f};
  float eye_h_{90.0f};
  float eye_v_{90.0f};

  // Target cache
  humanoid_interfaces::msg::TargetPosition current_target_;
  bool has_target_{false};
  rclcpp::Time last_target_time_;
};

} // namespace humanoid_control

#endif // HUMANOID_CONTROL__EYE_TRACKING_NODE_HPP_
