#include "media_controller_grid.h"

#include "esphome/components/json/json_util.h"
#include "esphome/core/log.h"

#include <cstdio>
#include <cstring>

namespace esphome::media_controller_grid {

static const char *const TAG = "room_grid";

/* The artwork this build carries. The names are the document's, shared with
 * the T560 panel; the two builds do not carry the same set, which is exactly
 * why `GET /api/entities` reports it rather than the editor writing it down a
 * second time. */
const char *const ICON_NAMES[] = {"light-1", "light-2", "fan", "ac"};
const size_t ICON_COUNT = sizeof(ICON_NAMES) / sizeof(ICON_NAMES[0]);

/* The default card. Two cells square is the smallest size that still holds an
 * icon and a readable name at 60 px a cell, so it is what a first run
 * places. */
static const uint8_t DEFAULT_CARD_SPAN = 2;

/* What a layout document may cost. A card is well under a hundred bytes, and
 * the backup endpoint refuses anything over sixteen kilobytes, so this is the
 * same ceiling seen from this end: it stops a body being accumulated
 * indefinitely by a caller that never finishes sending one. */
static const size_t MAX_DOCUMENT_BYTES = 16 * 1024;

// ------------------------------------------------------------------ helpers

/* A rid is eight lowercase hex characters (docs/CONTRACT.md, Registry
 * entries). Anything else is not a rid this build will store: the card is
 * four bytes of identity in flash, and guessing at a malformed one would
 * quietly bind a card to the wrong element. */
static bool parse_rid(const char *text, uint32_t *out) {
  if (text == nullptr)
    return false;
  uint32_t value = 0;
  size_t i = 0;
  for (; i < 8; i++) {
    const char c = text[i];
    if (c >= '0' && c <= '9') {
      value = (value << 4) | static_cast<uint32_t>(c - '0');
    } else if (c >= 'a' && c <= 'f') {
      value = (value << 4) | static_cast<uint32_t>(c - 'a' + 10);
    } else {
      return false;
    }
  }
  if (text[i] != '\0')
    return false;
  *out = value;
  return true;
}

static std::string format_rid(uint32_t rid) {
  char buffer[9];
  snprintf(buffer, sizeof(buffer), "%08x", static_cast<unsigned>(rid));
  return std::string(buffer);
}

static uint8_t domain_from_name(const char *domain) {
  if (domain == nullptr)
    return DOMAIN_OTHER;
  if (strcmp(domain, "light") == 0)
    return DOMAIN_LIGHT;
  if (strcmp(domain, "switch") == 0)
    return DOMAIN_SWITCH;
  return DOMAIN_OTHER;
}

static uint8_t icon_from_name(const char *name) {
  if (name == nullptr || *name == '\0')
    return 0;
  for (size_t i = 0; i < ICON_COUNT; i++) {
    if (strcmp(name, ICON_NAMES[i]) == 0)
      return static_cast<uint8_t>(i + 1);
  }
  /* An icon this build does not carry is dropped rather than refused: the
   * card then draws its domain's own artwork, which is always a defensible
   * picture, and a layout written on a device with more artwork still
   * loads. */
  return 0;
}

/* A JsonDocument on the PSRAM heap where there is one. A registry of
 * sixty-four Cyrillic names is about thirteen kilobytes of text and rather
 * more as a document; taking that out of internal RAM would be felt
 * elsewhere. */
static void serialize_to(JsonDocument &doc, std::string *out) { serializeJson(doc, *out); }

// ------------------------------------------------------------------- setup

void MediaControllerGrid::setup() {
  this->pref_ = global_preferences->make_preference<LayoutBlob>(fnv1_hash("media_controller_room_grid"));
  this->load_from_flash_();

  this->base_->set_port(this->port_);
  /* Without auth on purpose. See the header: the API is narrow enough that
   * the missing password is a decision rather than an oversight, and
   * add_handler() would wrap it in a middleware there is nothing to check
   * against anyway — this firmware configures no web server credentials. */
  this->base_->add_handler_without_auth(this);
  this->base_->init();
}

void MediaControllerGrid::dump_config() {
  ESP_LOGCONFIG(TAG,
                "Room grid:\n"
                "  Editor: http://<device>:%u/\n"
                "  Grid: %ux%u cells of %u px\n"
                "  Cards in flash: %u",
                this->port_, GRID_COLUMNS, GRID_ROWS, GRID_CELL_PX,
                static_cast<unsigned>(this->cards_.size()));
  ESP_LOGCONFIG(TAG, "  The editor has no password. Do not forward this port through a router.");
}

void MediaControllerGrid::set_skin(const std::string &skin) {
  if (this->skin_ == skin)
    return;
  LockGuard guard{this->lock_};
  this->skin_ = skin;
}

void MediaControllerGrid::set_skin_writable(bool writable) {
  if (this->skin_writable_ == writable)
    return;
  LockGuard guard{this->lock_};
  this->skin_writable_ = writable;
}

// ---------------------------------------------------------------- registry

const Entry *MediaControllerGrid::entry(uint32_t rid) const {
  for (const auto &entry : this->entries_) {
    if (entry.rid == rid)
      return &entry;
  }
  return nullptr;
}

Entry *MediaControllerGrid::entry(uint32_t rid) {
  for (auto &entry : this->entries_) {
    if (entry.rid == rid)
      return &entry;
  }
  return nullptr;
}

bool MediaControllerGrid::ingest_entities(const std::string &attributes) {
  std::vector<Entry> parsed;

  const bool read = json::parse_json(attributes, [&parsed](JsonObject root) -> bool {
    JsonArray entities = root["entities"].as<JsonArray>();
    if (entities.isNull())
      return false;
    for (JsonObject element : entities) {
      if (parsed.size() >= MAX_CARDS)
        break;
      uint32_t rid = 0;
      if (!parse_rid(element["rid"].as<const char *>(), &rid))
        continue;
      const char *entity = element["entity"].as<const char *>();
      if (entity == nullptr || *entity == '\0')
        continue;

      Entry entry{};
      entry.rid = rid;
      entry.entity = entity;
      const char *name = element["name"].as<const char *>();
      entry.name = name != nullptr ? name : "";
      entry.domain = domain_from_name(element["domain"].as<const char *>());
      entry.dimmable = false;
      for (JsonVariant control : element["controls"].as<JsonArray>()) {
        const char *value = control.as<const char *>();
        /* A control this build does not know is ignored rather than treated
         * as an error, so that a future one can be added without breaking a
         * device already in the field. */
        if (value != nullptr && strcmp(value, "brightness") == 0)
          entry.dimmable = true;
      }
      entry.pct = 50.0f;
      entry.direction = 1;
      parsed.push_back(std::move(entry));
    }
    return true;
  });

  if (!read) {
    ESP_LOGW(TAG, "The config payload carried no readable registry");
    return false;
  }

  bool changed = parsed.size() != this->entries_.size();
  if (!changed) {
    for (size_t i = 0; i < parsed.size(); i++) {
      const Entry &was = this->entries_[i];
      const Entry &now = parsed[i];
      if (was.rid != now.rid || was.entity != now.entity || was.name != now.name ||
          was.domain != now.domain || was.dimmable != now.dimmable) {
        changed = true;
        break;
      }
    }
  }
  if (!changed)
    return false;

  /* Carry the polled state and the brightness sweep across, so that a rename
   * in Home Assistant does not blank every card on the page until the next
   * state poll answers. */
  for (auto &entry : parsed) {
    const Entry *previous = this->entry(entry.rid);
    if (previous != nullptr) {
      entry.state = previous->state;
      entry.pct = previous->pct;
      entry.direction = previous->direction;
    }
  }
  {
    LockGuard guard{this->lock_};
    this->entries_ = std::move(parsed);
  }
  ESP_LOGD(TAG, "The registry now carries %u element(s)", static_cast<unsigned>(this->entries_.size()));

  /* A device that has never been given a layout gets one the moment it is
   * given a registry, so that the room page is useful without a second,
   * undiscoverable step in a browser. */
  if (this->cards_.empty() && !this->entries_.empty()) {
    this->adopt_(this->default_layout_(), false);
    return true;
  }
  return true;
}

// -------------------------------------------------------------- the layout

bool MediaControllerGrid::can_place_(const std::vector<Card> &placed, const Card &card) {
  if (card.w() == 0 || card.h() == 0)
    return false;
  if (card.x() >= GRID_COLUMNS || card.y() >= GRID_ROWS)
    return false;
  /* Written as a subtraction against the bound rather than an addition, so
   * that a width large enough to wrap cannot pass: both operands are already
   * bounded by the checks above. */
  if (card.w() > GRID_COLUMNS - card.x())
    return false;
  if (card.h() > GRID_ROWS - card.y())
    return false;

  for (const auto &other : placed) {
    const bool overlaps = card.x() < other.x() + other.w() && other.x() < card.x() + card.w() &&
                          card.y() < other.y() + other.h() && other.y() < card.y() + card.h();
    if (overlaps)
      return false;
  }
  return true;
}

std::vector<Card> MediaControllerGrid::default_layout_() const {
  std::vector<Card> cards;
  uint8_t x = 0;
  uint8_t y = 0;

  for (const auto &entry : this->entries_) {
    if (y + DEFAULT_CARD_SPAN > GRID_ROWS)
      break;
    Card card{};
    card.rid = entry.rid;
    card.cell = static_cast<uint8_t>((x << 4) | y);
    card.span = static_cast<uint8_t>((DEFAULT_CARD_SPAN << 4) | DEFAULT_CARD_SPAN);
    cards.push_back(card);

    x = static_cast<uint8_t>(x + DEFAULT_CARD_SPAN);
    if (x + DEFAULT_CARD_SPAN > GRID_COLUMNS) {
      x = 0;
      y = static_cast<uint8_t>(y + DEFAULT_CARD_SPAN);
    }
  }
  return cards;
}

bool MediaControllerGrid::parse_layout_(const std::string &document, std::vector<Card> *out,
                                        uint16_t *dropped, std::string *error) const {
  if (document.empty()) {
    *error = "The layout document is empty.";
    return false;
  }

  bool version_ok = false;
  int version_seen = 0;
  uint16_t lost = 0;
  std::vector<Card> cards;

  const bool read = json::parse_json(document, [&](JsonObject root) -> bool {
    version_seen = root["v"] | 0;
    if (version_seen != LAYOUT_VERSION)
      return true;
    version_ok = true;

    for (JsonObject element : root["cards"].as<JsonArray>()) {
      if (cards.size() >= MAX_CARDS) {
        lost++;
        continue;
      }
      uint32_t rid = 0;
      if (!parse_rid(element["rid"].as<const char *>(), &rid)) {
        lost++;
        continue;
      }
      const int x = element["x"] | -1;
      const int y = element["y"] | -1;
      const int w = element["w"] | -1;
      const int h = element["h"] | -1;
      if (x < 0 || y < 0 || w < 1 || h < 1 || x > 15 || y > 15 || w > 15 || h > 15) {
        lost++;
        continue;
      }

      Card card{};
      card.rid = rid;
      card.cell = static_cast<uint8_t>((x << 4) | y);
      card.span = static_cast<uint8_t>((w << 4) | h);
      card.icon = icon_from_name(element["icon"].as<const char *>());
      /* A card that does not fit, or that lands on one already placed, is
       * dropped rather than moved. Where it should go instead is a question
       * only the person editing the grid can answer, and quietly relocating
       * it would hide the fact that the document was wrong. */
      if (!can_place_(cards, card)) {
        lost++;
        continue;
      }
      cards.push_back(card);
    }
    return true;
  });

  if (!read) {
    *error = "The layout is not a JSON object.";
    return false;
  }
  if (!version_ok) {
    /* Refused rather than guessed at: reading a format this build does not
     * know would move somebody's cards without telling them. */
    char buffer[96];
    snprintf(buffer, sizeof(buffer), "The layout is version %d; this device writes version %u.", version_seen,
             LAYOUT_VERSION);
    *error = buffer;
    return false;
  }

  *dropped = lost;
  *out = std::move(cards);
  return true;
}

std::string MediaControllerGrid::layout_json() const {
#ifdef USE_PSRAM
  json::SpiRamAllocator allocator;
  JsonDocument doc(&allocator);
#else
  JsonDocument doc;
#endif
  JsonObject root = doc.to<JsonObject>();
  root["v"] = LAYOUT_VERSION;
  root["cols"] = GRID_COLUMNS;
  root["rows"] = GRID_ROWS;
  JsonArray cards = root["cards"].to<JsonArray>();
  for (const auto &card : this->cards_) {
    JsonObject item = cards.add<JsonObject>();
    item["x"] = card.x();
    item["y"] = card.y();
    item["w"] = card.w();
    item["h"] = card.h();
    item["rid"] = format_rid(card.rid);
    /* The card type is deliberately not written: it follows from the domain
     * of the registry element behind the rid, so storing it would be a second
     * copy of a fact that can change in Home Assistant. */
    if (card.icon > 0 && card.icon <= ICON_COUNT)
      item["icon"] = ICON_NAMES[card.icon - 1];
  }

  std::string out;
  serialize_to(doc, &out);
  return out;
}

void MediaControllerGrid::adopt_(std::vector<Card> &&cards, bool backup) {
  {
    LockGuard guard{this->lock_};
    this->cards_ = std::move(cards);
  }
  this->save_to_flash_();
  if (backup && this->backup_) {
    /* The copy in Home Assistant is what makes a wiped device recover its own
     * arrangement, and it is never allowed to fail a save: a layout that is
     * on the device is saved, whatever Home Assistant did. */
    this->backup_(this->layout_json());
  }
  if (this->redraw_)
    this->redraw_();
}

void MediaControllerGrid::save_to_flash_() {
  LayoutBlob blob{};
  blob.version = BLOB_VERSION;
  blob.columns = GRID_COLUMNS;
  blob.rows = GRID_ROWS;
  blob.count = static_cast<uint8_t>(this->cards_.size());
  for (size_t i = 0; i < this->cards_.size(); i++)
    blob.cards[i] = this->cards_[i];

  if (!this->pref_.save(&blob)) {
    ESP_LOGW(TAG, "Could not write the layout to flash");
    return;
  }
  ESP_LOGD(TAG, "Wrote %u card(s) to flash", blob.count);
}

void MediaControllerGrid::load_from_flash_() {
  LayoutBlob blob{};
  if (!this->pref_.load(&blob))
    return;
  if (blob.version != BLOB_VERSION || blob.columns != GRID_COLUMNS || blob.rows != GRID_ROWS) {
    /* Laid out for a different build. Rather than reshape it silently, leave
     * the device with no layout: it draws the default one from the registry,
     * and the copy in Home Assistant is one button away. */
    ESP_LOGW(TAG, "The stored layout is for a %ux%u grid of format %u; ignoring it", blob.columns, blob.rows,
             blob.version);
    return;
  }

  const uint8_t count = blob.count <= MAX_CARDS ? blob.count : MAX_CARDS;
  LockGuard guard{this->lock_};
  for (uint8_t i = 0; i < count; i++) {
    if (can_place_(this->cards_, blob.cards[i]))
      this->cards_.push_back(blob.cards[i]);
  }
  ESP_LOGD(TAG, "Read %u card(s) from flash", static_cast<unsigned>(this->cards_.size()));
}

void MediaControllerGrid::restore_finished(bool ok, const std::string &document,
                                           const std::string &message) {
  if (!ok) {
    LockGuard guard{this->lock_};
    this->restore_state_ = RESTORE_FAILED;
    this->restore_message_ = message.empty() ? "Home Assistant holds no copy of this layout." : message;
    ESP_LOGW(TAG, "Restore failed: %s", this->restore_message_.c_str());
    return;
  }

  std::vector<Card> cards;
  uint16_t dropped = 0;
  std::string error;
  if (!this->parse_layout_(document, &cards, &dropped, &error)) {
    LockGuard guard{this->lock_};
    this->restore_state_ = RESTORE_FAILED;
    this->restore_message_ = error;
    ESP_LOGW(TAG, "Restore failed: %s", error.c_str());
    return;
  }

  {
    LockGuard guard{this->lock_};
    this->restore_state_ = RESTORE_OK;
    this->restore_message_.clear();
    if (dropped > 0) {
      char buffer[80];
      snprintf(buffer, sizeof(buffer), "Dropped %u card(s) that did not fit this grid.", dropped);
      this->restore_message_ = buffer;
    }
  }
  /* Not backed up again: this document *is* what Home Assistant holds, and
   * writing it straight back would be a round trip for no change. */
  this->adopt_(std::move(cards), false);
  ESP_LOGI(TAG, "Restored %u card(s) from Home Assistant", static_cast<unsigned>(this->cards_.size()));
}

// ---------------------------------------------------------- state routing

std::string MediaControllerGrid::state_request() const {
  std::string list;
  size_t count = 0;
  for (const auto &entry : this->entries_) {
    bool drawn = false;
    for (const auto &card : this->cards_) {
      if (card.rid == entry.rid) {
        drawn = true;
        break;
      }
    }
    if (!drawn || entry.domain == DOMAIN_OTHER)
      continue;
    if (count > 0)
      list += ',';
    list += '\'';
    list += entry.entity;
    list += '\'';
    count++;
  }
  if (count == 0)
    return std::string();

  /* One template renders every card's state in one request. The alternative —
   * one `/api/states/<entity>` per card — is sixty-four blocking requests on
   * ESP-IDF for a page that has to stay responsive, which is exactly what
   * AGENTS.md forbids in the hot path. */
  std::string tmpl = "{% for e in [" + list + "] %}{{ states(e) }}|{% endfor %}";

  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  root["template"] = tmpl;
  std::string out;
  serialize_to(doc, &out);
  return out;
}

void MediaControllerGrid::apply_states(const std::string &rendered) {
  size_t at = 0;
  for (auto &entry : this->entries_) {
    bool drawn = false;
    for (const auto &card : this->cards_) {
      if (card.rid == entry.rid) {
        drawn = true;
        break;
      }
    }
    if (!drawn || entry.domain == DOMAIN_OTHER)
      continue;

    const size_t end = rendered.find('|', at);
    if (end == std::string::npos) {
      /* Fewer fields than entities means the answer was cut short. Leave the
       * remaining cards showing what they last knew rather than blanking a
       * page because one poll was truncated. */
      break;
    }
    entry.state = rendered.substr(at, end - at);
    at = end + 1;
  }
}

// ------------------------------------------------------------- the server

namespace {

enum Route : uint8_t {
  ROUTE_NONE = 0,
  ROUTE_EDITOR,
  ROUTE_ENTITIES,
  ROUTE_GET_LAYOUT,
  ROUTE_SAVE_LAYOUT,
  ROUTE_RESTORE_LAYOUT,
  ROUTE_SKINS,
  ROUTE_SET_SKIN,
};

/* Seven routes, and this is all of them. There is deliberately no catch-all
 * and no path that takes an entity, a service or a URL from the caller: this
 * server has no password, so what it cannot express is the security model.
 *
 * The T560 panel spells the three writes PUT and DELETE. Here they are POST,
 * because ESPHome's ESP-IDF web server registers URI handlers for GET, POST
 * and OPTIONS only: a PUT never reaches a handler at all. Same seven
 * questions, same bodies, the verbs the platform can carry. */
Route route_of(http_method method, const char *url) {
  if (method == HTTP_GET) {
    if (strcmp(url, "/") == 0)
      return ROUTE_EDITOR;
    if (strcmp(url, "/api/entities") == 0)
      return ROUTE_ENTITIES;
    if (strcmp(url, "/api/layout") == 0)
      return ROUTE_GET_LAYOUT;
    if (strcmp(url, "/api/skins") == 0)
      return ROUTE_SKINS;
    return ROUTE_NONE;
  }
  if (method == HTTP_POST) {
    if (strcmp(url, "/api/layout") == 0)
      return ROUTE_SAVE_LAYOUT;
    if (strcmp(url, "/api/layout/restore") == 0)
      return ROUTE_RESTORE_LAYOUT;
    if (strcmp(url, "/api/skin") == 0)
      return ROUTE_SET_SKIN;
    return ROUTE_NONE;
  }
  return ROUTE_NONE;
}

}  // namespace

bool MediaControllerGrid::canHandle(AsyncWebServerRequest *request) const {
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);
  return route_of(request->method(), url.c_str()) != ROUTE_NONE;
}

