#include "application.h"

#include "app_config.h"
#include "home_assistant_client.h"
#include "json_helpers.h"
#include "panel_config.h"
#include "panel_display.h"
#include "panel_pairing.h"
#include "panel_ui.h"
#include "panel_cards.h"
#include "panel_web.h"
#include "system_status.h"

#include <json-glib/json-glib.h>

#include <math.h>

#define APPLICATION_ID "com.vahac.T560MusicPanel"

/* Home Assistant restarting answers with a refused connection, not a refused
 * token, so a handful of rejections in a row really does mean the token is
 * gone rather than that the server is busy. */
#define UNAUTHORIZED_POLL_LIMIT 3

/* The battery and the backlight are read this often. Both are two small
 * sysfs reads, so the cost is in the report that may follow, not here. */
#define STATUS_INTERVAL_SECONDS 5
/* Home Assistant is told again after this long even when nothing changed, so
 * that a panel which is simply idle does not look absent. */
#define STATUS_HEARTBEAT_SECONDS 60

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
    guint pairing_source;
    gchar *pairing_code;
    gchar *pairing_message;
    guint clock_source;
    guint status_source;
    guint config_reload_source;
    GFileMonitor *config_monitor;
    gint64 clock_minute;
    guint poll_pending;
    guint unauthorized_polls;
    gint64 next_playlist_poll_us;
    /* Where the round-robin over the room cards reached. See
     * poll_room_cards. */
    guint room_poll_cursor;
    /* Whether a forecast request is still in flight. One at a time: the
     * forecast moves slowly and every weather card converges within a few
     * poll cycles of starting anyway. */
    gboolean forecast_pending;
    /* The layout editor this panel serves, or NULL when it is switched off
     * in config.ini or its port could not be bound. The room page works
     * either way; only the editing does not. */
    PanelWeb *web;
    /* The card artwork: the catalog Home Assistant publishes and the
     * pictures downloaded from it, held for the editor to serve. Neither is
     * ever fetched more often than it changes — the catalog moves when the
     * integration is upgraded, and a picture never does. */
    PanelCards *cards;
    gint64 next_catalog_poll_us;
    gboolean catalog_pending;
    gboolean icon_pending;
    /* The last payload written to the layout cache. It is compared before
     * every write: the config sensor is polled every cycle, and rewriting an
     * unchanged file once a second would wear the tablet's flash and would
     * keep waking the button handler that watches its timestamp. */
    GBytes *config_cache;
    /* The moment of the newest command of each kind this panel has acted on.
     * A command is applied only when it is newer, which is what makes the
     * poll a safe transport for one. */
    gint64 applied_display_at;
    gint64 applied_brightness_at;
    gint64 applied_restart_at;
    gint64 applied_page_at;
    gboolean commands_adopted;
    /* What was last reported to Home Assistant, and when. */
    BatteryStatus battery;
    DisplayStatus display;
    gint64 next_status_report_us;
    /* The page the person is looking at. Home Assistant both reads it and
     * sets it, so it is kept here rather than asked of the widget tree. It
     * always points into PANEL_PAGES below, never into a parsed payload,
     * which is freed as soon as it has been applied. */
    const gchar *current_page;
    gint64 started_at_us;
    gint queue_selected;
    gint playlist_selected;
    PanelUiStatus poll_status;
    gchar *poll_message;
    gboolean player_playing;
    gboolean shuffle_state;
    gboolean restarting;
} PanelApplication;

typedef struct {
    PanelApplication *application;
    gchar *url;
} AlbumArtRequest;

