#ifndef T560_APP_CONFIG_H
#define T560_APP_CONFIG_H

#include <glib.h>

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

/* Everything that comes from Home Assistant. It is cached on disk so that the
 * panel starts with the last known layout when Home Assistant is unreachable
 * at boot. */
typedef struct {
    gchar *player_entity;
    gchar *queue_entity;
    gchar *playlists_entity;
    PanelRoom rooms[PANEL_ROOM_MAX];
    guint room_count;
    gint64 revision;
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