void MediaControllerGrid::handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len,
                                     size_t index, size_t total) {
  if (index == 0) {
    this->body_.clear();
    if (total <= MAX_DOCUMENT_BYTES)
      this->body_.reserve(total);
  }
  if (this->body_.size() + len > MAX_DOCUMENT_BYTES) {
    /* Truncated on purpose, and the handler below then refuses the document
     * rather than acting on half of one. */
    return;
  }
  this->body_.append(reinterpret_cast<const char *>(data), len);
}

void MediaControllerGrid::handleRequest(AsyncWebServerRequest *request) {
  char buffer[AsyncWebServerRequest::URL_BUF_SIZE];
  const StringRef url = request->url_to(buffer);

  switch (route_of(request->method(), url.c_str())) {
    case ROUTE_EDITOR:
      this->handle_editor_(request);
      break;
    case ROUTE_ENTITIES:
      this->handle_entities_(request);
      break;
    case ROUTE_GET_LAYOUT:
      this->handle_get_layout_(request);
      break;
    case ROUTE_SAVE_LAYOUT:
      this->handle_save_layout_(request);
      break;
    case ROUTE_RESTORE_LAYOUT:
      this->handle_restore_layout_(request);
      break;
    case ROUTE_SKINS:
      this->handle_skins_(request);
      break;
    case ROUTE_SET_SKIN:
      this->handle_set_skin_(request);
      break;
    default:
      send_error_(request, 404, "No such route.");
      break;
  }
  this->body_.clear();
}