typedef enum {
    POLL_REQUEST_CONFIG,
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
static void start_panel(PanelApplication *application);

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

/* The pages the panel can be sent to, and the header each one carries. The
 * navigation buttons hold the same pairs; this table is what lets a page
 * arrive from Home Assistant, where no button was pressed. */
static const struct {
    const gchar *page;
    const gchar *title;
} PANEL_PAGES[] = {
    {"player", "NOW PLAYING"},
    {"queue", "QUEUE"},
    {"playlists", "PLAYLISTS"},
    {"room", "ROOM CONTROLS"},
};

/* Returns this build's own name for a page, so that what is remembered
 * outlives the payload the name arrived in. NULL for a page this build does
 * not have. */
static const gchar *canonical_page(const gchar *page)
{
    for (gsize i = 0; i < G_N_ELEMENTS(PANEL_PAGES); i++) {
        if (g_strcmp0(PANEL_PAGES[i].page, page) == 0)
            return PANEL_PAGES[i].page;
    }
    return NULL;
}

static const gchar *page_title(const gchar *page)
{
    for (gsize i = 0; i < G_N_ELEMENTS(PANEL_PAGES); i++) {
        if (g_strcmp0(PANEL_PAGES[i].page, page) == 0)
            return PANEL_PAGES[i].title;
    }
    return NULL;
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

/* The registry element behind one card on the room page.
 *
 * The interface owns the arrangement, so it owns the mapping from a card
 * position to the element that card acts on. A card whose rid the registry no
 * longer carries answers NULL and every action on it is dropped. */
static const PanelEntity *configured_room(PanelApplication *application,
                                          gint index)
{
    if (index < 0 || application->ui == NULL)
        return NULL;
    return panel_ui_card_entity(application->ui, (guint)index);
}

/* The same payload as room_value_json, for a value that is not a whole
 * number: a thermostat step of half a degree is ordinary. json-glib writes a
 * JSON number without consulting the locale, so a tablet whose locale writes
 * decimal commas still sends a decimal point. */
static gchar *room_double_json(const gchar *entity, const gchar *key,
                               gdouble value)
{
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "entity_id");
    json_builder_add_string_value(builder, entity);
    json_builder_set_member_name(builder, key);
    json_builder_add_double_value(builder, value);
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
    json_builder_add_string_value(builder, application->config->layout.player_entity);
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
    json_builder_add_string_value(builder, application->config->layout.player_entity);
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
                            application->config->layout.player_entity);
        break;
    case PANEL_UI_TOGGLE_SHUFFLE: {
        application->shuffle_state = !application->shuffle_state;
        panel_ui_set_modes(application->ui, application->shuffle_state,
                           application->repeat_state);
        gchar *json = service_json(application->config->layout.player_entity,
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
        gchar *json = service_json(application->config->layout.player_entity,
                                   "repeat", next, -1);
        call_service(application, "media_player", "repeat_set", json);
        g_free(json);
        break;
    }
    case PANEL_UI_TOGGLE_ROOM: {
        const PanelEntity *room = configured_room(application, index);
        /* Only where Home Assistant said the element can be turned off and
         * on. Every light and switch can; a thermostat with no `off` mode
         * cannot, and calling the service anyway would be a request Home
         * Assistant refuses and a user who is told nothing about it. */
        if (room != NULL && room->togglable) {
            call_entity_service(application, "homeassistant", "toggle",
                                room->entity);
        }
        break;
    }
    case PANEL_UI_SET_ROOM_BRIGHTNESS: {
        const PanelEntity *room = configured_room(application, index);
        if (room != NULL && value != NULL && room->brightness) {
            gint brightness = (gint)g_ascii_strtoll(value, NULL, 10);
            brightness = CLAMP(brightness, 1, 100);
            gchar *json = room_value_json(room->entity, "brightness_pct",
                                          brightness);
            call_service(application, "light", "turn_on", json);
            g_free(json);
        }
        break;
    }
    case PANEL_UI_SET_ROOM_POSITION: {
        const PanelEntity *room = configured_room(application, index);
        if (room != NULL && value != NULL && room->position) {
            gint position = (gint)g_ascii_strtoll(value, NULL, 10);
            position = CLAMP(position, 0, 100);
            gchar *json = room_value_json(room->entity, "position", position);
            call_service(application, "cover", "set_cover_position", json);
            g_free(json);
        }
        break;
    }
    case PANEL_UI_STOP_ROOM: {
        const PanelEntity *room = configured_room(application, index);
        /* Only where Home Assistant said the cover can be stopped. A cover
         * without the feature would refuse the call, and the person pressing
         * a button that answers nothing would be told nothing. */
        if (room != NULL && room->stoppable) {
            call_entity_service(application, "cover", "stop_cover",
                                room->entity);
        }
        break;
    }
    case PANEL_UI_SET_ROOM_COLOR_TEMPERATURE: {
        const PanelEntity *room = configured_room(application, index);
        if (room != NULL && value != NULL && room->color_temperature) {
            gint temperature = (gint)g_ascii_strtoll(value, NULL, 10);
            temperature = CLAMP(temperature, room->min_kelvin,
                                room->max_kelvin);
            gchar *json = room_value_json(room->entity, "color_temp_kelvin",
                                          temperature);
            call_service(application, "light", "turn_on", json);
            g_free(json);
        }
        break;
    }
    case PANEL_UI_SET_ROOM_TARGET_TEMPERATURE: {
        const PanelEntity *room = configured_room(application, index);
        /* Clamped again here rather than trusted from the interface: the
         * bounds are the registry's, and this is the last place before a
         * value reaches Home Assistant. */
        if (room != NULL && value != NULL && room->target_temperature) {
            gdouble setpoint = g_ascii_strtod(value, NULL);
            setpoint = CLAMP(setpoint, room->min_temp, room->max_temp);
            gchar *json = room_double_json(room->entity, "temperature",
                                           setpoint);
            call_service(application, "climate", "set_temperature", json);
            g_free(json);
        }
        break;
    }
    case PANEL_UI_SHOW_PAGE: {
        const gchar *page = canonical_page(value);
        if (page != NULL)
            application->current_page = page;
        /* Home Assistant shows which page the panel is on, so a tap on the
         * tablet is worth telling it about at once. */
        application->next_status_report_us = 0;
        if (g_str_equal(value, "queue"))
            call_service(application, "media_controller", "refresh", "{}");
        break;
    }
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

/* The larger of the two sizes the skins want, so one decode serves both. */
#define PANEL_ALBUM_ART_DECODE 530

static void album_art_finished(guint status_code, GBytes *body,
                               const GError *error, gpointer user_data)
{
    AlbumArtRequest *request = user_data;
    PanelApplication *application = request->application;

    if (error == NULL && body != NULL && status_code == 200 &&
        g_strcmp0(request->url, application->album_art_url) == 0) {
        GError *decode_error = NULL;
        GInputStream *stream = g_memory_input_stream_new_from_bytes(body);
        /* One decode serves both skins: the modern artwork card scales down
         * to 510 and the cassette label crops out of this, so neither ever
         * enlarges the picture. The interface resizes it once, on arrival. */
        GdkPixbuf *pixbuf = gdk_pixbuf_new_from_stream_at_scale(
            stream, PANEL_ALBUM_ART_DECODE, PANEL_ALBUM_ART_DECODE, TRUE,
            NULL, &decode_error);
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

/* Whether a card should read as on.
 *
 * A light and a switch say "on" and everything else is off. A thermostat does
 * not: its state is the mode it is in — heat, cool, auto, dry, fan_only — and
 * every one of them but "off" is a thermostat that is running. Anything the
 * panel cannot recognise is left alone rather than guessed at, which is what
 * `state_known` is for; here an unavailable entity is simply not on. */
static gboolean room_is_active(const PanelEntity *entity, const gchar *state)
{
    /* A weather block and a sensor block are readings rather than
     * controls: they are never on, so they never draw the active gradient
     * a button does. */
    if (entity != NULL && (g_strcmp0(entity->domain, "weather") == 0 ||
                           g_strcmp0(entity->domain, "sensor") == 0)) {
        return FALSE;
    }
    /* A blind is on when it is not shut. Home Assistant reports `open`,
     * `closed`, `opening` and `closing`; one that is opening is on its way to
     * being open and is drawn as on, and one that is closing is still open
     * until it is not, which is why only `closed` reads as off. */
    if (entity != NULL && g_strcmp0(entity->domain, "cover") == 0) {
        return g_str_equal(state, "open") || g_str_equal(state, "opening") ||
               g_str_equal(state, "closing");
    }
    if (entity != NULL && g_strcmp0(entity->domain, "climate") == 0) {
        return !g_str_equal(state, "off") &&
               !g_str_equal(state, "unavailable") &&
               !g_str_equal(state, "unknown") && *state != '\0';
    }
    return g_str_equal(state, "on");
}

/* One card's state, out of one `/api/states/<entity_id>` document.
 *
 * A thermostat costs no extra request: `current_temperature` and
 * `temperature` are attributes of the same document the card was already
 * polled with, so a page of thermostats polls exactly as a page of lamps
 * does. */
static void update_room(PanelApplication *application, guint index,
                        JsonObject *state)
{
    if (state == NULL)
        return;
    JsonObject *attributes = json_state_attributes(state);
    const PanelEntity *entity = configured_room(application, (gint)index);
    const gchar *raw_state = json_object_string(state, "state", "");
    gboolean is_weather = entity != NULL &&
                          g_strcmp0(entity->domain, "weather") == 0;
    gboolean is_sensor = entity != NULL &&
                         g_strcmp0(entity->domain, "sensor") == 0;
    PanelRoomState reported = {
        .active = room_is_active(entity, raw_state),
        .brightness_percent = -1,
        .color_temp_kelvin = -1,
        .min_color_temp_kelvin = 0,
        .max_color_temp_kelvin = 0,
        .setpoint = NAN,
        .ambient = NAN,
        .position = -1,
        .weather_condition = NULL,
        .weather_temperature = NAN,
        .weather_humidity = -1,
        .sensor_value = NULL,
        .sensor_unit = NULL
    };
    gdouble value = 0.0;

    /* A weather block costs no extra request either: the condition is the
     * state itself and the temperature and humidity are attributes of the
     * same document the card was already polled with. */
    if (is_weather) {
        if (!g_str_equal(raw_state, "unavailable") &&
            !g_str_equal(raw_state, "unknown") && *raw_state != '\0')
            reported.weather_condition = raw_state;
        if (json_object_number(attributes, "temperature", &value))
            reported.weather_temperature = value;
        if (json_object_number(attributes, "humidity", &value) &&
            value >= 0.0)
            reported.weather_humidity = CLAMP((gint)(value + 0.5), 0, 100);
    }

    /* A sensor block costs no extra request either: the value is the state
     * itself and the unit is the `unit_of_measurement` attribute of the
     * same document the card was already polled with. */
    if (is_sensor) {
        if (!g_str_equal(raw_state, "unavailable") &&
            !g_str_equal(raw_state, "unknown") && *raw_state != '\0')
            reported.sensor_value = raw_state;
        reported.sensor_unit =
            json_object_string(attributes, "unit_of_measurement", NULL);
    }

    if (json_object_number(attributes, "brightness", &value) && value >= 0.0) {
        reported.brightness_percent =
            CLAMP((gint)(value * 100.0 / 255.0 + 0.5), 1, 100);
    }
    if (json_object_number(attributes, "color_temp_kelvin", &value) &&
        value > 0.0) {
        reported.color_temp_kelvin = (gint)(value + 0.5);
    }
    if (json_object_number(attributes, "min_color_temp_kelvin", &value) &&
        value > 0.0)
        reported.min_color_temp_kelvin = (gint)(value + 0.5);
    if (json_object_number(attributes, "max_color_temp_kelvin", &value) &&
        value > 0.0)
        reported.max_color_temp_kelvin = (gint)(value + 0.5);
    /* No sanity range: the payload carries no unit, so a plausible
     * temperature in one house is an implausible one in another. */
    if (json_object_number(attributes, "temperature", &value))
        reported.setpoint = value;
    if (json_object_number(attributes, "current_temperature", &value))
        reported.ambient = value;
    /* A cover costs no extra request either: `current_position` is an
     * attribute of the document the card was already polled with. A cover
     * that cannot report one simply leaves this at -1. */
    if (json_object_number(attributes, "current_position", &value) &&
        value >= 0.0)
        reported.position = CLAMP((gint)(value + 0.5), 0, 100);

    panel_ui_set_room(application->ui, index, &reported);
}

/* Quitting takes effect on the next main loop iteration, so the request is
 * made once even if another poll cycle finishes first. The watchdog brings
 * the panel back within about two seconds. */
static void request_restart(PanelApplication *application,
                            const gchar *reason)
{
    if (application->restarting)
        return;

    application->restarting = TRUE;
    if (application->ui != NULL)
        panel_ui_set_status(application->ui, reason, PANEL_UI_STATUS_CONNECTED);
    g_application_quit(G_APPLICATION(application->gtk_application));
}

/* Settings are a desired configuration rather than an event, so the newest
 * payload simply wins and no timestamp is involved. The poll timer is the
 * only one that has to be rebuilt; the playlist interval is read on the next
 * cycle, and screen_off_seconds is applied by t560-power-button.py, which
 * reads it out of the layout cache written below. */
static void apply_settings(PanelApplication *application,
                           const PanelSettings *settings)
{
    if (!settings->present)
        return;

    application->config->playlist_poll_interval_ms =
        settings->playlist_poll_interval_ms;

    /* The skin is applied while the panel runs. Both layouts already exist
     * and both are kept up to date, so this is a stack switch and a repaint,
     * not a rebuild; before the interface exists it is only recorded, and
     * panel_ui_new reads it back. An absent skin leaves the config.ini
     * fallback alone. */
    if (settings->player_skin_present) {
        application->config->player_skin = settings->player_skin;
        if (application->ui != NULL)
            panel_ui_set_skin(application->ui, settings->player_skin);
    }

    if (settings->poll_interval_ms == application->config->poll_interval_ms)
        return;

    application->config->poll_interval_ms = settings->poll_interval_ms;
    if (application->poll_source != 0) {
        g_source_remove(application->poll_source);
        application->poll_source = g_timeout_add(settings->poll_interval_ms,
                                                 poll_states, application);
    }
}

/* Records every command as applied without acting on any of them.
 *
 * This runs for the first payload of each start. A command issued while the
 * panel was down has already been overtaken by events — the display state is
 * whatever the tablet is showing now, and a restart that has happened must
 * not happen again on every boot — so the panel adopts the moments and waits
 * for the next real one. */
static void adopt_commands(PanelApplication *application,
                           const PanelCommands *commands)
{
    application->applied_display_at = commands->display_at;
    application->applied_brightness_at = commands->brightness_at;
    application->applied_restart_at = commands->restart_at;
    application->applied_page_at = commands->page_at;
    application->commands_adopted = TRUE;
}

static void apply_commands(PanelApplication *application,
                           const PanelCommands *commands)
{
    if (!application->commands_adopted) {
        adopt_commands(application, commands);
        return;
    }

    if (commands->brightness_at > application->applied_brightness_at) {
        application->applied_brightness_at = commands->brightness_at;
        if (commands->brightness > 0)
            panel_display_request_brightness(commands->brightness);
    }

    if (commands->display_at > application->applied_display_at) {
        application->applied_display_at = commands->display_at;
        panel_display_request_state(
            g_strcmp0(commands->display_state, "on") == 0);
        /* Report as soon as the handler has had time to act, so that the
         * switch in Home Assistant stops showing what was asked for and
         * starts showing what happened. */
        application->next_status_report_us = 0;
    }

    if (commands->page_at > application->applied_page_at) {
        application->applied_page_at = commands->page_at;
        /* A page this build does not have is ignored rather than guessed at:
         * showing the wrong one would be worse than showing none. */
        const gchar *page = canonical_page(commands->page);
        if (page != NULL && application->ui != NULL) {
            application->current_page = page;
            panel_ui_show_page(application->ui, page, page_title(page));
            application->next_status_report_us = 0;
        }
    }

    if (commands->restart_at > application->applied_restart_at) {
        application->applied_restart_at = commands->restart_at;
        request_restart(application, "Restarting");
    }
}

/* The layout is applied once, at start-up. A later change restarts the panel
 * the same way a config.ini change does, and the fresh layout is read from
 * the cache. Settings and commands are not part of the layout revision and
 * are applied while the panel keeps running.
 *
 * The cache is written before anything is applied, because one of the
 * commands is a restart: the payload that asked for it has to be on disk
 * before the panel quits, or the panel would read the same request again on
 * every boot and never come up. */
static void update_config(PanelApplication *application, JsonObject *state,
                          GBytes *body)
{
    PanelLayout candidate = {0};
    gchar *failure = NULL;

    if (!panel_config_parse_state(state, &candidate, &failure)) {
        note_poll_status(application, PANEL_UI_STATUS_WARNING, failure);
        return;
    }

    /* The panel's half of the version check; the integration performs the
     * other half on the report this panel sends it. Home Assistant answered,
     * so this is a configuration warning and never a lost connection: the
     * server is there, but it speaks an older contract, and part of what this
     * build expects from the payload will simply never arrive. Reported every
     * cycle, because the poll cycle owns the icon and starts each one clean.
     * A payload that names no version at all reads as 0, which is what every
     * integration built before the field existed sends. */
    if (candidate.contract_version < T560_PANEL_CONTRACT_VERSION) {
        note_poll_status(
            application, PANEL_UI_STATUS_WARNING,
            g_strdup_printf("Home Assistant speaks contract %d and this panel "
                            "needs %d: update Media Controller",
                            candidate.contract_version,
                            T560_PANEL_CONTRACT_VERSION));
    }

    /* Only a payload the panel accepted is cached; an unusable one must not
     * become the layout of the next boot. */
    if (application->config_cache == NULL ||
        !g_bytes_equal(application->config_cache, body)) {
        gsize length = 0;
        const gchar *data = g_bytes_get_data(body, &length);

        if (data != NULL) {
            panel_config_store_cache(data, length);
            g_clear_pointer(&application->config_cache, g_bytes_unref);
            application->config_cache = g_bytes_ref(body);
        }
    }

    if (application->ui == NULL) {
        adopt_commands(application, &candidate.commands);
        panel_layout_clear(&application->config->layout);
        application->config->layout = candidate;
        apply_settings(application, &application->config->layout.settings);
        start_panel(application);
        return;
    }

    if (candidate.revision != application->config->layout.revision) {
        panel_layout_clear(&candidate);
        request_restart(application, "Configuration changed");
        return;
    }

    /* Adopted on every payload rather than only on the first one.
     *
     * Which entity holds the skin is deliberately outside the revision — it
     * is not layout, and folding it in would restart every panel in the house
     * whenever Home Assistant assigned it. The cost of that choice is this:
     * a payload that gains the key later must be picked up here, or a panel
     * that happened to poll while Home Assistant was still starting its
     * platforms would never learn the entity and could never write a skin. */
    if (g_strcmp0(application->config->layout.skin_select_entity,
                  candidate.skin_select_entity) != 0) {
        g_free(application->config->layout.skin_select_entity);
        application->config->layout.skin_select_entity =
            g_strdup(candidate.skin_select_entity);
    }

    apply_settings(application, &candidate.settings);
    apply_commands(application, &candidate.commands);
    panel_layout_clear(&candidate);
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
    case POLL_REQUEST_CONFIG:
        /* Handled in state_finished, which still owns the raw body the cache
         * is written from. */
        break;
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
        /* The token was revoked in Home Assistant, or expired. Nothing the
         * panel can do will work again, so it drops the token and restarts
         * into pairing, where Home Assistant offers to issue a new one. A few
         * cycles are allowed first, so that a momentary refusal does not
         * throw away a working token. */
        application->unauthorized_polls++;
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("Home Assistant refused the token "
                                         "(HTTP %u)", status_code));
        if (application->unauthorized_polls >= UNAUTHORIZED_POLL_LIMIT &&
            !application->restarting) {
            application->restarting = TRUE;
            g_warning("Home Assistant rejected the token; pairing again");
            panel_pairing_forget_token();
            g_application_quit(G_APPLICATION(application->gtk_application));
        }
    } else if (status_code != 200 || body == NULL) {
        note_poll_status(application, PANEL_UI_STATUS_WARNING,
                         g_strdup_printf("%s: Home Assistant HTTP %u",
                                         request->entity, status_code));
    } else {
        application->unauthorized_polls = 0;
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
            if (request->kind == POLL_REQUEST_CONFIG) {
                JsonObject *state =
                    json_node_get_object(json_parser_get_root(parser));
                update_config(application, state, body);
            } else {
                update_state(application, request->kind, request->index,
                             parser);
            }
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

/* Requests the state of the entities the room page is showing.
 *
 * The six-tile page asked for all six every cycle, and at six that is what
 * this still does. A registry of a hundred is the case that changes: a
 * hundred single-entity requests a second is not something an ARMv7 tablet
 * and the network between it and Home Assistant should be asked to carry, and
 * nothing on screen changes fast enough to need it. So a bounded number of
 * cards are refreshed per cycle, round robin, and a page of a hundred cards
 * comes fully round in about twelve seconds while a page of a handful behaves
 * exactly as it always did. */
#define PANEL_ROOM_POLL_BATCH 8

static void poll_room_cards(PanelApplication *application)
{
    guint count = application->ui != NULL
                      ? panel_ui_card_count(application->ui)
                      : 0;
    guint batch;

    if (count == 0)
        return;
    batch = MIN(count, (guint)PANEL_ROOM_POLL_BATCH);
    for (guint i = 0; i < batch; i++) {
        guint index = (application->room_poll_cursor + i) % count;
        const PanelEntity *entity = panel_ui_card_entity(application->ui,
                                                         index);

        /* A card whose registry element has gone names no entity to ask
         * about. It keeps its place on the page and simply has no state. */
        if (entity == NULL)
            continue;
        start_state_request(application, entity->entity, POLL_REQUEST_ROOM,
                            index);
    }
    application->room_poll_cursor = (application->room_poll_cursor + batch) %
                                    count;
}

/* The daily forecast behind a weather block. Slow-moving data: each weather
 * entity is asked at most every forty-five minutes, through the ordinary
 * service channel and naming that entity alone — never the full state list
 * AGENTS.md forbids. */
#define PANEL_FORECAST_INTERVAL_US ((gint64)45 * 60 * G_USEC_PER_SEC)

typedef struct {
    PanelApplication *application;
    guint index;
    gchar *entity;
} ForecastRequest;

/* The "forecast" array for one entity in a get_forecasts answer. The answer
 * wraps it per entity — under "service_response" when ?return_response was
 * asked for — so the entity a request named is looked up by name rather
 * than taking the first array found: a stale "forecast" attribute on some
 * other member must never read as the forecast. */
static JsonArray *find_forecast_array(JsonObject *object, const gchar *entity)
{
    JsonObject *wrapping = json_optional_object(object, "service_response");
    JsonArray *found = NULL;

    if (wrapping != NULL) {
        JsonObject *named = json_optional_object(wrapping, entity);
        if (named != NULL)
            found = json_optional_array(named, "forecast");
    }
    if (found == NULL) {
        JsonObject *named = json_optional_object(object, entity);
        if (named != NULL)
            found = json_optional_array(named, "forecast");
    }
    if (found == NULL) {
        GList *members = json_object_get_members(object);

        for (GList *item = members; item != NULL && found == NULL;
             item = item->next) {
            JsonNode *node = json_object_get_member(object, item->data);
            if (node == NULL)
                continue;
            if (JSON_NODE_HOLDS_ARRAY(node) &&
                g_strcmp0(item->data, "forecast") == 0) {
                found = json_node_get_array(node);
            } else if (JSON_NODE_HOLDS_OBJECT(node)) {
                found = find_forecast_array(json_node_get_object(node),
                                            entity);
            }
        }
        g_list_free(members);
    }
    return found;
}

/* The coming days out of one forecast answer. The first entry is today,
 * which the card already shows as its current reading, so the rows start
 * with the day after it — as many as there are data and room for. */
static guint collect_forecast_days(JsonObject *root, const gchar *entity,
                                     PanelWeatherDay *days)
{
    JsonArray *forecast = find_forecast_array(root, entity);
    guint count = 0;

    if (forecast == NULL)
        return 0;
    for (guint i = 1, length = json_array_get_length(forecast);
         i < length && count < PANEL_WEATHER_FORECAST_MAX; i++) {
        JsonNode *node = json_array_get_element(forecast, i);
        JsonObject *item;
        const gchar *datetime;
        gdouble high = 0.0;
        gdouble low = 0.0;
        GDateTime *when;
        gchar *day;

        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node))
            continue;
        item = json_node_get_object(node);
        datetime = json_object_string(item, "datetime", NULL);
        if (datetime == NULL ||
            !json_object_number(item, "temperature", &high))
            continue;
        when = g_date_time_new_from_iso8601(datetime, NULL);
        if (when == NULL)
            continue;
        day = g_date_time_format(when, "%a");
        g_date_time_unref(when);
        if (day == NULL)
            continue;
        g_strlcpy(days[count].day, day, sizeof(days[count].day));
        g_free(day);
        days[count].high = high;
        if (json_object_number(item, "templow", &low)) {
            days[count].low = low;
            days[count].has_low = TRUE;
        } else {
            days[count].low = 0.0;
            days[count].has_low = FALSE;
        }
        g_strlcpy(days[count].condition,
                  json_object_string(item, "condition", ""),
                  sizeof(days[count].condition));
        if (json_object_number(item, "precipitation", &low) && low > 0.0) {
            days[count].precipitation = low;
            days[count].has_precipitation = TRUE;
        } else {
            days[count].precipitation = 0.0;
            days[count].has_precipitation = FALSE;
        }
        count++;
    }
    return count;
}

static void forecast_finished(guint status_code, GBytes *body,
                              const GError *error, gpointer user_data)
{
    ForecastRequest *request = user_data;
    PanelApplication *application = request->application;

    application->forecast_pending = FALSE;
    /* A rebuild in between may have moved the cards: only the card that
     * still names this entity may keep the answer — or the backoff below,
     * which stops a failing entity from being asked again every second. */
    if (application->ui != NULL) {
        const PanelEntity *entity =
            panel_ui_card_entity(application->ui, request->index);

        if (entity != NULL && g_strcmp0(entity->entity, request->entity) == 0) {
            if (error == NULL && status_code == 200 && body != NULL) {
                gsize length = 0;
                const gchar *data = g_bytes_get_data(body, &length);
                JsonParser *parser = json_parser_new();
                gboolean parsed =
                    json_parser_load_from_data(parser, data, (gssize)length,
                                               NULL) &&
                    JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser));

                if (parsed) {
                    PanelWeatherDay days[PANEL_WEATHER_FORECAST_MAX];
                    guint count = collect_forecast_days(
                        json_node_get_object(json_parser_get_root(parser)),
                        request->entity, days);

                    if (count > 0) {
                        panel_ui_set_room_forecast(application->ui,
                                                   request->index, days,
                                                   count);
                    } else {
                        g_warning("No daily forecast for %s in the answer",
                                  request->entity);
                        panel_ui_touch_room_forecast(application->ui,
                                                     request->index);
                    }
                } else {
                    g_warning("Unreadable forecast answer for %s",
                              request->entity);
                    panel_ui_touch_room_forecast(application->ui,
                                                 request->index);
                }
                g_object_unref(parser);
            } else {
                gchar *reason =
                    error != NULL
                        ? g_strdup(error->message)
                        : g_strdup_printf("Home Assistant HTTP %u",
                                          status_code);
                g_warning("Forecast request for %s failed: %s",
                          request->entity, reason);
                g_free(reason);
                panel_ui_touch_room_forecast(application->ui, request->index);
            }
        }
    }
    g_free(request->entity);
    g_free(request);
}

