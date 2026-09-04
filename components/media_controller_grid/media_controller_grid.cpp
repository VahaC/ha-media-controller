#include "media_controller_grid.h"

#include "esphome/components/json/json_util.h"
#include "esphome/components/network/util.h"
#include "esphome/core/log.h"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace esphome::media_controller_grid {

static const char *const TAG = "room_grid";

/* The artwork this build carries. The names are the document's, shared with
 * the T560 panel; the two builds do not carry the same set, which is exactly
 * why `GET /api/entities` reports it rather than the editor writing it down a
 * second time. */
const char *const ICON_NAMES[] = {"light-1", "light-2", "fan", "ac", "weather"};
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
  if (strcmp(domain, "climate") == 0)
    return DOMAIN_CLIMATE;
  if (strcmp(domain, "weather") == 0)
    return DOMAIN_WEATHER;
  if (strcmp(domain, "sensor") == 0)
    return DOMAIN_SENSOR;
  return DOMAIN_OTHER;
}

static const char *domain_to_name(uint8_t domain) {
  switch (domain) {
    case DOMAIN_LIGHT:
      return "light";
    case DOMAIN_SWITCH:
      return "switch";
    case DOMAIN_CLIMATE:
      return "climate";
    case DOMAIN_WEATHER:
      return "weather";
    case DOMAIN_SENSOR:
      return "sensor";
    default:
      return "other";
  }
}

/* A temperature as a card writes one: no unit letter, because the payload
 * names none, and one decimal only where there is one to show. */
static std::string format_temperature(float value) {
  char buffer[16];
  if (fabsf(value - roundf(value)) < 0.05f) {
    snprintf(buffer, sizeof(buffer), "%.0f\u00b0", roundf(value));
  } else {
    snprintf(buffer, sizeof(buffer), "%.1f\u00b0", value);
  }
  return std::string(buffer);
}

/* A number out of the rendered template answer. Home Assistant writes
 * "None" for an attribute an entity does not have, which is not a number
 * and must leave the field alone rather than becoming zero. */
static float parse_number(const std::string &text) {
  if (text.empty() || text == "None" || text == "unknown" || text == "unavailable")
    return NAN;
  char *end = nullptr;
  const float value = strtof(text.c_str(), &end);
  return end == text.c_str() ? NAN : value;
}

bool card_is_labelled(const Card &card) { return card.w() >= 2 && card.h() >= 2; }

bool card_shows_reading(const Card &card, const Entry *entry) {
  return entry != nullptr &&
         (entry->domain == DOMAIN_CLIMATE || entry->domain == DOMAIN_WEATHER ||
          entry->domain == DOMAIN_SENSOR) &&
         card_is_labelled(card);
}

bool card_shows_compact(const Card &card, const Entry *entry) {
  return entry != nullptr && entry->domain == DOMAIN_SENSOR && !card_is_labelled(card);
}

/* A large weather card lists the coming days under its current reading, as
 * many rows as it has cells for: a 2x3 card fits two rows and a taller one
 * more, up to FORECAST_DAYS. Anything smaller, or anything but weather,
 * gets none — there is no room a row could honestly fit in. */
uint8_t card_forecast_rows(const Card &card, const Entry *entry) {
  if (entry == nullptr || entry->domain != DOMAIN_WEATHER || !card_is_labelled(card))
    return 0;
  if (card.h() < 3)
    return 0;
  const uint8_t rows = static_cast<uint8_t>(card.h() - 1);
  return rows > FORECAST_DAYS ? FORECAST_DAYS : rows;
}

static const char *const WEEKDAYS[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};

std::string forecast_text(const Entry &entry, uint8_t day) {
  if (day >= entry.fc_count || entry.fc_dow[day] < 0 || entry.fc_dow[day] > 6)
    return std::string();
  std::string text = WEEKDAYS[entry.fc_dow[day]];
  text += " " + format_temperature(entry.fc_high[day]);
  if (!std::isnan(entry.fc_low[day]))
    text += "/" + format_temperature(entry.fc_low[day]);
  return text;
}