void MediaControllerGrid::send_json_(AsyncWebServerRequest *request, int code, const std::string &body) {
  request->send(code, "application/json; charset=utf-8", body.c_str());
}

void MediaControllerGrid::send_error_(AsyncWebServerRequest *request, int code,
                                      const std::string &message) {
  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  root["error"] = message;
  std::string body;
  serialize_to(doc, &body);
  send_json_(request, code, body);
}

void MediaControllerGrid::handle_editor_(AsyncWebServerRequest *request) {
  if (this->editor_ == nullptr || this->editor_size_ == 0) {
    send_error_(request, 500, "The editor is missing from this build.");
    return;
  }
  auto *response = request->beginResponse(200, "text/html; charset=utf-8", this->editor_, this->editor_size_);
  response->addHeader("Content-Encoding", "gzip");
  request->send(response);
}

void MediaControllerGrid::handle_entities_(AsyncWebServerRequest *request) {
  /* The body is built under the lock and sent without it: a send takes as
   * long as the client needs to read it, and holding the lock across one
   * would stall the main loop for exactly that long. */
  std::string body;
  {
    LockGuard guard{this->lock_};
#ifdef USE_PSRAM
    json::SpiRamAllocator allocator;
    JsonDocument doc(&allocator);
#else
    JsonDocument doc;
#endif
    JsonObject root = doc.to<JsonObject>();

    /* Straight out of the payload this device has already parsed. The editor
     * never reaches Home Assistant and this route never does either. */
    JsonArray entities = root["entities"].to<JsonArray>();
    for (const auto &entry : this->entries_) {
      JsonObject item = entities.add<JsonObject>();
      item["rid"] = format_rid(entry.rid);
      item["entity"] = entry.entity;
      item["name"] = entry.name;
      item["domain"] = entry.domain == DOMAIN_LIGHT    ? "light"
                       : entry.domain == DOMAIN_SWITCH ? "switch"
                                                       : "other";
      item["brightness"] = entry.dimmable;
      item["color_temp"] = false;
    }

    /* The artwork this build carries, so the editor offers exactly what the
     * device can draw rather than a list written down twice. */
    JsonArray icons = root["icons"].to<JsonArray>();
    for (size_t i = 0; i < ICON_COUNT; i++)
      icons.add(ICON_NAMES[i]);

    JsonObject grid = root["grid"].to<JsonObject>();
    grid["cols"] = GRID_COLUMNS;
    grid["rows"] = GRID_ROWS;

    /* What this client can and cannot do, so that the editor offers no
     * control the device would ignore. Colours are absent because the room
     * cards of this firmware are drawn from the interface's own palette, and
     * a per-card colour would be a second owner for something the room page
     * already has one for. */
    JsonObject supports = root["supports"].to<JsonObject>();
    supports["colors"] = false;

    /* How the last restore ended. It lives here, on the route that answers
     * "what is this device's situation", because the restore itself cannot
     * answer synchronously: fetching the copy from Home Assistant blocks the
     * main loop, so it is done there and reported back here. */
    JsonObject restore = root["restore"].to<JsonObject>();
    restore["state"] = this->restore_state_ == RESTORE_PENDING  ? "pending"
                       : this->restore_state_ == RESTORE_OK     ? "ok"
                       : this->restore_state_ == RESTORE_FAILED ? "failed"
                                                                : "idle";
    restore["message"] = this->restore_message_;

    serialize_to(doc, &body);
  }
  send_json_(request, 200, body);
}