/* One weather entity per poll cycle, and only one whose forecast is older
 * than the interval above. A page of weather blocks still converges within
 * minutes of starting, and a house with one asks one small question every
 * forty-five minutes. */
static void maybe_poll_forecast(PanelApplication *application, gint64 now)
{
    guint count;

    if (application->forecast_pending || application->ui == NULL)
        return;
    count = panel_ui_card_count(application->ui);
    for (guint i = 0; i < count; i++) {
        const PanelEntity *entity = panel_ui_card_entity(application->ui, i);
        gchar *json;
        ForecastRequest *request;

        if (entity == NULL || g_strcmp0(entity->domain, "weather") != 0)
            continue;
        if (panel_ui_room_forecast_at(application->ui, i) != 0 &&
            now - panel_ui_room_forecast_at(application->ui, i) <
                PANEL_FORECAST_INTERVAL_US)
            continue;
        /* Entity IDs name [a-z0-9_.] and nothing that needs escaping. */
        json = g_strdup_printf("{\"entity_id\":\"%s\",\"type\":\"daily\"}",
                               entity->entity);
        request = g_new0(ForecastRequest, 1);
        request->application = application;
        request->index = i;
        request->entity = g_strdup(entity->entity);
        /* With the response asked for: without ?return_response Home
         * Assistant answers a bare empty list. */
        if (home_assistant_client_call_service_response(
                application->client, "weather", "get_forecasts", json,
                forecast_finished, request)) {
            application->forecast_pending = TRUE;
        } else {
            g_free(request->entity);
            g_free(request);
        }
        g_free(json);
        return;
    }
}

