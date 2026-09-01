#include "application.h"

#include "app_config.h"
#include "home_assistant_client.h"
#include "json_helpers.h"
#include "panel_ui.h"
#include "system_status.h"

#include <json-glib/json-glib.h>

#define APPLICATION_ID "com.vahac.T560MusicPanel"

typedef struct {
    GtkApplication *gtk_application;
    GtkWidget *window;
    AppConfig *config;
    PanelUi *ui;
    HomeAssistantClient *client;
    GPtrArray *queue_titles;
    GPtrArray *queue_artists;
    GPtrArray *queue_ids;
    GPtrArray *playlist_names;
    GPtrArray *playlist_uris;
    gchar *album_art_url;
    gchar *repeat_state;
    gchar *queue_data;
    guint poll_source;
    guint clock_source;
    guint battery_source;
    guint config_reload_source;
    GFileMonitor *config_monitor;
    gint64 clock_minute;
    guint poll_pending;
    gint64 next_playlist_poll_us;
    gint queue_selected;
    gint playlist_selected;
    PanelUiStatus poll_status;
    gchar *poll_message;
    gboolean player_playing;
    gboolean shuffle_state;
} PanelApplication;

typedef struct {
    PanelApplication *application;
    gchar *url;
} AlbumArtRequest;

typedef enum {
    POLL_REQUEST_PLAYER,
    POLL_REQUEST_QUEUE,
    POLL_REQUEST_PLAYLISTS,
    POLL_REQUEST_ROOM
} PollRequestKind;

typedef struct {
    PanelApplication *application;
    PollRequestKind kind;
    guint index;
    /* Owned by AppConfig, which outlives every request it started. */
    const gchar *entity;
} PollRequest;

static gboolean poll_states(gpointer user_data);

/* A poll cycle fans out one request per configured entity, so the icon has to
 * describe the whole cycle. The worst state seen is remembered here and
 * applied once every request has finished, which stops a single rejected
 * entity from overwriting the state reported by the healthy ones.
 * Takes ownership of message. */
static void note_poll_status(PanelApplication *application,
                             PanelUiStatus status, gchar *message)
{
    if (status <= application->poll_status) {
        g_free(message);
        return;
    }
    application->poll_status = status;
    g_free(application->poll_message);
    application->poll_message = message;
}

static void apply_poll_status(PanelApplication *application)
{
    panel_ui_set_status(application->ui,
                        application->poll_message != NULL
                            ? application->poll_message
                            : "Connected",
                        application->poll_status);
}

static gboolean file_is_panel_config(GFile *file)
{
    if (file == NULL)
        return FALSE;
    gchar *basename = g_file_get_basename(file);
    gboolean matches = g_strcmp0(basename, "config.ini") == 0;
    g_free(basename);
    return matches;
}

static gboolean reload_config(gpointer user_data)
{
    PanelApplication *application = user_data;
    gchar *failure = NULL;
    AppConfig *updated = app_config_load(&failure);

    application->config_reload_source = 0;
    if (updated == NULL) {
        gchar *message = g_strdup_printf("Config reload failed: %s", failure);
        panel_ui_set_status(application->ui, message,
                            PANEL_UI_STATUS_WARNING);
        g_warning("%s", message);
        g_free(message);
        g_free(failure);
        return G_SOURCE_REMOVE;
    }

    app_config_free(updated);
    panel_ui_set_status(application->ui, "Applying configuration",
                        PANEL_UI_STATUS_CONNECTED);
    g_application_quit(G_APPLICATION(application->gtk_application));
    return G_SOURCE_REMOVE;
}

