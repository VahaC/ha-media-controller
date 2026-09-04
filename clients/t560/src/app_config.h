#ifndef T560_APP_CONFIG_H
#define T560_APP_CONFIG_H

#include <glib.h>

/* The one place the panel's own version is written. It reaches Home
 * Assistant in the status report, which is what shows the software version on
 * the panel's device, and it is the user agent of every request. Keep it in
 * step with pkgver in packaging/APKBUILD. */
#define T560_PANEL_VERSION "0.6.0"

/* The version of docs/CONTRACT.md this build implements.
 *
 * T560_PANEL_VERSION says when this build shipped; this says what it
 * understands, and it is the only number worth comparing with the other side.
 * The panel sends it in every status report and reads the integration's own
 * out of the config sensor, so each half can tell that the other is behind.
 * Raise it in the same change that raises the number in that document. */
#define T560_PANEL_CONTRACT_VERSION 7

/* How many registry elements this panel will hold. The integration sends its
 * own `entity_limit` and the T560 profile's is the same number; this is the
 * ceiling a payload is trusted up to when it names none, and what stops a
 * malformed one from being read into unbounded memory. It is not a number of
 * tiles: how many cards are drawn, and how large each of them is, comes from
 * the grid the user arranged, not from here. */
enum {
    PANEL_ENTITY_LIMIT = 100,
    PANEL_DEFAULT_POLL_MS = 1000,
    PANEL_DEFAULT_PLAYLIST_POLL_MS = 60000,
    /* The layout editor's port. Above 1024 so that the panel needs no
     * privileges it does not already have: the deployment is deliberately
     * root-free. */
    PANEL_DEFAULT_WEB_PORT = 8730
};

/* How the panel draws itself. The name arrives from Home Assistant in the
 * config sensor and decides the whole interface, not only the player page:
 * the cassette skin restyles the navigation bar and the room page with it.
 * A name this build does not know falls back to MODERN rather than failing,
 * so a skin added later cannot break a panel already in the field. */
typedef enum {
    PANEL_PLAYER_SKIN_MODERN,
    PANEL_PLAYER_SKIN_CASSETTE,
    /* Not a skin: the number of them, so that the interface can hold one
     * record per skin and keep every one of them up to date. */
    PANEL_PLAYER_SKIN_COUNT
} PanelPlayerSkin;

PanelPlayerSkin panel_player_skin_from_string(const gchar *name);
const gchar *panel_player_skin_to_string(PanelPlayerSkin skin);

/* One element of the panel's registry, exactly as the config sensor describes
 * it. The panel never inspects Home Assistant capabilities itself: the
 * integration resolves them and sends the controls this element may draw.
 *
 * `rid` is the identity, not `entity`. A Home Assistant entity ID is renamed
 * by the user at will, so the grid on this tablet keys its cards on the rid
 * and a rename moves nothing. */
typedef struct {
    gchar *rid;
    gchar *entity;
    gchar *name;
    gchar *domain;
    /* Whether the payload offered `toggle`. Every light and switch does; a
     * thermostat that cannot be turned off does not, and its card reads
     * rather than acts. See docs/CONTRACT.md, Climate cards. */
    gboolean togglable;
    gboolean brightness;
    gboolean color_temperature;
    gint min_kelvin;
    gint max_kelvin;
    /* A thermostat's single setpoint, and the range a card may move it in.
     * The three numbers mean nothing unless `target_temperature` is set.
     *
     * They carry **no unit**, exactly as the payload carries none: they are
     * whatever the entity itself reports, and the card draws the number with
     * a bare degree sign. Assuming Celsius here would be wrong in a house
     * configured in Fahrenheit and would show a thermostat set to 68 as
     * being at the top of a 7-35 scale. */
    gboolean target_temperature;
    gdouble min_temp;
    gdouble max_temp;
    gdouble temp_step;
    /* A cover. `position` is whether the card may drag a percentage open and
     * `stoppable` whether it may halt one that is travelling. Both are
     * capabilities; how far open the thing actually is arrives with every
     * poll like any other state. A cover needs no bounds beside them: a
     * position is a percentage by definition. See docs/CONTRACT.md, Cover
     * cards. */
    gboolean position;
    gboolean stoppable;
} PanelEntity;

