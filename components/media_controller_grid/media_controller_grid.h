#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/core/preferences.h"
#include "esphome/components/web_server_base/web_server_base.h"

#ifdef USE_LVGL
/* Not <lvgl.h> directly: PlatformIO fails a build that merely mentions a
 * header it cannot resolve, even inside an #ifdef, and this proxy is the
 * workaround every other ESPHome component uses for exactly that. */
#include "esphome/components/lvgl/lvgl_proxy.h"
#endif

#include <cmath>
#include <functional>
#include <memory>
#include <string>
#include <vector>

/* The room-control grid of the paired ESP32-S3 firmware, and the editor it
 * serves for arranging it.
 *
 * Home Assistant says *what* this device can control — that is the registry
 * in the `entities` block of the config sensor, keyed on `rid`. This says
 * *where* each of those things is drawn and how large it is. The two are
 * deliberately separate: Home Assistant owns the registry and has no opinion
 * about the grid, and the grid is edited on the device itself, in the small
 * web page it serves. It is the same split, and the same document format, as
 * the T560 panel's `panel_grid.c`; see docs/CONTRACT.md and
 * clients/t560/src/panel_grid.h.
 *
 * **This component knows nothing about Home Assistant.** It never builds a
 * URL, never holds the token, and never performs a call. The four things it
 * needs from the other side of the wire — back a layout up, fetch the backup
 * again, write a skin, redraw the page — are `std::function`s the firmware
 * YAML installs at boot, and every one of them lands in a `cmd_` script
 * there. That is the same seam media-controller-ui.yaml describes, kept for
 * the same reason: what talks to Home Assistant lives in one half only.
 *
 * **There is no authentication on the web server.** That is a deliberate
 * decision and it is the reason for the shape of the API:
 *
 * - there are exactly eight routes and not one of them is a general proxy to
 *   Home Assistant. Nothing here can read a state, call an arbitrary service,
 *   or reach an entity the device does not already draw. The worst an
 *   unauthenticated caller can do is rearrange the room page of one device
 *   and ask Home Assistant for a skin this device already offers. The one
 *   route that takes a name from the caller — the skin preview — compares it
 *   with the skins registered at codegen time and never builds a path out of
 *   it;
 * - the registry is served from the payload the device has already parsed, so
 *   a request here never becomes a request to Home Assistant;
 * - the device's Home Assistant token never leaves it and is never readable
 *   through any route;
 * - `POST /api/layout/restore` puts back the copy Home Assistant holds. That
 *   is what makes the missing password survivable: the worst outcome is
 *   undone by one button.
 *
 * The listener is bound on every interface, which is what makes it reachable
 * from a phone. **Do not forward it through a router.** See
 * docs/ESP32_PAIRED_CONTROLLER.md.
 */