static void config_changed(GFileMonitor *monitor, GFile *file,
                           GFile *other_file, GFileMonitorEvent event,
                           gpointer user_data)
{
    (void)monitor;
    PanelApplication *application = user_data;
    gboolean complete = event == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT ||
                        event == G_FILE_MONITOR_EVENT_CREATED ||
                        event == G_FILE_MONITOR_EVENT_MOVED_IN ||
                        event == G_FILE_MONITOR_EVENT_RENAMED;

    if (!complete ||
        (!file_is_panel_config(file) &&
         !file_is_panel_config(other_file))) {
        return;
    }

    if (application->config_reload_source != 0)
        g_source_remove(application->config_reload_source);
    application->config_reload_source = g_timeout_add_full(
        G_PRIORITY_DEFAULT_IDLE, 400, reload_config, application, NULL);
}

static void start_config_monitor(PanelApplication *application)
{
    gchar *directory_path = app_config_directory_path();
    GFile *directory = g_file_new_for_path(directory_path);
    GError *error = NULL;

    application->config_monitor = g_file_monitor_directory(
        directory, G_FILE_MONITOR_WATCH_MOVES, NULL, &error);
    if (application->config_monitor != NULL) {
        g_signal_connect(application->config_monitor, "changed",
                         G_CALLBACK(config_changed), application);
    } else {
        g_warning("Could not monitor config.ini: %s", error->message);
        g_clear_error(&error);
    }

    g_object_unref(directory);
    g_free(directory_path);
}

static gchar *service_json(const gchar *entity, const gchar *key,
                           const gchar *string_value, gint boolean_value)
{
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entity_id");
    json_builder_add_string_value(builder, entity);
    if (key != NULL) {
        json_builder_set_member_name(builder, key);
        if (boolean_value >= 0)
            json_builder_add_boolean_value(builder, boolean_value != 0);
        else
            json_builder_add_string_value(
                builder, string_value != NULL ? string_value : "");
    }
    json_builder_end_object(builder);
    gchar *json = json_builder_to_string(builder);
    g_object_unref(builder);
    return json;
}

static gchar *room_value_json(const gchar *entity, const gchar *key,
                              gint value)
{
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entity_id");
    json_builder_add_string_value(builder, entity);
    json_builder_set_member_name(builder, key);
    json_builder_add_int_value(builder, value);
    json_builder_end_object(builder);
    gchar *json = json_builder_to_string(builder);
    g_object_unref(builder);
    return json;
}

static void service_finished(guint status_code, GBytes *body,
                             const GError *error, gpointer user_data)
{
    (void)body;
    PanelApplication *application = user_data;

    if (error != NULL) {
        gchar *message = g_strdup_printf("Command failed: %s", error->message);
        panel_ui_set_status(application->ui, message,
                            PANEL_UI_STATUS_OFFLINE);
        g_free(message);
    } else if (status_code < 200 || status_code >= 300) {
        /* Home Assistant answered, so the link is up. A refused command is a
         * wrong entity or service in config.ini, not a lost connection. */
        gchar *message = g_strdup_printf("Command rejected: HTTP %u",
                                         status_code);
        panel_ui_set_status(application->ui, message,
                            PANEL_UI_STATUS_WARNING);
        g_free(message);
    } else {
        /* The poll cycle owns the icon: it is the only place that knows
         * whether every configured entity still answers. */
        poll_states(application);
    }
}

static void call_service(PanelApplication *application, const gchar *domain,
                         const gchar *service, const gchar *json)
{
    if (!home_assistant_client_call_service(
            application->client, domain, service, json, service_finished,
            application)) {
        panel_ui_set_status(application->ui, "Invalid Home Assistant URL",
                            PANEL_UI_STATUS_OFFLINE);
    }
}

static void call_entity_service(PanelApplication *application,
                                const gchar *domain, const gchar *service,
                                const gchar *entity)
{
    gchar *json = service_json(entity, NULL, NULL, -1);
    call_service(application, domain, service, json);
    g_free(json);
}

