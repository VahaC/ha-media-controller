#include "app_config.h"

#include <string.h>

static gchar *config_path(const gchar *name)
{
    gchar *directory = app_config_directory_path();
    gchar *path = g_build_filename(directory, name, NULL);

    g_free(directory);
    return path;
}

gchar *app_config_directory_path(void)
{
    return g_build_filename(g_get_user_config_dir(),
                            "t560-music-panel", NULL);
}

gchar *app_config_cache_path(const gchar *name)
{
    gchar *directory = g_build_filename(g_get_user_cache_dir(),
                                        "t560-music-panel", NULL);
    gchar *path = g_build_filename(directory, name, NULL);

    g_mkdir_with_parents(directory, 0700);
    g_free(directory);
    return path;
}

static gchar *read_string(GKeyFile *file, const gchar *group,
                          const gchar *key, const gchar *fallback)
{
    GError *error = NULL;
    gchar *value = g_key_file_get_string(file, group, key, &error);

    if (error != NULL) {
        g_clear_error(&error);
        return fallback == NULL ? NULL : g_strdup(fallback);
    }
    g_strstrip(value);
    return value;
}

static gint read_integer(GKeyFile *file, const gchar *group,
                         const gchar *key, gint fallback)
{
    GError *error = NULL;
    gint value = g_key_file_get_integer(file, group, key, &error);

    if (error != NULL) {
        g_clear_error(&error);
        return fallback;
    }
    return value;
}

void panel_layout_clear(PanelLayout *layout)
{
    if (layout == NULL)
        return;

    g_clear_pointer(&layout->player_entity, g_free);
    g_clear_pointer(&layout->queue_entity, g_free);
    g_clear_pointer(&layout->playlists_entity, g_free);
    for (guint i = 0; i < PANEL_ROOM_MAX; i++) {
        g_clear_pointer(&layout->rooms[i].entity, g_free);
        g_clear_pointer(&layout->rooms[i].label, g_free);
    }
    layout->room_count = 0;
    layout->revision = 0;
}

static gboolean load_key_file(AppConfig *config, gchar **error_message)
{
    gchar *path = config_path("config.ini");
    GKeyFile *file = g_key_file_new();

    if (!g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL)) {
        *error_message = g_strdup_printf(
            "Configuration is missing.\n\nCreate:\n%s\n\nCopy "
            "config.ini.example and edit it over SSH. This application has "
            "no keyboard or text input.", path);
        g_key_file_unref(file);
        g_free(path);
        return FALSE;
    }

    config->base_url = read_string(file, "home_assistant", "url", NULL);
    config->panel_id = read_string(file, "home_assistant", "panel_id", NULL);
    config->config_entity = read_string(file, "home_assistant",
                                        "config_entity", NULL);
    config->poll_interval_ms = (guint)CLAMP(
        read_integer(file, "panel", "poll_interval_ms", PANEL_DEFAULT_POLL_MS),
        500, 30000);
    config->playlist_poll_interval_ms = (guint)CLAMP(
        read_integer(file, "panel", "playlist_poll_interval_ms",
                     PANEL_DEFAULT_PLAYLIST_POLL_MS),
        10000, 3600000);

    g_key_file_unref(file);
    g_free(path);

    if (config->base_url == NULL ||
        (config->panel_id == NULL && config->config_entity == NULL)) {
        *error_message = g_strdup(
            "config.ini must define url and panel_id.\n\nEvery other setting "
            "now lives in Home Assistant, in the panel you added to the Media "
            "Controller integration.");
        return FALSE;
    }

    /* The integration names the sensor after the panel device, so the entity
     * ID is predictable. config_entity overrides it for an installation whose
     * sensor was renamed in Home Assistant. */
    if (config->config_entity == NULL) {
        config->config_entity = g_strdup_printf("sensor.%s_config",
                                                config->panel_id);
    }

    while (*config->base_url != '\0' &&
           config->base_url[strlen(config->base_url) - 1] == '/') {
        config->base_url[strlen(config->base_url) - 1] = '\0';
    }
    return TRUE;
}

static gboolean load_token(AppConfig *config, gchar **error_message)
{
    gchar *path = config_path("token");

    if (!g_file_get_contents(path, &config->token, NULL, NULL)) {
        *error_message = g_strdup_printf(
            "Home Assistant token is missing.\n\nCreate this file over SSH "
            "and set mode 600:\n%s", path);
        g_free(path);
        return FALSE;
    }
    g_free(path);
    g_strstrip(config->token);
    if (*config->token == '\0') {
        *error_message = g_strdup("The token file is empty.");
        return FALSE;
    }
    return TRUE;
}

AppConfig *app_config_load(gchar **error_message)
{
    g_return_val_if_fail(error_message != NULL, NULL);

    *error_message = NULL;
    AppConfig *config = g_new0(AppConfig, 1);
    config->poll_interval_ms = PANEL_DEFAULT_POLL_MS;
    config->playlist_poll_interval_ms = PANEL_DEFAULT_PLAYLIST_POLL_MS;

    if (!load_key_file(config, error_message) ||
        !load_token(config, error_message)) {
        app_config_free(config);
        return NULL;
    }
    return config;
}

void app_config_free(AppConfig *config)
{
    if (config == NULL)
        return;

    g_free(config->base_url);
    g_free(config->token);
    g_free(config->panel_id);
    g_free(config->config_entity);
    panel_layout_clear(&config->layout);
    g_free(config);
}
