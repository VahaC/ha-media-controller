#include "media_controller_push.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

#include <cstring>

namespace esphome::media_controller_push {

static const char *const TAG = "media_controller_push";

static const char *const ROUTE_PLAYER = "/api/push/player";
static const char *const ROUTE_CONFIG = "/api/push/config";

/* The header the key travels in. A header rather than a query parameter on
 * purpose: a query string is what ends up in logs and in proxy access records,
 * and this one is a credential. */
static const char *const KEY_HEADER = "X-Panel-Push-Key";

void MediaControllerPush::setup() {
  this->base_->set_port(this->port_);
  /* Without the listener's own auth, and authenticated by this component
   * instead: `add_handler` would ask for the web server's credentials, which
   * this device has none of and Home Assistant was never told. What guards
   * these two routes is the key in the header. See the class header. */
  this->base_->add_handler_without_auth(this);
  this->base_->init();
}

void MediaControllerPush::dump_config() {
  ESP_LOGCONFIG(TAG, "Media Controller push:");
  ESP_LOGCONFIG(TAG, "  Port: %u", this->port_);
  /* Whether there is a key, never the key. */
  LockGuard guard{this->lock_};
  ESP_LOGCONFIG(TAG, "  Accepting pushes: %s", YESNO(!this->key_.empty()));
}

void MediaControllerPush::set_key(const std::string &key) {
  LockGuard guard{this->lock_};
  this->key_ = key;
}

// ---------------------------------------------------------------- dispatch

bool MediaControllerPush::canHandle(AsyncWebServerRequest *request) const {
  if (request->method() != HTTP_POST)
    return false;
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);
  const char *text = url.c_str();
  return std::strcmp(text, ROUTE_PLAYER) == 0 || std::strcmp(text, ROUTE_CONFIG) == 0;
}

void MediaControllerPush::handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len,
                                     size_t index, size_t total) {
  LockGuard guard{this->lock_};
  if (index == 0) {
    this->body_.clear();
    this->body_overran_ = false;
    if (total <= MAX_BODY_BYTES)
      this->body_.reserve(total);
  }
  if (this->body_.size() + len > MAX_BODY_BYTES) {
    /* Remembered rather than silently truncated: a document cut in half
     * parses as a smaller one, and a smaller one is a room page with cards
     * missing rather than an error anybody would notice. */
    this->body_overran_ = true;
    return;
  }
  this->body_.append(reinterpret_cast<const char *>(data), len);
}

void MediaControllerPush::handleRequest(AsyncWebServerRequest *request) {
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);
  const char *text = url.c_str();

  if (std::strcmp(text, ROUTE_PLAYER) == 0) {
    this->handle_push_(request, this->player_handler_, "player");
  } else if (std::strcmp(text, ROUTE_CONFIG) == 0) {
    this->handle_push_(request, this->config_handler_, "config");
  } else {
    send_status_(request, 404, "no_such_route");
  }
}

bool MediaControllerPush::authorized_(AsyncWebServerRequest *request) {
  std::string expected;
  {
    LockGuard guard{this->lock_};
    expected = this->key_;
  }
  if (expected.empty())
    return false;

  const optional<std::string> offered = request->get_header(KEY_HEADER);
  if (!offered.has_value())
    return false;

  /* Compared in constant time over the expected length. The lengths are
   * compared first and separately, which does leak whether the offered key is
   * the right size -- that is one bit about a value the caller already chose,
   * and it is not the byte-at-a-time oracle worth avoiding. */
  const std::string &got = offered.value();
  if (got.size() != expected.size())
    return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < expected.size(); i++)
    difference |= static_cast<uint8_t>(got[i] ^ expected[i]);
  return difference == 0;
}

void MediaControllerPush::handle_push_(AsyncWebServerRequest *request,
                                       const std::function<void(std::string)> &handler,
                                       const char *what) {
  if (!this->authorized_(request)) {
    /* One answer for "this device is not paired and accepts nothing" and for
     * "that is not the key": telling them apart would tell a caller which of
     * the two it had found. The firmware log says which, because the log is
     * read by whoever owns the device. */
    ESP_LOGD(TAG, "Refused a %s push: no key, or the wrong one", what);
    send_status_(request, 403, "forbidden");
    this->discard_body_();
    return;
  }

  if (!handler) {
    /* The firmware YAML installs both at boot, so this is a build that came
     * apart rather than anything a caller did. */
    ESP_LOGW(TAG, "No handler is installed for a %s push", what);
    send_status_(request, 503, "not_ready");
    this->discard_body_();
    return;
  }

  bool overran;
  std::string document;
  {
    LockGuard guard{this->lock_};
    overran = this->body_overran_;
    if (!overran)
      document.swap(this->body_);
    this->body_.clear();
    this->body_overran_ = false;
  }

  if (overran) {
    ESP_LOGW(TAG, "A %s push was larger than %u bytes and was refused", what,
             static_cast<unsigned>(MAX_BODY_BYTES));
    send_status_(request, 413, "too_large");
    return;
  }
  if (document.empty()) {
    send_status_(request, 400, "empty_body");
    return;
  }

  /* Deferred, because everything behind that handler publishes sensors and
   * draws on the screen, and this runs on the HTTP server's task. The answer
   * goes back now rather than after the parse: Home Assistant is being told
   * the document was accepted for delivery, which is all it can act on, and
   * holding the socket open across a parse would put the panel's own web
   * server in the way of the main loop it is trying to keep free. */
  this->defer([handler, document]() { handler(document); });
  send_status_(request, 202, "accepted");
}

void MediaControllerPush::discard_body_() {
  LockGuard guard{this->lock_};
  this->body_.clear();
  this->body_overran_ = false;
}

void MediaControllerPush::send_status_(AsyncWebServerRequest *request, int code, const char *status) {
  std::string body = std::string("{\"status\":\"") + status + "\"}";
  request->send(code, "application/json; charset=utf-8", body.c_str());
}

}  // namespace esphome::media_controller_push

#endif  // USE_ESP32
