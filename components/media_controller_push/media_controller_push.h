#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/components/web_server_base/web_server_base.h"

#include <functional>
#include <string>

/* Where Home Assistant hands this device a state it would otherwise have had
 * to ask for.
 *
 * ## Why this exists
 *
 * The paired firmware reads Home Assistant over `http_request`, which has no
 * asynchronous form: the request is opened, transferred and parsed inside the
 * action that started it, so the main loop stops for the whole exchange. That
 * is not a background cost on this device. The display is an RGB panel the
 * processor refreshes itself out of PSRAM through a bounce buffer, and the
 * interrupt that refills the buffer is on the same core as the main loop; a
 * request holds that core, streams its response into PSRAM, and the refill
 * misses. The panel's VSYNC interrupt notices the missed EOFs and resets the
 * DMA channel, which is the recovery working as designed and also a picture
 * that visibly jumps. Twice a second, for a player that is usually paused and
 * a configuration that usually has not changed.
 *
 * So the direction is reversed for the two payloads that were polled: Home
 * Assistant posts them here when they actually change, and the poll behind
 * them slows to a fallback. A paused player costs nothing at all.
 *
 * This is an external component rather than YAML for the same reason
 * `media_controller_provision` and `media_controller_grid` beside it are: an
 * `AsyncWebHandler` on `web_server_base` cannot be written as a lambda. It
 * shares that listener, so a device still opens exactly one port.
 *
 * **This component knows nothing about Home Assistant and nothing about the
 * documents it carries.** It does not parse them, and it holds no URL, no
 * token and no entity ID. It checks that the caller is allowed to speak, caps
 * the size, and hands the body to a `std::function` the firmware YAML installs
 * at boot -- the same seam `firmware/media-controller-ui.yaml` describes. The
 * parsers on the other side of that seam are the same ones the polls use, so
 * there is one reading of each payload and not two.
 *
 * ## What protects these endpoints
 *
 * Unlike the other two handlers on this listener, this one is authenticated,
 * and it has to be. The rationale in `media_controller_grid.h` turns on the
 * worst an unauthenticated caller can do being to rearrange the room page of
 * one device; the config payload does not fit inside that, because it is also
 * the channel display, brightness, page and restart commands arrive on. An
 * open route here would let anything on the network reboot a panel on a wall.
 *
 * The key is a random string the device mints once, keeps in flash, and
 * reports to Home Assistant in its status report. It never appears on any
 * route this device serves and never leaves the pair. Requests carrying the
 * wrong one are refused, and so are all requests until pairing has produced a
 * key at all.
 *
 * The key stops the commands. Nothing else here needs stopping, and that is
 * deliberate: a push is only ever a state this device already draws, the
 * fallback poll corrects whatever a push got wrong, and there is no route in
 * this component that reads anything back.
 */

namespace esphome::media_controller_push {

/* The config payload is the larger of the two by an order of magnitude --
 * sixty-four registry elements with Cyrillic names are about thirteen
 * kilobytes -- and this is the same ceiling `ui_load_room_config` gives the
 * response buffer it polls the very same document into. The two agree on
 * purpose: a document Home Assistant may hand this device one way and not the
 * other would be a difference nobody would find until a full room page hit it.
 */
static const size_t MAX_BODY_BYTES = 32 * 1024;

class MediaControllerPush final : public AsyncWebHandler, public Component {
 public:
  explicit MediaControllerPush(web_server_base::WebServerBase *base) : base_(base) {}

  void setup() override;
  void dump_config() override;
  /* After the network, like every other handler on this listener. */
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void set_port(uint16_t port) { this->port_ = port; }

  /* The key this device expects on every push, **pushed** in rather than read
   * back through a callback, for the reason `media_controller_provision`
   * gives for its own state: it lives in an ESPHome global the main loop owns,
   * a request arrives on the HTTP task, and reading a `std::string` the loop
   * may be assigning is a crash rather than a wrong answer. The firmware says
   * so whenever it changes -- at boot, on pairing, and when a token is
   * forgotten -- and this component keeps its own copy behind the same lock
   * the request body uses.
   *
   * An empty key disables both routes. That is the unpaired state, and it is
   * also what a forgotten token leaves behind. */
  void set_key(const std::string &key);

  /* What to do with an accepted document. Both are called on the main loop,
   * never on the HTTP task: the parsers behind them publish sensors and touch
   * LVGL, and neither is safe anywhere else. */
  void set_player_handler(std::function<void(std::string)> &&f) { this->player_handler_ = std::move(f); }
  void set_config_handler(std::function<void(std::string)> &&f) { this->config_handler_ = std::move(f); }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index,
                  size_t total) override;
  bool isRequestHandlerTrivial() const override { return false; }

 protected:
  /* Both routes are the same three steps -- may this caller speak, is there a
   * document, hand it over -- so they are one function and the handler it
   * belongs to is the argument. */
  void handle_push_(AsyncWebServerRequest *request, const std::function<void(std::string)> &handler,
                    const char *what);

  /* Drops whatever a refused request had already buffered, under the lock
   * the receiving half takes. */
  void discard_body_();

  /* Whether the request carries the key this device is expecting. False when
   * no key is set, which is the unpaired state. */
  bool authorized_(AsyncWebServerRequest *request);

  static void send_status_(AsyncWebServerRequest *request, int code, const char *status);

  web_server_base::WebServerBase *base_;
  uint16_t port_{80};

  std::function<void(std::string)> player_handler_{};
  std::function<void(std::string)> config_handler_{};

  /* Written by the main loop through set_key, read by the server task on
   * every request. */
  std::string key_;

  /* The body of the request being received. esp_http_server hands a raw body
   * over in chunks and services one request at a time, so a single buffer is
   * enough -- the same reasoning, and the same shape, as the grid beside it.
   *
   * It is kept rather than freed between requests: a push arrives as often as
   * the player changes, and returning thirteen kilobytes to the heap only to
   * ask for them again a moment later is how a device with one large
   * allocation and a long uptime ends up unable to make it. */
  std::string body_;
  /* Set when a body overran MAX_BODY_BYTES, so that the handler refuses the
   * document instead of acting on the part of it that fit. */
  bool body_overran_{false};

  Mutex lock_;
};

}  // namespace esphome::media_controller_push