namespace esphome::media_controller_grid {

/* Eight columns of sixty pixels each, over the whole 480x480 screen. The size
 * is not a preference: a cell has to divide the screen exactly, and 60 is the
 * largest square that does it in a useful number of columns. It is also why
 * the grid page carries no header and no hint — with them the work area is
 * about 405 px and a row collapses to 50. */
static const uint8_t GRID_COLUMNS = 8;
static const uint8_t GRID_ROWS = 8;
static const uint16_t GRID_CELL_PX = 60;

/* One card per cell at the smallest size, which is also the `entity_limit` of
 * the `esp32_s3_panel` profile. The two agree on purpose: a registry larger
 * than the grid could not be laid out, and a grid larger than the registry
 * would have nothing to put in it. */
static const uint8_t MAX_CARDS = GRID_COLUMNS * GRID_ROWS;

/* How many days after today a weather block keeps. The card draws as many
 * rows as it has room for, up to this; a day that reports no low still
 * draws, with the high alone. */
static const uint8_t FORECAST_DAYS = 5;

/* The version written into the layout document, shared with the T560 panel.
 * A document naming another one is refused rather than guessed at: reading a
 * format this build does not know would quietly move somebody's cards. */
static const uint8_t LAYOUT_VERSION = 1;

/* The version of the binary record below. It is not the document version: the
 * document is a contract with the editor and the backup endpoint, and this is
 * private to this build's NVS blob. A blob written by another one is
 * discarded and the layout comes back from Home Assistant instead. */
static const uint8_t BLOB_VERSION = 1;

enum CardDomain : uint8_t {
  /* A domain no card is written for yet. The element still travels in the
   * payload, and a build that learns the card later finds it already
   * there. */
  DOMAIN_OTHER = 0,
  DOMAIN_LIGHT = 1,
  DOMAIN_SWITCH = 2,
  /* Contract version 7. A thermostat is drawn like the other two; what
   * differs is what its card says and what a long press moves. */
  DOMAIN_CLIMATE = 3,
  /* A weather block. It carries no controls at all — the empty list — and
   * is drawn as a reading rather than something a tap acts on. */
  DOMAIN_WEATHER = 4,
  /* A sensor block. It carries no controls at all — the empty list — and
   * is drawn as a reading rather than something a tap acts on. The value
   * is the entity state itself and the unit an attribute of the same poll,
   * so like weather it needs no bounds beside the reading. */
  DOMAIN_SENSOR = 5,
  /* Contract version 7. A blind, a shutter or an awning. This build draws
   * the toggle the integration offers it and reports OPEN/CLOSED; the
   * percentage and the stop button need a slider the firmware has no
   * gesture left for, so the panel profile already strips `position` and
   * `stop` before they reach the device. */
  DOMAIN_COVER = 6,
};

/* One card, in the shape that goes to flash.
 *
 * Eight bytes, so the whole grid is 512 bytes and fits in one NVS blob. That
 * is the reason for the packing rather than a plain struct of six fields: a
 * restoring string global is capped at 254 bytes by
 * `max_restore_data_length`, so the layout could never have been a string,
 * and a preference is sized once at compile time.
 *
 * `rid` is the registry element's identity parsed from its eight hex
 * characters, never an entity ID: a Home Assistant entity ID is renamed by
 * the user at will, and a layout keyed on one would scatter the next time
 * somebody tidied their entity IDs. */
struct Card {
  uint32_t rid;
  uint8_t cell;   /* x in the high nibble, y in the low nibble */
  uint8_t span;   /* width in the high nibble, height in the low nibble */
  uint8_t icon;   /* 0 draws the domain's own artwork; otherwise 1-based */
  uint8_t flags;  /* reserved; written as zero and ignored on read */

