#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/core/preferences.h"
#include "esphome/components/web_server_base/web_server_base.h"

#include <cmath>
#include <functional>
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
 *   child 0     the icon, on every card;
 *   child 1     the reading, on a labelled thermostat card only;
 *   last child  the name, on any labelled card.
 */
bool card_is_labelled(const Card &card);
bool card_shows_reading(const Card &card, const Entry *entry);

/* Whether Home Assistant has said anything about this element at all, and
 * whether what it said means "on".
 *
 * They are two questions because a card has three states and not two: an
 * element that is unavailable, or that has not been polled yet, must not
 * read as off — off is a fact and that is the absence of one.
 *
 * A light and a switch say "on" and everything else is off. A thermostat
 * does not: its state is the mode it is in — heat, cool, auto, dry, fan_only
 * — and every one of them but "off" is a thermostat that is running. */
bool entry_is_known(const Entry &entry);
bool entry_is_on(const Entry &entry);
/* The line such a card draws under its name: the temperature the room is at
 * and, while the thermostat is running, the setpoint after it — the order a
 * thermostat is read in.
 *
 * Empty means "there is nothing to say", which includes a thermostat that is
 * off and reports no room temperature, and the caller **writes** that empty
 * string so a stale reading cannot survive. What the caller must skip
 * instead is an element that has never been answered at all — `state` still
 * empty — because that is a card the poll has said nothing about yet. */
std::string card_reading(const Entry &entry);

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

  /* The answer to a restore request. `document` is the layout Home Assistant
   * held, or empty when it holds none. */
  void restore_finished(bool ok, const std::string &document, const std::string &message);

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
  // Card to rid to entity to state. One request answers for every card on
  // the page, however many there are: http_request blocks the main loop on
  // ESP-IDF, so the number of requests may not grow with the number of
  // cards.

  /* The body of a Home Assistant `/api/template` request that renders every
   * distinct entity a card addresses, one state per line. Empty when there
   * is nothing to ask about, which is the caller's signal to skip the poll
   * entirely. */
  std::string state_request() const;
  /* Takes the rendered answer apart and stores one state per element. */
  void apply_states(const std::string &rendered);

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
  /* Which entries a poll asks about, and in what order: the ones a card
   * actually draws, everything but a thermostat first and the thermostats
   * after them. It is one function because `state_request` writes the
   * template in this order and `apply_states` reads the answer in it, and
   * two copies of an order are two chances for it to drift. */
  std::vector<size_t> polled_order_() const;

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

  std::string skin_;
  bool skin_writable_{false};

  RestoreState restore_state_{RESTORE_IDLE};
  std::string restore_message_;

  /* The body of the request being received. esp_http_server hands a raw body
   * over in chunks and services one request at a time, so a single buffer is
   * enough. */
  std::string body_;
};

/* The artwork this build carries, in the order the editor offers it. A card
 * stores the index rather than the name so that the whole grid stays eight
 * bytes per card; the document keeps the name, because it is shared with a
 * panel whose artwork is its own. */
extern const char *const ICON_NAMES[];
extern const size_t ICON_COUNT;

}  // namespace esphome::media_controller_grid
