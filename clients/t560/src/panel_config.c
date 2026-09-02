#include "panel_config.h"

#include "json_helpers.h"

#include <glib/gstdio.h>

#define PANEL_CONFIG_CACHE_NAME "layout.json"

static gint clamp_kelvin(gdouble value, gint fallback)
{
    if (value < 1000.0 || value > 20000.0)
        return fallback;
    return (gint)(value + 0.5);
}

/* An unknown control name is ignored rather than treated as an error, so the
 * integration can add one without breaking a released panel. */
static void read_controls(JsonArray *controls, PanelRoom *room)
{
    room->brightness = FALSE;
    room->color_temperature = FALSE;
    if (controls == NULL)
        return;

    for (guint i = 0; i < json_array_get_length(controls); i++) {
        const gchar *control = json_array_get_string_element(controls, i);
        if (control == NULL)
            continue;
        if (g_str_equal(control, "brightness"))
            room->brightness = TRUE;
        else if (g_str_equal(control, "color_temp"))
            room->color_temperature = TRUE;
    }
}

static gboolean read_room(JsonObject *object, PanelRoom *room)
{
    const gchar *entity = json_object_string(object, "entity", NULL);
    if (entity == NULL || *entity == '\0')
        return FALSE;

    gdouble value = 0.0;
    room->slot = json_object_number(object, "slot", &value) && value > 0.0
                     ? (guint)value
                     : 0;
    room->entity = g_strdup(entity);
    room->label = g_strdup(json_object_string(object, "label", entity));
    read_controls(json_optional_array(object, "controls"), room);
    room->min_kelvin = json_object_number(object, "min_kelvin", &value)
                           ? clamp_kelvin(value, 2000)
                           : 2000;
    room->max_kelvin = json_object_number(object, "max_kelvin", &value)
                           ? clamp_kelvin(value, 6500)
                           : 6500;
    if (room->max_kelvin <= room->min_kelvin) {
        room->min_kelvin = 2000;
        room->max_kelvin = 6500;
    }
    return TRUE;
}

/* Home Assistant clamps every setting before it sends one, so these bounds
 * only guard against a payload that did not come from it. They are the same
 * bounds config.ini is read with. */
static void read_settings(JsonObject *attributes, PanelSettings *settings)
{
    settings->present = FALSE;
    settings->poll_interval_ms = PANEL_DEFAULT_POLL_MS;
    settings->playlist_poll_interval_ms = PANEL_DEFAULT_PLAYLIST_POLL_MS;
    settings->screen_off_seconds = -1;
    settings->player_skin_present = FALSE;
    settings->player_skin = PANEL_PLAYER_SKIN_MODERN;

    JsonObject *object = json_optional_object(attributes, "settings");
    if (object == NULL)
        return;

    gdouble value = 0.0;
    settings->present = TRUE;
    if (json_object_number(object, "poll_interval_ms", &value))
        settings->poll_interval_ms = (guint)CLAMP(value, 500.0, 30000.0);
    if (json_object_number(object, "playlist_poll_interval_ms", &value)) {
        settings->playlist_poll_interval_ms =
            (guint)CLAMP(value, 10000.0, 3600000.0);
    }
    if (json_object_number(object, "screen_off_seconds", &value)) {
        settings->screen_off_seconds =
            value <= 0.0 ? 0 : (gint)CLAMP(value, 5.0, 3600.0);
    }
    /* An absent key is not a request for the default: it means nobody has
     * chosen, and config.ini keeps deciding. A name this build does not know
     * is a choice it cannot honour, so it draws the default rather than
     * nothing. */
    const gchar *skin = json_object_string(object, "player_skin", NULL);
    if (skin != NULL && *skin != '\0') {
        settings->player_skin_present = TRUE;
        settings->player_skin = panel_player_skin_from_string(skin);
    }
}

/* A command is a moment, not a message: the caller compares each timestamp
 * with the last one it applied. A command this build does not know is
 * ignored rather than treated as an error, so the integration can add one
 * without breaking a panel already in the field. */
static void read_commands(JsonObject *attributes, PanelCommands *commands)
{
    commands->display_state = NULL;
    commands->display_at = 0;
    commands->brightness = -1;
    commands->brightness_at = 0;
    commands->restart_at = 0;
    commands->page = NULL;
    commands->page_at = 0;

    JsonObject *object = json_optional_object(attributes, "commands");
    if (object == NULL)
        return;

    gdouble value = 0.0;
    JsonObject *display = json_optional_object(object, "display");
    if (display != NULL && json_object_number(display, "at", &value)) {
        const gchar *requested = json_object_string(display, "state", NULL);
        if (g_strcmp0(requested, "on") == 0 ||
            g_strcmp0(requested, "off") == 0) {
            commands->display_state = g_strdup(requested);
            commands->display_at = (gint64)value;
        }
    }

    JsonObject *brightness = json_optional_object(object, "brightness");
    if (brightness != NULL && json_object_number(brightness, "at", &value)) {
        gdouble level = 0.0;
        if (json_object_number(brightness, "value", &level)) {
            commands->brightness = (gint)CLAMP(level, 1.0, 100.0);
            commands->brightness_at = (gint64)value;
        }
    }

    JsonObject *restart = json_optional_object(object, "restart");
    if (restart != NULL && json_object_number(restart, "at", &value))
        commands->restart_at = (gint64)value;

    /* The page name is not checked here: which pages exist is the
     * application's business, not the payload reader's. */
    JsonObject *page = json_optional_object(object, "page");
    if (page != NULL && json_object_number(page, "at", &value)) {
        const gchar *requested = json_object_string(page, "value", NULL);
        if (requested != NULL && *requested != '\0') {
            commands->page = g_strdup(requested);
            commands->page_at = (gint64)value;
        }
    }
}

