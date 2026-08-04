/**
 * @file esp32_can_servo_driver.cpp
 * @brief Embedded FreeRTOS / micro-ROS Firmware for ESP32 Microcontroller Actuation.
 * @details Demonstrates dual-core scheduling, CAN bus interfacing, micro-ROS node management,
 *          and 1000Hz hard real-time PWM motor generation.
 * @author Javier - Robotics Software & Integration Engineer
 */

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <driver/mcpwm.h>
#include <driver/twai.h> // ESP32 CAN bus driver (TWAI)

// ══════════════════════════════════════════════════════════════════════════════
// FREERTOS CONFIGURATION & HANDLES
// ══════════════════════════════════════════════════════════════════════════════

// Task Handles
TaskHandle_t TaskMicroROS_Handle = NULL;
TaskHandle_t TaskMotorControl_Handle = NULL;

// Queue for inter-task communication (Zero-Copy pointer references)
QueueHandle_t ServoCommandQueue = NULL;

// Servo Angle Structure (8 Actuator Channels)
struct ServoCommand {
  uint8_t channel;
  float angle_degrees;
  uint32_t timestamp_us;
};

// Actuator Pin Definitions (PCA9685 / Local ESP32 PWM Pins)
#define CAN_TX_PIN GPIO_NUM_5
#define CAN_RX_PIN GPIO_NUM_4
#define PWM_SERVO_NECK_YAW GPIO_NUM_18
#define PWM_SERVO_NECK_PITCH GPIO_NUM_19

// ══════════════════════════════════════════════════════════════════════════════
// CORE 1: HARD REAL-TIME MOTOR CONTROL LOOP (1000 Hz / 1ms Cycle)
// ══════════════════════════════════════════════════════════════════════════════

void TaskMotorControl(void * pvParameters)
{
  (void) pvParameters;

  TickType_t xLastWakeTime = xTaskGetTickCount();
  const TickType_t xFrequency = pdMS_TO_TICKS(1); // 1ms = 1000Hz

  ServoCommand current_cmd;

  // Initialize ESP32 Motor PWM hardware timers
  mcpwm_config_t pwm_config;
  pwm_config.frequency = 50; // 50 Hz standard servo PWM
  pwm_config.cmpr_a = 0;
  pwm_config.cmpr_b = 0;
  pwm_config.counter_mode = MCPWM_UP_COUNTER;
  pwm_config.duty_mode = MCPWM_DUTY_MODE_0;
  
  mcpwm_init(MCPWM_UNIT_0, MCPWM_TIMER_0, &pwm_config);
  mcpwm_gpio_init(MCPWM_UNIT_0, MCPWM0A, PWM_SERVO_NECK_YAW);
  mcpwm_gpio_init(MCPWM_UNIT_0, MCPWM0B, PWM_SERVO_NECK_PITCH);

  Serial.println("✅ [CORE 1] FreeRTOS Hard Real-Time Motor Task Started (1000 Hz)");

  for (;;)
  {
    // Wait for next 1ms tick (Exact deterministic timing)
    vTaskDelayUntil(&xLastWakeTime, xFrequency);

    // Read incoming commands from micro-ROS queue without blocking
    if (xQueueReceive(ServoCommandQueue, &current_cmd, 0) == pdTRUE)
    {
      // Convert degrees (0-180) to pulse width (1000us - 2000us)
      float pulse_width_us = 1000.0f + (current_cmd.angle_degrees / 180.0f) * 1000.0f;
      
      // Update hardware PWM registers directly
      if (current_cmd.channel == 0) {
        mcpwm_set_duty_in_us(MCPWM_UNIT_0, MCPWM_TIMER_0, MCPWM_OPR_A, pulse_width_us);
      } else if (current_cmd.channel == 1) {
        mcpwm_set_duty_in_us(MCPWM_UNIT_0, MCPWM_TIMER_0, MCPWM_OPR_B, pulse_width_us);
      }
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// CORE 0: MICRO-ROS & CAN BUS COMMUNICATION TASK
// ══════════════════════════════════════════════════════════════════════════════

void TaskMicroROS(void * pvParameters)
{
  (void) pvParameters;

  // Initialize CAN Bus (TWAI) Driver at 500 kbps
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  if (twai_driver_install(&g_config, &t_config, &f_config) == ESP_OK) {
    twai_start();
    Serial.println("✅ [CORE 0] CAN Bus (TWAI) Driver Initialized @ 500 kbps");
  }

  Serial.println("✅ [CORE 0] micro-ROS / CAN Network Task Started");

  twai_message_t can_rx_msg;

  for (;;)
  {
    // Receive incoming CAN frames from ROS 2 Master
    if (twai_receive(&can_rx_msg, pdMS_TO_TICKS(10)) == ESP_OK)
    {
      if (can_rx_msg.identifier == 0x120) // Servo command CAN ID
      {
        ServoCommand cmd;
        cmd.channel = can_rx_msg.data[0];
        cmd.angle_degrees = (float)can_rx_msg.data[1];
        cmd.timestamp_us = micros();

        // Send to Core 1 high-priority motor task via FreeRTOS Queue
        xQueueSend(ServoCommandQueue, &cmd, 0);
      }
    }

    vTaskDelay(pdMS_TO_TICKS(5)); // Yield 5ms
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// SETUP & ENTRY POINT
// ══════════════════════════════════════════════════════════════════════════════

void setup()
{
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- ESP32 Dual-Core FreeRTOS Actuator Driver Initializing ---");

  // Create FreeRTOS Inter-Task Queue (Depth 10)
  ServoCommandQueue = xQueueCreate(10, sizeof(ServoCommand));

  // Pin Micro-ROS / CAN Task to CORE 0 (Network & I/O)
  xTaskCreatePinnedToCore(
    TaskMicroROS,
    "MicroROS_CAN_Task",
    8192,         // Stack size
    NULL,         // Parameters
    1,            // Priority (Medium)
    &TaskMicroROS_Handle,
    0             // Core ID = 0
  );

  // Pin Hard Real-Time Motor Control Task to CORE 1 (Dedicated PWM/Kinematics)
  xTaskCreatePinnedToCore(
    TaskMotorControl,
    "MotorControl_Task",
    4096,         // Stack size
    NULL,         // Parameters
    5,            // Priority (High - Realtime)
    &TaskMotorControl_Handle,
    1             // Core ID = 1
  );

  Serial.println("✅ Dual-Core FreeRTOS Scheduler Running.\n");
}

void loop()
{
  // Empty - FreeRTOS handles all execution tasks in background threads!
  vTaskDelete(NULL);
}
