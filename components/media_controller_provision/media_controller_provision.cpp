#include "media_controller_provision.h"

#include "esphome/components/json/json_util.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include <cstring>

namespace esphome::media_controller_provision {

static const char *const TAG = "provision";

static const char *const ROUTE_INFO = "/api/provision/info";
static const char *const ROUTE_VERIFY = "/api/provision/verify";
static const char *const ROUTE_APPLY = "/api/provision";

// ------------------------------------------------------------------ helpers

/* Compare two codes without leaking how far they matched. The lengths are
 * compared separately and both branches still walk the whole buffer, so a
 * caller learns only whether the answer was yes. */
static bool codes_match(const std::string &expected, const std::string &given) {
  if (expected.empty() || expected.size() != given.size())
    return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < expected.size(); i++)
    difference |= static_cast<uint8_t>(expected[i] ^ given[i]);
  return difference == 0;
}

static bool is_six_digits(const std::string &value) {
  if (value.size() != CODE_DIGITS)
    return false;
  for (const char c : value) {
    if (c < '0' || c > '9')
      return false;
  }
  return true;
}

/* An address this device can actually fetch from: absolute, http or https,
 * and nothing in it that would end up split across a header. A trailing
 * slash is trimmed, because every caller of `ha_base` appends a path that
 * begins with one. */
static bool clean_url(std::string *value) {
  if (value->size() > MAX_URL_CHARS)
    return false;
  for (const char c : *value) {
    if (static_cast<unsigned char>(c) <= 0x20 || static_cast<unsigned char>(c) >= 0x7f)
      return false;
  }
  while (!value->empty() && value->back() == '/')
    value->pop_back();

  size_t host = 0;
  if (value->rfind("http://", 0) == 0) {
    host = 7;
  } else if (value->rfind("https://", 0) == 0) {
    host = 8;
  } else {
    return false;
  }
  /* An origin and nothing else: Home Assistant is not served under a path,
   * and every caller of `ha_base` appends one of its own. Refusing a path
   * here is also what stops a payload from redirecting a request meant for
   * `/api/states/` somewhere else. */
  const std::string rest = value->substr(host);
  return !rest.empty() && rest.find('/') == std::string::npos;
}

/* A Home Assistant long-lived token is a JWT: three base64url segments and
 * two dots. Nothing else is accepted, so a value that could not be a token
 * never reaches a request header. */
static bool token_is_plausible(const std::string &value) {
  if (value.empty() || value.size() > MAX_TOKEN_CHARS)
    return false;
  uint8_t dots = 0;
  for (const char c : value) {
    if (c == '.') {
      dots++;
      continue;
    }
    const bool allowed = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                         c == '-' || c == '_';
    if (!allowed)
      return false;
  }
  return dots == 2;
}

/* `<domain>.<object_id>`, in the character set Home Assistant itself allows.
 * The device appends this to `/api/states/`, so anything that could change
 * the path it addresses is refused here. */
static bool entity_is_plausible(const std::string &value) {
  if (value.empty() || value.size() > MAX_ENTITY_CHARS)
    return false;
  size_t dots = 0;
  for (const char c : value) {
    if (c == '.') {
      dots++;
      continue;
    }
    const bool allowed = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
    if (!allowed)
      return false;
  }
  return dots == 1 && value.front() != '.' && value.back() != '.';
}

static std::string json_string(const std::string &value) {
  std::string out;
  out.reserve(value.size() + 2);
  out.push_back('"');
  for (const char c : value) {
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      default:
        if (static_cast<unsigned char>(c) < 0x20) {
          char buffer[7];
          snprintf(buffer, sizeof(buffer), "\\u%04x", static_cast<unsigned>(c) & 0xff);
          out += buffer;
        } else {
          out.push_back(c);
        }
    }
  }
  out.push_back('"');
  return out;
}

// -------------------------------------------------------------------- setup

void MediaControllerProvision::setup() {
  this->base_->set_port(this->port_);
  /* Without auth, deliberately: the caller has no credentials yet, and what
   * guards the exchange is the code on the screen and the attempt counter.
   * See the header. */
  this->base_->add_handler_without_auth(this);
  this->base_->init();
}

void MediaControllerProvision::set_state(bool paired, const std::string &code) {
  LockGuard guard{this->lock_};
  this->paired_ = paired;
  this->code_ = paired ? std::string() : code;
  if (!paired) {
    /* A device that has come back to pairing state starts with a clean slate:
     * the attempts spent against the *previous* code say nothing about this
     * one, and the code has changed. */
    this->attempts_ = 0;
    this->locked_ = false;
  }
}