  uint8_t x() const { return this->cell >> 4; }
  uint8_t y() const { return this->cell & 0x0F; }
  uint8_t w() const { return this->span >> 4; }
  uint8_t h() const { return this->span & 0x0F; }
} __attribute__((packed));

static_assert(sizeof(Card) == 8, "A card is eight bytes; the NVS blob is sized on it");

/* What one NVS blob holds. The columns and rows are stored rather than
 * assumed so that a build which changes the grid can tell that what it read
 * was laid out for a different one. */
struct LayoutBlob {
  uint8_t version;
  uint8_t columns;
  uint8_t rows;
  uint8_t count;
  Card cards[MAX_CARDS];
} __attribute__((packed));

/* One registry element, as this device needs it. Only what a card draws or
 * addresses is kept: the payload also carries colour-temperature bounds, and
 * this build has no control to set one with. */
struct Entry {
  uint32_t rid;
  std::string entity;
  std::string name;
  uint8_t domain;
  /* What the payload said this element can be asked to do. `togglable` is
   * the `toggle` control, which every light and switch carries and a
   * thermostat may not; a card whose element has none does nothing on a tap
   * rather than calling a service Home Assistant would refuse. */
  bool togglable;
  bool dimmable;
  /* Contract version 7: the `target_temperature` control, and the range a
   * long press may move the setpoint in. The three numbers carry no unit,
   * exactly as the payload carries none. */
  bool settable_temp;
  float min_temp;
  float max_temp;
  float temp_step;
  /* The catalog identifier of the picture this element's cards draw, or
   * empty when the user chose none and the domain decides. It arrives in the
   * `entities` block beside the name, because which picture a lamp wears is
   * a fact about the lamp and not about where somebody dragged its card: a
   * house with two panels chooses it once, and a device that is wiped gets
   * it back with the registry. */
  std::string icon;
  /* The last state Home Assistant reported for `entity`, as the template
   * endpoint rendered it: "on", "off", "unavailable", or empty before the
   * first answer. For a thermostat it is the mode — "heat", "cool", "off" —
   * and every mode but "off" is a thermostat that is running. */
  std::string state;
  /* The temperature the room is at, from the same poll as `state`. NAN
   * until Home Assistant has answered once. */
  float ambient;
  /* The setpoint. It arrives from the poll and is also where a long-press
   * sweep leaves it, for the same reason `pct` is local: a thermostat
   * reports the setpoint it has, not the one the finger is heading for. It
   * is sent to Home Assistant once, when the finger comes off — a service
   * call per sweep tick would put a radio thermostat on the air ten times a
   * second for a value nobody has finished choosing. */
  float setpoint;
  /* A weather block. The condition is `state` itself ("sunny",
   * "partlycloudy", ...); the temperature and humidity arrive with the same
   * poll. Both are NAN until Home Assistant has answered once. */
  float weather_temp;
  float weather_humidity;
  /* A sensor block. The value is `state` itself ("21.5", "on", ...) and the
   * unit arrives with the same poll, as the entity's `unit_of_measurement`
   * attribute. Empty until Home Assistant has answered once. */
  std::string sensor_unit;
  /* The daily forecast behind a weather block: up to FORECAST_DAYS days
   * after today, each a weekday and a high, with a low of NAN where none
   * was reported. Empty until a forecast poll has answered once; drawn only
   * where the card is large enough for a row. */
  uint8_t fc_count;
  int8_t fc_dow[5];
  float fc_high[5];
  float fc_low[5];
  /* Where the brightness sweep of a long press is, in percent. It is local
   * and deliberately not read back: the same value the four fixed buttons
   * kept, for the same reason — a light reports the brightness it reached,
   * not the one the finger is heading for. */
  float pct;
  /* Which way a sweep is going, shared by brightness and by the setpoint:
   * only one card can be under a finger. */
  int8_t direction;
};

/* What a tile is built out of, and the order its children are created in.
 * The firmware builds a tile in one lambda and refreshes it in another, and
 * the second walks the children by index, so the rule lives here once
 * instead of being written down twice:
 *
 *   child 0     the icon, on every card (hidden on a compact card, on a
 *               sensor card, and on a weather card, where the value is what
 *               the card is for — unless a person chose an icon for it in
 *               the editor, which wins);
 *   child 1     the value, on every labelled card but an unknown one: the
 *               reading on a thermostat, sensor or cover card, and ON/OFF
 *               on a light or switch card. On a large weather card it is the
 *               hero temperature instead (see weather_hero);
 *   child 2     on a large weather card, the condition with the humidity
 *               (see weather_sub); on any other labelled card, the first of
 *               the children below — which, weather aside, is the name;
 *   children 3.. the daily forecast rows, on a large weather card only
 *               (children 2.. on every other card shape, where they never
 *               exist and the name follows the value directly);
 *   last child  the name, on any labelled card and on a compact card
 *               that has room for it beside the value. On a large weather
 *               card it heads the card from the top; on every other card it
 *               sits at the bottom.
 */
bool card_is_labelled(const Card &card);
bool card_shows_reading(const Card &card, const Entry *entry);
/* Whether this card is too small for the labelled layout above: 1x1, 2x1
 * and every other card below two cells in either direction. A sensor or a
 * weather block below that size still says its value: the name goes on top
 * and the value under it, and where both do not fit the name is dropped
 * and the value stays, because the value outranks the name. */
bool card_shows_compact(const Card &card, const Entry *entry);
/* How many forecast rows this card was built with: large weather cards get
 * one per cell past the second, up to FORECAST_DAYS, and everything else
 * gets none. */
uint8_t card_forecast_rows(const Card &card, const Entry *entry);

/* Whether Home Assistant has said anything about this element at all, and
 * whether what it said means "on".
 *
 * They are two questions because a card has three states and not two: an
 * element that is unavailable, or that has not been polled yet, must not
 * read as off — off is a fact and that is the absence of one.
 *
 * A light and a switch say "on" and everything else is off. A thermostat
 * does not: its state is the mode it is in — heat, cool, auto, dry, fan_only
 * — and every one of them but "off" is a thermostat that is running. A
 * cover is open when it is not shut: Home Assistant reports `open`,
 * `closed`, `opening` and `closing`, one that is moving towards open reads
 * as on, and only `closed` reads as off. */
bool entry_is_known(const Entry &entry);
bool entry_is_on(const Entry &entry);
/* Whether this element is a reading rather than a control: a weather block
 * or a sensor block. A tap on one acts on nothing, exactly like the T560
 * panel — it never shows a pressed state and never calls a service. */
bool entry_is_reading(const Entry &entry);
/* One forecast row as a card writes it ("Sat 22°/14°", or the high alone
 * where no low was reported). Empty when the card holds no such day. */
std::string forecast_text(const Entry &entry, uint8_t day);
/* The same row in the T560 colours (weekday muted, high orange, low blue),
 * as `#rrggbb ...#` spans for a label with recolor enabled. */
std::string forecast_text_colored(const Entry &entry, uint8_t day);
/* The hero temperature and the condition line of a large weather card, the
 * way the T560 panel draws them: the temperature large on its own line, the
 * condition with the humidity beneath it. */
std::string weather_hero(const Entry &entry);
std::string weather_sub(const Entry &entry);
/* The line such a card draws under its name: ON/OFF on a light or a
 * switch, because "on" is the whole of what the person came to see there;
 * the temperature the room is at and, while the thermostat is running, the
 * setpoint after it on a thermostat, which is the order a thermostat is
 * read in; OPEN/CLOSED on a cover; the condition and how warm it is on a
 * weather block, with the humidity where one is reported; the value with
 * its unit on a sensor block.
 *
 * Empty means "there is nothing to say", which includes a thermostat that is
 * off and reports no room temperature, and the caller **writes** that empty
 * string so a stale reading cannot survive. What the caller must skip
 * instead is an element that has never been answered at all — `state` still
 * empty — because that is a card the poll has said nothing about yet. */
std::string card_reading(const Entry &entry);

/* ------------------------------------------------------------- card art
 *
 * The artwork a card draws is downloaded from Home Assistant and never
 * compiled in. Six pictures used to be linked into this firmware and a card
 * stored a **1-based index into that array**, which meant the set could only
 * grow by reflashing every device in the house, and reordering it would have
 * silently moved everybody's icons. The catalog now lives in the integration,
 * a card stores a stable identifier, and this is the machinery that turns one
 * of those identifiers into pixels LVGL can blit.
 *
 * The six built-in pictures stay, and stay in flash. They are the fallback:
 * what a card draws before Home Assistant has answered, while it is
 * unreachable, when a download fails, and for an identifier this build has
 * never heard of. A room page that cannot reach Home Assistant is a room page
 * with plain artwork on it, never an empty one.
 */

/* Exactly what the integration serves, and the only variant this build asks
 * for. The picture is used at the size it arrives at and never transformed:
 * this build sets LV_COLOR_16_SWAP and leaves LV_DRAW_SW_SUPPORT_SWAPPED off,
 * so LVGL's software renderer cannot scale a source at all. See AGENTS.md. */
static const uint16_t ICON_PIXELS = 40;
/* "MCI1" and the size, twice. It is here so that a truncated download, a
 * proxy that answered something else, or a variant of another size cannot be
 * mistaken for the picture that was asked for and handed to LVGL as a buffer
 * of the wrong shape. */
static const size_t ICON_HEADER_BYTES = 8;
/* ARGB8888, in the little-endian B, G, R, A order LVGL reads and ESPHome
 * already writes for the artwork compiled into this firmware. A downloaded
 * icon and a built-in one are therefore the same kind of thing. */
static const size_t ICON_PIXEL_BYTES = static_cast<size_t>(ICON_PIXELS) * ICON_PIXELS * 4;
static const size_t ICON_PAYLOAD_BYTES = ICON_HEADER_BYTES + ICON_PIXEL_BYTES;

/* How many pictures are held decoded at once. Sixteen is 102 KB, which is
 * nothing in PSRAM and rather a lot in internal RAM — hence the allocator.
 * The bound is what keeps a catalog that grows from becoming a device that
 * runs out of memory: a page of sixty-four cards naming three icons holds
 * three of these and not sixty-four, because the cache is keyed on the
 * identifier and every card that names one shares the same decoded copy. */
static const uint8_t ICON_CACHE_LIMIT = 16;

/* The longest identifier this build will store or ask for. The integration
 * publishes nothing longer; anything that is is not from the catalog. */
static const size_t ICON_ID_MAX = 32;

/* How long a failed download is left alone before it is tried again. Home
 * Assistant being down must not turn into a request per loop, and an icon
 * that is genuinely missing must not be asked for forever. */
static const uint32_t ICON_RETRY_MS = 60000;

/* How long after the editor last asked what this device knows the catalog
 * keeps being fetched ahead of what the cards need. The editor shows every
 * icon in the catalog and the cards use a handful, so the rest are worth
 * having only while somebody is looking at them. */
static const uint32_t ICON_PREFETCH_MS = 120000;

/* One row of the catalog Home Assistant publishes. The label is what the
 * editor calls the icon and nothing compares it; the identifier is what a
 * registry element stores and what a request names. */
struct CatalogIcon {
  std::string id;
  std::string label;
};

/* One downloaded picture, kept decoded.
 *
 * These are held by unique_ptr in a vector for one reason: LVGL keeps the
 * **address** of the descriptor for as long as a widget draws it, and a
 * vector of values moves its elements when it grows. */
struct CachedIcon {
  std::string id;
  /* The pixels, in PSRAM where there is any. Null means this identifier has
   * been tried and has not arrived: the row is kept so that the failure is
   * remembered and not retried on every loop. */
  uint8_t *pixels{nullptr};
  /* When it was last drawn or served, for eviction, and when it last failed,
   * for the retry. Both are millis(). */
  uint32_t used_ms{0};
  uint32_t failed_ms{0};
  /* Whether a card on the current layout draws it. A pinned row is never
   * evicted, because evicting one would free a buffer an LVGL widget is
   * still pointing at. */
  bool pinned{false};
#ifdef USE_LVGL
  /* Handed to lv_image_set_src. Its address must stay put, which is what the
   * unique_ptr above is for. */
  lv_image_dsc_t dsc{};
#endif
};

/* How the last card edit ended, reported to the editor the same way a restore
 * is and for the same reason: the write reaches Home Assistant over HTTP,
 * which blocks the main loop, so it cannot be answered inside the request. */
enum CardWriteState : uint8_t {
  CARD_IDLE = 0,
  CARD_PENDING = 1,
  CARD_OK = 2,
  CARD_FAILED = 3,
};

/* Why the last restore ended the way it did, reported to the editor. */
enum RestoreState : uint8_t {
  RESTORE_IDLE = 0,
  RESTORE_PENDING = 1,
  RESTORE_OK = 2,
  RESTORE_FAILED = 3,
};

class MediaControllerGrid final : public AsyncWebHandler, public Component {
 public:
  explicit MediaControllerGrid(web_server_base::WebServerBase *base) : base_(base) {}