/* ------------------------------------------------------- layout editor */

/* Where Home Assistant keeps this panel's copy of its own arrangement. It is
 * an endpoint of its own rather than a block on the config sensor: the config
 * sensor is polled every second, and a layout is read twice in the life of a
 * panel. See the panel layout endpoint in docs/CONTRACT.md. */
/* ------------------------------------------------------------- card art */

/* How often the catalog is asked for. It changes when the Media Controller
 * integration is upgraded and never otherwise, so anything oftener would be a
 * request spent on an answer that is always the same. It is deliberately not
 * a block on the config sensor for the same reason the layout backup is not:
 * that payload is polled about once a second. */
#define PANEL_CATALOG_INTERVAL_US ((gint64)6 * 60 * 60 * G_USEC_PER_SEC)

static void catalog_finished(guint status_code, GBytes *body,
                             const GError *error, gpointer user_data)
{
    PanelApplication *application = user_data;
    gsize length = 0;
    const gchar *data = body != NULL ? g_bytes_get_data(body, &length) : NULL;

    application->catalog_pending = FALSE;
    if (error != NULL || status_code < 200 || status_code >= 300 ||
        data == NULL) {
        /* Not reported anywhere a person looks: an unreachable Home
         * Assistant is already visible on the status line, and every card
         * keeps the artwork this build carries. */
        g_debug("The icon catalog could not be read");
        return;
    }
    panel_cards_set_catalog(application->cards, data, (gssize)length);
}