void MediaControllerGrid::handle_get_layout_(AsyncWebServerRequest *request) {
  std::string document;
  {
    LockGuard guard{this->lock_};
    document = this->layout_json();
  }
  send_json_(request, 200, document);
}

void MediaControllerGrid::handle_save_layout_(AsyncWebServerRequest *request) {
  std::vector<Card> cards;
  uint16_t dropped = 0;
  std::string error;

  if (!this->parse_layout_(this->body_, &cards, &dropped, &error)) {
    send_error_(request, 400, error);
    return;
  }
  /* A layout that lost cards on the way in is refused rather than saved as
   * something the editor did not ask for. The editor already refuses to place
   * a card that does not fit, so this only catches another client. */
  if (dropped > 0) {
    char buffer[96];
    snprintf(buffer, sizeof(buffer), "%u card(s) are outside the grid or overlap another card.", dropped);
    send_error_(request, 400, buffer);
    return;
  }

  /* Whether a copy will be **sent**, which is all this can honestly say: the
   * writer posts it and does not wait for the answer, because an HTTP request
   * blocks the main loop on ESP-IDF. Restore is where a person finds out
   * whether the copy arrived. */
  const bool backed_up = static_cast<bool>(this->backup_);
  /* Writing to flash, redrawing LVGL and asking Home Assistant for anything
   * all belong to the main loop; this runs on the HTTP server task. */
  this->defer([this, cards]() mutable { this->adopt_(std::move(cards), true); });

  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  root["status"] = "ok";
  /* Whether a copy goes to Home Assistant is reported, never enforced. */
  root["backup"] = backed_up;
  std::string body;
  serialize_to(doc, &body);
  send_json_(request, 200, body);
}

