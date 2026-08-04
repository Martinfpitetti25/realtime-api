cmake_minimum_required(VERSION 3.8)
project(humanoid_control)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -O3)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(humanoid_interfaces REQUIRED)

include_directories(include)

add_executable(eye_tracking_node src/eye_tracking_node.cpp)
ament_target_dependencies(eye_tracking_node
  rclcpp
  sensor_msgs
  humanoid_interfaces
)

install(TARGETS
  eye_tracking_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

ament_package()