gboolean panel_config_parse_state(JsonObject *state, PanelLayout *layout,
                                  gchar **error_message)
{
    g_return_val_if_fail(layout != NULL, FALSE);
    g_return_val_if_fail(error_message != NULL, FALSE);

    JsonObject *attributes = json_state_attributes(state);
    if (attributes == NULL) {
        *error_message = g_strdup("The config sensor has no attributes.");
        return FALSE;
    }

    const gchar *player = json_object_string(attributes, "player", NULL);
    const gchar *queue = json_object_string(attributes, "queue", NULL);
    const gchar *playlists = json_object_string(attributes, "playlists", NULL);
    if (player == NULL || *player == '\0' || queue == NULL ||
        *queue == '\0' || playlists == NULL || *playlists == '\0') {
        *error_message = g_strdup(
            "The config sensor does not name the player, queue, and playlist "
            "entities yet.");
        return FALSE;
    }

    PanelLayout parsed = {0};
    parsed.player_entity = g_strdup(player);
    parsed.queue_entity = g_strdup(queue);
    parsed.playlists_entity = g_strdup(playlists);

    gdouble revision = 0.0;
    if (json_object_number(attributes, "revision", &revision))
        parsed.revision = (gint64)revision;
    /* Absent is not an error: an integration built before this field existed
     * simply says nothing, and the caller reads 0 as "older than this
     * panel". */
    gdouble contract = 0.0;
    if (json_object_number(attributes, "contract_version", &contract) &&
        contract > 0.0) {
        parsed.contract_version = (gint)contract;
    }
    read_settings(attributes, &parsed.settings);
    read_commands(attributes, &parsed.commands);

    JsonArray *slots = json_optional_array(attributes, "slots");
    guint length = slots != NULL ? json_array_get_length(slots) : 0;
    for (guint i = 0; i < length && parsed.room_count < PANEL_ROOM_MAX; i++) {
        JsonNode *node = json_array_get_element(slots, i);
        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node))
            continue;
        if (read_room(json_node_get_object(node),
                      &parsed.rooms[parsed.room_count])) {
            parsed.room_count++;
        }
    }

    panel_layout_clear(layout);
    *layout = parsed;
    return TRUE;
}

gboolean panel_config_parse_json(const gchar *data, gssize length,
                                 PanelLayout *layout, gchar **error_message)
{
    g_return_val_if_fail(error_message != NULL, FALSE);

    JsonParser *parser = json_parser_new();
    GError *error = NULL;

    if (!json_parser_load_from_data(parser, data, length, &error) ||
        !JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser))) {
        *error_message = error != NULL
                             ? g_strdup(error->message)
                             : g_strdup("The config sensor is not an object.");
        g_clear_error(&error);
        g_object_unref(parser);
        return FALSE;
    }

    gboolean parsed = panel_config_parse_state(
        json_node_get_object(json_parser_get_root(parser)), layout,
        error_message);
    g_object_unref(parser);
    return parsed;
}

gboolean panel_config_load_cache(PanelLayout *layout, gchar **error_message)
{
    gchar *path = app_config_cache_path(PANEL_CONFIG_CACHE_NAME);
    gchar *data = NULL;
    gsize length = 0;

    if (!g_file_get_contents(path, &data, &length, NULL)) {
        *error_message = g_strdup(
            "Home Assistant is unreachable and no configuration has been "
            "cached yet.\n\nStart the panel once while Home Assistant "
            "answers at the URL in config.ini.");
        g_free(path);
        return FALSE;
    }
    g_free(path);

    gboolean parsed = panel_config_parse_json(data, (gssize)length, layout,
                                              error_message);
    g_free(data);
    return parsed;
}

void panel_config_store_cache(const gchar *data, gsize length)
{
    gchar *path = app_config_cache_path(PANEL_CONFIG_CACHE_NAME);
    GError *error = NULL;

    if (!g_file_set_contents(path, data, (gssize)length, &error)) {
        g_warning("Could not cache the panel configuration: %s",
                  error->message);
        g_clear_error(&error);
    } else {
        g_chmod(path, 0600);
    }
    g_free(path);
}