  void setup() override;
  void dump_config() override;
  /* After the network is up: the listener cannot be bound before it. */
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void set_port(uint16_t port) { this->port_ = port; }
  /* Where a browser on the same network reaches this editor, and "" while
   * the device has no address yet. The firmware reports it to Home
   * Assistant, which offers it as the link on this device's panel page. It
   * is built here because the port is this component's and nobody else's,
   * exactly as the T560 panel builds its own in panel_web.c. */
  std::string editor_url() const;
  void set_editor(const uint8_t *data, size_t size) {
    this->editor_ = data;
    this->editor_size_ = size;
  }
  /* The skins this device draws, in contract spelling. They are configured
   * rather than hard-coded here because which layouts exist is the
   * interface's business, not this component's. */
  void add_skin(const char *name) { this->skins_.emplace_back(name); }
  /* What one of those skins looks like, as a PNG in flash. The editor shows
   * it beside the list, because a name says nothing about a layout. It is a
   * static picture and not a live preview: drawing one would mean a second
   * implementation of every skin, in JavaScript, kept in step with
   * media-controller-ui.yaml by hand. A skin registered with no picture is
   * still offered; the editor falls back to its name. */
  void set_preview(const char *skin, const uint8_t *data, size_t size) {
    this->previews_.push_back(Preview{skin, data, size});
  }