typedef struct {
    PanelApplication *application;
    gchar *icon;
} IconRequest;

static void icon_request_free(gpointer user_data)
{
    IconRequest *request = user_data;

    if (request == NULL)
        return;
    g_free(request->icon);
    g_free(request);
}

static void icon_finished(guint status_code, GBytes *body,
                          const GError *error, gpointer user_data)
{
    IconRequest *request = user_data;
    PanelApplication *application = request->application;

    application->icon_pending = FALSE;
    if (error != NULL || status_code < 200 || status_code >= 300 ||
        body == NULL || g_bytes_get_size(body) == 0) {
        /* Recorded as a miss so that it is left alone for a while instead of
         * asked for on every tick. The editor drops the image and keeps the
         * name, and every card keeps the artwork this build carries. */
        panel_cards_mark_missing(application->cards, request->icon);
        return;
    }
    panel_cards_store_image(application->cards, request->icon, body);
}

/* One picture at a time, and only what the catalog says exists. Each is a
 * couple of kilobytes and they are spread over the poll rather than fetched
 * in a burst, because the GTK main loop on this tablet is a release
 * requirement and a burst of downloads is exactly what it must not do. */
static void maybe_fetch_card_art(PanelApplication *application, gint64 now)
{
    if (application->client == NULL)
        return;

    if (!application->catalog_pending &&
        (application->next_catalog_poll_us == 0 ||
         now >= application->next_catalog_poll_us)) {
        application->next_catalog_poll_us = now + PANEL_CATALOG_INTERVAL_US;
        application->catalog_pending = home_assistant_client_get_path(
            application->client, "/api/media_controller/icons",
            catalog_finished, application, NULL);
    }

    if (application->icon_pending)
        return;

    const gchar *wanted = panel_cards_next_wanted(application->cards);
    if (wanted == NULL)
        return;

    /* The identifier is the catalog's, already checked against the shape the
     * integration publishes and found in the list it published. Nothing a
     * caller typed reaches this line. */
    gchar *path = g_strdup_printf("/api/media_controller/icon/%s/png",
                                  wanted);
    IconRequest *request = g_new0(IconRequest, 1);
    request->application = application;
    request->icon = g_strdup(wanted);
    application->icon_pending = home_assistant_client_get_path(
        application->client, path, icon_finished, request,
        icon_request_free);
    if (!application->icon_pending)
        icon_request_free(request);
    g_free(path);
}

static gchar *layout_backup_path(PanelApplication *application)
{
    gchar *escaped = g_uri_escape_string(application->config->panel_id, NULL,
                                         TRUE);
    gchar *path = g_strdup_printf("/api/media_controller/panel_layout/%s",
                                  escaped);

    g_free(escaped);
    return path;
}

