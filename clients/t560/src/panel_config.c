#include "panel_config.h"

#include "json_helpers.h"

#include <glib/gstdio.h>

#include <string.h>

#define PANEL_CONFIG_CACHE_NAME "layout.json"

static gint clamp_kelvin(gdouble value, gint fallback)
{
    if (value < 1000.0 || value > 20000.0)
        return fallback;
    return (gint)(value + 0.5);
}

/* An unknown control name is ignored rather than treated as an error, so the
 * integration can add one without breaking a released panel. */
static void read_controls(JsonArray *controls, PanelEntity *entity)
{
    entity->togglable = FALSE;
    entity->brightness = FALSE;
    entity->color_temperature = FALSE;
    entity->target_temperature = FALSE;
    if (controls == NULL)
        return;

    for (guint i = 0; i < json_array_get_length(controls); i++) {
        const gchar *control = json_array_get_string_element(controls, i);
        if (control == NULL)
            continue;
        if (g_str_equal(control, "toggle"))
            entity->togglable = TRUE;
        else if (g_str_equal(control, "brightness"))
            entity->brightness = TRUE;
        else if (g_str_equal(control, "color_temp"))
            entity->color_temperature = TRUE;
        else if (g_str_equal(control, "target_temperature"))
            entity->target_temperature = TRUE;
    }
}

/* A thermostat's setpoint bounds. Unlike the Kelvin pair there is no
 * plausible range to sanity-check them against: the payload carries no unit,
 * so 7-35 and 45-95 are both ordinary. All that can be checked is that they
 * are ordered and that the step is a real step, and the fallbacks are Home
 * Assistant's own Celsius defaults, which is what the integration would have
 * sent had the entity reported nothing. */
static void read_temperature_bounds(JsonObject *object, PanelEntity *entity)
{
    gdouble value = 0.0;

    entity->min_temp = json_object_number(object, "min_temp", &value)
                           ? value
                           : 7.0;
    entity->max_temp = json_object_number(object, "max_temp", &value)
                           ? value
                           : 35.0;
    if (entity->max_temp <= entity->min_temp) {
        entity->min_temp = 7.0;
        entity->max_temp = 35.0;
    }
    entity->temp_step =
        json_object_number(object, "target_temp_step", &value) && value > 0.0
            ? value
            : 0.5;
}

/* The domain is repeated in the payload so that a client can pick a card
 * without parsing the entity ID. It is trusted when present and derived from
 * the entity ID when it is not, which is what a payload from an integration
 * that predates the field looks like. */
static gchar *read_domain(JsonObject *object, const gchar *entity_id)
{
    const gchar *domain = json_object_string(object, "domain", NULL);
    if (domain != NULL && *domain != '\0')
        return g_strdup(domain);

    const gchar *separator = strchr(entity_id, '.');
    return separator != NULL
               ? g_strndup(entity_id, (gsize)(separator - entity_id))
               : g_strdup("");
}

/* An element with no entity, or with no rid, is skipped rather than drawn:
 * the rid is what a card on this tablet is keyed on, so an element without
 * one could never be placed on the grid in the first place. */
static PanelEntity *read_entity(JsonObject *object)
{
    const gchar *entity_id = json_object_string(object, "entity", NULL);
    const gchar *rid = json_object_string(object, "rid", NULL);

    if (entity_id == NULL || *entity_id == '\0')
        return NULL;
    if (rid == NULL || *rid == '\0')
        return NULL;

    gdouble value = 0.0;
    PanelEntity *entity = g_new0(PanelEntity, 1);

    entity->rid = g_strdup(rid);
    entity->entity = g_strdup(entity_id);
    entity->name = g_strdup(json_object_string(object, "name", entity_id));
    entity->domain = read_domain(object, entity_id);
    read_controls(json_optional_array(object, "controls"), entity);
    entity->min_kelvin = json_object_number(object, "min_kelvin", &value)
                             ? clamp_kelvin(value, 2000)
                             : 2000;
    entity->max_kelvin = json_object_number(object, "max_kelvin", &value)
                             ? clamp_kelvin(value, 6500)
                             : 6500;
    if (entity->max_kelvin <= entity->min_kelvin) {
        entity->min_kelvin = 2000;
        entity->max_kelvin = 6500;
    }
    read_temperature_bounds(object, entity);
    return entity;
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

    /* The select Home Assistant holds this panel's skin in. Absent means the
     * integration offered none, and the panel simply has no local skin
     * picker to show. */
    const gchar *skin_select = json_object_string(attributes, "skin_select",
                                                  NULL);
    if (skin_select != NULL && *skin_select != '\0')
        parsed.skin_select_entity = g_strdup(skin_select);

    /* The integration sends its own ceiling. A payload naming none, or naming
     * an unreasonable one, is trusted only as far as this build's own. */
    gdouble limit = 0.0;
    guint entity_limit = PANEL_ENTITY_LIMIT;
    if (json_object_number(attributes, "entity_limit", &limit) && limit > 0.0)
        entity_limit = (guint)MIN(limit, (gdouble)PANEL_ENTITY_LIMIT);

    /* Only a panel is sent this block, and a panel is sent no `slots` at all.
     * A payload carrying neither is not an error: it is a panel with no room
     * controls configured yet, and the grid draws itself empty. */
    parsed.entities = g_ptr_array_new_with_free_func(
        (GDestroyNotify)panel_entity_free);
    JsonArray *entities = json_optional_array(attributes, "entities");
    guint length = entities != NULL ? json_array_get_length(entities) : 0;
    for (guint i = 0; i < length && parsed.entities->len < entity_limit; i++) {
        JsonNode *node = json_array_get_element(entities, i);
        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node))
            continue;
        PanelEntity *entity = read_entity(json_node_get_object(node));
        if (entity != NULL)
            g_ptr_array_add(parsed.entities, entity);
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

    /* A document of nothing but whitespace parses without error and leaves no
     * root at all, so the node is checked for existence before its type. A
     * truncated cache file looks exactly like that. */
    if (!json_parser_load_from_data(parser, data, length, &error) ||
        json_parser_get_root(parser) == NULL ||
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