  // ------------------------------------------------------------ the seam
  //
  // Everything that has to reach Home Assistant. All four are installed from
  // the firmware YAML at boot and all four end in a cmd_ script there.

  /* Called whenever the cards on screen are out of date: the layout changed,
   * or the registry behind it did. It is never called per frame — that is
   * the whole point of keeping a revision. */
  void set_redraw_listener(std::function<void()> &&f) { this->redraw_ = std::move(f); }
  /* Hand Home Assistant a copy of the layout that was just saved. */
  void set_backup_writer(std::function<void(std::string)> &&f) { this->backup_ = std::move(f); }
  /* Ask Home Assistant for the copy it holds. The answer arrives later,
   * through `restore_finished`. */
  void set_restore_requester(std::function<void()> &&f) { this->restore_ = std::move(f); }
  /* Ask Home Assistant to select a skin. Nothing is written locally: Home
   * Assistant owns the value and this device adopts it on its next poll. */
  void set_skin_writer(std::function<void(std::string)> &&f) { this->skin_writer_ = std::move(f); }
  /* Ask Home Assistant to store the display name and icon of one registry
   * element. Nothing is written locally, exactly as with the skin: the
   * registry belongs to Home Assistant, and the new name arrives back the
   * ordinary way, in the next config poll.
   *
   * The argument is the whole request body, already built and already
   * validated, for the same reason the backup writer is handed a whole
   * layout document: what may be said is this component's business, and the
   * other half of the seam only has to put a string on the wire. It also
   * carries the one thing a fixed argument list could not — which of the two
   * fields is being set, because leaving a name alone and clearing it are
   * different requests. */
  void set_card_writer(std::function<void(std::string)> &&f) {
    this->card_writer_ = std::move(f);
  }
  /* Ask Home Assistant for one icon at ICON_PIXELS. The answer arrives later,
   * through `icon_downloaded`. */
  void set_icon_fetcher(std::function<void(std::string)> &&f) { this->icon_fetcher_ = std::move(f); }

