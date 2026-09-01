#ifndef T560_APP_CONFIG_H
#define T560_APP_CONFIG_H

#include <glib.h>

enum {
    PANEL_ROOM_COUNT = 6,
    PANEL_DEFAULT_POLL_MS = 1000,
    PANEL_DEFAULT_PLAYLIST_POLL_MS = 60000
};

typedef struct {
    gchar *base_url;
    gchar *token;
    gchar *player_entity;
    gchar *queue_entity;
    gchar *playlists_entity;
    gchar *room_entities[PANEL_ROOM_COUNT];
    gchar *room_labels[PANEL_ROOM_COUNT];
    gboolean room_brightness[PANEL_ROOM_COUNT];
    gboolean room_color_temperature[PANEL_ROOM_COUNT];
    guint poll_interval_ms;
    guint playlist_poll_interval_ms;
} AppConfig;

AppConfig *app_config_load(gchar **error_message);
void app_config_free(AppConfig *config);
gchar *app_config_directory_path(void);

#endif