bool entry_is_known(const Entry &entry) {
  return !entry.state.empty() && entry.state != "unavailable" && entry.state != "unknown";
}

bool entry_is_on(const Entry &entry) {
  if (!entry_is_known(entry))
    return false;
  /* A weather block and a sensor block are readings rather than controls:
   * they are never on, so they never draw the active border a button does. */
  if (entry.domain == DOMAIN_WEATHER || entry.domain == DOMAIN_SENSOR)
    return false;
  return entry.domain == DOMAIN_CLIMATE ? entry.state != "off" : entry.state == "on";
}

/* What the card calls each Home Assistant weather state. The states are a
 * closed vocabulary ("partlycloudy" is one word), so a table says it right
 * where capitalising the raw state says "Partlycloudy". Anything unlisted
 * is drawn as it arrived rather than dropped. */
static std::string humanize_weather_condition(const std::string &condition) {
  static const struct {
    const char *state;
    const char *label;
  } LABELS[] = {
      {"clear-night", "Clear night"}, {"cloudy", "Cloudy"},
      {"fog", "Fog"},                 {"hail", "Hail"},
      {"lightning", "Thunderstorm"},  {"lightning-rainy", "Thunderstorm"},
      {"partlycloudy", "Partly cloudy"}, {"pouring", "Pouring rain"},
      {"rainy", "Rain"},              {"snowy", "Snow"},
      {"snowy-rainy", "Sleet"},       {"sunny", "Sunny"},
      {"windy", "Windy"},             {"windy-variant", "Windy"},
      {"exceptional", "Exceptional"},
  };
  for (const auto &row : LABELS) {
    if (condition == row.state)
      return std::string(row.label);
  }
  std::string out;
  bool capitalize = true;
  for (char c : condition) {
    if (c == '_' || c == '-' || c == ' ') {
      out += ' ';
      capitalize = true;
    } else if (capitalize) {
      out += static_cast<char>(toupper(static_cast<unsigned char>(c)));
      capitalize = false;
    } else {
      out += c;
    }
  }
  return out;
}

