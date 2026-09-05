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
const char *const ICON_NAMES[] = {"light-1", "light-2", "fan",
                                  "ac",      "weather", "blind"};
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
  if (strcmp(domain, "cover") == 0)
    return DOMAIN_COVER;
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
    case DOMAIN_COVER:
      return "cover";
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

/* Every labelled card of a known domain carries the value line: a reading
 * on a thermostat, weather, sensor or cover card, and ON/OFF on a light or
 * a switch card, where the state is the whole of the content. An element
 * whose domain this build cannot draw gets no line rather than a wrong
 * one. */
bool card_shows_reading(const Card &card, const Entry *entry) {
  return entry != nullptr && entry->domain != DOMAIN_OTHER && card_is_labelled(card);
}

bool card_shows_compact(const Card &card, const Entry *entry) {
  return entry != nullptr &&
         (entry->domain == DOMAIN_SENSOR || entry->domain == DOMAIN_WEATHER) &&
         !card_is_labelled(card);
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

/* What the card calls each Home Assistant weather state; defined below next
 * to card_reading. Declared here because the hero and sub lines above need
 * it first. */
static std::string humanize_weather_condition(const std::string &condition);

/* One forecast row as a large weather card writes it, in the T560 colours:
 * the weekday in muted blue-grey, the high in orange and the low in blue.
 * The `#rrggbb ...#` spans need `lv_label_set_recolor` on the label that
 * draws them; without it they read as literal text. */
std::string forecast_text_colored(const Entry &entry, uint8_t day) {
  if (day >= entry.fc_count || entry.fc_dow[day] < 0 || entry.fc_dow[day] > 6)
    return std::string();
  std::string text = "#a9c3e0 ";
  text += WEEKDAYS[entry.fc_dow[day]];
  text += "# #f5a83d ";
  text += format_temperature(entry.fc_high[day]);
  text += "#";
  if (!std::isnan(entry.fc_low[day])) {
    text += "/#8fb8e8 ";
    text += format_temperature(entry.fc_low[day]);
    text += "#";
  }
  return text;
}

/* The hero temperature of a large weather card, the way the T560 panel draws
 * it: the current temperature large, on its own line. Empty until the first
 * state answer, and "--" when the answer carried no reading at all. */
std::string weather_hero(const Entry &entry) {
  if (!entry_is_known(entry))
    return std::string();
  if (!std::isnan(entry.weather_temp))
    return format_temperature(entry.weather_temp);
  if (humanize_weather_condition(entry.state).empty() && std::isnan(entry.weather_humidity))
    return "--";
  return std::string();
}

/* The line under the hero: the condition with the humidity where one is
 * reported, the same " / " separator card_reading uses, for the same reason:
 * the Roboto face this firmware builds only carries the glyphs it was built
 * with. */
std::string weather_sub(const Entry &entry) {
  if (!entry_is_known(entry))
    return std::string();
  const bool has_humidity = !std::isnan(entry.weather_humidity);
  const std::string condition = humanize_weather_condition(entry.state);
  if (!condition.empty() && has_humidity) {
    return condition + " / " +
           std::to_string(static_cast<int>(entry.weather_humidity + 0.5f)) + "%";
  }
  if (!condition.empty())
    return condition;
  if (has_humidity)
    return std::to_string(static_cast<int>(entry.weather_humidity + 0.5f)) + "%";
  return std::string();
}

bool entry_is_known(const Entry &entry) {
  return !entry.state.empty() && entry.state != "unavailable" && entry.state != "unknown";
}

bool entry_is_reading(const Entry &entry) {
  /* A weather block and a sensor block are readings rather than controls:
   * a tap on them acts on nothing, exactly like the T560 panel. */
  return entry.domain == DOMAIN_WEATHER || entry.domain == DOMAIN_SENSOR;
}

bool entry_is_on(const Entry &entry) {
  if (!entry_is_known(entry))
    return false;
  /* A reading is never on, so it never draws the active border a button
   * does. */
  if (entry_is_reading(entry))
    return false;
  /* A blind is on when it is not shut: Home Assistant reports `open`,
   * `closed`, `opening` and `closing`. One that is opening is on its way to
   * being open and reads as on, one that is closing is still open until it
   * is not, and only `closed` reads as off. */
  if (entry.domain == DOMAIN_COVER)
    return entry.state == "open" || entry.state == "opening" || entry.state == "closing";
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

  /* A lamp and a socket say ON and OFF. It is the whole of what the card
   * has to say, and the reason the value line exists on cards that carry
   * no other reading. */
  if (entry.domain == DOMAIN_LIGHT || entry.domain == DOMAIN_SWITCH) {
    return entry_is_on(entry) ? "ON" : "OFF";
  }

  /* A blind says whether it is shut. The percentage is not said here: the
   * panel profile strips `position` before it reaches the device, so there
   * is no half way this card could honestly report. */
  if (entry.domain == DOMAIN_COVER) {
    return entry_is_on(entry) ? "OPEN" : "CLOSED";
  }

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

/* How long a card's display name may be, in characters and not in bytes.
 * It is the integration's `MAX_NAME_LENGTH`, checked here as well so that the
 * editor is told at once rather than after a round trip, and so that nothing
 * unbounded is ever put on the wire. Characters, because the name is UTF-8
 * and a limit in bytes would let a Latin name be twice as long as a Cyrillic
 * one for no reason a person could see. */
static const size_t MAX_CARD_NAME_CHARS = 64;

/* Whitespace at either end is dropped, so a field somebody cleared by typing
 * a space is the same as one they emptied. Only ASCII whitespace: the byte
 * values below cannot appear inside a multi-byte UTF-8 sequence, so this is
 * safe on any script without knowing anything about it. */
static std::string trim_name(const std::string &value) {
  size_t start = 0;
  size_t end = value.size();
  auto space = [](char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
  };
  while (start < end && space(value[start]))
    start++;
  while (end > start && space(value[end - 1]))
    end--;
  return value.substr(start, end - start);
}

/* Control characters are refused rather than stripped: a newline in a tile
 * label is somebody pasting the wrong thing, and quietly keeping half of what
 * they pasted is worse than telling them. A continuation byte of a UTF-8
 * sequence is always >= 0x80, so testing bytes is enough. */
static bool name_is_printable(const std::string &value) {
  for (unsigned char c : value) {
    if (c < 0x20 || c == 0x7F)
      return false;
  }
  return true;
}

/* How many characters a name is. Continuation bytes are 10xxxxxx and are not
 * counted, so "Настільна лампа" is fifteen characters here and not
 * twenty-nine. */
static size_t name_characters(const std::string &value) {
  size_t count = 0;
  for (unsigned char c : value) {
    if ((c & 0xC0) != 0x80)
      count++;
  }
  return count;
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
                "  Skins: %u, of which %u carry a preview\n"
                "  Card artwork: %u in flash as a fallback, %u downloadable, "
                "up to %u held at %ux%u",
                url.c_str(), this->port_, GRID_COLUMNS, GRID_ROWS, GRID_CELL_PX,
                static_cast<unsigned>(this->cards_.size()),
                static_cast<unsigned>(this->skins_.size()),
                static_cast<unsigned>(this->previews_.size()),
                static_cast<unsigned>(ICON_COUNT),
                static_cast<unsigned>(this->catalog_.size()),
                static_cast<unsigned>(ICON_CACHE_LIMIT), ICON_PIXELS, ICON_PIXELS);
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
      /* The picture the user chose for this element, as a catalog
       * identifier. Absent means they chose none and the domain decides. An
       * identifier of a shape the catalog could not have published is
       * dropped here rather than carried around and refused later. */
      const char *icon = element["icon"].as<const char *>();
      if (icon != nullptr && icon_id_is_sane_(icon))
        entry.icon = icon;
      entry.domain = domain_from_name(element["domain"].as<const char *>());
      entry.togglable = false;
      entry.dimmable = false;
      entry.settable_temp = false;
      JsonArray controls = element["controls"].as<JsonArray>();
      for (JsonVariant control : controls) {
        const char *value = control.as<const char *>();
        /* A control this build does not know is ignored rather than treated
         * as an error, so that a future one can be added without breaking a
         * device already in the field. That rule is what lets a card type
         * ship on its own: this list grows by one name per contract version
         * and a device in the field skips the names it has not learned.
         *
         * `position` and `stop` are ignored on purpose rather than unknown:
         * the panel profile strips them before they reach the device, and
         * this firmware has no gesture left to spend on a slider — the long
         * press already sweeps brightness on a lamp and the setpoint on a
         * thermostat. A cover is therefore a toggle card here. */
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
          was.icon != now.icon || was.domain != now.domain || was.togglable != now.togglable ||
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
  /* The registry decides which picture each card wants, so a registry that
   * moved is the other half of the question `adopt_` asks after a layout
   * change. Without this a card whose icon was just chosen in the editor
   * would leave the previous picture evictable and the new one unpinned. */
  this->refresh_icon_pins();
  return true;
}

// --------------------------------------------------------------- card art
//
// Everything that turns a catalog identifier into pixels LVGL can blit. The
// pictures are downloaded from Home Assistant and never compiled in; the six
// in flash are the fallback underneath, for a device that has not been
// answered yet and for one that cannot be.

bool MediaControllerGrid::icon_id_is_sane_(const std::string &id) {
  /* The same shape the integration publishes: lowercase, digits and hyphens,
   * bounded. It is checked here as well as there because this value ends up
   * in a URL, and a client trusts a payload no further than it has to.
   * Nothing that fails this is stored, asked for, or put on the wire. */
  if (id.empty() || id.size() > ICON_ID_MAX)
    return false;
  for (size_t i = 0; i < id.size(); i++) {
    const char c = id[i];
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))
      continue;
    /* A hyphen anywhere but first, so that "-x" is not an identifier. */
    if (c == '-' && i > 0)
      continue;
    return false;
  }
  return true;
}