static void play_selected_queue_item(PanelApplication *application)
{
    if (application->queue_selected < 0 ||
        (guint)application->queue_selected >= application->queue_ids->len)
        return;

    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entity_id");
    json_builder_add_string_value(builder, application->config->player_entity);
    json_builder_set_member_name(builder, "queue_item_id");
    json_builder_add_string_value(
        builder, g_ptr_array_index(application->queue_ids,
                                   application->queue_selected));
    json_builder_end_object(builder);
    gchar *json = json_builder_to_string(builder);
    call_service(application, "media_controller", "play_queue_item", json);
    g_free(json);
    g_object_unref(builder);
}

static void play_selected_playlist(PanelApplication *application)
{
    if (application->playlist_selected < 0 ||
        (guint)application->playlist_selected >= application->playlist_uris->len)
        return;

    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entity_id");
    json_builder_add_string_value(builder, application->config->player_entity);
    json_builder_set_member_name(builder, "media_id");
    json_builder_add_string_value(
        builder, g_ptr_array_index(application->playlist_uris,
                                   application->playlist_selected));
    json_builder_set_member_name(builder, "media_type");
    json_builder_add_string_value(builder, "playlist");
    json_builder_end_object(builder);
    gchar *json = json_builder_to_string(builder);
    call_service(application, "music_assistant", "play_media", json);
    g_free(json);
    g_object_unref(builder);
    panel_ui_show_page(application->ui, "player", "NOW PLAYING");
}

static void handle_ui_event(PanelUiEvent event, const gchar *value, gint index,
                            gpointer user_data)
{
    PanelApplication *application = user_data;

    switch (event) {
    case PANEL_UI_PLAYER_SERVICE:
        call_entity_service(application, "media_player", value,
                            application->config->player_entity);
        break;
    case PANEL_UI_TOGGLE_SHUFFLE: {
        application->shuffle_state = !application->shuffle_state;
        panel_ui_set_modes(application->ui, application->shuffle_state,
                           application->repeat_state);
        gchar *json = service_json(application->config->player_entity,
                                   "shuffle", NULL,
                                   application->shuffle_state);
        call_service(application, "media_player", "shuffle_set", json);
        g_free(json);
        break;
    }
    case PANEL_UI_CYCLE_REPEAT: {
        const gchar *next = g_str_equal(application->repeat_state, "off")
                                ? "all"
                            : g_str_equal(application->repeat_state, "all")
                                ? "one"
                                : "off";
        g_free(application->repeat_state);
        application->repeat_state = g_strdup(next);
        panel_ui_set_modes(application->ui, application->shuffle_state, next);
        gchar *json = service_json(application->config->player_entity,
                                   "repeat", next, -1);
        call_service(application, "media_player", "repeat_set", json);
        g_free(json);
        break;
    }
    case PANEL_UI_TOGGLE_ROOM:
        if (index >= 0 && index < PANEL_ROOM_COUNT &&
            application->config->room_entities[index] != NULL) {
            call_entity_service(application, "homeassistant", "toggle",
                                application->config->room_entities[index]);
        }
        break;
    case PANEL_UI_SET_ROOM_BRIGHTNESS:
        if (index >= 0 && index < PANEL_ROOM_COUNT && value != NULL &&
            application->config->room_entities[index] != NULL &&
            application->config->room_brightness[index]) {
            gint brightness = (gint)g_ascii_strtoll(value, NULL, 10);
            brightness = CLAMP(brightness, 1, 100);
            gchar *json = room_value_json(
                application->config->room_entities[index],
                "brightness_pct", brightness);
            call_service(application, "light", "turn_on", json);
            g_free(json);
        }
        break;
    case PANEL_UI_SET_ROOM_COLOR_TEMPERATURE:
        if (index >= 0 && index < PANEL_ROOM_COUNT && value != NULL &&
            application->config->room_entities[index] != NULL &&
            application->config->room_color_temperature[index]) {
            gint temperature = (gint)g_ascii_strtoll(value, NULL, 10);
            temperature = CLAMP(temperature, 1000, 10000);
            gchar *json = room_value_json(
                application->config->room_entities[index],
                "color_temp_kelvin", temperature);
            call_service(application, "light", "turn_on", json);
            g_free(json);
        }
        break;
    case PANEL_UI_SHOW_PAGE:
        if (g_str_equal(value, "queue"))
            call_service(application, "media_controller", "refresh", "{}");
        break;
    case PANEL_UI_SELECT_QUEUE_ITEM:
        application->queue_selected = index;
        break;
    case PANEL_UI_SELECT_PLAYLIST:
        application->playlist_selected = index;
        break;
    case PANEL_UI_PLAY_QUEUE_ITEM:
        play_selected_queue_item(application);
        break;
    case PANEL_UI_PLAY_PLAYLIST:
        play_selected_playlist(application);
        break;
    }
}

