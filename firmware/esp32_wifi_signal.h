#pragma once

#include "esp_wifi.h"

inline int media_controller_wifi_rssi() {
  wifi_ap_record_t ap_info{};
  if (esp_wifi_sta_get_ap_info(&ap_info) != ESP_OK) {
    return -127;
  }
  return static_cast<int>(ap_info.rssi);
}