static void backup_finished(guint status_code, GBytes *body,
                            const GError *error, gpointer user_data)
{
    (void)body;
    (void)user_data;

    /* A failed backup is logged and not shown: the layout is already saved on
     * the panel, and the copy is retried by the next save. */
    if (error != NULL) {
        g_warning("Could not send the layout to Home Assistant: %s",
                  error->message);
    } else if (status_code < 200 || status_code >= 300) {
        g_warning("Home Assistant refused the layout copy with status %u",
                  status_code);
    }
}

static gboolean send_layout_backup(PanelApplication *application,
                                   const PanelGrid *grid)
{
    gchar *path = layout_backup_path(application);
    gchar *json = panel_grid_to_json(grid);
    /* Opaque on the far side: Home Assistant stores these bytes and hands
     * them back without ever parsing them, so they are not announced as
     * JSON. */
    gboolean sent = home_assistant_client_put_path(
        application->client, path, json, "text/plain", backup_finished,
        NULL, NULL);

    g_free(json);
    g_free(path);
    return sent;
}

static const PanelLayout *editor_layout(gpointer user_data)
{
    PanelApplication *application = user_data;
    return &application->config->layout;
}

/* The skin on screen, which is not the same question as what Home Assistant
 * last said. `layout.settings` holds the first payload this panel ever read
 * and is not refreshed, because settings are applied as they arrive rather
 * than stored; the live answer is the one the interface was given. */
static PanelPlayerSkin editor_skin(gpointer user_data)
{
    PanelApplication *application = user_data;
    return application->config->player_skin;
}

static const PanelGrid *editor_grid(gpointer user_data)
{
    PanelApplication *application = user_data;
    return application->ui != NULL ? panel_ui_grid(application->ui) : NULL;
}

/* Writes the file, puts the arrangement on screen, and sends Home Assistant
 * its copy. The order matters: the panel's own file is the thing that must
 * survive, so it is written first and a Home Assistant that is unreachable
 * costs the backup and nothing else. */
static gboolean editor_save_grid(PanelGrid *grid, gboolean *backed_up,
                                 gchar **error_message, gpointer user_data)
{
    PanelApplication *application = user_data;

    if (!panel_grid_save(grid, error_message))
        return FALSE;

    *backed_up = send_layout_backup(application, grid);
    /* The interface takes ownership. The room page is one drawing area, so
     * this is a new card list and a redraw rather than a rebuilt widget
     * tree — and the poll cursor starts again so the new cards get states. */
    panel_ui_set_grid(application->ui, grid);
    application->room_poll_cursor = 0;
    return TRUE;
}

typedef struct {
    PanelWebRestoreReady ready;
    gpointer request;
} RestoreCall;

static void restore_finished(guint status_code, GBytes *body,
                             const GError *error, gpointer user_data)
{
    RestoreCall *call = user_data;
    gsize length = 0;
    const gchar *data = body != NULL ? g_bytes_get_data(body, &length) : NULL;

    if (error != NULL) {
        call->ready(NULL, error->message, call->request);
    } else if (status_code == 404) {
        call->ready(NULL, "Home Assistant holds no copy of this layout yet.",
                    call->request);
    } else if (status_code < 200 || status_code >= 300) {
        gchar *text = g_strdup_printf(
            "Home Assistant answered %u.", status_code);
        call->ready(NULL, text, call->request);
        g_free(text);
    } else if (data == NULL || length == 0) {
        call->ready(NULL, "The copy in Home Assistant is empty.",
                    call->request);
    } else {
        gchar *document = g_strndup(data, length);
        call->ready(document, NULL, call->request);
        g_free(document);
    }
}

static void restore_call_free(gpointer user_data)
{
    g_free(user_data);
}

static void editor_restore(PanelWebRestoreReady ready, gpointer request,
                           gpointer user_data)
{
    PanelApplication *application = user_data;
    RestoreCall *call = g_new0(RestoreCall, 1);
    gchar *path = layout_backup_path(application);

    call->ready = ready;
    call->request = request;
    if (!home_assistant_client_get_path(application->client, path,
                                        restore_finished, call,
                                        restore_call_free)) {
        ready(NULL, "The Home Assistant URL is not usable.", request);
        g_free(call);
    }
    g_free(path);
}

/* Calls select.select_option on this panel's own skin select and nothing
 * else. The skin is not stored locally: Home Assistant owns the value and the
 * panel adopts it on its next poll, which is the same path as changing it in
 * Home Assistant itself. */
static gboolean editor_select_skin(const gchar *name, gchar **error_message,
                                   gpointer user_data)
{
    PanelApplication *application = user_data;
    const gchar *entity = application->config->layout.skin_select_entity;

    if (entity == NULL) {
        *error_message = g_strdup(
            "Home Assistant has not told this panel which entity holds the "
            "skin.");
        return FALSE;
    }

    gchar *json = service_json(entity, "option", name, -1);
    gboolean called = home_assistant_client_call_service(
        application->client, "select", "select_option", json,
        service_finished, application);

    g_free(json);
    if (!called)
        *error_message = g_strdup("The Home Assistant URL is not usable.");
    return called;
}

static PanelCards *editor_cards(gpointer user_data)
{
    PanelApplication *application = user_data;
    return application->cards;
}

static void card_write_finished(guint status_code, GBytes *body,
                                const GError *error, gpointer user_data)
{
    PanelApplication *application = user_data;

    (void)body;
    if (error != NULL) {
        panel_cards_write_finished(application->cards, FALSE,
                                   "Home Assistant could not be reached.");
        return;
    }
    if (status_code < 200 || status_code >= 300) {
        gchar *text = g_strdup_printf(
            "Home Assistant refused the change (HTTP %u).", status_code);
        panel_cards_write_finished(application->cards, FALSE, text);
        g_free(text);
        return;
    }
    /* The new name and icon arrive back the ordinary way, in the next config
     * poll, because Home Assistant owns the registry and this panel only
     * asked. Nothing is written locally, so there is nothing to redraw
     * here. */
    panel_cards_write_finished(application->cards, TRUE, "");
}

/* Asks Home Assistant to store the display name and the icon of one registry
 * element, and nothing else. The rid is one this panel is already drawing —
 * panel_web checked before calling — the name has already been through
 * panel_card_name_normalize, and the icon is one the published catalog
 * carries. The integration checks all three again, because it is the side
 * that owns the registry.
 *
 * A NULL argument means "leave that one alone", and it is left out of the
 * body rather than sent empty: an empty name means "use the Home Assistant
 * entity's own name", so the two could not share a spelling. */
static gboolean editor_write_card(const gchar *rid, const gchar *name,
                                  const gchar *icon, gchar **error_message,
                                  gpointer user_data)
{
    PanelApplication *application = user_data;

    if (application->config->panel_id == NULL ||
        *application->config->panel_id == '\0') {
        *error_message = g_strdup(
            "This panel is not paired with Home Assistant, so the change "
            "was not saved.");
        return FALSE;
    }

    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "rid");
    json_builder_add_string_value(builder, rid);
    if (name != NULL) {
        json_builder_set_member_name(builder, "name");
        json_builder_add_string_value(builder, name);
    }
    if (icon != NULL) {
        json_builder_set_member_name(builder, "icon");
        json_builder_add_string_value(builder, icon);
    }
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    gchar *escaped = g_uri_escape_string(application->config->panel_id, NULL,
                                         TRUE);
    gchar *path = g_strdup_printf("/api/media_controller/panel_card/%s",
                                  escaped);

    panel_cards_write_started(application->cards);
    gboolean sent = home_assistant_client_post_path(
        application->client, path, json, card_write_finished, application,
        NULL);

    g_free(path);
    g_free(escaped);
    g_free(json);
    g_object_unref(builder);

    if (!sent) {
        panel_cards_write_finished(application->cards, FALSE,
                                   "The Home Assistant URL is not usable.");
        *error_message = g_strdup("The Home Assistant URL is not usable.");
    }
    return sent;
}