static void album_art_finished(guint status_code, GBytes *body,
                               const GError *error, gpointer user_data)
{
    AlbumArtRequest *request = user_data;
    PanelApplication *application = request->application;

    if (error == NULL && body != NULL && status_code == 200 &&
        g_strcmp0(request->url, application->album_art_url) == 0) {
        GError *decode_error = NULL;
        GInputStream *stream = g_memory_input_stream_new_from_bytes(body);
        GdkPixbuf *pixbuf = gdk_pixbuf_new_from_stream_at_scale(
            stream, 510, 510, TRUE, NULL, &decode_error);
        if (pixbuf != NULL) {
            panel_ui_set_album_art(application->ui, pixbuf);
            g_object_unref(pixbuf);
        }
        g_object_unref(stream);
        g_clear_error(&decode_error);
    }
}

static void album_art_request_free(gpointer user_data)
{
    AlbumArtRequest *request = user_data;
    g_free(request->url);
    g_free(request);
}

static void load_album_art(PanelApplication *application, const gchar *picture)
{
    if (picture == NULL || *picture == '\0')
        return;

    gchar *url = home_assistant_client_resolve_url(application->client, picture);
    if (g_strcmp0(url, application->album_art_url) == 0) {
        g_free(url);
        return;
    }
    g_free(application->album_art_url);
    application->album_art_url = url;

    AlbumArtRequest *request = g_new0(AlbumArtRequest, 1);
    request->application = application;
    request->url = g_strdup(url);
    if (!home_assistant_client_get_url(
            application->client, url, G_PRIORITY_LOW, album_art_finished,
            request, album_art_request_free))
        album_art_request_free(request);
}

static void update_player(PanelApplication *application, JsonObject *state)
{
    if (state == NULL)
        return;

    JsonObject *attributes = json_state_attributes(state);
    application->player_playing = g_str_equal(
        json_object_string(state, "state", ""), "playing");
    gdouble position = 0.0;
    gdouble duration = 0.0;
    gdouble volume = 0.0;
    json_object_number(attributes, "media_position", &position);
    json_object_number(attributes, "media_duration", &duration);
    json_object_number(attributes, "volume_level", &volume);

    const gchar *updated_at = json_object_string(
        attributes, "media_position_updated_at", NULL);
    if (application->player_playing && updated_at != NULL) {
        GDateTime *updated = g_date_time_new_from_iso8601(updated_at, NULL);
        GDateTime *now = g_date_time_new_now_utc();
        if (updated != NULL) {
            gint64 elapsed = g_date_time_difference(now, updated);
            if (elapsed > 0)
                position += (gdouble)elapsed / G_TIME_SPAN_SECOND;
            g_date_time_unref(updated);
        }
        g_date_time_unref(now);
    }

    application->shuffle_state = json_object_boolean(
        attributes, "shuffle", FALSE);
    const gchar *repeat = json_object_string(attributes, "repeat", "off");
    g_free(application->repeat_state);
    application->repeat_state = g_strdup(repeat);
    panel_ui_set_player(
        application->ui, application->player_playing,
        json_object_string(attributes, "media_title", "Nothing playing"),
        json_object_string(attributes, "media_artist", ""), position, duration,
        volume, application->shuffle_state, repeat);
    load_album_art(application,
                   json_object_string(attributes, "entity_picture", ""));
}