bool MediaControllerGrid::catalog_has_(const std::string &id) const {
  for (const auto &icon : this->catalog_) {
    if (icon.id == id)
      return true;
  }
  return false;
}

bool MediaControllerGrid::ingest_icon_catalog(const std::string &document) {
  std::vector<CatalogIcon> parsed;
  uint32_t revision = 0;

  const bool read = json::parse_json(document, [&](JsonObject root) -> bool {
    revision = static_cast<uint32_t>(root["revision"] | 0);
    JsonArray icons = root["icons"].as<JsonArray>();
    if (icons.isNull())
      return false;
    for (JsonObject element : icons) {
      const char *id = element["id"].as<const char *>();
      if (id == nullptr)
        continue;
      CatalogIcon icon{};
      icon.id = id;
      if (!icon_id_is_sane_(icon.id))
        continue;
      const char *label = element["label"].as<const char *>();
      icon.label = label != nullptr ? label : icon.id;
      parsed.push_back(std::move(icon));
      /* A catalog larger than the cache is still a usable catalog — the
       * editor lists it and the cards use a handful of it — but one large
       * enough to be a memory problem in itself is not. */
      if (parsed.size() >= 512)
        break;
    }
    return true;
  });

  if (!read) {
    ESP_LOGW(TAG, "The icon catalog was not readable");
    return false;
  }

  bool changed = revision != this->catalog_revision_ || parsed.size() != this->catalog_.size();
  if (!changed) {
    for (size_t i = 0; i < parsed.size(); i++) {
      if (parsed[i].id != this->catalog_[i].id) {
        changed = true;
        break;
      }
    }
  }
  if (!changed)
    return false;

  {
    LockGuard guard{this->lock_};
    this->catalog_ = std::move(parsed);
    this->catalog_revision_ = revision;
    /* A catalog that moved is reason to try a picture that failed once more:
     * the likeliest cause of a failure is an integration that did not carry
     * the file, and the likeliest cause of a new catalog is one that now
     * does. */
    for (auto &icon : this->icons_) {
      if (icon->pixels == nullptr)
        icon->failed_ms = 0;
    }
  }
  ESP_LOGD(TAG, "The icon catalog carries %u picture(s), revision %u",
           static_cast<unsigned>(this->catalog_.size()),
           static_cast<unsigned>(this->catalog_revision_));
  return true;
}