  /* The answer to a restore request. `document` is the layout Home Assistant
   * held, or empty when it holds none. */
  void restore_finished(bool ok, const std::string &document, const std::string &message);
  /* The answer to a card edit. The editor is watching /api/entities for it. */
  void card_write_finished(bool ok, const std::string &message);

  // ------------------------------------------------------------- card art

  /* Replaces the catalog Home Assistant publishes. Returns whether it
   * actually changed, which is what tells the caller to stop asking for a
   * while. The document carries no image data at all — the pictures are
   * separate requests, made only for the icons that are actually wanted. */
  bool ingest_icon_catalog(const std::string &document);
  /* The identifier of the next picture worth asking for, or empty when there
   * is nothing to fetch. Cards come first and the rest of the catalog only
   * while the editor is open; a download that failed is left alone for
   * ICON_RETRY_MS. One at a time on purpose: each is six kilobytes through a
   * request that blocks the main loop. */
  std::string next_wanted_icon();
  /* Takes one downloaded variant. Anything that is not exactly what was asked
   * for — wrong magic, wrong size, short body — is refused, and the
   * identifier is marked as failed rather than half-stored. `payload` empty
   * marks the failure without a body, which is what an HTTP error reports.
   *
   * Returns whether a card on the current layout draws this picture and was
   * drawing the fallback until now, which is the caller's signal to rebuild
   * the page. A picture nothing draws changes nothing on screen and must
   * cost no rebuild: the editor prefetches the whole catalog, and rebuilding
   * the room page once per prefetched row would be a page rebuilt eight
   * times for a page that did not change. */
  bool icon_downloaded(const std::string &id, const std::string &payload);
#ifdef USE_LVGL
  /* The picture one card should draw, or nullptr when this build has nothing
   * downloaded for it and the caller should fall back to its own artwork.
   * Cards naming the same identifier are handed the same descriptor. */
  const lv_image_dsc_t *icon_for(const Card &card, const Entry *entry);
#endif
  /* Which identifier a card resolves to, before the cache is consulted: the
   * registry's choice, or the legacy per-card name a layout written by an
   * older editor still carries. Empty means the domain decides. */
  std::string card_icon_id(const Card &card, const Entry *entry) const;
  /* Marks the icons the current layout draws so that they are never evicted
   * from under an LVGL widget. Called whenever the cards or the registry
   * change, which is the only time the answer can move. */
  void refresh_icon_pins();