static void update_queue(PanelApplication *application, JsonObject *state)
{
    const gchar *data = json_object_string(
        json_state_attributes(state), "data", NULL);
    if (data == NULL || g_strcmp0(data, application->queue_data) == 0)
        return;

    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, data, -1, NULL) ||
        !JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser))) {
        g_object_unref(parser);
        return;
    }

    g_free(application->queue_data);
    application->queue_data = g_strdup(data);
    JsonObject *payload = json_node_get_object(json_parser_get_root(parser));
    json_copy_string_array(application->queue_titles,
                           json_optional_array(payload, "titles"));
    json_copy_string_array(application->queue_artists,
                           json_optional_array(payload, "artists"));
    json_copy_string_array(application->queue_ids,
                           json_optional_array(payload, "queue_ids"));
    guint count = MIN(application->queue_titles->len,
                      MIN(application->queue_artists->len,
                          application->queue_ids->len));
    application->queue_selected = json_object_has_member(payload, "current_index")
                                      ? (gint)json_object_get_int_member(
                                            payload, "current_index")
                                      : 0;
    panel_ui_set_queue(application->ui, application->queue_titles,
                       application->queue_artists, count,
                       application->queue_selected);
    g_object_unref(parser);
}

static void update_playlists(PanelApplication *application, JsonObject *state)
{
    JsonObject *attributes = json_state_attributes(state);
    JsonArray *names = json_optional_array(attributes, "names");
    JsonArray *uris = json_optional_array(attributes, "uris");
    if (json_string_array_matches(application->playlist_names, names) &&
        json_string_array_matches(application->playlist_uris, uris))
        return;

    json_copy_string_array(application->playlist_names, names);
    json_copy_string_array(application->playlist_uris, uris);
    guint count = MIN(application->playlist_names->len,
                      application->playlist_uris->len);
    if (application->playlist_selected < 0 ||
        (guint)application->playlist_selected >= count) {
        application->playlist_selected = count > 0 ? 0 : -1;
    }
    panel_ui_set_playlists(application->ui, application->playlist_names, count,
                           application->playlist_selected);
}

static void update_room(PanelApplication *application, guint index,
                        JsonObject *state)
{
    if (state == NULL)
        return;
    JsonObject *attributes = json_state_attributes(state);
    gboolean active = g_str_equal(
        json_object_string(state, "state", ""), "on");
    gdouble value = 0.0;
    gint brightness = -1;
    gint color_temperature = -1;
    gint min_color_temperature = 2000;
    gint max_color_temperature = 6500;

    if (json_object_number(attributes, "brightness", &value) && value >= 0.0)
        brightness = CLAMP((gint)(value * 100.0 / 255.0 + 0.5), 1, 100);
    if (json_object_number(attributes, "color_temp_kelvin", &value) &&
        value > 0.0) {
        color_temperature = (gint)(value + 0.5);
    } else if (json_object_number(attributes, "color_temp", &value) &&
               value > 0.0) {
        color_temperature = (gint)(1000000.0 / value + 0.5);
    }
    if (json_object_number(attributes, "min_color_temp_kelvin", &value) &&
        value > 0.0)
        min_color_temperature = (gint)(value + 0.5);
    if (json_object_number(attributes, "max_color_temp_kelvin", &value) &&
        value > 0.0)
        max_color_temperature = (gint)(value + 0.5);

    panel_ui_set_room(application->ui, index, active, brightness,
                      color_temperature, min_color_temperature,
                      max_color_temperature);
}

static void poll_request_free(gpointer user_data)
{
    g_free(user_data);
}