std::string MediaControllerGrid::card_icon_id(const Card &card, const Entry *entry) const {
  /* The registry first: it is where the editor writes, where a second panel
   * reads the same answer, and what a wiped device gets back. */
  if (entry != nullptr && !entry->icon.empty())
    return entry->icon;
  /* Then the name a layout document written by an older editor still carries.
   * It is honoured for as long as it is there and never written again, so a
   * card keeps the picture somebody chose for it until the first time anybody
   * chooses another one. */
  if (card.icon > 0 && card.icon <= ICON_COUNT)
    return ICON_NAMES[card.icon - 1];
  return {};
}

CachedIcon *MediaControllerGrid::find_icon_(const std::string &id) {
  for (auto &icon : this->icons_) {
    if (icon->id == id)
      return icon.get();
  }
  return nullptr;
}

bool MediaControllerGrid::evict_icon_() {
  /* A row that failed is the cheapest thing to lose: it holds no pixels and
   * remembers only that an identifier did not arrive. */
  for (size_t i = 0; i < this->icons_.size(); i++) {
    if (this->icons_[i]->pixels == nullptr && !this->icons_[i]->pinned) {
      this->icons_.erase(this->icons_.begin() + i);
      return true;
    }
  }
  /* Then the picture no card is drawing that was looked at longest ago. A
   * pinned row is never a candidate: LVGL holds the address of its descriptor
   * for as long as a widget draws it, and freeing one would be a crash rather
   * than a stale picture. */
  size_t oldest = this->icons_.size();
  uint32_t oldest_age = 0;
  const uint32_t now = millis();
  for (size_t i = 0; i < this->icons_.size(); i++) {
    if (this->icons_[i]->pinned)
      continue;
    const uint32_t age = now - this->icons_[i]->used_ms;
    if (oldest == this->icons_.size() || age > oldest_age) {
      oldest = i;
      oldest_age = age;
    }
  }
  if (oldest == this->icons_.size())
    return false;
  ESP_LOGD(TAG, "Dropping the cached icon %s", this->icons_[oldest]->id.c_str());
  RAMAllocator<uint8_t> allocator{};
  allocator.deallocate(this->icons_[oldest]->pixels, ICON_PIXEL_BYTES);
  this->icons_.erase(this->icons_.begin() + oldest);
  return true;
}

