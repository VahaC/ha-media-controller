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

static gboolean read_room_features(GKeyFile *file, const gchar *key,
                                   gboolean *brightness,
                                   gboolean *color_temperature,
                                   gchar **error_message)
{
    gchar *value = read_string(file, "room_features", key, "");
    gchar **features = g_strsplit(value, ",", -1);

    *brightness = FALSE;
    *color_temperature = FALSE;
    for (guint i = 0; features[i] != NULL; i++) {
        gchar *feature = g_strstrip(features[i]);
        if (*feature == '\0' || g_str_equal(feature, "none"))
            continue;
        if (g_str_equal(feature, "brightness")) {
            *brightness = TRUE;
        } else if (g_str_equal(feature, "color_temperature")) {
            *color_temperature = TRUE;
        } else {
            *error_message = g_strdup_printf(
                "Unsupported room feature '%s' for %s.", feature, key);
            g_strfreev(features);
            g_free(value);
            return FALSE;
        }
    }

    g_strfreev(features);
    g_free(value);
    return TRUE;
}

static gboolean load_key_file(AppConfig *config, gchar **error_message)
{
    static const gchar *room_keys[PANEL_ROOM_COUNT] = {
        "light_1", "light_2", "fan", "ac", "desk_lamp",
        "desk_led_strip"
    };
    static const gchar *default_labels[PANEL_ROOM_COUNT] = {
        "LIGHT 1", "LIGHT 2", "FAN", "AC", "DESK LAMP",
        "DESK LED STRIP"
    };
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
    config->player_entity = read_string(file, "entities", "player", NULL);
    config->queue_entity = read_string(file, "entities", "queue", NULL);
    config->playlists_entity = read_string(file, "entities", "playlists", NULL);
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
        config->room_entities[i] = read_string(file, "entities", room_keys[i], NULL);
        config->room_labels[i] = read_string(file, "labels", room_keys[i],
                                             default_labels[i]);
        if (!read_room_features(
                file, room_keys[i], &config->room_brightness[i],
                &config->room_color_temperature[i], error_message)) {
            g_key_file_unref(file);
            g_free(path);
            return FALSE;
        }
    }
    config->poll_interval_ms = (guint)CLAMP(
        read_integer(file, "panel", "poll_interval_ms", PANEL_DEFAULT_POLL_MS),
        500, 30000);
    config->playlist_poll_interval_ms = (guint)CLAMP(
        read_integer(file, "panel", "playlist_poll_interval_ms",
                     PANEL_DEFAULT_PLAYLIST_POLL_MS),
        10000, 3600000);

    g_key_file_unref(file);
    g_free(path);

    if (config->base_url == NULL || config->player_entity == NULL ||
        config->queue_entity == NULL || config->playlists_entity == NULL) {
        *error_message = g_strdup(
            "config.ini must define url, player, queue, and playlists.");
        return FALSE;
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
    g_free(config->player_entity);
    g_free(config->queue_entity);
    g_free(config->playlists_entity);
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
        g_free(config->room_entities[i]);
        g_free(config->room_labels[i]);
    }
    g_free(config);
}