static void finish_poll_request(PanelApplication *application)
{
    g_assert(application->poll_pending > 0);
    application->poll_pending--;
    if (application->poll_pending == 0)
        apply_poll_status(application);
}

static gboolean parse_state(GBytes *body, JsonParser **parser,
                            GError **error)
{
    gsize length = 0;
    const gchar *data = g_bytes_get_data(body, &length);

    *parser = json_parser_new();
    if (!json_parser_load_from_data(*parser, data, (gssize)length, error) ||
        !JSON_NODE_HOLDS_OBJECT(json_parser_get_root(*parser))) {
        if (*error == NULL) {
            g_set_error_literal(error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                                "Home Assistant state is not a JSON object");
        }
        g_clear_object(parser);
        return FALSE;
    }
    return TRUE;
}

static void update_state(PanelApplication *application, PollRequestKind kind,
                         guint index, JsonParser *parser)
{
    JsonObject *state = json_node_get_object(json_parser_get_root(parser));

    switch (kind) {
    case POLL_REQUEST_PLAYER:
        update_player(application, state);
        break;
    case POLL_REQUEST_QUEUE:
        update_queue(application, state);
        break;
    case POLL_REQUEST_PLAYLISTS:
        update_playlists(application, state);
        break;
    case POLL_REQUEST_ROOM:
        update_room(application, index, state);
        break;
    }
}

static void parse_playlist_state_task(GTask *task, gpointer source_object,
                                      gpointer task_data,
                                      GCancellable *cancellable)
{
    (void)source_object;
    (void)cancellable;
    JsonParser *parser = NULL;
    GError *error = NULL;

    if (!parse_state((GBytes *)task_data, &parser, &error)) {
        g_task_return_error(task, error);
        return;
    }
    g_task_return_pointer(task, parser, g_object_unref);
}

static void playlist_state_parsed(GObject *source_object, GAsyncResult *result,
                                  gpointer user_data)
{
    (void)source_object;
    PollRequest *request = user_data;
    PanelApplication *application = request->application;
    GError *error = NULL;
    JsonParser *parser = g_task_propagate_pointer(G_TASK(result), &error);

    if (parser != NULL) {
        update_state(application, request->kind, request->index, parser);
        g_object_unref(parser);
    } else {
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("Unreadable state for %s",
                                         request->entity));
        g_clear_error(&error);
    }
    finish_poll_request(application);
    poll_request_free(request);
}

static void state_finished(guint status_code, GBytes *body,
                           const GError *error, gpointer user_data)
{
    PollRequest *request = user_data;
    PanelApplication *application = request->application;

    /* Only a transport failure means the panel could not reach Home
     * Assistant. Every HTTP reply, including the 404 sent for an entity ID
     * that does not exist, proves the connection works and must be reported
     * as a configuration warning instead. */
    if (error != NULL) {
        note_poll_status(application, PANEL_UI_STATUS_OFFLINE,
                         g_strdup_printf("Offline: %s", error->message));
    } else if (status_code == 404) {
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("Unknown entity %s: check config.ini",
                                         request->entity));
    } else if (status_code == 401 || status_code == 403) {
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("Home Assistant refused the token "
                                         "(HTTP %u): check config.ini",
                                         status_code));
    } else if (status_code != 200 || body == NULL) {
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("%s: Home Assistant HTTP %u",
                                         request->entity, status_code));
    } else {
        GError *parse_error = NULL;
        JsonParser *parser = NULL;

        if (request->kind == POLL_REQUEST_PLAYLISTS) {
            PollRequest *parse_request = g_new(PollRequest, 1);
            *parse_request = *request;
            GTask *task = g_task_new(NULL, NULL, playlist_state_parsed,
                                     parse_request);
            g_task_set_priority(task, G_PRIORITY_DEFAULT_IDLE);
            g_task_set_task_data(task, g_bytes_ref(body),
                                 (GDestroyNotify)g_bytes_unref);
            g_task_run_in_thread(task, parse_playlist_state_task);
            g_object_unref(task);
            return;
        }

        if (parse_state(body, &parser, &parse_error)) {
            update_state(application, request->kind, request->index, parser);
        } else {
            note_poll_status(application, PANEL_UI_STATUS_WARNING,
                             g_strdup_printf("Unreadable state for %s",
                                             request->entity));
        }
        g_clear_error(&parse_error);
        g_clear_object(&parser);
    }

    finish_poll_request(application);
}