CachedIcon *MediaControllerGrid::reserve_icon_(const std::string &id) {
  if (CachedIcon *existing = this->find_icon_(id))
    return existing;
  if (this->icons_.size() >= ICON_CACHE_LIMIT && !this->evict_icon_())
    return nullptr;
  std::unique_ptr<CachedIcon> icon(new CachedIcon());
  icon->id = id;
  icon->used_ms = millis();
  this->icons_.push_back(std::move(icon));
  return this->icons_.back().get();
}

void MediaControllerGrid::refresh_icon_pins() {
  LockGuard guard{this->lock_};
  for (auto &icon : this->icons_)
    icon->pinned = false;
  const uint32_t now = millis();
  for (const auto &card : this->cards_) {
    const Entry *entry = nullptr;
    for (const auto &candidate : this->entries_) {
      if (candidate.rid == card.rid) {
        entry = &candidate;
        break;
      }
    }
    const std::string id = this->card_icon_id(card, entry);
    if (id.empty())
      continue;
    if (CachedIcon *cached = this->find_icon_(id)) {
      cached->pinned = cached->pixels != nullptr;
      cached->used_ms = now;
    }
  }
}

std::string MediaControllerGrid::next_wanted_icon() {
  LockGuard guard{this->lock_};
  if (!this->icon_in_flight_.empty())
    return {};

  const uint32_t now = millis();
  auto worth_asking = [&](const std::string &id) -> bool {
    if (id.empty() || !icon_id_is_sane_(id))
      return false;
    /* Only what Home Assistant says it has. A legacy per-card name this build
     * carries in flash but the catalog does not publish is drawn from flash
     * and never asked for. */
    if (!this->catalog_has_(id))
      return false;
    const CachedIcon *cached = this->find_icon_(id);
    if (cached == nullptr)
      return true;
    if (cached->pixels != nullptr)
      return false;
    /* Tried and failed. Left alone for a while rather than retried every
     * loop: Home Assistant being down must not become a request per tick. */
    return cached->failed_ms == 0 || now - cached->failed_ms >= ICON_RETRY_MS;
  };

  /* What the room page is drawing comes first, always. */
  for (const auto &card : this->cards_) {
    const Entry *entry = nullptr;
    for (const auto &candidate : this->entries_) {
      if (candidate.rid == card.rid) {
        entry = &candidate;
        break;
      }
    }
    const std::string id = this->card_icon_id(card, entry);
    if (worth_asking(id)) {
      this->icon_in_flight_ = id;
      return id;
    }
  }

  // Editor previews go directly to Home Assistant, never into the LVGL cache.
  return {};
}