  // ------------------------------------------------------- the registry
  //
  // Fed from the config sensor by the firmware YAML, and only when the
  // payload's `revision` moved: parsing sixty-four elements once a second
  // would be pure churn for a list that changes twice in the life of a
  // device.

  /* Reads the `entities` block out of one config-sensor payload. Returns
   * whether the registry actually changed, which is what decides a redraw. */
  bool ingest_entities(const std::string &attributes);
  const std::vector<Entry> &entries() const { return this->entries_; }
  /* The element behind one card, or nullptr when the registry does not carry
   * it. A card whose element is gone is **kept** — the payload is empty
   * while Home Assistant is unreachable, and dropping cards against it would
   * let one bad poll erase a layout the next save then writes back. */
  const Entry *entry(uint32_t rid) const;
  Entry *entry(uint32_t rid);

  // ---------------------------------------------------------- the layout

  const std::vector<Card> &cards() const { return this->cards_; }
  /* The layout document, in the format the editor and the backup endpoint
   * share with the T560 panel. */
  std::string layout_json() const;

  // ----------------------------------------------------- state routing
  //
  // Rid to state. The states arrive inside the config poll, in the
  // `room_states` block the integration renders beside the registry: one
  // small array per element, keyed by rid. They used to come from a template
  // rendered by POST /api/template, but that endpoint answers administrators
  // only and this device's token belongs to a dedicated non-administrator
  // user, so Home Assistant refused it and every card stayed blank.

  /* Takes the `room_states` object apart and stores one state per element.
   * An element the block does not carry keeps what it last knew, the way a
   * truncated answer used to: a missing key is a poll that said nothing
   * about the card, not a card that is off. Returns whether anything
   * actually moved, which is what decides a repaint. */
  bool apply_room_states(const std::string &room_states);
  /* The body of one `weather.get_forecasts` request for the drawn weather
   * entities, at most two: a day-by-day answer is kilobytes, and the
   * response buffer is not the place to find that out. Empty when no
   * weather card is drawn, which is the caller's signal to skip the poll
   * entirely. */
  std::string forecast_request() const;
  /* Takes one forecast answer apart and stores the coming days per element,
   * today skipped: the card already shows the current reading. */
  void apply_forecast(const std::string &body);

  /* The skin on screen, pushed from the firmware YAML: the editor's picker
   * has to show what is being drawn, not what Home Assistant last mentioned.
   * Locked because the page that reads it is served from another task. */
  void set_skin(const std::string &skin);
  void set_skin_writable(bool writable);

  // --------------------------------------------------------- the server

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index,
                  size_t total) override;

 protected:
  /* Replaces the layout, writes it to flash, backs it up and redraws.
   * Everything that changes the grid goes through here, so that no path can
   * forget one of the four. */
  void adopt_(std::vector<Card> &&cards, bool backup);
  void save_to_flash_();
  void load_from_flash_();
  /* Reads a layout document. Returns false and fills `error` when the
   * document itself is unusable; `dropped` receives how many cards were
   * discarded for not fitting or for overlapping one already placed. */
  bool parse_layout_(const std::string &document, std::vector<Card> *out, uint16_t *dropped,
                     std::string *error) const;
  /* Whether this card may be placed: inside the grid, at least one cell in
   * each direction, and clear of every card already in `placed`. */
  static bool can_place_(const std::vector<Card> &placed, const Card &card);
  /* Every registry element as a 2x2 card, in registry order. This is what the
   * device draws before anybody has opened the editor, so that it is useful
   * the moment it is configured in Home Assistant rather than after a second,
   * undiscoverable step. */
  std::vector<Card> default_layout_() const;

  void handle_editor_(AsyncWebServerRequest *request);
  void handle_skin_preview_(AsyncWebServerRequest *request, const char *url);
  void handle_icon_(AsyncWebServerRequest *request, const char *url);
  void handle_set_card_(AsyncWebServerRequest *request);
  void handle_entities_(AsyncWebServerRequest *request);
  void handle_get_layout_(AsyncWebServerRequest *request);
  void handle_save_layout_(AsyncWebServerRequest *request);
  void handle_restore_layout_(AsyncWebServerRequest *request);
  void handle_skins_(AsyncWebServerRequest *request);
  void handle_set_skin_(AsyncWebServerRequest *request);
  static void send_json_(AsyncWebServerRequest *request, int code, const std::string &body);
  static void send_error_(AsyncWebServerRequest *request, int code, const std::string &message);