void MediaControllerGrid::handle_restore_layout_(AsyncWebServerRequest *request) {
  if (!this->restore_) {
    send_error_(request, 409, "This device cannot reach Home Assistant.");
    return;
  }

  {
    LockGuard guard{this->lock_};
    this->restore_state_ = RESTORE_PENDING;
    this->restore_message_.clear();
  }
  this->defer([this]() { this->restore_(); });

  /* Answered immediately, because the fetch it starts blocks the main loop
   * and this task must not hold a socket open across it. The editor watches
   * `restore` on /api/entities for the outcome. */
  send_json_(request, 200, "{\"status\":\"queued\"}");
}

void MediaControllerGrid::handle_skins_(AsyncWebServerRequest *request) {
  std::string body;
  {
    LockGuard guard{this->lock_};
    JsonDocument doc;
    JsonObject root = doc.to<JsonObject>();
    /* Fixed at codegen time and never written at runtime, so it is inside the
     * lock only because everything else in this answer is. */
    JsonArray skins = root["skins"].to<JsonArray>();
    for (const auto &skin : this->skins_)
      skins.add(skin);

    /* The skin on screen, which is always one of the names above: Home
     * Assistant's choice once somebody has made one, and the select restored
     * from flash until then. */
    root["current"] = this->skin_;
    /* Whether this device was told which entity holds the skin. Without one
     * there is nothing to write, and the editor greys the control. */
    root["writable"] = this->skin_writable_;

    serialize_to(doc, &body);
  }
  send_json_(request, 200, body);
}