static void start_state_request(PanelApplication *application,
                                const gchar *entity, PollRequestKind kind,
                                guint index)
{
    PollRequest *request = g_new0(PollRequest, 1);
    request->application = application;
    request->kind = kind;
    request->index = index;
    request->entity = entity;

    application->poll_pending++;
    if (!home_assistant_client_get_state(
            application->client, entity, state_finished, request,
            poll_request_free)) {
        application->poll_pending--;
        note_poll_status(application, PANEL_UI_STATUS_OFFLINE,
                         g_strdup("Invalid Home Assistant URL"));
        poll_request_free(request);
    }
}

static gboolean poll_states(gpointer user_data)
{
    PanelApplication *application = user_data;
    if (application->poll_pending != 0)
        return G_SOURCE_CONTINUE;

    application->poll_status = PANEL_UI_STATUS_CONNECTED;
    g_clear_pointer(&application->poll_message, g_free);
    start_state_request(application, application->config->player_entity,
                        POLL_REQUEST_PLAYER, 0);
    start_state_request(application, application->config->queue_entity,
                        POLL_REQUEST_QUEUE, 0);
    gint64 now = g_get_monotonic_time();
    if (application->next_playlist_poll_us == 0 ||
        now >= application->next_playlist_poll_us) {
        start_state_request(application, application->config->playlists_entity,
                            POLL_REQUEST_PLAYLISTS, 0);
        application->next_playlist_poll_us =
            now + (gint64)application->config->playlist_poll_interval_ms * 1000;
    }
    for (guint i = 0; i < PANEL_ROOM_COUNT; i++) {
        if (application->config->room_entities[i] != NULL) {
            start_state_request(application,
                                application->config->room_entities[i],
                                POLL_REQUEST_ROOM, i);
        }
    }

    /* Every request was rejected before it started, so no callback will run
     * to report the outcome. */
    if (application->poll_pending == 0)
        apply_poll_status(application);
    return G_SOURCE_CONTINUE;
}

/* The label is rewritten only when the displayed minute changes, so the
 * one-second tick costs a single clock read on the tablet. */
static gboolean update_clock(gpointer user_data)
{
    PanelApplication *application = user_data;
    gint64 minute = g_get_real_time() / (G_USEC_PER_SEC * 60);

    if (minute == application->clock_minute)
        return G_SOURCE_CONTINUE;

    application->clock_minute = minute;
    GDateTime *now = g_date_time_new_now_local();
    gchar *time_text = g_date_time_format(now, "%H:%M");
    gchar *date_text = g_date_time_format(now, "%a, %d %b");
    panel_ui_set_clock(application->ui, time_text, date_text);
    g_free(time_text);
    g_free(date_text);
    g_date_time_unref(now);
    return G_SOURCE_CONTINUE;
}

static gboolean update_battery(gpointer user_data)
{
    PanelApplication *application = user_data;
    BatteryStatus status;

    system_status_read_battery(&status);
    panel_ui_set_battery(application->ui, status.available, status.percent,
                         status.charging);
    return G_SOURCE_CONTINUE;
}

static void start_header_updates(PanelApplication *application)
{
    application->clock_minute = -1;
    update_clock(application);
    update_battery(application);
    application->clock_source = g_timeout_add_seconds(1, update_clock,
                                                      application);
    application->battery_source = g_timeout_add_seconds(10, update_battery,
                                                        application);
}