  web_server_base::WebServerBase *base_;
  uint16_t port_{80};
  const uint8_t *editor_{nullptr};
  size_t editor_size_{0};
  std::vector<std::string> skins_;

  /* One skin's picture in flash. Both are fixed at codegen time and never
   * written at runtime, so neither needs the lock below. */
  struct Preview {
    std::string skin;
    const uint8_t *data;
    size_t size;
  };
  std::vector<Preview> previews_;

  std::vector<Entry> entries_;
  std::vector<Card> cards_;
  ESPPreferenceObject pref_;

  /* The catalog Home Assistant publishes, and the pictures downloaded from
   * it. Both are read by the server task and written by the main loop, so
   * both are under the lock below. */
  std::vector<CatalogIcon> catalog_;
  uint32_t catalog_revision_{0};
  std::vector<std::unique_ptr<CachedIcon>> icons_;
  /* When the editor last asked what this device knows. Icons the cards do
   * not use are fetched only for ICON_PREFETCH_MS after it, because they
   * exist to be looked at in a list nobody has open the rest of the time. */
  uint32_t editor_seen_ms_{0};
  /* The identifier handed to the fetcher and not yet answered. One at a
   * time: each is six kilobytes through a request that blocks the main
   * loop. */
  std::string icon_in_flight_;

  /* Returns the cache row for an identifier, creating it when asked. Both
   * forms expect the lock to be held. */
  CachedIcon *find_icon_(const std::string &id);
  CachedIcon *reserve_icon_(const std::string &id);
  /* Frees the least useful row so that a new one fits: a failure first, then
   * the least recently used picture no card is drawing. Returns false when
   * every row is pinned, which is the signal to keep the built-in artwork
   * rather than evict something a widget is pointing at. */
  bool evict_icon_();
  /* Whether this is something the catalog could plausibly have published. It
   * is checked before an identifier is stored, asked for, or turned into a
   * request, so nothing that reaches the wire came unexamined off a URL. */
  static bool icon_id_is_sane_(const std::string &id);
  bool catalog_has_(const std::string &id) const;

  /* The routes are answered on the HTTP server's own task, and everything
   * they read is written by the main loop: the registry is replaced when a
   * poll brings a new revision, and the layout when one is saved. A vector of
   * std::string being reallocated under a reader is a crash rather than a
   * stale answer, so the writers and the **server-task** readers take this.
   *
   * The main loop reads these without it, on purpose: it is the only writer,
   * so it cannot race with itself, and the card renderer walks the registry
   * for every card on the page. */
  Mutex lock_;

  std::function<void()> redraw_{};
  std::function<void(std::string)> backup_{};
  std::function<void()> restore_{};
  std::function<void(std::string)> skin_writer_{};
  std::function<void(std::string)> card_writer_{};
  std::function<void(std::string)> icon_fetcher_{};

  std::string skin_;
  bool skin_writable_{false};

  RestoreState restore_state_{RESTORE_IDLE};
  std::string restore_message_;

  CardWriteState card_state_{CARD_IDLE};
  std::string card_message_;

  /* The body of the request being received. esp_http_server hands a raw body
   * over in chunks and services one request at a time, so a single buffer is
   * enough. */
  std::string body_;
};

/* The artwork this build carries in flash. It is no longer what the editor
 * offers — that is the catalog Home Assistant publishes — but the fallback
 * underneath it: what a card draws before Home Assistant has answered, while
 * it is unreachable, when a download fails, and for an identifier this build
 * has never heard of.
 *
 * A card may still carry one of these names as its own `icon`, because a
 * layout document written by an older editor does, and the index in `Card` is
 * how that is stored. It is read and honoured and never written again: the
 * editor writes the identifier to the registry now, where a second panel and
 * a wiped device can both find it. */
extern const char *const ICON_NAMES[];
extern const size_t ICON_COUNT;

}  // namespace esphome::media_controller_grid
