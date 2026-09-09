//
// Created by Clyde Stubbs on 29/10/2023.
//
#pragma once

// only applicable on ESP32-S3
#ifdef USE_ESP32_VARIANT_ESP32S3
#include "esphome/core/component.h"
#include "esphome/components/spi/spi.h"
#include "esphome/components/display/display.h"
#include "esp_lcd_panel_ops.h"

#include "esp_lcd_panel_rgb.h"
#include "esp_timer.h"

namespace esphome::st7701s {

constexpr static const char *const TAG = "display.st7701s";
const uint8_t SW_RESET_CMD = 0x01;
const uint8_t SLEEP_OUT = 0x11;
const uint8_t SDIR_CMD = 0xC7;
const uint8_t MADCTL_CMD = 0x36;
const uint8_t INVERT_OFF = 0x20;
const uint8_t INVERT_ON = 0x21;
const uint8_t DISPLAY_ON = 0x29;
const uint8_t CMD2_BKSEL = 0xFF;
const uint8_t CMD2_BK0[5] = {0x77, 0x01, 0x00, 0x00, 0x10};
const uint8_t ST7701S_DELAY_FLAG = 0xFF;

class ST7701S final : public display::Display,
                      public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW, spi::CLOCK_PHASE_LEADING,
                                            spi::DATA_RATE_1MHZ> {
 public:
  void update() override { this->do_update_(); }
  void setup() override;
  void loop() override;
  void draw_pixels_at(int x_start, int y_start, int w, int h, const uint8_t *ptr, display::ColorOrder order,
                      display::ColorBitness bitness, bool big_endian, int x_offset, int y_offset, int x_pad) override;

  display::ColorOrder get_color_mode() { return this->color_mode_; }
  void set_color_mode(display::ColorOrder color_mode) { this->color_mode_ = color_mode; }
  void set_invert_colors(bool invert_colors) { this->invert_colors_ = invert_colors; }

  void add_data_pin(InternalGPIOPin *data_pin, size_t index) { this->data_pins_[index] = data_pin; };
  void set_de_pin(InternalGPIOPin *de_pin) { this->de_pin_ = de_pin; }
  void set_pclk_pin(InternalGPIOPin *pclk_pin) { this->pclk_pin_ = pclk_pin; }
  void set_vsync_pin(InternalGPIOPin *vsync_pin) { this->vsync_pin_ = vsync_pin; }
  void set_hsync_pin(InternalGPIOPin *hsync_pin) { this->hsync_pin_ = hsync_pin; }
  void set_dc_pin(GPIOPin *dc_pin) { this->dc_pin_ = dc_pin; }
  void set_reset_pin(GPIOPin *reset_pin) { this->reset_pin_ = reset_pin; }
  void set_width(uint16_t width) { this->width_ = width; }
  void set_pclk_frequency(uint32_t pclk_frequency) { this->pclk_frequency_ = pclk_frequency; }
  void set_bounce_buffer_lines(uint16_t lines) { this->bounce_buffer_lines_ = lines; }
  void set_force_restart(bool force_restart) { this->force_restart_ = force_restart; }
  void set_pclk_inverted(bool inverted) { this->pclk_inverted_ = inverted; }
  void set_dimensions(uint16_t width, uint16_t height) {
    this->width_ = width;
    this->height_ = height;
  }
  int get_width() override { return this->width_; }
  int get_height() override { return this->height_; }
  void set_hsync_back_porch(uint16_t hsync_back_porch) { this->hsync_back_porch_ = hsync_back_porch; }
  void set_hsync_front_porch(uint16_t hsync_front_porch) { this->hsync_front_porch_ = hsync_front_porch; }
  void set_hsync_pulse_width(uint16_t hsync_pulse_width) { this->hsync_pulse_width_ = hsync_pulse_width; }
  void set_vsync_pulse_width(uint16_t vsync_pulse_width) { this->vsync_pulse_width_ = vsync_pulse_width; }
  void set_vsync_back_porch(uint16_t vsync_back_porch) { this->vsync_back_porch_ = vsync_back_porch; }
  void set_vsync_front_porch(uint16_t vsync_front_porch) { this->vsync_front_porch_ = vsync_front_porch; }
  void set_init_sequence(const std::vector<uint8_t> &init_sequence) { this->init_sequence_ = init_sequence; }
  void set_mirror_x(bool mirror_x) { this->mirror_x_ = mirror_x; }
  void set_mirror_y(bool mirror_y) { this->mirror_y_ = mirror_y; }
  void set_offsets(int16_t offset_x, int16_t offset_y) {
    this->offset_x_ = offset_x;
    this->offset_y_ = offset_y;
  }

  /* What the RGB peripheral did since this was last called, and it is reset
   * by the call. There is no other way to ask: this panel has no ESPHome
   * native API, so a number that stays on the device is a number nobody can
   * read. The status report takes a sample each time it goes out.
   *
   *  - `fps` is measured rather than calculated. The pixel clock the
   *    peripheral actually runs at is the PLL divided by an integer, not the
   *    frequency asked for, so this is the only honest answer to what raising
   *    `pclk_frequency` bought.
   *  - `desyncs` counts frames the DMA did not finish a sweep of the frame
   *    buffer in. Every one of them is a restart of the DMA channel, and a
   *    restart is the picture visibly jumping. This is the number that says
   *    whether a change helped, and it is the whole reason the counters exist.
   *
   *    It is counted in the VSYNC interrupt rather than worked out here, and
   *    that is not a detail. The first version of this subtracted two free
   *    running counters from the main loop, which cannot be right: the bounce
   *    filler runs two buffers ahead of the beam, so for about four percent of
   *    every frame the sweep counter is legitimately one ahead of the frame
   *    counter. A sample taken in that window reported a deficit in the window
   *    after it, and reported one desync per twenty-five reports on a panel
   *    that had had none. Comparing both inside the interrupt evaluates them
   *    at one point in the cycle, which is what makes the answer mean
   *    something.
   *  - `flushes` counts the times the interface handed this driver a region to
   *    copy into the frame buffer. It is the denominator for blaming a desync
   *    on the interface: a window with desyncs and no flushes in it did not
   *    get them from anything the interface drew.
   *  - `jitter_us` is the spread between the longest and the shortest gap
   *    between VSYNC interrupts. The hardware period is constant, so all of
   *    the spread is the interrupt being late, and the interrupt being late
   *    is what turns a restart into a shifted frame rather than an invisible
   *    one.
   */
  struct Stats {
    float fps;
    uint32_t desyncs;
    uint32_t flushes;
    uint32_t jitter_us;
  };
  Stats take_stats();

  display::DisplayType get_display_type() override { return display::DisplayType::DISPLAY_TYPE_COLOR; }
  int get_width_internal() override { return this->width_; }
  int get_height_internal() override { return this->height_; }
  void dump_config() override;
  void draw_pixel_at(int x, int y, Color color) override;

  // this will be horribly slow.
 protected:
  void write_command_(uint8_t value);
  void write_data_(uint8_t value);
  void write_sequence_(uint8_t cmd, size_t len, const uint8_t *bytes);
  void write_init_sequence_();
  static bool vsync_callback_(esp_lcd_panel_handle_t panel,
                              const esp_lcd_rgb_panel_event_data_t *data, void *ctx);
  static bool frame_callback_(esp_lcd_panel_handle_t panel,
                              const esp_lcd_rgb_panel_event_data_t *data, void *ctx);

  InternalGPIOPin *de_pin_{nullptr};
  InternalGPIOPin *pclk_pin_{nullptr};
  InternalGPIOPin *hsync_pin_{nullptr};
  InternalGPIOPin *vsync_pin_{nullptr};
  GPIOPin *reset_pin_{nullptr};
  GPIOPin *dc_pin_{nullptr};
  InternalGPIOPin *data_pins_[16] = {};
  uint16_t hsync_pulse_width_ = 10;
  uint16_t hsync_back_porch_ = 10;
  uint16_t hsync_front_porch_ = 20;
  uint16_t vsync_pulse_width_ = 10;
  uint16_t vsync_back_porch_ = 10;
  uint16_t vsync_front_porch_ = 10;
  std::vector<uint8_t> init_sequence_;
  uint32_t pclk_frequency_ = 16 * 1000 * 1000;
  /* How many display lines the bounce buffer holds. Upstream hardcodes ten.
   *
   * The option exists because raising it looked like free slack: the LCD
   * peripheral drains the buffer at the pixel clock, so more lines is more
   * time for the refill to happen in. Forty was tried on that reasoning and
   * changed nothing that could be seen, for about 75 kB of internal RAM.
   *
   * The reasoning was half the picture. The refill is a memcpy out of PSRAM
   * run inside the DMA end-of-frame interrupt, and its length is what the
   * buffer size actually sets: forty lines of a 480 px panel is 38 kB, which
   * is on the order of a millisecond of PSRAM read. That interrupt shares its
   * priority level with the VSYNC interrupt, which therefore cannot run until
   * the memcpy finishes -- and the VSYNC interrupt is where a restart of the
   * DMA channel has to happen if it is to be invisible. It has only the
   * vertical back porch to do it in: ten lines, 430 us at 12 MHz.
   *
   * So the buffer trades one deadline against another. It widens the refill
   * deadline in proportion to its size and narrows, by the same proportion,
   * the odds that VSYNC is serviced while there is still back porch left. The
   * total bytes copied per frame do not change either way. Ten lines is about
   * 300 us of memcpy against 430 us of back porch, and that is the side of the
   * trade this panel wants. */
  uint16_t bounce_buffer_lines_ = 10;
  /* Whether to ask the RGB driver to restart its DMA channel every main-loop
   * iteration, which is what upstream does unconditionally.
   *
   * The request is honoured in the VSYNC interrupt, and ESP-IDF's own comment
   * on the routine that honours it says what it costs: "this fix can lead to
   * single-frame desyncs itself, as in: if this interrupt is late enough, the
   * display will shift as the LCD controller already read out the first data
   * bytes, and resetting DMA will re-send those." The interrupt has only the
   * vertical back porch to be on time in -- ten lines, about 430 us at 12 MHz
   * -- and it shares its priority level with the DMA end-of-frame interrupt,
   * whose bounce-buffer memcpy runs for as long as the bounce buffer is big.
   * So asking for a restart on every frame is asking, thirty times a second,
   * for a lottery that a busy PSRAM bus loses.
   *
   * Nothing is given up by not asking. The driver in ESP-IDF 5.5 restarts on
   * its own when a frame actually underran -- it counts the end-of-frame
   * interrupts it received against the number it expected and restarts when
   * they are short -- which is the case the unconditional request was written
   * for, back when the driver had no such check. */
  bool force_restart_{true};
  /* Written by the VSYNC and frame-complete interrupts, read and zeroed by
   * take_stats() from the main loop. Nothing locks them: a sample that lands
   * between the read and the zero loses one frame out of the eighteen hundred
   * in a minute, and a diagnostic is not worth taking a spinlock into an
   * interrupt for. */
  volatile uint32_t vsync_count_{0};
  volatile uint32_t frame_count_{0};
  volatile uint32_t desync_count_{0};
  volatile uint32_t flush_count_{0};
  // Interrupt-private: the sweep count this VSYNC compares against.
  uint32_t last_frame_seen_{0};
  volatile uint32_t period_min_us_{UINT32_MAX};
  volatile uint32_t period_max_us_{0};
  volatile int64_t last_vsync_us_{0};
  int64_t window_start_us_{0};
  bool pclk_inverted_{true};

  bool invert_colors_{};
  display::ColorOrder color_mode_{display::COLOR_ORDER_BGR};
  size_t width_{};
  size_t height_{};
  int16_t offset_x_{0};
  int16_t offset_y_{0};
  bool mirror_x_{};
  bool mirror_y_{};

  esp_lcd_panel_handle_t handle_{};
};

}  // namespace esphome::st7701s
#endif