/* The tablet-local settings Home Assistant owns. They used to live only in
 * config.ini, which is still read as the fallback the panel starts from
 * before it has reached Home Assistant even once. Absent settings leave
 * `present` FALSE, and config.ini keeps deciding. */
typedef struct {
    gboolean present;
    guint poll_interval_ms;
    guint playlist_poll_interval_ms;
    /* Seconds of inactivity before the display turns off; 0 disables it, and
     * -1 means Home Assistant did not send one. Applied by
     * t560-power-button.py, which re-reads the cached payload. */
    gint screen_off_seconds;
    /* FALSE when Home Assistant named no skin. Nobody has chosen one there,
     * so config.ini keeps deciding; overwriting it with the default would
     * make an unconfigured Home Assistant louder than the tablet's own file. */
    gboolean player_skin_present;
    PanelPlayerSkin player_skin;
} PanelSettings;

/* The moments Home Assistant asked this panel to act.
 *
 * Nothing can be pushed to a tablet that serves nothing, so a command is a
 * timestamp rather than a message: the panel acts only when the timestamp is
 * newer than the last one it applied, which makes a command arrive exactly
 * once however often the payload is polled. */
typedef struct {
    /* "on", "off", or NULL when the display was never asked to change. */
    gchar *display_state;
    gint64 display_at;
    gint brightness;
    gint64 brightness_at;
    gint64 restart_at;
    /* The page to show, or NULL when none was ever asked for. */
    gchar *page;
    gint64 page_at;
} PanelCommands;

/* Everything that comes from Home Assistant. It is cached on disk so that the
 * panel starts with the last known layout when Home Assistant is unreachable
 * at boot. */
typedef struct {
    gchar *player_entity;
    gchar *queue_entity;
    gchar *playlists_entity;
    /* The select Home Assistant holds this panel's skin in, or NULL when the
     * integration named none. The panel writes it and never stores a skin of
     * its own: Home Assistant stays the owner, and the new value arrives back
     * in `settings.player_skin` on the next poll. */
    gchar *skin_select_entity;
    /* PanelEntity*, owned, in payload order. Unbounded by design: the number
     * of room controls is the user's business, not a compile-time constant. */
    GPtrArray *entities;
    /* A checksum of the layout above and of nothing else. Settings and
     * commands deliberately do not change it: they are applied while the
     * panel keeps running, and only a layout change rebuilds the interface. */
    gint64 revision;
    /* Which version of the contract the integration on the other end
     * implements, and 0 when the payload names none. Every integration built
     * before this field existed sends nothing, so 0 and "older than this
     * panel" are the same fact. */
    gint contract_version;
    PanelSettings settings;
    PanelCommands commands;
} PanelLayout;

typedef struct {
    /* From config.ini. */
    gchar *base_url;
    gchar *token;
    gchar *panel_id;
    gchar *config_entity;
    guint poll_interval_ms;
    guint playlist_poll_interval_ms;
    PanelPlayerSkin player_skin;
    /* The port the layout editor answers on, and 0 to switch it off. The
     * editor has no password by design, so the way to refuse it entirely is
     * a setting rather than a firewall rule somebody has to remember. */
    guint web_port;
    /* From Home Assistant, or from the on-disk cache. */
    PanelLayout layout;
} AppConfig;

AppConfig *app_config_load(gchar **error_message);
void app_config_free(AppConfig *config);
gchar *app_config_directory_path(void);
gchar *app_config_cache_path(const gchar *name);

void panel_layout_clear(PanelLayout *layout);
/* The element with this rid, or NULL when the registry no longer carries one.
 * A card whose rid has gone is a card whose entity was removed in Home
 * Assistant, which the grid draws as unassigned rather than dropping. */
const PanelEntity *panel_layout_find_entity(const PanelLayout *layout,
                                            const gchar *rid);
void panel_entity_free(PanelEntity *entity);

#endif
