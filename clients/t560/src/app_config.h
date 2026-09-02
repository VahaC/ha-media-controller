#ifndef T560_APP_CONFIG_H
#define T560_APP_CONFIG_H

#include <glib.h>

/* The one place the panel's own version is written. It reaches Home
 * Assistant in the status report, which is what shows the software version on
 * the panel's device, and it is the user agent of every request. Keep it in
 * step with pkgver in packaging/APKBUILD. */
#define T560_PANEL_VERSION "0.3.1"

/* Six is the number of tiles this panel draws. It is the T560 profile of the
 * Media Controller integration, which never sends more; a larger payload is
 * truncated rather than trusted. */
enum {
    PANEL_ROOM_MAX = 6,
    PANEL_DEFAULT_POLL_MS = 1000,
    PANEL_DEFAULT_PLAYLIST_POLL_MS = 60000
};

/* One room control, exactly as the config sensor describes it. The panel
 * never inspects Home Assistant capabilities itself: the integration resolves
 * them and sends the controls this tile may draw. */
typedef struct {
    guint slot;
    gchar *entity;
    gchar *label;
    gboolean brightness;
    gboolean color_temperature;
    gint min_kelvin;
    gint max_kelvin;
} PanelRoom;

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
    PanelRoom rooms[PANEL_ROOM_MAX];
    guint room_count;
    /* A checksum of the layout above and of nothing else. Settings and
     * commands deliberately do not change it: they are applied while the
     * panel keeps running, and only a layout change rebuilds the interface. */
    gint64 revision;
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
    /* From Home Assistant, or from the on-disk cache. */
    PanelLayout layout;
} AppConfig;

AppConfig *app_config_load(gchar **error_message);
void app_config_free(AppConfig *config);
gchar *app_config_directory_path(void);
gchar *app_config_cache_path(const gchar *name);

void panel_layout_clear(PanelLayout *layout);

#endif