static PanelApplication *panel_application_new(void)
{
    PanelApplication *application = g_new0(PanelApplication, 1);
    application->queue_selected = -1;
    application->playlist_selected = -1;
    application->repeat_state = g_strdup("off");
    application->queue_titles = g_ptr_array_new_with_free_func(g_free);
    application->queue_artists = g_ptr_array_new_with_free_func(g_free);
    application->queue_ids = g_ptr_array_new_with_free_func(g_free);
    application->playlist_names = g_ptr_array_new_with_free_func(g_free);
    application->playlist_uris = g_ptr_array_new_with_free_func(g_free);
    return application;
}

static void panel_application_free(PanelApplication *application)
{
    if (application->poll_source != 0)
        g_source_remove(application->poll_source);
    if (application->clock_source != 0)
        g_source_remove(application->clock_source);
    if (application->battery_source != 0)
        g_source_remove(application->battery_source);
    if (application->config_reload_source != 0)
        g_source_remove(application->config_reload_source);
    g_clear_object(&application->config_monitor);
    home_assistant_client_free(application->client);
    panel_ui_free(application->ui);
    app_config_free(application->config);
    g_ptr_array_unref(application->queue_titles);
    g_ptr_array_unref(application->queue_artists);
    g_ptr_array_unref(application->queue_ids);
    g_ptr_array_unref(application->playlist_names);
    g_ptr_array_unref(application->playlist_uris);
    g_free(application->album_art_url);
    g_free(application->repeat_state);
    g_free(application->queue_data);
    g_free(application->poll_message);
    g_free(application);
}

static void activate(GtkApplication *gtk_application, gpointer user_data)
{
    PanelApplication *application = user_data;
    application->gtk_application = gtk_application;
    if (application->window != NULL) {
        gtk_window_present(GTK_WINDOW(application->window));
        return;
    }

    panel_ui_install_styles();
    application->window = gtk_application_window_new(gtk_application);
    gtk_window_set_title(GTK_WINDOW(application->window), "T560 Music Panel");
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    gtk_window_set_wmclass(GTK_WINDOW(application->window),
                           "t560-music-panel", "T560MusicPanel");
    G_GNUC_END_IGNORE_DEPRECATIONS
    gtk_window_set_default_size(GTK_WINDOW(application->window), 800, 1219);
    /* The panel owns the whole screen: no decorations and no window manager
     * panels above it. */
    gtk_window_set_decorated(GTK_WINDOW(application->window), FALSE);
    gtk_window_fullscreen(GTK_WINDOW(application->window));

    gchar *failure = NULL;
    application->config = app_config_load(&failure);
    GtkWidget *content = NULL;
    if (application->config == NULL) {
        content = panel_ui_build_config_error(failure);
        g_free(failure);
    } else {
        application->client = home_assistant_client_new(
            application->config->base_url, application->config->token);
        application->ui = panel_ui_new(application->config, handle_ui_event,
                                       application);
        content = panel_ui_build(application->ui);
        start_header_updates(application);
        start_config_monitor(application);
        poll_states(application);
        application->poll_source = g_timeout_add(
            application->config->poll_interval_ms, poll_states, application);
    }
    gtk_container_add(GTK_CONTAINER(application->window), content);
    gtk_widget_show_all(application->window);
}

int application_run(int argc, char **argv)
{
    g_set_prgname("t560-music-panel");
    g_set_application_name("T560 Music Panel");

    PanelApplication *application = panel_application_new();
    GtkApplication *gtk_application = gtk_application_new(
        APPLICATION_ID, G_APPLICATION_DEFAULT_FLAGS);
    g_signal_connect(gtk_application, "activate", G_CALLBACK(activate),
                     application);
    int result = g_application_run(G_APPLICATION(gtk_application), argc, argv);
    panel_application_free(application);
    g_object_unref(gtk_application);
    return result;
}