std::string card_reading(const Entry &entry) {
  if (!entry_is_known(entry))
    return std::string();

  /* A sensor block says its value with its unit: the name on the card says
   * what it is, this line says what it reads. A sensor that reported no
   * unit, or one whose state is not a number at all, still draws the bare
   * value rather than nothing. */
  if (entry.domain == DOMAIN_SENSOR) {
    if (entry.state.empty())
      return std::string();
    if (!entry.sensor_unit.empty())
      return entry.state + " " + entry.sensor_unit;
    return entry.state;
  }

  /* A weather block says what the sky is doing and how warm it is. It is a
   * reading rather than a control: ON and OFF would be the wrong words
   * here. The slash before the humidity is the same one a thermostat uses
   * below, for the same reason: the Roboto face this firmware builds only
   * carries the glyphs it was built with. */
  if (entry.domain == DOMAIN_WEATHER) {
    const bool has_temp = !std::isnan(entry.weather_temp);
    const bool has_humidity = !std::isnan(entry.weather_humidity);
    const std::string condition = humanize_weather_condition(entry.state);
    std::string reading;
    if (has_temp && !condition.empty())
      reading = format_temperature(entry.weather_temp) + " " + condition;
    else if (has_temp)
      reading = format_temperature(entry.weather_temp);
    else if (!condition.empty())
      reading = condition;
    else if (has_humidity)
      reading = std::to_string(static_cast<int>(entry.weather_humidity + 0.5f)) + "%";
    if (has_humidity && !reading.empty() && (has_temp || !condition.empty())) {
      reading += " / " +
                 std::to_string(static_cast<int>(entry.weather_humidity + 0.5f)) + "%";
    }
    return reading;
  }

  /* The room first and the setpoint after it, which is the order a
   * thermostat is read in. The separator is a slash and not an arrow
   * because the Roboto face this firmware builds carries no U+2192, and a
   * glyph a font does not have cannot be added to it.
   *
   * The room temperature is drawn whether the thermostat is running or not,
   * because it is true either way. The **setpoint** is not: a thermostat
   * that is off is heading nowhere, and leaving the number it used to be set
   * to on the card would read as something it is doing. The card's border
   * already says which of the two it is. */
  const bool running = entry_is_on(entry);
  const bool has_ambient = !std::isnan(entry.ambient);
  const bool has_setpoint = running && !std::isnan(entry.setpoint);
  if (has_ambient && has_setpoint)
    return format_temperature(entry.ambient) + " / " + format_temperature(entry.setpoint);
  if (has_ambient)
    return format_temperature(entry.ambient);
  if (has_setpoint)
    return "set " + format_temperature(entry.setpoint);
  return std::string();
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

std::string MediaControllerGrid::editor_url() const {
  /* The listener is bound on every interface, so this only has to name one
   * address a phone on that network can reach. IPv6 is passed over rather
   * than bracketed: this address is read by a person off a device page on a
   * house network, and it is the v4 one they can type. A device that is not
   * on the network yet has none, and the caller reports nothing. */
  for (const auto &address : network::get_ip_addresses()) {
    if (!address.is_set() || !address.is_ip4())
      continue;
    char text[network::IP_ADDRESS_BUFFER_SIZE];
    address.str_to(text);
    std::string url = std::string("http://") + text;
    /* A browser assumes 80, and the address is shorter without it. */
    if (this->port_ != 80)
      url += ":" + std::to_string(this->port_);
    return url + "/";
  }
  return {};
}

void MediaControllerGrid::dump_config() {
  std::string url = this->editor_url();
  if (url.empty())
    url = "http://<device>/";
  ESP_LOGCONFIG(TAG,
                "Room grid:\n"
                "  Editor: %s (port %u)\n"
                "  Grid: %ux%u cells of %u px\n"
                "  Cards in flash: %u\n"
                "  Skins: %u, of which %u carry a preview",
                url.c_str(), this->port_, GRID_COLUMNS, GRID_ROWS, GRID_CELL_PX,
                static_cast<unsigned>(this->cards_.size()),
                static_cast<unsigned>(this->skins_.size()),
                static_cast<unsigned>(this->previews_.size()));
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
      entry.togglable = false;
      entry.dimmable = false;
      entry.settable_temp = false;
      for (JsonVariant control : element["controls"].as<JsonArray>()) {
        const char *value = control.as<const char *>();
        /* A control this build does not know is ignored rather than treated
         * as an error, so that a future one can be added without breaking a
         * device already in the field. That rule is what lets a card type
         * ship on its own: this list grows by one name per contract version
         * and a device in the field skips the names it has not learned. */
        if (value == nullptr)
          continue;
        if (strcmp(value, "toggle") == 0)
          entry.togglable = true;
        else if (strcmp(value, "brightness") == 0)
          entry.dimmable = true;
        else if (strcmp(value, "target_temperature") == 0)
          entry.settable_temp = true;
      }
      /* The bounds are sent only with the control, and Home Assistant's own
       * Celsius defaults are what it would have sent had the thermostat
       * reported nothing. They are not sanity-checked against a range: the
       * payload names no unit, so 7-35 and 45-95 are both ordinary. */
      entry.min_temp = element["min_temp"] | 7.0f;
      entry.max_temp = element["max_temp"] | 35.0f;
      entry.temp_step = element["target_temp_step"] | 0.5f;
      if (entry.max_temp <= entry.min_temp) {
        entry.min_temp = 7.0f;
        entry.max_temp = 35.0f;
      }
      if (entry.temp_step <= 0.0f)
        entry.temp_step = 0.5f;
      entry.ambient = NAN;
      entry.setpoint = NAN;
      entry.weather_temp = NAN;
      entry.weather_humidity = NAN;
      entry.fc_count = 0;
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
          was.domain != now.domain || was.togglable != now.togglable ||
          was.dimmable != now.dimmable || was.settable_temp != now.settable_temp ||
          was.min_temp != now.min_temp || was.max_temp != now.max_temp ||
          was.temp_step != now.temp_step) {
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
      entry.ambient = previous->ambient;
      entry.setpoint = previous->setpoint;
      entry.weather_temp = previous->weather_temp;
      entry.weather_humidity = previous->weather_humidity;
      entry.sensor_unit = previous->sensor_unit;
      entry.fc_count = previous->fc_count;
      for (uint8_t day = 0; day < previous->fc_count && day < FORECAST_DAYS; day++) {
        entry.fc_dow[day] = previous->fc_dow[day];
        entry.fc_high[day] = previous->fc_high[day];
        entry.fc_low[day] = previous->fc_low[day];
      }
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

std::vector<size_t> MediaControllerGrid::polled_order_() const {
  std::vector<size_t> plain;
  std::vector<size_t> thermostats;
  std::vector<size_t> weather;
  std::vector<size_t> sensors;

  for (size_t i = 0; i < this->entries_.size(); i++) {
    const Entry &entry = this->entries_[i];
    if (entry.domain == DOMAIN_OTHER)
      continue;
    bool drawn = false;
    for (const auto &card : this->cards_) {
      if (card.rid == entry.rid) {
        drawn = true;
        break;
      }
    }
    if (!drawn)
      continue;
    /* Thermostats last, and in a group of their own, because they are the
     * ones that render three fields instead of one. Two template loops keep
     * the *request* small — a loop over a list of entity IDs is about twenty
     * bytes an entity, and writing each entity into three function calls
     * would be a hundred and thirty. Weather blocks are a third group for
     * the same reason: the condition plus two attributes. Sensor blocks are
     * a fourth: the value plus its unit. */
    if (entry.domain == DOMAIN_CLIMATE)
      thermostats.push_back(i);
    else if (entry.domain == DOMAIN_WEATHER)
      weather.push_back(i);
    else if (entry.domain == DOMAIN_SENSOR)
      sensors.push_back(i);
    else
      plain.push_back(i);
  }
  plain.insert(plain.end(), thermostats.begin(), thermostats.end());
  plain.insert(plain.end(), weather.begin(), weather.end());
  plain.insert(plain.end(), sensors.begin(), sensors.end());
  return plain;
}

std::string MediaControllerGrid::state_request() const {
  std::string plain;
  std::string thermostats;
  std::string weather;
  std::string sensors;
  size_t count = 0;

  for (const size_t index : this->polled_order_()) {
    const Entry &entry = this->entries_[index];
    std::string &list = entry.domain == DOMAIN_CLIMATE  ? thermostats
                        : entry.domain == DOMAIN_WEATHER ? weather
                        : entry.domain == DOMAIN_SENSOR  ? sensors
                                                         : plain;
    if (!list.empty())
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
   * AGENTS.md forbids in the hot path. A card type added to the contract may
   * therefore add fields to this answer, and must never add a request.
   *
   * A thermostat renders three fields where everything else renders one:
   * the mode, the temperature the room is at, and the setpoint. They are
   * separated by `~` inside a card and by `|` between cards, and neither
   * character occurs in a Home Assistant state or in a number. A weather
   * block renders three fields of its own: the condition, the temperature
   * and the humidity. A sensor block renders two: the value and its unit. */
  std::string tmpl;
  if (!plain.empty())
    tmpl += "{% for e in [" + plain + "] %}{{ states(e) }}|{% endfor %}";
  if (!thermostats.empty()) {
    tmpl += "{% for e in [" + thermostats +
            "] %}{{ states(e) }}~{{ state_attr(e,'current_temperature') }}"
            "~{{ state_attr(e,'temperature') }}|{% endfor %}";
  }
  if (!weather.empty()) {
    tmpl += "{% for e in [" + weather +
            "] %}{{ states(e) }}~{{ state_attr(e,'temperature') }}"
            "~{{ state_attr(e,'humidity') }}|{% endfor %}";
  }
  if (!sensors.empty()) {
    tmpl += "{% for e in [" + sensors +
            "] %}{{ states(e) }}~{{ state_attr(e,'unit_of_measurement') }}|{% endfor %}";
  }

  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  root["template"] = tmpl;
  std::string out;
  serialize_to(doc, &out);
  return out;
}

void MediaControllerGrid::apply_states(const std::string &rendered) {
  size_t at = 0;

  for (const size_t index : this->polled_order_()) {
    Entry &entry = this->entries_[index];
    const size_t end = rendered.find('|', at);
    if (end == std::string::npos) {
      /* Fewer fields than entities means the answer was cut short. Leave the
       * remaining cards showing what they last knew rather than blanking a
       * page because one poll was truncated. */
      break;
    }
    const std::string field = rendered.substr(at, end - at);
    at = end + 1;

    if (entry.domain != DOMAIN_CLIMATE && entry.domain != DOMAIN_WEATHER &&
        entry.domain != DOMAIN_SENSOR) {
      entry.state = field;
      continue;
    }

    const size_t first = field.find('~');
    if (first == std::string::npos) {
      /* Not the shape that was asked for. Take it as a bare state rather
       * than discarding it: a thermostat card still reads as on or off, a
       * weather block still names the sky, and a sensor block still names
       * its value. */
      entry.state = field;
      continue;
    }
    const size_t second = field.find('~', first + 1);
    entry.state = field.substr(0, first);
    const std::string middle =
        field.substr(first + 1, second == std::string::npos ? std::string::npos
                                                            : second - first - 1);
    const std::string last =
        second == std::string::npos ? std::string() : field.substr(second + 1);
    if (entry.domain == DOMAIN_WEATHER) {
      entry.weather_temp = parse_number(middle);
      entry.weather_humidity = parse_number(last);
      continue;
    }
    if (entry.domain == DOMAIN_SENSOR) {
      /* Home Assistant renders a missing attribute as "None": no unit, not
       * a unit called None. */
      entry.sensor_unit =
          (middle.empty() || middle == "None" || middle == "unknown" ||
           middle == "unavailable")
              ? std::string()
              : middle;
      continue;
    }
    entry.ambient = parse_number(middle);
    if (second != std::string::npos)
      entry.setpoint = parse_number(last);
  }
}

// ------------------------------------------------------- the forecast

/* Days since the civil date, Howard Hinnant's algorithm. Only the weekday
 * is read out of it: 1970-01-01 was a Thursday, so the remainder against
 * that anchor is the day of the week. */
static int64_t days_from_civil(int year, unsigned month, unsigned day) {
  year -= month <= 2 ? 1 : 0;
  const int64_t era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(year - era * 400);
  const unsigned doy = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int64_t>(doe) - 719468;
}

/* The weekday of an ISO "YYYY-MM-DD" date, 0 for Sunday, or -1 for
 * anything that is not one. The forecast answers carry full timestamps;
 * only the date part is read. */
static int8_t weekday_from_date(const std::string &text) {
  if (text.size() < 10 || text[4] != '-' || text[7] != '-')
    return -1;
  for (uint8_t i = 0; i < 10; i++) {
    if (i == 4 || i == 7)
      continue;
    if (text[i] < '0' || text[i] > '9')
      return -1;
  }
  const int year = (text[0] - '0') * 1000 + (text[1] - '0') * 100 +
                   (text[2] - '0') * 10 + (text[3] - '0');
  const unsigned month =
      static_cast<unsigned>((text[5] - '0') * 10 + (text[6] - '0'));
  const unsigned day =
      static_cast<unsigned>((text[8] - '0') * 10 + (text[9] - '0'));
  if (month < 1 || month > 12 || day < 1 || day > 31)
    return -1;
  const int64_t days = days_from_civil(year, month, day);
  int dow = static_cast<int>((4 + days) % 7);
  if (dow < 0)
    dow += 7;
  return static_cast<int8_t>(dow);
}

/* One flat value out of one flat forecast object. Forecast items carry no
 * nesting, so the value runs to the next comma or closing brace; a string
 * runs to its closing quote. Anything else reads as absent. */
static float forecast_number(const std::string &item, const char *key) {
  const std::string quoted = std::string("\"") + key + "\"";
  const size_t at = item.find(quoted);
  if (at == std::string::npos)
    return NAN;
  const size_t colon = item.find(':', at + quoted.size());
  if (colon == std::string::npos)
    return NAN;
  char *end = nullptr;
  const float value = strtof(item.c_str() + colon + 1, &end);
  return end == item.c_str() + colon + 1 ? NAN : value;
}

static std::string forecast_string(const std::string &item, const char *key) {
  const std::string quoted = std::string("\"") + key + "\"";
  const size_t at = item.find(quoted);
  if (at == std::string::npos)
    return std::string();
  const size_t colon = item.find(':', at + quoted.size());
  if (colon == std::string::npos)
    return std::string();
  const size_t open = item.find('"', colon + 1);
  if (open == std::string::npos)
    return std::string();
  const size_t close = item.find('"', open + 1);
  if (close == std::string::npos)
    return std::string();
  return item.substr(open + 1, close - open - 1);
}

std::string MediaControllerGrid::forecast_request() const {
  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  JsonArray ids = root["entity_id"].to<JsonArray>();

  /* At most two: a day-by-day answer is kilobytes per entity, and the
   * response buffer is not the place to find that out. A house with more
   * weather blocks than that still converges — the next poll names the
   * next ones. */
  uint8_t count = 0;
  for (const auto &entry : this->entries_) {
    if (entry.domain != DOMAIN_WEATHER || count >= 2)
      continue;
    bool drawn = false;
    for (const auto &card : this->cards_) {
      if (card.rid == entry.rid) {
        drawn = true;
        break;
      }
    }
    if (!drawn)
      continue;
    ids.add(entry.entity);
    count++;
  }
  if (count == 0)
    return std::string();

  root["type"] = "daily";
  std::string out;
  serialize_to(doc, &out);
  return out;
}

void MediaControllerGrid::apply_forecast(const std::string &body) {
  /* With ?return_response the answer wraps per-entity forecasts under
   * "service_response"; without it the answer is a bare empty list. Each
   * element reads the forecast that follows its own name under that block,
   * so a stale "forecast" attribute on some other member never reads as
   * the forecast. */
  size_t scope = body.find("\"service_response\"");
  if (scope == std::string::npos)
    scope = 0;

  for (auto &entry : this->entries_) {
    if (entry.domain != DOMAIN_WEATHER)
      continue;

    /* The answer is keyed by entity ID, so each element reads the forecast
     * that follows its own name rather than the first array in the body. */
    const std::string needle = "\"" + entry.entity + "\"";
    const size_t named = body.find(needle, scope);
    if (named == std::string::npos)
      continue;
    const size_t listed = body.find("\"forecast\"", named);
    if (listed == std::string::npos)
      continue;
    const size_t opened = body.find('[', listed);
    if (opened == std::string::npos)
      continue;

    /* Forecast items are flat objects, so each one runs from its opening
     * brace to the next closing brace. The first item is today, which the
     * card already shows as its current reading; the rows start with the
     * day after it. */
    uint8_t kept = 0;
    uint8_t seen = 0;
    size_t pos = opened + 1;
    while (kept < FORECAST_DAYS) {
      const size_t obj = body.find('{', pos);
      if (obj == std::string::npos)
        break;
      const size_t shut = body.find(']', pos);
      if (shut != std::string::npos && shut < obj)
        break;
      const size_t close = body.find('}', obj + 1);
      if (close == std::string::npos)
        break;
      pos = close + 1;
      seen++;
      if (seen == 1)
        continue;
      const std::string item = body.substr(obj, close - obj + 1);
      const int8_t dow = weekday_from_date(forecast_string(item, "datetime"));
      const float high = forecast_number(item, "temperature");
      if (dow < 0 || std::isnan(high))
        continue;
      entry.fc_dow[kept] = dow;
      entry.fc_high[kept] = high;
      entry.fc_low[kept] = forecast_number(item, "templow");
      kept++;
    }
    entry.fc_count = kept;
  }
}

// ------------------------------------------------------------- the server

namespace {

/* What a skin preview is addressed as. The name between the two is compared
 * with the skins registered at codegen time; nothing here becomes a path. */
const char *const SKIN_PREFIX = "/skins/";
const char *const SKIN_SUFFIX = ".png";

enum Route : uint8_t {
  ROUTE_NONE = 0,
  ROUTE_EDITOR,
  ROUTE_SKIN_PREVIEW,
  ROUTE_ENTITIES,
  ROUTE_GET_LAYOUT,
  ROUTE_SAVE_LAYOUT,
  ROUTE_RESTORE_LAYOUT,
  ROUTE_SKINS,
  ROUTE_SET_SKIN,
};

/* Eight routes, and this is all of them. There is deliberately no catch-all
 * and no path that takes an entity, a service or a URL from the caller: this
 * server has no password, so what it cannot express is the security model.
 *
 * The T560 panel spells the three writes PUT and DELETE. Here they are POST,
 * because ESPHome's ESP-IDF web server registers URI handlers for GET, POST
 * and OPTIONS only: a PUT never reaches a handler at all. Same eight
 * questions, same bodies, the verbs the platform can carry. */
Route route_of(http_method method, const char *url) {
  if (method == HTTP_GET) {
    if (strcmp(url, "/") == 0)
      return ROUTE_EDITOR;
    if (strncmp(url, SKIN_PREFIX, strlen(SKIN_PREFIX)) == 0)
      return ROUTE_SKIN_PREVIEW;
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
    case ROUTE_SKIN_PREVIEW:
      this->handle_skin_preview_(request, url.c_str());
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

/* One skin's picture. The name in the path is compared with the skins this
 * build registered and is never used to address anything: there is no
 * filesystem here to traverse, and a name that matches nothing is a 404. */
void MediaControllerGrid::handle_skin_preview_(AsyncWebServerRequest *request, const char *url) {
  const std::string tail = url + strlen(SKIN_PREFIX);
  const size_t suffix = strlen(SKIN_SUFFIX);
  if (tail.size() <= suffix || tail.compare(tail.size() - suffix, suffix, SKIN_SUFFIX) != 0) {
    send_error_(request, 404, "No such route.");
    return;
  }

  const std::string skin = tail.substr(0, tail.size() - suffix);
  for (const auto &preview : this->previews_) {
    if (preview.skin != skin)
      continue;
    auto *response = request->beginResponse(200, "image/png", preview.data, preview.size);
    /* Linked into flash, so it changes only when the device is installed
     * again: worth caching for the life of the page rather than fetching it
     * on every render. */
    response->addHeader("Cache-Control", "max-age=86400");
    request->send(response);
    return;
  }
  /* A skin this build draws but carries no picture for lands here too. The
   * editor falls back to the name alone rather than a broken image. */
  send_error_(request, 404, "This device carries no picture of that skin.");
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
      item["domain"] = domain_to_name(entry.domain);
      item["brightness"] = entry.dimmable;
      item["color_temp"] = false;
      item["target_temperature"] = entry.settable_temp;
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