bool MediaControllerProvision::is_paired_() {
  LockGuard guard{this->lock_};
  return this->paired_;
}

void MediaControllerProvision::dump_config() {
  ESP_LOGCONFIG(TAG, "Media Controller provisioning:");
  ESP_LOGCONFIG(TAG, "  Port: %u", this->port_);
  ESP_LOGCONFIG(TAG, "  Profile: %s", this->profile_.c_str());
  ESP_LOGCONFIG(TAG, "  Contract version: %u", this->contract_version_);
}

// ---------------------------------------------------------------- dispatch

bool MediaControllerProvision::canHandle(AsyncWebServerRequest *request) const {
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);
  const char *text = url.c_str();
  if (request->method() == HTTP_GET)
    return std::strcmp(text, ROUTE_INFO) == 0;
  if (request->method() == HTTP_POST)
    return std::strcmp(text, ROUTE_VERIFY) == 0 || std::strcmp(text, ROUTE_APPLY) == 0;
  return false;
}

void MediaControllerProvision::handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len,
                                          size_t index, size_t total) {
  LockGuard guard{this->lock_};
  if (index == 0) {
    this->body_.clear();
    if (total <= MAX_BODY_BYTES)
      this->body_.reserve(total);
  }
  if (this->body_.size() + len > MAX_BODY_BYTES) {
    /* Truncated on purpose. The handler then refuses the document rather
     * than acting on half of one. */
    return;
  }
  this->body_.append(reinterpret_cast<const char *>(data), len);
}

void MediaControllerProvision::handleRequest(AsyncWebServerRequest *request) {
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);
  const char *text = url.c_str();

  if (std::strcmp(text, ROUTE_INFO) == 0) {
    this->handle_info_(request);
  } else if (std::strcmp(text, ROUTE_VERIFY) == 0) {
    this->handle_verify_(request);
  } else if (std::strcmp(text, ROUTE_APPLY) == 0) {
    this->handle_apply_(request);
  } else {
    send_status_(request, 404, "no_such_route");
  }

  LockGuard guard{this->lock_};
  this->body_.clear();
}

// ----------------------------------------------------------------- answers

void MediaControllerProvision::send_json_(AsyncWebServerRequest *request, int code,
                                          const std::string &body) {
  request->send(code, "application/json; charset=utf-8", body.c_str());
}

void MediaControllerProvision::send_status_(AsyncWebServerRequest *request, int code,
                                            const char *status) {
  std::string body = "{\"status\":";
  body += json_string(status);
  body += "}";
  send_json_(request, code, body);
}

/* What this device is, and whether it is waiting to be paired. Nothing here
 * is a secret: it is the discovery record plus one boolean, and Home
 * Assistant reads it to confirm that the address it found really is the panel
 * whose code somebody is about to type. It keeps answering after pairing, so
 * that a device page can still tell what it is talking to. */
void MediaControllerProvision::handle_info_(AsyncWebServerRequest *request) {
  const bool paired = this->is_paired_();
  std::string body = "{\"panel_id\":";
  body += json_string(get_mac_address());
  body += ",\"profile\":";
  body += json_string(this->profile_);
  body += ",\"name\":";
  body += json_string(this->panel_name_);
  body += ",\"version\":";
  body += json_string(this->firmware_version_);
  body += ",\"contract_version\":" + std::to_string(this->contract_version_);
  body += ",\"paired\":";
  body += paired ? "true" : "false";
  body += "}";
  send_json_(request, 200, body);
}

uint32_t MediaControllerProvision::lockout_remaining_ms_() {
  if (!this->locked_)
    return 0;
  const uint32_t now = millis();
  if (static_cast<int32_t>(this->locked_until_ms_ - now) <= 0) {
    this->locked_ = false;
    this->attempts_ = 0;
    return 0;
  }
  return this->locked_until_ms_ - now;
}

