#include "app_config.h"

#include "panel_pairing.h"

#include <string.h>

/* The names the contract uses. They are matched here and nowhere else, so a
 * skin added to the integration reaches this build as an unknown name and is
 * answered with the default rather than with a broken interface. */
PanelPlayerSkin panel_player_skin_from_string(const gchar *name)
{
    if (name != NULL && g_str_equal(name, "cassette"))
        return PANEL_PLAYER_SKIN_CASSETTE;
    return PANEL_PLAYER_SKIN_MODERN;
}

const gchar *panel_player_skin_to_string(PanelPlayerSkin skin)
{
    return skin == PANEL_PLAYER_SKIN_CASSETTE ? "cassette" : "modern";
}

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
    if (*value == '\0') {
        g_free(value);
        return fallback == NULL ? NULL : g_strdup(fallback);
    }
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

/* Written by t560-announce-panel once it has resolved Home Assistant over
 * mDNS, so that the tablet needs no URL of its own. */
static gchar *discovered_base_url(void)
{
    gchar *path = app_config_cache_path("discovered.ini");
    GKeyFile *file = g_key_file_new();
    gchar *url = NULL;

    if (g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL))
        url = read_string(file, "home_assistant", "url", NULL);

    g_key_file_unref(file);
    g_free(path);
    return url;
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
    g_clear_pointer(&layout->commands.display_state, g_free);
    g_clear_pointer(&layout->commands.page, g_free);
    layout->room_count = 0;
    layout->revision = 0;
    layout->settings.present = FALSE;
    layout->commands.display_at = 0;
    layout->commands.brightness = -1;
    layout->commands.brightness_at = 0;
    layout->commands.restart_at = 0;
    layout->commands.page_at = 0;
}

static void strip_trailing_slashes(gchar *url)
{
    gsize length = strlen(url);

    while (length > 0 && url[length - 1] == '/') {
        url[length - 1] = '\0';
        length--;
    }
}

/* config.ini is optional. Home Assistant is found over mDNS, the panel ID
 * defaults to the hostname, and every entity comes from Home Assistant. The
 * file exists only to override one of those, or to hold the tablet-local
 * settings that the button handler and the motion detector read. */
static gboolean load_key_file(AppConfig *config, gchar **error_message)
{
    gchar *path = config_path("config.ini");
    GKeyFile *file = g_key_file_new();

    if (g_key_file_load_from_file(file, path, G_KEY_FILE_NONE, NULL)) {
        config->base_url = read_string(file, "home_assistant", "url", NULL);
        config->panel_id = read_string(file, "home_assistant", "panel_id",
                                       NULL);
        config->config_entity = read_string(file, "home_assistant",
                                            "config_entity", NULL);
        config->poll_interval_ms = (guint)CLAMP(
            read_integer(file, "panel", "poll_interval_ms",
                         PANEL_DEFAULT_POLL_MS),
            500, 30000);
        config->playlist_poll_interval_ms = (guint)CLAMP(
            read_integer(file, "panel", "playlist_poll_interval_ms",
                         PANEL_DEFAULT_PLAYLIST_POLL_MS),
            10000, 3600000);
        gchar *skin = read_string(file, "panel", "player_skin", NULL);
        if (skin != NULL) {
            config->player_skin = panel_player_skin_from_string(skin);
            g_free(skin);
        }
    }
    g_key_file_unref(file);
    g_free(path);

    if (config->base_url == NULL)
        config->base_url = discovered_base_url();
    if (config->base_url == NULL) {
        *error_message = g_strdup(
            "Home Assistant was not found on the network.\n\nCheck that the "
            "tablet and Home Assistant share a network, or set url= under "
            "[home_assistant] in config.ini.");
        return FALSE;
    }
    strip_trailing_slashes(config->base_url);

    if (config->panel_id == NULL)
        config->panel_id = panel_pairing_device_id();

    /* Home Assistant derives the config sensor's entity ID from the device
     * name, so it is handed over during pairing rather than guessed. The
     * derived name below is only a fallback for an installation that was
     * paired before the value was stored. */
    if (config->config_entity == NULL)
        config->config_entity = panel_pairing_config_entity();
    if (config->config_entity == NULL) {
        config->config_entity = g_strdup_printf("sensor.%s_config",
                                                config->panel_id);
    }
    return TRUE;
}

/* A missing token is not an error. The panel shows a pairing code and asks
 * Home Assistant for one instead, so that nothing has to be typed on a tablet
 * that has no keyboard. */
static void load_token(AppConfig *config)
{
    gchar *path = config_path("token");

    if (g_file_get_contents(path, &config->token, NULL, NULL)) {
        g_strstrip(config->token);
        if (*config->token == '\0')
            g_clear_pointer(&config->token, g_free);
    }
    g_free(path);
}

AppConfig *app_config_load(gchar **error_message)
{
    g_return_val_if_fail(error_message != NULL, NULL);

    *error_message = NULL;
    AppConfig *config = g_new0(AppConfig, 1);
    config->poll_interval_ms = PANEL_DEFAULT_POLL_MS;
    config->playlist_poll_interval_ms = PANEL_DEFAULT_PLAYLIST_POLL_MS;
    config->player_skin = PANEL_PLAYER_SKIN_MODERN;

    if (!load_key_file(config, error_message)) {
        app_config_free(config);
        return NULL;
    }
    load_token(config);
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