void MediaControllerGrid::handle_set_skin_(AsyncWebServerRequest *request) {
  std::string requested;
  json::parse_json(this->body_, [&requested](JsonObject root) -> bool {
    const char *value = root["skin"].as<const char *>();
    if (value != nullptr)
      requested = value;
    return true;
  });

  if (requested.empty()) {
    send_error_(request, 400, "No skin was named.");
    return;
  }
  /* An unknown name is refused rather than passed on, so this route cannot be
   * used to write an arbitrary value into an entity. */
  bool known = false;
  // skins_ is fixed at codegen time and never written at runtime, so it needs
  // no lock; skin_writable_ does.
  for (const auto &skin : this->skins_) {
    if (skin == requested) {
      known = true;
      break;
    }
  }
  if (!known) {
    send_error_(request, 400, "This device does not draw that skin.");
    return;
  }
  bool writable;
  {
    LockGuard guard{this->lock_};
    writable = this->skin_writable_;
  }
  if (!writable || !this->skin_writer_) {
    send_error_(request, 409, "Home Assistant has not named a skin entity for this device.");
    return;
  }

  this->defer([this, requested]() { this->skin_writer_(requested); });
  send_json_(request, 200, "{\"status\":\"ok\"}");
}

}  // namespace esphome::media_controller_grid
