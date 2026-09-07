#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/components/web_server_base/web_server_base.h"

#include <functional>
#include <string>

/* Where Home Assistant hands this device its bootstrap.
 *
 * The paired firmware can reach Home Assistant in two directions, and both end
 * in the same three strings — an address, a token and the entity ID of the
 * config sensor:
 *
 * - a device that was flashed with an address *asks*, in `poll_pairing` in
 *   firmware/media-controller-paired.yaml. That is the original path and it
 *   is untouched;
 * - a device flashed from the factory image knows no address, so it cannot
 *   ask. It announces itself over mDNS instead, and Home Assistant posts the
 *   bootstrap here after somebody has typed the six digits on its screen.
 *
 * ## What protects this endpoint
 *
 * It is unauthenticated because the caller has no credentials yet, which is
 * the same position the Home Assistant side is in; see the header of
 * `custom_components/media_controller/provision.py`. Five things stand in the
 * way of anything else using it:
 *
 * - it answers at all only while the device is **unpaired**. The moment a
 *   token is stored, every route but `GET /api/provision/info` refuses with
 *   409, so provisioning a device a second time needs an explicit return to
 *   pairing state — a revoked token, or a reset;
 * - the six-digit code is shown on the device's own screen and nowhere else,
 *   so the caller has to be able to see it;
 * - a wrong code counts. `MAX_ATTEMPTS` of them close the endpoint for
 *   `LOCKOUT_MS`, which turns a million-guess search into something that
 *   takes about a year;
 * - the body is capped at `MAX_BODY_BYTES` and every field inside it has its
 *   own limit, so nothing here can be made to allocate;
 * - the code is compared in constant time, so timing says nothing about how
 *   many digits were right.
 *
 * Nothing is ever logged that a caller supplied: the token is never printed,
 * not even at VERBOSE, and neither is the code.
 *
 * ## What it does not do
 *
 * It holds no URL, calls nothing and knows no entity. It hands three strings
 * to a `std::function` the firmware YAML installs at boot, exactly as
 * `media_controller_grid` does with everything it needs from that half. The
 * component and the transport stay separable.
 */

namespace esphome::media_controller_provision {

/* What Home Assistant sends. Every field is validated before the handler is
 * called: the address is an absolute http(s) URL, the token is printable, and
 * the entity ID is a `<domain>.<object>` pair. */
struct ProvisionPayload {
  std::string ha_url;
  std::string token;
  std::string config_entity;
};

/* Wrong codes before the endpoint closes itself. Five is the same number the
 * Home Assistant side allows, and it is generous: the digits are on the
 * screen of the device being paired. */
static const uint8_t MAX_ATTEMPTS = 5;

/* How long the endpoint stays closed afterwards. Long enough that guessing a
 * six-digit code at five tries per window would take about a year, short
 * enough that somebody who mistyped it four times is not sent to find a
 * screwdriver. */
static const uint32_t LOCKOUT_MS = 300000;

/* The most a request body may be. The real one is about three hundred bytes:
 * a token of roughly a hundred and eighty characters, an address and an
 * entity ID. */
static const size_t MAX_BODY_BYTES = 1024;

/* Per-field ceilings, matched to the globals they end up in. They are the
 * `max_restore_data_length` of `ha_base`, `ha_token` and `config_entity` in
 * firmware/media-controller-paired.yaml; a value that would not survive a
 * reboot is refused now rather than silently truncated later. */
static const size_t MAX_URL_CHARS = 128;
static const size_t MAX_TOKEN_CHARS = 254;
static const size_t MAX_ENTITY_CHARS = 128;
static const size_t CODE_DIGITS = 6;

class MediaControllerProvision final : public AsyncWebHandler, public Component {
 public:
  explicit MediaControllerProvision(web_server_base::WebServerBase *base) : base_(base) {}

  void setup() override;
  void dump_config() override;
  /* After the network, like every other handler on this listener. */
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void set_port(uint16_t port) { this->port_ = port; }
  void set_profile(const std::string &profile) { this->profile_ = profile; }
  void set_panel_name(const std::string &name) { this->panel_name_ = name; }
  void set_contract_version(uint16_t version) { this->contract_version_ = version; }
  void set_firmware_version(const std::string &version) { this->firmware_version_ = version; }

  /* The two things this component needs from the firmware YAML. Neither is
   * compiled in, for the reason in the header above.
   *
   * `set_state` is **pushed** rather than read back through a callback, and
   * that is the whole of the thread safety here. Both values live in ESPHome
   * globals owned by the main loop, and a request arrives on the HTTP task;
   * reaching into those globals from a handler would be reading a
   * `std::string` while the loop may be assigning it. Instead the firmware
   * says so whenever either changes — at boot, on pairing, and when a token
   * is forgotten — and this component keeps its own copy behind the same
   * lock the request body uses. */
  void set_state(bool paired, const std::string &code);
  /* What to do with an accepted bootstrap. Called on the main loop, never on
   * the HTTP task. */
  void set_apply_handler(std::function<void(ProvisionPayload)> handler) { this->apply_handler_ = std::move(handler); }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index,
                  size_t total) override;
  bool isRequestHandlerTrivial() const override { return false; }

 protected:
  void handle_info_(AsyncWebServerRequest *request);
  void handle_verify_(AsyncWebServerRequest *request);
  void handle_apply_(AsyncWebServerRequest *request);

  /* Whether the code is the one on screen, counting the attempt when it is
   * not. Returns the HTTP status to answer with, or 0 when the code was
   * right. */
  int check_code_(const std::string &code);
  uint32_t lockout_remaining_ms_();
  bool is_paired_();

  static void send_json_(AsyncWebServerRequest *request, int code, const std::string &body);
  static void send_status_(AsyncWebServerRequest *request, int code, const char *status);
  static void send_refusal_(AsyncWebServerRequest *request, int status);

  web_server_base::WebServerBase *base_;
  uint16_t port_{80};

  std::string profile_;
  std::string panel_name_;
  std::string firmware_version_;
  uint16_t contract_version_{0};

  std::function<void(ProvisionPayload)> apply_handler_;

  /* Everything a request touches, and everything the main loop pushes in.
   * All of it is behind the one lock, because the two run on different
   * tasks. */
  Mutex lock_;
  std::string body_;
  std::string code_;
  bool paired_{false};
  uint8_t attempts_{0};
  uint32_t locked_until_ms_{0};
  bool locked_{false};
};

}  // namespace esphome::media_controller_provision