bool MediaControllerGrid::icon_downloaded(const std::string &id, const std::string &payload) {
  LockGuard guard{this->lock_};
  if (this->icon_in_flight_ == id)
    this->icon_in_flight_.clear();
  if (!icon_id_is_sane_(id))
    return false;

  /* Asked before anything is stored, because after it is stored the answer
   * would be the same for a picture nothing draws. A card that is already
   * drawing this identifier from the cache needs no rebuild either: it is
   * only the ones still on the fallback that have something to gain. */
  bool wanted_by_card = false;
  for (const auto &card : this->cards_) {
    const Entry *entry = nullptr;
    for (const auto &candidate : this->entries_) {
      if (candidate.rid == card.rid) {
        entry = &candidate;
        break;
      }
    }
    if (this->card_icon_id(card, entry) == id) {
      wanted_by_card = true;
      break;
    }
  }
  const CachedIcon *before = this->find_icon_(id);
  const bool was_drawn = before != nullptr && before->pixels != nullptr;

  CachedIcon *cached = this->reserve_icon_(id);
  if (cached == nullptr) {
    /* Every row is pinned, so there is nowhere to put this without freeing a
     * buffer LVGL is drawing. The card keeps the built-in artwork, which is
     * exactly what the fallback is for. */
    ESP_LOGD(TAG, "No room to cache the icon %s", id.c_str());
    return false;
  }

  /* Refused rather than half-stored. A body of the wrong length, of the wrong
   * magic, or of the wrong size is a download that was interrupted, a proxy
   * that answered something else, or a variant this build cannot draw, and
   * every one of them would be a buffer of the wrong shape handed to LVGL. */
  const bool usable = payload.size() == ICON_PAYLOAD_BYTES && memcmp(payload.data(), "MCI1", 4) == 0 &&
                      static_cast<uint8_t>(payload[4]) == (ICON_PIXELS & 0xFF) &&
                      static_cast<uint8_t>(payload[5]) == ((ICON_PIXELS >> 8) & 0xFF);
  if (!usable) {
    ESP_LOGW(TAG, "The icon %s arrived as %u byte(s) and was refused", id.c_str(),
             static_cast<unsigned>(payload.size()));
    if (cached->pixels == nullptr)
      cached->failed_ms = millis();
    return false;
  }

  /* The default allocator prefers external RAM and falls back to internal,
   * which is exactly the order this wants: a hundred kilobytes of card
   * artwork out of internal RAM would be felt everywhere else on this
   * device, and a device with no PSRAM should still draw its cards. */
  RAMAllocator<uint8_t> allocator{};
  uint8_t *pixels = cached->pixels;
  if (pixels == nullptr) {
    pixels = allocator.allocate(ICON_PIXEL_BYTES);
    if (pixels == nullptr) {
      ESP_LOGW(TAG, "No memory for the icon %s", id.c_str());
      cached->failed_ms = millis();
      return false;
    }
  }
  memcpy(pixels, payload.data() + ICON_HEADER_BYTES, ICON_PIXEL_BYTES);
  cached->pixels = pixels;
  cached->failed_ms = 0;
  cached->used_ms = millis();
#ifdef USE_LVGL
  cached->dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
  cached->dsc.header.cf = LV_COLOR_FORMAT_ARGB8888;
  cached->dsc.header.flags = 0;
  cached->dsc.header.w = ICON_PIXELS;
  cached->dsc.header.h = ICON_PIXELS;
  cached->dsc.header.stride = ICON_PIXELS * 4;
  cached->dsc.header.reserved_2 = 0;
  cached->dsc.data_size = ICON_PIXEL_BYTES;
  cached->dsc.data = pixels;
#endif
  /* Pinned here as well as in refresh_icon_pins: this is the moment a card's
   * picture becomes evictable, and it must not be evicted between here and
   * the rebuild that hands it to a widget. */
  cached->pinned = cached->pinned || wanted_by_card;
  ESP_LOGD(TAG, "Cached the icon %s (%u of %u rows in use)", id.c_str(),
           static_cast<unsigned>(this->icons_.size()), static_cast<unsigned>(ICON_CACHE_LIMIT));
  return wanted_by_card && !was_drawn;
}

#ifdef USE_LVGL
const lv_image_dsc_t *MediaControllerGrid::icon_for(const Card &card, const Entry *entry) {
  const std::string id = this->card_icon_id(card, entry);
  if (id.empty())
    return nullptr;
  LockGuard guard{this->lock_};
  CachedIcon *cached = this->find_icon_(id);
  if (cached == nullptr || cached->pixels == nullptr)
    return nullptr;
  cached->used_ms = millis();
  /* Pinned the moment it is drawn as well as when the pins are recomputed:
   * this is the call that hands LVGL the address, so this is where the
   * promise not to free it starts. */
  cached->pinned = true;
  return &cached->dsc;
}
#endif