int MediaControllerProvision::check_code_(const std::string &code) {
  LockGuard guard{this->lock_};

  if (const uint32_t remaining = this->lockout_remaining_ms_(); remaining > 0)
    return 429;
  if (!is_six_digits(code))
    return 403;

  if (this->paired_) {
    /* Nothing to guess against, and nothing to spend an attempt on. */
    return 409;
  }
  const std::string expected = this->code_;
  if (expected.empty()) {
    /* Unpaired but with nothing on screen yet: the device is still starting.
     * Not an attempt — there was nothing to guess against. */
    return 503;
  }

  if (codes_match(expected, code)) {
    this->attempts_ = 0;
    return 0;
  }

  this->attempts_++;
  if (this->attempts_ >= MAX_ATTEMPTS) {
    this->locked_ = true;
    this->locked_until_ms_ = millis() + LOCKOUT_MS;
    ESP_LOGW(TAG, "Too many wrong pairing codes; provisioning is closed for %u s",
             static_cast<unsigned>(LOCKOUT_MS / 1000));
    return 429;
  }
  ESP_LOGW(TAG, "A wrong pairing code was offered (%u of %u)", static_cast<unsigned>(this->attempts_),
           static_cast<unsigned>(MAX_ATTEMPTS));
  return 403;
}

/* Turn one of check_code_'s statuses into an answer. Every route that checks a
 * code answers the same way, so the mapping lives here rather than being
 * spelled out twice and drifting. */
void MediaControllerProvision::send_refusal_(AsyncWebServerRequest *request, int status) {
  switch (status) {
    case 429:
      send_status_(request, 429, "too_many_attempts");
      break;
    case 503:
      send_status_(request, 503, "not_ready");
      break;
    case 409:
      /* Only reachable if the device paired between this request arriving and
       * the code being checked. */
      send_status_(request, 409, "already_paired");
      break;
    default:
      send_status_(request, 403, "invalid_code");
      break;
  }
}

/* Answer the question "is this the panel showing that code" without changing
 * anything. Home Assistant asks it before it mints a token, so a mistyped
 * code costs nothing and leaves no credential behind. */
void MediaControllerProvision::handle_verify_(AsyncWebServerRequest *request) {
  if (this->is_paired_()) {
    send_status_(request, 409, "already_paired");
    return;
  }

  std::string code;
  {
    LockGuard guard{this->lock_};
    const bool read = json::parse_json(this->body_, [&](JsonObject root) -> bool {
      const char *value = root["code"].as<const char *>();
      if (value != nullptr)
        code = value;
      return true;
    });
    if (!read) {
      send_status_(request, 400, "invalid_request");
      return;
    }
  }

  const int refusal = this->check_code_(code);
  if (refusal == 0) {
    send_status_(request, 200, "ok");
    return;
  }
  send_refusal_(request, refusal);
}

/* The bootstrap itself. Everything is validated before anything is stored, so
 * a payload that is wrong in its last field does not leave the device holding
 * the first three. */
void MediaControllerProvision::handle_apply_(AsyncWebServerRequest *request) {
  if (this->is_paired_()) {
    send_status_(request, 409, "already_paired");
    return;
  }
  if (!this->apply_handler_) {
    send_status_(request, 500, "not_configured");
    return;
  }

  std::string code;
  ProvisionPayload payload;
  {
    LockGuard guard{this->lock_};
    const bool read = json::parse_json(this->body_, [&](JsonObject root) -> bool {
      const char *value = root["code"].as<const char *>();
      if (value != nullptr)
        code = value;
      if ((value = root["ha_url"].as<const char *>()) != nullptr)
        payload.ha_url = value;
      if ((value = root["token"].as<const char *>()) != nullptr)
        payload.token = value;
      if ((value = root["config_entity"].as<const char *>()) != nullptr)
        payload.config_entity = value;
      return true;
    });
    if (!read) {
      send_status_(request, 400, "invalid_request");
      return;
    }
  }

  if (const int refusal = this->check_code_(code); refusal != 0) {
    send_refusal_(request, refusal);
    return;
  }

  /* Checked after the code, so that a caller who cannot pair learns nothing
   * about what a well-formed payload looks like. */
  if (!clean_url(&payload.ha_url) || !token_is_plausible(payload.token) ||
      !entity_is_plausible(payload.config_entity)) {
    ESP_LOGW(TAG, "The bootstrap was refused: a field was missing or malformed");
    send_status_(request, 400, "invalid_payload");
    return;
  }

  /* Storing it touches globals, flash and LVGL, none of which may be reached
   * from the HTTP task. The answer is sent first: the device is about to be
   * busy for a moment, and Home Assistant has everything it needs to know. */
  ESP_LOGI(TAG, "Paired from %s; reading %s", payload.ha_url.c_str(), payload.config_entity.c_str());
  send_status_(request, 200, "paired");
  this->defer([this, payload]() { this->apply_handler_(payload); });
}

}  // namespace esphome::media_controller_provision