static void start_editor(PanelApplication *application)
{
    static const PanelWebCallbacks CALLBACKS = {
        .layout = editor_layout,
        .skin = editor_skin,
        .grid = editor_grid,
        .save_grid = editor_save_grid,
        .restore = editor_restore,
        .select_skin = editor_select_skin,
        .cards = editor_cards,
        .write_card = editor_write_card
    };
    gchar *failure = NULL;

    if (application->web != NULL || application->config->web_port == 0)
        return;

    application->web = panel_web_new(application->config->web_port,
                                     &CALLBACKS, application, &failure);
    if (application->web == NULL) {
        /* Not fatal, and deliberately not shown on the status line: the room
         * page is fully usable without an editor, and a warning that never
         * clears would sit over the music. */
        g_warning("The layout editor is not available: %s", failure);
        g_free(failure);
        return;
    }
    panel_ui_set_editor_url(application->ui, panel_web_url(application->web));
    g_message("The layout editor is at %s", panel_web_url(application->web));
}

static gboolean poll_states(gpointer user_data)
{
    PanelApplication *application = user_data;
    if (application->poll_pending != 0)
        return G_SOURCE_CONTINUE;

    application->poll_status = PANEL_UI_STATUS_CONNECTED;
    g_clear_pointer(&application->poll_message, g_free);
    gint64 now = g_get_monotonic_time();

    /* The layout names every other entity, so it is requested first. It is
     * also the channel Home Assistant asks this panel to turn its display off
     * or to restart through, which is why it is requested every cycle rather
     * than as rarely as the layout alone would need: a button in Home
     * Assistant that took a minute to do anything would read as broken. The
     * payload is small and the response is cached, not stored, unless it
     * actually changed. */
    start_state_request(application, application->config->config_entity,
                        POLL_REQUEST_CONFIG, 0);
    if (application->config->layout.player_entity == NULL) {
        /* Nothing else can be requested until the layout arrives. */
        if (application->poll_pending == 0)
            apply_poll_status(application);
        return G_SOURCE_CONTINUE;
    }

    start_state_request(application, application->config->layout.player_entity,
                        POLL_REQUEST_PLAYER, 0);
    start_state_request(application, application->config->layout.queue_entity,
                        POLL_REQUEST_QUEUE, 0);
    if (application->next_playlist_poll_us == 0 ||
        now >= application->next_playlist_poll_us) {
        start_state_request(application,
                            application->config->layout.playlists_entity,
                            POLL_REQUEST_PLAYLISTS, 0);
        application->next_playlist_poll_us =
            now + (gint64)application->config->playlist_poll_interval_ms * 1000;
    }
    poll_room_cards(application);
    maybe_poll_forecast(application, now);
    maybe_fetch_card_art(application, now);

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

/* Home Assistant cannot ask a tablet anything, so the battery and the
 * backlight are pushed. The report is deliberately small and infrequent: it
 * carries no media state, which Home Assistant already has. */
static void report_status(PanelApplication *application)
{
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "panel_id");
    json_builder_add_string_value(builder, application->config->panel_id);
    json_builder_set_member_name(builder, "version");
    json_builder_add_string_value(builder, T560_PANEL_VERSION);
    /* The release number above says when this build shipped; this says what
     * it understands. It is what lets Home Assistant notice that a tablet is
     * running a build older than the contract the integration speaks. */
    json_builder_set_member_name(builder, "contract_version");
    json_builder_add_int_value(builder, T560_PANEL_CONTRACT_VERSION);
    /* Where this panel's own layout editor answers, so that Home Assistant
     * can offer it on the panel's device page: the address is on the tablet
     * and nowhere else, because the port is a local setting and the routable
     * interface is the tablet's to know. A panel whose editor is switched
     * off has no address, sends nothing, and the link disappears. */
    const gchar *editor_url = panel_web_url(application->web);
    if (editor_url != NULL) {
        json_builder_set_member_name(builder, "editor_url");
        json_builder_add_string_value(builder, editor_url);
    }
    json_builder_set_member_name(builder, "page");
    json_builder_add_string_value(builder, application->current_page);
    json_builder_set_member_name(builder, "uptime_seconds");
    json_builder_add_int_value(
        builder,
        (g_get_monotonic_time() - application->started_at_us) /
            G_USEC_PER_SEC);

    /* Read here rather than on every tick: neither is worth a report of its
     * own, and both ride along with whatever report is being sent. */
    SystemDiagnostics diagnostics;
    system_status_read_diagnostics(&diagnostics);
    if (diagnostics.wifi_available) {
        json_builder_set_member_name(builder, "wifi_dbm");
        json_builder_add_int_value(builder, diagnostics.wifi_dbm);
    }
    if (diagnostics.temperature_available) {
        json_builder_set_member_name(builder, "temperature_c");
        json_builder_add_double_value(builder, diagnostics.temperature_c);
    }

    json_builder_set_member_name(builder, "battery");
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "available");
    json_builder_add_boolean_value(builder, application->battery.available);
    json_builder_set_member_name(builder, "percent");
    json_builder_add_int_value(builder, application->battery.percent);
    json_builder_set_member_name(builder, "charging");
    json_builder_add_boolean_value(builder, application->battery.charging);
    json_builder_end_object(builder);

    json_builder_set_member_name(builder, "display");
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "available");
    json_builder_add_boolean_value(builder, application->display.available);
    json_builder_set_member_name(builder, "on");
    json_builder_add_boolean_value(builder, application->display.on);
    json_builder_set_member_name(builder, "brightness");
    json_builder_add_int_value(builder, application->display.brightness);
    json_builder_end_object(builder);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    g_object_unref(builder);

    /* Nothing depends on the answer: a refused or lost report is simply sent
     * again on the next tick, and the entities go unavailable meanwhile. */
    home_assistant_client_post_path(application->client,
                                    "/api/media_controller/panel_status",
                                    json, NULL, NULL, NULL);
    g_free(json);
    application->next_status_report_us =
        g_get_monotonic_time() +
        (gint64)STATUS_HEARTBEAT_SECONDS * G_USEC_PER_SEC;
}

static gboolean status_differs(const BatteryStatus *battery,
                               const DisplayStatus *display,
                               const BatteryStatus *previous_battery,
                               const DisplayStatus *previous_display)
{
    return battery->available != previous_battery->available ||
           battery->percent != previous_battery->percent ||
           battery->charging != previous_battery->charging ||
           display->available != previous_display->available ||
           display->on != previous_display->on ||
           display->brightness != previous_display->brightness;
}

static gboolean update_status(gpointer user_data)
{
    PanelApplication *application = user_data;
    BatteryStatus battery;
    DisplayStatus display;

    system_status_read_battery(&battery);
    panel_display_read(&display);
    panel_ui_set_battery(application->ui, battery.available, battery.percent,
                         battery.charging);

    gboolean changed = status_differs(&battery, &display,
                                      &application->battery,
                                      &application->display);
    application->battery = battery;
    application->display = display;

    if (application->config->token == NULL)
        return G_SOURCE_CONTINUE;
    if (changed || g_get_monotonic_time() >= application->next_status_report_us)
        report_status(application);
    return G_SOURCE_CONTINUE;
}