void MediaControllerGrid::card_write_finished(bool ok, const std::string &message) {
  LockGuard guard{this->lock_};
  this->card_state_ = ok ? CARD_OK : CARD_FAILED;
  this->card_message_ = message;
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

    JsonArray cards_payload = root["cards"].as<JsonArray>();
    for (JsonObject element : cards_payload) {
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
  /* Which pictures are in use has just changed, and a picture in use may
   * never be evicted from under the widget drawing it. */
  this->refresh_icon_pins();
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

/* One number out of a room_states array. JSON null — an attribute the entity
 * does not report — reads as no reading rather than as zero, and so does a
 * value of any other shape this build did not ask for. */
static float room_number(JsonVariant value) {
  if (value.is<float>())
    return value.as<float>();
  if (value.is<int>())
    return static_cast<float>(value.as<int>());
  const char *text = value.as<const char *>();
  if (text == nullptr)
    return NAN;
  return parse_number(text);
}

bool MediaControllerGrid::apply_room_states(const std::string &room_states) {
  bool changed = false;
  if (room_states.empty())
    return false;

  /* Two floats are the same reading when they are equal, or when neither is
   * a reading at all. */
  auto same_number = [](float was, float now) {
    return (std::isnan(was) && std::isnan(now)) || was == now;
  };

  const bool read = json::parse_json(room_states, [&](JsonObject root) -> bool {
    for (auto &entry : this->entries_) {
      JsonArray item = root[format_rid(entry.rid).c_str()].as<JsonArray>();
      if (item.isNull())
        continue;

      /* The state itself. Explicitly unknown when the integration names no
       * usable value, so a deleted entity cannot keep a stale one. */
      const char *raw = item[0].as<const char *>();
      std::string state =
          (raw != nullptr && *raw != '\0') ? raw : "unknown";

      float ambient = entry.ambient;
      float setpoint = entry.setpoint;
      float weather_temp = entry.weather_temp;
      float weather_humidity = entry.weather_humidity;
      std::string unit = entry.sensor_unit;
      if (entry.domain == DOMAIN_CLIMATE) {
        ambient = room_number(item[1]);
        setpoint = room_number(item[2]);
      } else if (entry.domain == DOMAIN_WEATHER) {
        weather_temp = room_number(item[1]);
        weather_humidity = room_number(item[2]);
      } else if (entry.domain == DOMAIN_SENSOR) {
        const char *text = item[1].as<const char *>();
        unit = text != nullptr ? text : "";
      }

      if (entry.state == state && same_number(entry.ambient, ambient) &&
          same_number(entry.setpoint, setpoint) &&
          same_number(entry.weather_temp, weather_temp) &&
          same_number(entry.weather_humidity, weather_humidity) &&
          entry.sensor_unit == unit) {
        continue;
      }
      entry.state = state;
      entry.ambient = ambient;
      entry.setpoint = setpoint;
      entry.weather_temp = weather_temp;
      entry.weather_humidity = weather_humidity;
      entry.sensor_unit = unit;
      changed = true;
    }
    return true;
  });

  return read && changed;
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

/* What a card icon is addressed as. The identifier after it is compared with
 * the pictures this device has downloaded and never used to address anything;
 * there is no filesystem here to traverse. No extension: the two panels serve
 * different image formats out of what each of them happens to hold, and the
 * shared editor page asks for the icon rather than for a file. */
const char *const ICON_PREFIX = "/icons/";

enum Route : uint8_t {
  ROUTE_NONE = 0,
  ROUTE_EDITOR,
  ROUTE_SKIN_PREVIEW,
  ROUTE_ICON,
  ROUTE_ENTITIES,
  ROUTE_GET_LAYOUT,
  ROUTE_SAVE_LAYOUT,
  ROUTE_RESTORE_LAYOUT,
  ROUTE_SKINS,
  ROUTE_SET_SKIN,
  ROUTE_SET_CARD,
};

/* Ten routes, and this is all of them. There is deliberately no catch-all
 * and no path that takes an entity, a service or a URL from the caller: this
 * server has no password, so what it cannot express is the security model.
 *
 * The two added for card artwork keep that rule rather than bending it. The
 * picture route serves what this device has already downloaded for its own
 * cards and can reach nothing else; the card route changes the name and icon
 * of an element this device is already drawing, and every value in it is
 * checked here and again by the integration that owns the registry.
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
    if (strncmp(url, ICON_PREFIX, strlen(ICON_PREFIX)) == 0)
      return ROUTE_ICON;
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
    if (strcmp(url, "/api/card") == 0)
      return ROUTE_SET_CARD;
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
    case ROUTE_ICON:
      this->handle_icon_(request, url.c_str());
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
    case ROUTE_SET_CARD:
      this->handle_set_card_(request);
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

/* One catalog picture, for the editor page.
 *
 * It is served out of the same bounded cache the cards draw from, wrapped in
 * a BMP header on the way out. That is why there is no proxy here and no
 * second download: the device has already fetched these pixels for its own
 * use, and a browser reads a 32-bit BMP with an alpha mask without a decoder,
 * a library, or anything from outside the house.
 *
 * The identifier in the path is compared with what is in the cache and never
 * used to address anything: there is no filesystem here to traverse. An icon
 * this device has not downloaded yet is a 404, and the editor then drops the
 * image and keeps the name — exactly what it already does for a skin this
 * build carries no picture of.
 */
void MediaControllerGrid::handle_icon_(AsyncWebServerRequest *request, const char *url) {
  const std::string id = url + strlen(ICON_PREFIX);
  if (!icon_id_is_sane_(id)) {
    send_error_(request, 404, "No such icon.");
    return;
  }

  /* Built under the lock and sent without it: a send takes as long as the
   * client needs to read it, and holding the lock across one would stall the
   * main loop for exactly that long. */
  std::vector<uint8_t> bmp;
  {
    LockGuard guard{this->lock_};
    const CachedIcon *cached = this->find_icon_(id);
    if (cached != nullptr && cached->pixels != nullptr) {
      /* A BITMAPV4HEADER, because that is the only BMP shape browsers agree
       * carries alpha. The pixels need no rearranging at all: they are
       * already B, G, R, A in memory, which is exactly what the masks below
       * say. */
      const uint32_t header = 14 + 108;
      bmp.assign(header + ICON_PIXEL_BYTES, 0);
      uint8_t *out = bmp.data();
      auto put32 = [out](size_t at, uint32_t value) {
        out[at] = value & 0xFF;
        out[at + 1] = (value >> 8) & 0xFF;
        out[at + 2] = (value >> 16) & 0xFF;
        out[at + 3] = (value >> 24) & 0xFF;
      };
      out[0] = 'B';
      out[1] = 'M';
      put32(2, header + ICON_PIXEL_BYTES);
      put32(10, header);
      put32(14, 108);          /* BITMAPV4HEADER */
      put32(18, ICON_PIXELS);  /* width */
      /* A negative height is a top-down bitmap, which is the order the pixels
       * are already in. Flipping them here instead would be forty memcpys per
       * request for a picture that is going to be drawn the right way up. */
      put32(22, static_cast<uint32_t>(-static_cast<int32_t>(ICON_PIXELS)));
      out[26] = 1;   /* planes */
      out[28] = 32;  /* bits per pixel */
      put32(30, 3);  /* BI_BITFIELDS */
      put32(34, ICON_PIXEL_BYTES);
      put32(54, 0x00FF0000);  /* red */
      put32(58, 0x0000FF00);  /* green */
      put32(62, 0x000000FF);  /* blue */
      put32(66, 0xFF000000);  /* alpha */
      put32(70, 0x57696E20);  /* 'Win ', the sRGB colour space */
      memcpy(out + header, cached->pixels, ICON_PIXEL_BYTES);
    }
  }

  if (bmp.empty()) {
    /* Compatibility route for cached artwork only. Browser requests must
     * never start a device download; previews now come from Home Assistant. */
    send_error_(request, 404, "This device has not downloaded that icon yet.");
    return;
  }

  auto *response = request->beginResponse(200, "image/bmp", bmp.data(), bmp.size());
  /* The pictures change only when the integration is upgraded, and the
   * editor asks for one per catalog row on every render. */
  response->addHeader("Cache-Control", "max-age=3600");
  request->send(response);
}

/* The display name and icon of one card.
 *
 * This is the only route that ends in a write to Home Assistant's own data,
 * and it is deliberately the narrowest one here. It can change the name and
 * the picture of an element **this device already draws**, and there is no
 * path through it that names an entity, calls a service, adds an element, or
 * reaches anything the registry does not already carry. Everything it accepts
 * is checked twice: here, and again by the integration, which is the side
 * that actually owns the registry.
 *
 * A key that is absent means "leave this alone" and a key that is present
 * means "set it to this, including to nothing". The difference matters: a
 * card whose name field simply shows the Home Assistant entity's own name
 * must not have that name stored as a custom one just because somebody
 * changed its icon, or it would stop following the entity through a rename.
 */
void MediaControllerGrid::handle_set_card_(AsyncWebServerRequest *request) {
  std::string rid_text;
  std::string name;
  std::string icon;
  bool has_name = false;
  bool has_icon = false;

  const bool read = json::parse_json(this->body_, [&](JsonObject root) -> bool {
    const char *value = root["rid"].as<const char *>();
    if (value != nullptr)
      rid_text = value;
    if (!root["name"].isNull()) {
      has_name = true;
      const char *text = root["name"].as<const char *>();
      name = text != nullptr ? text : "";
    }
    if (!root["icon"].isNull()) {
      has_icon = true;
      const char *text = root["icon"].as<const char *>();
      icon = text != nullptr ? text : "";
    }
    return true;
  });
  if (!read) {
    send_error_(request, 400, "The request is not a JSON object.");
    return;
  }
  if (!has_name && !has_icon) {
    send_error_(request, 400, "There is nothing to change.");
    return;
  }

  uint32_t rid = 0;
  if (!parse_rid(rid_text.c_str(), &rid)) {
    send_error_(request, 400, "That is not a registry identifier.");
    return;
  }

  if (has_name) {
    name = trim_name(name);
    if (!name_is_printable(name)) {
      send_error_(request, 400, "A name cannot contain control characters.");
      return;
    }
    if (name_characters(name) > MAX_CARD_NAME_CHARS) {
      char buffer[80];
      snprintf(buffer, sizeof(buffer), "A name may be at most %u characters.",
               static_cast<unsigned>(MAX_CARD_NAME_CHARS));
      send_error_(request, 400, buffer);
      return;
    }
  }

  /* The element has to be one this device is already drawing, and the icon
   * one Home Assistant says it publishes. Those two checks are the whole of
   * why this route is not a way into a registry the caller knows nothing
   * about. */
  bool known_card = false;
  bool known_icon = true;
  {
    LockGuard guard{this->lock_};
    known_card = this->entry(rid) != nullptr;
    if (has_icon && !icon.empty())
      known_icon = this->catalog_has_(icon);
  }
  if (!known_card) {
    send_error_(request, 404, "This device draws no such card.");
    return;
  }
  if (!known_icon) {
    send_error_(request, 400, "Home Assistant does not publish that icon.");
    return;
  }

  const bool writable = static_cast<bool>(this->card_writer_);
  if (writable) {
    /* The body is built here rather than in the script that sends it, for the
     * same reason the layout document is: what may be said is this
     * component's business, and the other half of the seam only has to put a
     * string on the wire. */
    JsonDocument doc;
    JsonObject root = doc.to<JsonObject>();
    root["rid"] = rid_text;
    if (has_name)
      root["name"] = name;
    if (has_icon)
      root["icon"] = icon;
    std::string request_body;
    serialize_to(doc, &request_body);

    {
      LockGuard guard{this->lock_};
      this->card_state_ = CARD_PENDING;
      this->card_message_.clear();
    }
    /* Deferred, because the write reaches Home Assistant over HTTP and that
     * blocks the main loop; this runs on the HTTP server task. The editor
     * watches `card` on /api/entities for the outcome, exactly as it watches
     * `restore`. */
    this->defer([this, request_body]() { this->card_writer_(request_body); });
  }

  JsonDocument doc;
  JsonObject root = doc.to<JsonObject>();
  root["status"] = "ok";
  /* Whether the change is on its way to Home Assistant is reported, never
   * enforced: a device that has not paired yet still has an editor, and the
   * person using it should be told which of the two happened. */
  root["synced"] = writable;
  std::string body;
  serialize_to(doc, &body);
  send_json_(request, 200, body);
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
      /* What the user chose for this element, so that the editor can show
       * the choice rather than guess at it from the picture on screen. */
      item["icon"] = entry.icon;
      item["domain"] = domain_to_name(entry.domain);
      item["brightness"] = entry.dimmable;
      item["color_temp"] = false;
      item["target_temperature"] = entry.settable_temp;
    }

    /* The artwork Home Assistant publishes, so the editor offers exactly
     * what a card can be given rather than a list written down twice. It is
     * the integration's catalog and not this build's flash: adding a picture
     * there must not mean reflashing every device in the house.
     *
     * Empty before the catalog has been fetched, and empty for good on a
     * device that has never paired. The editor then offers Automatic alone,
     * which is the honest answer: there is nothing else this device could be
     * told to draw. */
    root["icon_preview_base"] = this->icon_preview_base_;
    JsonArray icons = root["icons"].to<JsonArray>();
    for (const auto &icon : this->catalog_) {
      JsonObject row = icons.add<JsonObject>();
      row["id"] = icon.id;
      row["label"] = icon.label;
    }

    /* What the editor may not exceed, so the limit is enforced in one place
     * and read in the other rather than written down twice. */
    JsonObject limits = root["limits"].to<JsonObject>();
    limits["name"] = MAX_CARD_NAME_CHARS;

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

    /* How the last card edit ended, and it lives here for the same reason
     * the restore does: the write reaches Home Assistant over HTTP, which
     * blocks the main loop, so it cannot be answered inside the request that
     * asked for it. */
    JsonObject card = root["card"].to<JsonObject>();
    card["state"] = this->card_state_ == CARD_PENDING  ? "pending"
                    : this->card_state_ == CARD_OK     ? "ok"
                    : this->card_state_ == CARD_FAILED ? "failed"
                                                       : "idle";
    card["message"] = this->card_message_;

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