static void start_header_updates(PanelApplication *application)
{
    application->clock_minute = -1;
    update_clock(application);
    /* Impossible values, so that the first read always counts as a change
     * and Home Assistant hears from the panel as soon as it is up. */
    application->battery.percent = -1;
    application->display.brightness = -2;
    update_status(application);
    application->clock_source = g_timeout_add_seconds(1, update_clock,
                                                      application);
    application->status_source = g_timeout_add_seconds(
        STATUS_INTERVAL_SECONDS, update_status, application);
}

static PanelApplication *panel_application_new(void)
{
    PanelApplication *application = g_new0(PanelApplication, 1);
    application->started_at_us = g_get_monotonic_time();
    application->current_page = PANEL_PAGES[0].page;
    application->queue_selected = -1;
    application->playlist_selected = -1;
    application->repeat_state = g_strdup("off");
    application->queue_titles = g_ptr_array_new_with_free_func(g_free);
    application->queue_artists = g_ptr_array_new_with_free_func(g_free);
    application->queue_ids = g_ptr_array_new_with_free_func(g_free);
    application->playlist_names = g_ptr_array_new_with_free_func(g_free);
    application->playlist_uris = g_ptr_array_new_with_free_func(g_free);
    application->cards = panel_cards_new();
    return application;
}

static void panel_application_free(PanelApplication *application)
{
    if (application->poll_source != 0)
        g_source_remove(application->poll_source);
    if (application->pairing_source != 0)
        g_source_remove(application->pairing_source);
    if (application->clock_source != 0)
        g_source_remove(application->clock_source);
    if (application->status_source != 0)
        g_source_remove(application->status_source);
    if (application->config_reload_source != 0)
        g_source_remove(application->config_reload_source);
    g_clear_object(&application->config_monitor);
    /* Before the interface: a request in flight calls back into it. */
    panel_web_free(application->web);
    home_assistant_client_free(application->client);
    /* After the client: a download in flight writes into it. */
    panel_cards_free(application->cards);
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
    g_clear_pointer(&application->config_cache, g_bytes_unref);
    g_free(application->poll_message);
    g_free(application->pairing_code);
    g_free(application->pairing_message);
    g_free(application);
}

/* Replaces whatever the window currently shows. The panel starts on a
 * placeholder when no layout has been cached yet. */
static void set_window_content(PanelApplication *application,
                               GtkWidget *content)
{
    GtkWidget *previous = gtk_bin_get_child(GTK_BIN(application->window));

    if (previous != NULL)
        gtk_container_remove(GTK_CONTAINER(application->window), previous);
    gtk_container_add(GTK_CONTAINER(application->window), content);
    gtk_widget_show_all(application->window);
}

/* ---------------------------------------------------------------- pairing
 *
 * A panel with no token asks Home Assistant for one. The person reads the
 * code off this screen and types it in Home Assistant; nothing is typed on
 * the tablet, and no token travels over SSH. */

static void show_pairing(PanelApplication *application, const gchar *message)
{
    if (g_strcmp0(application->pairing_message, message) == 0)
        return;

    g_free(application->pairing_message);
    application->pairing_message = g_strdup(message);
    set_window_content(
        application,
        panel_ui_build_pairing(application->pairing_code, message));
}

static void pairing_finished(guint status_code, GBytes *body,
                             const GError *error, gpointer user_data)
{
    PanelApplication *application = user_data;

    if (error != NULL) {
        show_pairing(application,
                     "Waiting for Home Assistant to answer.");
        return;
    }
    if (status_code == 404) {
        show_pairing(application,
                     "This panel is not in Home Assistant yet.\n"
                     "Add it there, then enter this code.");
        return;
    }
    if (status_code == 202) {
        /* The code was accepted; the token follows once the rest of the form
         * in Home Assistant is finished. The panel keeps asking. */
        show_pairing(application,
                     "Code accepted.\n"
                     "Finish the setup in Home Assistant.");
        return;
    }
    if (status_code != 200 || body == NULL) {
        show_pairing(application,
                     "Enter this code in Home Assistant to finish pairing.");
        return;
    }

    JsonParser *parser = NULL;
    GError *parse_error = NULL;
    if (!parse_state(body, &parser, &parse_error)) {
        g_clear_error(&parse_error);
        show_pairing(application, "Home Assistant sent an unreadable reply.");
        return;
    }

    JsonObject *object = json_node_get_object(json_parser_get_root(parser));
    const gchar *token = json_object_string(object, "token", NULL);
    const gchar *config_entity = json_object_string(object, "config_entity",
                                                    NULL);
    gchar *failure = NULL;

    if (token == NULL || !panel_pairing_store_token(token, config_entity,
                                                    &failure)) {
        gchar *message = g_strdup_printf(
            "The token could not be stored:\n%s",
            failure != NULL ? failure : "no token in the reply");
        show_pairing(application, message);
        g_free(message);
        g_free(failure);
        g_object_unref(parser);
        return;
    }
    g_object_unref(parser);

    /* The watchdog restarts the panel, which now finds its token. */
    show_pairing(application, "Paired. Starting.");
    g_application_quit(G_APPLICATION(application->gtk_application));
}

static gboolean request_pairing(gpointer user_data)
{
    PanelApplication *application = user_data;
    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "panel_id");
    json_builder_add_string_value(builder, application->config->panel_id);
    json_builder_set_member_name(builder, "code");
    json_builder_add_string_value(builder, application->pairing_code);
    json_builder_end_object(builder);
    gchar *json = json_builder_to_string(builder);
    g_object_unref(builder);

    home_assistant_client_post_path(application->client,
                                    "/api/media_controller/provision", json,
                                    pairing_finished, application, NULL);
    g_free(json);
    return G_SOURCE_CONTINUE;
}

static void start_pairing(PanelApplication *application)
{
    application->pairing_code = panel_pairing_code();
    show_pairing(application,
                 "Enter this code in Home Assistant to finish pairing.");
    request_pairing(application);
    application->pairing_source = g_timeout_add_seconds(3, request_pairing,
                                                        application);
}

static void start_panel(PanelApplication *application)
{
    application->ui = panel_ui_new(application->config, handle_ui_event,
                                   application);
    set_window_content(application, panel_ui_build(application->ui));
    panel_ui_set_skin(application->ui, application->config->player_skin);
    start_header_updates(application);
    start_config_monitor(application);
    /* Last, because it needs the interface it hands its URL to. */
    start_editor(application);
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
    if (application->config == NULL) {
        set_window_content(application,
                           panel_ui_build_config_error(failure));
        g_free(failure);
        return;
    }

    application->client = home_assistant_client_new(
        application->config->base_url, application->config->token);

    /* Without a token the panel can do exactly one thing: ask for one. */
    if (application->config->token == NULL) {
        start_pairing(application);
        return;
    }

    /* The cached layout makes a normal start immediate and, more importantly,
     * makes the panel usable while Home Assistant is down. Only a tablet that
     * has never reached Home Assistant has to wait. */
    gchar *cache_failure = NULL;
    if (panel_config_load_cache(&application->config->layout,
                                &cache_failure)) {
        /* The cached payload carries the settings Home Assistant last sent,
         * so the panel starts at the right interval instead of running at the
         * config.ini fallback until the first poll answers. */
        apply_settings(application, &application->config->layout.settings);
        start_panel(application);
    } else {
        set_window_content(
            application,
            panel_ui_build_config_error(
                "Waiting for Home Assistant.\n\nThe panel reads its layout "
                "from the Media Controller integration."));
        g_debug("No cached layout: %s", cache_failure);
    }
    g_free(cache_failure);

    poll_states(application);
    application->poll_source = g_timeout_add(
        application->config->poll_interval_ms, poll_states, application);
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
